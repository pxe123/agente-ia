from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List

from database.supabase_sq import supabase
from database.models import Tables, ClienteModel
from services.billing.mercadopago import cancel_preapproval, now_iso


def run_cancel_scheduled(limit: int = 500) -> Dict[str, Any]:
    """
    Job periódico para efetivar cancelamentos agendados no fim do período.

    Fluxo:
    - Seleciona clientes com billing_cancel_at_period_end=true
    - Se billing_current_period_end <= now e mp_preapproval_id existe, cancela no Mercado Pago
    - Atualiza billing_status para cancelled e limpa flags
    """
    if supabase is None:
        return {"ok": False, "erro": "Supabase não configurado."}

    now = datetime.now(timezone.utc)
    now_s = now_iso()

    try:
        rows: List[dict] = (
            supabase.table(Tables.CLIENTES)
            .select(
                ",".join(
                    [
                        ClienteModel.ID,
                        ClienteModel.MP_PREAPPROVAL_ID,
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
        preapproval_id = (c.get(ClienteModel.MP_PREAPPROVAL_ID) or "").strip()
        if not preapproval_id:
            out["skipped"] += 1
            continue

        ok, mp = cancel_preapproval(preapproval_id)
        if not ok:
            out["failed"] += 1
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

