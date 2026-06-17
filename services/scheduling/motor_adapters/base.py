"""Contrato de adaptador motor-agnóstico para booking no painel."""
from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Protocol

from services.scheduling import repository


@dataclass
class BookOccurrenceRequest:
    cliente_id: str
    service_id: str
    professional_id: str | None
    starts_at: datetime
    ends_at: datetime
    contact_name: str
    contact_phone: str | None = None
    notes: str | None = None
    status: str = "confirmed"
    meta: dict[str, Any] | None = None
    remote_id: str | None = None
    recurrence_series_id: str | None = None
    series_occurrence_at: datetime | None = None
    is_series_exception: bool = False
    zapaction_appointment_id: str | None = None

    def resolved_appointment_id(self) -> str:
        return (self.zapaction_appointment_id or "").strip() or str(uuid.uuid4())


@dataclass
class BookOccurrenceResult:
    row: dict[str, Any] | None
    error: str | None = None
    motor_sync: str = "synced"  # synced | pending | failed | local_only


@dataclass
class BatchCancelResult:
    cancelled_local: int = 0
    cancelled_remote: int = 0
    error: str | None = None


class MotorAdapter(Protocol):
    def check_slot_free(
        self,
        *,
        cliente_id: str,
        professional_id: str | None,
        starts_at: datetime,
        ends_at: datetime,
    ) -> bool: ...

    def book_occurrence(self, request: BookOccurrenceRequest) -> BookOccurrenceResult: ...

    def cancel_appointment(
        self,
        *,
        cliente_id: str,
        local_row: dict[str, Any],
    ) -> tuple[bool, str | None]: ...

    def cancel_series_remote(
        self,
        *,
        cliente_id: str,
        series_id: str,
        scope: str,
        from_starts_at: datetime | None = None,
        appointment_rows: list[dict[str, Any]] | None = None,
    ) -> BatchCancelResult: ...


def _overlap(a0: datetime, a1: datetime, b0: datetime, b1: datetime) -> bool:
    return a0 < b1 and a1 > b0


def check_slot_free_local(
    *,
    cliente_id: str,
    professional_id: str | None,
    starts_at: datetime,
    ends_at: datetime,
) -> bool:
    from datetime import timedelta, timezone

    pad = timedelta(days=1)
    busy = repository.busy_intervals_utc(
        cliente_id, professional_id, starts_at - pad, ends_at + pad
    )
    for b0, b1 in busy:
        if _overlap(starts_at, ends_at, b0, b1):
            return False
    return True


def revalidate_overlap_after_insert(
    *,
    cliente_id: str,
    professional_id: str | None,
    starts_at: datetime,
    ends_at: datetime,
    row_id: str,
) -> bool:
    """True se ainda livre (sem outras marcações sobrepostas)."""
    if not professional_id:
        return True
    others = repository.find_overlapping_appointments(
        cliente_id, str(professional_id), starts_at, ends_at, exclude_appointment_id=row_id
    )
    return not others
