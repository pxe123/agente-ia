from __future__ import annotations

import json
import time
from typing import Any, Dict, Optional


def emit(event: str, *, cliente_id: str | None = None, session_name: str | None = None, profile_id: str | None = None, data: Optional[Dict[str, Any]] = None) -> None:
    """
    Observabilidade leve: emite eventos estruturados em stdout.
    (Pode ser ingerido por Sentry/log aggregation.)
    """
    try:
        payload = {
            "ts": int(time.time() * 1000),
            "event": (event or "")[:80],
            "cliente_id": (str(cliente_id) if cliente_id else None),
            "session_name": (str(session_name) if session_name else None),
            "profile_id": (str(profile_id) if profile_id else None),
            "data": data or {},
        }
        print("[EGRESS] " + json.dumps(payload, ensure_ascii=False), flush=True)
    except Exception:
        pass

