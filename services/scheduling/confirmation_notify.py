"""Notificações WhatsApp para fluxo de confirmação de agendamento."""
from __future__ import annotations

import logging
from datetime import datetime
from typing import Any

from base.domain_redirects import public_base_url
from database.models import ClienteModel, Tables
from database.supabase_sq import supabase
from services.routing_service import RoutingService
from services.scheduling import repository
from services.scheduling.display import format_datetime_br

logger = logging.getLogger(__name__)


def _client_whatsapp_instancia(cliente_id: str) -> str:
    try:
        if not supabase:
            return "default"
        r = (
            supabase.table(Tables.CLIENTES)
            .select(ClienteModel.WHATSAPP_INSTANCIA)
            .eq(ClienteModel.ID, str(cliente_id))
            .limit(1)
            .execute()
        )
        return ((r.data or [{}])[0]).get(ClienteModel.WHATSAPP_INSTANCIA) or "default"
    except Exception:
        return "default"


def _clinic_notify_phone(cliente_id: str) -> str:
    try:
        if not supabase:
            return ""
        r = (
            supabase.table(Tables.CLIENTES)
            .select(ClienteModel.NOTIFY_WHATSAPP)
            .eq(ClienteModel.ID, str(cliente_id))
            .limit(1)
            .execute()
        )
        phone = ((r.data or [{}])[0]).get(ClienteModel.NOTIFY_WHATSAPP) or ""
        return "".join(c for c in str(phone) if c.isdigit())
    except Exception:
        return ""


def _clinic_whatsapp_link(cliente_id: str) -> str | None:
    phone = _clinic_notify_phone(cliente_id)
    if len(phone) >= 10:
        return f"https://wa.me/{phone}"
    return None


def _normalize_dest_phone(phone: str) -> str:
    """E.164 em dígitos (ex.: 5514999999999) para envio WAHA."""
    from services.scheduling.public_contact import normalize_scheduling_contact_phone

    return normalize_scheduling_contact_phone(phone) or ""


def _send_whatsapp(cliente_id: str, phone: str, text: str) -> tuple[bool, str | None]:
    phone = _normalize_dest_phone(phone)
    if not phone or len(phone) < 10 or not text.strip():
        return False, "Telefone de destino inválido."
    instancia = _client_whatsapp_instancia(cliente_id)
    ok, err = RoutingService.enviar_resposta(
        "whatsapp",
        instancia,
        phone,
        text,
        cliente_id=str(cliente_id),
    )
    if not ok:
        logger.info("confirmation_notify failed cliente=%s err=%s", str(cliente_id)[:8], err)
    return bool(ok), err


def send_scheduling_whatsapp_text(cliente_id: str, phone: str, text: str) -> tuple[bool, str | None]:
    """Envio genérico de texto WhatsApp (ex.: resumo de série recorrente)."""
    return _send_whatsapp(cliente_id, phone, text)


def _appointment_context(cliente_id: str, appointment_id: str) -> dict[str, Any]:
    row = repository.get_appointment(cliente_id, appointment_id) or {}
    st = repository.get_settings(cliente_id) or {}
    tz = str(st.get("timezone") or "America/Sao_Paulo")
    svc = repository.get_service(cliente_id, str(row.get("service_id") or ""))
    prof = repository.get_professional(cliente_id, str(row.get("professional_id") or ""))
    meta = row.get("meta") if isinstance(row.get("meta"), dict) else {}
    when = format_datetime_br(row.get("starts_at"), tz)
    contact_phone = row.get("contact_phone") or row.get("remote_id") or ""
    return {
        "row": row,
        "tz": tz,
        "service_name": (svc or {}).get("name") or "serviço",
        "prof_name": (prof or {}).get("name") or "profissional",
        "when": when,
        "contact_name": meta.get("contact_name") or "",
        "phone": contact_phone,
        "contact_phone": contact_phone,
    }


