#!/usr/bin/env python3
"""Verifica GOOGLE_* no ZapAction e imprime checklist para produção OAuth."""
from __future__ import annotations

import os
import sys

_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _root not in sys.path:
    sys.path.insert(0, _root)

from base.config import settings
from base.domain_redirects import app_base_url, public_base_url
from services.agendamento_ia_urls import agendamento_ia_configured
from services.google_calendar_oauth import (
    SCOPES,
    google_oauth_configured,
    google_oauth_env_present,
    google_oauth_libs_missing,
    google_redirect_uri,
)

# Valores recomendados para OAuth consent screen (Google Cloud Console)
CONSENT_SCREEN = {
    "app_name": "ZapAction",
    "user_support_email": "contato@updigitalbrasil.com.br",
    "home_page": "https://zapaction.com.br",
    "privacy_policy": "https://zapaction.com.br/politica",
    "terms": "https://zapaction.com.br/termos",
    "authorized_domains": ["zapaction.com.br", "updigitalbrasil.com.br"],
}


def main() -> int:
    issues: list[str] = []
    cid = (getattr(settings, "GOOGLE_CLIENT_ID", None) or "").strip()
    secret = (getattr(settings, "GOOGLE_CLIENT_SECRET", None) or "").strip()
    redirect = (getattr(settings, "GOOGLE_OAUTH_REDIRECT_URI", None) or "").strip()
    derived = google_redirect_uri()
    derived_legacy = google_redirect_uri("http://127.0.0.1:5000/")

    print("=== ZapAction Google OAuth (servidor) ===")
    print(f"GOOGLE_CLIENT_ID={'(definido)' if cid else '(vazio)'}")
    print(f"GOOGLE_CLIENT_SECRET={'(definido)' if secret else '(vazio)'}")
    print(f"GOOGLE_OAUTH_REDIRECT_URI={redirect or '(vazio — usa APP_BASE_URL)'}")
    print(f"APP_BASE_URL={app_base_url()}")
    print(f"PUBLIC_BASE_URL={public_base_url()}")
    print(f"oauth_callback_efetivo={derived or '(vazio)'}")
    print(f"oauth_scopes={SCOPES}")
    print(f"google_oauth_ready={google_oauth_configured() and agendamento_ia_configured()}")

    if derived_legacy != derived:
        print(
            f"aviso: sem APP_BASE_URL/GOOGLE_OAUTH_REDIRECT_URI o gunicorn enviaria "
            f"{derived_legacy} ao Google (redirect_uri_mismatch)"
        )

    if not cid:
        issues.append("GOOGLE_CLIENT_ID vazio")
    if not secret:
        issues.append("GOOGLE_CLIENT_SECRET vazio")
    if google_oauth_libs_missing():
        issues.append("Pacotes Google ausentes — pip install -r requirements.txt")
    if not agendamento_ia_configured():
        issues.append("AGENDAMENTO_IA_BASE_URL / API_KEY não configurados")
    if not derived and not redirect:
        issues.append("Não foi possível determinar redirect URI (defina GOOGLE_OAUTH_REDIRECT_URI ou APP_BASE_URL)")

    print("\n=== Checklist Google Cloud Console (manual) ===")
    print("1. APIs & Services -> Library -> Google Calendar API = ENABLED")
    print("2. OAuth consent screen -> User type = External")
    for k, v in CONSENT_SCREEN.items():
        if isinstance(v, list):
            print(f"   {k}: {', '.join(v)}")
        else:
            print(f"   {k}: {v}")
    print("3. Data Access -> scopes (remover calendar largo se existir):")
    for s in SCOPES:
        print(f"   - {s}")
    print("4. Credentials -> OAuth client -> Authorized redirect URIs:")
    if derived:
        print(f"   - {derived}")
    print("5. Search Console -> verificar dominios zapaction.com.br e updigitalbrasil.com.br")
    print("6. Publish app + Submit verification (ver docs/google_oauth_verification_package.md)")

    print("\n=== URLs para colar no consent screen ===")
    pub = public_base_url().rstrip("/") or CONSENT_SCREEN["home_page"]
    print(f"Home:     {pub}")
    print(f"Privacy:  {pub}/politica")
    print(f"Terms:    {pub}/termos")
    if derived:
        print(f"Redirect: {derived}")

    if issues:
        print("\nAVISOS:")
        for i in issues:
            print(f"  - {i}")
        return 1
    print("\nOK — confira redirect URI e scopes no Console (passos acima).")
    print("Docs: docs/google_oauth_production_checklist.md")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
