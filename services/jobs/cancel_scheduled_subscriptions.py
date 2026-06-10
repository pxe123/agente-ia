from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List

from database.supabase_sq import supabase
from database.models import Tables, ClienteModel


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def run_cancel_scheduled(limit: int = 500) -> Dict[str, Any]:
    """
    Job periódico para efetivar cancelamentos agendados no fim do período.

    Stripe e legacy MP: não chama APIs externas — confia no fim natural do período
    e atualiza status local quando billing_current_period_end passou.
    """
    if supabase is None:
        return {"ok": False, "erro": "Supabase não configurado."}

    now_s = _now_iso()

    try:
        rows: List[dict] = (
            supabase.table(Tables.CLIENTES)
            .select(
                ",".join(
                    [
                        ClienteModel.ID,
                        ClienteModel.BILLING_STATUS,
                        ClienteModel.BILLING_CURRENT_PERIOD_END,
                        getattr(ClienteModel, "BILLING_CANCEL_AT_PERIOD_END", "billing_cancel_at_period_end"),
                    ]
                )
            )
            .eq(getattr(ClienteModel, "BILLING_CANCEL_AT_PERIOD_END", "billing_cancel_at_period_end"), True)
            .lte(ClienteModel.BILLING_CURRENT_PERIOD_END, now_s)
            .limit(limit)
            .execute()
            .data
            or []
        )
    except Exception as e:
        return {"ok": False, "erro": str(e)}

    out = {"ok": True, "total": len(rows), "cancelled": 0, "skipped": 0, "failed": 0}

    for c in rows:
        cid = c.get(ClienteModel.ID)
        if not cid:
            out["skipped"] += 1
            continue

        try:
            payload = {
                ClienteModel.BILLING_STATUS: "cancelled",
                getattr(ClienteModel, "BILLING_CANCEL_AT_PERIOD_END", "billing_cancel_at_period_end"): False,
                getattr(ClienteModel, "BILLING_CANCEL_SCHEDULED_AT", "billing_cancel_scheduled_at"): None,
            }
            supabase.table(Tables.CLIENTES).update(payload).eq(ClienteModel.ID, cid).execute()
            out["cancelled"] += 1
        except Exception:
            out["failed"] += 1

    return out
