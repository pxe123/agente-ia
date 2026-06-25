"""Vistas de calendário (dia / semana / mês) para o painel."""
from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone
from typing import Any

from services.scheduling.blocks import block_scope
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


def _parse_time_hms(v: Any) -> time | None:
    if isinstance(v, time):
        return v
    s = str(v or "").strip()
    if not s:
        return None
    if len(s) >= 5 and ":" in s:
        parts = s.replace("T", " ").split()
        if len(parts) >= 2:
            s = parts[-1]
        seg = s.split(":")
        try:
            h = int(seg[0])
            m = int(seg[1]) if len(seg) > 1 else 0
            sec = int(seg[2]) if len(seg) > 2 else 0
            return time(h, m, sec)
        except (TypeError, ValueError):
            return None
    return None


def _calendar_hour_range(
    events: list[dict[str, Any]],
    working_rows: list[dict[str, Any]] | None,
) -> tuple[int, list[int]]:
    """Retorna (grid_start_hour, lista de horas inteiras) com margem em torno de horários e eventos."""
    min_h = 7
    max_h = 20
    for row in working_rows or []:
        st = _parse_time_hms(row.get("start_time"))
        et = _parse_time_hms(row.get("end_time"))
        if st:
            min_h = min(min_h, st.hour)
        if et:
            end_hour = et.hour if (et.minute, et.second) == (0, 0) else et.hour + 1
            max_h = max(max_h, min(23, end_hour))
    for ev in events or []:
        sh = float(ev.get("start_hour") or 0)
        dur = float(ev.get("duration_hours") or 1)
        min_h = min(min_h, int(sh))
        max_h = max(max_h, min(23, int(sh + dur) + (1 if (sh + dur) % 1 else 0)))
    grid_start = max(0, min_h - 1)
    grid_end = min(24, max_h + 2)
    if grid_end <= grid_start:
        grid_start, grid_end = 7, 21
    return grid_start, list(range(grid_start, grid_end))


def _appointment_client_name(row: dict[str, Any]) -> str:
    meta = row.get("meta_dict") if isinstance(row.get("meta_dict"), dict) else {}
    name = (
        (row.get("contact_name_display") or "").strip()
        or (meta.get("contact_name") or "").strip()
        or (row.get("contact_display") or "").strip()
        or (row.get("contact_phone") or "").strip()
        or (row.get("remote_id") or "").strip()
        or "Cliente"
    )
    if name == "—":
        return "Cliente"
    return name


def _appointment_display_label(row: dict[str, Any], service_name: str) -> str:
    client = _appointment_client_name(row)
    svc = (service_name or "").strip()
    if svc:
        return f"{client} - {svc}"
    return client


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
        cancelled = str(row.get("status") or "").lower() == "cancelled"
        status_l = str(row.get("status") or "").lower()
        status_tone = (
            "cancelled"
            if cancelled
            else ("pending" if status_l == "pending" else "local")
        )
        starts = parse_iso_datetime(row.get("starts_at"))
        ends = parse_iso_datetime(row.get("ends_at"))
        if not starts:
            continue
        local_start = starts.astimezone(tz)
        local_end = ends.astimezone(tz) if ends else local_start + timedelta(minutes=30)
        duration_min = max(15, int((local_end - local_start).total_seconds() // 60))
        pid = str(row.get("professional_id") or "")
        sid = str(row.get("service_id") or "")
        svc = service_names.get(sid, "")
        prof = prof_names.get(pid, "")
        label = _appointment_display_label(row, svc)
        out.append(
            {
                "id": str(row.get("id") or ""),
                "title": label,
                "display_label": label,
                "client_name": _appointment_client_name(row),
                "prof_name": prof,
                "service_name": svc,
                "status": str(row.get("status") or ""),
                "status_tone": status_tone,
                "cancelled": cancelled,
                "day": local_start.date().isoformat(),
                "start_hour": local_start.hour + local_start.minute / 60.0,
                "duration_hours": duration_min / 60.0,
                "starts_at": starts.astimezone(timezone.utc).isoformat(),
                "time_short": local_start.strftime("%H:%M"),
                "starts_display": row.get("starts_at_display")
                or format_datetime_br(starts, tz_name),
                "origin": row.get("origin") or "local",
                "event_kind": "appointment",
                "is_recurring": bool(row.get("recurrence_series_id")),
                "recurrence_series_id": str(row.get("recurrence_series_id") or "") or None,
                "series_status": row.get("series_status"),
            }
        )
    return out


def _block_event_blocks(
    blocked_times: list[dict[str, Any]],
    *,
    tz_name: str,
    prof_names: dict[str, str],
) -> list[dict[str, Any]]:
    tz = _get_tz(normalize_timezone(tz_name))
    out: list[dict[str, Any]] = []
    for row in blocked_times or []:
        starts = parse_iso_datetime(row.get("starts_at"))
        ends = parse_iso_datetime(row.get("ends_at"))
        if not starts:
            continue
        local_start = starts.astimezone(tz)
        local_end = ends.astimezone(tz) if ends else local_start + timedelta(hours=1)
        duration_min = max(15, int((local_end - local_start).total_seconds() // 60))
        pid = row.get("professional_id")
        pid_str = str(pid) if pid not in (None, "") else ""
        scope = block_scope(pid_str or None)
        reason = (row.get("reason") or "").strip()
        if scope == "clinic":
            label = f"Clínica — {reason}" if reason else "Clínica — Bloqueado"
        else:
            prof = prof_names.get(pid_str, "Profissional")
            label = reason or f"Bloqueado — {prof}"
        out.append(
            {
                "id": str(row.get("id") or ""),
                "title": label,
                "prof_name": prof_names.get(pid_str, "") if scope == "professional" else "Clínica",
                "scope": scope,
                "day": local_start.date().isoformat(),
                "start_hour": local_start.hour + local_start.minute / 60.0,
                "duration_hours": duration_min / 60.0,
                "starts_at": starts.astimezone(timezone.utc).isoformat(),
                "ends_at": ends.astimezone(timezone.utc).isoformat() if ends else "",
                "starts_display": format_datetime_br(starts, tz_name),
                "ends_display": format_datetime_br(ends, tz_name) if ends else "",
                "reason": reason,
                "professional_id": pid_str or None,
                "event_kind": "block",
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
    blocked_times: list[dict[str, Any]] | None = None,
    working_rows: list[dict[str, Any]] | None = None,
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
    events.extend(
        _block_event_blocks(
            blocked_times or [],
            tz_name=tz_name,
            prof_names=prof_names,
        )
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

    visible_events = [e for e in events if e["day"] in day_set]
    grid_start, hours = _calendar_hour_range(visible_events, working_rows)
    row_px = 48
    return {
        "view": v,
        "anchor": anchor.isoformat(),
        "days": [{"date": d.isoformat(), "label": d.strftime("%d/%m"), "weekday": d.strftime("%a")} for d in days],
        "events_by_day": by_day,
        "month_grid": build_month_grid(anchor) if v == "month" else None,
        "hours": hours,
        "grid_start_hour": grid_start,
        "row_px": row_px,
        "grid_height_px": len(hours) * row_px,
        "events": visible_events,
        "events_count": len(visible_events),
    }
