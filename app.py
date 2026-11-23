import os
import re
import json
import io
from datetime import datetime, timezone
from functools import wraps
from flask import Flask, request, jsonify
import requests
import anthropic
from openai import OpenAI

# Import centralized db instance
from database import db

# Initialize Flask app
app = Flask(__name__)

# Database configuration (supports DATABASE_URI or DATABASE_URL, SQLite or PostgreSQL)
raw_db_url = os.getenv('DATABASE_URI') or os.getenv('DATABASE_URL') or 'sqlite:///vault9.db'
if raw_db_url.startswith('postgres://'):
    raw_db_url = raw_db_url.replace('postgres://', 'postgresql://', 1)

app.config['SQLALCHEMY_DATABASE_URI'] = raw_db_url
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

db.init_app(app)

# Import models
from models import Company, SeatWhitelist, ConversationHistory, UserState, Farmer, AuditSubmission

with app.app_context():
    db.create_all()

# Meta & WhatsApp Configuration
VERIFY_TOKEN = os.getenv("WHATSAPP_VERIFY_TOKEN", "vault9_secure_verify_token")
WHATSAPP_ACCESS_TOKEN = os.getenv("WHATSAPP_ACCESS_TOKEN", "YOUR_META_PERMANENT_TOKEN")
PHONE_NUMBER_ID = os.getenv("PHONE_NUMBER_ID", "1502060209648250")
ADMIN_API_KEY = os.getenv("ADMIN_API_KEY", "")

# AI API Keys & Clients
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")

openai_client = OpenAI(api_key=OPENAI_API_KEY) if OPENAI_API_KEY else None
anthropic_client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY) if ANTHROPIC_API_KEY else None

BASE_SYSTEM_INSTRUCTION = (
    "You are Vault 9 (Bridge Muunganisha), a ruthless, high-level cognitive coach and strategic execution engine. "
    "Your job is to challenge assumptions, stress-test ideas across the 7 Pillars of Society "
    "and 9 Capitals of Wealth (Financial, Intellectual, Social, Spiritual, Physical, Emotional, Cultural, Experiential, Reputation), "
    "and demand bulletproof thinking. "
    "CONFIDENCE & SELF-EXECUTION PROTOCOL: Never validate hesitation, passive framing ('I'll try', 'maybe', 'hoping to'), or self-doubt. "
    "When a user exhibits low confidence or hesitation (via text or transcribed voice notes), intercept immediately, "
    "strip away excuses, and demand concrete execution windows and uncompromising mental authority. "
    "NEVER use repetitive introductory templates, boilerplate tags, or meta-commentary like 'I received your input'. "
    "Jump straight into the attack. Challenge the user directly, expose contradictions, and keep responses sharp and concise for WhatsApp."
)

STAGE_DIRECTIVES = {
    "AWAKENING": (
        " [STAGE 1: AWAKENING (SCAN) — GATE: Lock baseline KPI & diagnose blind spots before advancing to REGENERATION]. "
        "Act as a forensic diagnostician. Strip illusions, expose contradictions and blind spots, "
        "and lock down a concrete, measurable KPI/target. End with one sharp diagnostic question."
    ),
    "REGENERATION": (
        " [STAGE 2: REGENERATION (BUILD) — GATE: Sustain execution & confidence (>=75) across check-ins to advance to MASTERY]. "
        "Act as a ruthless tactical execution coach. Enforce concrete time-bound commitments, reject excuses, "
        "audit follow-through against the locked KPI, and demand specific next actions."
    ),
    "MASTERY": (
        " [STAGE 3: MASTERY (RELEASE) — GATE: Operate with high-leverage autonomy & scale; sustained drop (<45) triggers demotion to REGENERATION]. "
        "Act as a boardroom strategist stress-testing 10x scale, systems, delegation, and second-order consequences. "
        "Challenge dependency and verify autonomous first-principles execution."
    ),
}


def require_admin(fn):
    @wraps(fn)
    def wrapper(*args, **kwargs):
        provided = request.headers.get("X-Admin-Key", "")
        if not ADMIN_API_KEY or provided != ADMIN_API_KEY:
            return jsonify({"error": "Unauthorized"}), 401
        return fn(*args, **kwargs)
    return wrapper


