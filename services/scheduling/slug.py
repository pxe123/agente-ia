"""Normalização de slug público da agenda (painel + sync Agenda)."""
from __future__ import annotations

import re

_SLUG_RE = re.compile(r"[^a-z0-9]+")


def normalize_public_slug(raw: str | None) -> str | None:
    """
    Slug URL-safe: minúsculas, apenas a-z, 0-9 e hífens.

    Espaços e underscores viram hífen; caracteres inválidos removidos.
    """
    s = (raw or "").strip().lower()
    if not s:
        return None
    s = s.replace("_", "-")
    s = _SLUG_RE.sub("-", s)
    s = re.sub(r"-+", "-", s).strip("-")
    return s[:120] if s else None
