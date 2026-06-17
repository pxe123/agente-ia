"""Convite de calendário ao cliente via WhatsApp (link genérico, V1)."""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Literal
from urllib.parse import urlencode

from base.config import settings
from services.scheduling import repository
from services.scheduling.display import appointment_meta_dict, format_datetime_br, parse_iso_datetime
from services.scheduling.public_contact import normalize_scheduling_contact_phone
from services.scheduling.slot_engine import _get_tz
from services.scheduling.timezones import normalize_timezone

logger = logging.getLogger(__name__)

InviteKind = Literal["confirmed", "rescheduled"]


def client_calendar_invites_enabled() -> bool:
    return bool(getattr(settings, "ENABLE_CLIENT_CALENDAR_INVITE", True))


def _gcal_datetime_local(dt: datetime, tz_name: str) -> str:
    tz = _get_tz(normalize_timezone(tz_name))
    return dt.astimezone(tz).strftime("%Y%m%dT%H%M%S")


def _resolve_context(cliente_id: str, row: dict[str, Any]) -> dict[str, Any]:
    st = repository.get_settings(cliente_id) or {}
    tz = normalize_timezone(str(st.get("timezone") or ""))
    clinic_name = (st.get("public_name") or "").strip() or "Consulta"
    svc = repository.get_service(cliente_id, str(row.get("service_id") or ""))
    prof = repository.get_professional(cliente_id, str(row.get("professional_id") or ""))
    meta = appointment_meta_dict(row.get("meta"))
    contact_name = (meta.get("contact_name") or "").strip() or "Cliente"
    service_name = (svc or {}).get("name") or "serviço"
    prof_name = (prof or {}).get("name") or ""
    when = format_datetime_br(row.get("starts_at"), tz)
    return {
        "tz": tz,
        "clinic_name": clinic_name,
        "service_name": service_name,
        "prof_name": prof_name,
        "contact_name": contact_name,
        "when": when,
    }


def build_calendar_add_url(row: dict[str, Any], context: dict[str, Any]) -> str:
    """URL pública para adicionar evento (implementação atual: Google Calendar template)."""
    starts = parse_iso_datetime(row.get("starts_at"))
    ends = parse_iso_datetime(row.get("ends_at"))
    if not starts or not ends:
        return ""
    tz_name = context["tz"]
    title = f"{context['service_name']} — {context['clinic_name']}"
    details_parts = [f"Cliente: {context['contact_name']}"]
    if context.get("prof_name"):
        details_parts.append(f"Profissional: {context['prof_name']}")
    notes = (row.get("notes") or "").strip()
    if notes:
        details_parts.append(notes)
    params = {
        "action": "TEMPLATE",
        "text": title,
        "dates": f"{_gcal_datetime_local(starts, tz_name)}/{_gcal_datetime_local(ends, tz_name)}",
        "details": "\n".join(details_parts),
        "location": context["clinic_name"],
        "ctz": tz_name,
    }
    return f"https://calendar.google.com/calendar/render?{urlencode(params)}"


def build_invite_message_parts(
    row: dict[str, Any],
    context: dict[str, Any],
    *,
    kind: InviteKind = "confirmed",
) -> tuple[str, str]:
    """Retorna (intro, linha_cta) sem URL."""
    name = context["contact_name"]
    when = context["when"]
    service = context["service_name"]
    if kind == "rescheduled":
        intro = (
            f"Olá {name}! Seu horário foi remarcado.\n\n"
            f"Nova data:\n{when}"
        )
        cta = "📅 Atualize sua agenda:"
    else:
        intro = f"Olá {name}! Seu horário foi confirmado:\n{service} — {when}"
        cta = "📅 Adicionar ao calendário"
    return intro, cta


def build_invite_text_with_link(
    row: dict[str, Any],
    context: dict[str, Any],
    calendar_url: str,
    *,
    kind: InviteKind = "confirmed",
) -> str:
    intro, cta = build_invite_message_parts(row, context, kind=kind)
    if kind == "rescheduled":
        return f"{intro}\n\n{cta}\n{calendar_url}"
    return f"{intro}\n\n{cta}\n{calendar_url}"


def build_calendar_invite_append_for_row(cliente_id: str, row: dict[str, Any]) -> str:
    """Bloco opcional para anexar a outra mensagem (ex.: resumo de série)."""
    if not client_calendar_invites_enabled():
        return ""
    if str(row.get("status") or "").lower() != "confirmed":
        return ""
    ctx = _resolve_context(cliente_id, row)
    url = build_calendar_add_url(row, ctx)
    if not url:
        return ""
    return f"\n\n📅 Adicionar ao calendário:\n{url}"


