"""
Booking outbound ZapAction → Agendamento IA (integração painel / recorrência).
"""
from __future__ import annotations

import json
import uuid
from datetime import datetime
from typing import Any

import requests

from base.config import settings
from services.agendamento_ia_urls import (
    agendamento_ia_configured,
    agendamento_ia_url,
    scheduling_integration_headers,
)

REQUEST_SCHEMA_VERSION = 1


def resolved_appointments_create_url() -> str:
    return agendamento_ia_url("/v1/integrations/zapaction/appointments")


def resolved_appointments_cancel_batch_url() -> str:
    return agendamento_ia_url("/v1/integrations/zapaction/appointments/cancel-batch")


def recurrence_external_sync_enabled() -> bool:
    raw = getattr(settings, "RECURRENCE_EXTERNAL_SYNC_ENABLED", None)
    if raw is None:
        return True
    if isinstance(raw, bool):
        return raw
    return str(raw).strip().lower() in ("1", "true", "yes", "on")


def _timeout_sec() -> int:
    return int(getattr(settings, "AGENDAMENTO_IA_TIMEOUT_SEC", 25) or 25)


def _parse_error_response(data: dict[str, Any] | None) -> str | None:
    if not isinstance(data, dict):
        return None
    err = data.get("error")
    if isinstance(err, dict) and err.get("code"):
        return str(err.get("code"))
    if isinstance(err, str) and err.strip():
        return err.strip()
    return None


def create_appointment_in_agendamento_ia(
    *,
    cliente_id: str,
    zapaction_appointment_id: str,
    service_id: str,
    provider_id: str | None,
    starts_at: datetime,
    ends_at: datetime,
    contact_name: str,
    contact_phone: str | None = None,
    notes: str | None = None,
    status: str = "confirmed",
    metadata: dict[str, Any] | None = None,
    recurrence_series_id: str | None = None,
    series_occurrence_at: datetime | None = None,
    is_series_exception: bool = False,
    event_id: str | None = None,
) -> tuple[str | None, str | None]:
    """
    Cria marcação no motor Agenda IA.

    Retorno: (external_appointment_id, erro).
    """
    if not agendamento_ia_configured():
        return None, "agendamento_ia_nao_configurado"
    if not recurrence_external_sync_enabled():
        return None, "sync_externo_desativado"
    url = resolved_appointments_create_url()
    if not url:
        return None, "url_nao_configurado"

    cid = (cliente_id or "").strip()
    zaid = (zapaction_appointment_id or "").strip()
    if not cid or not zaid:
        return None, "cliente_id_ou_appointment_id_em_falta"

    body: dict[str, Any] = {
        "request_schema_version": REQUEST_SCHEMA_VERSION,
        "event_id": (event_id or f"za-book-{uuid.uuid4()}"),
        "cliente_id": cid,
        "zapaction_appointment_id": zaid,
        "booking": {
            "service_id": str(service_id),
            "provider_id": (provider_id or "").strip() or None,
            "starts_at": starts_at.isoformat(),
            "ends_at": ends_at.isoformat(),
            "status": (status or "confirmed").strip().lower(),
            "contact": {
                "name": (contact_name or "").strip() or "Cliente",
                "phone": (contact_phone or "").strip() or None,
            },
            "notes": (notes or "").strip() or None,
            "metadata": dict(metadata or {}),
        },
    }
    if recurrence_series_id and series_occurrence_at:
        body["recurrence"] = {
            "series_id": str(recurrence_series_id),
            "occurrence_at": series_occurrence_at.isoformat(),
            "is_exception": bool(is_series_exception),
        }

    try:
        r = requests.post(
            url,
            json=body,
            headers=scheduling_integration_headers(),
            timeout=_timeout_sec(),
        )
    except requests.Timeout:
        return None, "timeout"
    except Exception as e:
        return None, str(e)

    try:
        data = r.json() if r.text else {}
    except json.JSONDecodeError:
        data = {}

    if 200 <= r.status_code < 300 and isinstance(data, dict):
        err_code = _parse_error_response(data)
        if err_code:
            return None, err_code
        ext = (data.get("appointment_id") or "").strip()
        if ext:
            return ext, None
        return None, "resposta_sem_appointment_id"

    if isinstance(data, dict):
        err_code = _parse_error_response(data)
        if err_code:
            return None, err_code
    detail = (r.text or "")[:200]
    return None, f"http_{r.status_code}:{detail}"


def cancel_appointments_batch_in_agendamento_ia(
    *,
    cliente_id: str,
    scope: str,
    series_id: str | None = None,
    from_starts_at: datetime | None = None,
    appointment_ids: list[str] | None = None,
    event_id: str | None = None,
) -> tuple[int, str | None]:
    """
    Cancela ocorrências em lote no motor Agenda IA.

    Retorno: (cancelled_count, erro).
    """
    if not agendamento_ia_configured():
        return 0, "agendamento_ia_nao_configurado"
    if not recurrence_external_sync_enabled():
        return 0, "sync_externo_desativado"
    url = resolved_appointments_cancel_batch_url()
    if not url:
        return 0, "url_nao_configurado"

    cid = (cliente_id or "").strip()
    sc = (scope or "").strip().lower()
    if not cid or sc not in ("following", "all", "ids"):
        return 0, "parametros_invalidos"

    body: dict[str, Any] = {
        "request_schema_version": REQUEST_SCHEMA_VERSION,
        "event_id": (event_id or f"za-cancel-batch-{uuid.uuid4()}"),
        "cliente_id": cid,
        "scope": sc,
    }
    if series_id:
        body["series_id"] = str(series_id)
    if from_starts_at:
        body["from_starts_at"] = from_starts_at.isoformat()
    if appointment_ids:
        body["appointment_ids"] = [str(x) for x in appointment_ids if str(x).strip()]

    try:
        r = requests.post(
            url,
            json=body,
            headers=scheduling_integration_headers(),
            timeout=_timeout_sec(),
        )
    except requests.Timeout:
        return 0, "timeout"
    except Exception as e:
        return 0, str(e)

    try:
        data = r.json() if r.text else {}
    except json.JSONDecodeError:
        data = {}

    if 200 <= r.status_code < 300 and isinstance(data, dict):
        err_code = _parse_error_response(data)
        if err_code:
            return 0, err_code
        try:
            return int(data.get("cancelled") or 0), None
        except (TypeError, ValueError):
            return 0, None

    if isinstance(data, dict):
        err_code = _parse_error_response(data)
        if err_code:
            return 0, err_code
    detail = (r.text or "")[:200]
    return 0, f"http_{r.status_code}:{detail}"
