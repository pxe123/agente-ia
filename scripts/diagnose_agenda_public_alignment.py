#!/usr/bin/env python3
"""
Compara scheduling_settings (Supabase) com /branding e /catalog do Agendamento IA.

Uso:
  python scripts/diagnose_agenda_public_alignment.py
  python scripts/diagnose_agenda_public_alignment.py --slug clinica-teste
  python scripts/diagnose_agenda_public_alignment.py --agenda-base https://agenda.zapaction.com.br
"""
from __future__ import annotations

import argparse
import json
import os
import sys

_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _root not in sys.path:
    sys.path.insert(0, _root)


def _fetch_json(url: str, timeout: int = 30) -> tuple[int, dict | list | str]:
    import urllib.error
    import urllib.request

    try:
        with urllib.request.urlopen(url, timeout=timeout) as r:
            body = r.read().decode("utf-8", errors="replace")
            code = r.getcode()
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")
        return e.code, body
    try:
        return code, json.loads(body)
    except json.JSONDecodeError:
        return code, body


def main() -> int:
    parser = argparse.ArgumentParser(description="Diagnóstico alinhamento painel vs página pública")
    parser.add_argument("--cliente-id", default="d1ddf96e-e667-48dc-9975-362a9c539fe2")
    parser.add_argument("--slug", default="clinica-teste")
    parser.add_argument("--agenda-base", default="https://agenda.zapaction.com.br")
    args = parser.parse_args()
    cid = args.cliente_id.strip()
    slug = args.slug.strip()
    base = (args.agenda_base or "").rstrip("/")
    issues: list[str] = []

    print("=== ZapAction (Supabase) ===")
    st: dict = {}
    try:
        from database.models import SchedulingSettingsModel, Tables
        from database.supabase_sq import supabase

        if not supabase:
            issues.append("Supabase indisponível no ambiente local")
        else:
            res = (
                supabase.table(Tables.SCHEDULING_SETTINGS)
                .select("*")
                .eq(SchedulingSettingsModel.CLIENTE_ID, cid)
                .limit(1)
                .execute()
            )
            rows = res.data or []
            st = rows[0] if rows else {}
            if not st:
                issues.append(f"scheduling_settings não encontrado para cliente_id={cid}")
            else:
                print("public_name:", st.get("public_name"))
                print("public_slug:", st.get("public_slug"))
                print("timezone:", st.get("timezone"))
                print("professional_assignment_mode:", st.get("professional_assignment_mode"))
                print("confirmation_policy:", st.get("confirmation_policy"))
    except Exception as e:
        issues.append(f"Erro Supabase: {e}")

    print()
    print("=== Agendamento IA (HTTP) ===")
    branding_url = f"{base}/v1/book/{slug}/branding"
    catalog_url = f"{base}/v1/book/{slug}/catalog"
    b_code, branding = _fetch_json(branding_url)
    c_code, catalog = _fetch_json(catalog_url)
    print(f"GET branding -> HTTP {b_code}")
    print(f"GET catalog  -> HTTP {c_code}")

    if isinstance(branding, dict):
        print("branding.name:", branding.get("name"))
        print("branding.slug:", branding.get("slug"))
        print("branding.timezone:", branding.get("timezone"))
    if isinstance(catalog, dict):
        print("catalog.cliente_id:", catalog.get("cliente_id"))
        print("catalog.assignment_mode:", catalog.get("assignment_mode"))
        print("catalog.confirmation_policy:", catalog.get("confirmation_policy"))
        print("catalog.services:", len(catalog.get("services") or []))
        print("catalog.providers:", len(catalog.get("providers") or []))

    print()
    print("=== Comparação ===")
    if st and isinstance(branding, dict):
        za_name = (st.get("public_name") or "").strip()
        ag_name = (branding.get("name") or "").strip()
        if za_name and ag_name != za_name:
            issues.append(f"Nome: painel={za_name!r} vs branding={ag_name!r}")
        if za_name and ag_name == cid:
            issues.append("branding.name é o cliente_id — public_name não sincronizado (tenant.branding_name)")

    if st and isinstance(catalog, dict):
        za_mode = (st.get("professional_assignment_mode") or "manual").strip().lower()
        ag_mode = (catalog.get("assignment_mode") or "manual").strip().lower()
        if za_mode != ag_mode:
            issues.append(f"assignment_mode: painel={za_mode} vs catalog={ag_mode}")

        za_conf = (st.get("confirmation_policy") or "auto").strip().lower()
        ag_conf = (catalog.get("confirmation_policy") or "auto").strip().lower()
        if za_conf != ag_conf:
            issues.append(f"confirmation_policy: painel={za_conf} vs catalog={ag_conf}")

        za_tz = (st.get("timezone") or "").strip()
        ag_tz = (catalog.get("timezone") or "").strip()
        if za_tz and ag_tz and za_tz != ag_tz:
            issues.append(f"timezone: painel={za_tz} vs catalog={ag_tz}")

    if c_code != 200:
        issues.append(f"/catalog HTTP {c_code}")
    if b_code != 200:
        issues.append(f"/branding HTTP {b_code}")

    if issues:
        print("PROBLEMAS:")
        for i in issues:
            print(" -", i)
        print()
        print("Ação: deploy agente-ia + agendamento-ia, depois Sincronizar com Agenda externa no painel.")
        return 1

    print("OK — painel e APIs públicas alinhados.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
