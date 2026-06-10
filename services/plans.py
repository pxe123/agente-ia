from __future__ import annotations

import time
from datetime import datetime, timedelta, timezone
from threading import Lock
from typing import Any, Dict, Optional, Tuple

from database.supabase_sq import supabase
from database.models import Tables, PlanModel, ClienteModel

# Tabela plans muda raramente; cache evita GET /rest/v1/plans em cada página do painel (paywall).
_PLANS_CACHE_TTL_SEC = int((__import__("os").getenv("PLANS_CACHE_TTL_SEC") or "120").strip() or "120")
_plans_cache: dict[str, tuple[float, Any]] = {}
_plans_cache_lock = Lock()

_PLANS_LIST_SELECT = (
    f"{PlanModel.PLAN_KEY},{PlanModel.NAME},{PlanModel.PRICE},{PlanModel.CURRENCY},"
    f"{PlanModel.TRIAL_DAYS},{PlanModel.ACTIVE},{PlanModel.ENTITLEMENTS_JSON},"
    f"{PlanModel.IS_PRIVATE},{PlanModel.PRIVATE_CLIENTE_ID},"
    f"{PlanModel.STRIPE_PRICE_ID},{PlanModel.STRIPE_PRODUCT_ID}"
)


def invalidate_plans_cache() -> None:
    """Chamar após criar/editar/remover planos no admin."""
    with _plans_cache_lock:
        _plans_cache.clear()


def _cache_get(key: str) -> Any:
    now = time.monotonic()
    with _plans_cache_lock:
        entry = _plans_cache.get(key)
        if entry and entry[0] > now:
            return entry[1]
    return None


def _cache_set(key: str, value: Any) -> None:
    with _plans_cache_lock:
        _plans_cache[key] = (time.monotonic() + _PLANS_CACHE_TTL_SEC, value)


def get_plan(plan_key: str) -> Optional[Dict[str, Any]]:
    if not supabase:
        return None
    key = (plan_key or "").strip()
    if not key:
        return None
    cache_key = f"plan:{key}"
    cached = _cache_get(cache_key)
    if cached is not None:
        return cached
    try:
        r = (
            supabase.table(Tables.PLANS)
            .select(_PLANS_LIST_SELECT)
            .eq(PlanModel.PLAN_KEY, key)
            .limit(1)
            .execute()
        )
        row = r.data[0] if r.data else None
        _cache_set(cache_key, row)
        return row
    except Exception:
        # Compat: colunas stripe_* ainda não migradas
        try:
            r = (
                supabase.table(Tables.PLANS)
                .select(
                    f"{PlanModel.PLAN_KEY},{PlanModel.NAME},{PlanModel.PRICE},{PlanModel.CURRENCY},"
                    f"{PlanModel.TRIAL_DAYS},{PlanModel.ACTIVE},{PlanModel.ENTITLEMENTS_JSON},"
                    f"{PlanModel.IS_PRIVATE},{PlanModel.PRIVATE_CLIENTE_ID}"
                )
                .eq(PlanModel.PLAN_KEY, key)
                .limit(1)
                .execute()
            )
            row = r.data[0] if r.data else None
            _cache_set(cache_key, row)
            return row
        except Exception:
            return None


def get_plan_by_stripe_price_id(stripe_price_id: str) -> Optional[Dict[str, Any]]:
    """Resolve plan_key a partir do Price ID Stripe (webhook)."""
    pid = (stripe_price_id or "").strip()
    if not supabase or not pid:
        return None
    cache_key = f"stripe_price:{pid}"
    cached = _cache_get(cache_key)
    if cached is not None:
        return cached
    try:
        r = (
            supabase.table(Tables.PLANS)
            .select(_PLANS_LIST_SELECT)
            .eq(PlanModel.STRIPE_PRICE_ID, pid)
            .limit(1)
            .execute()
        )
        row = r.data[0] if r.data else None
        _cache_set(cache_key, row)
        return row
    except Exception:
        return None


def plan_key_from_stripe_price_id(stripe_price_id: str) -> Optional[str]:
    row = get_plan_by_stripe_price_id(stripe_price_id)
    if not row:
        return None
    pk = (row.get(PlanModel.PLAN_KEY) or "").strip()
    return pk or None


def plan_is_available_to_cliente(plan: Optional[Dict[str, Any]], cliente_id: Optional[str] = None) -> bool:
    if not plan:
        return False
    if not bool(plan.get(getattr(PlanModel, "IS_PRIVATE", "is_private"))):
        return True
    allowed_id = str(plan.get(getattr(PlanModel, "PRIVATE_CLIENTE_ID", "private_cliente_id")) or "").strip()
    return bool(cliente_id and allowed_id and allowed_id == str(cliente_id).strip())


