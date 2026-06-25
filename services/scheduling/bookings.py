"""Reservas, cancelamento e remarcação (usa repository)."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Tuple

from services.scheduling import repository
from services.scheduling.swap import SwapOffer, detect_swap_offer


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
    status: str | None = None,
) -> Tuple[dict[str, Any] | None, str | None]:
    from services.scheduling.confirmation_policy import (
        build_booking_meta_patch,
        resolve_initial_appointment_status,
    )

    initial_status = status or resolve_initial_appointment_status(cliente_id)
    meta_patch = build_booking_meta_patch(cliente_id)
    if meta_patch:
        merged = dict(meta or {})
        merged.update(meta_patch)
        meta = merged

    existing = repository.find_existing_booking_for_contact(
        cliente_id,
        service_id,
        starts_at,
        contact_phone=contact_phone,
        remote_id=remote_id,
    )
    if existing:
        return existing, None

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
        status=initial_status,
        contact_phone=contact_phone,
        notes=notes,
        meta=meta,
    )
    if not row:
        return None, "insert_falhou"
    # Revalidação pós-insert: só outras marcações (não bloqueios) no mesmo profissional
    row_id = str(row.get("id") or "")
    if row_id and professional_id:
        others = repository.find_overlapping_appointments(
            cliente_id,
            str(professional_id),
            starts_at,
            ends_at,
            exclude_appointment_id=row_id,
        )
        if others:
            repository.delete_appointment_row(cliente_id, row_id)
            return None, "slot_ocupado"
    if initial_status == "pending":
        try:
            from services.scheduling.confirmation_notify import (
                notify_client_booking_received,
                notify_pending_booking,
            )

            notify_pending_booking(cliente_id, row)
            if row_id:
                notify_client_booking_received(cliente_id, row_id)
        except Exception:
            pass
    elif initial_status == "confirmed" and row_id:
        try:
            from services.scheduling.client_calendar_invite import on_appointment_confirmed

            on_appointment_confirmed(cliente_id, row_id, kind="confirmed")
        except Exception:
            pass
    return row, None


def cancel_appointment(
    cliente_id: str,
    appointment_id: str,
    *,
    notify_client: bool = False,
) -> bool:
    row = repository.get_appointment(cliente_id, appointment_id)
    if not row:
        return False
    previous_status = str(row.get("status") or "").lower()
    if previous_status == "cancelled":
        return True
    ok = repository.update_appointment_status(cliente_id, appointment_id, "cancelled")
    if ok and notify_client and previous_status in ("pending", "confirmed"):
        try:
            from services.scheduling.confirmation_notify import notify_client_cancelled

            notify_client_cancelled(cliente_id, appointment_id)
        except Exception:
            pass
    return ok


def check_reschedule_slot(
    *,
    cliente_id: str,
    appointment_id: str,
    new_starts_at: datetime,
    duration_minutes: int,
    professional_id: str | None,
) -> Tuple[bool, str | None, SwapOffer | None]:
    """Valida conflitos para remarcação sem alterar a base."""
    row = repository.get_appointment(cliente_id, appointment_id)
    if not row:
        return False, "nao_encontrado", None
    ends_at = new_starts_at + timedelta(minutes=max(1, int(duration_minutes or 30)))
    pad = timedelta(days=1)
    from_utc = new_starts_at.astimezone(timezone.utc) - pad
    to_utc = ends_at.astimezone(timezone.utc) + pad
    busy = repository.busy_intervals_utc(
        cliente_id, professional_id, from_utc, to_utc, exclude_appointment_id=str(appointment_id)
    )
    has_conflict = any(
        _overlap(new_starts_at, ends_at, b0, b1) for b0, b1 in busy if b0 and b1
    )
    if has_conflict:
        offer = None
        if professional_id:
            offer = detect_swap_offer(
                cliente_id,
                row,
                str(professional_id),
                starts_at=new_starts_at,
                ends_at=ends_at,
            )
        if offer:
            return False, "swap_available", offer
        return False, "slot_ocupado", None
    return True, None, None


def reschedule_appointment(
    *,
    cliente_id: str,
    appointment_id: str,
    new_starts_at: datetime,
    duration_minutes: int,
    professional_id: str | None,
) -> Tuple[bool, str | None, SwapOffer | None]:
    """Atualiza horário após validar conflitos (ignora o próprio registo)."""
    from database.supabase_sq import supabase
    from database.models import Tables, SchedulingAppointmentModel

    if not supabase:
        return False, "sem_db", None
    ok, err, offer = check_reschedule_slot(
        cliente_id=cliente_id,
        appointment_id=appointment_id,
        new_starts_at=new_starts_at,
        duration_minutes=duration_minutes,
        professional_id=professional_id,
    )
    if not ok:
        return False, err, offer
    ends_at = new_starts_at + timedelta(minutes=max(1, int(duration_minutes or 30)))
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
    try:
        from services.scheduling.client_calendar_invite import on_appointment_confirmed

        row = repository.get_appointment(cliente_id, appointment_id)
        if row and str(row.get("status") or "").lower() == "confirmed":
            on_appointment_confirmed(cliente_id, appointment_id, kind="rescheduled")
    except Exception:
        pass
    return True, None, None


def book_with_auto_assignment(
    *,
    cliente_id: str,
    service_id: str,
    starts_at: datetime,
    duration_minutes: int,
    candidate_professional_ids: list[str],
    remote_id: str | None,
    contact_phone: str | None = None,
    notes: str | None = None,
    meta: dict | None = None,
) -> Tuple[dict[str, Any] | None, str | None]:
    """Tenta reservar com candidatos em ordem (round-robin) até sucesso ou esgotar."""
    from services.scheduling.assignment import order_candidates_for_assignment, record_auto_assignment

    ordered = order_candidates_for_assignment(cliente_id, candidate_professional_ids)
    if not ordered:
        return None, "sem_profissional"
    last_err: str | None = "slot_ocupado"
    for pid in ordered:
        row, err = book_appointment(
            cliente_id=cliente_id,
            service_id=service_id,
            professional_id=pid,
            starts_at=starts_at,
            duration_minutes=duration_minutes,
            remote_id=remote_id,
            contact_phone=contact_phone,
            notes=notes,
            meta=meta,
        )
        if row and not err:
            record_auto_assignment(cliente_id, pid)
            return row, None
        last_err = err or "slot_ocupado"
    return None, last_err


def reassign_appointment_professional(
    *,
    cliente_id: str,
    appointment_id: str,
    new_professional_id: str,
    changed_by: str = "panel",
) -> Tuple[bool, str | None, SwapOffer | None]:
    """Altera profissional se não houver conflito de agenda."""
    from services.scheduling.display import parse_iso_datetime

    row = repository.get_appointment(cliente_id, appointment_id)
    if not row:
        return False, "nao_encontrado", None
    if str(row.get("status") or "").lower() == "cancelled":
        return False, "cancelado", None
    starts = parse_iso_datetime(row.get("starts_at"))
    ends = parse_iso_datetime(row.get("ends_at"))
    if not starts or not ends:
        return False, "horario_invalido", None
    pad = timedelta(days=1)
    from_utc = starts.astimezone(timezone.utc) - pad
    to_utc = ends.astimezone(timezone.utc) + pad
    busy = repository.busy_intervals_utc(
        cliente_id,
        new_professional_id,
        from_utc,
        to_utc,
        exclude_appointment_id=str(appointment_id),
    )
    has_conflict = any(_overlap(starts, ends, b0, b1) for b0, b1 in busy if b0 and b1)
    if has_conflict:
        offer = detect_swap_offer(cliente_id, row, new_professional_id)
        if offer:
            return False, "swap_available", offer
        return False, "slot_ocupado", None
    meta_patch = {
        "reassigned_by": changed_by,
        "reassigned_at": datetime.now(timezone.utc).isoformat(),
        "assignment_mode": "manual",
        "assigned_by": "panel_user",
    }
    ok = repository.update_appointment_professional(
        cliente_id,
        appointment_id,
        new_professional_id,
        meta_patch=meta_patch,
    )
    return ((True, None, None) if ok else (False, "update_falhou", None))
