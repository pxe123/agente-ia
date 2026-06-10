"""Reservas, cancelamento e remarcação (usa repository)."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Tuple

from services.scheduling import repository


def _overlap(a0: datetime, a1: datetime, b0: datetime, b1: datetime) -> bool:
    return a0 < b1 and a1 > b0


def book_appointment(
    *,
    cliente_id: str,
    service_id: str,
    professional_id: str | None,
    starts_at: datetime,
    duration_minutes: int,
    remote_id: str | None,
    contact_phone: str | None = None,
    notes: str | None = None,
    meta: dict | None = None,
) -> Tuple[dict[str, Any] | None, str | None]:
    ends_at = starts_at + timedelta(minutes=max(1, int(duration_minutes or 30)))
    pad = timedelta(days=1)
    from_utc = starts_at.astimezone(timezone.utc) - pad
    to_utc = ends_at.astimezone(timezone.utc) + pad
    busy = repository.busy_intervals_utc(cliente_id, professional_id, from_utc, to_utc)
    for b0, b1 in busy:
        if _overlap(starts_at, ends_at, b0, b1):
            return None, "slot_ocupado"
    row = repository.insert_appointment(
        cliente_id=cliente_id,
        service_id=service_id,
        professional_id=professional_id,
        starts_at=starts_at,
        ends_at=ends_at,
        remote_id=remote_id,
        status="confirmed",
        contact_phone=contact_phone,
        notes=notes,
        meta=meta,
    )
    if not row:
        return None, "insert_falhou"
    # Revalidação pós-insert (mitiga race em slot popular)
    row_id = str(row.get("id") or "")
    if row_id:
        busy_after = repository.busy_intervals_utc(cliente_id, professional_id, from_utc, to_utc)
        conflicts = 0
        for b0, b1 in busy_after:
            if _overlap(starts_at, ends_at, b0, b1):
                conflicts += 1
        if conflicts > 1:
            repository.delete_appointment_row(cliente_id, row_id)
            return None, "slot_ocupado"
    return row, None


def cancel_appointment(cliente_id: str, appointment_id: str) -> bool:
    return repository.update_appointment_status(cliente_id, appointment_id, "cancelled")


def reschedule_appointment(
    *,
    cliente_id: str,
    appointment_id: str,
    new_starts_at: datetime,
    duration_minutes: int,
    professional_id: str | None,
) -> Tuple[bool, str | None]:
    """Atualiza horário após validar conflitos (ignora o próprio registo)."""
    from database.supabase_sq import supabase
    from database.models import Tables, SchedulingAppointmentModel

    if not supabase:
        return False, "sem_db"
    ends_at = new_starts_at + timedelta(minutes=max(1, int(duration_minutes or 30)))
    pad = timedelta(days=1)
    from_utc = new_starts_at.astimezone(timezone.utc) - pad
    to_utc = ends_at.astimezone(timezone.utc) + pad
    busy = repository.busy_intervals_utc(
        cliente_id, professional_id, from_utc, to_utc, exclude_appointment_id=str(appointment_id)
    )
    for b0, b1 in busy:
        if _overlap(new_starts_at, ends_at, b0, b1):
            return False, "slot_ocupado"
    supabase.table(Tables.SCHEDULING_APPOINTMENTS).update(
        {
            SchedulingAppointmentModel.STARTS_AT: new_starts_at.astimezone(timezone.utc).isoformat(),
            SchedulingAppointmentModel.ENDS_AT: ends_at.astimezone(timezone.utc).isoformat(),
            SchedulingAppointmentModel.PROFESSIONAL_ID: professional_id,
            SchedulingAppointmentModel.UPDATED_AT: datetime.now(timezone.utc).isoformat(),
        }
    ).eq(SchedulingAppointmentModel.ID, str(appointment_id)).eq(
        SchedulingAppointmentModel.CLIENTE_ID, str(cliente_id)
    ).execute()
    return True, None
