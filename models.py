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
    message_type = db.Column(db.String(30), nullable=False)  # text, image, document, location
    content = db.Column(db.Text, nullable=True)
    status = db.Column(db.String(20), default='PENDING')  # PENDING, PROCESSED, FAILED
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))