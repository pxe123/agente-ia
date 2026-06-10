from __future__ import annotations

import json
import logging
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from typing import Any, Dict, Optional, Tuple

import stripe
from stripe import StripeError

from base.config import settings
from billing.stripe_price_sync import ensure_stripe_price_for_plan
from database.models import PlanModel
from services.plans import get_plan, list_active_plans, plan_key_from_stripe_price_id

logger = logging.getLogger(__name__)


def _stripe_attr(obj: Any, key: str, default: Any = None) -> Any:
    """Lê campo de StripeObject ou dict (Stripe SDK v15+ não tem .get())."""
    if obj is None:
        return default
    if isinstance(obj, dict):
        return obj.get(key, default)
    try:
        return obj[key]
    except (KeyError, TypeError):
        return getattr(obj, key, default)


def _stripe_enabled() -> bool:
    return bool((getattr(settings, "STRIPE_SECRET_KEY", "") or "").strip())


def _configure_stripe() -> None:
    key = (getattr(settings, "STRIPE_SECRET_KEY", "") or "").strip()
    if key:
        stripe.api_key = key


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def _assert_stripe_price_id(price_id: str, *, env_var: str) -> None:
    """Garante Price ID (price_...), não Product ID (prod_...)."""
    pid = (price_id or "").strip()
    if not pid:
        raise ValueError(f"stripe_price_not_configured:{env_var}")
    if pid.startswith("prod_"):
        raise ValueError(
            f"stripe_price_invalid:{env_var}: use Price ID (price_...) no .env, não Product ID (prod_...)"
        )
    if not pid.startswith("price_"):
        raise ValueError(
            f"stripe_price_invalid:{env_var}: valor deve começar com price_ (Dashboard Stripe → Products → Price)"
        )


def price_id_for_plan(plan_key: str) -> str:
    """Price ID a partir da tabela plans (cria/sincroniza na Stripe se necessário)."""
    key = (plan_key or "").strip()
    if not key:
        raise ValueError("unknown_plan_key:")
    return ensure_stripe_price_for_plan(key)


def stripe_env_diagnostics() -> Dict[str, Any]:
    """Status das variáveis Stripe (sem expor segredos)."""
    secret_ok = bool((getattr(settings, "STRIPE_SECRET_KEY", "") or "").strip())
    pub_ok = bool((getattr(settings, "STRIPE_PUBLISHABLE_KEY", "") or "").strip())
    webhook_ok = bool((getattr(settings, "STRIPE_WEBHOOK_SECRET", "") or "").strip())
    success_url = (getattr(settings, "STRIPE_SUCCESS_URL", "") or "").strip()
    cancel_url = (getattr(settings, "STRIPE_CANCEL_URL", "") or "").strip()
    portal_url = (getattr(settings, "STRIPE_PORTAL_RETURN_URL", "") or "").strip()

    prices: Dict[str, str] = {}
    for plan in list_active_plans():
        pk = (plan.get(PlanModel.PLAN_KEY) or "").strip()
        if not pk:
            continue
        spid = (plan.get(PlanModel.STRIPE_PRICE_ID) or "").strip()
        if spid:
            try:
                _assert_stripe_price_id(spid, env_var=f"plans.{pk}.stripe_price_id")
                prices[pk] = "ok"
            except ValueError as e:
                prices[pk] = str(e)
        else:
            try:
                price_val = float(plan.get(PlanModel.PRICE) or 0)
            except (TypeError, ValueError):
                prices[pk] = "plan_price_invalid"
            else:
                if price_val <= 0:
                    prices[pk] = "plan_price_zero"
                elif secret_ok:
                    prices[pk] = "auto_create_on_checkout"
                else:
                    prices[pk] = "stripe_price_id_missing: configure STRIPE_SECRET_KEY ou plans.stripe_price_id"

    prices_ok = bool(prices) and all(
        v in ("ok", "auto_create_on_checkout") for v in prices.values()
    )

    return {
        "secret_key_set": secret_ok,
        "publishable_key_set": pub_ok,
        "webhook_secret_set": webhook_ok,
        "success_url_set": bool(success_url),
        "cancel_url_set": bool(cancel_url),
        "portal_return_url_set": bool(portal_url),
        "prices": prices,
        "ready": secret_ok and prices_ok and bool(success_url) and bool(cancel_url),
    }


