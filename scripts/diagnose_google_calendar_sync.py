#!/usr/bin/env python3
"""
Diagnóstico Google Calendar: env ZapAction + status Agenda IA + política + source das marcações.

Uso:
  python scripts/diagnose_google_calendar_sync.py
  python scripts/diagnose_google_calendar_sync.py --cliente-id UUID --limit 20
"""
from __future__ import annotations

import argparse
import os
import subprocess
import sys
from typing import Any

_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _root not in sys.path:
    sys.path.insert(0, _root)


def _interpret_row(status: str, source: str, external_id: str | None) -> str:
    st = (status or "").strip().lower()
    src = (source or "internal").strip().lower()
    ext = (external_id or "").strip()
    if st == "pending" and src == "internal" and not ext:
        return "normal (política profissional — confirmar no painel)"
    if st == "confirmed" and src == "internal" and not ext:
        return "PROBLEMA — confirmado sem evento Google (backfill ou reconectar profissional)"
    if st == "confirmed" and src == "google" and ext:
        return "OK — evento Google deveria existir no calendário do profissional"
    if st == "confirmed" and src == "google" and not ext:
        return "ATENÇÃO — source=google mas external_id vazio (export antigo ou evento removido)"
    if st == "cancelled":
        return "cancelado"
    return "rever manualmente"


def _fetch_appointments_export(cliente_id: str, *, limit: int) -> tuple[list[dict[str, Any]], str | None]:
    import requests

    from services.agendamento_ia_urls import agendamento_ia_base_url, scheduling_integration_headers

    base = agendamento_ia_base_url()
    if not base:
        return [], "AGENDAMENTO_IA_BASE_URL não configurado"
    url = f"{base.rstrip('/')}/v1/integrations/zapaction/appointments/export"
    try:
        r = requests.get(
            url,
            params={"cliente_id": cliente_id, "limit": limit},
            headers=scheduling_integration_headers(),
            timeout=30,
        )
        if r.status_code >= 400:
            return [], f"export HTTP {r.status_code}: {(r.text or '')[:160]}"
        data = r.json()
        if not isinstance(data, dict):
            return [], "export resposta inválida"
        items = data.get("appointments") or []
        return [x for x in items if isinstance(x, dict)], None
    except Exception as e:
        return [], str(e)[:200]


