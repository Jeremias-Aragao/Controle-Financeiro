from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from flask_login import UserMixin

from .extensions import db


class User(UserMixin, db.Model):
    __tablename__ = "users"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), nullable=False)
    email = db.Column(db.String(180), unique=True, nullable=False, index=True)
    password_hash = db.Column(db.String(255), nullable=False)
    is_admin = db.Column(db.Boolean, nullable=False, default=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    memberships = db.relationship("Membership", back_populates="user", cascade="all, delete-orphan")


class Organization(db.Model):
    __tablename__ = "organizations"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(140), nullable=False)
    slug = db.Column(db.String(160), unique=True, nullable=False, index=True)
    plan = db.Column(db.String(20), nullable=False, default="FREE")
    status = db.Column(db.String(20), nullable=False, default="active")
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    memberships = db.relationship("Membership", back_populates="org", cascade="all, delete-orphan")


class Membership(db.Model):
    __tablename__ = "memberships"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), index=True, nullable=False)
    org_id = db.Column(db.Integer, db.ForeignKey("organizations.id"), index=True, nullable=False)
    role = db.Column(db.String(30), nullable=False, default="ORG_USER")
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    user = db.relationship("User", back_populates="memberships")
    org = db.relationship("Organization", back_populates="memberships")


class OrgConfig(db.Model):
    __tablename__ = "org_config"

    id = db.Column(db.Integer, primary_key=True)
    org_id = db.Column(db.Integer, db.ForeignKey("organizations.id"), unique=True, nullable=False)
    saldo_inicial = db.Column(db.Float, default=0.0)
    competencia_inicio = db.Column(db.String(7), nullable=False)


class Lancamento(db.Model):
    __tablename__ = "lancamentos"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), index=True, nullable=False)
    org_id = db.Column(db.Integer, db.ForeignKey("organizations.id"), index=True, nullable=False)
    created_by_user_id = db.Column(db.Integer, db.ForeignKey("users.id"), index=True)

    tipo = db.Column(db.String(20), nullable=False)
    descricao = db.Column(db.String(255), nullable=False)
    categoria = db.Column(db.String(120))
    competencia = db.Column(db.String(7), index=True, nullable=False)
    data_evento = db.Column(db.String(10), nullable=False)
    valor = db.Column(db.Float, nullable=False)

    status = db.Column(db.String(20), nullable=False, default="PENDENTE")
    data_baixa = db.Column(db.String(10))

    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class Subscription(db.Model):
    __tablename__ = "subscriptions"

    id = db.Column(db.Integer, primary_key=True)
    org_id = db.Column(db.Integer, db.ForeignKey("organizations.id"), unique=True, nullable=False)
    plan = db.Column(db.String(20), nullable=False, default="FREE")
    status = db.Column(db.String(20), nullable=False, default="active")
    current_period_end = db.Column(db.DateTime)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class PaymentAttempt(db.Model):
    __tablename__ = "payment_attempts"

    id = db.Column(db.Integer, primary_key=True)
    org_id = db.Column(db.Integer, db.ForeignKey("organizations.id"), index=True, nullable=False)
    mp_payment_id = db.Column(db.String(120), index=True)
    amount = db.Column(db.Numeric(10, 2), nullable=False, default=Decimal("0.00"))
    status = db.Column(db.String(20), nullable=False, default="created")
    qr_code_data = db.Column(db.Text)
    pix_copia_cola = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    paid_at = db.Column(db.DateTime)


class InviteToken(db.Model):
    __tablename__ = "invite_tokens"

    id = db.Column(db.Integer, primary_key=True)
    org_id = db.Column(db.Integer, db.ForeignKey("organizations.id"), index=True, nullable=False)
    invited_by_user_id = db.Column(db.Integer, db.ForeignKey("users.id"), index=True, nullable=False)
    token_hash = db.Column(db.String(255), unique=True, nullable=False, index=True)
    role = db.Column(db.String(30), nullable=False, default="ORG_USER")
    expires_at = db.Column(db.DateTime, nullable=False)
    used_at = db.Column(db.DateTime)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)


class AdminAuditLog(db.Model):
    __tablename__ = "admin_audit_logs"

    id = db.Column(db.Integer, primary_key=True)
    admin_user_id = db.Column(db.Integer, db.ForeignKey("users.id"), index=True, nullable=False)
    action = db.Column(db.String(120), nullable=False)
    org_id = db.Column(db.Integer, db.ForeignKey("organizations.id"), index=True)
    payload_json = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
