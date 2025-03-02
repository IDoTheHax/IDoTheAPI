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
    response = requests.get(f"https://api.mojang.com/users/profiles/minecraft/{username}")
    if response.status_code == 200:
        data = response.json()
        return data['id']
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
    return redirect(url_for('blacklist_requests'))

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('index'))

@app.route('/blacklist', methods=['POST'])
def blacklist_user():
    data = request.json
    auth_id = int(data['auth_id'])
    if auth_id not in AUTHORIZED_USERS:
        return jsonify({"error": "Unauthorized"}), 403

    user_id = data['user_id']
    reason = data['reason']
    display_name = data['display_name']
    mc_info = data.get('mc_info')

    banned_users = load_banned_users()
    banned_users[user_id] = {
        "reason": reason,
        "timestamp": datetime.utcnow().isoformat(),
        "display_name": display_name,
        "mc_info": mc_info
    }
    save_banned_users(banned_users)
    return jsonify({"message": "User blacklisted successfully"})

@app.route('/check_blacklist/<user_id>', methods=['GET'])
def check_blacklist(user_id):
    banned_users = load_banned_users()
    if user_id in banned_users:
        return jsonify({"blacklisted": True, "reason": banned_users[user_id]["reason"]})
    return jsonify({"blacklisted": False})

# Routes for Web Form and Blacklist Requests with Authentication
@app.route('/')
def index():
    return render_template('index.html')

@app.route('/website_blacklist', methods=['POST'])
def website_blacklist():
    discord_user_id = request.form.get('discord_user_id')
    display_name = request.form.get('display_name')
    minecraft_username = request.form.get('minecraft_username', '')  # Get optional fields
    minecraft_uuid = request.form.get('minecraft_uuid', '')
    reason = request.form.get('reason')

    # Validate required fields
    if not all([discord_user_id, display_name, reason]):
        return "Missing required fields", 400

    # Store the request in the pending list.  Use database in a real app
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
    return jsonify({"requests": PENDING_REQUESTS, "discord_username": session.get("discord_username")})


@app.route('/check_login')
def check_login():
    if session.get("discord_id"):
        return jsonify({"logged_in": True, "username": session.get("discord_username")})
    else:
        return jsonify({"logged_in": False})

if __name__ == '__main__':
    app.run(debug=True)
