import os
import sys

# Ensure Python includes the current working directory in the search path
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from flask import Flask, jsonify, request
from database import db
from models import AuditSubmission, Farmer

app = Flask(__name__)

# Configure database (pulls from environment variable or defaults)
app.config['SQLALCHEMY_DATABASE_URI'] = os.getenv('DATABASE_URL', 'sqlite:///vault9.db')
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

# Initialize database with app
db.init_app(app)

with app.app_context():
    db.create_all()

VERIFY_TOKEN = os.getenv("WHATSAPP_VERIFY_TOKEN", "vault9_secure_verify_token")

@app.route("/", methods=["GET"])
def home():
    return jsonify({"status": "Vault 9 Backend is Live", "pillar": "Bridge Muunganisha"}), 200

@app.route("/webhook", methods=["GET"])
def verify_webhook():
    mode = request.args.get("hub.mode")
    token = request.args.get("hub.verify_token")
    challenge = request.args.get("hub.challenge")

    if mode == "subscribe" and token == VERIFY_TOKEN:
        print("WEBHOOK_VERIFIED")
        return challenge, 200
    else:
        return "Verification failed", 403

@app.route("/webhook", methods=["POST"])
def receive_webhook():
    data = request.get_json()
    print("Incoming payload:", data)
    # Phase 4 logic will parse incoming WhatsApp messages here and save to db
    return jsonify({"status": "success"}), 200

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)