def normalize_phone(phone: str) -> str:
    return re.sub(r"[^\d+]", "", str(phone or "")).strip()


def get_or_create_user_state(phone_number: str) -> UserState:
    clean_phone = normalize_phone(phone_number)
    state = UserState.query.filter_by(phone_number=clean_phone).first()
    if state:
        return state

    whitelist = (
        SeatWhitelist.query.filter_by(phone_number=clean_phone, claimed=False)
        .order_by(SeatWhitelist.id.desc())
        .first()
    )
    if whitelist and whitelist.company and whitelist.company.has_open_seat():
        whitelist.claimed = True
        state = UserState(
            phone_number=clean_phone,
            company_id=whitelist.company.id,
            is_licensed=True,
            account_type="corporate",
            full_name=whitelist.full_name,
            department=whitelist.department,
            role_title=whitelist.role_title,
            onboarding_step="AWAIT_PRIMARY_KPI" if whitelist.full_name else "AWAIT_ROLE_DEPT",
            current_stage="AWAKENING",
            scan_step=1,
            scan_completed=False,
            momentum_score=50.0,
            confidence_index=50.0,
        )
    else:
        state = UserState(
            phone_number=clean_phone,
            is_licensed=True,
            account_type="solo",
            onboarding_step="ACTIVE",
            current_stage="AWAKENING",
            scan_step=1,
            scan_completed=False,
            momentum_score=50.0,
            confidence_index=50.0,
        )

    db.session.add(state)
    db.session.commit()
    return state


def handle_join_code(state: UserState, text: str) -> str | None:
    match = re.match(r"^\s*JOIN\s+([A-Z0-9_-]{3,40})\s*$", text.strip(), re.IGNORECASE)
    if not match:
        return None

    code = match.group(1).upper()
    company = Company.query.filter_by(invite_code=code).first()
    if not company:
        return f"Invite code '{code}' is invalid. Verify the code with your administrator."

    if state.company_id == company.id and state.is_licensed:
        return f"Already active under {company.name} ({code}). State your current bottleneck or KPI."

    if not company.has_open_seat():
        return f"No open seats available or license expired for {company.name} ({code})."

    state.company_id = company.id
    state.is_licensed = True
    state.account_type = "corporate"
    state.onboarding_step = "AWAIT_ROLE_DEPT"
    state.current_stage = "AWAKENING"
    state.scan_step = 1
    state.scan_completed = False
    db.session.commit()

    return (
        f"Seat claimed for {company.name} ({company.invite_code}). "
        f"Send your Full Name, Department, and Role in one message "
        f"(e.g., Chanda Mwila - Commercial - Regional Sales Manager)."
    )


def handle_corporate_onboarding(state: UserState, text: str) -> str | None:
    if state.account_type != "corporate" or state.onboarding_step == "ACTIVE":
        return None

    clean = text.strip()
    if state.onboarding_step == "AWAIT_ROLE_DEPT":
        parts = [p.strip() for p in re.split(r"\s*[-–—|/,]\s*", clean) if p.strip()]
        state.full_name = parts[0] if len(parts) >= 1 else clean
        state.department = parts[1] if len(parts) >= 2 else "General"
        state.role_title = parts[2] if len(parts) >= 3 else clean
        state.onboarding_step = "AWAIT_PRIMARY_KPI"
        db.session.commit()
        return (
            f"Profile recorded: {state.full_name} ({state.department} / {state.role_title}). "
            f"What is your single highest-leverage KPI or bottleneck over the next 30 days?"
        )

    if state.onboarding_step == "AWAIT_PRIMARY_KPI":
        state.primary_kpi = clean
        state.onboarding_step = "ACTIVE"
        state.current_stage = "AWAKENING"
        state.scan_step = 1
        state.scan_completed = False
        db.session.commit()
        return (
            f"30-day KPI locked: {state.primary_kpi}. "
            f"Entering Stage 1: Awakening (Scan). "
            f"Where is execution currently leaking between daily actions and this target?"
        )

    return None


