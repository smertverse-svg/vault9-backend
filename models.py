from datetime import datetime, timezone
from database import db

class Farmer(db.Model):
    __tablename__ = 'farmers'

    id = db.Column(db.Integer, primary_key=True)
    phone_number = db.Column(db.String(20), unique=True, nullable=False, index=True)
    name = db.Column(db.String(100), nullable=True)
    location = db.Column(db.String(100), nullable=True)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))

    audits = db.relationship('AuditSubmission', backref='farmer', lazy=True)

class AuditSubmission(db.Model):
    __tablename__ = 'audit_submissions'

    id = db.Column(db.Integer, primary_key=True)
    farmer_id = db.Column(db.Integer, db.ForeignKey('farmers.id'), nullable=False)
    raw_payload = db.Column(db.JSON, nullable=False)
    message_type = db.Column(db.String(30), nullable=False)
    content = db.Column(db.Text, nullable=True)
    status = db.Column(db.String(20), default='PENDING')
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))

class UserState(db.Model):
    __tablename__ = 'user_states'
    
    id = db.Column(db.Integer, primary_key=True)
    phone_number = db.Column(db.String(20), unique=True, nullable=False, index=True)
    momentum_score = db.Column(db.Float, default=50.0)
    cognitive_load = db.Column(db.String(20), default='balanced')
    emotional_valence = db.Column(db.String(20), default='neutral')
    core_friction = db.Column(db.Text, nullable=True)
    last_updated = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))

class ConversationHistory(db.Model):
    __tablename__ = 'conversation_histories'
    
    id = db.Column(db.Integer, primary_key=True)
    sender_phone = db.Column(db.String(50), index=True, nullable=False)
    role = db.Column(db.String(20), nullable=False)
    message = db.Column(db.Text, nullable=False)