"""Política de confirmação de agendamento por tenant (auto | professional | reception)."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from services.agendamento_ia_bridge import scheduling_uses_internal_motor
from services.scheduling import repository as scheduling_repository


VALID_CONFIRMATION_POLICIES = frozenset({"auto", "professional", "reception"})


def get_confirmation_policy(cliente_id: str) -> str:
    """auto | professional | reception. Default auto."""
    st = scheduling_repository.get_settings(cliente_id) or {}
    mode = (st.get("confirmation_policy") or "auto").strip().lower()
    if mode not in VALID_CONFIRMATION_POLICIES:
        return "auto"
    if mode == "reception":
        return "auto"
    if mode == "professional" and not scheduling_uses_internal_motor(cliente_id):
        return "auto"
    return mode


def requires_professional_confirmation(cliente_id: str) -> bool:
    return get_confirmation_policy(cliente_id) == "professional"


def resolve_initial_appointment_status(cliente_id: str) -> str:
    return "pending" if requires_professional_confirmation(cliente_id) else "confirmed"


def confirmation_policy_label(mode: str) -> str:
    m = (mode or "auto").strip().lower()
    if m == "professional":
        return "Confirmação pelo profissional"
    if m == "reception":
        return "Confirmação pela recepção (em breve)"
    return "Confirmação automática"


def get_confirmation_pending_ttl_hours(cliente_id: str) -> int:
    st = scheduling_repository.get_settings(cliente_id) or {}
    try:
        ttl = int(st.get("confirmation_pending_ttl_hours") or 48)
    except (TypeError, ValueError):
        ttl = 48
    return max(1, min(ttl, 720))


def build_booking_meta_patch(cliente_id: str) -> dict[str, Any]:
    """Meta extra ao criar marcação quando política exige confirmação."""
    policy = get_confirmation_policy(cliente_id)
    if policy != "professional":
        return {}
    return {
        "confirmation_policy": policy,
        "confirmation_requested_at": datetime.now(timezone.utc).isoformat(),
    }


def can_enable_professional_confirmation(cliente_id: str) -> bool:
    return scheduling_uses_internal_motor(cliente_id)
