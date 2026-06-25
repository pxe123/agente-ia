"""
Confirmação / remarcação outbound ZapAction → Agendamento IA (POST /v1/agendamento).
"""
from __future__ import annotations

import json
import time
from datetime import datetime, timezone
from typing import Any

import requests

from base.config import settings
from services.agendamento_ia_urls import (
    agendamento_ia_configured,
    resolved_agendamento_webhook_url,
    scheduling_integration_headers,
)

REQUEST_SCHEMA_VERSION = 1


def _iso_z(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _post_operation(
    *,
    cliente_id: str,
    operation: str,
    external_appointment_id: str,
    remote_id: str | None = None,
    turn_suffix: str,
    starts_at: datetime | None = None,
    ends_at: datetime | None = None,
    target_status: str | None = None,
) -> tuple[bool, str | None]:
    if not agendamento_ia_configured():
        return True, None
    url = resolved_agendamento_webhook_url()
    if not url:
        return True, None
    cid = (cliente_id or "").strip()
    aid = (external_appointment_id or "").strip()
    if not cid or not aid:
        return False, "cliente_id_ou_appointment_id_em_falta"

    booking: dict[str, Any] = {"appointment_id": aid}
    if starts_at and ends_at:
        booking["start"] = _iso_z(starts_at)
        booking["end"] = _iso_z(ends_at)
    if target_status:
        booking["target_status"] = target_status

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


def confirm_appointment_in_agendamento_ia(
    *,
    cliente_id: str,
    external_appointment_id: str,
    remote_id: str | None = None,
    starts_at: datetime | None = None,
    ends_at: datetime | None = None,
) -> tuple[bool, str | None]:
    if starts_at and ends_at:
        return finalize_appointment_in_agendamento_ia(
            cliente_id=cliente_id,
            external_appointment_id=external_appointment_id,
            remote_id=remote_id,
            starts_at=starts_at,
            ends_at=ends_at,
            target_status="confirmed",
        )
    return _post_operation(
        cliente_id=cliente_id,
        operation="confirm",
        external_appointment_id=external_appointment_id,
        remote_id=remote_id,
        turn_suffix="confirm",
    )


def finalize_appointment_in_agendamento_ia(
    *,
    cliente_id: str,
    external_appointment_id: str,
    remote_id: str | None = None,
    starts_at: datetime,
    ends_at: datetime,
    target_status: str = "confirmed",
) -> tuple[bool, str | None]:
    return _post_operation(
        cliente_id=cliente_id,
        operation="finalize",
        external_appointment_id=external_appointment_id,
        remote_id=remote_id,
        turn_suffix="finalize",
        starts_at=starts_at,
        ends_at=ends_at,
        target_status=target_status,
    )


def reject_appointment_in_agendamento_ia(
    *,
    cliente_id: str,
    external_appointment_id: str,
    remote_id: str | None = None,
) -> tuple[bool, str | None]:
    return _post_operation(
        cliente_id=cliente_id,
        operation="reject",
        external_appointment_id=external_appointment_id,
        remote_id=remote_id,
        turn_suffix="reject",
    )
