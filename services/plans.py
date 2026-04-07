from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional, Tuple

from database.supabase_sq import supabase
from database.models import Tables, PlanModel, ClienteModel


def get_plan(plan_key: str) -> Optional[Dict[str, Any]]:
    if not supabase:
        return None
    key = (plan_key or "").strip()
    if not key:
        return None
    try:
        r = (
            supabase.table(Tables.PLANS)
            .select("*")
            .eq(PlanModel.PLAN_KEY, key)
            .limit(1)
            .execute()
        )
        return r.data[0] if r.data else None
    except Exception:
        return None


def list_active_plans() -> list[Dict[str, Any]]:
    if not supabase:
        return []
    try:
        r = (
            supabase.table(Tables.PLANS)
            .select("*")
            .eq(PlanModel.ACTIVE, True)
            .order(PlanModel.PRICE)
            .execute()
        )
        return r.data or []
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

