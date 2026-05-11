from __future__ import annotations

import json
from typing import Any, Optional


def log_authz_event(
    *,
    allowed: bool,
    reason: str,
    role: str,
    role_source: str,
    tenant_id: Optional[str],
    subscription_status: Optional[str] = None,
    route: Optional[str] = None,
    method: Optional[str] = None,
    request_id: Optional[str] = None,
    extra: Optional[dict[str, Any]] = None,
) -> None:
    """
    Audit log (Fase 1): log estruturado (JSON) no logger do app.
    Não grava em DB para não aumentar risco.
    """
    try:
        from flask import current_app
    except Exception:
        return

    payload: dict[str, Any] = {
        "event": "AUTHZ_LOG",
        "allowed": bool(allowed),
        "reason": (reason or "")[:200],
        "role": (role or "")[:64],
        "role_source": (role_source or "")[:32],
        "tenant_id": (str(tenant_id) if tenant_id else None),
        "subscription_status": (subscription_status or None),
        "route": (route or None),
        "method": (method or None),
        "request_id": (request_id or None),
    }
    if extra:
        try:
            payload["extra"] = extra
        except Exception:
            payload["extra"] = {"_error": "extra_not_serializable"}

    try:
        current_app.logger.info("%s", json.dumps(payload, ensure_ascii=False))
    except Exception:
        # Nunca quebrar request por logging
        return

