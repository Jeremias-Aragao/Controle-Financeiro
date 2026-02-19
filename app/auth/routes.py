from __future__ import annotations

from datetime import datetime
import os

from flask import Blueprint, flash, redirect, render_template, request, session, url_for
from flask_login import current_user, login_required, login_user, logout_user
from werkzeug.security import check_password_hash, generate_password_hash

from ..extensions import db
from ..models import Membership, Organization, User

bp = Blueprint("auth", __name__)


def _safe_next_url() -> str | None:
    next_url = request.args.get("next") or request.form.get("next")
    if next_url and next_url.startswith("/") and not next_url.startswith("//"):
        return next_url
    return None


@bp.route("/register", methods=["GET", "POST"])
def register():
    if current_user.is_authenticated:
        return redirect(url_for("finance.home"))

    allow_first_admin = (os.getenv("ALLOW_FIRST_ADMIN_FROM_REGISTER") or "").lower() in {"1", "true", "yes", "on"}
    platform_admin_exists = Membership.query.filter_by(role="PLATFORM_ADMIN").first() is not None
    can_register_first_admin = allow_first_admin and not platform_admin_exists

    if request.method == "POST":
        name = request.form.get("name", "").strip()
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")
        wants_admin = request.form.get("create_as_admin") == "on"

        if not name or not email or not password:
            flash("Preencha nome, e-mail e senha.")
            return redirect(url_for("auth.register"))

        if User.query.filter_by(email=email).first():
            flash("Este e-mail já está cadastrado. Faça login.")
            return redirect(url_for("auth.login"))

        user = User(name=name, email=email, password_hash=generate_password_hash(password))
        db.session.add(user)
        db.session.commit()

        if wants_admin and can_register_first_admin:
            org = Organization.query.filter_by(slug="platform").first()
            if not org:
                org = Organization(name="Admin Org", slug="platform", plan="ENTERPRISE", status="active")
                db.session.add(org)
                db.session.commit()
            db.session.add(Membership(user_id=user.id, org_id=org.id, role="PLATFORM_ADMIN"))
            db.session.commit()
            flash("Conta admin criada com sucesso! Faça login.")
        else:
            flash("Conta criada! Agora faça login.")

        return redirect(url_for("auth.login"))

    return render_template("register.html", can_register_first_admin=can_register_first_admin, datetime=datetime)


@bp.route("/login", methods=["GET", "POST"])
def login():
    if current_user.is_authenticated:
        return redirect(url_for("finance.home"))

    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")

        user = User.query.filter_by(email=email).first()
        if not user or not check_password_hash(user.password_hash, password):
            flash("E-mail ou senha inválidos.")
            return redirect(url_for("auth.login"))

        login_user(user)
        next_url = _safe_next_url()
        if next_url:
            return redirect(next_url)

        memberships = Membership.query.filter_by(user_id=user.id).all()
        if len(memberships) == 1:
            session["active_org_id"] = memberships[0].org_id
            return redirect(url_for("finance.home"))
        return redirect(url_for("org.select_org"))

    return render_template("login.html")


@bp.route("/logout")
@login_required
def logout():
    session.pop("active_org_id", None)
    logout_user()
    flash("Você saiu.")
    return redirect(url_for("auth.login"))
