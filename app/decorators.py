from __future__ import annotations

from datetime import datetime, timedelta
from functools import wraps

from flask import abort, flash, redirect, request, session, url_for
from flask_login import current_user

from .extensions import db
from .models import Membership, Organization, Subscription


def active_org_id() -> int | None:
    try:
        return int(session.get("active_org_id")) if session.get("active_org_id") else None
    except Exception:
        return None


def get_active_org() -> Organization | None:
    org_id = active_org_id()
    if not org_id:
        return None
    return Organization.query.get(org_id)


def user_membership_for_active_org() -> Membership | None:
    org_id = active_org_id()
    if not org_id or not current_user.is_authenticated:
        return None
    return Membership.query.filter_by(user_id=current_user.id, org_id=org_id).first()


def user_has_role(role: str) -> bool:
    if not current_user.is_authenticated:
        return False
    if role == "PLATFORM_ADMIN":
        return Membership.query.filter_by(user_id=current_user.id, role="PLATFORM_ADMIN").first() is not None
    membership = user_membership_for_active_org()
    return membership is not None and membership.role == role


def require_org(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if not current_user.is_authenticated:
            return redirect(url_for("auth.login"))
        membership = user_membership_for_active_org()
        if not membership:
            flash("Selecione uma organização para continuar.")
            return redirect(url_for("org.select_org"))
        return view(*args, **kwargs)

    return wrapped


def require_role(role: str):
    def decorator(view):
        @wraps(view)
        def wrapped(*args, **kwargs):
            if not current_user.is_authenticated:
                return redirect(url_for("auth.login"))
            if not user_has_role(role):
                abort(403)
            return view(*args, **kwargs)

        return wrapped

    return decorator


def billing_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        org = get_active_org()
        if not org:
            flash("Selecione uma organização para continuar.")
            return redirect(url_for("org.select_org"))

        subscription = Subscription.query.filter_by(org_id=org.id).first()
        now = datetime.utcnow()
        if subscription and subscription.current_period_end and subscription.current_period_end < now:
            subscription.status = "past_due"
            org.status = "past_due"
            if subscription.current_period_end + timedelta(days=3) < now:
                subscription.status = "blocked"
                org.status = "blocked"
            db.session.commit()

        if org.status == "blocked":
            flash("Organização bloqueada por billing. Regularize para continuar.")
            return redirect(url_for("billing.index"))

        return view(*args, **kwargs)

    return wrapped


def should_skip_billing_gate(endpoint: str | None) -> bool:
    if not endpoint:
        return True
    allowed_prefixes = (
        "auth.",
        "billing.",
        "org.",
    )
    allowed_exact = {"static", "webhooks.mercadopago_webhook"}
    return endpoint in allowed_exact or endpoint.startswith(allowed_prefixes)


def enforce_billing_gate():
    if request.endpoint and should_skip_billing_gate(request.endpoint):
        return None
    if not current_user.is_authenticated:
        return None
    org = get_active_org()
    if org and org.status == "blocked":
        flash("Organização bloqueada por billing.")
        return redirect(url_for("billing.index"))
    return None
