from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class RoleResolution:
    role: str  # super_admin | tenant_admin | tenant_user | anonymous
    source: str  # env | user_attr | tenant_flag | default


def _norm_email(v: Optional[str]) -> str:
    return (v or "").strip().casefold()


def is_super_admin_email(email: Optional[str]) -> bool:
    """
    Fail-safe: decide super_admin somente via env/config (sem DB).
    """
    try:
        from base.config import settings
    except Exception:
        return False

    e = _norm_email(email)
    if not e:
        return False

    allow = set()
    try:
        allow.add(_norm_email(getattr(settings, "ADMIN_EMAIL", None)))
    except Exception:
        pass
    try:
        allow.update({_norm_email(x) for x in (getattr(settings, "ADMIN_EMAILS", []) or [])})
    except Exception:
        pass
    try:
        allow.update({_norm_email(x) for x in (getattr(settings, "SUPER_ADMIN_EMAILS", []) or [])})
    except Exception:
        pass

    allow.discard("")
    return e in allow


def resolve_role(user) -> RoleResolution:
    """
    Resolve role do principal autenticado.

    Ordem (sem DB):
    - super_admin por e-mail (env) (fail-safe)
    - user.role (se o objeto User já tiver role carregada)
    - tenant_admin por flag is_admin_cliente (usuários internos)
    - tenant_user por default
    """
    if not user or not getattr(user, "is_authenticated", False) or not user.is_authenticated:
        return RoleResolution("anonymous", "default")

    email = getattr(user, "email", None)
    if is_super_admin_email(email):
        return RoleResolution("super_admin", "env")

    # Se em algum ponto carregarmos role do banco (Fase 2), ela entra aqui sem quebrar compat.
    raw_role = (getattr(user, "role", None) or "").strip().lower()
    if raw_role:
        return RoleResolution(raw_role, "user_attr")

    # Admin operacional do tenant (não é super_admin)
    if bool(getattr(user, "is_admin_cliente", False)):
        return RoleResolution("tenant_admin", "tenant_flag")

    return RoleResolution("tenant_user", "default")

