from __future__ import annotations

import os
from datetime import datetime

from flask import Flask, session
from werkzeug.security import generate_password_hash

from .admin.routes import bp as admin_bp
from .auth.routes import bp as auth_bp
from .billing.routes import bp as billing_bp
from .billing.routes import webhooks_bp
from .cli import create_admin, promote_admin
from .decorators import enforce_billing_gate
from .extensions import db, login_manager, migrate
from .finance.routes import bp as finance_bp
from .models import Membership, Organization, User
from .org.routes import bp as org_bp


def _env_is_true(value: str | None) -> bool:
    return (value or "").strip().lower() in {"1", "true", "yes", "on"}


def _is_production_env() -> bool:
    return _env_is_true(os.getenv("RENDER")) or os.getenv("FLASK_ENV", "").lower() == "production"


def _ensure_platform_admin() -> None:
    if Membership.query.filter_by(role="PLATFORM_ADMIN").first():
        return

    email = os.getenv("ADMIN_EMAIL")
    password = os.getenv("ADMIN_PASSWORD")
    if not email or not password:
        return

    user = User.query.filter_by(email=email.strip().lower()).first()
    if not user:
        user = User(
            name="Platform Admin",
            email=email.strip().lower(),
            password_hash=generate_password_hash(password),
            is_admin=True,
        )
        db.session.add(user)
        db.session.commit()

    org = Organization.query.filter_by(slug="platform").first()
    if not org:
        org = Organization(name="Admin Org", slug="platform", plan="ENTERPRISE", status="active")
        db.session.add(org)
        db.session.commit()

    db.session.add(Membership(user_id=user.id, org_id=org.id, role="PLATFORM_ADMIN"))
    db.session.commit()




def _current_user_is_platform_admin() -> bool:
    from flask_login import current_user

    if not current_user.is_authenticated:
        return False
    return Membership.query.filter_by(user_id=current_user.id, role="PLATFORM_ADMIN").first() is not None


def create_app() -> Flask:
    app = Flask(__name__, template_folder="../templates", static_folder="../static")

    database_url = os.getenv("DATABASE_URL", "sqlite:///local.db")
    if database_url.startswith("postgres://"):
        database_url = database_url.replace("postgres://", "postgresql://", 1)

    app.config["SQLALCHEMY_DATABASE_URI"] = database_url
    app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

    secret_key = os.getenv("SECRET_KEY")
    if _is_production_env() and not secret_key:
        raise RuntimeError("SECRET_KEY é obrigatória em produção.")
    app.config["SECRET_KEY"] = secret_key or "magnata-r02-dev-change-me"

    db.init_app(app)
    login_manager.init_app(app)
    migrate.init_app(app, db)
    login_manager.login_view = "auth.login"

    @login_manager.user_loader
    def load_user(user_id: str):
        try:
            return User.query.get(int(user_id))
        except Exception:
            return None

    app.register_blueprint(auth_bp)
    app.register_blueprint(finance_bp)
    app.register_blueprint(org_bp)
    app.register_blueprint(admin_bp)
    app.register_blueprint(billing_bp)
    app.register_blueprint(webhooks_bp)

    app.cli.add_command(create_admin)
    app.cli.add_command(promote_admin)

    @app.before_request
    def _before_request_guard():
        return enforce_billing_gate()

    @app.context_processor
    def inject_globals():
        return {"datetime": datetime, "active_org_id": session.get("active_org_id"), "is_platform_admin": _current_user_is_platform_admin()}

    with app.app_context():
        db.create_all()
        _ensure_platform_admin()

    return app
