"""OAuth Google Calendar no domínio ZapAction (login Google direto, sem passar pelo Agenda no browser)."""
from __future__ import annotations

import base64
import hashlib
import hmac
import logging
import os
import time
from typing import Any
from urllib.parse import urlencode

from base.config import settings

logger = logging.getLogger(__name__)

SCOPES = [
    "https://www.googleapis.com/auth/calendar.events",
    "https://www.googleapis.com/auth/calendar.events.freebusy",
]

os.environ.setdefault("OAUTHLIB_RELAX_TOKEN_SCOPE", "1")


def _google_libs_available() -> bool:
    try:
        import google_auth_oauthlib.flow  # noqa: F401
        return True
    except ImportError:
        return False


def google_oauth_configured() -> bool:
    return bool(
        (getattr(settings, "GOOGLE_CLIENT_ID", None) or "").strip()
        and (getattr(settings, "GOOGLE_CLIENT_SECRET", None) or "").strip()
        and _google_libs_available()
    )


def google_oauth_env_present() -> bool:
    """Credenciais no .env (mesmo que a lib Google ainda não esteja instalada)."""
    return bool(
        (getattr(settings, "GOOGLE_CLIENT_ID", None) or "").strip()
        and (getattr(settings, "GOOGLE_CLIENT_SECRET", None) or "").strip()
    )


def google_oauth_libs_missing() -> bool:
    return google_oauth_env_present() and not _google_libs_available()


def google_redirect_uri(fallback_request_root: str = "") -> str:
    """
    URI de callback OAuth. Ordem: GOOGLE_OAUTH_REDIRECT_URI → APP_BASE_URL → request.url_root.
    Atrás de nginx, request.url_root costuma ser http://127.0.0.1:5000 (invalid_grant / mismatch).
    """
    explicit = (getattr(settings, "GOOGLE_OAUTH_REDIRECT_URI", None) or "").strip()
    if explicit:
        return explicit
    try:
        from base.domain_redirects import app_base_url

        base = app_base_url()
        if base:
            return f"{base.rstrip('/')}/painel/agenda/google/callback"
    except Exception:
        pass
    root = (fallback_request_root or "").strip().rstrip("/")
    if root:
        return f"{root}/painel/agenda/google/callback"
    return ""


def _signing_key() -> bytes:
    return (getattr(settings, "SECRET_KEY", None) or "dev-google-oauth").encode("utf-8")


def sign_oauth_state(*, cliente_id: str, provider_id: str) -> str:
    cid = (cliente_id or "").strip()
    pid = (provider_id or "").strip()
    if not cid or not pid:
        raise ValueError("cliente_id_ou_provider_id_em_falta")
    raw = f"{cid}|{pid}|{int(time.time()) + 600}".encode("utf-8")
    sig = hmac.new(_signing_key(), raw, hashlib.sha256).hexdigest()[:16]
    b64 = base64.urlsafe_b64encode(raw).decode().rstrip("=")
    return f"{b64}.{sig}"


def verify_oauth_state(state: str) -> tuple[str, str] | None:
    s = (state or "").strip()
    if not s or "." not in s:
        return None
    b64, sig = s.split(".", 1)
    try:
        raw = base64.urlsafe_b64decode(b64 + "==")
    except Exception:
        return None
    expected = hmac.new(_signing_key(), raw, hashlib.sha256).hexdigest()[:16]
    if not hmac.compare_digest(sig, expected):
        return None
    try:
        text = raw.decode("utf-8")
    except Exception:
        return None
    parts = text.split("|", 2)
    if len(parts) < 2:
        return None
    cid, pid = parts[0].strip(), parts[1].strip()
    if not cid or not pid:
        return None
    if len(parts) >= 3:
        try:
            exp = int(parts[2])
            if time.time() > exp:
                return None
        except ValueError:
            pass
    return cid, pid


def build_google_authorize_url(
    *,
    cliente_id: str,
    provider_id: str,
    redirect_uri: str,
    force_consent: bool = True,
) -> str:
    if not google_oauth_configured():
        if google_oauth_libs_missing():
            raise ValueError(
                "google_oauth_lib_missing: instale dependências (pip install -r requirements.txt)"
            )
        raise ValueError("google_not_configured")
    if not redirect_uri:
        raise ValueError("google_redirect_uri_em_falta")
    from google_auth_oauthlib.flow import Flow

    oauth_state = sign_oauth_state(cliente_id=cliente_id, provider_id=provider_id)
    flow = Flow.from_client_config(
        {
            "web": {
                "client_id": settings.GOOGLE_CLIENT_ID,
                "client_secret": settings.GOOGLE_CLIENT_SECRET,
                "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                "token_uri": "https://oauth2.googleapis.com/token",
            }
        },
        scopes=SCOPES,
        redirect_uri=redirect_uri,
        state=oauth_state,
        autogenerate_code_verifier=False,
    )
    kwargs: dict[str, str] = {
        "access_type": "offline",
        "include_granted_scopes": "true",
        "state": oauth_state,
        # consent obrigatório para refresh_token (Google só envia na 1ª vez ou com prompt=consent)
        "prompt": "consent" if force_consent else "select_account",
    }
    url, _ = flow.authorization_url(**kwargs)
    logger.info(
        "google oauth authorize zapaction cliente_id=…%s provider_id=…%s",
        (cliente_id or "")[-8:],
        (provider_id or "")[-8:],
    )
    return url


def exchange_google_code(
    *,
    code: str,
    redirect_uri: str,
    authorization_response: str | None = None,
) -> str:
    """Troca authorization code por refresh_token."""
    if not google_oauth_configured():
        if google_oauth_libs_missing():
            raise ValueError(
                "google_oauth_lib_missing: instale dependências (pip install -r requirements.txt)"
            )
        raise ValueError("google_not_configured")
    from google_auth_oauthlib.flow import Flow

    flow = Flow.from_client_config(
        {
            "web": {
                "client_id": settings.GOOGLE_CLIENT_ID,
                "client_secret": settings.GOOGLE_CLIENT_SECRET,
                "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                "token_uri": "https://oauth2.googleapis.com/token",
            }
        },
        scopes=SCOPES,
        redirect_uri=redirect_uri,
        autogenerate_code_verifier=False,
    )
    try:
        flow.fetch_token(code=(code or "").strip())
    except Exception as e:
        if authorization_response:
            flow2 = Flow.from_client_config(
                {
                    "web": {
                        "client_id": settings.GOOGLE_CLIENT_ID,
                        "client_secret": settings.GOOGLE_CLIENT_SECRET,
                        "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                        "token_uri": "https://oauth2.googleapis.com/token",
                    }
                },
                scopes=SCOPES,
                redirect_uri=redirect_uri,
                autogenerate_code_verifier=False,
            )
            flow2.fetch_token(authorization_response=authorization_response)
            flow = flow2
        else:
            err = str(e).lower()
            if "invalid_grant" in err:
                raise ValueError(
                    "oauth_codigo_expirado: clique Conectar Google outra vez (não atualize esta página)."
                ) from e
            raise ValueError(f"oauth_exchange_failed:{type(e).__name__}") from e
    creds = flow.credentials
    refresh = getattr(creds, "refresh_token", None) or ""
    if not refresh:
        raise ValueError(
            "missing_refresh_token: o Google não devolveu permissão offline. "
            "Clique Reconectar Google (marque todos os acessos). "
            "Se persistir: https://myaccount.google.com/permissions — remova o app ZapAction/Agenda e tente de novo."
        )
    return str(refresh)