def _pending_booking_message(ctx: dict[str, Any]) -> str:
    base = public_base_url().rstrip("/")
    panel_url = f"{base}/painel/agenda?tab=agendamentos&status=pending"
    contact_line = ctx["contact_name"] or "—"
    if ctx.get("contact_phone"):
        contact_line = f"{contact_line} ({ctx['contact_phone']})"
    return (
        f"Novo pedido de agendamento pendente de confirmação:\n"
        f"Cliente: {contact_line}\n"
        f"Serviço: {ctx['service_name']}\n"
        f"Profissional: {ctx['prof_name']}\n"
        f"Horário: {ctx['when']}\n"
        f"Confirmar no painel: {panel_url}"
    )


def notify_pending_booking(cliente_id: str, appointment_row: dict[str, Any]) -> bool:
    """Avisa clínica (notify_whatsapp) ou, em fallback, o profissional."""
    aid = str(appointment_row.get("id") or "")
    if not aid:
        return False
    ctx = _appointment_context(cliente_id, aid)
    text = _pending_booking_message(ctx)

    clinic_phone = _clinic_notify_phone(cliente_id)
    if len(clinic_phone) >= 10:
        ok, _ = _send_whatsapp(cliente_id, clinic_phone, text)
        return ok

    pid = str((ctx["row"] or {}).get("professional_id") or "")
    prof = repository.get_professional(cliente_id, pid) if pid else None
    prof_phone = (prof or {}).get("whatsapp_notify_phone") or ""
    if prof_phone:
        ok, _ = _send_whatsapp(cliente_id, prof_phone, text)
        return ok

    logger.info(
        "notify_pending_booking skipped cliente=%s appointment=%s (sem notify_whatsapp nem profissional)",
        str(cliente_id)[:8],
        aid[:8],
    )
    return False


def notify_professional_pending_booking(cliente_id: str, appointment_row: dict[str, Any]) -> bool:
    """Alias retrocompatível — usa notify_pending_booking."""
    return notify_pending_booking(cliente_id, appointment_row)


def notify_client_confirmed(cliente_id: str, appointment_id: str) -> bool:
    ctx = _appointment_context(cliente_id, appointment_id)
    text = (
        f"Seu horário foi confirmado com sucesso.\n"
        f"{ctx['service_name']} — {ctx['when']}"
    )
    ok, _ = _send_whatsapp(cliente_id, ctx["phone"], text)
    return ok


def notify_client_rejected(cliente_id: str, appointment_id: str) -> bool:
    ctx = _appointment_context(cliente_id, appointment_id)
    link = _clinic_whatsapp_link(cliente_id)
    text = (
        f"Infelizmente não foi possível confirmar o horário solicitado ({ctx['when']}).\n"
        f"Entre em contacto com a clínica para reagendar."
    )
    if link:
        text += f"\n{link}"
    ok, _ = _send_whatsapp(cliente_id, ctx["phone"], text)
    return ok


def notify_client_proposal(
    cliente_id: str,
    appointment_id: str,
    *,
    proposal_url: str,
    proposed_starts_at: datetime,
    accept_url: str = "",
    decline_url: str = "",
    is_reschedule: bool = False,
) -> bool:
    ctx = _appointment_context(cliente_id, appointment_id)
    when_new = format_datetime_br(proposed_starts_at.isoformat(), ctx["tz"])
    url = proposal_url or accept_url
    if is_reschedule:
        text = (
            f"A clínica sugere remarcar seu horário de {ctx['when']} para {when_new}.\n"
            f"Confirme ou recuse aqui: {url}"
        )
    else:
        text = (
            f"A clínica sugere um novo horário: {when_new}\n"
            f"Responda aqui: {url}"
        )
    ok, _ = _send_whatsapp(cliente_id, ctx["phone"], text)
    return ok


def notify_client_slot_submitted(cliente_id: str, appointment_id: str) -> bool:
    ctx = _appointment_context(cliente_id, appointment_id)
    text = (
        f"Recebemos sua sugestão de horário: {ctx['when']}.\n"
        f"A clínica vai confirmar em breve. Obrigado!"
    )
    ok, _ = _send_whatsapp(cliente_id, ctx["phone"], text)
    return ok
