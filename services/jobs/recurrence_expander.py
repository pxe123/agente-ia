"""Retry de sync pendente + expansão de séries."""
from __future__ import annotations

import logging

from services.scheduling import repository
from services.scheduling.recurrence import HORIZON_DAYS, expand_series, retry_pending_motor_sync

logger = logging.getLogger(__name__)


def run_recurrence_expander(*, limit: int = 200, horizon_days: int = HORIZON_DAYS) -> dict[str, int]:
    series_list = repository.list_active_recurrence_series(limit=limit)
    total_created = 0
    total_conflicts = 0
    total_sync_pending = 0
    processed = 0
    for series in series_list:
        cid = str(series.get("cliente_id") or "")
        sid = str(series.get("id") or "")
        if not cid or not sid:
            continue
        try:
            result = expand_series(cid, sid, horizon_days=horizon_days)
            total_created += result.created
            total_conflicts += result.skipped_conflict
            total_sync_pending += result.sync_pending
            processed += 1
        except Exception:
            logger.exception("recurrence_expander failed series=%s", sid[:8])
    retry_stats = retry_pending_motor_sync(limit=limit)
    logger.info(
        "recurrence_expander series=%s created=%s conflicts=%s sync_pending=%s retry=%s",
        processed,
        total_created,
        total_conflicts,
        total_sync_pending,
        retry_stats,
    )
    return {
        "series": processed,
        "created": total_created,
        "conflicts": total_conflicts,
        "sync_pending": total_sync_pending,
        "retry": retry_stats,
    }


def run_recurrence_expander_for_cliente(cliente_id: str, *, horizon_days: int = HORIZON_DAYS) -> dict[str, int]:
    series_list = repository.list_active_recurrence_series(limit=500)
    cid = str(cliente_id)
    total_created = 0
    total_conflicts = 0
    total_sync_pending = 0
    processed = 0
    for series in series_list:
        if str(series.get("cliente_id") or "") != cid:
            continue
        sid = str(series.get("id") or "")
        if not sid:
            continue
        result = expand_series(cid, sid, horizon_days=horizon_days)
        total_created += result.created
        total_conflicts += result.skipped_conflict
        total_sync_pending += result.sync_pending
        processed += 1
    retry_stats = retry_pending_motor_sync(cid, limit=100)
    return {
        "series": processed,
        "created": total_created,
        "conflicts": total_conflicts,
        "sync_pending": total_sync_pending,
        "retry": retry_stats,
    }
