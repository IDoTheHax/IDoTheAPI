from flask import Flask, request, jsonify
from blacklist.blacklist import blacklist_user, check_blacklist, get_banned_users

app = Flask(__name__)

@app.route('/blacklist', methods=['POST'])
def blacklist_user_route():
    data = request.json
    result = blacklist_user(data['auth_id'], data['user_id'], data['reason'], data['display_name'])
    return jsonify(result)

@app.route('/check_blacklist/<user_id>', methods=['GET'])
def check_blacklist_route(user_id):
    return jsonify(check_blacklist(user_id))

@app.route('/get_banned_users', methods=['GET'])
def get_banned_users_route():
    return jsonify(get_banned_users())

if __name__ == '__main__':
    app.run()