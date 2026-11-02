import os
import requests
from flask import Flask, request
from dotenv import load_dotenv

# Force load variables from .env file into environment
load_dotenv()

from database import db
from models import AuditSubmission, Farmer

app = Flask(__name__)

# Configure SQLite database
app.config['SQLALCHEMY_DATABASE_URI'] = os.getenv("DATABASE_URL", "sqlite:///vault9.db")
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

db.init_app(app)

# Ensure database tables exist within app context
with app.app_context():
    db.create_all()

def send_whatsapp_reply(to_phone, message_body):
    """Dispatches an automated text response back to the sender via Meta Cloud API."""
    token = os.getenv("WHATSAPP_ACCESS_TOKEN")
    phone_number_id = os.getenv("WHATSAPP_PHONE_NUMBER_ID")
    
    url = f"https://graph.facebook.com/v20.0/{phone_number_id}/messages"
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json"
    }
    payload = {
        "messaging_product": "whatsapp",
        "to": to_phone,
        "type": "text",
        "text": {"body": message_body}
    }
    
    response = requests.post(url, json=payload, headers=headers)
    return response.json()

@app.route('/webhook', methods=['GET', 'POST'])
def webhook():
    # 1. Meta Webhook Verification (GET)
    if request.method == 'GET':
        verify_token = os.getenv("WHATSAPP_VERIFY_TOKEN")
        mode = request.args.get("hub.mode")
        token = request.args.get("hub.verify_token")
        challenge = request.args.get("hub.challenge")
        
        if mode and token:
            if mode == "subscribe" and token == verify_token:
                return challenge, 200
            return "Verification failed", 403
        return "Invalid verification request", 400

    # 2. Inbound Message Handling (POST)
    if request.method == 'POST':
        data = request.get_json()
        print(f"Received webhook payload: {data}")  # Debug print to console
        
        try:
            # Parse incoming WhatsApp payload structure
            entry = data.get('entry', [{}])[0]
            change = entry.get('changes', [{}])[0]
            value = change.get('value', {})
            messages = value.get('messages')
            
            if messages:
                msg = messages[0]
                sender_phone = msg.get('from')
                msg_body = msg.get('text', {}).get('body', '')
                
                # Check or create default farmer profile mapping
                farmer = Farmer.query.filter_by(phone_number=sender_phone).first()
                if not farmer:
                    farmer = Farmer(phone_number=sender_phone, name="Field Auditor")
                    db.session.add(farmer)
                    db.session.commit()

                # Save the audit submission to SQLite
                submission = AuditSubmission(
                    farmer_id=farmer.id,
                    raw_payload=data,
                    message_type='text',
                    content=msg_body,
                    status='PENDING'
                )
                db.session.add(submission)
                db.session.commit()
                
                # Trigger automated WhatsApp confirmation reply
                reply_text = f"VAULT 9: Audit received successfully! Logged content: '{msg_body}'. Status: PENDING."
                reply_res = send_whatsapp_reply(sender_phone, reply_text)
                print(f"WhatsApp Reply Response: {reply_res}")

        except Exception as e:
            print(f"Error processing webhook: {e}")
            
        return "OK", 200

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)