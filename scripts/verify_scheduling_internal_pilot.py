#!/usr/bin/env python3
"""
Checklist automatizado motor interno — valida BD (scheduling_engine), env e testes.

Após migration 028: fonte definitiva = scheduling_settings.scheduling_engine (admin ou script).
Allowlist .env = rede de segurança temporária (Fase 1–2).
"""
from __future__ import annotations

import os
import subprocess
import sys

_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _root not in sys.path:
    sys.path.insert(0, _root)

from base.config import settings


def _parse_csv(raw: str) -> list[str]:
    return [p.strip() for p in (raw or "").split(",") if p.strip()]


def main() -> int:
    issues: list[str] = []
    warnings: list[str] = []

    allowlist = (getattr(settings, "SCHEDULING_INTERNAL_CLIENTE_IDS", "") or "").strip()
    force = (getattr(settings, "SCHEDULING_FORCE_AGENDA_CLIENTE_IDS", "") or "").strip()

    print("Allowlist env (rede segurança):", allowlist or "(vazia)")
    print("Force Agenda env:", force or "(vazia)")
    print()

    internal_db: list[str] = []
    try:
        from database.supabase_sq import supabase
        from database.models import SchedulingSettingsModel, Tables

        if supabase:
            r = (
                supabase.table(Tables.SCHEDULING_SETTINGS)
                .select(SchedulingSettingsModel.CLIENTE_ID)
                .eq(SchedulingSettingsModel.SCHEDULING_ENGINE, "zapaction_internal")
                .execute()
            )
            internal_db = [
                str(row.get(SchedulingSettingsModel.CLIENTE_ID) or "")
                for row in (r.data or [])
                if row.get(SchedulingSettingsModel.CLIENTE_ID)
            ]
            print("Tenants zapaction_internal na BD:", internal_db or "(nenhum)")
        else:
            warnings.append("Supabase indisponível — não foi possível listar scheduling_engine na BD")
    except Exception as exc:
        warnings.append(f"Leitura BD scheduling_engine falhou: {exc}")

    allow_ids = _parse_csv(allowlist)
    for cid in allow_ids:
        if cid not in internal_db:
            warnings.append(
                f"Allowlist env tem {cid[:8]}… mas BD não está zapaction_internal "
                "(corra migrate_env_allowlist_to_db.py ou admin PATCH)"
            )
    for cid in internal_db:
        if allow_ids and cid not in allow_ids:
            warnings.append(
                f"BD interno {cid[:8]}… sem entrada na allowlist env (ok após Fase 3 limpeza env)"
            )

    if getattr(settings, "USE_INTERNAL_SCHEDULING", False) and not allowlist and not internal_db:
        issues.append("USE_INTERNAL_SCHEDULING=1 sem allowlist nem tenants na BD — risco global")

    if not internal_db and not allowlist:
        warnings.append(
            "Nenhum tenant no motor interno (BD ou env). Piloto: PATCH admin ou migrate script."
        )

    tests = [
        "tests.test_scheduling_engine_resolver",
        "tests.test_scheduling_internal_motor",
        "tests.test_scheduling_cancel_turn",
        "tests.test_agendamento_ia_urls",
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
        issues.append("Testes unitários falharam (ver saída abaixo)")
        print(proc.stdout)
        print(proc.stderr, file=sys.stderr)
    else:
        print("Testes unitários: OK")

    print()
    print("Ver: docs/scheduling_internal_rollout_runbook.md")

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
