"""Remoção de marcações no painel com cancelamento no motor Agenda IA."""
from __future__ import annotations

from typing import Any

from database.models import SchedulingAppointmentModel
from services.scheduling import repository


def purge_appointment_from_panel(
    cliente_id: str,
    appointment_id: str,
) -> tuple[bool, str | None]:
    """
    Cancela no Agendamento IA (se espelhado) e remove a linha local.
    Não envia WhatsApp ao cliente — use cancel_appointment para cancelamento com aviso.
    """
    cid = (cliente_id or "").strip()
    aid = (appointment_id or "").strip()
    if not cid or not aid:
        return False, "appointment_id_em_falta"

    row = repository.get_appointment(cid, aid)
    if not row:
        return False, "nao_encontrado"

    ext = (
        row.get(SchedulingAppointmentModel.EXTERNAL_AGENDA_APPOINTMENT_ID)
        or row.get("external_agenda_appointment_id")
    )
    if ext:
        from services.agendamento_ia_cancel import cancel_appointment_in_agendamento_ia

        ok_remote, err = cancel_appointment_in_agendamento_ia(
            cliente_id=cid,
            external_appointment_id=str(ext),
            remote_id=str(row.get("remote_id") or row.get(SchedulingAppointmentModel.REMOTE_ID) or "") or None,
        )
        if not ok_remote:
            return False, err or "cancel_agenda_falhou"

    if not repository.delete_appointment_row(cid, aid):
        return False, "delete_falhou"
    return True, None


def purge_appointment_row(cliente_id: str, row: dict[str, Any]) -> tuple[bool, str | None]:
    aid = str(row.get("id") or row.get(SchedulingAppointmentModel.ID) or "")
    return purge_appointment_from_panel(cliente_id, aid)
