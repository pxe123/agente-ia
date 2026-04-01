"""
Verificação leve da API Meta (Graph) com token de app (app_id|app_secret).
Instagram Direct e Messenger usam a mesma app Meta; este probe valida credenciais e alcance à Graph API.
"""
from __future__ import annotations

from typing import Any, Dict

import requests

from base.config import settings

# Versão estável comum; Meta aceita várias.
_GRAPH_VER = "v21.0"


def probe_meta_graph_app() -> Dict[str, Any]:
    """
    Retorna {"status": "online", "app_name": "..."} ou {"status": "offline", "detail": "..."}.
    """
    app_id = (getattr(settings, "META_APP_ID", None) or "").strip()
    secret = (getattr(settings, "META_APP_SECRET", None) or "").strip()
    if not app_id or not secret:
        return {"status": "offline", "detail": "META_APP_ID ou META_APP_SECRET não configurados no .env."}

    token = f"{app_id}|{secret}"
    url = f"https://graph.facebook.com/{_GRAPH_VER}/{app_id}"
    try:
        r = requests.get(
            url,
            params={"fields": "id,name", "access_token": token},
            timeout=8,
        )
        try:
            j = r.json()
        except Exception:
            j = {}
        if r.status_code == 200 and isinstance(j, dict) and "id" in j and "error" not in j:
            name = j.get("name") or app_id
            return {"status": "online", "app_name": str(name)[:120]}
        err = j.get("error") if isinstance(j, dict) else None
        if isinstance(err, dict):
            msg = err.get("message") or str(err)
        else:
            msg = r.text[:200] if r.text else r.reason
        return {"status": "offline", "detail": str(msg)[:300]}
    except requests.exceptions.Timeout:
        return {"status": "offline", "detail": "Timeout ao contactar graph.facebook.com."}
    except Exception as e:
        return {"status": "offline", "detail": str(e)[:300]}
