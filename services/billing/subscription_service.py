from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, Optional, Tuple

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


# Estados em subscriptions que bloqueiam o produto mas costumam ficar defasados após o webhook
# só ter atualizado `clientes` (antes do upsert unificado em billing.py).
_STALE_SUBSCRIPTION_STATUSES = frozenset({"onboarding", "pending"})
# Estados em `clientes.billing_status` que indicam assinatura válida / período pago.
_PAID_CLIENTE_STATUSES = frozenset({"active", "authorized", "trialing", "cancel_scheduled"})
_LEGACY_MP_GRACE_STATUSES = frozenset({"active", "authorized", "trialing", "cancel_scheduled"})


def is_legacy_mercadopago_grace(
    cliente_id: str,
    billing_status: str | None = None,
    period_end: Optional[datetime] = None,
) -> bool:
    """
    Assinantes Mercado Pago legados: acesso read-only até billing_current_period_end.
    Não chama API MP; só valida dados já persistidos.
    """
    cid = str(cliente_id or "").strip()
    if not cid or not supabase:
        return False

    status = (billing_status or "").strip().lower()
    if status and status not in _LEGACY_MP_GRACE_STATUSES:
        return False

    has_mp = False
    try:
        r = (
            supabase.table(Tables.CLIENTES)
            .select(getattr(ClienteModel, "MP_PREAPPROVAL_ID", "mp_preapproval_id"))
            .eq(ClienteModel.ID, cid)
            .limit(1)
            .execute()
        )
        row = r.data[0] if r.data else {}
        has_mp = bool((row.get(getattr(ClienteModel, "MP_PREAPPROVAL_ID", "mp_preapproval_id")) or "").strip())
    except Exception:
        has_mp = False

    if not has_mp:
        try:
            r2 = (
                supabase.table(Tables.SUBSCRIPTIONS)
                .select(SubscriptionModel.PROVIDER)
                .eq(SubscriptionModel.CLIENTE_ID, cid)
                .limit(1)
                .execute()
            )
            prov = ((r2.data[0] if r2.data else {}).get(SubscriptionModel.PROVIDER) or "").strip().lower()
            has_mp = prov == "mercadopago"
        except Exception:
            pass

    if not has_mp:
        return False

    if period_end is None:
        try:
            r3 = (
                supabase.table(Tables.CLIENTES)
                .select(getattr(ClienteModel, "BILLING_CURRENT_PERIOD_END", "billing_current_period_end"))
                .eq(ClienteModel.ID, cid)
                .limit(1)
                .execute()
            )
            raw = (r3.data[0] if r3.data else {}).get(
                getattr(ClienteModel, "BILLING_CURRENT_PERIOD_END", "billing_current_period_end")
            )
            period_end = _parse_dt(raw)
        except Exception:
            period_end = None

    if status == "trialing":
        return True
    if period_end and datetime.now(timezone.utc) <= period_end:
        return True
    return False


def _billing_tuple_from_cliente_row(row2: Dict[str, Any]) -> Tuple[str, Optional[datetime], Optional[datetime], Optional[str]]:
    """Mesma semântica do fallback histórico + cancel_scheduled (alinhado a entitlements.get_billing_state)."""
    if not row2:
        return "active", None, None, None
    bs = getattr(ClienteModel, "BILLING_STATUS", "billing_status")
    status2 = (row2.get(bs) or "active").strip().lower()
    period_end2 = _parse_dt(row2.get(getattr(ClienteModel, "BILLING_CURRENT_PERIOD_END", "billing_current_period_end")))
    trial_end2 = _parse_dt(row2.get(getattr(ClienteModel, "TRIAL_ENDS_AT", "trial_ends_at")))
    plan_key2 = (row2.get(getattr(ClienteModel, "BILLING_PLAN_KEY", "billing_plan_key")) or "").strip() or None
    try:
        cancel_flag = bool(
            row2.get(getattr(ClienteModel, "BILLING_CANCEL_AT_PERIOD_END", "billing_cancel_at_period_end"))
        )
    except Exception:
        cancel_flag = False
    if cancel_flag and period_end2 and datetime.now(timezone.utc) <= period_end2:
        status2 = "cancel_scheduled"
    return status2, period_end2, trial_end2, plan_key2


def get_tenant_subscription_state(cliente_id: str) -> Tuple[str, Optional[datetime], Optional[datetime], Optional[str]]:
    """
    Preferência: subscriptions (por cliente_id), com leitura de clientes para compatibilidade.

    Se existir linha em subscriptions com status onboarding/pending mas `clientes.billing_status`
    já estiver pago (active/authorized/trialing/cancel_scheduled), usa clientes — evita bloqueio
    quando a linha de subscriptions ficou desatualizada antes do fix do webhook.

    Retorna (status, current_period_end_dt, trial_ends_at_dt, plan_key).
    """
    cid = str(cliente_id or "").strip()
    if not cid or not supabase:
        return "active", None, None, None

    sub_row: Optional[Dict[str, Any]] = None
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
            sub_row = r.data[0] or {}
    except Exception:
        pass

    row2: Dict[str, Any] = {}
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
                        getattr(ClienteModel, "BILLING_CANCEL_AT_PERIOD_END", "billing_cancel_at_period_end"),
                    ]
                )
            )
            .eq(ClienteModel.ID, cid)
            .limit(1)
            .execute()
        )
        row2 = r2.data[0] if r2.data else {}
    except Exception:
        pass

    bs = getattr(ClienteModel, "BILLING_STATUS", "billing_status")
    raw_cli = (row2.get(bs) or "").strip().lower()

    if sub_row:
        status_sub = (sub_row.get(SubscriptionModel.STATUS) or "").strip().lower()
        if raw_cli in _PAID_CLIENTE_STATUSES and status_sub in _STALE_SUBSCRIPTION_STATUSES:
            return _billing_tuple_from_cliente_row(row2)
        status = (sub_row.get(SubscriptionModel.STATUS) or "active").strip().lower()
        period_end = _parse_dt(sub_row.get(SubscriptionModel.CURRENT_PERIOD_END))
        trial_end = _parse_dt(sub_row.get(getattr(SubscriptionModel, "TRIAL_ENDS_AT", "trial_ends_at")))
        plan_key = (sub_row.get(SubscriptionModel.PLAN_KEY) or "").strip() or None
        return status, period_end, trial_end, plan_key

    return _billing_tuple_from_cliente_row(row2)


def upsert_tenant_subscription(
    *,
    cliente_id: str,
    provider: str = "stripe",
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
        SubscriptionModel.PROVIDER: (provider or "stripe").strip() or "stripe",
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

