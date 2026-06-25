"""
Receptor do webhook reverso Agendamento IA → ZapAction (contrato §5.2–5.3 do plano técnico).
"""
from __future__ import annotations

import hashlib
import hmac
import json
import time
import uuid
from datetime import datetime, timezone
from typing import Any

from database.models import SchedulingAppointmentModel, Tables
from database.supabase_sq import supabase
from services.scheduling import repository as sched_repo

# Janela anti-replay (segundos)
_SIGNATURE_SKEW_SEC = 300

_ALLOWED_EVENTS = frozenset(
    {
        "appointment.created",
        "appointment.cancelled",
        "appointment.rescheduled",
        "appointment.updated",
        "appointment.pending",
        "appointment.confirmed",
        "appointment.rejected",
        "appointment.proposal.created",
        "appointment.proposal.resolved",
    }
)

# Alias legado emitido por alguns deploys do Agendamento IA (link confirmado).
_EVENT_ALIASES = {
    "APPOINTMENT_CONFIRMED": "appointment.created",
    "appointment.confirmed": "appointment.created",
}


def normalize_webhook_event(raw: str | None) -> str:
    e = (raw or "").strip()
    if e in _ALLOWED_EVENTS:
        return e
    return _EVENT_ALIASES.get(e, e)


def tenant_has_scheduling(cliente_id: str) -> bool:
    if not cliente_id:
        return False
    try:
        return sched_repo.get_settings(str(cliente_id)) is not None
    except Exception:
        return False


def appointment_origin_label(row: dict[str, Any] | None) -> str:
    """Rótulo para UI: agenda (Agendamento IA) ou zapaction_local."""
    if not row:
        return "zapaction_local"
    ext = row.get(SchedulingAppointmentModel.EXTERNAL_AGENDA_APPOINTMENT_ID) or row.get(
        "external_agenda_appointment_id"
    )
    if ext:
        return "agenda"
    meta = row.get(SchedulingAppointmentModel.META) or row.get("meta") or {}
    if isinstance(meta, dict) and (meta.get("agenda_webhook") or meta.get("source") == "agendamento_ia"):
        return "agenda"
    return "zapaction_local"


def panel_can_reassign_professional(
    row: dict[str, Any] | None,
    *,
    auto_distribution: bool,
) -> bool:
    """Painel pode trocar profissional (pendente ou confirmado; incl. Agenda IA em modo automático)."""
    if not row:
        return False
    status = str(row.get("status") or "").lower()
    if status == "cancelled":
        return False
    if appointment_origin_label(row) != "agenda":
        return True
    return auto_distribution


def verify_zapaction_webhook_signature(
    *, secret: str, raw_body: bytes, timestamp_header: str, signature_header: str
) -> tuple[bool, str | None]:
    """
    Cabeçalhos §5.3: X-Zapaction-Timestamp (unix seconds), X-Zapaction-Signature: sha256=<hex>.
    Mensagem: f"{timestamp}.{raw_body.decode('utf-8')}" — raw_body deve ser o corpo exato recebido.
    """
    if not secret:
        return False, "secret_nao_configurado"
    ts_raw = (timestamp_header or "").strip()
    sig_raw = (signature_header or "").strip()
    if not ts_raw or not sig_raw:
        return False, "cabecalhos_em_falta"
    try:
        ts = int(ts_raw)
    except ValueError:
        return False, "timestamp_invalido"
    now = int(time.time())
    if abs(now - ts) > _SIGNATURE_SKEW_SEC:
        return False, "timestamp_fora_da_janela"
    if sig_raw.lower().startswith("sha256="):
        got = sig_raw.split("=", 1)[1].strip()
    else:
        got = sig_raw
    try:
        body_text = raw_body.decode("utf-8")
    except UnicodeDecodeError:
        return False, "corpo_invalido_utf8"
    msg = f"{ts_raw}.{body_text}".encode("utf-8")
    expected = hmac.new(secret.encode("utf-8"), msg, hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected, got):
        return False, "assinatura_invalida"
    return True, None


def _normalize_webhook_phone(phone: str, remote_id: str) -> tuple[str, str]:
    """Garante contact_phone/remote_id em E.164 dígitos (ex.: 5511999999999)."""
    from services.scheduling.public_contact import normalize_scheduling_contact_phone

    for raw in (phone, remote_id):
        norm = normalize_scheduling_contact_phone(raw)
        if norm:
            return norm, norm
    return phone, remote_id


