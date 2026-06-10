"""
Importa marcações do Agendamento IA para scheduling_appointments (Supabase).
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any

import requests

from services.agendamento_ia_appointment_webhook import process_appointment_webhook_payload
from services.agendamento_ia_urls import agendamento_ia_base_url, scheduling_integration_headers

logger = logging.getLogger(__name__)


def _export_url() -> str | None:
    base = agendamento_ia_base_url()
    if not base:
        return None
    return f"{base.rstrip('/')}/v1/integrations/zapaction/appointments/export"


def _item_to_webhook_payload(cliente_id: str, item: dict[str, Any]) -> dict[str, Any]:
    st = (item.get("status") or "confirmed").strip().lower()
    event = "appointment.cancelled" if st == "cancelled" else "appointment.created"
    contact = item.get("contact") if isinstance(item.get("contact"), dict) else {}
    return {
        "event": event,
        "request_schema_version": 1,
        "event_id": f"import-{item.get('appointment_id') or ''}",
        "occurred_at": datetime.now(timezone.utc).isoformat(),
        "cliente_id": cliente_id,
        "appointment_id": str(item.get("appointment_id") or "").strip(),
        "status": st,
        "starts_at": item.get("starts_at"),
        "ends_at": item.get("ends_at"),
        "provider_id": item.get("provider_id"),
        "service_id": item.get("service_id"),
        "remote_id": item.get("remote_id") or "",
        "contact": {
            "phone": (contact.get("phone") or "").strip(),
            "name": (contact.get("name") or "").strip(),
            "email": (contact.get("email") or "").strip(),
        },
        "metadata": {"source": item.get("source") or "agendamento_ia"},
    }


def sync_appointments_from_agenda(
    cliente_id: str,
    *,
    since_days: int = 90,
    timeout_sec: int = 25,
) -> tuple[int, str | None]:
    """
    GET export no Agenda e upsert em scheduling_appointments.
    Retorno: (importados_ok, erro_opcional).
    """
    url = _export_url()
    if not url:
        return 0, "agendamento_ia_nao_configurado"

    since = (datetime.now(timezone.utc) - timedelta(days=max(1, since_days))).isoformat()
    params = {"cliente_id": str(cliente_id).strip(), "since": since, "limit": 500}
    try:
        r = requests.get(
            url,
            params=params,
            headers=scheduling_integration_headers(),
            timeout=timeout_sec,
        )
    except requests.RequestException as e:
        logger.warning("agenda appointments export failed cliente_id=%s err=%s", cliente_id[:8], e)
        return 0, "falha_ligacao_agenda"

    if r.status_code == 401:
        return 0, "nao_autorizado_verifique_api_key"
    if r.status_code >= 400:
        return 0, f"agenda_http_{r.status_code}"

    try:
        data = r.json()
    except ValueError:
        return 0, "resposta_json_invalida"

    items = data.get("appointments") if isinstance(data, dict) else None
    if not isinstance(items, list):
        return 0, "appointments_em_falta"

    imported = 0
    last_err: str | None = None
    for item in items:
        if not isinstance(item, dict):
            continue
        payload = _item_to_webhook_payload(cliente_id, item)
        if not payload.get("appointment_id"):
            continue
        try:
            ok, err, _code = process_appointment_webhook_payload(payload)
        except Exception as exc:
            logger.exception(
                "import appointment failed cliente_id=%s appointment_id=%s",
                cliente_id[:8],
                payload.get("appointment_id"),
            )
            last_err = str(exc)[:200]
            continue
        if ok:
            imported += 1
        else:
            last_err = err

    if imported == 0 and last_err:
        return 0, last_err
    return imported, None
