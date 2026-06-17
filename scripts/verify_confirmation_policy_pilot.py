#!/usr/bin/env python3
"""
Checklist piloto — Confirmação de Agendamento (migration 030 + motor interno).

Uso (Linux/servidor: python3; Windows: python ou py):
  python3 scripts/verify_confirmation_policy_pilot.py
  python3 scripts/verify_confirmation_policy_pilot.py --cliente-id UUID
"""
from __future__ import annotations

import argparse
import os
import subprocess
import sys

_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _root not in sys.path:
    sys.path.insert(0, _root)


def main() -> int:
    parser = argparse.ArgumentParser(description="Verificar piloto confirmação de agendamento")
    parser.add_argument(
        "--cliente-id",
        default="d1ddf96e-e667-48dc-9975-362a9c539fe2",
        help="Tenant piloto (default: clinica-teste homologação)",
    )
    args = parser.parse_args()
    cid = (args.cliente_id or "").strip()
    issues: list[str] = []
    warnings: list[str] = []

    print("Tenant piloto:", cid or "(não indicado)")
    print()

    try:
        from database.models import SchedulingSettingsModel, Tables
        from database.supabase_sq import supabase
        from services.scheduling.confirmation_policy import (
            get_confirmation_policy,
            requires_professional_confirmation,
            resolve_initial_appointment_status,
        )
        from services.scheduling.engine import scheduling_uses_internal_motor

        if not supabase:
            issues.append("Supabase indisponível")
        else:
            row = (
                supabase.table(Tables.SCHEDULING_SETTINGS)
                .select("*")
                .eq(SchedulingSettingsModel.CLIENTE_ID, cid)
                .limit(1)
                .execute()
                .data
            )
            st = row[0] if row else None
            if not st:
                issues.append(f"scheduling_settings ausente para {cid[:8]}…")
            else:
                policy = st.get(SchedulingSettingsModel.CONFIRMATION_POLICY) or "auto"
                ttl = st.get(SchedulingSettingsModel.CONFIRMATION_PENDING_TTL_HOURS) or 48
                engine = st.get(SchedulingSettingsModel.SCHEDULING_ENGINE) or "agendamento_ia"
                print("scheduling_engine:", engine)
                print("confirmation_policy (DB):", policy)
                print("confirmation_pending_ttl_hours:", ttl)
                print("resolve_initial_appointment_status:", resolve_initial_appointment_status(cid))
                print("requires_professional_confirmation:", requires_professional_confirmation(cid))
                if policy == "professional" and not scheduling_uses_internal_motor(cid):
                    issues.append("confirmation_policy=professional com motor externo (incohérente)")
                if policy == "professional" and scheduling_uses_internal_motor(cid):
                    print("OK: política professional com motor interno")

        print()
        print("Testes unitários…")
        r = subprocess.run(
            [
                sys.executable,
                "-m",
                "unittest",
                "tests.test_scheduling_confirmation_policy",
                "tests.test_scheduling_proposals",
                "-q",
            ],
            cwd=_root,
            capture_output=True,
            text=True,
        )
        if r.returncode != 0:
            issues.append("testes unitários falharam")
            print(r.stdout)
            print(r.stderr)
        else:
            print("Testes OK")

    except Exception as e:
        issues.append(f"erro: {e}")

    print()
    if warnings:
        print("Avisos:")
        for w in warnings:
            print(" -", w)
    if issues:
        print("Problemas:")
        for i in issues:
            print(" -", i)
        return 1
    print("Checklist piloto: OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
