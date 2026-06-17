"""Motor externo Agendamento IA."""
from __future__ import annotations

from datetime import datetime
from typing import Any

from database.models import SchedulingAppointmentModel
from services.agendamento_ia_book import (
    cancel_appointments_batch_in_agendamento_ia,
    create_appointment_in_agendamento_ia,
    recurrence_external_sync_enabled,
)
from services.agendamento_ia_cancel import cancel_appointment_in_agendamento_ia
from services.scheduling import repository
from services.scheduling.motor_adapters.base import (
    BatchCancelResult,
    BookOccurrenceRequest,
    BookOccurrenceResult,
    check_slot_free_local,
    revalidate_overlap_after_insert,
)


class AgendaIAMotorAdapter:
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
        if not self.check_slot_free(
            cliente_id=request.cliente_id,
            professional_id=request.professional_id,
            starts_at=request.starts_at,
            ends_at=request.ends_at,
        ):
            return BookOccurrenceResult(row=None, error="slot_ocupado")

        zaid = request.resolved_appointment_id()
        meta = dict(request.meta or {})
        if request.recurrence_series_id:
            meta.setdefault("source", "panel_recurrence")
        else:
            meta.setdefault("source", "panel")
        meta["zapaction_appointment_id"] = zaid

        contact_name = (request.contact_name or "").strip()
        if contact_name:
            meta.setdefault("contact_name", contact_name)

        sync_state = "pending"
        external_id: str | None = None
        sync_err: str | None = None

        if recurrence_external_sync_enabled():
            external_id, sync_err = create_appointment_in_agendamento_ia(
                cliente_id=request.cliente_id,
                zapaction_appointment_id=zaid,
                service_id=request.service_id,
                provider_id=request.professional_id,
                starts_at=request.starts_at,
                ends_at=request.ends_at,
                contact_name=contact_name or "Cliente",
                contact_phone=request.contact_phone,
                notes=request.notes,
                status=request.status,
                metadata=meta,
                recurrence_series_id=request.recurrence_series_id,
                series_occurrence_at=request.series_occurrence_at,
                is_series_exception=request.is_series_exception,
            )
            if external_id:
                sync_state = "synced"
            elif sync_err == "slot_ocupado":
                return BookOccurrenceResult(row=None, error="slot_ocupado")
            else:
                sync_state = "pending" if sync_err in ("timeout", "sync_externo_desativado") else "failed"
                meta["motor_sync"] = sync_state
                if sync_err:
                    meta["motor_sync_error"] = sync_err
        else:
            sync_state = "local_only"
            meta["motor_sync"] = "local_only"

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
                if external_id:
                    cancel_appointment_in_agendamento_ia(
                        cliente_id=request.cliente_id,
                        external_appointment_id=external_id,
                    )
                return BookOccurrenceResult(row=None, error="slot_ocupado")

        if external_id and row_id:
            repository.set_appointment_external_id(
                request.cliente_id,
                row_id,
                external_id,
                meta_patch={**meta, "motor_sync": "synced"},
            )
            row = repository.get_appointment(request.cliente_id, row_id) or row
            sync_state = "synced"
        elif sync_state in ("pending", "failed"):
            repository.merge_appointment_meta(
                request.cliente_id,
                row_id,
                {"motor_sync": sync_state, "motor_sync_error": sync_err or ""},
            )

        return BookOccurrenceResult(row=row, motor_sync=sync_state, error=sync_err if sync_state != "synced" else None)

    def cancel_appointment(
        self,
        *,
        cliente_id: str,
        local_row: dict[str, Any],
    ) -> tuple[bool, str | None]:
        aid = str(local_row.get("id") or "")
        if not aid:
            return False, "appointment_id_em_falta"
        ext = (
            local_row.get(SchedulingAppointmentModel.EXTERNAL_AGENDA_APPOINTMENT_ID)
            or local_row.get("external_agenda_appointment_id")
        )
        if ext:
            ok, err = cancel_appointment_in_agendamento_ia(
                cliente_id=cliente_id,
                external_appointment_id=str(ext),
                remote_id=local_row.get("remote_id"),
            )
            if not ok:
                return False, err
        return repository.update_appointment_status(cliente_id, aid, "cancelled"), None

    def cancel_series_remote(
        self,
        *,
        cliente_id: str,
        series_id: str,
        scope: str,
        from_starts_at: datetime | None = None,
        appointment_rows: list[dict[str, Any]] | None = None,
    ) -> BatchCancelResult:
        if not recurrence_external_sync_enabled():
            return BatchCancelResult()
        sc = (scope or "").strip().lower()
        if sc == "ids":
            ext_ids = []
            for row in appointment_rows or []:
                ext = row.get(SchedulingAppointmentModel.EXTERNAL_AGENDA_APPOINTMENT_ID) or row.get(
                    "external_agenda_appointment_id"
                )
                if ext:
                    ext_ids.append(str(ext))
            if not ext_ids:
                return BatchCancelResult()
            n, err = cancel_appointments_batch_in_agendamento_ia(
                cliente_id=cliente_id,
                scope="ids",
                series_id=series_id,
                appointment_ids=ext_ids,
            )
            return BatchCancelResult(cancelled_remote=n, error=err)

        n, err = cancel_appointments_batch_in_agendamento_ia(
            cliente_id=cliente_id,
            scope=sc if sc in ("following", "all") else "following",
            series_id=series_id,
            from_starts_at=from_starts_at,
        )
        return BatchCancelResult(cancelled_remote=n, error=err)
