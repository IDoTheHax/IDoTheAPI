from flask import Flask, request, jsonify
import json
from datetime import datetime
import requests

app = Flask(__name__)

BANNED_USERS_FILE = "data/banned_users.json"
AUTHORIZED_USERS = [987323487343493191, 1088268266499231764, 726721909374320640, 710863981039845467, 1151136371164065904]

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

if __name__ == '__main__':
    app.run(debug=True)
