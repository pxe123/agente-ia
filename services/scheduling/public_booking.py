"""Calendário e agrupamento de slots para a página pública /agenda/<slug>."""
from __future__ import annotations

from calendar import monthrange
from datetime import date, datetime, timedelta, timezone
from typing import Any

from services.scheduling.display import parse_iso_datetime
from services.scheduling.slot_engine import _get_tz
from services.scheduling.timezones import normalize_timezone

_MONTH_PT = (
    "",
    "Janeiro",
    "Fevereiro",
    "Março",
    "Abril",
    "Maio",
    "Junho",
    "Julho",
    "Agosto",
    "Setembro",
    "Outubro",
    "Novembro",
    "Dezembro",
)
_WEEKDAY_PT = (
    "segunda-feira",
    "terça-feira",
    "quarta-feira",
    "quinta-feira",
    "sexta-feira",
    "sábado",
    "domingo",
)
_WEEKDAY_SHORT_PT = ("seg", "ter", "qua", "qui", "sex", "sáb", "dom")


def format_selected_date_long(d: date) -> str:
    return f"{_WEEKDAY_PT[d.weekday()]}, {d.day} de {_MONTH_PT[d.month].lower()}"


def build_month_grid_full(anchor: date) -> list[list[date]]:
    """Grelha 6×7 estilo Google Calendar (inclui dias do mês anterior/seguinte)."""
    first = anchor.replace(day=1)
    start = first - timedelta(days=first.weekday())
    grid: list[list[date]] = []
    cur = start
    for _ in range(6):
        grid.append([cur + timedelta(days=i) for i in range(7)])
        cur += timedelta(days=7)
    return grid


def local_today(tz_name: str) -> date:
    tz = _get_tz(normalize_timezone(tz_name))
    return datetime.now(timezone.utc).astimezone(tz).date()


def parse_month_anchor(raw: str | None, tz_name: str) -> date:
    if raw:
        try:
            y, m = str(raw).strip()[:7].split("-")[:2]
            return date(int(y), int(m), 1)
        except (TypeError, ValueError):
            pass
    return local_today(tz_name).replace(day=1)


def parse_selected_date(raw: str | None) -> date | None:
    if not raw or not str(raw).strip():
        return None
    try:
        return date.fromisoformat(str(raw).strip()[:10])
    except ValueError:
        return None


def month_bounds(month_anchor: date) -> tuple[date, date]:
    last_day = monthrange(month_anchor.year, month_anchor.month)[1]
    return month_anchor.replace(day=1), month_anchor.replace(day=last_day)


def group_slot_isos_by_local_day(slots_iso: list[str], tz_name: str) -> dict[str, list[str]]:
    tz = _get_tz(normalize_timezone(tz_name))
    out: dict[str, list[str]] = {}
    for iso in slots_iso or []:
        dt = parse_iso_datetime(iso)
        if not dt:
            continue
        key = dt.astimezone(tz).date().isoformat()
        out.setdefault(key, []).append(iso)
    for key in out:
        out[key].sort()
    return out


def day_time_slots(slots_iso: list[str], tz_name: str) -> list[dict[str, str]]:
    tz = _get_tz(normalize_timezone(tz_name))
    rows: list[dict[str, str]] = []
    for iso in slots_iso or []:
        dt = parse_iso_datetime(iso)
        if not dt:
            continue
        rows.append({"iso": iso, "time": dt.astimezone(tz).strftime("%H:%M")})
    return rows


def build_public_booking_calendar(
    *,
    month_anchor: date,
    slots_by_day: dict[str, list[str]],
    tz_name: str,
    selected_date: date | None,
) -> dict[str, Any]:
    today = local_today(tz_name)
    weeks: list[list[dict[str, Any]]] = []
    for week in build_month_grid_full(month_anchor):
        row: list[dict[str, Any]] = []
        for d in week:
            iso = d.isoformat()
            slot_count = len(slots_by_day.get(iso, []))
            in_month = d.month == month_anchor.month
            row.append(
                {
                    "date": iso,
                    "day": d.day,
                    "has_slots": slot_count > 0,
                    "slot_count": slot_count,
                    "in_month": in_month,
                    "is_past": d < today,
                    "is_selected": bool(selected_date and d == selected_date),
                    "is_today": d == today,
                    "clickable": in_month and d >= today and slot_count > 0,
                }
            )
        weeks.append(row)

    prev_m = (month_anchor.replace(day=1) - timedelta(days=1)).strftime("%Y-%m")
    if month_anchor.month == 12:
        next_m = date(month_anchor.year + 1, 1, 1).strftime("%Y-%m")
    else:
        next_m = date(month_anchor.year, month_anchor.month + 1, 1).strftime("%Y-%m")

    return {
        "weeks": weeks,
        "month_label": f"{_MONTH_PT[month_anchor.month]} {month_anchor.year}",
        "month_key": month_anchor.strftime("%Y-%m"),
        "prev_month": prev_m,
        "next_month": next_m,
        "today_month": today.strftime("%Y-%m"),
        "today_date": today.isoformat(),
        "weekday_short": _WEEKDAY_SHORT_PT,
    }
