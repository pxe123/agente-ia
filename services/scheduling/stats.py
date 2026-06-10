"""Estatísticas da agenda para dashboard P2."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from services.scheduling.display import parse_iso_datetime
from services.scheduling.slot_engine import _get_tz
from services.scheduling.timezones import normalize_timezone


def compute_dashboard_stats(
    appointments: list[dict[str, Any]],
    *,
    tz_name: str,
) -> dict[str, int]:
    tz = _get_tz(normalize_timezone(tz_name))
    now_utc = datetime.now(timezone.utc)
    now_local = now_utc.astimezone(tz)
    today = now_local.date()
    week_start = today - timedelta(days=today.weekday())
    week_end = week_start + timedelta(days=7)
    month_start = today.replace(day=1)
    if month_start.month == 12:
        month_end = month_start.replace(year=month_start.year + 1, month=1)
    else:
        month_end = month_start.replace(month=month_start.month + 1)
    in_24h = now_utc + timedelta(hours=24)

    stats = {
        "today": 0,
        "this_week": 0,
        "next_24h": 0,
        "cancelled_month": 0,
        "upcoming_total": 0,
    }
    for row in appointments or []:
        st = str(row.get("status") or "").lower()
        starts = parse_iso_datetime(row.get("starts_at"))
        if not starts:
            continue
        local_start = starts.astimezone(tz)
        d = local_start.date()
        if st == "cancelled":
            if month_start <= d < month_end:
                stats["cancelled_month"] += 1
            continue
        if d == today:
            stats["today"] += 1
        if week_start <= d < week_end:
            stats["this_week"] += 1
        if now_utc < starts <= in_24h:
            stats["next_24h"] += 1
        if starts >= now_utc:
            stats["upcoming_total"] += 1
    return stats
