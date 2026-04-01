from __future__ import annotations

from typing import Any, Dict, Optional

from database.supabase_sq import supabase
from database.models import Tables, ClienteModel
from services.billing.mercadopago import get_preapproval


def reconcile_cliente(cliente_id: str) -> Dict[str, Any]:
    """
    Revalida a assinatura do cliente no Mercado Pago a partir do mp_preapproval_id.
    """
    if supabase is None:
        return {"ok": False, "erro": "Supabase não configurado."}
    try:
        r = (
            supabase.table(Tables.CLIENTES)
            .select(
                ",".join(
                    [
                        ClienteModel.ID,
                        ClienteModel.MP_PREAPPROVAL_ID,
                        ClienteModel.BILLING_PLAN_KEY,
                    ]
                )
            )
            .eq(ClienteModel.ID, cliente_id)
            .single()
            .execute()
        )
        row = r.data or {}
    except Exception as e:
        return {"ok": False, "erro": str(e)}

    preapproval_id = (row.get(ClienteModel.MP_PREAPPROVAL_ID) or "").strip()
    if not preapproval_id:
        return {"ok": True, "status": "no_preapproval"}

    ok, pre = get_preapproval(preapproval_id)
    if not ok:
        return {"ok": False, "erro": "Falha ao buscar preapproval no MP", "detalhe": pre}

    status = (pre.get("status") or "").strip().lower() or "pending"
    current_period_end = (pre.get("next_payment_date") or pre.get("end_date") or None)
    payload: Dict[str, Any] = {ClienteModel.BILLING_STATUS: status}
    if current_period_end:
        payload[ClienteModel.BILLING_CURRENT_PERIOD_END] = current_period_end

    try:
        supabase.table(Tables.CLIENTES).update(payload).eq(ClienteModel.ID, cliente_id).execute()
    except Exception as e:
        return {"ok": False, "erro": str(e), "mp": pre}
    return {"ok": True, "cliente_id": cliente_id, "mp": {"status": status, "current_period_end": current_period_end}}


def reconcile_all(limit: int = 500) -> Dict[str, Any]:
    """
    Revalida um lote de clientes com mp_preapproval_id preenchido.
    """
    if supabase is None:
        return {"ok": False, "erro": "Supabase não configurado."}
    try:
        res = (
            supabase.table(Tables.CLIENTES)
            .select(",".join([ClienteModel.ID, ClienteModel.MP_PREAPPROVAL_ID]))
            .not_.is_(ClienteModel.MP_PREAPPROVAL_ID, "null")
            .limit(limit)
            .execute()
        )
        rows = res.data or []
    except Exception as e:
        return {"ok": False, "erro": str(e)}

    out = {"ok": True, "total": len(rows), "updated": 0, "failed": 0}
    for r in rows:
        cid = r.get(ClienteModel.ID)
        if not cid:
            continue
        res_one = reconcile_cliente(str(cid))
        if res_one.get("ok"):
            out["updated"] += 1
        else:
            out["failed"] += 1
    return out