def stripe_checkout_ready_for_plan(plan_key: str) -> tuple[bool, str]:
    """Valida plano ativo no Supabase + env Stripe mínimo."""
    pk = (plan_key or "").strip()
    if not pk:
        return False, "missing_plan_key"
    plan = get_plan(pk)
    if not plan:
        return False, f"unknown_plan:{pk}"
    if not bool(plan.get(PlanModel.ACTIVE, True)):
        return False, f"plan_inactive:{pk}"
    if not (getattr(settings, "STRIPE_SECRET_KEY", "") or "").strip():
        return False, "stripe_not_configured:STRIPE_SECRET_KEY"
    success_url = (getattr(settings, "STRIPE_SUCCESS_URL", "") or "").strip()
    cancel_url = (getattr(settings, "STRIPE_CANCEL_URL", "") or "").strip()
    if not success_url or not cancel_url:
        return False, "stripe_urls_missing:STRIPE_SUCCESS_URL/STRIPE_CANCEL_URL"
    spid = (plan.get(PlanModel.STRIPE_PRICE_ID) or "").strip()
    if spid:
        try:
            _assert_stripe_price_id(spid, env_var=f"plans.{pk}.stripe_price_id")
            return True, "ok"
        except ValueError as e:
            return False, str(e)
    try:
        price_id_for_plan(pk)
    except ValueError as e:
        return False, str(e)
    return True, "ok"


def create_or_get_customer(*, stripe_customer_id: str | None, email: str, cliente_id: str) -> str:
    _configure_stripe()
    if not _stripe_enabled():
        raise ValueError("stripe_not_configured")

    cid = (stripe_customer_id or "").strip()
    if cid:
        try:
            existing = stripe.Customer.retrieve(cid)
            if existing and not _stripe_attr(existing, "deleted"):
                return cid
        except StripeError as e:
            logger.warning(
                "stripe customer %s inválido para a chave atual, recriando: %s",
                cid,
                str(e)[:200],
            )

    c = stripe.Customer.create(
        email=(email or "").strip().lower() or None,
        metadata={"cliente_id": str(cliente_id)},
    )
    return str(_stripe_attr(c, "id") or "")


def create_checkout_session(
    *,
    cliente_id: str,
    user_id: str,
    email: str,
    plan_key: str,
    stripe_customer_id: str | None,
    success_url: str,
    cancel_url: str,
    trial_days: int | None = None,
) -> Tuple[str, str, str]:
    """
    Retorna (checkout_url, customer_id, session_id).
    """
    _configure_stripe()
    if not _stripe_enabled():
        raise ValueError("stripe_not_configured")

    price_id = price_id_for_plan(plan_key)
    customer_id = create_or_get_customer(
        stripe_customer_id=stripe_customer_id,
        email=email,
        cliente_id=cliente_id,
    )

    subscription_data: Dict[str, Any] = {
        "metadata": {
            "cliente_id": str(cliente_id),
            "user_id": str(user_id),
            "plan_key": (plan_key or "").strip(),
        }
    }
    if trial_days is not None and int(trial_days) > 0:
        subscription_data["trial_period_days"] = int(trial_days)

    sess = stripe.checkout.Session.create(
        mode="subscription",
        customer=customer_id,
        line_items=[{"price": price_id, "quantity": 1}],
        success_url=success_url,
        cancel_url=cancel_url,
        client_reference_id=str(cliente_id),
        metadata={
            "cliente_id": str(cliente_id),
            "user_id": str(user_id),
            "plan_key": (plan_key or "").strip(),
        },
        subscription_data=subscription_data,
        allow_promotion_codes=True,
    )
    url = str(_stripe_attr(sess, "url") or "")
    if not url:
        raise ValueError("stripe_session_missing_url")
    return url, customer_id, str(_stripe_attr(sess, "id") or "")


def create_customer_portal(
    *,
    stripe_customer_id: str,
    return_url: str,
) -> str:
    _configure_stripe()
    if not _stripe_enabled():
        raise ValueError("stripe_not_configured")

    ps = stripe.billing_portal.Session.create(customer=stripe_customer_id, return_url=return_url)
    url = str(_stripe_attr(ps, "url") or "")
    if not url:
        raise ValueError("stripe_portal_missing_url")
    return url


