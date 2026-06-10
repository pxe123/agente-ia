#!/usr/bin/env python3
"""
Backfill scheduling_settings.scheduling_engine a partir do .env (allowlist / force).

Uso:
  python3 scripts/migrate_env_allowlist_to_db.py
  python3 scripts/migrate_env_allowlist_to_db.py --dry-run
"""
from __future__ import annotations

import argparse
import os
import sys

_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _root not in sys.path:
    sys.path.insert(0, _root)

from base.config import settings
from services.scheduling.engine import (
    ENGINE_AGENDAMENTO_IA,
    ENGINE_ZAPACTION_INTERNAL,
    set_scheduling_engine,
)


def _parse_csv(raw: str) -> list[str]:
    return [p.strip() for p in (raw or "").split(",") if p.strip()]


def main() -> int:
    parser = argparse.ArgumentParser(description="Migrar allowlist env → scheduling_engine na BD")
    parser.add_argument("--dry-run", action="store_true", help="Só imprimir, sem gravar")
    args = parser.parse_args()

    internal = _parse_csv(getattr(settings, "SCHEDULING_INTERNAL_CLIENTE_IDS", ""))
    force = _parse_csv(getattr(settings, "SCHEDULING_FORCE_AGENDA_CLIENTE_IDS", ""))

    if not internal and not force:
        print("Nada a migrar: allowlist e force list vazias no .env")
        return 0

    print("Allowlist (→ zapaction_internal):", internal or "(vazia)")
    print("Force Agenda (→ agendamento_ia):", force or "(vazia)")
    print()

    changed_by = "migration_script"
    errors = 0

    for cid in internal:
        if args.dry_run:
            print(f"[dry-run] {cid} → {ENGINE_ZAPACTION_INTERNAL}")
            continue
        ok, err = set_scheduling_engine(cid, ENGINE_ZAPACTION_INTERNAL, changed_by=changed_by)
        if ok:
            print(f"OK {cid} → {ENGINE_ZAPACTION_INTERNAL}")
        else:
            print(f"ERRO {cid}: {err}")
            errors += 1

    for cid in force:
        if args.dry_run:
            print(f"[dry-run] {cid} → {ENGINE_AGENDAMENTO_IA}")
            continue
        ok, err = set_scheduling_engine(cid, ENGINE_AGENDAMENTO_IA, changed_by=changed_by)
        if ok:
            print(f"OK {cid} → {ENGINE_AGENDAMENTO_IA}")
        else:
            print(f"ERRO {cid}: {err}")
            errors += 1

    print()
    if args.dry_run:
        print("Dry-run concluído. Execute sem --dry-run para gravar.")
        return 0
    if errors:
        print(f"Concluído com {errors} erro(s).")
        return 1
    print("Migração concluída. Valide com:")
    print("  python3 -c \"from services.scheduling.engine import scheduling_uses_internal_motor as m; ...\"")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