def _appointment_phone(row: dict[str, Any]) -> str:
    meta = appointment_meta_dict(row.get("meta"))
    for cand in (
        row.get("contact_phone"),
        row.get("remote_id"),
        meta.get("contact_phone"),
    ):
        norm = normalize_scheduling_contact_phone(str(cand or ""))
        if norm:
            return norm
    return ""


def _starts_at_key(row: dict[str, Any]) -> str:
    starts = parse_iso_datetime(row.get("starts_at"))
    if not starts:
        return str(row.get("starts_at") or "").strip()
    return starts.astimezone(timezone.utc).isoformat()


def _already_sent_for_slot(meta: dict[str, Any], starts_key: str) -> bool:
    sent_for = str(meta.get("calendar_invite_for_starts_at") or "").strip()
    return bool(sent_for and sent_for == starts_key)


def _send_invite_whatsapp(
    cliente_id: str,
    phone: str,
    intro: str,
    cta: str,
    calendar_url: str,
) -> tuple[bool, str | None]:
    from services.scheduling.confirmation_notify import (
        _client_whatsapp_instancia,
        _normalize_dest_phone,
        send_scheduling_whatsapp_text,
    )

    phone_norm = _normalize_dest_phone(phone)
    if not phone_norm:
        return False, "Telefone de destino inválido."

    instancia = _client_whatsapp_instancia(cliente_id)
    body_with_link = f"{intro}\n\n{cta}\n{calendar_url}"

    if getattr(settings, "WAHA_URL", None) and getattr(settings, "WAHA_API_KEY", None):
        try:
            from integrations.whatsapp.waha_client import enviar_botoes

            ok, err = enviar_botoes(
                phone_norm,
                body_with_link,
                [{"id": "calendar_ok", "title": "Entendido"}],
                session=instancia,
            )
            if ok:
                return True, None
            logger.info("calendar invite buttons failed cliente=%s err=%s", str(cliente_id)[:8], err)
        except Exception as exc:
            logger.info("calendar invite buttons exception cliente=%s err=%s", str(cliente_id)[:8], exc)

    fallback = f"{intro}\n\n📅 Clique aqui para adicionar ao calendário:\n{calendar_url}"
    return send_scheduling_whatsapp_text(cliente_id, phone_norm, fallback)


def maybe_send_client_calendar_invite(
    cliente_id: str,
    row: dict[str, Any],
    *,
    kind: InviteKind = "confirmed",
) -> tuple[bool, str | None]:
    if not client_calendar_invites_enabled():
        return False, "desativado"
    try:
        from services.scheduling.engine import scheduling_uses_internal_motor

        if not scheduling_uses_internal_motor(cliente_id):
            return False, "motor_externo"
    except Exception:
        pass

    if str(row.get("status") or "").lower() != "confirmed":
        return False, "nao_confirmado"

    phone = _appointment_phone(row)
    if not phone:
        return False, "sem_telefone"

    meta = appointment_meta_dict(row.get("meta"))
    starts_key = _starts_at_key(row)
    if _already_sent_for_slot(meta, starts_key):
        return False, "ja_enviado"

    ctx = _resolve_context(cliente_id, row)
    calendar_url = build_calendar_add_url(row, ctx)
    if not calendar_url:
        return False, "url_invalida"

    intro, cta = build_invite_message_parts(row, ctx, kind=kind)
    ok, err = _send_invite_whatsapp(cliente_id, phone, intro, cta, calendar_url)
    if not ok:
        return False, err

    aid = str(row.get("id") or "")
    if aid:
        repository.merge_appointment_meta(
            cliente_id,
            aid,
            {
                "calendar_invite_sent_at": datetime.now(timezone.utc).isoformat(),
                "calendar_invite_for_starts_at": starts_key,
            },
        )
    return True, None


def on_appointment_confirmed(
    cliente_id: str,
    appointment_id: str,
    *,
    kind: InviteKind = "confirmed",
) -> tuple[bool, str | None]:
    row = repository.get_appointment(cliente_id, appointment_id)
    if not row:
        return False, "nao_encontrado"
    return maybe_send_client_calendar_invite(cliente_id, row, kind=kind)
