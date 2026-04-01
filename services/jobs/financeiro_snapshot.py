from __future__ import annotations

import json
from datetime import date, datetime, timezone
from typing import Any, Dict

from database.supabase_sq import supabase
from database.models import Tables, ClienteModel, BillingEventModel


def run_snapshot(day_iso: str | None = None) -> Dict[str, Any]:
    """
    Calcula métricas financeiras básicas do SaaS e salva em billing_snapshots_daily.
    - Receita (valor real): soma dos `billing_events.amount` para eventos de billing aprovados/ativos no dia.
    - Contagens por status.
    """
    if supabase is None:
        return {"ok": False, "erro": "Supabase não configurado."}

    if day_iso:
        d = date.fromisoformat(day_iso)
    else:
        d = datetime.now(timezone.utc).date()

    def _try_parse_json(raw: Any) -> Any:
        if raw is None:
            return None
        if isinstance(raw, (dict, list)):
            return raw
        if not isinstance(raw, str):
            try:
                return json.loads(str(raw))
            except Exception:
                return None
        s = raw.strip()
        if not s:
            return None
        try:
            return json.loads(s)
        except Exception:
            return None

    def _deep_find_status(obj: Any) -> str | None:
        """Procura um campo 'status' em estruturas aninhadas."""
        allowed = {"active", "authorized", "pending", "rejected", "cancelled", "canceled", "inactive", "past_due"}
        try:
            if isinstance(obj, dict):
                # Prioriza status local do objeto
                if isinstance(obj.get("status"), str):
                    st = obj.get("status").strip().lower()
                    if st in allowed:
                        return st
                for v in obj.values():
                    r = _deep_find_status(v)
                    if r:
                        return r
            elif isinstance(obj, list):
                for it in obj:
                    r = _deep_find_status(it)
                    if r:
                        return r
        except Exception:
            return None
        return None

    def _deep_find_transaction_amount(obj: Any) -> float | None:
        """
        Procura transaction_amount / auto_recurring.transaction_amount em estruturas aninhadas.
        Retorna float se encontrado.
        """
        try:
            if isinstance(obj, dict):
                # Alguns payloads podem trazer diretamente a chave
                if obj.get("transaction_amount") is not None:
                    try:
                        return float(obj.get("transaction_amount"))
                    except Exception:
                        pass
                # Busca recursiva por 'auto_recurring' e demais
                for v in obj.values():
                    r = _deep_find_transaction_amount(v)
                    if r is not None:
                        return r
            elif isinstance(obj, list):
                for it in obj:
                    r = _deep_find_transaction_amount(it)
                    if r is not None:
                        return r
        except Exception:
            return None
        return None

    # Carrega clientes (apenas campos necessários)
    try:
        clientes = (
            supabase.table(Tables.CLIENTES)
            .select(
                ",".join(
                    [
                        ClienteModel.ID,
                        ClienteModel.BILLING_STATUS,
                        ClienteModel.BILLING_PLAN_KEY,
                        ClienteModel.TRIAL_ENDS_AT,
                    ]
                )
            )
            .execute()
            .data
            or []
        )
    except Exception as e:
        return {"ok": False, "erro": str(e)}

    counts = {
        "active_subscriptions": 0,
        "trialing": 0,
        "past_due": 0,
        "canceled": 0,
        "inactive": 0,
    }
    by_plan: Dict[str, int] = {}
    revenue_today = 0.0

    for c in clientes:
        status = (c.get(ClienteModel.BILLING_STATUS) or "inactive").strip().lower()
        plan_key = (c.get(ClienteModel.BILLING_PLAN_KEY) or c.get(ClienteModel.PLANO) or "").strip() or "social"
        by_plan[plan_key] = by_plan.get(plan_key, 0) + 1

        if status in ("active", "authorized"):
            counts["active_subscriptions"] += 1
        elif status == "trialing":
            counts["trialing"] += 1
        elif status == "past_due":
            counts["past_due"] += 1
        elif status in ("canceled", "cancelled"):
            counts["canceled"] += 1
        else:
            counts["inactive"] += 1

    # Receita por dia (valor real): soma eventos de billing aprovados/ativos processados no dia.
    start_dt = datetime(d.year, d.month, d.day, 0, 0, 0, tzinfo=timezone.utc).isoformat()
    end_dt = datetime(d.year, d.month, d.day, 23, 59, 59, 999999, tzinfo=timezone.utc).isoformat()
    try:
        rows = (
            supabase.table(Tables.BILLING_EVENTS)
            .select(",".join([BillingEventModel.AMOUNT, BillingEventModel.MP_STATUS, BillingEventModel.PROCESSED_AT, BillingEventModel.RAW_BODY]))
            .eq(BillingEventModel.STATUS, "processed")
            .gte(BillingEventModel.PROCESSED_AT, start_dt)
            .lte(BillingEventModel.PROCESSED_AT, end_dt)
            .execute()
            .data
            or []
        )
    except Exception:
        rows = []

    for e in rows:
        mp_status = (e.get(BillingEventModel.MP_STATUS) or "").strip().lower() if isinstance(e, dict) else ""
        if not mp_status:
            mp_status = (_deep_find_status(_try_parse_json(e.get(BillingEventModel.RAW_BODY))) or "").strip().lower()
        if mp_status not in ("active", "authorized"):
            continue

        amt = e.get(BillingEventModel.AMOUNT)
        if amt is None or amt == "":
            amt = _deep_find_transaction_amount(_try_parse_json(e.get(BillingEventModel.RAW_BODY)))
        try:
            revenue_today += float(amt or 0.0)
        except Exception:
            pass

    payload = {
        "day": d.isoformat(),
        "mrr_total": revenue_today,
        "active_subscriptions": counts["active_subscriptions"],
        "trialing": counts["trialing"],
        "past_due": counts["past_due"],
        "canceled": counts["canceled"],
        "inactive": counts["inactive"],
        "new_paid": 0,
        "churned": 0,
        "revenue_estimated": revenue_today,
        "by_plan": by_plan,
    }

    try:
        # upsert pelo PK day
        supabase.table("billing_snapshots_daily").upsert(payload).execute()
        return {"ok": True, "snapshot": payload}
    except Exception as e:
        return {"ok": False, "erro": str(e), "snapshot": payload}