def evaluate_stage_gates(state: UserState, message_text: str) -> None:
    """
    Enforces deterministic stage gates across:
      1. AWAKENING (Scan) -> 2. REGENERATION (Build) -> 3. MASTERY (Release)
    """
    state.checkins_count = (state.checkins_count or 0) + 1
    clean_text = (message_text or "").strip()

    if not state.primary_kpi and len(clean_text) >= 12 and (state.scan_step or 1) >= 2:
        state.primary_kpi = clean_text[:240]

    if float(state.momentum_score or 0.0) >= 75.0:
        state.high_momentum_streaks = (state.high_momentum_streaks or 0) + 1
    else:
        state.high_momentum_streaks = 0

    stage = (state.current_stage or "AWAKENING").upper()

    # Gate 1 -> Gate 2: AWAKENING -> REGENERATION
    if stage == "AWAKENING":
        if (state.scan_step or 1) < 3:
            state.scan_step = (state.scan_step or 1) + 1
        has_baseline = bool(state.primary_kpi or state.core_friction)
        if (state.scan_step or 1) >= 3 and state.checkins_count >= 3 and has_baseline:
            state.scan_completed = True
            state.current_stage = "REGENERATION"

    # Gate 2 -> Gate 3: REGENERATION -> MASTERY
    elif stage == "REGENERATION":
        meets_mastery_gate = (
            bool(state.scan_completed)
            and state.checkins_count >= 10
            and float(state.momentum_score or 0.0) >= 75.0
            and float(state.confidence_index or 0.0) >= 75.0
        )
        if meets_mastery_gate:
            state.current_stage = "MASTERY"

    # Gate 3 -> Gate 2: MASTERY -> REGENERATION (demotion on sustained drop)
    elif stage == "MASTERY":
        if (
            float(state.momentum_score or 0.0) < 45.0
            and (state.high_momentum_streaks or 0) == 0
            and state.checkins_count >= 12
        ):
            state.current_stage = "REGENERATION"

    db.session.commit()


@app.route("/", methods=["GET"])
def home():
    return jsonify({
        "status": "Vault 9 Backend is Live",
        "pillar": "Bridge Muunganisha",
        "brains": "OpenAI GPT-4o-mini (Primary) -> Claude 3.5 Sonnet -> Gemini 3.8 Flash",
        "persistence": "Active",
        "stages": ["AWAKENING", "REGENERATION", "MASTERY"],
        "telemetry": "Advanced (3-Stage Gates, Momentum-Tiered, Confidence Protocol, Auto-Multimodal Accessibility & Whisper Audio Enabled)"
    }), 200


@app.route("/privacy", methods=["GET"])
def privacy_policy():
    html = """<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <title>Privacy Policy - Vault 9 (Bridge Muunganisha)</title>
  <style>
    body {
      font-family: Arial, Helvetica, sans-serif;
      line-height: 1.6;
      max-width: 780px;
      margin: 40px auto;
      padding: 0 20px;
      color: #1f2937;
      background-color: #f9fafb;
    }
    h1, h2 {
      color: #111827;
    }
    .card {
      background: #ffffff;
      border: 1px solid #e5e7eb;
      border-radius: 8px;
      padding: 28px;
    }
  </style>
</head>
<body>
  <div class="card">
    <h1>Privacy Policy for Vault 9 (Bridge Muunganisha)</h1>
    <p><strong>Last Updated:</strong> November 23, 2026</p>

    <p>Vault 9 ("we," "our," or "us") provides an automated cognitive coaching and strategic execution service via WhatsApp. This Privacy Policy explains what information we collect, how we use it, and how you can request deletion of your data.</p>

    <h2>1. Information We Collect</h2>
    <ul>
      <li><strong>WhatsApp Contact &amp; Message Content:</strong> When you message Vault 9 on WhatsApp, we receive your phone number, message text, and audio voice notes (which are transcribed to text to generate responses).</li>
      <li><strong>Coaching &amp; Session State:</strong> We store recent conversation history and coaching state/telemetry used to maintain context and tailor responses.</li>
    </ul>

    <h2>2. How We Use Information</h2>
    <ul>
      <li>To transcribe voice messages, generate coaching responses, and match your preferred response format (voice or text).</li>
      <li>To operate, maintain, troubleshoot, and secure the Vault 9 service.</li>
      <li>We do not sell user data or use platform data for unauthorized profiling or data brokers.</li>
    </ul>

    <h2>3. Third-Party Service Providers</h2>
    <p>Messages and audio inputs may be transmitted to hosting and AI processing providers strictly as necessary to generate your requested coaching response and deliver WhatsApp messages.</p>

    <h2>4. Data Retention &amp; Deletion Instructions</h2>
    <p>We retain conversation and session records as needed to provide the service. To request deletion of your data, email <a href="mailto:smertverse@gmail.com">smertverse@gmail.com</a> with the subject line <strong>"Vault 9 Data Deletion Request"</strong> and include the WhatsApp phone number you used with Vault 9. We will process verified deletion requests promptly.</p>

    <h2>5. Contact</h2>
    <p>For privacy questions or data deletion requests, contact <a href="mailto:smertverse@gmail.com">smertverse@gmail.com</a>.</p>
  </div>
</body>
</html>"""
    return html, 200


