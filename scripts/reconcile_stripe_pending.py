#!/usr/bin/env python3
"""
Reconcilia clientes com billing_status=pending que já pagaram na Stripe.

Uso:
  python scripts/reconcile_stripe_pending.py
  python scripts/reconcile_stripe_pending.py --cliente-id <uuid>
  python scripts/reconcile_stripe_pending.py --dry-run
"""
from __future__ import annotations

import argparse
import os
import sys

_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _root not in sys.path:
    sys.path.insert(0, _root)

from billing.stripe_service import sync_cliente_billing_from_stripe
from database.models import ClienteModel, Tables
from database.supabase_sq import supabase


def _list_pending_clientes() -> list[dict]:
    if supabase is None:
        return []
    cols = ",".join(
        [
            ClienteModel.ID,
            ClienteModel.EMAIL,
            getattr(ClienteModel, "BILLING_STATUS", "billing_status"),
            "stripe_customer_id",
            "stripe_subscription_id",
        ]
    )
    r = (
        supabase.table(Tables.CLIENTES)
        .select(cols)
        .eq(getattr(ClienteModel, "BILLING_STATUS", "billing_status"), "pending")
        .execute()
    )
    return list(r.data or [])


def main() -> int:
    parser = argparse.ArgumentParser(description="Reconcilia billing Stripe pending → active")
    parser.add_argument("--cliente-id", help="UUID de um cliente específico")
    parser.add_argument("--dry-run", action="store_true", help="Só lista, não atualiza")
    args = parser.parse_args()

    if supabase is None:
        print("ERRO: Supabase indisponível")
        return 1

    if args.cliente_id:
        targets = [{"id": args.cliente_id.strip()}]
    else:
        targets = _list_pending_clientes()

    if not targets:
        print("Nenhum cliente pending encontrado.")
        return 0

    ok = 0
    fail = 0
    for row in targets:
        cid = str(row.get(ClienteModel.ID) or row.get("id") or "").strip()
        if not cid:
            continue
        email = row.get(ClienteModel.EMAIL) or ""
        print(f"\n--- {cid} {email}".strip())

        if args.dry_run:
            print("  (dry-run) seria reconciliado")
            continue

        result = sync_cliente_billing_from_stripe(cid)
        if result.get("ok"):
            ok += 1
            print(f"  OK → billing_status={result.get('billing_status')}")
        else:
            fail += 1
            print(f"  FALHA: {result.get('erro')}")

    print(f"\nConcluído: {ok} ok, {fail} falha(s)")
    return 0 if fail == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