def main() -> int:
    parser = argparse.ArgumentParser(description="Diagnóstico Google Calendar (ZapAction + Agenda IA)")
    parser.add_argument(
        "--cliente-id",
        default="d1ddf96e-e667-48dc-9975-362a9c539fe2",
        help="Tenant piloto (default: clinica-teste)",
    )
    parser.add_argument("--limit", type=int, default=30, help="Marcações recentes a inspecionar")
    parser.add_argument("--skip-verify-scripts", action="store_true")
    args = parser.parse_args()
    cid = (args.cliente_id or "").strip()
    issues: list[str] = []
    warnings: list[str] = []

    print("=== 1. ZapAction OAuth (env) ===")
    if not args.skip_verify_scripts:
        r = subprocess.run(
            [sys.executable, os.path.join(_root, "scripts", "verify_google_oauth_env.py")],
            cwd=_root,
            capture_output=True,
            text=True,
        )
        print(r.stdout or r.stderr or "(sem saída)")
        if r.returncode != 0:
            warnings.append("verify_google_oauth_env reportou avisos (normal em dev local)")
    else:
        from services.google_calendar_oauth import google_oauth_configured

        print(f"google_oauth_configured={google_oauth_configured()}")

    print()
    print("=== 2. Agenda IA Google status (API) ===")
    from services.agendamento_ia_google_status import fetch_google_status
    from services.agendamento_ia_urls import agendamento_ia_configured

    if not agendamento_ia_configured():
        issues.append("Agendamento IA não configurado (AGENDAMENTO_IA_BASE_URL / API_KEY)")
        g_status: dict[str, Any] = {}
    else:
        g_status = fetch_google_status(cid) or {}
        if g_status.get("error"):
            issues.append(f"status Google: {g_status.get('error')}")
        print(f"enabled={g_status.get('enabled')}")
        print(f"oauth_configured={g_status.get('oauth_configured')}")
        print(f"freebusy_ok={g_status.get('freebusy_ok')}")
        print(f"connected={g_status.get('connected')}")
        if g_status.get("last_error"):
            print(f"last_error={g_status.get('last_error')}")
        for p in g_status.get("providers") or []:
            print(
                f"  {p.get('provider_name')}: connected={p.get('connected')} "
                f"refresh={p.get('refresh_token')} freebusy={p.get('freebusy_ok')} "
                f"err={p.get('last_error')}"
            )
        if g_status.get("enabled") and not g_status.get("freebusy_ok"):
            warnings.append("Motor Google ligado mas freebusy_ok=false — tokens ou API Calendar")

    print()
    print("=== 3. Política de confirmação (Supabase) ===")
    policy = "auto"
    try:
        from database.models import SchedulingSettingsModel, Tables
        from database.supabase_sq import supabase
        from services.scheduling.confirmation_policy import (
            get_confirmation_policy,
            requires_professional_confirmation,
            resolve_initial_appointment_status,
        )

        if not supabase:
            warnings.append("Supabase indisponível — política só via API catalog")
        else:
            row = (
                supabase.table(Tables.SCHEDULING_SETTINGS)
                .select("*")
                .eq(SchedulingSettingsModel.CLIENTE_ID, cid)
                .limit(1)
                .execute()
                .data
            )
            st = row[0] if row else {}
            policy = get_confirmation_policy(cid)
            print(f"confirmation_policy (efetiva)={policy}")
            print(f"requires_professional_confirmation={requires_professional_confirmation(cid)}")
            print(f"resolve_initial_appointment_status={resolve_initial_appointment_status(cid)}")
            if st:
                print(f"confirmation_policy (DB)={st.get('confirmation_policy') or 'auto'}")
            if policy == "professional":
                print(
                    "NOTA: com política profissional, eventos Google só após Confirmar no painel "
                    "(não no momento do pedido público)."
                )
    except Exception as e:
        warnings.append(f"Erro ao ler política: {e}")

    print()
    print("=== 4. Marcações recentes (source / external_id) ===")
    items, export_err = _fetch_appointments_export(cid, limit=max(1, args.limit))
    if export_err:
        warnings.append(f"export marcações: {export_err}")
        print(f"(export falhou: {export_err})")
    elif not items:
        print("(nenhuma marcação no export)")
    else:
        pending_no_google = 0
        confirmed_internal = 0
        confirmed_google = 0
        print(f"{'status':<12} {'source':<10} {'external_id':<28} interpretação")
        print("-" * 90)
        for it in items[: args.limit]:
            st = str(it.get("status") or "")
            src = str(it.get("source") or "internal")
            ext = it.get("external_id")
            ext_s = str(ext or "")[:26]
            interp = _interpret_row(st, src, str(ext or ""))
            print(f"{st:<12} {src:<10} {ext_s:<28} {interp}")
            if st == "pending" and src == "internal" and not ext:
                pending_no_google += 1
            elif st == "confirmed" and src == "internal" and not ext:
                confirmed_internal += 1
            elif st == "confirmed" and src == "google" and ext:
                confirmed_google += 1
        print()
        print(
            f"Resumo: pending_sem_google={pending_no_google} "
            f"confirmed_internal={confirmed_internal} confirmed_google={confirmed_google}"
        )
        if policy == "professional" and pending_no_google and not confirmed_internal:
            print("Comportamento esperado se ainda não confirmou pedidos pendentes.")
        if confirmed_internal:
            issues.append(
                f"{confirmed_internal} marcação(ões) confirmada(s) com source=internal — "
                "evento Google não foi criado (rodar backfill ou reconectar OAuth)"
            )

    print()
    print("=== 5. Checklist rápido ===")
    print("- OAuth no painel: Agenda -> Profissionais -> Google (por profissional)")
    print("- Sincronizar catálogo antes do OAuth")
    print("- Servidor Agenda: USE_GOOGLE=true + GOOGLE_CLIENT_ID/SECRET")
    print("- Teste: pedido pendente -> Confirmar -> source deve virar google")
    print("- Backfill: python scripts/backfill_google_calendar_events.py --cliente-id ... --dry-run")

    if warnings:
        print()
        print("Avisos:")
        for w in warnings:
            print(" -", w)
    if issues:
        print()
        print("Problemas:")
        for i in issues:
            print(" -", i)
        return 1
    print()
    print("Diagnóstico: sem problemas críticos detectados (revise avisos em dev local).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
