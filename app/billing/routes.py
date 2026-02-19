from __future__ import annotations

import hashlib
import hmac
import os
from datetime import datetime, timedelta
from decimal import Decimal

from flask import Blueprint, abort, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required

from ..decorators import get_active_org, require_org
from ..extensions import db
from ..models import Organization, PaymentAttempt, Subscription
from ..services.mercadopago import MercadoPagoError, MercadoPagoService

bp = Blueprint("billing", __name__, url_prefix="/billing")
webhooks_bp = Blueprint("webhooks", __name__, url_prefix="/webhooks")

PLAN_PRICE = {
    "FREE": Decimal("0.00"),
    "PRO": Decimal("49.90"),
    "AGENCY": Decimal("149.90"),
    "ENTERPRISE": Decimal("399.90"),
}


@bp.route("")
@login_required
@require_org
def index():
    org = get_active_org()
    subscription = Subscription.query.filter_by(org_id=org.id).first()
    last_payment = PaymentAttempt.query.filter_by(org_id=org.id).order_by(PaymentAttempt.created_at.desc()).first()
    return render_template("billing.html", org=org, subscription=subscription, last_payment=last_payment, plan_price=PLAN_PRICE)


@bp.route("/checkout", methods=["POST"])
@login_required
@require_org
def checkout():
    org = get_active_org()
    plan = request.args.get("plan", "PRO").upper()
    if plan not in PLAN_PRICE:
        abort(400)

    amount = float(PLAN_PRICE[plan])
    service = MercadoPagoService()
    external_reference = f"org:{org.id}:plan:{plan}:ts:{int(datetime.utcnow().timestamp())}"
    try:
        payload = service.create_pix_charge(
            amount=amount,
            description=f"Assinatura {plan} - {org.name}",
            external_reference=external_reference,
            payer_email=current_user.email,
        )
    except MercadoPagoError as exc:
        flash(str(exc))
        return redirect(url_for("billing.index"))

    payment = PaymentAttempt(
        org_id=org.id,
        mp_payment_id=payload["mp_payment_id"],
        amount=PLAN_PRICE[plan],
        status=payload.get("status", "pending"),
        qr_code_data=payload.get("qr_code_data"),
        pix_copia_cola=payload.get("pix_copia_cola"),
    )
    db.session.add(payment)

    sub = Subscription.query.filter_by(org_id=org.id).first()
    if not sub:
        sub = Subscription(org_id=org.id, plan=plan, status="past_due")
        db.session.add(sub)
    else:
        sub.plan = plan
        sub.status = "past_due"
    org.status = "past_due"

    db.session.commit()
    flash("Cobrança PIX gerada. Pague para liberar automaticamente.")
    return redirect(url_for("billing.status"))


@bp.route("/status")
@login_required
@require_org
def status():
    org = get_active_org()
    payment = PaymentAttempt.query.filter_by(org_id=org.id).order_by(PaymentAttempt.created_at.desc()).first()
    return render_template("billing_status.html", org=org, payment=payment)


def _parse_signature_header(signature: str) -> tuple[str | None, str | None]:
    if not signature:
        return None, None
    if "=" not in signature:
        return None, signature.strip()

    parts = {}
    for chunk in signature.split(","):
        if "=" not in chunk:
            continue
        key, value = chunk.strip().split("=", 1)
        parts[key.strip()] = value.strip()
    return parts.get("ts"), parts.get("v1")


def _validate_webhook_signature(payload: bytes) -> bool:
    secret = os.getenv("MP_WEBHOOK_SECRET")
    if not secret:
        return True

    provided = request.headers.get("x-signature", "")
    ts, v1 = _parse_signature_header(provided)

    expected_raw = hmac.new(secret.encode(), payload, hashlib.sha256).hexdigest()
    if v1 and hmac.compare_digest(v1, expected_raw):
        return True
    if not v1 and hmac.compare_digest(provided.strip(), expected_raw):
        return True

    if ts:
        expected_with_ts = hmac.new(secret.encode(), f"{ts}.{payload.decode(errors='ignore')}".encode(), hashlib.sha256).hexdigest()
        if v1 and hmac.compare_digest(v1, expected_with_ts):
            return True

    return False


@webhooks_bp.route("/mercadopago", methods=["POST"])
def mercadopago_webhook():
    raw_payload = request.get_data() or b""
    if not _validate_webhook_signature(raw_payload):
        return {"ok": False}, 401

    data = request.get_json(silent=True) or {}
    payment_id = str(data.get("data", {}).get("id") or data.get("id") or "")
    if not payment_id:
        return {"ok": True}, 200

    payment = PaymentAttempt.query.filter_by(mp_payment_id=payment_id).first()
    if not payment:
        return {"ok": True}, 200

    service = MercadoPagoService()
    try:
        result = service.get_payment(payment_id)
    except MercadoPagoError:
        return {"ok": False}, 502

    status = (result.get("status") or "").lower()
    payment.status = status
    org = Organization.query.get(payment.org_id)
    subscription = Subscription.query.filter_by(org_id=payment.org_id).first()
    if status == "approved":
        payment.paid_at = datetime.utcnow()
        if subscription:
            subscription.status = "active"
            subscription.current_period_end = datetime.utcnow() + timedelta(days=30)
        org.status = "active"
    elif status in {"rejected", "cancelled", "expired"}:
        if subscription:
            subscription.status = "past_due"
        if org.status != "blocked":
            org.status = "past_due"

    db.session.commit()
    return {"ok": True}, 200
