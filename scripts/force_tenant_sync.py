#!/usr/bin/env python3
"""Força snapshot ZapAction -> Agenda IA (uso em servidor ou local)."""
from __future__ import annotations

import argparse
import os
import sys

_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _root not in sys.path:
    sys.path.insert(0, _root)


def main() -> int:
    parser = argparse.ArgumentParser(description="Forçar tenant snapshot para Agenda IA")
    parser.add_argument("--cliente-id", required=True)
    args = parser.parse_args()
    cid = args.cliente_id.strip()
    from services.agendamento_ia_sync import (
        build_tenant_snapshot_payload,
        push_tenant_snapshot_to_agendamento_ia,
    )

    payload = build_tenant_snapshot_payload(cid)
    if not payload:
        print("ERRO: payload vazio (Supabase?)")
        return 1
    clinic = payload.get("clinic") or {}
    print(
        "payload clinic:",
        clinic.get("public_name"),
        clinic.get("professional_assignment_mode"),
        clinic.get("confirmation_policy"),
    )
    ok, err, _ = push_tenant_snapshot_to_agendamento_ia(cid)
    print("sync ok:", ok, "err:", err)
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
