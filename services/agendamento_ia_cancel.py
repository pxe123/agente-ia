"""
Cancelamento outbound ZapAction → Agendamento IA (POST /v1/agendamento, operation=cancel).
"""
from __future__ import annotations

import json
import time
from typing import Any

import requests

from base.config import settings
from services.agendamento_ia_urls import (
    agendamento_ia_configured,
    resolved_agendamento_webhook_url,
    scheduling_integration_headers,
)

REQUEST_SCHEMA_VERSION = 1


def cancel_appointment_in_agendamento_ia(
    *,
    cliente_id: str,
    external_appointment_id: str,
    remote_id: str | None = None,
) -> tuple[bool, str | None]:
    """
    Pede cancelamento no motor Agenda para marcação espelhada (external_agenda_appointment_id).

    Retorno: (ok, mensagem_erro).
    """
    if not agendamento_ia_configured():
        return False, "agendamento_ia_nao_configurado"
    url = resolved_agendamento_webhook_url()
    if not url:
        return False, "webhook_url_nao_configurado"
    cid = (cliente_id or "").strip()
    aid = (external_appointment_id or "").strip()
    if not cid or not aid:
        return False, "cliente_id_ou_appointment_id_em_falta"

    body: dict[str, Any] = {
        "request_schema_version": REQUEST_SCHEMA_VERSION,
        "operation": "cancel",
        "user_message": "",
        "context": {
            "cliente_id": cid,
            "remote_id": (remote_id or "").strip() or None,
        },
        "booking": {"appointment_id": aid},
        "zapaction_turn_id": f"panel-cancel-{int(time.time())}",
    }
    timeout = int(getattr(settings, "AGENDAMENTO_IA_TIMEOUT_SEC", 25) or 25)
    try:
        r = requests.post(
            url,
            json=body,
            headers=scheduling_integration_headers(),
            timeout=timeout,
        )
    except requests.Timeout:
        return False, "timeout"
    except Exception as e:
        return False, str(e)

    if 200 <= r.status_code < 300:
        try:
            data = r.json() if r.text else {}
        except json.JSONDecodeError:
            data = {}
        if isinstance(data, dict):
            err = data.get("error")
            if isinstance(err, dict) and err.get("code"):
                return False, str(err.get("code"))
            if (data.get("status") or "").strip().lower() == "error":
                return False, str(
                    (err or {}).get("message") if isinstance(err, dict) else "motor_error"
                )
        return True, None
    detail = (r.text or "")[:200]
    return False, f"http_{r.status_code}:{detail}"
