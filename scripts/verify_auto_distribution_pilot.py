#!/usr/bin/env python3
"""
Checklist piloto — Distribuição Automática (migration 029 + motor interno).

Uso:
  python scripts/verify_auto_distribution_pilot.py
  python scripts/verify_auto_distribution_pilot.py --cliente-id UUID
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
    parser = argparse.ArgumentParser(description="Verificar piloto distribuição automática")
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
        from services.scheduling.assignment import uses_auto_distribution
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
                engine = st.get(SchedulingSettingsModel.SCHEDULING_ENGINE) or "agendamento_ia"
                mode = st.get(SchedulingSettingsModel.PROFESSIONAL_ASSIGNMENT_MODE) or "manual"
                strat = st.get(SchedulingSettingsModel.DISTRIBUTION_STRATEGY) or "round_robin"
                print("scheduling_engine:", engine)
                print("professional_assignment_mode:", mode)
                print("distribution_strategy:", strat)
                if engine != "zapaction_internal":
                    warnings.append(
                        "Motor não é zapaction_internal — distribuição automática só funciona no motor interno"
                    )
                if mode == "auto_distribution" and engine != "zapaction_internal":
                    issues.append("auto_distribution activo mas motor externo")
                if not scheduling_uses_internal_motor(cid):
                    warnings.append("scheduling_uses_internal_motor=False para este tenant")
                print("uses_auto_distribution():", uses_auto_distribution(cid))
    except Exception as exc:
        issues.append(f"Leitura BD falhou: {exc}")

    tests = [
        "tests.test_scheduling_assignment",
        "tests.test_scheduling_pool_slots",
        "tests.test_scheduling_engine_resolver",
        "tests.test_scheduling_slot_engine",
    ]
    print()
    print("A correr testes unitários…")
    proc = subprocess.run(
        [sys.executable, "-m", "unittest", *tests, "-q"],
        cwd=_root,
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0:
        issues.append("Testes unitários falharam")
        print(proc.stdout)
        print(proc.stderr, file=sys.stderr)
    else:
        print("Testes unitários: OK")

    print()
    print("Ver: docs/scheduling_auto_distribution_runbook.md")
    print("Migration: database/migrations/029_professional_assignment_mode.sql")

    if warnings:
        print()
        print("NOTAS:")
        for w in warnings:
            print(" -", w)

    if issues:
        print()
        print("AVISOS:")
        for i in issues:
            print(" -", i)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