@app.route("/terms", methods=["GET"])
def terms_of_service():
    html = """<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <title>Terms of Service - Vault 9 (Bridge Muunganisha)</title>
  <style>
    body {
      font-family: Arial, Helvetica, sans-serif;
      line-height: 1.6;
      max-width: 780px;
      margin: 40px auto;
      padding: 0 20px;
      color: #1f2937;
      background-color: #f9fafb;
    }
    h1, h2 {
      color: #111827;
    }
    .card {
      background: #ffffff;
      border: 1px solid #e5e7eb;
      border-radius: 8px;
      padding: 28px;
    }
  </style>
</head>
<body>
  <div class="card">
    <h1>Terms of Service for Vault 9 (Bridge Muunganisha)</h1>
    <p><strong>Last Updated:</strong> November 23, 2026</p>

    <p>By interacting with Vault 9 ("we," "our," or "us") via WhatsApp or related services, you agree to these Terms of Service.</p>

    <h2>1. Nature of the Service</h2>
    <p>Vault 9 provides automated cognitive coaching, strategic questioning, and execution accountability through text and voice messages. Responses are generated with AI systems and are intended for personal and strategic development only, not as legal, financial, medical, or clinical advice.</p>

    <h2>2. Acceptable Use</h2>
    <p>You agree to use Vault 9 lawfully and responsibly. Do not send unlawful, abusive, harmful, or disruptive traffic, or attempt to interfere with service operations.</p>

    <h2>3. Availability &amp; Updates</h2>
    <p>We may update, modify, suspend, or discontinue features or integrations at any time without prior notice, and we do not guarantee uninterrupted or error-free operation.</p>

    <h2>4. Limitation of Liability</h2>
    <p>To the fullest extent permitted by law, Vault 9 is provided "as is" without warranties of any kind, and we are not liable for decisions made or actions taken based on generated responses or service interruptions.</p>

    <h2>5. Contact</h2>
    <p>Questions about these terms can be sent to <a href="mailto:smertverse@gmail.com">smertverse@gmail.com</a>.</p>
  </div>
</body>
</html>"""
    return html, 200


@app.route("/data-deletion", methods=["GET"])
def data_deletion():
    html = """<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <title>User Data Deletion - Vault 9 (Bridge Muunganisha)</title>
  <style>
    body {
      font-family: Arial, Helvetica, sans-serif;
      line-height: 1.6;
      max-width: 780px;
      margin: 40px auto;
      padding: 0 20px;
      color: #1f2937;
      background-color: #f9fafb;
    }
    h1, h2 {
      color: #111827;
    }
    .card {
      background: #ffffff;
      border: 1px solid #e5e7eb;
      border-radius: 8px;
      padding: 28px;
    }
  </style>
</head>
<body>
  <div class="card">
    <h1>User Data Deletion Instructions - Vault 9 (Bridge Muunganisha)</h1>
    <p><strong>Last Updated:</strong> November 23, 2026</p>

    <p>Users of Vault 9 may request deletion of their stored WhatsApp conversation history and coaching state/telemetry data at any time.</p>

    <h2>How to Request Data Deletion</h2>
    <ol>
      <li>Send an email to <a href="mailto:smertverse@gmail.com">smertverse@gmail.com</a>.</li>
      <li>Use the subject line: <strong>Vault 9 Data Deletion Request</strong>.</li>
      <li>Include the <strong>WhatsApp phone number</strong> (with country code) used to interact with Vault 9 so we can locate and delete matching records.</li>
    </ol>

    <h2>What Data Is Deleted</h2>
    <p>Upon verifying your request, we delete associated stored message history and coaching session state tied to that WhatsApp phone number, except where retention is required by law or security logs.</p>

    <h2>Support Contact</h2>
    <p>For assistance with data deletion requests, contact <a href="mailto:smertverse@gmail.com">smertverse@gmail.com</a>.</p>
  </div>
</body>
</html>"""
    return html, 200


