"""Troca de clientes entre profissionais (swap)."""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

from services.scheduling import repository as scheduling_repository
from services.scheduling.display import enrich_appointments_display, format_datetime_br, parse_iso_datetime


def _overlap(a0: datetime, a1: datetime, b0: datetime, b1: datetime) -> bool:
    return a0 < b1 and a1 > b0

logger = logging.getLogger(__name__)

SWAP_MODE_SAME_SLOT = "same_slot"
SWAP_MODE_CROSS = "cross_validated"


@dataclass
class SwapOffer:
    mode: str
    appointment_b: dict[str, Any]
    target_professional_id: str

    @property
    def appointment_b_id(self) -> str:
        return str(self.appointment_b.get("id") or "")


def _starts_equal(a: datetime, b: datetime) -> bool:
    return abs((a.astimezone(timezone.utc) - b.astimezone(timezone.utc)).total_seconds()) < 1


def _appointment_interval(row: dict[str, Any]) -> tuple[datetime, datetime] | None:
    starts = parse_iso_datetime(row.get("starts_at"))
    ends = parse_iso_datetime(row.get("ends_at"))
    if not starts or not ends:
        return None
    return starts, ends


def _validate_base_pair(row_a: dict[str, Any], row_b: dict[str, Any]) -> str | None:
    if str(row_a.get("status") or "").lower() == "cancelled":
        return "cancelado"
    if str(row_b.get("status") or "").lower() == "cancelled":
        return "cancelado"
    prof_a = str(row_a.get("professional_id") or "").strip()
    prof_b = str(row_b.get("professional_id") or "").strip()
    if not prof_a or not prof_b:
        return "sem_profissional"
    if prof_a == prof_b:
        return "mesmo_profissional"
    if str(row_a.get("id") or "") == str(row_b.get("id") or ""):
        return "mesmo_agendamento"
    return None


def can_professional_assume_appointment(
    cliente_id: str,
    professional_id: str,
    appointment_row: dict[str, Any],
    *,
    exclude_appointment_ids: frozenset[str],
) -> bool:
    """Profissional livre para assumir o horário da marcação (appointments + bloqueios)."""
    interval = _appointment_interval(appointment_row)
    if not interval:
        return False
    starts, ends = interval
    pad = timedelta(days=1)
    from_utc = starts.astimezone(timezone.utc) - pad
    to_utc = ends.astimezone(timezone.utc) + pad
    busy = scheduling_repository.busy_intervals_utc(
        cliente_id,
        professional_id,
        from_utc,
        to_utc,
        exclude_appointment_ids=exclude_appointment_ids,
    )
    return not any(_overlap(starts, ends, b0, b1) for b0, b1 in busy if b0 and b1)


def cross_swap_valid(row_a: dict[str, Any], row_b: dict[str, Any], cliente_id: str) -> bool:
    """Valida troca cruzada: prof_a assume B e prof_b assume A."""
    err = _validate_base_pair(row_a, row_b)
    if err:
        return False
    prof_a = str(row_a.get("professional_id") or "")
    prof_b = str(row_b.get("professional_id") or "")
    exclude = frozenset({str(row_a.get("id") or ""), str(row_b.get("id") or "")})
    return can_professional_assume_appointment(
        cliente_id, prof_a, row_b, exclude_appointment_ids=exclude
    ) and can_professional_assume_appointment(
        cliente_id, prof_b, row_a, exclude_appointment_ids=exclude
    )


def _offer_from_candidate(
    row_a: dict[str, Any],
    row_b: dict[str, Any],
    target_professional_id: str,
    cliente_id: str,
) -> SwapOffer | None:
    err = _validate_base_pair(row_a, row_b)
    if err:
        return None
    interval_a = _appointment_interval(row_a)
    interval_b = _appointment_interval(row_b)
    if not interval_a or not interval_b:
        return None
    if _starts_equal(interval_a[0], interval_b[0]):
        return SwapOffer(
            mode=SWAP_MODE_SAME_SLOT,
            appointment_b=row_b,
            target_professional_id=target_professional_id,
        )
    if cross_swap_valid(row_a, row_b, cliente_id):
        return SwapOffer(
            mode=SWAP_MODE_CROSS,
            appointment_b=row_b,
            target_professional_id=target_professional_id,
        )
    return None


