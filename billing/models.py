from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class StripePriceMap:
    """Legado — removido do fluxo de checkout; mantido só para scripts de migração one-shot."""
    starter: str
    pro: str
    business: str


def normalize_plan_key(plan_key: str) -> str:
    """
    Normaliza plan_key vindos do frontend.

    Compat:
    - legado: social/profissional/empresa
    - novo: starter/pro/business
    """
    k = (plan_key or "").strip().lower()
    # Compat: chaves vistas no catálogo Stripe / UI
    # - start/master (português/curto)
    # - plan_test (ambiente antigo de testes)
    if k in ("start", "starter_plan", "plan_start"):
        return "starter"
    if k in ("plan_pro",):
        return "pro"
    if k in ("master", "business_plan", "plan_master"):
        return "business"
    if k in ("plan_test", "test", "teste"):
        return "starter"
    if k in ("starter", "pro", "business"):
        return k
    if k == "social":
        return "starter"
    if k == "profissional":
        return "pro"
    if k == "empresa":
        return "business"
    return k