def construct_webhook_event(*, payload: bytes, sig_header: str) -> stripe.Event:
    _configure_stripe()
    secret = (getattr(settings, "STRIPE_WEBHOOK_SECRET", "") or "").strip()
    if not secret:
        raise ValueError("stripe_webhook_not_configured")
    return stripe.Webhook.construct_event(payload=payload, sig_header=sig_header, secret=secret)


def _ts_from_unix(value: Any) -> Optional[datetime]:
    try:
        if value is None:
            return None
        v = int(value)
        return datetime.fromtimestamp(v, tz=timezone.utc)
    except Exception:
        return None


@dataclass(frozen=True)
class StripeSubscriptionState:
    stripe_customer_id: str | None
    stripe_subscription_id: str | None
    stripe_price_id: str | None
    status: str | None
    current_period_end: datetime | None
    cancel_at_period_end: bool | None
    plan_key: str | None


def _state_from_subscription_object(
    obj: Dict[str, Any],
    *,
    fallback: StripeSubscriptionState | None = None,
) -> StripeSubscriptionState:
    cust_id = obj.get("customer")
    sub_id = obj.get("id")
    status = (obj.get("status") or "").strip().lower() or None
    cpe = _ts_from_unix(obj.get("current_period_end"))
    cancel_flag = obj.get("cancel_at_period_end")
    items = obj.get("items", {}).get("data") or []
    price_id = None
    if items and isinstance(items, list):
        price = (items[0] or {}).get("price") or {}
        price_id = price.get("id") or None
    meta = obj.get("metadata") or {}
    plan_key = meta.get("plan_key") or (fallback.plan_key if fallback else None)
    fb = fallback
    return StripeSubscriptionState(
        stripe_customer_id=str(cust_id) if cust_id else (fb.stripe_customer_id if fb else None),
        stripe_subscription_id=str(sub_id) if sub_id else (fb.stripe_subscription_id if fb else None),
        stripe_price_id=str(price_id) if price_id else (fb.stripe_price_id if fb else None),
        status=status or (fb.status if fb else None),
        current_period_end=cpe or (fb.current_period_end if fb else None),
        cancel_at_period_end=bool(cancel_flag) if cancel_flag is not None else (fb.cancel_at_period_end if fb else None),
        plan_key=str(plan_key).strip() if plan_key else None,
    )


def resolve_cliente_id_for_webhook(
    *,
    event_type: str,
    event_object: Dict[str, Any],
    st: StripeSubscriptionState,
) -> Optional[str]:
    """
    Resolve tenant a partir de metadata, client_reference_id ou IDs Stripe já gravados em clientes.
    """
    from database.supabase_sq import supabase
    from database.models import Tables, ClienteModel

    if not isinstance(event_object, dict):
        event_object = {}

    meta = event_object.get("metadata") or {}
    if isinstance(meta, dict):
        cid = (meta.get("cliente_id") or "").strip()
        if cid:
            return cid

    if event_type == "checkout.session.completed":
        cref = (event_object.get("client_reference_id") or "").strip()
        if cref:
            return cref

    if supabase is None:
        return None

    sid = (st.stripe_subscription_id or event_object.get("subscription") or "").strip()
    if sid:
        try:
            r = (
                supabase.table(Tables.CLIENTES)
                .select(ClienteModel.ID)
                .eq("stripe_subscription_id", sid)
                .limit(1)
                .execute()
            )
            if r.data:
                return str(r.data[0].get(ClienteModel.ID) or "")
        except Exception:
            pass

    cust = (st.stripe_customer_id or event_object.get("customer") or "").strip()
    if cust:
        try:
            r = (
                supabase.table(Tables.CLIENTES)
                .select(ClienteModel.ID)
                .eq("stripe_customer_id", cust)
                .limit(1)
                .execute()
            )
            if r.data:
                return str(r.data[0].get(ClienteModel.ID) or "")
        except Exception:
            pass

    return None


