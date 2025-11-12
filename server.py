
from flask import Flask, request, redirect, jsonify
from datetime import datetime
import uuid
import os
from pymongo import MongoClient

app = Flask(__name__)

MONGO_URI = os.getenv("MONGO_URI", "mongodb://localhost:27017")
DOMAIN = os.getenv("DOMAIN", "yourdomain.com")
AD_TARGET_URL = os.getenv("AD_TARGET_URL", "https://ad-host.example.com/adpage")

mongo = MongoClient(MONGO_URI)
db = mongo[os.getenv("DB_NAME", "video_bot_db")]

@app.route("/ad/create", methods=["POST"])
def create_ad_session():
    data = request.json or {}
    user_id = int(data.get("user_id")) if data.get("user_id") else None
    token = uuid.uuid4().hex
    rec = {
        "token": token,
        "user_id": user_id,
        "status": "pending",
        "created_at": datetime.utcnow(),
        "clicked_at": None,
        "completed_at": None
    }
    db.ad_sessions.insert_one(rec)
    return jsonify({"token": token, "redirect_url": f"https://{DOMAIN}/ad/redirect?token={token}"}), 201

@app.route("/ad/redirect")
def ad_redirect():
    token = request.args.get("token")
    if not token:
        return "Missing token", 400
    db.ad_sessions.update_one({"token": token}, {"$set": {"clicked_at": datetime.utcnow()}})
    # redirect to ad host; include token so ad host can callback
    return redirect(f"{AD_TARGET_URL}?token={token}", code=302)

@app.route("/ad/callback", methods=["POST"])
def ad_callback():
    payload = request.json or {}
    token = payload.get("token")
    status = payload.get("status")
    if not token:
        return "Missing token", 400
    if status == "completed":
        db.ad_sessions.update_one({"token": token}, {"$set": {"status": "completed", "completed_at": datetime.utcnow()}})
        return "ok", 200
    return "ignored", 200

@app.route("/ad/status/<token>")
def ad_status(token):
    rec = db.ad_sessions.find_one({"token": token})
    if not rec:
        return jsonify({"error": "not found"}), 404
    return jsonify({"token": rec.get("token"), "status": rec.get("status")})

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=int(os.getenv('PORT', '8080')))