def _is_reconciliation_import(event_id: str | None) -> bool:
    return str(event_id or "").strip().startswith("import-")


def _dispatch_webhook_notifications(
    *,
    cliente_id: str,
    agenda_appointment_id: str,
    event: str,
    status: str,
    is_new: bool,
) -> None:
    """WhatsApp após agendamento vindo do motor Agenda IA (página pública)."""
    if not is_new:
        return
    row = sched_repo.get_appointment_by_external_agenda_id(cliente_id, agenda_appointment_id)
    if not row:
        return
    aid = str(row.get(SchedulingAppointmentModel.ID) or row.get("id") or "")
    if not aid:
        return
    try:
        if status == "pending":
            from services.scheduling.confirmation_notify import (
                notify_client_booking_received,
                notify_pending_booking,
            )

            notify_pending_booking(cliente_id, row)
            notify_client_booking_received(cliente_id, aid)
        elif status == "confirmed" and event in (
            "appointment.created",
            "appointment.confirmed",
        ):
            from services.scheduling.client_calendar_invite import on_appointment_confirmed
            from services.scheduling.confirmation_notify import notify_client_confirmed

            notify_client_confirmed(cliente_id, aid)
            on_appointment_confirmed(cliente_id, aid, kind="confirmed")
    except Exception:
        pass


def _normalize_status(raw: str | None, event: str) -> str:
    s = (raw or "").strip().lower()
    if s in ("pending", "confirmed", "cancelled", "no_show"):
        return s
    if event in ("appointment.cancelled", "appointment.rejected"):
        return "cancelled"
    if event == "appointment.pending":
        return "pending"
    if event in ("appointment.created", "appointment.confirmed"):
        return "confirmed"
    return "confirmed"


def _is_uuid(value: str) -> bool:
    try:
        uuid.UUID(str(value).strip())
        return True
    except (ValueError, AttributeError, TypeError):
        return False


def _resolve_service_id(cliente_id: str, payload: dict[str, Any]) -> tuple[str | None, str | None]:
    sid = payload.get("service_id")
    if sid is not None and str(sid).strip():
        s = str(sid).strip()
        if _is_uuid(s) and sched_repo.get_service(cliente_id, s):
            return s, None
        if _is_uuid(s):
            return None, "service_id_desconhecido"
    svcs = sched_repo.list_services(cliente_id, active_only=True)
    if not svcs:
        return None, "sem_servicos_no_tenant"
    first = svcs[0].get(SchedulingAppointmentModel.ID) or svcs[0].get("id")
    if first:
        return str(first), None
    return None, "sem_servicos_no_tenant"


def _resolve_professional_id(cliente_id: str, pid: Any) -> str | None:
    if pid is None or str(pid).strip() == "":
        return None
    p = str(pid).strip()
    if p.lower() in ("any", "null", "none"):
        return None
    if not _is_uuid(p):
        return None
    if sched_repo.get_professional(cliente_id, p):
        return p
    return None