def cliente_billing_patch(st: StripeSubscriptionState) -> Dict[str, Any]:
    """Campos para UPDATE em clientes — omite None para não apagar dados existentes."""
    from database.models import ClienteModel

    patch: Dict[str, Any] = {}
    if st.status:
        patch[getattr(ClienteModel, "BILLING_STATUS", "billing_status")] = st.status
    if st.current_period_end is not None:
        patch[getattr(ClienteModel, "BILLING_CURRENT_PERIOD_END", "billing_current_period_end")] = (
            st.current_period_end.isoformat()
        )
    if st.cancel_at_period_end is not None:
        patch[getattr(ClienteModel, "BILLING_CANCEL_AT_PERIOD_END", "billing_cancel_at_period_end")] = bool(
            st.cancel_at_period_end
        )
    if st.plan_key:
        patch[getattr(ClienteModel, "BILLING_PLAN_KEY", "billing_plan_key")] = st.plan_key
        patch[getattr(ClienteModel, "PLANO", "plano")] = st.plan_key
    if st.stripe_customer_id:
        patch["stripe_customer_id"] = st.stripe_customer_id
    if st.stripe_subscription_id:
        patch["stripe_subscription_id"] = st.stripe_subscription_id
    if st.stripe_price_id:
        patch["stripe_price_id"] = st.stripe_price_id
    return patch


def _coerce_status_after_paid_checkout(
    st: StripeSubscriptionState,
    checkout_object: Dict[str, Any],
) -> StripeSubscriptionState:
    """
    Se checkout foi pago mas retrieve da subscription falhou, não deixar pending eterno.
    """
    status = (st.status or "").strip().lower()
    if status not in ("", "pending"):
        return st
    paid = (checkout_object.get("payment_status") or "").strip().lower() == "paid"
    if paid and st.stripe_subscription_id:
        logger.warning(
            "checkout paid but subscription status unresolved sub=%s — forcing active",
            st.stripe_subscription_id,
        )
        return replace(st, status="active")
    return st


def sync_cliente_billing_from_stripe(cliente_id: str) -> Dict[str, Any]:
    """
    Reconcilia manualmente um cliente (pending pós-pagamento) consultando a Stripe API.
    """
    from database.supabase_sq import supabase
    from database.models import Tables, ClienteModel

    cid = (cliente_id or "").strip()
    if not cid or supabase is None:
        return {"ok": False, "erro": "supabase_or_cliente_missing"}

    try:
        r = (
            supabase.table(Tables.CLIENTES)
            .select(
                ",".join(
                    [
                        ClienteModel.ID,
                        "stripe_customer_id",
                        "stripe_subscription_id",
                        getattr(ClienteModel, "BILLING_STATUS", "billing_status"),
                    ]
                )
            )
            .eq(ClienteModel.ID, cid)
            .limit(1)
            .execute()
        )
        row = r.data[0] if r.data else None
    except Exception as e:
        return {"ok": False, "erro": str(e)}

    if not row:
        return {"ok": False, "erro": "cliente_not_found"}

    sub_id = (row.get("stripe_subscription_id") or "").strip()
    cust_id = (row.get("stripe_customer_id") or "").strip()

    if not sub_id and cust_id:
        _configure_stripe()
        try:
            subs = stripe.Subscription.list(customer=cust_id, status="all", limit=3)
            data = _stripe_attr(subs, "data") or []
            for s in data:
                sid = str(_stripe_attr(s, "id") or "")
                st_raw = (_stripe_attr(s, "status") or "").strip().lower()
                if sid and st_raw in ("active", "trialing", "past_due"):
                    sub_id = sid
                    break
            if not sub_id and data:
                sub_id = str(_stripe_attr(data[0], "id") or "")
        except StripeError as e:
            return {"ok": False, "erro": f"stripe_list_subscriptions:{e}"}

    if not sub_id:
        return {"ok": False, "erro": "no_stripe_subscription"}

    _configure_stripe()
    try:
        sub = stripe.Subscription.retrieve(sub_id)
        obj = sub.to_dict() if hasattr(sub, "to_dict") else dict(sub)
    except StripeError as e:
        return {"ok": False, "erro": f"stripe_retrieve:{e}"}

    st = finalize_subscription_state(_state_from_subscription_object(obj), fetch_subscription=False)
    patch = cliente_billing_patch(st)
    if not patch:
        return {"ok": False, "erro": "empty_patch"}

    supabase.table(Tables.CLIENTES).update(patch).eq(ClienteModel.ID, cid).execute()

    from services.billing.subscription_service import upsert_tenant_subscription

    upsert_tenant_subscription(
        cliente_id=cid,
        provider="stripe",
        provider_subscription_id=st.stripe_subscription_id,
        plan_key=st.plan_key,
        status=st.status,
        current_period_end=st.current_period_end.isoformat() if st.current_period_end else None,
    )

    return {"ok": True, "cliente_id": cid, "billing_status": st.status, "patch": patch}


