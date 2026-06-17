"""Modo de atribuição de profissional (manual vs distribuição automática)."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from services.agendamento_ia_bridge import scheduling_uses_internal_motor
from services.scheduling import repository as scheduling_repository


def uses_auto_distribution(cliente_id: str) -> bool:
    if not scheduling_uses_internal_motor(cliente_id):
        return False
    return scheduling_repository.get_assignment_mode(cliente_id) == "auto_distribution"


def uses_auto_distribution_for_panel(cliente_id: str) -> bool:
    """Distribuição automática na criação painel (inclui motor externo)."""
    return scheduling_repository.get_assignment_mode(cliente_id) == "auto_distribution"


def assignment_mode_label(mode: str) -> str:
    if mode == "auto_distribution":
        return "Distribuição automática"
    return "Cliente escolhe profissional"


def _sort_professionals(professionals: list[dict], candidate_ids: list[str]) -> list[str]:
    by_id = {str(p.get("id") or ""): p for p in professionals}
    ordered = [pid for pid in candidate_ids if pid in by_id]
    ordered.sort(
        key=lambda pid: (
            int(by_id[pid].get("sort_order") or 0),
            str(by_id[pid].get("name") or "").lower(),
            pid,
        )
    )
    return ordered


def pick_professional_round_robin(
    cliente_id: str,
    candidate_ids: list[str],
    *,
    professionals: list[dict] | None = None,
) -> str | None:
    if not candidate_ids:
        return None
    profs = professionals or scheduling_repository.list_professionals(cliente_id, active_only=True)
    ordered = _sort_professionals(profs, candidate_ids)
    if not ordered:
        return None
    if len(ordered) == 1:
        return ordered[0]
    cursor = scheduling_repository.get_distribution_cursor(cliente_id)
    if cursor and cursor in ordered:
        idx = ordered.index(cursor)
        return ordered[(idx + 1) % len(ordered)]
    return ordered[0]


def order_candidates_for_assignment(
    cliente_id: str,
    candidate_ids: list[str],
    *,
    professionals: list[dict] | None = None,
) -> list[str]:
    """Ordena candidatos para tentativa de reserva (round-robin primeiro)."""
    if not candidate_ids:
        return []
    strategy = scheduling_repository.get_distribution_strategy(cliente_id)
    profs = professionals or scheduling_repository.list_professionals(cliente_id, active_only=True)
    if strategy == "least_busy":
        # V2 placeholder: fallback round-robin
        pass
    first = pick_professional_round_robin(cliente_id, candidate_ids, professionals=profs)
    if not first:
        return _sort_professionals(profs, candidate_ids)
    rest = [p for p in _sort_professionals(profs, candidate_ids) if p != first]
    return [first, *rest]


def record_auto_assignment(cliente_id: str, professional_id: str) -> None:
    scheduling_repository.set_distribution_cursor(cliente_id, professional_id)


def build_auto_booking_meta(*, extra: dict[str, Any] | None = None) -> dict[str, Any]:
    meta: dict[str, Any] = {
        "assignment_mode": "auto",
        "assigned_by": "system",
        "assigned_at": datetime.now(timezone.utc).isoformat(),
    }
    if extra:
        meta.update(extra)
    return meta
