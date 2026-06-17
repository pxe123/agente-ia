"""Motor interno ZapAction (Supabase)."""
from __future__ import annotations

from datetime import datetime
from typing import Any

from services.scheduling import repository
from services.scheduling.bookings import book_appointment
from services.scheduling.motor_adapters.base import (
    BatchCancelResult,
    BookOccurrenceRequest,
    BookOccurrenceResult,
    check_slot_free_local,
    revalidate_overlap_after_insert,
)


class InternalMotorAdapter:
    def check_slot_free(
        self,
        *,
        cliente_id: str,
        professional_id: str | None,
        starts_at: datetime,
        ends_at: datetime,
    ) -> bool:
        return check_slot_free_local(
            cliente_id=cliente_id,
            professional_id=professional_id,
            starts_at=starts_at,
            ends_at=ends_at,
        )

    def book_occurrence(self, request: BookOccurrenceRequest) -> BookOccurrenceResult:
        duration = max(1, int((request.ends_at - request.starts_at).total_seconds() // 60))
        meta = dict(request.meta or {})
        if request.recurrence_series_id:
            meta.setdefault("source", "panel_recurrence")
        elif not meta.get("source"):
            meta["source"] = "panel"

        if request.recurrence_series_id and request.series_occurrence_at:
            if not self.check_slot_free(
                cliente_id=request.cliente_id,
                professional_id=request.professional_id,
                starts_at=request.starts_at,
                ends_at=request.ends_at,
            ):
                return BookOccurrenceResult(row=None, error="slot_ocupado")

            row = repository.insert_appointment(
                cliente_id=request.cliente_id,
                service_id=request.service_id,
                professional_id=request.professional_id,
                starts_at=request.starts_at,
                ends_at=request.ends_at,
                remote_id=request.remote_id,
                status=request.status,
                contact_phone=request.contact_phone,
                notes=request.notes,
                meta=meta,
                recurrence_series_id=request.recurrence_series_id,
                series_occurrence_at=request.series_occurrence_at,
                is_series_exception=request.is_series_exception,
            )
            if not row:
                return BookOccurrenceResult(row=None, error="insert_falhou")
            row_id = str(row.get("id") or "")
            if row_id and request.professional_id:
                if not revalidate_overlap_after_insert(
                    cliente_id=request.cliente_id,
                    professional_id=request.professional_id,
                    starts_at=request.starts_at,
                    ends_at=request.ends_at,
                    row_id=row_id,
                ):
                    repository.delete_appointment_row(request.cliente_id, row_id)
                    return BookOccurrenceResult(row=None, error="slot_ocupado")
            return BookOccurrenceResult(row=row, motor_sync="local_only")

        row, err = book_appointment(
            cliente_id=request.cliente_id,
            service_id=request.service_id,
            professional_id=request.professional_id,
            starts_at=request.starts_at,
            duration_minutes=duration,
            remote_id=request.remote_id,
            contact_phone=request.contact_phone,
            notes=request.notes,
            status=request.status,
            meta=meta,
        )
        if row:
            return BookOccurrenceResult(row=row, motor_sync="local_only")
        return BookOccurrenceResult(row=None, error=err or "erro")

    def cancel_appointment(
        self,
        *,
        cliente_id: str,
        local_row: dict[str, Any],
    ) -> tuple[bool, str | None]:
        aid = str(local_row.get("id") or "")
        if not aid:
            return False, "appointment_id_em_falta"
        ok = repository.update_appointment_status(cliente_id, aid, "cancelled")
        return ok, None if ok else "cancel_falhou"

    def cancel_series_remote(
        self,
        *,
        cliente_id: str,
        series_id: str,
        scope: str,
        from_starts_at: datetime | None = None,
        appointment_rows: list[dict[str, Any]] | None = None,
    ) -> BatchCancelResult:
        return BatchCancelResult(cancelled_local=0, cancelled_remote=0)
