#!/usr/bin/env python3
"""Valida Stripe + planos (plans.stripe_price_id no Supabase)."""
from __future__ import annotations

import os
import sys

_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _root not in sys.path:
    sys.path.insert(0, _root)

from base.config import settings
from billing.stripe_service import _stripe_attr, stripe_env_diagnostics
from database.models import PlanModel
from services.plans import list_active_plans


def main() -> int:
    diag = stripe_env_diagnostics()
    print("=== Stripe env (servidor) ===")
    for k, v in diag.items():
        if k != "prices":
            print(f"  {k}: {v}")
    print("  prices (plans.stripe_price_id):")
    for pk, status in (diag.get("prices") or {}).items():
        print(f"    {pk}: {status}")

    secret = (getattr(settings, "STRIPE_SECRET_KEY", "") or "").strip()
    if not secret:
        print("\nERRO: STRIPE_SECRET_KEY vazio")
        return 1

    mode = "test" if secret.startswith("sk_test_") else "live" if secret.startswith("sk_live_") else "?"
    print(f"\nModo da chave: {mode}")

    try:
        import stripe

        stripe.api_key = secret
        for plan in list_active_plans():
            pk = (plan.get(PlanModel.PLAN_KEY) or "").strip()
            if not pk:
                continue
            price_id = (plan.get(PlanModel.STRIPE_PRICE_ID) or "").strip()
            if not price_id:
                print(f"  {pk}: (sem stripe_price_id — será criado no checkout ou admin sync)")
                continue
            try:
                p = stripe.Price.retrieve(price_id)
                active = bool(_stripe_attr(p, "active"))
                product = _stripe_attr(p, "product")
                amount = _stripe_attr(p, "unit_amount")
                currency = _stripe_attr(p, "currency")
                print(
                    f"  {pk} {price_id}: active={active} product={product} "
                    f"amount={amount} {currency}"
                )
            except stripe.StripeError as e:
                print(f"  {pk} {price_id}: ERRO API — {e}")
    except ImportError:
        print("Pacote stripe não instalado (pip install stripe)")

    if not diag.get("ready"):
        print("\nAVISO: nem todos os planos/URLs estão OK (checkout pode criar Price na 1ª venda).")
    if not diag.get("webhook_secret_set"):
        print("\nAVISO: STRIPE_WEBHOOK_SECRET vazio — checkout funciona, mas assinatura não atualiza após pagamento.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