def process_appointment_webhook_payload(payload: dict[str, Any]) -> tuple[bool, str | None, int]:
    """
    Aplica upsert/cancel em scheduling_appointments.
    Retorno: (ok, mensagem_erro_opcional, status_http_sugerido).
    """
    if supabase is None:
        return False, "supabase_nao_configurado", 503

    event = normalize_webhook_event(payload.get("event"))
    if event not in _ALLOWED_EVENTS:
        return False, "evento_invalido", 400
    payload = {**payload, "event": event}

    if event in ("appointment.proposal.created", "appointment.proposal.resolved"):
        return True, None, 200

    ver = payload.get("request_schema_version")
    if ver != 1:
        return False, "request_schema_version_invalida", 400

    cliente_id = (payload.get("cliente_id") or "").strip()
    appointment_id = (payload.get("appointment_id") or "").strip()
    if not cliente_id or not appointment_id:
        return False, "cliente_id_ou_appointment_id_em_falta", 400

    if not tenant_has_scheduling(cliente_id):
        return False, "cliente_id_desconhecido", 404

    event_id = (payload.get("event_id") or "").strip() or None
    occurred_at = (payload.get("occurred_at") or "").strip()

    existing = sched_repo.get_appointment_by_external_agenda_id(cliente_id, appointment_id)

    zapaction_appointment_id = (payload.get("zapaction_appointment_id") or "").strip()
    recurrence_payload = payload.get("recurrence") if isinstance(payload.get("recurrence"), dict) else {}
    recurrence_series_id = (recurrence_payload.get("series_id") or "").strip() or None
    series_occurrence_at = (recurrence_payload.get("occurrence_at") or "").strip() or None

    if not existing and zapaction_appointment_id:
        by_za = sched_repo.get_appointment(cliente_id, zapaction_appointment_id)
        if by_za:
            existing = by_za

    if not existing and recurrence_series_id and series_occurrence_at:
        occ_dt = sched_repo.parse_row_datetime(series_occurrence_at)
        if occ_dt:
            by_occ = sched_repo.get_appointment_by_series_occurrence(recurrence_series_id, occ_dt)
            if by_occ and str(by_occ.get("cliente_id") or "") == str(cliente_id):
                existing = by_occ

    if event_id and existing:
        prev_meta = existing.get(SchedulingAppointmentModel.META) or existing.get("meta") or {}
        if isinstance(prev_meta, dict):
            aw = prev_meta.get("agenda_webhook") or {}
            if isinstance(aw, dict) and (aw.get("last_event_id") or "").strip() == event_id:
                return True, None, 200

    status = _normalize_status(payload.get("status"), event)
    starts_at = (payload.get("starts_at") or "").strip()
    ends_at = (payload.get("ends_at") or "").strip()

    contact = payload.get("contact") if isinstance(payload.get("contact"), dict) else {}
    phone_raw = (contact.get("phone") or "").strip() if contact else ""
    name = (contact.get("name") or "").strip() if contact else ""
    email = (contact.get("email") or "").strip() if contact else ""
    remote_id_raw = (payload.get("remote_id") or "").strip()
    phone, remote_id = _normalize_webhook_phone(phone_raw, remote_id_raw)
    metadata = payload.get("metadata") if isinstance(payload.get("metadata"), dict) else {}

    if event in ("appointment.cancelled", "appointment.rejected") or status == "cancelled":
        if not existing:
            return True, None, 200
        meta = dict(existing.get(SchedulingAppointmentModel.META) or {})
        if event == "appointment.rejected":
            meta["cancellation_reason"] = "professional_rejected"
        meta["agenda_webhook"] = {
            **(meta.get("agenda_webhook") or {}),
            "appointment_id": appointment_id,
            "last_event_id": event_id,
            "occurred_at": occurred_at,
            "source": "agendamento_ia",
            "event": event,
        }
        supabase.table(Tables.SCHEDULING_APPOINTMENTS).update(
            {
                SchedulingAppointmentModel.STATUS: "cancelled",
                SchedulingAppointmentModel.META: meta,
                SchedulingAppointmentModel.UPDATED_AT: datetime.now(timezone.utc).isoformat(),
            }
        ).eq(SchedulingAppointmentModel.ID, str(existing["id"])).eq(
            SchedulingAppointmentModel.CLIENTE_ID, str(cliente_id)
        ).execute()
        return True, None, 200

    if not starts_at or not ends_at:
        return False, "starts_at_ou_ends_at_em_falta", 400

    service_id, err = _resolve_service_id(cliente_id, payload)
    if err == "service_id_desconhecido":
        payload_fallback = {**payload, "service_id": None}
        service_id, err = _resolve_service_id(cliente_id, payload_fallback)
    if err or not service_id:
        return False, err or "service_id_em_falta", 400

    provider_id = _resolve_professional_id(cliente_id, payload.get("provider_id"))

    meta_base: dict[str, Any] = {
        "agenda_webhook": {
            "appointment_id": appointment_id,
            "last_event_id": event_id,
            "occurred_at": occurred_at,
            "source": "agendamento_ia",
            "event": event,
            "agenda_service_id": (payload.get("service_id") or None),
            "agenda_provider_id": (payload.get("provider_id") or None),
        },
        "agenda_metadata": metadata,
    }
    if email:
        meta_base["contact_email"] = email
    if name:
        meta_base["contact_name"] = name
    if zapaction_appointment_id:
        meta_base["zapaction_appointment_id"] = zapaction_appointment_id
        meta_base["motor_sync"] = "synced"
    notes_parts = [name] if name else []
    notes = " — ".join(notes_parts) if notes_parts else None

    if existing:
        prev_meta = dict(existing.get(SchedulingAppointmentModel.META) or {})
        prev_status = str(
            existing.get(SchedulingAppointmentModel.STATUS) or existing.get("status") or ""
        ).lower()
        if prev_status == "cancelled" and status != "cancelled":
            return True, None, 200

        merged = {**prev_meta, **meta_base}
        if "agenda_metadata" in prev_meta and metadata:
            merged["agenda_metadata"] = {**(prev_meta.get("agenda_metadata") or {}), **metadata}
        update_row = {
            SchedulingAppointmentModel.SERVICE_ID: str(service_id),
            SchedulingAppointmentModel.PROFESSIONAL_ID: provider_id,
            SchedulingAppointmentModel.STARTS_AT: starts_at,
            SchedulingAppointmentModel.ENDS_AT: ends_at,
            SchedulingAppointmentModel.STATUS: status,
            SchedulingAppointmentModel.REMOTE_ID: remote_id or existing.get(
                SchedulingAppointmentModel.REMOTE_ID
            ),
            SchedulingAppointmentModel.CONTACT_PHONE: phone or existing.get(
                SchedulingAppointmentModel.CONTACT_PHONE
            ),
            SchedulingAppointmentModel.NOTES: notes if notes else existing.get(SchedulingAppointmentModel.NOTES),
            SchedulingAppointmentModel.META: merged,
            SchedulingAppointmentModel.UPDATED_AT: datetime.now(timezone.utc).isoformat(),
            SchedulingAppointmentModel.EXTERNAL_AGENDA_APPOINTMENT_ID: str(appointment_id),
        }
        if recurrence_series_id:
            update_row[SchedulingAppointmentModel.RECURRENCE_SERIES_ID] = recurrence_series_id
        if series_occurrence_at:
            update_row[SchedulingAppointmentModel.SERIES_OCCURRENCE_AT] = series_occurrence_at
        supabase.table(Tables.SCHEDULING_APPOINTMENTS).update(update_row).eq(SchedulingAppointmentModel.ID, str(existing["id"])).eq(
            SchedulingAppointmentModel.CLIENTE_ID, str(cliente_id)
        ).execute()
        if not _is_reconciliation_import(event_id) and prev_status != status:
            _dispatch_webhook_notifications(
                cliente_id=cliente_id,
                agenda_appointment_id=appointment_id,
                event=event,
                status=status,
                is_new=status == "pending" and prev_status != "pending",
            )
        return True, None, 200

    row = {
        SchedulingAppointmentModel.CLIENTE_ID: str(cliente_id),
        SchedulingAppointmentModel.EXTERNAL_AGENDA_APPOINTMENT_ID: str(appointment_id),
        SchedulingAppointmentModel.SERVICE_ID: str(service_id),
        SchedulingAppointmentModel.PROFESSIONAL_ID: provider_id,
        SchedulingAppointmentModel.STARTS_AT: starts_at,
        SchedulingAppointmentModel.ENDS_AT: ends_at,
        SchedulingAppointmentModel.STATUS: status,
        SchedulingAppointmentModel.REMOTE_ID: remote_id or None,
        SchedulingAppointmentModel.CONTACT_PHONE: phone or None,
        SchedulingAppointmentModel.NOTES: notes,
        SchedulingAppointmentModel.META: meta_base,
        SchedulingAppointmentModel.UPDATED_AT: datetime.now(timezone.utc).isoformat(),
    }
    if recurrence_series_id:
        row[SchedulingAppointmentModel.RECURRENCE_SERIES_ID] = recurrence_series_id
    if series_occurrence_at:
        row[SchedulingAppointmentModel.SERIES_OCCURRENCE_AT] = series_occurrence_at
    if zapaction_appointment_id:
        row[SchedulingAppointmentModel.ID] = zapaction_appointment_id
    supabase.table(Tables.SCHEDULING_APPOINTMENTS).insert(row).execute()
    if not _is_reconciliation_import(event_id):
        _dispatch_webhook_notifications(
            cliente_id=cliente_id,
            agenda_appointment_id=appointment_id,
            event=event,
            status=status,
            is_new=True,
        )
    return True, None, 200


def parse_json_body(raw_body: bytes) -> tuple[dict[str, Any] | None, str | None]:
    try:
        data = json.loads(raw_body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return None, "json_invalido"
    if not isinstance(data, dict):
        return None, "json_deve_ser_objeto"
    return data, None
