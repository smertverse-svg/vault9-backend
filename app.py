import os
import sys
import requests
from flask import Flask, request, jsonify

# Ensure Python includes the current working directory in the search path
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from database import db
from models import AuditSubmission, Farmer

app = Flask(__name__)

# Configure database
app.config['SQLALCHEMY_DATABASE_URI'] = os.getenv('DATABASE_URL', 'sqlite:///vault9.db')
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
db.init_app(app)

with app.app_context():
    db.create_all()

VERIFY_TOKEN = os.getenv("WHATSAPP_VERIFY_TOKEN", "vault9_secure_verify_token")
WHATSAPP_TOKEN = os.getenv("WHATSAPP_TOKEN", "YOUR_META_PERMANENT_OR_TEMP_TOKEN")
PHONE_NUMBER_ID = os.getenv("PHONE_NUMBER_ID", "1387329541133056")

@app.route("/", methods=["GET"])
def home():
    return jsonify({"status": "Vault 9 Backend is Live", "pillar": "Bridge Muunganisha"}), 200

# 1. GET /webhook: Meta Webhook Verification Handshake
@app.route("/webhook", methods=["GET"])
def verify_webhook():
    mode = request.args.get("hub.mode")
    token = request.args.get("hub.verify_token")
    challenge = request.args.get("hub.challenge")

    if mode and token:
        if mode == "subscribe" and token == VERIFY_TOKEN:
            return challenge, 200
        else:
            return "Verification failed: Token mismatch", 403
    return "Invalid verification request", 400

# 2. POST /webhook: Ingress for Incoming WhatsApp Messages & Cognitive Engine
@app.route("/webhook", methods=["POST"])
def handle_webhook():
    data = request.get_json()
    
    try:
        # Parse Meta WhatsApp Cloud API incoming payload structure
        if data.get("object") == "whatsapp_business_account":
            for entry in data.get("entry", []):
                for change in entry.get("changes", []):
                    value = change.get("value", {})
                    messages = value.get("messages")
                    
                    if messages:
                        message = messages[0]
                        sender_phone = message.get("from")
                        msg_body = message.get("text", {}).get("body", "").strip()
                        
                        # Trigger Vault 9's Ruthless Mentor Cognitive Response
                        generate_cognitive_response(sender_phone, msg_body)
                        
            return jsonify({"status": "EVENT_RECEIVED"}), 200
    except Exception as e:
        print(f"Error processing webhook payload: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500

def generate_cognitive_response(recipient_phone, user_input):
    """
    Vault 9 Cognitive Engine: Analyzes user input across the 7 Pillars and 
    9 Capitals of Wealth, acting as a ruthless mentor challenging assumptions.
    """
    user_lower = user_input.lower()
    
    # Example cognitive routing logic challenging the user's mental bandwidth
    if "pillar" in user_lower or "society" in user_lower:
        reply = (
            "🧠 **Vault 9 Cognitive Audit [Pillars of Society]**: "
            "You speak of societal transformation, yet your current framework lacks structural depth. "
            "Which of the 7 pillars (Economy, Education, Health, Governance, Security, Infrastructure, Culture) "
            "does your current strategy actually fortify? Defend your assumptions or watch your model collapse."
        )
    elif "wealth" in user_lower or "capital" in user_lower:
        reply = (
            "💎 **Vault 9 Wealth Scan [9 Capitals]**: "
            "You are fixated solely on financial capital. Where are your strategies for Intellectual, "
            "Social, and Cultural capital? If your network and cognitive reserves are stagnant, "
            "your monetary capital is a ticking clock. What is your actual leverage?"
        )
    else:
        reply = (
            f"⚡ **Vault 9 Stress Test**: "
            f"I received your input: *\"{user_input}\"*. That sounds like comforting validation rather than bulletproof thinking. "
            "Are you operating at peak cognitive capacity, or are you settling for mediocre execution? "
            "State your core objective clearly across the 7 Pillars so we can stress test it properly."
        )
        
    send_whatsapp_message(recipient_phone, reply)

def send_whatsapp_message(recipient_phone, message_text):
    """Sends an automated reply back to the user via Meta Cloud API."""
    headers = {
        "Authorization": f"Bearer {WHATSAPP_TOKEN}",
        "Content-Type": "application/json",
    }
    payload = {
        "messaging_product": "whatsapp",
        "to": recipient_phone,
        "type": "text",
        "text": {"body": message_text},
    }
    url = f"https://graph.facebook.com/v25.0/{PHONE_NUMBER_ID}/messages"
    response = requests.post(url, json=payload, headers=headers)
    if response.status_code != 200:
        print(f"Failed to send WhatsApp message: {response.text}")

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", 10000)))