"""Tokens seguros para aceite/recusa de propostas de horário."""
from __future__ import annotations

import hashlib
import secrets
from datetime import datetime, timedelta, timezone
from typing import Any

from base.domain_redirects import public_base_url
from services.scheduling import repository


def _hash_token(raw: str) -> str:
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def create_proposal_token(
    *,
    cliente_id: str,
    appointment_id: str,
    proposal_id: str,
    expires_hours: int = 72,
) -> str:
    """Gera um token resolve_proposal; devolve URL único da página pública."""
    base = public_base_url().rstrip("/")
    raw = secrets.token_urlsafe(32)
    expires_at = datetime.now(timezone.utc) + timedelta(hours=max(1, expires_hours))
    repository.insert_confirmation_token(
        token_hash=_hash_token(raw),
        cliente_id=cliente_id,
        appointment_id=appointment_id,
        proposal_id=proposal_id,
        action="resolve_proposal",
        expires_at=expires_at,
    )
    return f"{base}/confirmacao/{raw}"


def create_proposal_tokens(
    *,
    cliente_id: str,
    appointment_id: str,
    proposal_id: str,
    expires_hours: int = 72,
) -> tuple[str, str]:
    """Legado: dois tokens accept/decline (links antigos)."""
    base = public_base_url().rstrip("/")
    accept_raw = secrets.token_urlsafe(32)
    decline_raw = secrets.token_urlsafe(32)
    expires_at = datetime.now(timezone.utc) + timedelta(hours=max(1, expires_hours))
    for raw, action in ((accept_raw, "accept_proposal"), (decline_raw, "decline_proposal")):
        repository.insert_confirmation_token(
            token_hash=_hash_token(raw),
            cliente_id=cliente_id,
            appointment_id=appointment_id,
            proposal_id=proposal_id,
            action=action,
            expires_at=expires_at,
        )
    return (
        f"{base}/confirmacao/{accept_raw}",
        f"{base}/confirmacao/{decline_raw}",
    )


def resolve_token(raw_token: str) -> tuple[dict[str, Any] | None, str | None]:
    """Valida token; devolve (row, erro)."""
    raw = (raw_token or "").strip()
    if not raw or len(raw) < 16:
        return None, "token_invalido"
    row = repository.get_confirmation_token_by_hash(_hash_token(raw))
    if not row:
        return None, "token_nao_encontrado"
    if row.get("used_at"):
        return None, "token_ja_usado"
    exp_raw = row.get("expires_at")
    try:
        exp = datetime.fromisoformat(str(exp_raw).replace("Z", "+00:00"))
        if exp.tzinfo is None:
            exp = exp.replace(tzinfo=timezone.utc)
    except Exception:
        return None, "token_expirado"
    if datetime.now(timezone.utc) > exp:
        return None, "token_expirado"
    return row, None
