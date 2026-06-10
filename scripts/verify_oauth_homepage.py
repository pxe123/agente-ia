#!/usr/bin/env python3
"""Verifica requisitos da página inicial para Google OAuth (home pública)."""
from __future__ import annotations

import re
import sys
import urllib.error
import urllib.request

HOME_URL = "https://zapaction.com.br/"
POLICY_URL = "https://zapaction.com.br/politica"
EXPECTED_PRIVACY_PATH = "/politica"

CHECKS: list[tuple[str, str]] = [
    ("secao_agendamento", r'id=["\']agendamento["\']'),
    ("link_politica", r'href=["\'][^"\']*' + re.escape(EXPECTED_PRIVACY_PATH) + r'["\']'),
    ("disclosure_google", r"disponibilidade.*horários livres|free/busy|criar ou remover eventos"),
    ("marca_zapaction", r"ZapAction"),
    ("google_agenda", r"Google (Agenda|Calendar)"),
    ("sem_login_obrigatorio", r"(Ver planos|Começar|Criar conta)"),
]


def fetch(url: str, timeout: int = 25) -> tuple[int, str]:
    req = urllib.request.Request(url, headers={"User-Agent": "ZapAction-OAuth-Homepage-Verify/1.0"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.status, resp.read().decode("utf-8", errors="replace")


def main() -> int:
    issues: list[str] = []
    print(f"=== OAuth homepage checks: {HOME_URL} ===\n")

    try:
        status, html = fetch(HOME_URL)
    except urllib.error.URLError as e:
        print(f"ERRO: não foi possível aceder à home: {e}")
        return 1

    if status != 200:
        issues.append(f"Home HTTP {status} (esperado 200)")

    for name, pattern in CHECKS:
        ok = bool(re.search(pattern, html, re.I | re.S))
        mark = "OK" if ok else "FALTA"
        print(f"  [{mark}] {name}")
        if not ok:
            issues.append(name)

    try:
        p_status, policy_html = fetch(POLICY_URL)
        if p_status != 200:
            issues.append(f"Política HTTP {p_status}")
        else:
            has_gc = bool(re.search(r"Google Calendar", policy_html, re.I))
            print(f"  [{'OK' if has_gc else 'FALTA'}] politica_google_calendar")
            if not has_gc:
                issues.append("politica_google_calendar")
    except urllib.error.URLError as e:
        issues.append(f"politica_inacessivel: {e}")
        print(f"  [ERRO] politica: {e}")

    print("\n=== URLs para OAuth consent screen ===")
    print(f"  Home:    {HOME_URL.rstrip('/')}")
    print(f"  Privacy: {POLICY_URL}")
    print("\n=== Search Console (manual) ===")
    print("  1. https://search.google.com/search-console (mesma conta do GCP)")
    print("  2. Propriedade: https://zapaction.com.br ou dominio zapaction.com.br")
    print("  3. DNS TXT google-site-verification deve existir no registrador")
    print("  4. Verification Center -> Reverificar requisitos da pagina inicial")

    if issues:
        print("\nAVISOS:")
        for i in issues:
            print(f"  - {i}")
        return 1

    print("\nOK - home atende aos checks automatizados. Conclua Search Console + reverificacao no GCP.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
