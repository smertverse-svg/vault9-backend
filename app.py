import os
import json
import time
from flask import Flask, request, jsonify
import requests
from flask_sqlalchemy import SQLAlchemy
import anthropic
from openai import OpenAI

# Initialize Flask app
app = Flask(__name__)

# Database configuration
app.config['SQLALCHEMY_DATABASE_URI'] = os.getenv('DATABASE_URI', 'sqlite:///vault9.db')
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
db = SQLAlchemy(app)

# Import models to ensure tables are registered
from models import ConversationHistory, UserState, Farmer, AuditSubmission

# Initialize database tables within app context
with app.app_context():
    db.create_all()

# Meta & WhatsApp Configuration
VERIFY_TOKEN = os.getenv("WHATSAPP_VERIFY_TOKEN", "vault9_secure_verify_token")
WHATSAPP_ACCESS_TOKEN = os.getenv("WHATSAPP_ACCESS_TOKEN", "YOUR_META_PERMANENT_TOKEN")
PHONE_NUMBER_ID = os.getenv("PHONE_NUMBER_ID", "1387329541133056")

# AI API Keys & Clients
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")

openai_client = OpenAI(api_key=OPENAI_API_KEY) if OPENAI_API_KEY else None
anthropic_client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY) if ANTHROPIC_API_KEY else None

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
    return jsonify({
        "status": "Vault 9 Backend is Live", 
        "pillar": "Bridge Muunganisha", 
        "brains": "OpenAI GPT-4o-mini (Primary) -> Claude 3.5 Sonnet -> Gemini 3.8 Flash",
        "persistence": "Active",
        "telemetry": "Enabled"
    }), 200

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

def analyze_user_telemetry(sender_phone, message_text):
    """
    Scans incoming text using GPT-4o-mini to extract cognitive telemetry,
    updating the persistent user state profile in PostgreSQL.
    """
    if not openai_client:
        return None

    system_prompt = (
        "Analyze the following user input and return a strict JSON object with these keys: "
        "'momentum_shift' (float between -5.0 and +5.0 representing change in drive), "
        "'cognitive_load' (one of: 'strategic', 'tactical', 'overwhelmed'), "
        "'emotional_valence' (one of: 'driven', 'stressed', 'fatigued', 'focused', 'neutral'), "
        "'core_friction' (a concise 1-sentence summary of their current bottleneck or flawed assumption)."
    )
    
    try:
        response = openai_client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": message_text}
            ],
            response_format={"type": "json_object"}
        )
        data = json.loads(response.choices[0].message.content)
        
        # Update or create user state in PostgreSQL
        state = UserState.query.filter_by(phone_number=sender_phone.strip()).first()
        if not state:
            state = UserState(phone_number=sender_phone.strip())
            db.session.add(state)
            
        # Update metrics
        state.momentum_score = max(0.0, min(100.0, state.momentum_score + float(data.get('momentum_shift', 0))))
        state.cognitive_load = data.get('cognitive_load', 'balanced')
        state.emotional_valence = data.get('emotional_valence', 'neutral')
        state.core_friction = data.get('core_friction', '')
        
        db.session.commit()
        return state
    except Exception as e:
        print(f"Telemetry scanning error: {e}")
        return None

