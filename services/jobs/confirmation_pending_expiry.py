"""Cancela pedidos pending expirados (TTL por tenant)."""
from __future__ import annotations

import logging
from datetime import datetime, timezone

from services.scheduling import repository

logger = logging.getLogger(__name__)


def run_confirmation_pending_expiry(*, limit: int = 200) -> dict[str, int]:
    expired = repository.list_expired_pending_appointments(limit=limit)
    cancelled = 0
    for row in expired:
        cid = str(row.get("cliente_id") or "")
        aid = str(row.get("id") or "")
        if not cid or not aid:
            continue
        ok = repository.update_appointment_status(cid, aid, "cancelled")
        if ok:
            repository.merge_appointment_meta(
                cid,
                aid,
                {
                    "cancellation_reason": "pending_expired",
                    "expired_at": datetime.now(timezone.utc).isoformat(),
                },
            )
            cancelled += 1
    logger.info("confirmation_pending_expiry scanned=%s cancelled=%s", len(expired), cancelled)
    return {"scanned": len(expired), "cancelled": cancelled}
