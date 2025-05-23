from flask import Flask, request, jsonify, render_template, redirect, url_for, session, g
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from flask_caching import Cache
from flask_cors import CORS
from file_storage import FileStorage
from limits.storage import registry
import json
from datetime import datetime
import requests
from functools import wraps
import os
from dotenv import load_dotenv
import uuid

# Register the custom storage with the limits library
registry.register_storage(FileStorage, "file")

# Discord OAuth2 settings
load_dotenv()
CLIENT_ID = os.getenv('CLIENT_ID')
CLIENT_SECRET = os.getenv('CLIENT_SECRET')
REDIRECT_URI = 'http://localhost:5000/callback'

app = Flask(__name__)
app.secret_key = os.urandom(24)
os.environ['OAUTHLIB_INSECURE_TRANSPORT'] = '1'
CORS(app, supports_credentials=True)

# Caching to reduce load on server
cache = Cache(app, config={'CACHE_TYPE': 'simple'})

# Init Limiter with the registered file storage
limiter = Limiter(
    get_remote_address,
    app=app,
    default_limits=["200 per day", "50 per hour"],
    storage_uri="file://",  # Now properly registered
    storage_options={
        "file_path": "data/rate_limits/limiter.json"
    }
)
# Blacklist data
BANNED_USERS_FILE = "data/banned_users.json"
API_KEYS_FILE = "data/api_keys.json"
AUTHORIZED_USERS = [987323487343493191, 1088268266499231764, 726721909374320640, 710863981039845467, 1151136371164065904]
UNLIMITED_KEY_ROLES = [1201518458739892334]
PENDING_REQUESTS = []

def load_banned_users():
    try:
        with open(BANNED_USERS_FILE, "r") as f:
            return json.load(f)
    except FileNotFoundError:
        return {}

def save_banned_users(banned_users):
    with open(BANNED_USERS_FILE, "w") as f:
        json.dump(banned_users, f, indent=4)

def get_uuid(username):
    url = f'https://api.mojang.com/users/profiles/minecraft/{username}'
    response = requests.get(url)
    if response.status_code == 200:
        data = response.json()
        return data.get('id')
    return None

# Authentication Decorator
def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if session.get("discord_id") is None:
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated_function

# Authorization Decorator
def authorized_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if int(session.get("discord_id")) not in AUTHORIZED_USERS:
            return "Unauthorized", 403
        return f(*args, **kwargs)
    return decorated_function

# API Key Functions
def load_api_keys():
    try:
        with open(API_KEYS_FILE, "r") as f:
            data = json.load(f)
            return data.get("keys", [])
    except (FileNotFoundError, json.JSONDecodeError) as e:
        app.logger.warning(f"Error loading API keys: {str(e)}")
        return []

def save_api_keys(keys):  # Changed 'data' to 'keys' for clarity
    with open(API_KEYS_FILE, "w") as f:
        json.dump({"keys": keys}, f, indent=4)  # Ensure proper structure

def get_user_id_from_api_key(api_key):
    keys = load_api_keys()
    now = datetime.utcnow()
    for key_data in keys:
        if key_data["key"] == api_key:
            expiry_str = key_data.get("expiry")
            if expiry_str is None:
                return key_data["user_id"]
            try:
                expiry = datetime.fromisoformat(expiry_str)
                if expiry > now:
                    return key_data["user_id"]
            except ValueError:
                app.logger.error(f"Invalid expiry format in API key: {expiry_str}")
    return None

def api_key_required(f):
    @wraps(f)  # Preserve the original function's identity
    def decorated_function(*args, **kwargs):
        api_key = request.headers.get("X-API-Key")
        user_id = get_user_id_from_api_key(api_key)
        if user_id is None:
            return jsonify({"error": "Invalid or missing API key"}), 401
        g.user_id = user_id
        return f(*args, **kwargs)
    return decorated_function

def api_authorized_required(f):
    @wraps(f)  # Preserve the original function's identity
    def decorated_function(*args, **kwargs):
        if not hasattr(g, "user_id") or int(g.user_id) not in AUTHORIZED_USERS:
            return jsonify({"error": "Unauthorized"}), 403
        return f(*args, **kwargs)
    return decorated_function

# OAuth Routes
@app.route('/login')
def login():
    oauth2_url = f"https://discord.com/api/oauth2/authorize?client_id={CLIENT_ID}&redirect_uri={REDIRECT_URI}&response_type=code&scope=identify"
    return redirect(oauth2_url)

@app.route('/callback')
def callback():
    code = request.args.get('code')
    token_url = 'https://discord.com/api/oauth2/token'
    data = {
        'client_id': CLIENT_ID,
        'client_secret': CLIENT_SECRET,
        'grant_type': 'authorization_code',
        'code': code,
        'redirect_uri': REDIRECT_URI
    }
    headers = {'Content-Type': 'application/x-www-form-urlencoded'}
    response = requests.post(token_url, data=data, headers=headers)
    token_json = response.json()
    access_token = token_json.get('access_token')
    user_url = 'https://discord.com/api/users/@me'
    headers = {'Authorization': f'Bearer {access_token}'}
    user_response = requests.get(user_url, headers=headers)
    user_json = user_response.json()
    session["discord_id"] = user_json.get("id")
    session["discord_username"] = user_json.get("username")
    return redirect(url_for('blacklist_requests'))

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('index'))

