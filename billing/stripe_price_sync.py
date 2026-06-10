from __future__ import annotations

import logging
from typing import Any, Dict, Optional, Tuple

import stripe
from stripe import StripeError

from base.config import settings
from database.models import PlanModel, Tables
from database.supabase_sq import supabase
from services.plans import get_plan, invalidate_plans_cache

logger = logging.getLogger(__name__)


def _stripe_attr(obj: Any, key: str, default: Any = None) -> Any:
    if obj is None:
        return default
    if isinstance(obj, dict):
        return obj.get(key, default)
    try:
        return obj[key]
    except (KeyError, TypeError):
        return getattr(obj, key, default)


def _configure_stripe() -> None:
    key = (getattr(settings, "STRIPE_SECRET_KEY", "") or "").strip()
    if key:
        stripe.api_key = key


def _stripe_enabled() -> bool:
    return bool((getattr(settings, "STRIPE_SECRET_KEY", "") or "").strip())


def assert_stripe_price_id(price_id: str, *, source: str) -> None:
    pid = (price_id or "").strip()
    if not pid:
        raise ValueError(f"stripe_price_not_configured:{source}")
    if pid.startswith("prod_"):
        raise ValueError(f"stripe_price_invalid:{source}: use Price ID (price_...), não Product ID")
    if not pid.startswith("price_"):
        raise ValueError(f"stripe_price_invalid:{source}: valor deve começar com price_")


def _amount_cents(price: float, currency: str) -> int:
    cur = (currency or "BRL").strip().upper()
    if cur in ("BRL", "USD", "EUR"):
        return max(0, int(round(float(price) * 100)))
    return max(0, int(round(float(price) * 100)))


def persist_plan_stripe_ids(
    plan_key: str,
    *,
    stripe_price_id: str,
    stripe_product_id: str | None = None,
) -> None:
    if not supabase or not (plan_key or "").strip():
        return
    payload: Dict[str, Any] = {PlanModel.STRIPE_PRICE_ID: stripe_price_id}
    if stripe_product_id:
        payload[PlanModel.STRIPE_PRODUCT_ID] = stripe_product_id
    try:
        supabase.table(Tables.PLANS).update(payload).eq(PlanModel.PLAN_KEY, plan_key).execute()
        invalidate_plans_cache()
    except Exception as e:
        logger.warning("persist_plan_stripe_ids %s: %s", plan_key, e)


def create_stripe_price_for_plan(plan: Dict[str, Any]) -> Tuple[str, str]:
    """Cria Product (se necessário) e Price recorrente mensal a partir da linha plans."""
    _configure_stripe()
    if not _stripe_enabled():
        raise ValueError("stripe_not_configured")

    plan_key = (plan.get(PlanModel.PLAN_KEY) or "").strip()
    name = (plan.get(PlanModel.NAME) or plan_key or "Plano").strip()
    currency = ((plan.get(PlanModel.CURRENCY) or "BRL").strip() or "BRL").lower()
    try:
        price_val = float(plan.get(PlanModel.PRICE) or 0)
    except (TypeError, ValueError):
        price_val = 0.0
    if price_val <= 0:
        raise ValueError(f"plan_price_invalid:{plan_key}")

    product_id = (plan.get(PlanModel.STRIPE_PRODUCT_ID) or "").strip()
    if product_id:
        try:
            existing = stripe.Product.retrieve(product_id)
            if _stripe_attr(existing, "deleted"):
                product_id = ""
        except StripeError:
            product_id = ""

    if not product_id:
        prod = stripe.Product.create(
            name=name,
            metadata={"plan_key": plan_key},
        )
        product_id = str(_stripe_attr(prod, "id") or "")

    price = stripe.Price.create(
        product=product_id,
        unit_amount=_amount_cents(price_val, currency),
        currency=currency,
        recurring={"interval": "month"},
        metadata={"plan_key": plan_key},
    )
    price_id = str(_stripe_attr(price, "id") or "")
    if not price_id:
        raise ValueError("stripe_price_create_failed")
    return price_id, product_id


def ensure_stripe_price_for_plan(plan_key: str) -> str:
    """
    Resolve Price ID para checkout: plans.stripe_price_id ou cria na Stripe a partir de plans.price.
    """
    plan = get_plan(plan_key)
    if not plan:
        raise ValueError(f"unknown_plan_key:{plan_key}")

    existing = (plan.get(PlanModel.STRIPE_PRICE_ID) or "").strip()
    if existing:
        assert_stripe_price_id(existing, source=f"plans.{plan_key}.stripe_price_id")
        return existing

    price_id, product_id = create_stripe_price_for_plan(plan)
    persist_plan_stripe_ids(plan_key, stripe_price_id=price_id, stripe_product_id=product_id)
    return price_id


def sync_stripe_price_for_plan(plan_key: str, *, price_changed: bool = False) -> Optional[str]:
    """
    Admin: ao alterar preço/nome, cria novo Price na Stripe (Prices são imutáveis).
    """
    if not _stripe_enabled():
        return None
    plan = get_plan(plan_key)
    if not plan:
        return None
    if not price_changed:
        try:
            return ensure_stripe_price_for_plan(plan_key)
        except ValueError:
            return None
    try:
        price_id, product_id = create_stripe_price_for_plan(plan)
        persist_plan_stripe_ids(plan_key, stripe_price_id=price_id, stripe_product_id=product_id)
        return price_id
    except Exception as e:
        logger.warning("sync_stripe_price_for_plan %s: %s", plan_key, e)
        return None