def get_plan_for_cliente(plan_key: str, cliente_id: Optional[str] = None) -> Optional[Dict[str, Any]]:
    plan = get_plan(plan_key)
    if not plan_is_available_to_cliente(plan, cliente_id):
        return None
    return plan


def list_active_plans(cliente_id: Optional[str] = None, include_private: bool = False) -> list[Dict[str, Any]]:
    if not supabase:
        return []
    cache_key = f"list:{cliente_id or ''}:{int(include_private)}"
    cached = _cache_get(cache_key)
    if cached is not None:
        return cached
    try:
        r = (
            supabase.table(Tables.PLANS)
            .select(_PLANS_LIST_SELECT)
            .eq(PlanModel.ACTIVE, True)
            .order(PlanModel.PRICE)
            .execute()
        )
        rows = r.data or []
        if include_private and cliente_id:
            out = [
                p
                for p in rows
                if (
                    not bool(p.get(getattr(PlanModel, "IS_PRIVATE", "is_private")))
                    or plan_is_available_to_cliente(p, cliente_id)
                )
            ]
        else:
            out = [p for p in rows if not bool(p.get(getattr(PlanModel, "IS_PRIVATE", "is_private")))]
        _cache_set(cache_key, out)
        return out
    except Exception:
        try:
            r = (
                supabase.table(Tables.PLANS)
                .select(
                    f"{PlanModel.PLAN_KEY},{PlanModel.NAME},{PlanModel.PRICE},{PlanModel.CURRENCY},"
                    f"{PlanModel.TRIAL_DAYS},{PlanModel.ACTIVE},{PlanModel.ENTITLEMENTS_JSON},"
                    f"{PlanModel.IS_PRIVATE},{PlanModel.PRIVATE_CLIENTE_ID}"
                )
                .eq(PlanModel.ACTIVE, True)
                .order(PlanModel.PRICE)
                .execute()
            )
            rows = r.data or []
            out = [p for p in rows if not bool(p.get(getattr(PlanModel, "IS_PRIVATE", "is_private")))]
            _cache_set(cache_key, out)
            return out
        except Exception:
            return []


def plan_price(plan_key: str) -> Tuple[Optional[float], str]:
    plan = get_plan(plan_key)
    if not plan:
        return None, "BRL"
    try:
        price = float(plan.get(PlanModel.PRICE) or 0)
    except Exception:
        price = 0.0
    currency = (plan.get(PlanModel.CURRENCY) or "BRL").strip() or "BRL"
    return price, currency


def plan_price_for_cliente(plan_key: str, cliente_id: Optional[str] = None) -> Tuple[Optional[float], str]:
    plan = get_plan_for_cliente(plan_key, cliente_id)
    if not plan:
        return None, "BRL"
    try:
        price = float(plan.get(PlanModel.PRICE) or 0)
    except Exception:
        price = 0.0
    currency = (plan.get(PlanModel.CURRENCY) or "BRL").strip() or "BRL"
    return price, currency


def plan_trial_ends_at(plan_key: str) -> Optional[str]:
    plan = get_plan(plan_key)
    if not plan:
        return None
    try:
        days = int(plan.get(PlanModel.TRIAL_DAYS) or 0)
    except Exception:
        days = 0
    if days <= 0:
        return None
    dt = datetime.now(timezone.utc) + timedelta(days=days)
    return dt.isoformat()


def plan_entitlements(plan_key: str) -> Dict[str, Any]:
    plan = get_plan(plan_key)
    if not plan:
        return {}
    ent = plan.get(PlanModel.ENTITLEMENTS_JSON) or {}
    return ent if isinstance(ent, dict) else {}


def cliente_acesso_flags_for_plan(plan_key: str) -> Dict[str, Any]:
    """
    Mapeia entitlements_json do plano para colunas acesso_* em clientes.
    Mesma regra do cadastro público (public.py), centralizada aqui para billing/webhook.
    """
    ent = plan_entitlements(plan_key)
    return {
        ClienteModel.ACESSO_WHATSAPP: bool(ent.get("whatsapp", True)),
        ClienteModel.ACESSO_INSTAGRAM: bool(ent.get("instagram", True)),
        ClienteModel.ACESSO_MESSENGER: bool(ent.get("messenger", True)),
        ClienteModel.ACESSO_SITE: bool(ent.get("site", True)),
    }