def process_incoming_message(sender_phone, message_text):
    reply_text = None
    ai_success = False

    try:
        # Run cognitive telemetry scan on the incoming message
        user_state = analyze_user_telemetry(sender_phone, message_text)
        
        # Build dynamic context from user state if available
        state_context = ""
        if user_state:
            state_context = (
                f"\n[USER TELEMETRY CONTEXT - Momentum: {user_state.momentum_score}/100, "
                f"Cognitive Load: {user_state.cognitive_load}, State: {user_state.emotional_valence}, "
                f"Core Friction: {user_state.core_friction}]"
            )

        # Retrieve last 5 messages from database
        recent_chats = ConversationHistory.query.filter_by(sender_phone=sender_phone)\
            .order_by(ConversationHistory.id.desc()).limit(5).all()
        recent_chats.reverse()

        # --- ATTEMPT 1: OpenAI GPT-4o-mini (PRIMARY BRAIN) ---
        if openai_client:
            try:
                openai_messages = [{"role": "system", "content": VAULT9_SYSTEM_INSTRUCTION + state_context}]
                for chat in recent_chats:
                    role = "user" if chat.role == "user" else "assistant"
                    openai_messages.append({"role": role, "content": chat.message})
                openai_messages.append({"role": "user", "content": message_text})

                response = openai_client.chat.completions.create(
                    model="gpt-4o-mini",
                    messages=openai_messages,
                    max_tokens=300,
                    temperature=0.85
                )
                reply_text = response.choices[0].message.content
                ai_success = True
                print("Response generated via Primary Brain (OpenAI GPT-4o-mini).")
            except Exception as openai_err:
                print(f"OpenAI failed ({openai_err}). Routing to Claude 3.5 Sonnet...")

        # --- ATTEMPT 2: Claude 3.5 Sonnet (SECONDARY FALLBACK) ---
        if not ai_success and anthropic_client:
            try:
                anthropic_messages = []
                for chat in recent_chats:
                    role = "user" if chat.role == "user" else "assistant"
                    anthropic_messages.append({"role": role, "content": chat.message})
                anthropic_messages.append({"role": "user", "content": message_text})

                response = anthropic_client.messages.create(
                    model="claude-3-5-sonnet-20241022",
                    max_tokens=300,
                    system=VAULT9_SYSTEM_INSTRUCTION + state_context,
                    messages=anthropic_messages
                )
                reply_text = response.content[0].text
                ai_success = True
                print("Response generated via Secondary Brain (Claude 3.5 Sonnet).")
            except Exception as claude_err:
                print(f"Claude failed ({claude_err}). Routing to Gemini 3.8 Flash...")

        # --- ATTEMPT 3: Gemini 3.8 Flash (TERTIARY FALLBACK) ---
        if not ai_success and GEMINI_API_KEY:
            try:
                contents = []
                for chat in recent_chats:
                    gemini_role = "user" if chat.role == "user" else "model"
                    contents.append({
                        "role": gemini_role,
                        "parts": [{"text": chat.message}]
                    })
                contents.append({
                    "role": "user",
                    "parts": [{"text": message_text}]
                })

                api_url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-3.8-flash:generateContent?key={GEMINI_API_KEY}"
                
                payload = {
                    "system_instruction": {
                        "parts": [{"text": VAULT9_SYSTEM_INSTRUCTION + state_context}]
                    },
                    "contents": contents,
                    "generationConfig": {
                        "temperature": 0.85,
                        "maxOutputTokens": 300
                    }
                }

                resp = requests.post(api_url, json=payload, timeout=(5, 30))
                resp_data = resp.json()

                if resp.status_code == 200:
                    candidates = resp_data.get("candidates", [])
                    if candidates:
                        reply_text = candidates[0]["content"]["parts"][0]["text"]
                        ai_success = True
                        print("Response generated via Tertiary Brain (Gemini 3.8 Flash).")
                else:
                    err_msg = resp_data.get("error", {}).get("message", "Gemini API error")
                    print(f"Gemini error: {err_msg}")
            except Exception as gemini_err:
                print(f"Gemini failed ({gemini_err}).")

        if not reply_text:
            reply_text = "🧠 *Vault 9 Error*: All upstream AI services are currently unavailable."

        # Save conversation context to database
        user_msg = ConversationHistory(sender_phone=sender_phone, role='user', message=message_text)
        assistant_msg = ConversationHistory(sender_phone=sender_phone, role='assistant', message=reply_text)
        db.session.add(user_msg)
        db.session.add(assistant_msg)
        db.session.commit()

    except Exception as e:
        print(f"Server / DB Error: {e}")
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