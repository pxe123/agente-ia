#!/usr/bin/env python3
"""
Migração P1: importa marcações do Agendamento IA e audita espelho no Supabase.

Uso (antes de ativar motor interno em cliente com histórico Agenda):

  python scripts/migrate_scheduling_from_agenda.py <cliente_uuid>
  python scripts/migrate_scheduling_from_agenda.py <cliente_uuid> --since-days 120
"""
from __future__ import annotations

import argparse
import os
import subprocess
import sys

_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _root not in sys.path:
    sys.path.insert(0, _root)

from services.agendamento_ia_appointments_import import sync_appointments_from_agenda


def main() -> int:
    parser = argparse.ArgumentParser(description="Import + auditoria Agenda → Supabase")
    parser.add_argument("cliente_id", help="UUID do cliente ZapAction")
    parser.add_argument("--since-days", type=int, default=90)
    parser.add_argument("--skip-import", action="store_true", help="Só auditar, sem import")
    args = parser.parse_args()
    cid = args.cliente_id.strip()

    if not args.skip_import:
        print(f"Importando marcações (últimos {args.since_days} dias)…")
        imported, err = sync_appointments_from_agenda(cid, since_days=args.since_days)
        if err and imported == 0:
            print(f"ERRO import: {err}")
            return 1
        print(f"Importados/atualizados: {imported}")
        if err:
            print(f"Aviso parcial: {err}")
        print()

    audit = subprocess.run(
        [sys.executable, os.path.join(_root, "scripts", "audit_scheduling_mirror.py"), cid,
         "--since-days", str(args.since_days)],
        cwd=_root,
    )
    return int(audit.returncode or 0)


if __name__ == "__main__":
    raise SystemExit(main())