@app.post("/admin/companies")
@require_admin
def create_company():
    data = request.get_json(force=True) or {}
    name = (data.get("name") or "").strip()
    invite_code = (data.get("invite_code") or "").strip().upper()
    if not name or not invite_code:
        return jsonify({"error": "name and invite_code are required"}), 400

    if Company.query.filter_by(invite_code=invite_code).first():
        return jsonify({"error": "invite_code already exists"}), 409

    expires_at = None
    if data.get("expires_at"):
        expires_at = datetime.fromisoformat(data["expires_at"])

    company = Company(
        name=name,
        invite_code=invite_code,
        industry=data.get("industry", "General Enterprise"),
        corporate_context=data.get("corporate_context", ""),
        license_tier=data.get("license_tier", "corporate_pilot"),
        max_seats=int(data.get("max_seats", 50)),
        expires_at=expires_at,
    )
    db.session.add(company)
    db.session.commit()
    return jsonify({
        "id": company.id,
        "name": company.name,
        "invite_code": company.invite_code,
        "max_seats": company.max_seats,
    }), 201


@app.post("/admin/companies/<invite_code>/whitelist")
@require_admin
def add_company_whitelist(invite_code):
    company = Company.query.filter_by(invite_code=invite_code.upper()).first()
    if not company:
        return jsonify({"error": "Company not found"}), 404

    data = request.get_json(force=True) or {}
    added = 0
    for item in data.get("employees", []):
        phone = normalize_phone(item.get("phone_number", ""))
        if not phone:
            continue
        db.session.add(SeatWhitelist(
            company_id=company.id,
            phone_number=phone,
            full_name=item.get("full_name", ""),
            department=item.get("department", ""),
            role_title=item.get("role_title", ""),
        ))
        added += 1

    db.session.commit()
    return jsonify({"company": company.name, "whitelisted_added": added}), 201


@app.get("/admin/companies/<invite_code>/telemetry")
@require_admin
def company_telemetry(invite_code):
    company = Company.query.filter_by(invite_code=invite_code.upper()).first()
    if not company:
        return jsonify({"error": "Company not found"}), 404

    users = UserState.query.filter_by(company_id=company.id, is_licensed=True).all()
    count = len(users)
    avg_momentum = round(sum(float(u.momentum_score or 0.0) for u in users) / count, 1) if count else 0.0
    avg_confidence = round(sum(float(u.confidence_index or 0.0) for u in users) / count, 1) if count else 0.0

    return jsonify({
        "company": company.name,
        "invite_code": company.invite_code,
        "seats_used": count,
        "max_seats": company.max_seats,
        "avg_momentum_score": avg_momentum,
        "avg_confidence_index": avg_confidence,
        "stage_breakdown": {
            "AWAKENING": sum(1 for u in users if u.current_stage == "AWAKENING"),
            "REGENERATION": sum(1 for u in users if u.current_stage == "REGENERATION"),
            "MASTERY": sum(1 for u in users if u.current_stage == "MASTERY"),
        },
        "recent_frictions": [u.core_friction for u in users if u.core_friction][:10],
    })


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


