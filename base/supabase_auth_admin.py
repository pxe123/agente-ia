"""
Helpers para Supabase Auth Admin (criar utilizador, localizar por e-mail, atualizar senha).
Usado pelo fluxo unificado de login e pela gestão de funcionários.
"""
from __future__ import annotations

from flask import current_app

from database.supabase_sq import supabase


def _user_id_from_obj(u) -> str | None:
    if u is None:
        return None
    if isinstance(u, dict):
        uid = u.get("id")
        return str(uid) if uid else None
    uid = getattr(u, "id", None)
    return str(uid) if uid else None


def auth_user_id_from_admin_response(resp) -> str | None:
    """
    Extrai auth.users.id da resposta de auth.admin.create_user / update (várias versões supabase-py / gotrue).
    """
    if resp is None:
        return None
    u = getattr(resp, "user", None)
    if u is not None:
        got = _user_id_from_obj(u)
        if got:
            return got
    sess = getattr(resp, "session", None)
    if sess is not None:
        su = getattr(sess, "user", None) if not isinstance(sess, dict) else sess.get("user")
        got = _user_id_from_obj(su)
        if got:
            return got
    if isinstance(resp, dict):
        u = resp.get("user") or resp.get("data", {}).get("user")
        if isinstance(u, dict) and u.get("id"):
            return str(u["id"])
    return None


def create_user_email_conflict(exc: Exception) -> bool:
    msg = str(exc).lower()
    hints = (
        "already been registered",
        "already registered",
        "user already registered",
        "email address is already",
        "duplicate key",
        "users_email_partial_key",
        "email_exists",
    )
    return any(h in msg for h in hints)


def find_auth_user_id_by_email(email: str) -> str | None:
    """Localiza auth.users.id por e-mail (list_users paginado)."""
    if supabase is None:
        return None
    email_norm = (email or "").strip().lower()
    if not email_norm:
        return None
    page = 1
    per_page = 200
    max_pages = 100
    while page <= max_pages:
        try:
            users = supabase.auth.admin.list_users(page=page, per_page=per_page)
        except Exception as e:
            current_app.logger.warning("find_auth_user_id_by_email page=%s: %s", page, e)
            return None
        if not users:
            return None
        for u in users:
            em = (getattr(u, "email", None) or "").strip().lower()
            if em == email_norm:
                uid = getattr(u, "id", None)
                return str(uid) if uid else None
        if len(users) < per_page:
            break
        page += 1
    return None


def update_user_password(auth_uid: str, new_password: str) -> bool:
    """Define nova senha no Supabase Auth (service role)."""
    if supabase is None or not auth_uid or not new_password:
        return False
    try:
        supabase.auth.admin.update_user_by_id(auth_uid, {"password": new_password})
        return True
    except Exception as e:
        current_app.logger.warning("update_user_password: %s", e)
        return False


def delete_auth_user(auth_uid: str) -> bool:
    """Remove utilizador do Auth (rollback após falha ao gravar linha em BD)."""
    if supabase is None or not auth_uid:
        return False
    try:
        supabase.auth.admin.delete_user(auth_uid)
        return True
    except Exception as e:
        current_app.logger.warning("delete_auth_user: %s", e)
        return False
