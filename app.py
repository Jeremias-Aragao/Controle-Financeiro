from __future__ import annotations

"""
API Flask para integração com Mercado Pago (PIX).

Exemplos rápidos de uso:
1) Subir aplicação
   export FLASK_APP=app.py
   export MP_ACCESS_TOKEN="TEST-..."
   export MP_WEBHOOK_URL="https://seu-dominio.com/mp/webhook"
   flask run --host 0.0.0.0 --port 5000

2) Criar cobrança PIX
   curl -X POST http://localhost:5000/create_pix \
     -H 'Content-Type: application/json' \
     -d '{
       "tenant_id": 1,
       "invoice_id": 1001,
       "amount": 59.90,
       "due_date": "2026-03-10",
       "external_reference": "INV-1001"
     }'

3) Simular webhook (em produção o Mercado Pago chama automaticamente)
   curl -X POST http://localhost:5000/mp/webhook \
     -H 'Content-Type: application/json' \
     -d '{"data": {"id": "1234567890"}, "type": "payment"}'
"""

import json
import os
from datetime import date, datetime, timedelta
from decimal import Decimal, InvalidOperation
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from flask import Flask, jsonify, request
from flask_sqlalchemy import SQLAlchemy

# -----------------------------------------------------------------------------
# Configuração base
# -----------------------------------------------------------------------------

db = SQLAlchemy()

MERCADO_PAGO_API_BASE = "https://api.mercadopago.com"
INVOICE_STATUS_PENDING = "PENDING"
INVOICE_STATUS_PAID = "PAID"
TENANT_STATUS_ACTIVE = "ACTIVE"
TENANT_STATUS_BLOCKED = "BLOCKED"