@app.route("/webhook", methods=["POST"])
def webhook():
    body = request.get_json(silent=True)
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
                        msg_type = message.get("type")

                        message_text = None

                        if msg_type == "text":
                            message_text = message.get("text", {}).get("body")
                        elif msg_type == "audio":
                            audio_id = message.get("audio", {}).get("id")
                            message_text = transcribe_whatsapp_audio(audio_id)

                        if sender_phone and message_text:
                            process_incoming_message(sender_phone, message_text, incoming_type=msg_type)

        return jsonify({"status": "EVENT_RECEIVED"}), 200
    except Exception as e:
        print(f"Webhook Error: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500


def transcribe_whatsapp_audio(audio_id):
    """Downloads a WhatsApp audio file using Meta Graph API and transcribes it via OpenAI Whisper."""
    if not openai_client or not audio_id:
        return "[Audio message received, but transcription unavailable]"

    try:
        media_url_endpoint = f"https://graph.facebook.com/v21.0/{audio_id}"
        headers = {"Authorization": f"Bearer {WHATSAPP_ACCESS_TOKEN}"}
        resp = requests.get(media_url_endpoint, headers=headers, timeout=(5, 15))
        media_data = resp.json()
        download_url = media_data.get("url")

        if not download_url:
            return "[Failed to retrieve audio download URL from Meta]"

        audio_resp = requests.get(download_url, headers=headers, timeout=(5, 30))
        audio_file_bytes = io.BytesIO(audio_resp.content)
        audio_file_bytes.name = "voice_note.ogg"

        transcript = openai_client.audio.transcriptions.create(
            model="whisper-1",
            file=audio_file_bytes
        )
        print(f"Whisper Transcription Success: {transcript.text}")
        return transcript.text
    except Exception as e:
        print(f"Audio transcription error: {e}")
        return "[Error processing voice note transcription]"


def analyze_user_telemetry(sender_phone, message_text):
    """Scans incoming text to extract cognitive telemetry, confidence index, and compromised capital."""
    clean_phone = normalize_phone(sender_phone)
    state = get_or_create_user_state(clean_phone)

    if not openai_client:
        return state

    system_prompt = (
        "Analyze the following user input and return a strict JSON object with these keys: "
        "'momentum_shift' (float between -5.0 and +5.0 representing change in drive), "
        "'confidence_index' (float between 0.0 and 100.0 representing the user's certainty, conviction, and lack of hesitation), "
        "'cognitive_load' (one of: 'strategic', 'tactical', 'overwhelmed'), "
        "'emotional_valence' (one of: 'driven', 'stressed', 'fatigued', 'focused', 'neutral'), "
        "'core_friction' (a concise 1-sentence summary of their bottleneck), "
        "'compromised_capital' (name of the specific Capital of Wealth or Pillar under threat, e.g., 'Financial', 'Physical', 'Reputation')."
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

        current_score = float(state.momentum_score or 50.0)
        shift = float(data.get('momentum_shift', 0) or 0)
        state.momentum_score = max(0.0, min(100.0, current_score + shift))

        raw_conf = data.get('confidence_index', state.confidence_index if state.confidence_index is not None else 50.0)
        conf_val = max(0.0, min(100.0, float(raw_conf or 50.0)))
        state.confidence_index = round((float(state.confidence_index or 50.0) * 0.6) + (conf_val * 0.4), 1)

        state.cognitive_load = data.get('cognitive_load', 'balanced')
        state.emotional_valence = data.get('emotional_valence', 'neutral')
        if data.get('core_friction'):
            state.core_friction = data.get('core_friction')
        if data.get('compromised_capital'):
            state.compromised_capital = data.get('compromised_capital')

        db.session.commit()
        return state
    except Exception as e:
        db.session.rollback()
        print(f"Telemetry scanning error: {e}")
        return state


def process_incoming_message(sender_phone, message_text, incoming_type="text"):
    clean_phone = normalize_phone(sender_phone)
    user_pref = "voice" if incoming_type == "audio" else "text"
    reply_text = None
    ai_success = False

    try:
        user_state = get_or_create_user_state(clean_phone)

        # Gate 0A: Corporate seat activation code ('JOIN <CODE>')
        join_reply = handle_join_code(user_state, message_text)
        if join_reply:
            reply_text = join_reply
            db.session.add(ConversationHistory(sender_phone=clean_phone, role='user', message=message_text))
            db.session.add(ConversationHistory(sender_phone=clean_phone, role='assistant', message=reply_text))
            db.session.commit()
            send_whatsapp_multimodal_response(sender_phone, reply_text, preference=user_pref)
            return

        # Gate 0B: 3-step corporate onboarding (Role/Dept -> 30-day KPI)
        onboarding_reply = handle_corporate_onboarding(user_state, message_text)
        if onboarding_reply:
            reply_text = onboarding_reply
            db.session.add(ConversationHistory(sender_phone=clean_phone, role='user', message=message_text))
            db.session.add(ConversationHistory(sender_phone=clean_phone, role='assistant', message=reply_text))
            db.session.commit()
            send_whatsapp_multimodal_response(sender_phone, reply_text, preference=user_pref)
            return

        # Analyze telemetry & evaluate stage gates (AWAKENING -> REGENERATION -> MASTERY)
        user_state = analyze_user_telemetry(clean_phone, message_text)
        evaluate_stage_gates(user_state, message_text)

        momentum = float(user_state.momentum_score) if user_state else 50.0
        if momentum < 40.0:
            persona_tier_instruction = (
                " [MOMENTUM ALERT: LOW (<40)]. Drop all pleasantries. Act as an uncompromising tactical drill sergeant. "
                "Focus purely on immediate friction removal, cutting noise, and enforcing basic execution blocks."
            )
        elif momentum > 80.0:
            persona_tier_instruction = (
                " [MOMENTUM ALERT: PEAK (>80)]. The user is performing well. Do not let them get comfortable or complacent. "
                "Attack their ambition ceiling. Demand to know why they aren't 10x-ing their scale or expanding into new markets."
            )
        else:
            persona_tier_instruction = " [MOMENTUM ALERT: STABLE]. Maintain rigorous, direct cognitive challenge."

        company_context = ""
        if user_state and user_state.company:
            company_context = (
                f"\n[CORPORATE TENANT: {user_state.company.name} ({user_state.company.industry}) | "
                f"Context: {user_state.company.corporate_context or 'Drive execution & accountability'} | "
                f"User: {user_state.full_name or 'Employee'} | Dept: {user_state.department or 'General'} | "
                f"Role: {user_state.role_title or 'Staff'} | KPI: {user_state.primary_kpi or 'Pending'}]"
            )

        stage_name = (user_state.current_stage or "AWAKENING").upper() if user_state else "AWAKENING"
        stage_directive = STAGE_DIRECTIVES.get(stage_name, STAGE_DIRECTIVES["AWAKENING"])

        state_context = ""
        if user_state:
            state_context = (
                f"{company_context}"
                f"\n[USER TELEMETRY - Stage: {stage_name} (Step {user_state.scan_step}/3, Check-ins: {user_state.checkins_count}), "
                f"Momentum: {user_state.momentum_score}/100, Confidence: {user_state.confidence_index}/100, "
                f"Load: {user_state.cognitive_load}, State: {user_state.emotional_valence}, "
                f"Compromised Capital: {user_state.compromised_capital}, Friction: {user_state.core_friction}]"
                f"{stage_directive}"
                f"{persona_tier_instruction}"
            )

        recent_chats = ConversationHistory.query.filter_by(sender_phone=clean_phone)\
            .order_by(ConversationHistory.id.desc()).limit(5).all()
        recent_chats.reverse()

        full_system_instruction = BASE_SYSTEM_INSTRUCTION + state_context

        # --- ATTEMPT 1: OpenAI GPT-4o-mini ---
        if openai_client:
            try:
                openai_messages = [{"role": "system", "content": full_system_instruction}]
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
            except Exception as openai_err:
                print(f"OpenAI failed ({openai_err}). Routing to Claude...")

        # --- ATTEMPT 2: Claude 3.5 Sonnet ---
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
                    system=full_system_instruction,
                    messages=anthropic_messages
                )
                reply_text = response.content[0].text
                ai_success = True
            except Exception as claude_err:
                print(f"Claude failed ({claude_err}). Routing to Gemini...")

        # --- ATTEMPT 3: Gemini 3.8 Flash ---
        if not ai_success and GEMINI_API_KEY:
            try:
                contents = []
                for chat in recent_chats:
                    gemini_role = "user" if chat.role == "user" else "model"
                    contents.append({"role": gemini_role, "parts": [{"text": chat.message}]})
                contents.append({"role": "user", "parts": [{"text": message_text}]})

                api_url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-3.8-flash:generateContent?key={GEMINI_API_KEY}"
                payload = {
                    "system_instruction": {"parts": [{"text": full_system_instruction}]},
                    "contents": contents,
                    "generationConfig": {"temperature": 0.85, "maxOutputTokens": 300}
                }
                resp = requests.post(api_url, json=payload, timeout=(5, 30))
                resp_data = resp.json()
                if resp.status_code == 200:
                    candidates = resp_data.get("candidates", [])
                    if candidates:
                        reply_text = candidates[0]["content"]["parts"][0]["text"]
                        ai_success = True
            except Exception as gemini_err:
                print(f"Gemini failed ({gemini_err}).")

        if not reply_text:
            reply_text = "🧠 *Vault 9 Error*: All upstream AI services are currently unavailable."

        # Save conversation history
        user_msg = ConversationHistory(sender_phone=clean_phone, role='user', message=message_text)
        assistant_msg = ConversationHistory(sender_phone=clean_phone, role='assistant', message=reply_text)
        db.session.add(user_msg)
        db.session.add(assistant_msg)
        db.session.commit()

    except Exception as e:
        db.session.rollback()
        print(f"Server / DB Error: {e}")
        reply_text = f"🧠 *Vault 9 Error*: {str(e)}"

    send_whatsapp_multimodal_response(sender_phone, reply_text, preference=user_pref)


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
    response = requests.post(url, headers=headers, json=payload, timeout=(5, 15))
    if response.status_code != 200:
        print(f"Failed to send WhatsApp message: {response.json()}")


def send_whatsapp_multimodal_response(recipient_phone, text_message, preference="text"):
    """
    Handles universal accessibility routing:
      - 'text': Standard WhatsApp text message.
      - 'voice': Converts text response to a true Opus/Ogg voice note via OpenAI TTS.
    """
    if preference == "voice" and openai_client:
        try:
            speech_file_path = "/tmp/vault9_response.ogg"
            response = openai_client.audio.speech.create(
                model="tts-1",
                voice="onyx",
                input=text_message,
                response_format="opus"
            )
            response.stream_to_file(speech_file_path)

            upload_url = f"https://graph.facebook.com/v21.0/{PHONE_NUMBER_ID}/media"
            headers = {"Authorization": f"Bearer {WHATSAPP_ACCESS_TOKEN}"}

            with open(speech_file_path, "rb") as audio_file:
                files = {
                    "file": ("vault9_response.ogg", audio_file, "audio/ogg")
                }
                data = {
                    "messaging_product": "whatsapp",
                    "type": "audio"
                }
                upload_resp = requests.post(upload_url, headers=headers, files=files, data=data, timeout=(5, 30))
                media_data = upload_resp.json()
                media_id = media_data.get("id")

            if media_id:
                msg_url = f"https://graph.facebook.com/v21.0/{PHONE_NUMBER_ID}/messages"
                msg_payload = {
                    "messaging_product": "whatsapp",
                    "to": recipient_phone,
                    "type": "audio",
                    "audio": {"id": media_id}
                }
                msg_resp = requests.post(
                    msg_url,
                    headers={"Authorization": f"Bearer {WHATSAPP_ACCESS_TOKEN}", "Content-Type": "application/json"},
                    json=msg_payload,
                    timeout=(5, 15)
                )
                if msg_resp.status_code != 200:
                    print(f"Failed to send WhatsApp audio message, falling back to text: {msg_resp.json()}")
                    send_whatsapp_message(recipient_phone, text_message)
            else:
                print(f"Failed to upload audio media to Meta ({media_data}), falling back to text.")
                send_whatsapp_message(recipient_phone, text_message)
        except Exception as e:
            print(f"Multimodal TTS error ({e}), falling back to text.")
            send_whatsapp_message(recipient_phone, text_message)
    else:
        send_whatsapp_message(recipient_phone, text_message)


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 10000)))