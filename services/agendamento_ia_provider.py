"""
Troca de profissional outbound ZapAction → Agendamento IA (POST /v1/agendamento).
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


def _post_provider_operation(
    *,
    cliente_id: str,
    operation: str,
    booking: dict[str, Any],
    remote_id: str | None = None,
    turn_suffix: str,
) -> tuple[bool, str | None]:
    if not agendamento_ia_configured():
        return True, None
    url = resolved_agendamento_webhook_url()
    if not url:
        return True, None
    cid = (cliente_id or "").strip()
    if not cid:
        return False, "cliente_id_em_falta"

    body: dict[str, Any] = {
        "request_schema_version": REQUEST_SCHEMA_VERSION,
        "operation": operation,
        "user_message": "",
        "context": {
            "cliente_id": cid,
            "remote_id": (remote_id or "").strip(),
        },
        "booking": booking,
        "zapaction_turn_id": f"panel-{turn_suffix}-{int(time.time())}",
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
    return False, f"http_{r.status_code}"


def reassign_provider_in_agendamento_ia(
    *,
    cliente_id: str,
    external_appointment_id: str,
    new_provider_id: str,
    remote_id: str | None = None,
) -> tuple[bool, str | None]:
    aid = (external_appointment_id or "").strip()
    pid = (new_provider_id or "").strip()
    if not aid or not pid:
        return False, "appointment_id_ou_provider_em_falta"
    return _post_provider_operation(
        cliente_id=cliente_id,
        operation="reassign_provider",
        booking={"appointment_id": aid, "provider_id": pid},
        remote_id=remote_id,
        turn_suffix="reassign",
    )


def swap_providers_in_agendamento_ia(
    *,
    cliente_id: str,
    external_appointment_a_id: str,
    external_appointment_b_id: str,
    remote_id: str | None = None,
) -> tuple[bool, str | None]:
    aid = (external_appointment_a_id or "").strip()
    bid = (external_appointment_b_id or "").strip()
    if not aid or not bid:
        return False, "appointment_ids_em_falta"
    return _post_provider_operation(
        cliente_id=cliente_id,
        operation="swap_providers",
        booking={"appointment_id": aid, "appointment_b_id": bid},
        remote_id=remote_id,
        turn_suffix="swap",
    )


def sync_panel_reassign_to_agenda(
    *,
    cliente_id: str,
    appointment_row: dict[str, Any],
    new_professional_id: str,
) -> tuple[bool, str | None]:
    ext = str(appointment_row.get("external_agenda_appointment_id") or "").strip()
    if not ext:
        return True, None
    return reassign_provider_in_agendamento_ia(
        cliente_id=cliente_id,
        external_appointment_id=ext,
        new_provider_id=new_professional_id,
        remote_id=str(appointment_row.get("remote_id") or ""),
    )


def sync_panel_swap_to_agenda(
    *,
    cliente_id: str,
    row_a: dict[str, Any],
    row_b: dict[str, Any],
) -> tuple[bool, str | None]:
    ext_a = str(row_a.get("external_agenda_appointment_id") or "").strip()
    ext_b = str(row_b.get("external_agenda_appointment_id") or "").strip()
    if not ext_a and not ext_b:
        return True, None
    if not ext_a or not ext_b:
        return False, "swap_parcial_sem_id_externo"
    return swap_providers_in_agendamento_ia(
        cliente_id=cliente_id,
        external_appointment_a_id=ext_a,
        external_appointment_b_id=ext_b,
        remote_id=str(row_a.get("remote_id") or row_b.get("remote_id") or ""),
    )
