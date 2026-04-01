"""
Health check do WAHA (URL + API key do .env). Usado pelo painel Admin.
"""
from __future__ import annotations

from typing import Any, Dict

import requests

from base.config import settings


def probe_waha_status() -> Dict[str, Any]:
    """
    Retorna {"status": "online", "version": "..."} ou {"status": "offline"}.
    """
    base = (getattr(settings, "WAHA_URL", None) or "").strip().rstrip("/")
    if not base:
        return {"status": "offline"}

    key = (getattr(settings, "WAHA_API_KEY", None) or "").strip()
    headers: Dict[str, str] = {"Accept": "application/json"}
    if key:
        headers["X-Api-Key"] = key
    timeout = 5

    def _version_from_json(j: Any) -> str | None:
        if not isinstance(j, dict):
            return None
        v = j.get("version") or j.get("engine") or j.get("name")
        if isinstance(v, dict):
            v = v.get("version") or v.get("name")
        if v is None and j.get("healthy") is True:
            return "healthy"
        if v is None and j.get("status") in ("ok", "UP", "up", True):
            return "ok"
        return str(v)[:120] if v is not None else None

    for path in ("/api/health", "/api/version", "/api/server/version"):
        try:
            r = requests.get(f"{base}{path}", headers=headers, timeout=timeout)
            if r.status_code == 200:
                ver = None
                try:
                    ver = _version_from_json(r.json())
                except Exception:
                    pass
                return {"status": "online", "version": ver or "ok"}
        except Exception:
            continue

    try:
        r = requests.get(
            f"{base}/api/sessions",
            headers=headers,
            params={"all": "true"},
            timeout=timeout,
        )
        if r.status_code == 200:
            return {"status": "online", "version": "API sessions"}
    except Exception:
        pass

    return {"status": "offline"}
