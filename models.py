from datetime import datetime, timezone
from database import db


def utc_now():
    return datetime.now(timezone.utc)


class Company(db.Model):
    __tablename__ = 'companies'

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(160), nullable=False)
    invite_code = db.Column(db.String(64), unique=True, nullable=False, index=True)
    industry = db.Column(db.String(120), default='General Enterprise')
    corporate_context = db.Column(db.Text, nullable=True)
    license_tier = db.Column(db.String(64), default='corporate_pilot')
    max_seats = db.Column(db.Integer, default=50, nullable=False)
    is_active = db.Column(db.Boolean, default=True, nullable=False)
    expires_at = db.Column(db.DateTime, nullable=True)
    created_at = db.Column(db.DateTime, default=utc_now)

    users = db.relationship('UserState', backref='company', lazy=True)
    whitelists = db.relationship('SeatWhitelist', backref='company', lazy=True, cascade='all, delete-orphan')

    def active_seat_count(self) -> int:
        return sum(1 for u in self.users if u.is_licensed)

    def has_open_seat(self) -> bool:
        if not self.is_active:
            return False
        if self.expires_at:
            now = utc_now()
            exp = self.expires_at if self.expires_at.tzinfo else self.expires_at.replace(tzinfo=timezone.utc)
            if now > exp:
                return False
        return self.active_seat_count() < self.max_seats


class SeatWhitelist(db.Model):
    __tablename__ = 'seat_whitelists'

    id = db.Column(db.Integer, primary_key=True)
    company_id = db.Column(db.Integer, db.ForeignKey('companies.id'), nullable=False, index=True)
    phone_number = db.Column(db.String(32), nullable=False, index=True)
    full_name = db.Column(db.String(160), nullable=True)
    department = db.Column(db.String(120), nullable=True)
    role_title = db.Column(db.String(120), nullable=True)
    claimed = db.Column(db.Boolean, default=False, nullable=False)
    created_at = db.Column(db.DateTime, default=utc_now)


class Farmer(db.Model):
    __tablename__ = 'farmers'

    id = db.Column(db.Integer, primary_key=True)
    phone_number = db.Column(db.String(32), unique=True, nullable=False, index=True)
    name = db.Column(db.String(100), nullable=True)
    location = db.Column(db.String(100), nullable=True)
    created_at = db.Column(db.DateTime, default=utc_now)

    audits = db.relationship('AuditSubmission', backref='farmer', lazy=True)


class AuditSubmission(db.Model):
    __tablename__ = 'audit_submissions'

    id = db.Column(db.Integer, primary_key=True)
    farmer_id = db.Column(db.Integer, db.ForeignKey('farmers.id'), nullable=False)
    raw_payload = db.Column(db.JSON, nullable=False)
    message_type = db.Column(db.String(30), nullable=False)
    content = db.Column(db.Text, nullable=True)
    status = db.Column(db.String(20), default='PENDING')
    created_at = db.Column(db.DateTime, default=utc_now)


class UserState(db.Model):
    __tablename__ = 'user_states'

    id = db.Column(db.Integer, primary_key=True)
    phone_number = db.Column(db.String(32), unique=True, nullable=False, index=True)

    # Corporate licensing & employee identity
    company_id = db.Column(db.Integer, db.ForeignKey('companies.id'), nullable=True, index=True)
    is_licensed = db.Column(db.Boolean, default=True, nullable=False)
    account_type = db.Column(db.String(24), default='solo', nullable=False)  # 'solo' | 'corporate'
    full_name = db.Column(db.String(160), nullable=True)
    department = db.Column(db.String(120), nullable=True)
    role_title = db.Column(db.String(120), nullable=True)
    primary_kpi = db.Column(db.Text, nullable=True)

    # Onboarding state: 'NONE' | 'AWAIT_ROLE_DEPT' | 'AWAIT_PRIMARY_KPI' | 'ACTIVE'
    onboarding_step = db.Column(db.String(24), default='ACTIVE', nullable=False)

    # 3-Stage Engine: 'AWAKENING' (Scan) -> 'REGENERATION' (Build) -> 'MASTERY' (Release)
    current_stage = db.Column(db.String(24), default='AWAKENING', nullable=False)
    scan_step = db.Column(db.Integer, default=1, nullable=False)  # 1..3 during AWAKENING
    scan_completed = db.Column(db.Boolean, default=False, nullable=False)

    # Core coaching & telemetry state
    momentum_score = db.Column(db.Float, default=50.0, nullable=False)  # 0 to 100 scale
    confidence_index = db.Column(db.Float, default=50.0, nullable=False)  # 0 to 100 scale
    cognitive_load = db.Column(db.String(20), default='balanced')  # strategic, tactical, overwhelmed, balanced
    emotional_valence = db.Column(db.String(20), default='neutral')  # driven, stressed, fatigued, focused, neutral
    core_friction = db.Column(db.Text, nullable=True)
    compromised_capital = db.Column(db.String(50), default='Financial')  # Tracks 9 Capitals / 7 Pillars under threat
    checkins_count = db.Column(db.Integer, default=0, nullable=False)
    high_momentum_streaks = db.Column(db.Integer, default=0, nullable=False)
    last_updated = db.Column(db.DateTime, default=utc_now, onupdate=utc_now)


class ConversationHistory(db.Model):
    __tablename__ = 'conversation_histories'

    id = db.Column(db.Integer, primary_key=True)
    sender_phone = db.Column(db.String(50), index=True, nullable=False)
    role = db.Column(db.String(20), nullable=False)  # 'user' or 'assistant'
    message = db.Column(db.Text, nullable=False)
    created_at = db.Column(db.DateTime, default=utc_now, index=True)