"""Acções de confirmação: aprovar, recusar, propor e resolver propostas."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from services.scheduling import repository
from services.scheduling.confirmation_tokens import create_proposal_token, resolve_token
from services.scheduling.display import appointment_meta_dict, parse_iso_datetime
from services.scheduling.swap import SwapOffer


def _appointment_pending(row: dict[str, Any] | None) -> bool:
    return bool(row) and str(row.get("status") or "").lower() == "pending"


def _sync_agenda_schedule(
    cliente_id: str,
    appointment_id: str,
    *,
    starts_at: datetime,
    ends_at: datetime,
    target_status: str = "confirmed",
) -> tuple[bool, str | None]:
    row = repository.get_appointment(cliente_id, appointment_id)
    ext = str((row or {}).get("external_agenda_appointment_id") or "").strip()
    if not ext:
        return True, None
    from services.agendamento_ia_confirmation import finalize_appointment_in_agendamento_ia

    return finalize_appointment_in_agendamento_ia(
        cliente_id=cliente_id,
        external_appointment_id=ext,
        remote_id=str((row or {}).get("remote_id") or ""),
        starts_at=starts_at,
        ends_at=ends_at,
        target_status=target_status,
    )


def confirm_appointment(
    cliente_id: str,
    appointment_id: str,
    *,
    confirmed_by: str,
) -> tuple[bool, str | None]:
    row = repository.get_appointment(cliente_id, appointment_id)
    if not row:
        return False, "nao_encontrado"
    if not _appointment_pending(row):
        return False, "nao_pendente"

    ext = str(row.get("external_agenda_appointment_id") or "").strip()
    starts = parse_iso_datetime(row.get("starts_at"))
    ends = parse_iso_datetime(row.get("ends_at"))
    if ext and starts and ends:
        ok_ext, err_ext = _sync_agenda_schedule(
            cliente_id,
            appointment_id,
            starts_at=starts,
            ends_at=ends,
            target_status="confirmed",
        )
        if not ok_ext:
            return False, err_ext or "agenda_confirm_falhou"
    elif ext:
        from services.agendamento_ia_confirmation import confirm_appointment_in_agendamento_ia

        ok_ext, err_ext = confirm_appointment_in_agendamento_ia(
            cliente_id=cliente_id,
            external_appointment_id=ext,
            remote_id=str(row.get("remote_id") or ""),
        )
        if not ok_ext:
            return False, err_ext or "agenda_confirm_falhou"

    ok = repository.update_appointment_status(cliente_id, appointment_id, "confirmed")
    if not ok:
        return False, "update_falhou"
    repository.merge_appointment_meta(
        cliente_id,
        appointment_id,
        {
            "confirmed_at": datetime.now(timezone.utc).isoformat(),
            "confirmed_by": confirmed_by,
        },
    )
    from services.scheduling.confirmation_notify import notify_client_confirmed

    notify_client_confirmed(cliente_id, appointment_id)
    try:
        from services.scheduling.client_calendar_invite import on_appointment_confirmed

        on_appointment_confirmed(cliente_id, appointment_id, kind="confirmed")
    except Exception:
        pass
    return True, None


def reject_appointment(
    cliente_id: str,
    appointment_id: str,
    *,
    rejected_by: str,
) -> tuple[bool, str | None]:
    row = repository.get_appointment(cliente_id, appointment_id)
    if not row:
        return False, "nao_encontrado"
    if not _appointment_pending(row):
        return False, "nao_pendente"

    ext = str(row.get("external_agenda_appointment_id") or "").strip()
    if ext:
        from services.agendamento_ia_confirmation import reject_appointment_in_agendamento_ia

        ok_ext, err_ext = reject_appointment_in_agendamento_ia(
            cliente_id=cliente_id,
            external_appointment_id=ext,
            remote_id=str(row.get("remote_id") or ""),
        )
        if not ok_ext:
            return False, err_ext or "agenda_reject_falhou"

    ok = repository.update_appointment_status(cliente_id, appointment_id, "cancelled")
    if not ok:
        return False, "update_falhou"
    repository.merge_appointment_meta(
        cliente_id,
        appointment_id,
        {
            "cancellation_reason": "professional_rejected",
            "rejected_by": rejected_by,
            "rejected_at": datetime.now(timezone.utc).isoformat(),
        },
    )
    from services.scheduling.confirmation_notify import notify_client_rejected

    notify_client_rejected(cliente_id, appointment_id)
    return True, None


def propose_new_time(
    cliente_id: str,
    appointment_id: str,
    *,
    proposed_starts_at: datetime,
    proposed_ends_at: datetime,
    proposed_by: str,
) -> tuple[dict[str, Any] | None, str | None]:
    row = repository.get_appointment(cliente_id, appointment_id)
    if not row:
        return None, "nao_encontrado"
    if not _appointment_pending(row):
        return None, "nao_pendente"
    if proposed_starts_at >= proposed_ends_at:
        return None, "horario_invalido"
    repository.supersede_open_proposals(cliente_id, appointment_id)
    proposal = repository.insert_proposal(
        cliente_id=cliente_id,
        appointment_id=appointment_id,
        proposed_starts_at=proposed_starts_at,
        proposed_ends_at=proposed_ends_at,
        proposed_by=proposed_by,
    )
    if not proposal:
        return None, "proposta_falhou"
    pid = str(proposal.get("id") or "")
    proposal_url = create_proposal_token(
        cliente_id=cliente_id,
        appointment_id=appointment_id,
        proposal_id=pid,
    )
    repository.merge_appointment_meta(
        cliente_id,
        appointment_id,
        {"proposal_id": pid},
    )
    from services.scheduling.confirmation_notify import notify_client_proposal

    notify_client_proposal(
        cliente_id,
        appointment_id,
        proposal_url=proposal_url,
        proposed_starts_at=proposed_starts_at,
    )
    return proposal, None


def propose_reschedule_confirmed(
    cliente_id: str,
    appointment_id: str,
    *,
    proposed_starts_at: datetime,
    duration_minutes: int,
    professional_id: str | None,
    proposed_by: str,
) -> tuple[dict[str, Any] | None, str | None, SwapOffer | None]:
    """Remarcação de horário confirmado: volta a pending e pede confirmação ao cliente."""
    row = repository.get_appointment(cliente_id, appointment_id)
    if not row:
        return None, "nao_encontrado", None
    if str(row.get("status") or "").lower() != "confirmed":
        return None, "nao_confirmado", None
    phone = "".join(
        c for c in str(row.get("contact_phone") or row.get("remote_id") or "") if c.isdigit()
    )
    if len(phone) < 10:
        return None, "sem_telefone_cliente", None

    pid = professional_id or str(row.get("professional_id") or "") or None
    from services.scheduling.bookings import check_reschedule_slot

    ok, err, offer = check_reschedule_slot(
        cliente_id=cliente_id,
        appointment_id=appointment_id,
        new_starts_at=proposed_starts_at,
        duration_minutes=duration_minutes,
        professional_id=pid,
    )
    if not ok:
        return None, err, offer

    proposed_ends_at = proposed_starts_at + timedelta(
        minutes=max(1, int(duration_minutes or 30))
    )
    if pid and pid != str(row.get("professional_id") or ""):
        repository.update_appointment_professional(cliente_id, appointment_id, pid)

    original_starts = row.get("starts_at")
    original_ends = row.get("ends_at")
    if not repository.update_appointment_status(cliente_id, appointment_id, "pending"):
        return None, "update_falhou", None

    repository.merge_appointment_meta(
        cliente_id,
        appointment_id,
        {
            "reschedule_from_confirmed": True,
            "confirmed_slot_starts_at": original_starts,
            "confirmed_slot_ends_at": original_ends,
            "reschedule_proposed_at": datetime.now(timezone.utc).isoformat(),
            "reschedule_proposed_by": proposed_by,
        },
    )
    repository.supersede_open_proposals(cliente_id, appointment_id)
    proposal = repository.insert_proposal(
        cliente_id=cliente_id,
        appointment_id=appointment_id,
        proposed_starts_at=proposed_starts_at,
        proposed_ends_at=proposed_ends_at,
        proposed_by=proposed_by,
    )
    if not proposal:
        repository.update_appointment_status(cliente_id, appointment_id, "confirmed")
        return None, "proposta_falhou", None

    prop_id = str(proposal.get("id") or "")
    proposal_url = create_proposal_token(
        cliente_id=cliente_id,
        appointment_id=appointment_id,
        proposal_id=prop_id,
    )
    repository.merge_appointment_meta(
        cliente_id,
        appointment_id,
        {"proposal_id": prop_id},
    )
    from services.scheduling.confirmation_notify import notify_client_proposal

    notify_client_proposal(
        cliente_id,
        appointment_id,
        proposal_url=proposal_url,
        proposed_starts_at=proposed_starts_at,
        is_reschedule=True,
    )
    return proposal, None, None


def _execute_accept_proposal(
    token_row: dict[str, Any],
) -> tuple[bool, str | None, dict[str, Any] | None]:
    cid = str(token_row.get("cliente_id") or "")
    aid = str(token_row.get("appointment_id") or "")
    pid = str(token_row.get("proposal_id") or "")
    appt = repository.get_appointment(cid, aid)
    if not _appointment_pending(appt):
        return False, "nao_pendente", None
    proposal = repository.get_proposal(cid, pid)
    if not proposal or str(proposal.get("status") or "") != "open":
        return False, "proposta_indisponivel", None
    meta_before = appointment_meta_dict((appt or {}).get("meta"))
    was_reschedule = bool(meta_before.get("reschedule_from_confirmed"))
    starts = parse_iso_datetime(proposal.get("proposed_starts_at"))
    ends = parse_iso_datetime(proposal.get("proposed_ends_at"))
    if not starts or not ends:
        return False, "horario_invalido", None
    prof_id = str((appt or {}).get("professional_id") or "") or None
    svc = repository.get_service(cid, str((appt or {}).get("service_id") or ""))
    dur = int((svc or {}).get("duration_minutes") or 30)
    from services.scheduling.bookings import check_reschedule_slot, reschedule_appointment

    ok, rerr, _swap = check_reschedule_slot(
        cliente_id=cid,
        appointment_id=aid,
        new_starts_at=starts,
        duration_minutes=dur,
        professional_id=prof_id,
    )
    if not ok:
        return False, rerr or "slot_ocupado", None
    ok_sync, sync_err = _sync_agenda_schedule(
        cid,
        aid,
        starts_at=starts,
        ends_at=ends,
        target_status="confirmed",
    )
    if not ok_sync:
        return False, sync_err or "agenda_sync_falhou", None
    ok, rerr, _swap = reschedule_appointment(
        cliente_id=cid,
        appointment_id=aid,
        new_starts_at=starts,
        duration_minutes=dur,
        professional_id=prof_id,
    )
    if not ok:
        return False, rerr or "slot_ocupado", None
    repository.update_appointment_status(cid, aid, "confirmed")
    repository.update_proposal_status(cid, pid, "accepted")
    repository.mark_confirmation_token_used(str(token_row.get("id") or ""))
    merge_patch: dict[str, Any] = {
        "confirmed_at": datetime.now(timezone.utc).isoformat(),
        "confirmed_by": "client_proposal_accept",
        "proposal_id": pid,
        "reschedule_from_confirmed": False,
    }
    repository.merge_appointment_meta(cid, aid, merge_patch)
    from services.scheduling.confirmation_notify import notify_client_confirmed

    notify_client_confirmed(cid, aid)
    try:
        from services.scheduling.client_calendar_invite import on_appointment_confirmed

        invite_kind = "rescheduled" if was_reschedule else "confirmed"
        on_appointment_confirmed(cid, aid, kind=invite_kind)
    except Exception:
        pass
    return True, None, appt


def _execute_decline_proposal(token_row: dict[str, Any]) -> tuple[bool, str | None]:
    cid = str(token_row.get("cliente_id") or "")
    aid = str(token_row.get("appointment_id") or "")
    pid = str(token_row.get("proposal_id") or "")
    appt = repository.get_appointment(cid, aid)
    if not _appointment_pending(appt):
        return False, "nao_pendente"
    if pid:
        repository.update_proposal_status(cid, pid, "declined")
    repository.merge_appointment_meta(
        cid,
        aid,
        {
            "awaiting_client_slot": True,
            "proposal_declined_by_client_at": datetime.now(timezone.utc).isoformat(),
            "reschedule_from_confirmed": False,
            "proposal_id": pid or None,
        },
    )
    return True, None


def client_choose_alternative_slot(raw_token: str, slot_iso: str) -> tuple[bool, str | None]:
    """Cliente escolhe novo horário após recusar proposta da clínica."""
    token_row, err = resolve_token(raw_token)
    if err or not token_row:
        return False, err or "token_invalido"
    cid = str(token_row.get("cliente_id") or "")
    aid = str(token_row.get("appointment_id") or "")
    appt = repository.get_appointment(cid, aid)
    if not _appointment_pending(appt):
        return False, "nao_pendente"
    starts = parse_iso_datetime(slot_iso)
    if not starts:
        return False, "horario_invalido"
    svc = repository.get_service(cid, str(appt.get("service_id") or ""))
    dur = int((svc or {}).get("duration_minutes") or 30)
    prof_id = str(appt.get("professional_id") or "") or None
    from services.scheduling.bookings import check_reschedule_slot, reschedule_appointment

    ok, rerr, _swap = check_reschedule_slot(
        cliente_id=cid,
        appointment_id=aid,
        new_starts_at=starts,
        duration_minutes=dur,
        professional_id=prof_id,
    )
    if not ok:
        return False, rerr or "slot_ocupado"
    ok, rerr, _swap = reschedule_appointment(
        cliente_id=cid,
        appointment_id=aid,
        new_starts_at=starts,
        duration_minutes=dur,
        professional_id=prof_id,
    )
    if not ok:
        return False, rerr or "falha"
    ok_sync, sync_err = _sync_agenda_schedule(
        cid,
        aid,
        starts_at=starts,
        ends_at=starts + timedelta(minutes=dur),
        target_status="pending",
    )
    if not ok_sync:
        return False, sync_err or "agenda_sync_falhou"
    repository.merge_appointment_meta(
        cid,
        aid,
        {
            "awaiting_client_slot": False,
            "client_suggested_slot_at": datetime.now(timezone.utc).isoformat(),
            "client_suggested_via": "confirmacao_page",
        },
    )
    repository.mark_confirmation_token_used(str(token_row.get("id") or ""))
    updated = repository.get_appointment(cid, aid) or appt
    from services.scheduling.confirmation_notify import (
        notify_client_slot_submitted,
        notify_pending_booking,
    )

    notify_pending_booking(cid, updated)
    notify_client_slot_submitted(cid, aid)
    return True, None


def accept_proposal_token(raw_token: str) -> tuple[bool, str | None, dict[str, Any] | None]:
    token_row, err = resolve_token(raw_token)
    if err or not token_row:
        return False, err or "token_invalido", None
    if str(token_row.get("action") or "") != "accept_proposal":
        return False, "acao_invalida", None
    return _execute_accept_proposal(token_row)


def decline_proposal_token(raw_token: str) -> tuple[bool, str | None]:
    token_row, err = resolve_token(raw_token)
    if err or not token_row:
        return False, err or "token_invalido"
    if str(token_row.get("action") or "") != "decline_proposal":
        return False, "acao_invalida"
    return _execute_decline_proposal(token_row)


def resolve_proposal_choice(
    raw_token: str,
    choice: str,
) -> tuple[bool, str | None, dict[str, Any] | None]:
    """Resolve proposta: token único (resolve_proposal) ou legado accept/decline."""
    token_row, err = resolve_token(raw_token)
    if err or not token_row:
        return False, err or "token_invalido", None

    action = str(token_row.get("action") or "")
    choice_norm = (choice or "").strip().lower()

    if action == "resolve_proposal":
        if choice_norm == "accept":
            return _execute_accept_proposal(token_row)
        if choice_norm == "decline":
            ok, derr = _execute_decline_proposal(token_row)
            return ok, derr, None
        return False, "escolha_invalida", None

    if choice_norm == "accept":
        return accept_proposal_token(raw_token)
    if choice_norm == "decline":
        ok, derr = decline_proposal_token(raw_token)
        return ok, derr, None
    return False, "escolha_invalida", None
