"""Slots disponíveis para página pública e remarcação no painel."""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

from services.scheduling import repository as scheduling_repository
from services.scheduling.slot_engine import slot_starts_in_range, _get_tz


def eligible_professionals(
    services: list[dict],
    professionals: list[dict],
    service_id: str,
) -> list[dict]:
    svc = next((x for x in services if str(x.get("id")) == str(service_id)), None)
    if not svc:
        return []
    pid = svc.get("professional_id")
    if pid:
        return [p for p in professionals if str(p.get("id")) == str(pid)]
    return list(professionals)


def compute_available_slot_isos(
    *,
    cliente_id: str,
    service_id: str,
    professional_id: str,
    tz_name: str,
    working_rows: list[dict],
    duration_minutes: int,
    num_days: int = 14,
    max_slots: int = 120,
    start_day: date | None = None,
    exclude_appointment_id: str | None = None,
) -> list[str]:
    if not (cliente_id and service_id and professional_id):
        return []
    tz = _get_tz(tz_name)
    today = datetime.now(timezone.utc).astimezone(tz).date()
    range_start = start_day or today
    if range_start < today:
        range_start = today
    from_utc = datetime.combine(range_start, datetime.min.time(), tzinfo=tz).astimezone(timezone.utc)
    to_utc = from_utc + timedelta(days=max(num_days, 1) + 7)
    busy = scheduling_repository.busy_intervals_utc(
        cliente_id,
        professional_id,
        from_utc,
        to_utc,
        exclude_appointment_id=exclude_appointment_id,
    )
    slot_dts = slot_starts_in_range(
        tz_name=tz_name,
        start_day=range_start,
        num_days=num_days,
        duration_minutes=max(5, int(duration_minutes or 30)),
        professional_id=professional_id,
        working_rows=working_rows,
        busy_intervals_utc=busy,
    )
    return [s.astimezone(timezone.utc).isoformat() for s in slot_dts[:max_slots]]
