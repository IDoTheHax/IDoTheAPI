from flask import Flask, request, jsonify, render_template, redirect, url_for, session
from flask_cors import CORS
import json
from datetime import datetime
import requests
from functools import wraps
import os
from dotenv import load_dotenv

# Discord OAuth2 settings
load_dotenv()
CLIENT_ID = os.getenv('CLIENT_ID')
CLIENT_SECRET = os.getenv('CLIENT_SECRET')
REDIRECT_URI = 'http://localhost:5000/callback'  # Ensure this matches your Discord app setting

app = Flask(__name__)
app.secret_key = os.urandom(24) # Use os.urandom for better security
os.environ['OAUTHLIB_INSECURE_TRANSPORT'] = '1'
CORS(app, supports_credentials=True)

# Blacklist data
BANNED_USERS_FILE = "data/banned_users.json"
AUTHORIZED_USERS = [987323487343493191, 1088268266499231764, 726721909374320640, 710863981039845467, 1151136371164065904]
PENDING_REQUESTS = []  # Temporary storage for requests, replace with db in real app

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
    headers = {
        'Content-Type': 'application/x-www-form-urlencoded'
    }
    response = requests.post(token_url, data=data, headers=headers)
    token_json = response.json()
    access_token = token_json.get('access_token')

    user_url = 'https://discord.com/api/users/@me'
    headers = {
        'Authorization': f'Bearer {access_token}'
    }
    user_response = requests.get(user_url, headers=headers)
    user_json = user_response.json()
    session["discord_id"] = user_json.get("id")
    session["discord_username"] = user_json.get("username")
    return redirect(url_for('blacklist_requests')) ## TODO MAKE IT GO TO THE OTHER SERVER

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('index'))

@app.route('/blacklist', methods=['POST'])
def blacklist_user():
    try:
        data = request.json
        app.logger.info(f"Received data: {data}")

        # Check for required fields
        required_fields = ['auth_id', 'user_id', 'display_name', 'reason']
        missing_fields = [field for field in required_fields if field not in data]

        if missing_fields:
            error_msg = f"Missing required fields: {', '.join(missing_fields)}"
            app.logger.error(error_msg)
            return jsonify({"error": error_msg}), 400

        # Convert auth_id to int, with error handling
        try:
            auth_id = int(data['auth_id'])
        except (ValueError, TypeError):
            error_msg = "auth_id must be a valid integer"
            app.logger.error(error_msg)
            return jsonify({"error": error_msg}), 400

        if auth_id not in AUTHORIZED_USERS:
            app.logger.error(f"Unauthorized attempt by {auth_id}")
            return jsonify({"error": "Unauthorized"}), 403

        user_id = data['user_id']
        reason = data['reason']
        display_name = data['display_name']
        mc_info = data.get('mc_info', {})

        # Fetch Minecraft UUID if username is provided and UUID is missing
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


@app.route('/check_blacklist/<identifier>', methods=['GET'])
def check_blacklist(identifier):
    banned_users = load_banned_users()
    # Log the identifier for debugging
    app.logger.info(f"Checking blacklist for identifier: {identifier}")

    for user_id, details in banned_users.items():
        mc_info = details.get('mc_info', {})

        # Log user_id and minecraft_uuid for debugging
        app.logger.info(f"Checking user_id: {user_id}, minecraft_uuid: {mc_info.get('uuid')}")

        # Check both Discord user ID and Minecraft UUID
        if user_id == identifier or mc_info.get('uuid') == identifier:
            result = {
                "reason": details["reason"],
                "display_name": details.get("display_name", "Unknown"),
                "timestamp": details.get("timestamp"),
                "mc_info": mc_info  # Include mc_info in the result
            }
            app.logger.info(f"Found match for identifier: {identifier}, Details: {result}")
            return jsonify(result)  # Return immediately upon finding a match

    app.logger.info(f"No match found for identifier: {identifier}")
    return jsonify({})  # Return empty dictionary if no match is found


# Routes for Web Form and Blacklist Requests with Authentication
@app.route('/')
def index():
    return render_template('index.html')

@app.route('/website_blacklist', methods=['POST'])
def website_blacklist():
    discord_user_id = request.form.get('discord_user_id')
    display_name = request.form.get('display_name')
    minecraft_username = request.form.get('minecraft_username', '')  # Optional field
    minecraft_uuid = request.form.get('minecraft_uuid', '')
    reason = request.form.get('reason')

    # Validate required fields
    if not all([discord_user_id, display_name, reason]):
        return "Missing required fields", 400

    # If Minecraft UUID isn't provided, attempt to fetch it using the username
    if not minecraft_uuid and minecraft_username:
        minecraft_uuid = get_uuid(minecraft_username)
        if not minecraft_uuid:
            return jsonify({"error": "Invalid Minecraft username"}), 400

    # Store the request in the pending list. Use a database in a real app
    request_data = {
        'discord_user_id': discord_user_id,
        'display_name': display_name,
        'minecraft_username': minecraft_username,
        'minecraft_uuid': minecraft_uuid,
        'reason': reason
    }
    PENDING_REQUESTS.append(request_data)
    return jsonify({"message": "Request submitted successfully"})

@app.route('/blacklist_requests')
@login_required
@authorized_required
def blacklist_requests():
    return jsonify({
        "requests": PENDING_REQUESTS,
        "discord_id": session.get("discord_id"),  # Make sure this field exists
        "discord_username": session.get("discord_username")
    })

@app.route('/check_login')
def check_login():
    if session.get("discord_id"):
        return jsonify({"logged_in": True, "username": session.get("discord_username")})
    else:
        return jsonify({"logged_in": False})

if __name__ == '__main__':
    app.run(debug=True)
