"""Slots agregados (pool) para distribuição automática de profissionais."""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from typing import Any

from services.scheduling import repository as scheduling_repository
from services.scheduling.display import parse_iso_datetime
from services.scheduling.eligible import eligible_professionals
from services.scheduling.slot_engine import slot_starts_in_range, _get_tz


def compute_pooled_slot_entries(
    *,
    cliente_id: str,
    service_id: str,
    tz_name: str,
    working_rows: list[dict],
    professionals: list[dict],
    services: list[dict],
    duration_minutes: int,
    start_day: date,
    num_days: int,
    max_slots: int = 200,
) -> list[dict[str, Any]]:
    """
    Lista de slots com profissional: [{starts_at_utc: datetime, professional_id: str, iso: str}, ...]
    """
    profs = eligible_professionals(services, professionals, service_id)
    if not profs:
        return []
    tz = _get_tz(tz_name)
    from_utc = datetime.combine(start_day, datetime.min.time(), tzinfo=tz).astimezone(timezone.utc)
    to_utc = from_utc + timedelta(days=max(num_days, 1) + 7)
    entries: list[dict[str, Any]] = []
    for prof in profs:
        pid = str(prof.get("id") or "")
        if not pid:
            continue
        busy = scheduling_repository.busy_intervals_utc(cliente_id, pid, from_utc, to_utc)
        slot_dts = slot_starts_in_range(
            tz_name=tz_name,
            start_day=start_day,
            num_days=num_days,
            duration_minutes=max(5, int(duration_minutes or 30)),
            professional_id=pid,
            working_rows=working_rows,
            busy_intervals_utc=busy,
        )
        for s in slot_dts:
            entries.append(
                {
                    "starts_at_utc": s,
                    "professional_id": pid,
                    "iso": s.astimezone(timezone.utc).isoformat(),
                }
            )
    entries.sort(key=lambda e: (e["starts_at_utc"], e["professional_id"]))
    return entries[:max_slots]


def merge_slots_for_display(
    entries: list[dict[str, Any]],
    tz_name: str,
) -> tuple[list[str], dict[str, list[str]]]:
    """
    Retorna (slots_iso únicos para UI, mapa iso -> [professional_id, ...]).
    """
    tz = _get_tz(tz_name)
    by_iso: dict[str, list[str]] = {}
    order: list[str] = []
    for e in entries or []:
        iso = str(e.get("iso") or "")
        pid = str(e.get("professional_id") or "")
        if not iso or not pid:
            continue
        if iso not in by_iso:
            by_iso[iso] = []
            order.append(iso)
        if pid not in by_iso[iso]:
            by_iso[iso].append(pid)
    return order, by_iso


def compute_pooled_slot_isos(
    *,
    cliente_id: str,
    service_id: str,
    tz_name: str,
    working_rows: list[dict],
    professionals: list[dict],
    services: list[dict],
    duration_minutes: int,
    start_day: date,
    num_days: int,
    max_slots: int = 200,
) -> tuple[list[str], dict[str, list[str]]]:
    entries = compute_pooled_slot_entries(
        cliente_id=cliente_id,
        service_id=service_id,
        tz_name=tz_name,
        working_rows=working_rows,
        professionals=professionals,
        services=services,
        duration_minutes=duration_minutes,
        start_day=start_day,
        num_days=num_days,
        max_slots=max_slots,
    )
    return merge_slots_for_display(entries, tz_name)


def professional_ids_free_at_slot(
    *,
    cliente_id: str,
    service_id: str,
    starts_at: datetime,
    duration_minutes: int,
    tz_name: str,
    working_rows: list[dict],
    professionals: list[dict],
    services: list[dict],
) -> list[str]:
    """Recalcula candidatos livres no instante (validação server-side no POST)."""
    from services.scheduling.bookings import _overlap

    profs = eligible_professionals(services, professionals, service_id)
    duration = timedelta(minutes=max(5, int(duration_minutes or 30)))
    ends_at = starts_at + duration
    pad = timedelta(days=1)
    from_utc = starts_at.astimezone(timezone.utc) - pad
    to_utc = ends_at.astimezone(timezone.utc) + pad
    tz = _get_tz(tz_name)
    start_day = starts_at.astimezone(tz).date()
    out: list[str] = []
    for prof in profs:
        pid = str(prof.get("id") or "")
        if not pid:
            continue
        busy = scheduling_repository.busy_intervals_utc(cliente_id, pid, from_utc, to_utc)
        conflict = any(_overlap(starts_at, ends_at, b0, b1) for b0, b1 in busy if b0 and b1)
        if conflict:
            continue
        slots = slot_starts_in_range(
            tz_name=tz_name,
            start_day=start_day,
            num_days=1,
            duration_minutes=int(duration_minutes or 30),
            professional_id=pid,
            working_rows=working_rows,
            busy_intervals_utc=busy,
        )
        for s in slots:
            if abs((s - starts_at.astimezone(timezone.utc)).total_seconds()) < 1:
                out.append(pid)
                break
    return out


def candidates_at_instant(
    *,
    slot_iso: str,
    candidates_map: dict[str, list[str]],
) -> list[str]:
    """Profissionais livres no instante (iso normalizado UTC)."""
    key = str(slot_iso or "").strip()
    if not key:
        return []
    if key in candidates_map:
        return list(candidates_map[key])
    dt = parse_iso_datetime(key)
    if not dt:
        return []
    norm = dt.astimezone(timezone.utc).isoformat()
    return list(candidates_map.get(norm, []))
