#!/usr/bin/env python3
"""Smoke check das variáveis Agendamento IA (Fase 0 do plano de integração)."""
from __future__ import annotations

import os
import sys

_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _root not in sys.path:
    sys.path.insert(0, _root)

from base.config import settings
from services.agendamento_ia_urls import (
    agendamento_ia_configured,
    agendamento_webhook_url_misconfigured,
    check_agendamento_ia_health,
    resolved_agendamento_webhook_url,
    resolved_clinic_sync_url,
)


def main() -> int:
    issues: list[str] = []
    if not getattr(settings, "AGENDAMENTO_IA_BASE_URL", "").strip():
        issues.append("AGENDAMENTO_IA_BASE_URL vazio")
    if not getattr(settings, "AGENDAMENTO_IA_API_KEY", "").strip():
        issues.append("AGENDAMENTO_IA_API_KEY vazio")
    if not getattr(settings, "ZAPACTION_WEBHOOK_SECRET", "").strip():
        issues.append("ZAPACTION_WEBHOOK_SECRET vazio (receptor webhook)")
    allowlist = (getattr(settings, "SCHEDULING_INTERNAL_CLIENTE_IDS", "") or "").strip()
    force_agenda = (getattr(settings, "SCHEDULING_FORCE_AGENDA_CLIENTE_IDS", "") or "").strip()
    use_global = getattr(settings, "USE_INTERNAL_SCHEDULING", False)
    if use_global and agendamento_ia_configured() and not allowlist:
        issues.append(
            "USE_INTERNAL_SCHEDULING=1 global com BASE — prefira SCHEDULING_INTERNAL_CLIENTE_IDS (piloto)"
        )
    if use_global and force_agenda:
        issues.append("USE_INTERNAL_SCHEDULING=1 com FORCE_AGENDA — clientes na blocklist usam Agenda")
    if agendamento_webhook_url_misconfigured():
        issues.append("AGENDAMENTO_IA_WEBHOOK_URL aponta para ZapAction, não /v1/agendamento")

    print("Motor URL:", resolved_agendamento_webhook_url() or "(vazio)")
    print("Snapshot URL:", resolved_clinic_sync_url() or "(vazio)")

    if issues:
        print("AVISOS:")
        for i in issues:
            print(" -", i)

    health = check_agendamento_ia_health()
    print("Health:", "OK" if health.get("ok") else health.get("error"), health.get("url"))
    if not health.get("ok") and agendamento_ia_configured():
        return 1
    return 1 if issues and agendamento_ia_configured() else 0


if __name__ == "__main__":
    raise SystemExit(main())
