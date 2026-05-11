from __future__ import annotations

from datetime import datetime
from typing import Optional, Tuple

from database.supabase_sq import supabase
from database.models import Tables, SubscriptionModel, ClienteModel


def _parse_dt(value) -> Optional[datetime]:
    if not value:
        return None
    try:
        from datetime import datetime as _dt

        return _dt.fromisoformat(str(value).replace("Z", "+00:00"))
    except Exception:
        return None


def get_tenant_subscription_state(cliente_id: str) -> Tuple[str, Optional[datetime], Optional[datetime], Optional[str]]:
    """
    Fonte de verdade: subscriptions (por cliente_id).
    Fallback: clientes.billing_* para compatibilidade.

    Retorna (status, current_period_end_dt, trial_ends_at_dt, plan_key).
    """
    cid = str(cliente_id or "").strip()
    if not cid or not supabase:
        return "active", None, None, None

    # 1) subscriptions (preferencial)
    try:
        r = (
            supabase.table(Tables.SUBSCRIPTIONS)
            .select(
                ",".join(
                    [
                        SubscriptionModel.STATUS,
                        SubscriptionModel.CURRENT_PERIOD_END,
                        getattr(SubscriptionModel, "TRIAL_ENDS_AT", "trial_ends_at"),
                        SubscriptionModel.PLAN_KEY,
                    ]
                )
            )
            .eq(SubscriptionModel.CLIENTE_ID, cid)
            .limit(1)
            .execute()
        )
        if r.data:
            row = r.data[0] or {}
            status = (row.get(SubscriptionModel.STATUS) or "active").strip().lower()
            period_end = _parse_dt(row.get(SubscriptionModel.CURRENT_PERIOD_END))
            trial_end = _parse_dt(row.get(getattr(SubscriptionModel, "TRIAL_ENDS_AT", "trial_ends_at")))
            plan_key = (row.get(SubscriptionModel.PLAN_KEY) or "").strip() or None
            return status, period_end, trial_end, plan_key
    except Exception:
        pass

    # 2) fallback: clientes.billing_*
    try:
        r2 = (
            supabase.table(Tables.CLIENTES)
            .select(
                ",".join(
                    [
                        getattr(ClienteModel, "BILLING_STATUS", "billing_status"),
                        getattr(ClienteModel, "BILLING_CURRENT_PERIOD_END", "billing_current_period_end"),
                        getattr(ClienteModel, "TRIAL_ENDS_AT", "trial_ends_at"),
                        getattr(ClienteModel, "BILLING_PLAN_KEY", "billing_plan_key"),
                    ]
                )
            )
            .eq(ClienteModel.ID, cid)
            .limit(1)
            .execute()
        )
        row2 = r2.data[0] if r2.data else {}
        status2 = (row2.get(getattr(ClienteModel, "BILLING_STATUS", "billing_status")) or "active").strip().lower()
        period_end2 = _parse_dt(row2.get(getattr(ClienteModel, "BILLING_CURRENT_PERIOD_END", "billing_current_period_end")))
        trial_end2 = _parse_dt(row2.get(getattr(ClienteModel, "TRIAL_ENDS_AT", "trial_ends_at")))
        plan_key2 = (row2.get(getattr(ClienteModel, "BILLING_PLAN_KEY", "billing_plan_key")) or "").strip() or None
        return status2, period_end2, trial_end2, plan_key2
    except Exception:
        return "active", None, None, None


def upsert_tenant_subscription(
    *,
    cliente_id: str,
    provider: str = "mercadopago",
    provider_subscription_id: Optional[str] = None,
    plan_key: Optional[str] = None,
    status: Optional[str] = None,
    current_period_end: Optional[str] = None,
    trial_ends_at: Optional[str] = None,
) -> None:
    """
    Best-effort upsert em subscriptions (não deve quebrar fluxo se tabela não existir ainda).
    """
    cid = str(cliente_id or "").strip()
    if not cid or not supabase:
        return
    payload = {
        SubscriptionModel.CLIENTE_ID: cid,
        SubscriptionModel.PROVIDER: (provider or "mercadopago").strip() or "mercadopago",
        SubscriptionModel.PROVIDER_SUBSCRIPTION_ID: (provider_subscription_id or None),
        SubscriptionModel.PLAN_KEY: (plan_key or None),
        SubscriptionModel.STATUS: (status or None),
        SubscriptionModel.CURRENT_PERIOD_END: (current_period_end or None),
        getattr(SubscriptionModel, "TRIAL_ENDS_AT", "trial_ends_at"): (trial_ends_at or None),
        SubscriptionModel.UPDATED_AT: datetime.utcnow().isoformat(),
    }
    try:
        supabase.table(Tables.SUBSCRIPTIONS).upsert(payload, on_conflict=SubscriptionModel.CLIENTE_ID).execute()
    except Exception:
        return

