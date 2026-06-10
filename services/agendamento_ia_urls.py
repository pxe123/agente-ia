"""
URLs e helpers de integração com o serviço Agendamento IA (FastAPI externo).
"""
from __future__ import annotations

import logging
from typing import Any
from urllib.parse import urlparse

import requests

from base.config import settings

logger = logging.getLogger(__name__)


def _strip_base(url: str | None) -> str:
    return (url or "").strip().rstrip("/")


def _origin_from_absolute_url(url: str) -> str:
    u = (url or "").strip()
    if not u.startswith("http"):
        return ""
    parsed = urlparse(u)
    if not parsed.scheme or not parsed.netloc:
        return ""
    return f"{parsed.scheme}://{parsed.netloc}".rstrip("/")


def effective_agendamento_ia_base_url() -> str:
    """
    BASE explícita ou origem inferida de CLINIC_SYNC_URL / WEBHOOK_URL / LINK_GENERATE_URL.
    """
    explicit = _strip_base(getattr(settings, "AGENDAMENTO_IA_BASE_URL", None) or "")
    if explicit:
        return explicit
    for candidate in (
        getattr(settings, "AGENDAMENTO_IA_CLINIC_SYNC_URL", None),
        getattr(settings, "AGENDAMENTO_IA_WEBHOOK_URL", None),
        getattr(settings, "AGENDAMENTO_IA_LINK_GENERATE_URL", None),
    ):
        origin = _origin_from_absolute_url(str(candidate or ""))
        if origin:
            return origin
    return ""


def agendamento_ia_base_url() -> str:
    """Origem do serviço Agenda (para health e UI)."""
    return effective_agendamento_ia_base_url()


def agendamento_webhook_url_misconfigured() -> bool:
    """True se WEBHOOK_URL aponta para o ZapAction em vez do motor /v1/agendamento."""
    url = (getattr(settings, "AGENDAMENTO_IA_WEBHOOK_URL", None) or "").strip().lower()
    if not url:
        return False
    if "/v1/agendamento" in url:
        return False
    if "/webhook/" in url or "agendamento_ia" in url.replace("-", "_"):
        return True
    return False


def agendamento_ia_public_base_url() -> str:
    pub = _strip_base(getattr(settings, "AGENDAMENTO_IA_PUBLIC_BASE_URL", None) or "")
    return pub or agendamento_ia_base_url()


def build_public_book_page_url(
    slug: str,
    *,
    phone: str = "",
    name: str = "",
) -> str:
    """
    URL canónica da agenda pública no Agendamento IA: /v1/book/{slug}/page.
    Query opcional: phone, name (pré-preenchimento no browser).
    """
    from urllib.parse import urlencode

    s = (slug or "").strip().lower().replace(" ", "-")
    base = agendamento_ia_public_base_url()
    if not base or not s:
        return ""
    path = f"{base}/v1/book/{s}/page"
    params: dict[str, str] = {}
    ph = (phone or "").strip()
    nm = (name or "").strip()
    if ph:
        params["phone"] = ph
    if nm:
        params["name"] = nm
    if not params:
        return path
    return f"{path}?{urlencode(params)}"


def agendamento_ia_url(path: str) -> str:
    base = agendamento_ia_base_url()
    if not base:
        return ""
    p = path if path.startswith("/") else f"/{path}"
    return f"{base}{p}"


def resolved_agendamento_webhook_url() -> str:
    explicit = (getattr(settings, "AGENDAMENTO_IA_WEBHOOK_URL", None) or "").strip()
    if explicit:
        return explicit
    return agendamento_ia_url("/v1/agendamento")


def resolved_link_generate_url() -> str:
    explicit = (getattr(settings, "AGENDAMENTO_IA_LINK_GENERATE_URL", None) or "").strip()
    if explicit:
        return explicit
    return agendamento_ia_url("/v1/link/generate")


def resolved_clinic_sync_url() -> str:
    explicit = (getattr(settings, "AGENDAMENTO_IA_CLINIC_SYNC_URL", None) or "").strip()
    if explicit:
        return explicit
    return agendamento_ia_url("/v1/integrations/zapaction/tenant-snapshot")


def agendamento_ia_configured() -> bool:
    return bool(
        agendamento_ia_base_url()
        or (getattr(settings, "AGENDAMENTO_IA_WEBHOOK_URL", None) or "").strip()
        or (getattr(settings, "AGENDAMENTO_IA_CLINIC_SYNC_URL", None) or "").strip()
    )


def link_generate_available() -> bool:
    return bool(resolved_link_generate_url())


def clinic_sync_configured() -> bool:
    return bool(resolved_clinic_sync_url())


def is_production_environment() -> bool:
    env = (getattr(settings, "ENVIRONMENT", None) or "").strip().lower()
    return env in ("production", "prod")


def scheduling_integration_headers() -> dict[str, str]:
    headers = {"Content-Type": "application/json"}
    key = (
        (getattr(settings, "AGENDAMENTO_IA_CLINIC_SYNC_API_KEY", None) or "").strip()
        or (getattr(settings, "AGENDAMENTO_IA_API_KEY", None) or "").strip()
    )
    if key:
        headers["Authorization"] = f"Bearer {key}"
    return headers


def check_agendamento_ia_health(timeout_sec: int = 5) -> dict[str, Any]:
    """
    GET {BASE}/health. Retorno: ok, http_status, error, body (dict|None).
    """
    url = agendamento_ia_url("/health")
    out: dict[str, Any] = {
        "ok": False,
        "http_status": None,
        "error": None,
        "body": None,
        "url": url,
    }
    if not url:
        out["error"] = "nao_configurado"
        return out
    try:
        r = requests.get(url, timeout=timeout_sec)
        out["http_status"] = r.status_code
        out["ok"] = 200 <= r.status_code < 300
        if r.text:
            try:
                import json

                out["body"] = json.loads(r.text)
            except Exception:
                out["body"] = {"raw": (r.text or "")[:200]}
        if not out["ok"]:
            out["error"] = f"http_{r.status_code}"
    except requests.Timeout:
        out["error"] = "timeout"
    except Exception as e:
        out["error"] = str(e)
    return out
