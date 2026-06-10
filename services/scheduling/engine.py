"""
Resolução do motor de agenda por tenant (scheduling_settings.scheduling_engine).

Prioridade: env break-glass → global → BD → allowlist env (rede de segurança) → default produção.
Sem cache na v1.
"""
from __future__ import annotations

import logging
from typing import Any

from base.config import settings
from database.models import SchedulingSettingsModel
from services.agendamento_ia_urls import (
    agendamento_ia_base_url,
    is_production_environment,
    resolved_agendamento_webhook_url,
)

logger = logging.getLogger(__name__)

ENGINE_AGENDAMENTO_IA = "agendamento_ia"
ENGINE_ZAPACTION_INTERNAL = "zapaction_internal"
VALID_ENGINES = frozenset({ENGINE_AGENDAMENTO_IA, ENGINE_ZAPACTION_INTERNAL})


def _parse_cliente_id_csv(raw: str) -> frozenset[str]:
    return frozenset(p.strip().lower() for p in (raw or "").split(",") if p.strip())


def _env_force_agenda_ids() -> frozenset[str]:
    return _parse_cliente_id_csv(getattr(settings, "SCHEDULING_FORCE_AGENDA_CLIENTE_IDS", ""))


def _env_internal_allowlist_ids() -> frozenset[str]:
    return _parse_cliente_id_csv(getattr(settings, "SCHEDULING_INTERNAL_CLIENTE_IDS", ""))


def _read_engine_from_db(cliente_id: str) -> str | None:
    """None = sem linha ou falha de leitura (activa fallback env)."""
    try:
        from services.scheduling import repository as sched_repo

        if not sched_repo.supabase_available():
            return None
        return sched_repo.get_scheduling_engine(cliente_id)
    except Exception as exc:
        logger.warning(
            "scheduling_engine read failed cliente_id=%s err=%s",
            (cliente_id or "")[:8],
            exc,
        )
        return None


def get_scheduling_engine(cliente_id: str | None) -> str:
    """
    Motor efectivo para exibição (não aplica só env global sem tenant).
    """
    cid = (cliente_id or "").strip()
    if not cid:
        return ENGINE_AGENDAMENTO_IA
    engine = _read_engine_from_db(cid)
    if engine in VALID_ENGINES:
        return engine
    if cid.lower() in _env_internal_allowlist_ids():
        return ENGINE_ZAPACTION_INTERNAL
    return ENGINE_AGENDAMENTO_IA


def scheduling_uses_internal_motor(cliente_id: str | None) -> bool:
    """
    True: nó agendamento_ia usa SchedulingService interno (Supabase).
    False: POST para Agendamento IA (/v1/agendamento).
    """
    cid = (cliente_id or "").strip().lower()
    if cid and cid in _env_force_agenda_ids():
        return False
    if getattr(settings, "USE_INTERNAL_SCHEDULING", False):
        return True

    db_engine = _read_engine_from_db(cliente_id or "") if cid else None
    if db_engine == ENGINE_ZAPACTION_INTERNAL:
        return True
    if db_engine == ENGINE_AGENDAMENTO_IA:
        return False

    if cid and cid in _env_internal_allowlist_ids():
        return True

    if is_production_environment() and agendamento_ia_base_url():
        return False
    return not bool(resolved_agendamento_webhook_url())


def set_scheduling_engine(
    cliente_id: str,
    engine: str,
    *,
    changed_by: str | None = None,
) -> tuple[bool, str | None]:
    eng = (engine or "").strip().lower()
    if eng not in VALID_ENGINES:
        return False, "engine_invalido"
    try:
        from services.scheduling import repository as sched_repo

        if not sched_repo.supabase_available():
            return False, "supabase_indisponivel"
        sched_repo.set_scheduling_engine(
            cliente_id,
            eng,
            changed_by=(changed_by or "").strip() or None,
        )
        return True, None
    except Exception as exc:
        logger.warning("set_scheduling_engine failed cliente_id=%s err=%s", cliente_id[:8], exc)
        return False, str(exc)


def scheduling_engine_metadata(cliente_id: str) -> dict[str, Any]:
    """Metadados para admin UI."""
    try:
        from services.scheduling import repository as sched_repo

        if not sched_repo.supabase_available():
            return {}
        row = sched_repo.get_settings(cliente_id) or {}
        engine = (row.get(SchedulingSettingsModel.SCHEDULING_ENGINE) or ENGINE_AGENDAMENTO_IA).strip()
        if engine not in VALID_ENGINES:
            engine = ENGINE_AGENDAMENTO_IA
        return {
            "scheduling_engine": engine,
            "scheduling_engine_changed_at": row.get(SchedulingSettingsModel.SCHEDULING_ENGINE_CHANGED_AT),
            "scheduling_engine_changed_by": row.get(SchedulingSettingsModel.SCHEDULING_ENGINE_CHANGED_BY),
            "public_slug": row.get(SchedulingSettingsModel.PUBLIC_SLUG),
        }
    except Exception:
        return {}
