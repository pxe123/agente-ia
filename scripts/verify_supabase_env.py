#!/usr/bin/env python3
"""Valida presença das variáveis Supabase (sem imprimir chaves)."""
from __future__ import annotations

import os
import sys

_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _root not in sys.path:
    sys.path.insert(0, _root)

from base.config import settings, ENV_FILE_PATH
from database.supabase_sq import supabase, supabase_public, supabase_config_diagnostics


def main() -> int:
    print("=== Supabase env ===")
    print(f"  .env path: {ENV_FILE_PATH}")
    print(f"  .env exists: {os.path.isfile(ENV_FILE_PATH)}")
    diag = supabase_config_diagnostics()
    for k, v in diag.items():
        print(f"  {k}: {v}")
    print(f"  supabase (service) client: {'OK' if supabase else 'FALHOU'}")
    print(f"  supabase_public (anon) client: {'OK' if supabase_public else 'FALHOU'}")

    ok = True
    if not diag.get("url_set"):
        print("\nERRO: SUPABASE_URL vazia")
        ok = False
    if not diag.get("service_key_set") or (diag.get("service_key_len") or 0) < 20:
        print("ERRO: SUPABASE_KEY (service role) ausente ou curta demais")
        ok = False
    if not diag.get("anon_key_set") or (diag.get("anon_key_len") or 0) < 20:
        print("ERRO: SUPABASE_ANON_KEY ausente ou curta — login retorna 503 ou Supabase 'No API key'")
        ok = False
    if not supabase:
        print("ERRO: cliente service role não inicializou (veja logs acima)")
        ok = False
    if not supabase_public:
        print("ERRO: cliente anon não inicializou — configure SUPABASE_ANON_KEY e reinicie o serviço")
        ok = False

    if ok:
        print("\nOK: variáveis e clientes Supabase presentes.")
        return 0
    print("\nCorrija o .env ou EnvironmentFile do systemd e reinicie o processo (gunicorn/uwsgi).")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