def detect_swap_offer(
    cliente_id: str,
    appointment_a: dict[str, Any],
    target_professional_id: str,
    *,
    starts_at: datetime | None = None,
    ends_at: datetime | None = None,
) -> SwapOffer | None:
    """
    Após conflito ao mover A para target_professional_id:
    localiza marcação B e determina modo de swap.
    """
    if starts_at is not None and ends_at is not None:
        starts, ends = starts_at, ends_at
    else:
        interval = _appointment_interval(appointment_a)
        if not interval:
            return None
        starts, ends = interval
    aid = str(appointment_a.get("id") or "")
    target = str(target_professional_id or "").strip()
    if not target:
        return None
    current_prof = str(appointment_a.get("professional_id") or "")
    if current_prof == target:
        return None

    exact_b = scheduling_repository.find_appointment_at_exact_starts(
        cliente_id, target, starts, exclude_appointment_id=aid or None
    )
    if exact_b:
        offer = _offer_from_candidate(appointment_a, exact_b, target, cliente_id)
        if offer:
            return offer

    overlapping = scheduling_repository.find_overlapping_appointments(
        cliente_id, target, starts, ends, exclude_appointment_id=aid or None
    )
    if len(overlapping) != 1:
        return None
    return _offer_from_candidate(appointment_a, overlapping[0], target, cliente_id)


def swap_appointments_between_professionals(
    cliente_id: str,
    appointment_a_id: str,
    appointment_b_id: str,
    changed_by: str,
    *,
    swap_mode: str = SWAP_MODE_SAME_SLOT,
) -> tuple[bool, str | None]:
    row_a = scheduling_repository.get_appointment(cliente_id, appointment_a_id)
    row_b = scheduling_repository.get_appointment(cliente_id, appointment_b_id)
    if not row_a or not row_b:
        return False, "nao_encontrado"
    err = _validate_base_pair(row_a, row_b)
    if err:
        return False, err
    if swap_mode == SWAP_MODE_CROSS:
        if not cross_swap_valid(row_a, row_b, cliente_id):
            return False, "conflito_cruzado"
    elif swap_mode == SWAP_MODE_SAME_SLOT:
        interval_a = _appointment_interval(row_a)
        interval_b = _appointment_interval(row_b)
        if not interval_a or not interval_b or not _starts_equal(interval_a[0], interval_b[0]):
            if not cross_swap_valid(row_a, row_b, cliente_id):
                return False, "horario_diferente"
            swap_mode = SWAP_MODE_CROSS
    else:
        return False, "modo_invalido"

    prof_a = str(row_a.get("professional_id") or "")
    prof_b = str(row_b.get("professional_id") or "")
    now_iso = datetime.now(timezone.utc).isoformat()
    meta_patch = {
        "swap_performed": True,
        "swap_mode": swap_mode,
        "swapped_at": now_iso,
        "swapped_by": changed_by,
    }
    ok_a = scheduling_repository.update_appointment_professional(
        cliente_id, appointment_a_id, prof_b, meta_patch=meta_patch
    )
    if not ok_a:
        return False, "update_falhou"
    ok_b = scheduling_repository.update_appointment_professional(
        cliente_id, appointment_b_id, prof_a, meta_patch=meta_patch
    )
    if not ok_b:
        scheduling_repository.update_appointment_professional(
            cliente_id, appointment_a_id, prof_a, meta_patch={"swap_rollback": True}
        )
        return False, "update_falhou"

    logger.info(
        "appointment_swap cliente_id=%s appointment_a=%s appointment_b=%s "
        "prof_a_antes=%s prof_b_antes=%s swap_mode=%s swapped_by=%s",
        cliente_id,
        appointment_a_id,
        appointment_b_id,
        prof_a,
        prof_b,
        swap_mode,
        changed_by,
    )
    return True, None


def build_swap_preview(
    row_a: dict[str, Any],
    row_b: dict[str, Any],
    prof_names: dict[str, str],
    tz_name: str | None,
) -> dict[str, Any]:
    """Estrutura Antes/Depois para o modal do painel."""
    ea = enrich_appointments_display([row_a], tz_name)[0]
    eb = enrich_appointments_display([row_b], tz_name)[0]
    prof_a_id = str(row_a.get("professional_id") or "")
    prof_b_id = str(row_b.get("professional_id") or "")
    prof_a = prof_names.get(prof_a_id, "—")
    prof_b = prof_names.get(prof_b_id, "—")

    def _time_label(row: dict[str, Any], enriched: dict[str, Any]) -> str:
        t = enriched.get("starts_time_display")
        if t:
            return str(t)
        return format_datetime_br(row.get("starts_at"), tz_name)

    time_a = _time_label(row_a, ea)
    time_b = _time_label(row_b, eb)
    client_a = ea.get("contact_name_display") or ea.get("contact_display") or "—"
    client_b = eb.get("contact_name_display") or eb.get("contact_display") or "—"

    return {
        "prof_a": prof_a,
        "prof_b": prof_b,
        "target_prof": prof_b,
        "conflict_client": client_b,
        "before": [
            {"prof": prof_a, "client": client_a, "time": time_a},
            {"prof": prof_b, "client": client_b, "time": time_b},
        ],
        "after": [
            {"prof": prof_a, "client": client_b, "time": time_b},
            {"prof": prof_b, "client": client_a, "time": time_a},
        ],
    }