# API Routes
@app.route("/api_keys", methods=["POST"])
@api_key_required
def create_api_key():
    try:
        data = request.json or {}
        user_id = data.get("user_id")
        roles = data.get("roles", [])  # Get the roles array from the request
        
        # Validation
        if not user_id:
            return jsonify({"error": "Missing user_id parameter"}), 400
            
        keys = load_api_keys()
        
        # Check if user already has a key and if they're allowed multiple keys
        has_unlimited_role = any(role_id in UNLIMITED_KEY_ROLES for role_id in roles)
        user_has_key = any(key_data["user_id"] == user_id for key_data in keys)
        
        if user_has_key and not has_unlimited_role:
            return jsonify({"error": "User already has an API key"}), 400
                
        new_key = str(uuid.uuid4())
        keys.append({
            "key": new_key,
            "user_id": user_id,
            "created_at": datetime.utcnow().isoformat(),
            "role_created": True if has_unlimited_role else False,  # Track if created by privileged role
            "expiry": None
        })
        
        save_api_keys(keys)
        app.logger.info(f"Created new API key for user: {user_id}")
        return jsonify({"api_key": new_key})
    except Exception as e:
        app.logger.error(f"Error creating API key: {str(e)}", exc_info=True)
        return jsonify({"error": "Internal server error"}), 500

@app.route("/api_keys/user/<user_id>", methods=["GET"])
@api_key_required
@api_authorized_required
def get_user_api_keys(user_id):
    try:
        # Load all API keys
        keys = load_api_keys()
        
        # Filter keys for the specific user
        user_keys = [
            {
                "key": key_data["key"],
                "created_at": key_data["created_at"],
                "role_created": key_data.get("role_created", False),
                "expiry": key_data.get("expiry")
            }
            for key_data in keys
            if key_data["user_id"] == user_id
        ]
        
        if not user_keys:
            app.logger.info(f"No API keys found for user {user_id}")
            return jsonify({"keys": []}), 200
            
        app.logger.info(f"Retrieved {len(user_keys)} API keys for user {user_id}")
        return jsonify({"keys": user_keys})
    except Exception as e:
        app.logger.error(f"Error retrieving API keys for user {user_id}: {str(e)}", exc_info=True)
        return jsonify({"error": "Internal server error"}), 500

@app.route('/blacklist', methods=['POST'])
@api_key_required
@api_authorized_required
def blacklist_user():
    try:
        data = request.json
        app.logger.info(f"Received data: {data}")
        required_fields = ['user_id', 'display_name', 'reason']
        missing_fields = [field for field in required_fields if field not in data]
        if missing_fields:
            error_msg = f"Missing required fields: {', '.join(missing_fields)}"
            app.logger.error(error_msg)
            return jsonify({"error": error_msg}), 400
        user_id = data['user_id']
        reason = data['reason']
        display_name = data['display_name']
        mc_info = data.get('mc_info', {})
        if 'minecraft_username' in mc_info and 'minecraft_uuid' not in mc_info:
            mc_info['minecraft_uuid'] = get_uuid(mc_info['minecraft_username'])
            app.logger.info(mc_info)
            if not mc_info['minecraft_uuid']:
                app.logger.error(f"Invalid Minecraft username: {mc_info['minecraft_username']}")
                return jsonify({"error": "Invalid Minecraft username"}), 400
        banned_users = load_banned_users()
        banned_users[user_id] = {
            "reason": reason,
            "timestamp": datetime.utcnow().isoformat(),
            "display_name": display_name,
            "mc_info": mc_info
        }
        save_banned_users(banned_users)
        app.logger.info(f"Successfully blacklisted user {user_id}")
        return jsonify({"message": "User blacklisted successfully"})
    except Exception as e:
        app.logger.error(f"Error in blacklist_user: {str(e)}")
        return jsonify({"error": f"An error occurred while processing the request: {str(e)}"}), 500

