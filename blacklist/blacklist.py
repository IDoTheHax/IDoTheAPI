import json
from datetime import datetime

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

def blacklist_user(auth_id, user_id, reason, display_name):
    if auth_id not in AUTHORIZED_USERS:
        return {"error": "Unauthorized"}, 403
    
    banned_users = load_banned_users()
    banned_users[str(user_id)] = {
        "reason": reason,
        "timestamp": datetime.utcnow().isoformat(),
        "display_name": display_name
    }
    save_banned_users(banned_users)
    return {"message": "User blacklisted successfully"}

def check_blacklist(user_id):
    banned_users = load_banned_users()
    if user_id in banned_users:
        return {"blacklisted": True, "reason": banned_users[user_id]["reason"]}
    return {"blacklisted": False}

def get_banned_users():
    return load_banned_users()