def finalize_subscription_state(
    st: StripeSubscriptionState,
    *,
    fetch_subscription: bool = False,
) -> StripeSubscriptionState:
    """Enriquece estado: retrieve subscription + mapeia stripe_price_id → plan_key."""
    out = st
    if fetch_subscription and st.stripe_subscription_id:
        _configure_stripe()
        try:
            sub = stripe.Subscription.retrieve(st.stripe_subscription_id)
            if isinstance(sub, dict):
                obj = sub
            else:
                obj = sub.to_dict() if hasattr(sub, "to_dict") else dict(sub)
            out = _state_from_subscription_object(obj, fallback=out)
        except StripeError as e:
            logger.warning(
                "stripe subscription retrieve %s: %s",
                st.stripe_subscription_id,
                str(e)[:200],
            )
    if out.stripe_price_id and not out.plan_key:
        pk = plan_key_from_stripe_price_id(out.stripe_price_id)
        if pk:
            out = replace(out, plan_key=pk)
    return out


def parse_subscription_from_event(event: stripe.Event) -> StripeSubscriptionState:
    """
    Extrai estado canónico da assinatura a partir de eventos Stripe.
    """
    typ = str(event.get("type") or "")
    obj = event.get("data", {}).get("object", {}) or {}

    if typ == "checkout.session.completed":
        # obj é checkout.session
        sub_id = obj.get("subscription")
        cust_id = obj.get("customer")
        meta = obj.get("metadata") or {}
        plan_key = meta.get("plan_key") or None
        base = StripeSubscriptionState(
            stripe_customer_id=str(cust_id) if cust_id else None,
            stripe_subscription_id=str(sub_id) if sub_id else None,
            stripe_price_id=None,
            status="pending",
            current_period_end=None,
            cancel_at_period_end=None,
            plan_key=str(plan_key).strip() if plan_key else None,
        )
        out = finalize_subscription_state(base, fetch_subscription=bool(sub_id))
        return _coerce_status_after_paid_checkout(out, obj)

    if typ in ("customer.subscription.updated", "customer.subscription.deleted"):
        # obj é subscription
        cust_id = obj.get("customer")
        sub_id = obj.get("id")
        status = (obj.get("status") or "").strip().lower() or None
        cpe = _ts_from_unix(obj.get("current_period_end"))
        cancel_flag = obj.get("cancel_at_period_end")
        items = obj.get("items", {}).get("data") or []
        price_id = None
        if items and isinstance(items, list):
            price = (items[0] or {}).get("price") or {}
            price_id = price.get("id") or None
        meta = obj.get("metadata") or {}
        plan_key = meta.get("plan_key") or None
        base = StripeSubscriptionState(
            stripe_customer_id=str(cust_id) if cust_id else None,
            stripe_subscription_id=str(sub_id) if sub_id else None,
            stripe_price_id=str(price_id) if price_id else None,
            status=status,
            current_period_end=cpe,
            cancel_at_period_end=bool(cancel_flag) if cancel_flag is not None else None,
            plan_key=str(plan_key).strip() if plan_key else None,
        )
        return finalize_subscription_state(base)

    if typ in ("invoice.paid", "invoice.payment_failed"):
        cust_id = obj.get("customer")
        sub_id = obj.get("subscription")
        status = "active" if typ == "invoice.paid" else "past_due"
        cpe = _ts_from_unix(obj.get("current_period_end"))  # pode vir em invoice
        base = StripeSubscriptionState(
            stripe_customer_id=str(cust_id) if cust_id else None,
            stripe_subscription_id=str(sub_id) if sub_id else None,
            stripe_price_id=None,
            status=status,
            current_period_end=cpe,
            cancel_at_period_end=None,
            plan_key=None,
        )
        return finalize_subscription_state(base, fetch_subscription=bool(sub_id))

    return StripeSubscriptionState(
        stripe_customer_id=None,
        stripe_subscription_id=None,
        stripe_price_id=None,
        status=None,
        current_period_end=None,
        cancel_at_period_end=None,
        plan_key=None,
    )


def log_event_summary(event: stripe.Event) -> None:
    try:
        eid = str(event.get("id") or "")
        typ = str(event.get("type") or "")
        created = _ts_from_unix(event.get("created"))
        logger.info(
            "stripe webhook event received id=%s type=%s created=%s",
            eid,
            typ,
            created.isoformat() if created else None,
        )
    except Exception:
        return

