import hmac
import hashlib
from datetime import datetime, timezone
from typing import Any, Dict, Optional, Tuple

import requests

from base.config import settings


MP_API_BASE = "https://api.mercadopago.com"


def mp_headers() -> Dict[str, str]:
    token = (settings.MERCADOPAGO_ACCESS_TOKEN or "").strip()
    if not token:
        return {}
    return {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }


def verify_webhook_signature(
    *,
    x_signature: str,
    x_request_id: str,
    data_id: str,
) -> bool:
    """
    Valida origem do webhook do Mercado Pago conforme docs:
    - header x-signature: "ts=<unix>,v1=<hmac_hex>"
    - header x-request-id
    - manifest: "id:{data_id};request-id:{x_request_id};ts:{ts};"
    - HMAC SHA256 com MERCADOPAGO_WEBHOOK_SECRET
    """
    secret = (settings.MERCADOPAGO_WEBHOOK_SECRET or "").strip()
    if not secret:
        return False
    if not x_signature or not x_request_id or not data_id:
        return False

    ts = None
    v1 = None
    try:
        parts = [p.strip() for p in x_signature.split(",") if p.strip()]
        for part in parts:
            k, v = part.split("=", 1)
            k = k.strip()
            v = v.strip()
            if k == "ts":
                ts = v
            elif k == "v1":
                v1 = v
    except Exception:
        return False

    if not ts or not v1:
        return False

    manifest = f"id:{data_id};request-id:{x_request_id};ts:{ts};"
    sha = hmac.new(secret.encode("utf-8"), msg=manifest.encode("utf-8"), digestmod=hashlib.sha256).hexdigest()
    return hmac.compare_digest(sha, v1)


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def create_preapproval(
    *,
    plan_key: str,
    reason: str,
    payer_email: str,
    cliente_id: str,
    amount: float,
    frequency: int = 1,
    frequency_type: str = "months",
    currency_id: str = "BRL",
    back_url: Optional[str] = None,
) -> Tuple[bool, Dict[str, Any]]:
    """
    Cria uma assinatura recorrente (preapproval) no Mercado Pago sem plano associado.
    Retorna (ok, payload_resposta).
    """
    url = f"{MP_API_BASE}/preapproval"
    headers = mp_headers()
    if not headers:
        return False, {"erro": "MERCADOPAGO_ACCESS_TOKEN não configurado."}

    back_url = back_url or settings.MERCADOPAGO_BACK_URL
    if not back_url:
        return False, {"erro": "MERCADOPAGO_BACK_URL não configurado."}

    body: Dict[str, Any] = {
        "reason": reason,
        "external_reference": str(cliente_id),
        "payer_email": payer_email,
        "back_url": back_url,
        "auto_recurring": {
            "frequency": int(frequency),
            "frequency_type": frequency_type,
            "transaction_amount": float(amount),
            "currency_id": currency_id,
        },
        # status inicial "pending" (o pagador completa o fluxo)
        "status": "pending",
        "metadata": {"plan_key": plan_key},
    }

    r = requests.post(url, json=body, headers=headers, timeout=20)
    try:
        data = r.json()
    except Exception:
        data = {"erro": "Resposta inválida do Mercado Pago.", "status_code": r.status_code, "text": r.text[:2000]}
    if r.status_code >= 200 and r.status_code < 300:
        return True, data
    return False, data


def get_preapproval(preapproval_id: str) -> Tuple[bool, Dict[str, Any]]:
    url = f"{MP_API_BASE}/preapproval/{preapproval_id}"
    headers = mp_headers()
    if not headers:
        return False, {"erro": "MERCADOPAGO_ACCESS_TOKEN não configurado."}
    r = requests.get(url, headers=headers, timeout=20)
    try:
        data = r.json()
    except Exception:
        data = {"erro": "Resposta inválida do Mercado Pago.", "status_code": r.status_code, "text": r.text[:2000]}
    if r.status_code >= 200 and r.status_code < 300:
        return True, data
    return False, data


def cancel_preapproval(preapproval_id: str) -> Tuple[bool, Dict[str, Any]]:
    """
    Cancela uma assinatura (preapproval) no Mercado Pago.
    Observação: usamos status 'cancelled' (o app trata 'canceled'/'cancelled').
    """
    url = f"{MP_API_BASE}/preapproval/{preapproval_id}"
    headers = mp_headers()
    if not headers:
        return False, {"erro": "MERCADOPAGO_ACCESS_TOKEN não configurado."}
    body = {"status": "cancelled"}
    r = requests.put(url, json=body, headers=headers, timeout=20)
    try:
        data = r.json()
    except Exception:
        data = {"erro": "Resposta inválida do Mercado Pago.", "status_code": r.status_code, "text": r.text[:2000]}
    if r.status_code >= 200 and r.status_code < 300:
        return True, data
    return False, data


def create_preference(
    *,
    title: str,
    payer_email: str,
    cliente_id: str,
    amount: float,
    currency_id: str = "BRL",
    back_url: Optional[str] = None,
    metadata: Optional[Dict[str, Any]] = None,
) -> Tuple[bool, Dict[str, Any]]:
    """
    Cria um checkout avulso (preference) no Mercado Pago.
    Usado para cobranças pró-rata (upgrade).
    """
    url = f"{MP_API_BASE}/checkout/preferences"
    headers = mp_headers()
    if not headers:
        return False, {"erro": "MERCADOPAGO_ACCESS_TOKEN não configurado."}
    back_url = back_url or settings.MERCADOPAGO_BACK_URL
    if not back_url:
        return False, {"erro": "MERCADOPAGO_BACK_URL não configurado."}
    body: Dict[str, Any] = {
        "external_reference": str(cliente_id),
        "payer": {"email": payer_email},
        "items": [
            {
                "title": title,
                "quantity": 1,
                "currency_id": currency_id,
                "unit_price": float(amount),
            }
        ],
        "back_urls": {"success": back_url, "pending": back_url, "failure": back_url},
        "auto_return": "approved",
        "metadata": metadata or {},
    }
    r = requests.post(url, json=body, headers=headers, timeout=20)
    try:
        data = r.json()
    except Exception:
        data = {"erro": "Resposta inválida do Mercado Pago.", "status_code": r.status_code, "text": r.text[:2000]}
    if 200 <= r.status_code < 300:
        return True, data
    return False, data


def get_payment(payment_id: str) -> Tuple[bool, Dict[str, Any]]:
    """
    Busca detalhes de um pagamento (payment) no Mercado Pago.
    """
    pid = (payment_id or "").strip()
    if not pid:
        return False, {"erro": "payment_id vazio."}
    url = f"{MP_API_BASE}/v1/payments/{pid}"
    headers = mp_headers()
    if not headers:
        return False, {"erro": "MERCADOPAGO_ACCESS_TOKEN não configurado."}
    r = requests.get(url, headers=headers, timeout=20)
    try:
        data = r.json()
    except Exception:
        data = {"erro": "Resposta inválida do Mercado Pago.", "status_code": r.status_code, "text": r.text[:2000]}
    if 200 <= r.status_code < 300:
        return True, data
    return False, data

