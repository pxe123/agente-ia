"""Vistas de calendário (dia / semana / mês) para o painel."""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from typing import Any

from services.scheduling.display import format_datetime_br, parse_iso_datetime
from services.scheduling.slot_engine import _get_tz
from services.scheduling.timezones import normalize_timezone


def parse_anchor_date(raw: str | None, tz_name: str) -> date:
    if raw:
        try:
            return date.fromisoformat(str(raw).strip()[:10])
        except ValueError:
            pass
    tz = _get_tz(normalize_timezone(tz_name))
    return datetime.now(timezone.utc).astimezone(tz).date()


def _event_blocks(
    appointments: list[dict[str, Any]],
    *,
    tz_name: str,
    prof_names: dict[str, str],
    service_names: dict[str, str],
) -> list[dict[str, Any]]:
    tz = _get_tz(normalize_timezone(tz_name))
    out: list[dict[str, Any]] = []
    for row in appointments or []:
        if str(row.get("status") or "").lower() == "cancelled":
            continue
        starts = parse_iso_datetime(row.get("starts_at"))
        ends = parse_iso_datetime(row.get("ends_at"))
        if not starts:
            continue
        local_start = starts.astimezone(tz)
        local_end = ends.astimezone(tz) if ends else local_start + timedelta(minutes=30)
        duration_min = max(15, int((local_end - local_start).total_seconds() // 60))
        pid = str(row.get("professional_id") or "")
        sid = str(row.get("service_id") or "")
        meta = row.get("meta_dict") if isinstance(row.get("meta_dict"), dict) else {}
        title = (
            (meta.get("contact_name") or "").strip()
            or (row.get("contact_display") or "").strip()
            or (row.get("contact_phone") or "").strip()
            or (row.get("remote_id") or "").strip()
            or "Cliente"
        )
        svc = service_names.get(sid, "")
        prof = prof_names.get(pid, "")
        label = title
        if svc:
            label = f"{title} — {svc}"
        out.append(
            {
                "id": str(row.get("id") or ""),
                "title": label,
                "prof_name": prof,
                "service_name": svc,
                "status": str(row.get("status") or ""),
                "day": local_start.date().isoformat(),
                "start_hour": local_start.hour + local_start.minute / 60.0,
                "duration_hours": duration_min / 60.0,
                "starts_at": starts.astimezone(timezone.utc).isoformat(),
                "starts_display": row.get("starts_at_display")
                or format_datetime_br(starts, tz_name),
                "origin": row.get("origin") or "local",
            }
        )
    return out


def build_week_days(anchor: date) -> list[date]:
    start = anchor - timedelta(days=anchor.weekday())
    return [start + timedelta(days=i) for i in range(7)]


def build_month_grid(anchor: date) -> list[list[date | None]]:
    first = anchor.replace(day=1)
    start = first - timedelta(days=(first.weekday()))
    grid: list[list[date | None]] = []
    cur = start
    for _ in range(6):
        row: list[date | None] = []
        for _ in range(7):
            row.append(cur if cur.month == anchor.month else None)
            cur += timedelta(days=1)
        grid.append(row)
    return grid


def build_calendar_view(
    *,
    view: str,
    anchor: date,
    appointments: list[dict[str, Any]],
    tz_name: str,
    prof_names: dict[str, str],
    service_names: dict[str, str],
) -> dict[str, Any]:
    v = (view or "week").strip().lower()
    if v not in ("day", "week", "month"):
        v = "week"
    events = _event_blocks(
        appointments,
        tz_name=tz_name,
        prof_names=prof_names,
        service_names=service_names,
    )
    if v == "day":
        days = [anchor]
    elif v == "month":
        days = [d for week in build_month_grid(anchor) for d in week if d]
    else:
        days = build_week_days(anchor)
        v = "week"

    day_set = {d.isoformat() for d in days}
    by_day: dict[str, list[dict[str, Any]]] = {d.isoformat(): [] for d in days}
    for ev in events:
        if ev["day"] in by_day:
            by_day[ev["day"]].append(ev)

    hours = list(range(7, 21))
    return {
        "view": v,
        "anchor": anchor.isoformat(),
        "days": [{"date": d.isoformat(), "label": d.strftime("%d/%m"), "weekday": d.strftime("%a")} for d in days],
        "events_by_day": by_day,
        "month_grid": build_month_grid(anchor) if v == "month" else None,
        "hours": hours,
        "events": [e for e in events if e["day"] in day_set],
    }
