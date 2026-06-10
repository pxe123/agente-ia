"""
Formatação de datas/horas da agenda para exibição no painel (pt-BR, fuso da clínica).
"""
from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from typing import Any

from services.scheduling.slot_engine import _get_tz
from services.scheduling.timezones import DEFAULT_TIMEZONE, normalize_timezone


def parse_iso_datetime(value: Any) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    s = str(value).strip()
    if not s:
        return None
    try:
        dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def format_datetime_br(
    iso_or_dt: Any,
    tz_name: str | None = None,
    *,
    date_only: bool = False,
) -> str:
    """
    Converte instante UTC (ISO) para texto pt-BR no fuso da clínica.
    Ex.: 21/05/2026 14:30
    """
    dt = iso_or_dt if isinstance(iso_or_dt, datetime) else parse_iso_datetime(iso_or_dt)
    if not dt:
        return "—"
    tz = _get_tz(normalize_timezone(tz_name))
    local = dt.astimezone(tz)
    if date_only:
        return local.strftime("%d/%m/%Y")
    return local.strftime("%d/%m/%Y %H:%M")


def appointment_meta_dict(meta: Any) -> dict[str, Any]:
    if isinstance(meta, dict):
        return meta
    if isinstance(meta, str) and meta.strip():
        try:
            parsed = json.loads(meta)
            if isinstance(parsed, dict):
                return parsed
        except (TypeError, ValueError):
            pass
    return {}


def _phone_digits(raw: str) -> str:
    return re.sub(r"\D", "", raw or "")


def format_phone_br_display(phone: str | None) -> str:
    """Ex.: (14) 99875-7520 ou +55 (14) 99875-7520."""
    raw = (phone or "").strip()
    if not raw:
        return "—"
    if "@" in raw:
        raw = raw.split("@", 1)[0]
    digits = _phone_digits(raw)
    if len(digits) == 13 and digits.startswith("55"):
        return f"+55 ({digits[2:4]}) {digits[4:9]}-{digits[9:]}"
    if len(digits) == 12 and digits.startswith("55"):
        return f"+55 ({digits[2:4]}) {digits[4:8]}-{digits[8:]}"
    if len(digits) == 11:
        return f"({digits[:2]}) {digits[2:7]}-{digits[7:]}"
    if len(digits) == 10:
        return f"({digits[:2]}) {digits[2:6]}-{digits[6:]}"
    return raw


def _contact_name_and_phone(row: dict[str, Any], meta: dict[str, Any]) -> tuple[str, str]:
    name = (meta.get("contact_name") or "").strip()
    if not name:
        notes = (row.get("notes") or "").strip()
        if notes and _phone_digits(notes) != notes.replace(" ", ""):
            name = notes

    phone_raw = (row.get("contact_phone") or "").strip()
    if not phone_raw:
        remote = (row.get("remote_id") or "").strip()
        if remote and remote.lower() not in ("public", "guest", "anonymous"):
            candidate = remote.split("@", 1)[0] if "@" in remote else remote
            digits = _phone_digits(candidate)
            if len(digits) >= 10:
                phone_raw = digits

    return name or "—", format_phone_br_display(phone_raw)


def enrich_appointments_display(
    rows: list[dict[str, Any]] | None,
    tz_name: str | None,
) -> list[dict[str, Any]]:
    """Adiciona campos de exibição em cada linha (cópia superficial)."""
    tz = normalize_timezone(tz_name)
    out: list[dict[str, Any]] = []
    for row in rows or []:
        r = dict(row)
        r["starts_at_display"] = format_datetime_br(r.get("starts_at"), tz)
        if r.get("ends_at"):
            r["ends_at_display"] = format_datetime_br(r.get("ends_at"), tz)
        meta = appointment_meta_dict(r.get("meta"))
        r["meta_dict"] = meta
        contact_name, contact_phone = _contact_name_and_phone(r, meta)
        r["contact_name_display"] = contact_name
        r["contact_phone_display"] = contact_phone
        r["contact_display"] = (
            contact_name
            if contact_name != "—"
            else contact_phone
            if contact_phone != "—"
            else "—"
        )
        out.append(r)
    return out
