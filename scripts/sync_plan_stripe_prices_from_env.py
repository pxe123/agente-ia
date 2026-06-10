#!/usr/bin/env python3
"""
Migração one-shot: copia STRIPE_PRICE_* legados do .env para plans.stripe_price_id.

Use antes de remover STRIPE_PRICE_* do .env (após deploy da migration 029).
Requer STRIPE_PRICE_STARTER/PRO/BUSINESS ainda presentes no ambiente.
"""
from __future__ import annotations

import os
import sys

_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _root not in sys.path:
    sys.path.insert(0, _root)

from base.config import settings
from billing.models import normalize_plan_key
from billing.stripe_price_sync import assert_stripe_price_id, persist_plan_stripe_ids
from database.models import PlanModel, Tables
from database.supabase_sq import supabase
from services.plans import invalidate_plans_cache, list_active_plans


def _env_for_tier(tier: str) -> str:
    tier = (tier or "").strip().lower()
    if tier == "starter":
        return (os.getenv("STRIPE_PRICE_STARTER") or getattr(settings, "STRIPE_PRICE_STARTER", "") or "").strip()
    if tier == "pro":
        return (os.getenv("STRIPE_PRICE_PRO") or getattr(settings, "STRIPE_PRICE_PRO", "") or "").strip()
    if tier == "business":
        return (os.getenv("STRIPE_PRICE_BUSINESS") or getattr(settings, "STRIPE_PRICE_BUSINESS", "") or "").strip()
    return ""


def main() -> int:
    if supabase is None:
        print("ERRO: Supabase não configurado")
        return 1

    updated = 0
    for plan in list_active_plans():
        pk = (plan.get(PlanModel.PLAN_KEY) or "").strip()
        if not pk:
            continue
        existing = (plan.get(PlanModel.STRIPE_PRICE_ID) or "").strip()
        if existing:
            print(f"  {pk}: já tem {existing[:20]}...")
            continue
        tier = normalize_plan_key(pk)
        env_pid = _env_for_tier(tier)
        if not env_pid:
            print(f"  {pk}: sem env fallback (tier={tier})")
            continue
        try:
            assert_stripe_price_id(env_pid, source=f"env.{tier}")
        except ValueError as e:
            print(f"  {pk}: env inválido — {e}")
            continue
        persist_plan_stripe_ids(pk, stripe_price_id=env_pid)
        print(f"  {pk}: gravado {env_pid}")
        updated += 1

    invalidate_plans_cache()
    print(f"\nOK: {updated} plano(s) atualizado(s).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
