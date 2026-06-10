"""
Reconciliação ZapAction ↔ Agendamento IA: puxa marcações para scheduling_appointments.
"""
from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


def run_agendamento_ia_reconcile(
    cliente_id: str | None = None,
    *,
    since_hours: int = 24,
) -> dict[str, Any]:
    """
    Job: importa marcações do Agenda para o Supabase.
    since_hours mapeado para janela mínima de dias no import (mín. 7 dias).
    """
    from services.agendamento_ia_appointments_import import sync_appointments_from_agenda

    if not cliente_id:
        return {"ok": True, "skipped": "cliente_id_em_falta", "imported": 0}

    since_days = max(7, (since_hours + 23) // 24)
    imported, err = sync_appointments_from_agenda(str(cliente_id), since_days=since_days)
    if err:
        logger.info(
            "agendamento_ia_reconcile cliente_id=%s imported=%s err=%s",
            cliente_id[:8],
            imported,
            err,
        )
        return {"ok": False, "error": err, "imported": imported}
    return {"ok": True, "imported": imported}
