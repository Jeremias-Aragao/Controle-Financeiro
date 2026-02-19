from __future__ import annotations

import json
import re
from datetime import datetime

from flask import Blueprint, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required
from werkzeug.security import generate_password_hash

from ..decorators import require_role
from ..extensions import db
from ..models import AdminAuditLog, Membership, Organization, Subscription, User

bp = Blueprint("admin", __name__, url_prefix="/admin")


def slugify(value: str) -> str:
    value = re.sub(r"[^a-zA-Z0-9\s-]", "", value).strip().lower()
    return re.sub(r"[\s_-]+", "-", value)


def audit(action: str, org_id: int | None = None, payload: dict | None = None) -> None:
    db.session.add(
        AdminAuditLog(
            admin_user_id=current_user.id,
            action=action,
            org_id=org_id,
            payload_json=json.dumps(payload or {}, ensure_ascii=False),
        )
    )
    db.session.commit()


@bp.route("/dashboard")
@login_required
@require_role("PLATFORM_ADMIN")
def dashboard():
    orgs = Organization.query.order_by(Organization.created_at.desc()).all()
    return render_template("admin_dashboard.html", orgs=orgs)


@bp.route("/org/create", methods=["GET", "POST"])
@login_required
@require_role("PLATFORM_ADMIN")
def create_org():
    if request.method == "POST":
        name = request.form.get("name", "").strip()
        admin_email = request.form.get("admin_email", "").strip().lower()
        admin_name = request.form.get("admin_name", "").strip() or "Org Admin"
        admin_password = request.form.get("admin_password", "").strip()
        plan = request.form.get("plan", "FREE")
        slug = slugify(name)

        if not name or not slug:
            flash("Nome da organização inválido.")
            return redirect(url_for("admin.create_org"))
        if Organization.query.filter_by(slug=slug).first():
            flash("Já existe uma organização com esse nome/slug.")
            return redirect(url_for("admin.create_org"))

        org = Organization(name=name, slug=slug, plan=plan, status="active")
        db.session.add(org)
        db.session.commit()

        user = User.query.filter_by(email=admin_email).first()
        if not user:
            if not admin_password:
                flash("Informe senha para criar usuário novo.")
                db.session.delete(org)
                db.session.commit()
                return redirect(url_for("admin.create_org"))
            user = User(name=admin_name, email=admin_email, password_hash=generate_password_hash(admin_password))
            db.session.add(user)
            db.session.commit()

        db.session.add(Membership(user_id=user.id, org_id=org.id, role="ORG_ADMIN"))
        db.session.add(Subscription(org_id=org.id, plan=plan, status="active", current_period_end=datetime.utcnow()))
        db.session.commit()
        audit("admin_create_org", org.id, {"plan": plan, "admin_email": admin_email})
        flash("Organização criada com sucesso.")
        return redirect(url_for("admin.dashboard"))

    return render_template("admin_org_create.html")


@bp.route("/org/<int:org_id>/members", methods=["GET", "POST"])
@login_required
@require_role("PLATFORM_ADMIN")
def org_members(org_id: int):
    org = Organization.query.get_or_404(org_id)
    if request.method == "POST":
        membership_id = int(request.form.get("membership_id", "0"))
        role = request.form.get("role", "ORG_USER")
        membership = Membership.query.filter_by(id=membership_id, org_id=org_id).first_or_404()
        membership.role = role
        db.session.commit()
        audit("admin_change_member_role", org.id, {"membership_id": membership.id, "role": role})
        flash("Role atualizada.")
        return redirect(url_for("admin.org_members", org_id=org.id))

    members = Membership.query.filter_by(org_id=org.id).all()
    return render_template("admin_members.html", org=org, members=members)


@bp.route("/org/<int:org_id>/status", methods=["POST"])
@login_required
@require_role("PLATFORM_ADMIN")
def org_status(org_id: int):
    org = Organization.query.get_or_404(org_id)
    org.status = request.form.get("status", org.status)
    org.plan = request.form.get("plan", org.plan)
    db.session.commit()
    audit("admin_update_org", org.id, {"status": org.status, "plan": org.plan})
    flash("Organização atualizada.")
    return redirect(url_for("admin.dashboard"))


@bp.route("/billing/override/<int:org_id>", methods=["POST"])
@login_required
@require_role("PLATFORM_ADMIN")
def billing_override(org_id: int):
    org = Organization.query.get_or_404(org_id)
    org.status = "active"
    sub = Subscription.query.filter_by(org_id=org.id).first()
    if sub:
        sub.status = "active"
    db.session.commit()
    audit("admin_billing_override", org.id)
    flash("Billing liberado manualmente.")
    return redirect(url_for("admin.dashboard"))
