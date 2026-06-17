"""Parse de campos datetime-local do painel (fuso da clínica)."""
from __future__ import annotations

from datetime import datetime
from typing import Any

from services.scheduling.repository import parse_row_datetime
from services.scheduling.slot_engine import _get_tz
from services.scheduling.timezones import normalize_timezone


def format_datetime_local_input(value: Any, tz_name: str) -> str:
    """Formata datetime para ``<input type=\"datetime-local\">`` no fuso da clínica."""
    dt = parse_row_datetime(value)
    if not dt:
        return ""
    tz = _get_tz(normalize_timezone(tz_name))
    local = dt.astimezone(tz)
    return local.strftime("%Y-%m-%dT%H:%M")


def _has_tz_offset(raw: str) -> bool:
    s = (raw or "").strip()
    if not s:
        return False
    if s.endswith("Z") or s.endswith("z"):
        return True
    if len(s) >= 6 and s[-6] in "+-" and ":" in s[-5:]:
        return True
    if len(s) >= 3 and s[-3] in "+-" and s[-2:].isdigit():
        return True
    return False


def parse_datetime_local(value: str, tz_name: str) -> datetime | None:
    """Converte ``YYYY-MM-DDTHH:MM`` no fuso da clínica para datetime aware."""
    raw = (value or "").strip()
    if not raw:
        return None
    try:
        naive = datetime.fromisoformat(raw)
    except ValueError:
        return None
    tz = _get_tz(normalize_timezone(tz_name))
    return naive.replace(tzinfo=tz)


def parse_panel_datetime(value: str, tz_name: str) -> datetime | None:
    """
    Parse de datetime do painel/API:
    - com offset ou Z → ISO absoluto;
    - sem offset → fuso da clínica (datetime-local).
    """
    raw = (value or "").strip()
    if not raw:
        return None
    if _has_tz_offset(raw):
        try:
            dt = datetime.fromisoformat(raw.replace("Z", "+00:00").replace("z", "+00:00"))
        except ValueError:
            return None
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=_get_tz(normalize_timezone(tz_name)))
        return dt
    return parse_datetime_local(raw, tz_name)
