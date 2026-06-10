"""Lembretes automáticos de marcação via WhatsApp (P2)."""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any

from base.config import settings
from database.models import ClienteModel, Tables
from database.supabase_sq import supabase
from services.routing_service import RoutingService
from services.scheduling.display import appointment_meta_dict, format_datetime_br, parse_iso_datetime
from services.scheduling.repository import merge_appointment_meta

logger = logging.getLogger(__name__)


def _reminder_hours() -> list[int]:
    raw = (getattr(settings, "SCHEDULING_REMINDER_HOURS_BEFORE", "") or "24").strip()
    out: list[int] = []
    for part in raw.split(","):
        part = part.strip()
        if not part:
            continue
        try:
            h = int(part)
            if h > 0:
                out.append(h)
        except ValueError:
            continue
    return out or [24]


def reminders_enabled() -> bool:
    return bool(getattr(settings, "SCHEDULING_REMINDERS_ENABLED", False))


def _appointment_phone(row: dict[str, Any]) -> str:
    meta = appointment_meta_dict(row.get("meta"))
    for cand in (
        row.get("contact_phone"),
        row.get("remote_id"),
        meta.get("contact_phone"),
    ):
        s = "".join(c for c in str(cand or "") if c.isdigit())
        if len(s) >= 10:
            return s
    return ""


def _build_message(row: dict[str, Any], *, hours_before: int, tz_name: str) -> str:
    starts = parse_iso_datetime(row.get("starts_at"))
    when = format_datetime_br(starts, tz_name) if starts else "em breve"
    name = appointment_meta_dict(row.get("meta")).get("contact_name") or ""
    greeting = f"Olá{', ' + name if name else ''}!"
    return (
        f"{greeting} Lembrete: seu agendamento é em {hours_before}h ({when}). "
        "Qualquer alteração, responda neste chat."
    )


def run_appointment_reminders(*, limit: int = 200) -> dict[str, Any]:
    """
    Envia lembretes WhatsApp para marcações confirmadas no intervalo configurado.
    Marca envio em ``meta.reminders_sent`` para idempotência.
    """
    if not reminders_enabled():
        return {"ok": True, "skipped": True, "reason": "disabled"}
    if not supabase:
        return {"ok": False, "error": "sem_supabase"}

    now = datetime.now(timezone.utc)
    hours_list = _reminder_hours()
    sent = 0
    skipped = 0
    failed = 0

    for hours_before in hours_list:
        window_start = now + timedelta(hours=hours_before) - timedelta(minutes=20)
        window_end = now + timedelta(hours=hours_before) + timedelta(minutes=20)
        try:
            rows = (
                supabase.table(Tables.SCHEDULING_APPOINTMENTS)
                .select("*")
                .eq("status", "confirmed")
                .gte("starts_at", window_start.isoformat())
                .lte("starts_at", window_end.isoformat())
                .limit(max(1, int(limit)))
                .execute()
                .data
                or []
            )
        except Exception as e:
            logger.warning("scheduling reminders query failed: %s", e)
            return {"ok": False, "error": str(e)}

        for row in rows:
            cid = str(row.get("cliente_id") or "")
            aid = str(row.get("id") or "")
            if not cid or not aid:
                skipped += 1
                continue
            meta = appointment_meta_dict(row.get("meta"))
            sent_map = meta.get("reminders_sent") if isinstance(meta.get("reminders_sent"), dict) else {}
            key = f"{hours_before}h"
            if sent_map.get(key):
                skipped += 1
                continue
            phone = _appointment_phone(row)
            if not phone:
                skipped += 1
                continue
            try:
                st = (
                    supabase.table(Tables.SCHEDULING_SETTINGS)
                    .select("timezone")
                    .eq("cliente_id", cid)
                    .limit(1)
                    .execute()
                )
                tz_name = ((st.data or [{}])[0]).get("timezone") or "America/Sao_Paulo"
            except Exception:
                tz_name = "America/Sao_Paulo"
            text = _build_message(row, hours_before=hours_before, tz_name=tz_name)
            try:
                cliente = (
                    supabase.table(Tables.CLIENTES)
                    .select(ClienteModel.WHATSAPP_INSTANCIA)
                    .eq(ClienteModel.ID, cid)
                    .limit(1)
                    .execute()
                )
                instancia = ((cliente.data or [{}])[0]).get(ClienteModel.WHATSAPP_INSTANCIA) or "default"
            except Exception:
                instancia = "default"
            ok, err = RoutingService.enviar_resposta(
                "whatsapp",
                instancia,
                phone,
                text,
                cliente_id=cid,
            )
            if ok:
                merge_appointment_meta(
                    cid,
                    aid,
                    {"reminders_sent": {**sent_map, key: now.isoformat()}},
                )
                sent += 1
            else:
                logger.info("reminder failed cliente=%s appt=%s err=%s", cid[:8], aid[:8], err)
                failed += 1

    return {"ok": True, "sent": sent, "skipped": skipped, "failed": failed, "hours": hours_list}
