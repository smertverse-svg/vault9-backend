import os
from flask import Flask, request, jsonify
from flask_sqlalchemy import SQLAlchemy
import requests
from google import genai
from google.genai import types

# Initialize Flask app
app = Flask(__name__)

# Database configuration
app.config['SQLALCHEMY_DATABASE_URI'] = os.getenv('DATABASE_URI', 'sqlite:///vault9.db')
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
db = SQLAlchemy(app)

# Define Conversation History Model for Persistence
class ConversationHistory(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    sender_phone = db.Column(db.String(50), index=True, nullable=False)
    role = db.Column(db.String(20), nullable=False)  # 'user' or 'model'
    message = db.Column(db.Text, nullable=False)

# Initialize database tables within app context
with app.app_context():
    db.create_all()

# Meta & WhatsApp Configuration
VERIFY_TOKEN = os.getenv("WHATSAPP_VERIFY_TOKEN", "vault9_secure_verify_token")
WHATSAPP_ACCESS_TOKEN = os.getenv("WHATSAPP_ACCESS_TOKEN", "YOUR_META_PERMANENT_TOKEN")
PHONE_NUMBER_ID = os.getenv("PHONE_NUMBER_ID", "1387329541133056")

# Initialize the Gemini client
client = genai.Client()

VAULT9_SYSTEM_INSTRUCTION = (
    "You are Vault 9 (Bridge Muunganisha), a ruthless, high-level cognitive coach and mentor. "
    "Your job is to challenge assumptions, stress-test ideas across the 7 Pillars of Society "
    "and 9 Capitals of Wealth, and demand bulletproof thinking. "
    "NEVER use repetitive introductory templates, boilerplate tags, or meta-commentary like 'I received your input'. "
    "Jump straight into the attack. Challenge the user directly, expose contradictions based on past turns, "
    "and keep responses sharp, provocative, and concise for WhatsApp."
)

@app.route("/", methods=["GET"])
def home():
    return jsonify({"status": "Vault 9 Backend is Live", "pillar": "Bridge Muunganisha", "persistence": "Active"}), 200

# 1. GET /webhook: Meta Webhook Verification Handshake
@app.route("/webhook", methods=["GET"])
def verify():
    mode = request.args.get("hub.mode")
    token = request.args.get("hub.verify_token")
    challenge = request.args.get("hub.challenge")

    if mode and token:
        if mode == "subscribe" and token == VERIFY_TOKEN:
            return challenge, 200
        else:
            return "Verification token mismatch", 403
    return "Invalid verification request", 400

# 2. POST /webhook: Incoming WhatsApp Message Listener
@app.route("/webhook", methods=["POST"])
def webhook():
    body = request.get_json()
    print("Incoming WhatsApp Payload:", body)

    try:
        if body and "entry" in body:
            for entry in body["entry"]:
                changes = entry.get("changes", [])
                for change in changes:
                    value = change.get("value", {})
                    messages = value.get("messages", [])
                    if messages:
                        message = messages[0]
                        sender_phone = message.get("from")
                        message_text = message.get("text", {}).get("body")

                        if sender_phone and message_text:
                            process_incoming_message(sender_phone, message_text)

        return jsonify({"status": "EVENT_RECEIVED"}), 200
    except Exception as e:
        print(f"Webhook Error: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500

def process_incoming_message(sender_phone, message_text):
    try:
        # 1. Retrieve last 10 messages from database BEFORE adding current user message
        recent_chats = ConversationHistory.query.filter_by(sender_phone=sender_phone)\
            .order_by(ConversationHistory.id.desc()).limit(10).all()
        recent_chats.reverse() # Oldest to newest

        # 2. Build contents payload for Gemini maintaining history
        contents = []
        for chat in recent_chats:
            contents.append(types.Content(
                role=chat.role,
                parts=[types.Part.from_text(text=chat.message)]
            ))
        
        # Append the current user message to the live payload
        contents.append(types.Content(
            role="user",
            parts=[types.Part.from_text(text=message_text)]
        ))

        # 3. Generate dynamic response via Gemini 3.8 Flash with full context
        response = client.models.generate_content(
            model='gemini-3.8-flash',
            contents=contents,
            config=types.GenerateContentConfig(
                system_instruction=VAULT9_SYSTEM_INSTRUCTION,
                temperature=0.85,
                max_output_tokens=350,
            ),
        )
        reply_text = response.text

        # 4. Save BOTH user message and model reply to database for future turns
        user_msg = ConversationHistory(sender_phone=sender_phone, role='user', message=message_text)
        assistant_msg = ConversationHistory(sender_phone=sender_phone, role='model', message=reply_text)
        db.session.add(user_msg)
        db.session.add(assistant_msg)
        db.session.commit()

    except Exception as e:
        print(f"Gemini API / DB Error: {e}")
        reply_text = f"🧠 *Vault 9 Error*: {str(e)}"

    send_whatsapp_message(sender_phone, reply_text)

def send_whatsapp_message(recipient_phone, text_message):
    url = f"https://graph.facebook.com/v21.0/{PHONE_NUMBER_ID}/messages"
    headers = {
        "Authorization": f"Bearer {WHATSAPP_ACCESS_TOKEN}",
        "Content-Type": "application/json"
    }
    payload = {
        "messaging_product": "whatsapp",
        "to": recipient_phone,
        "type": "text",
        "text": {"body": text_message}
    }
    
    response = requests.post(url, headers=headers, json=payload)
    if response.status_code != 200:
        print(f"Failed to send WhatsApp message: {response.json()}")
    else:
        print("WhatsApp message sent successfully.")

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 10000)))