@app.route('/blacklist/remove', methods=['POST'])
@api_key_required
@api_authorized_required
def remove_from_blacklist():
    try:
        data = request.json
        app.logger.info(f"Received remove request data: {data}")
        
        # Required field: the identifier to remove by (e.g., user_id or minecraft_uuid)
        identifier = data.get('identifier')
        field = data.get('field', 'user_id')  # Default to user_id if not specified
        
        if not identifier:
            return jsonify({"error": "Missing identifier"}), 400
        
        if field not in ['user_id', 'minecraft_uuid']:
            return jsonify({"error": "Invalid field. Must be 'user_id' or 'minecraft_uuid'"}), 400

        banned_users = load_banned_users()
        
        # Search for the user to remove
        user_to_remove = None
        for user_id, details in banned_users.items():
            if field == 'user_id' and user_id == identifier:
                user_to_remove = user_id
                break
            elif field == 'minecraft_uuid' and details.get('mc_info', {}).get('minecraft_uuid') == identifier:
                user_to_remove = user_id
                break
        
        if user_to_remove:
            del banned_users[user_to_remove]
            save_banned_users(banned_users)
            app.logger.info(f"User with {field}={identifier} removed from blacklist")
            return jsonify({"message": f"User with {field}={identifier} removed from blacklist"})
        else:
            app.logger.info(f"No user found with {field}={identifier}")
            return jsonify({"error": f"No user found with {field}={identifier}"}), 404

    except Exception as e:
        app.logger.error(f"Error removing from blacklist: {str(e)}")
        return jsonify({"error": f"An error occurred: {str(e)}"}), 500

@app.route('/check_blacklist/<identifier>', methods=['GET'])
@api_key_required
def check_blacklist(identifier):
    banned_users = load_banned_users()
    app.logger.info(f"Checking blacklist for identifier: {identifier}")
    for user_id, details in banned_users.items():
        mc_info = details.get('mc_info', {})
        if user_id == identifier or mc_info.get('minecraft_uuid') == identifier or mc_info.get('uuid') == identifier:
            # Format the timestamp
            timestamp = details.get("timestamp")
            formatted_timestamp = timestamp
            if timestamp:
                try:
                    # Parse the ISO timestamp and format it
                    dt = datetime.fromisoformat(timestamp)
                    formatted_timestamp = dt.strftime("%B %d, %Y at %I:%M %p")
                except (ValueError, TypeError):
                    # If parsing fails, use the original timestamp
                    pass
                    
            result = {
                "reason": details["reason"],
                "display_name": details.get("display_name", "Unknown"),
                "timestamp": formatted_timestamp,
                "mc_info": mc_info
            }
            app.logger.info(f"Found match for identifier: {identifier}, Details: {result}")
            return jsonify(result)
    app.logger.info(f"No match found for identifier: {identifier}")
    return jsonify({})

# Web Routes
@app.route('/')
def index():
    return render_template('index.html')

@app.route('/website_blacklist', methods=['POST'])
def website_blacklist():
    discord_user_id = request.form.get('discord_user_id')
    display_name = request.form.get('display_name')
    minecraft_username = request.form.get('minecraft_username', '')
    minecraft_uuid = request.form.get('minecraft_uuid', '')
    reason = request.form.get('reason')
    if not all([discord_user_id, display_name, reason]):
        return "Missing required fields", 400
    if not minecraft_uuid and minecraft_username:
        minecraft_uuid = get_uuid(minecraft_username)
        if not minecraft_uuid:
            return jsonify({"error": "Invalid Minecraft username"}), 400
    request_data = {
        'discord_user_id': discord_user_id,
        'display_name': display_name,
        'minecraft_username': minecraft_username,
        'minecraft_uuid': minecraft_uuid,
        'reason': reason
    }
    PENDING_REQUESTS.append(request_data)
    return jsonify({"message": "Request submitted successfully"})

@app.route('/view_blacklist')
@cache.cached(timeout=300)
@limiter.limit("100 per hour")
def view_blacklist():
    banned_users = load_banned_users()
    # Format the data for easier template rendering
    formatted_users = []
    for user_id, details in banned_users.items():
        timestamp = details.get("timestamp", "")
        formatted_timestamp = timestamp
        if timestamp:
            try:
                dt = datetime.fromisoformat(timestamp)
                formatted_timestamp = dt.strftime("%B %d, %Y at %I:%M %p")
            except (ValueError, TypeError):
                pass
        
        formatted_users.append({
            "user_id": user_id,
            "display_name": details.get("display_name", "Unknown"),
            "reason": details.get("reason", ""),
            "timestamp": formatted_timestamp,
            "minecraft_username": details.get("mc_info", {}).get("minecraft_username", ""),
            "minecraft_uuid": details.get("mc_info", {}).get("minecraft_uuid", "")
        })
    
    return render_template('blacklisted.html',
                         banned_users=formatted_users,
                         discord_id=session.get("discord_id"),
                         discord_username=session.get("discord_username"))

@app.route('/blacklist_requests')
@login_required
@authorized_required
def blacklist_requests():
    return jsonify({
        "requests": PENDING_REQUESTS,
        "discord_id": session.get("discord_id"),
        "discord_username": session.get("discord_username")
    })

@app.route('/check_login')
def check_login():
    if session.get("discord_id"):
        return jsonify({"logged_in": True, "username": session.get("discord_username")})
    else:
        return jsonify({"logged_in": False})

if __name__ == '__main__':
    os.makedirs("data", exist_ok=True)
    app.run(debug=True)