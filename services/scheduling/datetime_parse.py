"""Parse de campos datetime-local do painel (fuso da clínica)."""
from __future__ import annotations

from datetime import datetime

from services.scheduling.slot_engine import _get_tz
from services.scheduling.timezones import normalize_timezone


def parse_datetime_local(value: str, tz_name: str) -> datetime | None:
    """Converte ``YYYY-MM-DDTHH:MM`` no fuso da clínica para UTC aware."""
    raw = (value or "").strip()
    if not raw:
        return None
    try:
        naive = datetime.fromisoformat(raw)
    except ValueError:
        return None
    tz = _get_tz(normalize_timezone(tz_name))
    return naive.replace(tzinfo=tz)
