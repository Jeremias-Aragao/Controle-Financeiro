from __future__ import annotations

import json
import os
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


class MercadoPagoError(RuntimeError):
    pass


class MercadoPagoService:
    def __init__(self) -> None:
        self.access_token = os.getenv("MP_ACCESS_TOKEN")
        self.notification_url = os.getenv("MP_NOTIFICATION_URL")
        self.base_url = "https://api.mercadopago.com/v1/payments"

    def _headers(self) -> dict[str, str]:
        if not self.access_token:
            raise MercadoPagoError("MP_ACCESS_TOKEN não configurado.")
        return {
            "Authorization": f"Bearer {self.access_token}",
            "Content-Type": "application/json",
        }

    def _request_json(self, method: str, url: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        data = json.dumps(payload).encode() if payload is not None else None
        request = Request(url, data=data, method=method, headers=self._headers())
        try:
            with urlopen(request, timeout=20) as response:
                return json.loads(response.read().decode())
        except HTTPError as exc:
            raise MercadoPagoError(f"Falha na API Mercado Pago: HTTP {exc.code}") from exc
        except URLError as exc:
            raise MercadoPagoError("Falha de conexão com Mercado Pago.") from exc

    def create_pix_charge(self, amount: float, description: str, external_reference: str, payer_email: str) -> dict[str, Any]:
        payload = {
            "transaction_amount": float(amount),
            "description": description,
            "payment_method_id": "pix",
            "external_reference": external_reference,
            "payer": {"email": payer_email},
        }
        if self.notification_url:
            payload["notification_url"] = self.notification_url

        body = self._request_json("POST", self.base_url, payload)
        point = body.get("point_of_interaction", {}).get("transaction_data", {})
        return {
            "mp_payment_id": str(body.get("id")),
            "status": body.get("status", "pending"),
            "qr_code_data": point.get("qr_code_base64"),
            "pix_copia_cola": point.get("qr_code"),
        }

    def get_payment(self, mp_payment_id: str) -> dict[str, Any]:
        body = self._request_json("GET", f"{self.base_url}/{mp_payment_id}")
        return {"id": str(body.get("id")), "status": body.get("status")}
