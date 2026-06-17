"""Factory de adaptadores por motor de agenda."""
from __future__ import annotations

from services.scheduling.engine import scheduling_uses_internal_motor
from services.scheduling.motor_adapters.agenda_ia import AgendaIAMotorAdapter
from services.scheduling.motor_adapters.base import MotorAdapter
from services.scheduling.motor_adapters.internal import InternalMotorAdapter

_internal = InternalMotorAdapter()
_agenda_ia = AgendaIAMotorAdapter()


def get_motor_adapter(cliente_id: str | None) -> MotorAdapter:
    if scheduling_uses_internal_motor(cliente_id):
        return _internal
    return _agenda_ia


def panel_booking_allowed(cliente_id: str | None) -> bool:
    """Painel pode criar agendamentos (único/recorrente) se scheduling configurado."""
    cid = (cliente_id or "").strip()
    if not cid:
        return False
    try:
        from services.scheduling import repository as sched_repo

        if not sched_repo.supabase_available():
            return False
        return sched_repo.get_settings(cid) is not None
    except Exception:
        return False
