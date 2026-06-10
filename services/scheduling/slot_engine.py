"""
Motor puro de slots (testável sem Supabase).
"""
from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone
from typing import Any, Iterable
from zoneinfo import ZoneInfo

from services.scheduling.timezones import fixed_offset_tz_fallback


def _get_tz(name: str):
    """ZoneInfo com fallback de offset fixo para fusos da lista da agenda."""
    n = (name or "UTC").strip() or "UTC"
    if n.upper() == "UTC":
        return timezone.utc
    try:
        return ZoneInfo(n)
    except Exception:
        fb = fixed_offset_tz_fallback(n)
        return fb if fb is not None else timezone.utc


def _parse_time_hms(v: Any) -> time:
    if isinstance(v, time):
        return v
    s = str(v or "").strip()
    if not s:
        return time(0, 0)
    parts = s.replace("T", " ").split()
    if len(parts) >= 2 and ":" in parts[-1]:
        s = parts[-1]
    seg = s.split(":")
    h = int(seg[0]) if seg else 0
    m = int(seg[1]) if len(seg) > 1 else 0
    sec = int(seg[2]) if len(seg) > 2 else 0
    return time(h, m, sec)


def _intervals_overlap(a0: datetime, a1: datetime, b0: datetime, b1: datetime) -> bool:
    return a0 < b1 and a1 > b0


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def effective_working_rows_for_professional(
    rows: list[dict[str, Any]], professional_id: str
) -> list[dict[str, Any]]:
    """Por dia da semana: horários do profissional; se não houver, usa linhas com professional_id nulo."""
    by_day: dict[int, list[dict[str, Any]]] = {}
    for row in rows or []:
        try:
            dow = int(row.get("day_of_week"))
        except (TypeError, ValueError):
            continue
        pid = row.get("professional_id")
        by_day.setdefault(dow, []).append({**row, "_pid": pid})

    out: list[dict[str, Any]] = []
    for dow, lst in by_day.items():
        spec = [x for x in lst if x.get("_pid") not in (None, "") and str(x["_pid"]) == str(professional_id)]
        use = spec if spec else [x for x in lst if x.get("_pid") in (None, "")]
        for x in use:
            cp = {k: v for k, v in x.items() if not str(k).startswith("_")}
            out.append(cp)
    return out


def slot_starts_in_range(
    *,
    tz_name: str,
    start_day: date,
    num_days: int,
    duration_minutes: int,
    professional_id: str,
    working_rows: list[dict[str, Any]],
    busy_intervals_utc: Iterable[tuple[datetime, datetime]],
) -> list[datetime]:
    """
    Gera inícios de slot em UTC, respeitando horários de trabalho no fuso `tz_name` e intervalos ocupados em UTC.
    """
    tz = _get_tz(tz_name)

    duration = timedelta(minutes=max(1, int(duration_minutes or 30)))
    rows_eff = effective_working_rows_for_professional(working_rows, professional_id)
    busy = [(a, b) for a, b in busy_intervals_utc if a and b and a < b]

    slots: list[datetime] = []
    for n in range(max(1, int(num_days or 7))):
        d = start_day + timedelta(days=n)
        weekday = d.weekday()
        day_rows = [r for r in rows_eff if int(r.get("day_of_week", -1)) == weekday]
        for r in day_rows:
            st = _parse_time_hms(r.get("start_time"))
            et = _parse_time_hms(r.get("end_time"))
            cur_local = datetime.combine(d, st, tzinfo=tz)
            end_local = datetime.combine(d, et, tzinfo=tz)
            while cur_local + duration <= end_local:
                slot_start_utc = cur_local.astimezone(timezone.utc)
                slot_end_utc = (cur_local + duration).astimezone(timezone.utc)
                conflict = any(
                    _intervals_overlap(slot_start_utc, slot_end_utc, b0, b1) for b0, b1 in busy
                )
                if not conflict:
                    slots.append(slot_start_utc)
                cur_local += duration
    now_utc = _utc_now()
    slots = [s for s in slots if s > now_utc]
    # limite prático para mensagem WhatsApp
    return slots[:40]
