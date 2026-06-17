#!/usr/bin/env python3
"""
Checklist — Bloqueios de horário (motor interno ZapAction).

Uso (Linux/servidor: python3; Windows: python ou py):
  python3 scripts/verify_scheduling_blocks.py
  python3 scripts/verify_scheduling_blocks.py --cliente-id UUID
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
    parser = argparse.ArgumentParser(description="Verificar bloqueios de horário (motor interno)")
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
        from database.models import SchedulingBlockedTimeModel, SchedulingSettingsModel, Tables
        from database.supabase_sq import supabase
        from services.scheduling.blocks import block_scope, validate_block_interval
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
                tz = st.get(SchedulingSettingsModel.TIMEZONE) or "America/Sao_Paulo"
                print("scheduling_engine:", engine)
                print("timezone:", tz)
                uses_internal = scheduling_uses_internal_motor(cid)
                print("scheduling_uses_internal_motor:", uses_internal)
                if not uses_internal:
                    warnings.append(
                        "Tenant usa motor externo — bloqueios no painel devolvem motor_externo (esperado)"
                    )
                else:
                    print("OK: motor interno — bloqueios activos no painel")

                blocks = (
                    supabase.table(Tables.SCHEDULING_BLOCKED_TIMES)
                    .select("id, professional_id, starts_at, ends_at, reason")
                    .eq(SchedulingBlockedTimeModel.CLIENTE_ID, cid)
                    .order("starts_at", desc=True)
                    .limit(5)
                    .execute()
                    .data
                    or []
                )
                print("Últimos bloqueios (máx. 5):", len(blocks))
                for b in blocks:
                    pid = b.get("professional_id")
                    scope = block_scope(str(pid) if pid else None)
                    print(
                        f"  - {b.get('id', '')[:8]}… scope={scope} "
                        f"{b.get('starts_at')} → {b.get('ends_at')} "
                        f"reason={b.get('reason') or '-'}"
                    )

        # Smoke helpers
        from datetime import datetime, timezone

        a = datetime(2026, 6, 15, 10, 0, tzinfo=timezone.utc)
        b = datetime(2026, 6, 15, 12, 0, tzinfo=timezone.utc)
        if validate_block_interval(a, b) is not None:
            issues.append("validate_block_interval smoke falhou")

        print()
        print("Testes unitários…")
        r = subprocess.run(
            [sys.executable, "-m", "unittest", "tests.test_scheduling_blocks", "-q"],
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
    print("Checklist bloqueios: OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
