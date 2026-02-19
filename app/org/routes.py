from __future__ import annotations

import hashlib
import secrets
from datetime import datetime, timedelta

from flask import Blueprint, flash, redirect, render_template, request, session, url_for
from flask_login import current_user, login_required

from ..decorators import active_org_id, require_org, require_role
from ..extensions import db
from ..models import InviteToken, Membership, Organization

bp = Blueprint("org", __name__, url_prefix="/org")


@bp.route("/select", methods=["GET", "POST"])
@login_required
def select_org():
    memberships = Membership.query.filter_by(user_id=current_user.id).all()
    if request.method == "POST":
        org_id = int(request.form.get("org_id", "0"))
        allowed = any(m.org_id == org_id for m in memberships)
        if not allowed:
            flash("Organização inválida.")
            return redirect(url_for("org.select_org"))
        session["active_org_id"] = org_id
        return redirect(url_for("finance.home"))

    if len(memberships) == 1:
        session["active_org_id"] = memberships[0].org_id
        return redirect(url_for("finance.home"))

    orgs = [Organization.query.get(m.org_id) for m in memberships]
    return render_template("org_select.html", orgs=orgs, active_org_id=active_org_id())


@bp.route("/invite", methods=["POST"])
@login_required
@require_org
@require_role("ORG_ADMIN")
def invite():
    org_id = active_org_id()
    role = request.form.get("role", "ORG_USER")
    raw_token = secrets.token_urlsafe(24)
    token_hash = hashlib.sha256(raw_token.encode()).hexdigest()
    invite_token = InviteToken(
        org_id=org_id,
        invited_by_user_id=current_user.id,
        token_hash=token_hash,
        role=role,
        expires_at=datetime.utcnow() + timedelta(days=7),
    )
    db.session.add(invite_token)
    db.session.commit()
    link = url_for("org.accept_invite", token=raw_token, _external=True)
    flash(f"Convite gerado: {link}")
    return redirect(url_for("finance.home"))


@bp.route("/invite/accept/<token>")
def accept_invite(token: str):
    token_hash = hashlib.sha256(token.encode()).hexdigest()
    invite_token = InviteToken.query.filter_by(token_hash=token_hash).first_or_404()
    if invite_token.used_at or invite_token.expires_at < datetime.utcnow():
        flash("Convite inválido ou expirado.")
        return redirect(url_for("org.select_org"))

    if not current_user.is_authenticated:
        return redirect(url_for("auth.login", next=request.path))

    exists = Membership.query.filter_by(user_id=current_user.id, org_id=invite_token.org_id).first()
    if not exists:
        db.session.add(Membership(user_id=current_user.id, org_id=invite_token.org_id, role=invite_token.role))
    invite_token.used_at = datetime.utcnow()
    db.session.commit()
    session["active_org_id"] = invite_token.org_id
    flash("Você entrou na organização.")
    return redirect(url_for("finance.home"))