def create_app() -> Flask:
    app = Flask(__name__)

    database_url = os.getenv("DATABASE_URL", "sqlite:///local.db")
    if database_url.startswith("postgres://"):
        database_url = database_url.replace("postgres://", "postgresql://", 1)

    app.config["SQLALCHEMY_DATABASE_URI"] = database_url
    app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

    db.init_app(app)

    # -------------------------------------------------------------------------
    # Modelos de dados
    # -------------------------------------------------------------------------
    class Tenant(db.Model):
        __tablename__ = "tenants"

        id = db.Column(db.Integer, primary_key=True)
        status = db.Column(db.String(20), nullable=False, default=TENANT_STATUS_BLOCKED)
        paid_until = db.Column(db.Date, nullable=True)
        created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
        updated_at = db.Column(
            db.DateTime,
            nullable=False,
            default=datetime.utcnow,
            onupdate=datetime.utcnow,
        )

        invoices = db.relationship("Invoice", backref="tenant", lazy=True)

    class Invoice(db.Model):
        __tablename__ = "invoices"

        id = db.Column(db.Integer, primary_key=True)
        tenant_id = db.Column(db.Integer, db.ForeignKey("tenants.id"), nullable=False, index=True)
        amount = db.Column(db.Numeric(12, 2), nullable=False)
        due_date = db.Column(db.Date, nullable=False)
        external_reference = db.Column(db.String(120), nullable=False, unique=True, index=True)
        status = db.Column(db.String(20), nullable=False, default=INVOICE_STATUS_PENDING)

        # Campo adicional para rastrear pagamento no Mercado Pago.
        mp_payment_id = db.Column(db.String(60), nullable=True, unique=True, index=True)

        created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
        updated_at = db.Column(
            db.DateTime,
            nullable=False,
            default=datetime.utcnow,
            onupdate=datetime.utcnow,
        )

    with app.app_context():
        db.create_all()

    # -------------------------------------------------------------------------
    # Helpers
    # -------------------------------------------------------------------------
    def _get_access_token() -> str:
        token = os.getenv("MP_ACCESS_TOKEN", "").strip()
        if not token:
            raise ValueError("MP_ACCESS_TOKEN não configurado")
        return token

    def _get_webhook_url() -> str:
        webhook_url = os.getenv("MP_WEBHOOK_URL", "").strip()
        if not webhook_url:
            raise ValueError("MP_WEBHOOK_URL não configurada")
        return webhook_url

    def _parse_amount(value: object) -> Decimal:
        try:
            amount = Decimal(str(value))
        except (InvalidOperation, TypeError, ValueError) as exc:
            raise ValueError("amount inválido") from exc
        if amount <= 0:
            raise ValueError("amount deve ser maior que zero")
        return amount.quantize(Decimal("0.01"))

    def _parse_due_date(value: object | None) -> date:
        if value is None:
            return date.today() + timedelta(days=1)
        try:
            return date.fromisoformat(str(value))
        except ValueError as exc:
            raise ValueError("due_date inválido. Use YYYY-MM-DD") from exc

    def _mp_request(method: str, endpoint: str, payload: dict | None = None, headers: dict | None = None) -> dict:
        token = _get_access_token()
        final_headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        }
        if headers:
            final_headers.update(headers)

        data = None
        if payload is not None:
            data = json.dumps(payload).encode("utf-8")

        req = Request(
            url=f"{MERCADO_PAGO_API_BASE}{endpoint}",
            data=data,
            method=method.upper(),
            headers=final_headers,
        )

        try:
            with urlopen(req, timeout=20) as response:
                raw = response.read().decode("utf-8")
                return json.loads(raw) if raw else {}
        except HTTPError as exc:
            body = exc.read().decode("utf-8", errors="ignore")
            raise RuntimeError(f"Erro Mercado Pago HTTP {exc.code}: {body}") from exc
        except URLError as exc:
            raise RuntimeError(f"Falha de conexão com Mercado Pago: {exc}") from exc

    def _extract_payment_id_from_webhook() -> str | None:
        payload = request.get_json(silent=True) or {}

        # Formato comum:
        # {"type":"payment", "data":{"id":"123"}}
        data_id = payload.get("data", {}).get("id")
        if data_id:
            return str(data_id)

        # Alguns cenários incluem apenas "id" no corpo.
        if payload.get("id"):
            return str(payload["id"])

        # Fallback por query string:
        # /mp/webhook?type=payment&data.id=123
        q_data_id = request.args.get("data.id")
        if q_data_id:
            return q_data_id

        # Outro fallback comum: /mp/webhook?id=123
        q_id = request.args.get("id")
        if q_id:
            return q_id

        return None

    def _activate_tenant_after_payment(tenant: Tenant) -> None:
        """Regra simples: ativa tenant e estende 30 dias após o maior entre hoje e paid_until."""
        today = date.today()
        base_date = tenant.paid_until if tenant.paid_until and tenant.paid_until > today else today
        tenant.status = TENANT_STATUS_ACTIVE
        tenant.paid_until = base_date + timedelta(days=30)

    # -------------------------------------------------------------------------
    # Endpoints
    # -------------------------------------------------------------------------
    @app.post("/create_pix")
    def create_pix():
        """
        Cria cobrança PIX no Mercado Pago usando /v1/payments.

        Entrada JSON:
        {
          "tenant_id": 1,
          "invoice_id": 1001,
          "amount": 59.90,
          "due_date": "2026-03-10",                # opcional
          "external_reference": "INV-1001"         # opcional
        }
        """
        body = request.get_json(silent=True) or {}

        tenant_id = body.get("tenant_id")
        invoice_id = body.get("invoice_id")
        amount_raw = body.get("amount")

        if tenant_id is None or invoice_id is None or amount_raw is None:
            return jsonify({"error": "tenant_id, invoice_id e amount são obrigatórios"}), 400

        try:
            tenant_id = int(tenant_id)
            invoice_id = int(invoice_id)
            amount = _parse_amount(amount_raw)
            due_date = _parse_due_date(body.get("due_date"))
            _ = _get_access_token()
            webhook_url = _get_webhook_url()
        except ValueError as exc:
            return jsonify({"error": str(exc)}), 400

        tenant = Tenant.query.get(tenant_id)
        if tenant is None:
            tenant = Tenant(id=tenant_id, status=TENANT_STATUS_BLOCKED)
            db.session.add(tenant)
            db.session.flush()

        invoice = Invoice.query.get(invoice_id)
        if invoice is None:
            external_reference = str(body.get("external_reference") or f"INV-{invoice_id}")
            invoice = Invoice(
                id=invoice_id,
                tenant_id=tenant.id,
                amount=amount,
                due_date=due_date,
                external_reference=external_reference,
                status=INVOICE_STATUS_PENDING,
            )
            db.session.add(invoice)
            db.session.flush()
        else:
            if invoice.tenant_id != tenant.id:
                return jsonify({"error": "invoice_id não pertence ao tenant_id informado"}), 400

        if invoice.status == INVOICE_STATUS_PAID:
            return jsonify({"error": "fatura já está paga"}), 409

        # Idempotência: mesma chave para evitar duplicidade ao recriar a mesma cobrança.
        idempotency_key = f"pix-invoice-{invoice.id}-tenant-{tenant.id}-amount-{str(amount)}"

        payload = {
            "transaction_amount": float(amount),
            "description": f"Invoice #{invoice.id}",
            "payment_method_id": "pix",
            "external_reference": invoice.external_reference,
            "notification_url": webhook_url,
            "payer": {
                # Para produção, use e-mail real do cliente.
                "email": "cliente@example.com"
            },
        }

        try:
            mp_response = _mp_request(
                method="POST",
                endpoint="/v1/payments",
                payload=payload,
                headers={"X-Idempotency-Key": idempotency_key},
            )
        except RuntimeError as exc:
            db.session.rollback()
            return jsonify({"error": str(exc)}), 502

        payment_id = str(mp_response.get("id", ""))
        qr_data = mp_response.get("point_of_interaction", {}).get("transaction_data", {})
        qr_code = qr_data.get("qr_code")
        qr_code_base64 = qr_data.get("qr_code_base64")

        if not payment_id:
            db.session.rollback()
            return jsonify({"error": "Mercado Pago não retornou payment id"}), 502

        invoice.mp_payment_id = payment_id
        invoice.status = INVOICE_STATUS_PENDING
        db.session.commit()

        return jsonify(
            {
                "invoice_id": invoice.id,
                "tenant_id": tenant.id,
                "status": invoice.status,
                "mp_payment_id": payment_id,
                "qr_code": qr_code,
                "qr_code_base64": qr_code_base64,
                "mercado_pago": mp_response,
            }
        ), 201

    @app.post("/mp/webhook")
    def mercado_pago_webhook():
        """
        Webhook do Mercado Pago.

        IMPORTANTE: nunca confiar somente no payload recebido.
        Sempre consulta GET /v1/payments/{payment_id} antes de liberar acesso.
        """
        payment_id = _extract_payment_id_from_webhook()
        if not payment_id:
            return jsonify({"error": "payment_id não encontrado na notificação"}), 400

        try:
            payment_info = _mp_request(method="GET", endpoint=f"/v1/payments/{payment_id}")
        except (RuntimeError, ValueError) as exc:
            return jsonify({"error": str(exc)}), 502

        # Validação de segurança: status precisa ser approved na API oficial.
        payment_status = str(payment_info.get("status", "")).lower()
        if payment_status != "approved":
            return jsonify(
                {
                    "message": "Pagamento ainda não aprovado",
                    "payment_id": payment_id,
                    "status": payment_status,
                }
            ), 200

        invoice = Invoice.query.filter_by(mp_payment_id=str(payment_id)).first()
        if invoice is None:
            external_reference = payment_info.get("external_reference")
            if external_reference:
                invoice = Invoice.query.filter_by(external_reference=str(external_reference)).first()

        if invoice is None:
            return jsonify({"error": "invoice não encontrada para pagamento aprovado"}), 404

        invoice.status = INVOICE_STATUS_PAID
        tenant = Tenant.query.get(invoice.tenant_id)
        if tenant is None:
            return jsonify({"error": "tenant da invoice não encontrado"}), 404

        _activate_tenant_after_payment(tenant)
        db.session.commit()

        return jsonify(
            {
                "message": "Pagamento confirmado e tenant ativado",
                "payment_id": payment_id,
                "invoice_id": invoice.id,
                "invoice_status": invoice.status,
                "tenant_id": tenant.id,
                "tenant_status": tenant.status,
                "paid_until": tenant.paid_until.isoformat() if tenant.paid_until else None,
            }
        ), 200

    @app.get("/health")
    def health():
        return jsonify({"ok": True, "service": "mercado-pago-pix-api"}), 200

    return app


app = create_app()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", "5000")), debug=True)
