import json
from datetime import datetime
import requests
import aiohttp

BANNED_USERS_FILE = "data/banned_users.json"
AUTHORIZED_USERS = [987323487343493191, 1088268266499231764, 726721909374320640, 710863981039845467, 1151136371164065904]

def get_uuid(username):
    response = requests.get(f"https://api.mojang.com/users/profiles/minecraft/{username}")
    if response.status_code == 200:
        data = response.json()
        return data['id']
    return None

def load_banned_users():
    try:
        with open(BANNED_USERS_FILE, "r") as f:
            return json.load(f)
    except FileNotFoundError:
        return {}

def save_banned_users(banned_users):
    with open(BANNED_USERS_FILE, "w") as f:
        json.dump(banned_users, f, indent=4)

def blacklist_user(auth_id, user_identifier, reason):
    if auth_id not in AUTHORIZED_USERS:
        return {"error": "Unauthorized"}, 403
    
    uuid = user_identifier if len(user_identifier) == 32 else get_uuid(user_identifier)
    if not uuid:
        return {"error": "Invalid username or UUID"}, 400
    
    banned_users = load_banned_users()
    banned_users[uuid] = {
        "reason": reason,
        "timestamp": datetime.utcnow().isoformat(),
        "username": user_identifier if len(user_identifier) < 32 else None
    }
    save_banned_users(banned_users)
    return {"message": f"User {user_identifier} blacklisted successfully"}


async def check_blacklist(user_identifier):
    # Check if it's a potential Discord user ID (long integer)
    if user_identifier.isdigit() and len(user_identifier) > 15:
        # Verify the Discord ID by querying the API
        async with aiohttp.ClientSession() as session:
            async with session.get(f"https://discord.com/api/v10/users/{user_identifier}") as response:
                if response.status == 200:
                    # Valid Discord ID
                    uuid = user_identifier
                elif response.status == 404:
                    return {"error": "Invalid Discord user ID"}, 400
                else:
                    return {"error": "Unable to verify Discord user ID"}, 500
    elif len(user_identifier) == 32 and all(c in '0123456789abcdef' for c in user_identifier):
        # It's a Minecraft UUID
        uuid = user_identifier
    else:
        # Assume it's a Minecraft username and convert to UUID
        uuid = get_uuid(user_identifier)
    
    if not uuid:
        return {"error": "Invalid identifier"}, 400
    
    banned_users = load_banned_users()
    if uuid in banned_users:
        return {"blacklisted": True, "reason": banned_users[uuid]["reason"]}
    return {"blacklisted": False}

def get_banned_users():
    return load_banned_users()