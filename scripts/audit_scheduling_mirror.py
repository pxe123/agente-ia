#!/usr/bin/env python3
"""
Auditoria: compara export do Agendamento IA vs espelho em scheduling_appointments.

Executar ANTES de adicionar cliente com histórico Agenda à SCHEDULING_INTERNAL_CLIENTE_IDS.
Ver docs/scheduling_internal_rollout_runbook.md
"""
from __future__ import annotations

import argparse
import os
import sys
from datetime import datetime, timedelta, timezone

_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _root not in sys.path:
    sys.path.insert(0, _root)

import requests

from database.supabase_sq import supabase
from services.agendamento_ia_appointments_import import _export_url
from services.agendamento_ia_urls import scheduling_integration_headers


def _supabase_counts(cliente_id: str) -> dict[str, int]:
    if not supabase:
        return {"mirrored": -1, "local_only": -1, "future_active": -1}
    cid = str(cliente_id).strip()
    mirrored = (
        supabase.table("scheduling_appointments")
        .select("id", count="exact")
        .eq("cliente_id", cid)
        .not_.is_("external_agenda_appointment_id", "null")
        .execute()
    )
    local_only = (
        supabase.table("scheduling_appointments")
        .select("id", count="exact")
        .eq("cliente_id", cid)
        .is_("external_agenda_appointment_id", "null")
        .execute()
    )
    now = datetime.now(timezone.utc).isoformat()
    future = (
        supabase.table("scheduling_appointments")
        .select("id", count="exact")
        .eq("cliente_id", cid)
        .neq("status", "cancelled")
        .gte("starts_at", now)
        .execute()
    )
    return {
        "mirrored": int(getattr(mirrored, "count", None) or len(mirrored.data or [])),
        "local_only": int(getattr(local_only, "count", None) or len(local_only.data or [])),
        "future_active": int(getattr(future, "count", None) or len(future.data or [])),
    }


def _agenda_export_count(cliente_id: str, *, since_days: int, limit: int) -> tuple[int, str | None]:
    url = _export_url()
    if not url:
        return -1, "agendamento_ia_nao_configurado"
    since = (datetime.now(timezone.utc) - timedelta(days=max(1, since_days))).isoformat()
    params = {"cliente_id": str(cliente_id).strip(), "since": since, "limit": limit}
    try:
        r = requests.get(
            url,
            params=params,
            headers=scheduling_integration_headers(),
            timeout=25,
        )
    except requests.RequestException as e:
        return -1, f"falha_ligacao: {e}"
    if r.status_code >= 400:
        return -1, f"agenda_http_{r.status_code}"
    try:
        data = r.json()
    except ValueError:
        return -1, "json_invalido"
    items = data.get("appointments") if isinstance(data, dict) else None
    if not isinstance(items, list):
        return -1, "appointments_em_falta"
    return len(items), None


def main() -> int:
    parser = argparse.ArgumentParser(description="Auditoria Agenda vs Supabase scheduling_appointments")
    parser.add_argument("cliente_id", help="UUID do cliente")
    parser.add_argument("--since-days", type=int, default=90, help="Janela do export Agenda (default 90)")
    parser.add_argument("--limit", type=int, default=500, help="Limite do export Agenda (default 500)")
    args = parser.parse_args()
    cid = args.cliente_id.strip()

    print(f"Cliente: {cid}")
    print(f"Janela export: {args.since_days} dias, limit={args.limit}")
    print()

    sb = _supabase_counts(cid)
    if sb["mirrored"] < 0:
        print("ERRO: Supabase indisponível")
        return 1

    agenda_n, err = _agenda_export_count(cid, since_days=args.since_days, limit=args.limit)
    print("Supabase scheduling_appointments:")
    print(f"  espelhadas (external_agenda_appointment_id): {sb['mirrored']}")
    print(f"  só locais (sem external):                  {sb['local_only']}")
    print(f"  futuras ativas (não canceladas):            {sb['future_active']}")
    print()
    if err:
        print(f"Export Agenda: ERRO — {err}")
        return 1
    print(f"Export Agenda (itens na janela): {agenda_n}")
    print()

    gap = agenda_n - sb["mirrored"]
    if gap > 0:
        print(
            f"AVISO: export tem {gap} item(ns) a mais que espelhadas no Supabase. "
            "Execute sync_appointments_from_agenda antes da allowlist."
        )
        return 1
    if gap < 0:
        print(
            f"INFO: Supabase tem {abs(gap)} espelhada(s) a mais que o export "
            "(normal se houve import parcial ou cancelamentos fora da janela)."
        )
    else:
        print("OK: contagem export == espelhadas (na janela/limit do export).")
    print()
    print("Próximo passo: só adicionar à SCHEDULING_INTERNAL_CLIENTE_IDS após import + revisão manual.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
