"""Intervalos de data para a aba Agendamentos (fuso da clínica)."""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

from services.scheduling.slot_engine import _get_tz
from services.scheduling.timezones import normalize_timezone

VALID_PERIODS = frozenset({"today", "tomorrow", "week", "month", "all", "day"})


def _local_today(tz_name: str) -> date:
    tz = _get_tz(normalize_timezone(tz_name))
    return datetime.now(timezone.utc).astimezone(tz).date()


def _day_bounds_utc(d: date, tz_name: str) -> tuple[datetime, datetime]:
    tz = _get_tz(normalize_timezone(tz_name))
    start = datetime.combine(d, datetime.min.time(), tzinfo=tz).astimezone(timezone.utc)
    end = datetime.combine(d + timedelta(days=1), datetime.min.time(), tzinfo=tz).astimezone(timezone.utc)
    return start, end


def resolve_appointments_period(
    *,
    period: str | None,
    anchor_date: date | None,
    tz_name: str,
) -> tuple[datetime, datetime, str, str]:
    """
    Retorna (from_utc, to_utc, period_key, period_label_pt).

    Prioridade:
    1. ``anchor_date`` explícito → dia específico
    2. ``period`` (today, tomorrow, week, month, all)
    3. default → today
    """
    tz = normalize_timezone(tz_name)
    today = _local_today(tz)

    if anchor_date is not None:
        d = anchor_date
        from_utc, to_utc = _day_bounds_utc(d, tz)
        label = d.strftime("%d/%m/%Y")
        if d == today:
            label = f"Hoje ({label})"
        elif d == today + timedelta(days=1):
            label = f"Amanhã ({label})"
        return from_utc, to_utc, "day", label

    key = (period or "today").strip().lower()
    if key not in VALID_PERIODS:
        key = "today"

    if key == "today":
        from_utc, to_utc = _day_bounds_utc(today, tz)
        return from_utc, to_utc, "today", f"Hoje ({today.strftime('%d/%m/%Y')})"

    if key == "tomorrow":
        d = today + timedelta(days=1)
        from_utc, to_utc = _day_bounds_utc(d, tz)
        return from_utc, to_utc, "tomorrow", f"Amanhã ({d.strftime('%d/%m/%Y')})"

    if key == "week":
        start = today - timedelta(days=today.weekday())
        end = start + timedelta(days=6)
        from_utc, _ = _day_bounds_utc(start, tz)
        _, to_utc = _day_bounds_utc(end, tz)
        label = f"Semana {start.strftime('%d/%m')} – {end.strftime('%d/%m/%Y')}"
        return from_utc, to_utc, "week", label

    if key == "month":
        start = today.replace(day=1)
        if start.month == 12:
            next_month = date(start.year + 1, 1, 1)
        else:
            next_month = date(start.year, start.month + 1, 1)
        last = next_month - timedelta(days=1)
        from_utc, _ = _day_bounds_utc(start, tz)
        _, to_utc = _day_bounds_utc(last, tz)
        return from_utc, to_utc, "month", f"Mês {start.strftime('%m/%Y')}"

    # all
    now = datetime.now(timezone.utc)
    from_utc = now - timedelta(days=90)
    to_utc = now + timedelta(days=365)
    return from_utc, to_utc, "all", "Todos (últimos 90 dias e futuro)"


def parse_filter_date(raw: str | None, tz_name: str) -> date | None:
    if not raw or not str(raw).strip():
        return None
    try:
        return date.fromisoformat(str(raw).strip()[:10])
    except ValueError:
        return None


def view_date_for_period(
    *,
    period: str,
    anchor_date: date | None,
    tz_name: str,
) -> date:
    """Data de referência para navegação ◀ Hoje ▶ (fuso da clínica)."""
    if anchor_date is not None:
        return anchor_date
    today = _local_today(tz_name)
    key = (period or "today").strip().lower()
    if key == "tomorrow":
        return today + timedelta(days=1)
    return today


def shift_view_date(d: date, delta_days: int) -> date:
    return d + timedelta(days=int(delta_days))
