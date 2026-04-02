"""
Segurança partilhada entre login do dono (Supabase) e sublogin (operador):
mesmo limite por IP, mesmo token CSRF emitido em GET /login.
"""
import secrets
import time
from typing import Final

from flask import request, session

# Um único contador por IP para todos os endpoints de autenticação (evita duplicar quota).
_ATTEMPTS: dict[str, list[float]] = {}
_LIMIT: Final[int] = 10
_WINDOW_SEC: Final[int] = 15 * 60

_CSRF_MSG = "Sessão inválida. Recarregue a página."


def auth_rate_limit_exceeded(ip: str) -> bool:
    """True se o IP excedeu tentativas na janela (aplica-se a dono e funcionário)."""
    now = time.time()
    if ip not in _ATTEMPTS:
        _ATTEMPTS[ip] = []
    _ATTEMPTS[ip] = [t for t in _ATTEMPTS[ip] if now - t < _WINDOW_SEC]
    if len(_ATTEMPTS[ip]) >= _LIMIT:
        return True
    _ATTEMPTS[ip].append(now)
    return False


def login_csrf_valid() -> bool:
    """
    Valida o token emitido em session['login_csrf'] no GET /login.
    Aceita header X-CSRF-Token / X-CSRFToken ou campo csrf_token no JSON.
    """
    token = (request.headers.get("X-CSRF-Token") or request.headers.get("X-CSRFToken") or "").strip()
    if not token:
        data = request.get_json(silent=True) or {}
        token = (data.get("csrf_token") or "").strip()
    expected = (session.get("login_csrf") or "").strip()
    if not token or not expected:
        return False
    return secrets.compare_digest(token, expected)


def csrf_error_response_dono():
    """Resposta JSON para /auth/login."""
    return {"ok": False, "erro": _CSRF_MSG}


def csrf_error_response_operador():
    """Resposta JSON para /api/auth/operador-login."""
    return {"ok": False, "erro": _CSRF_MSG}


def csrf_error_response_update_access():
    """Resposta para /auth/update-access (mantém formato success/message)."""
    return {"success": False, "message": _CSRF_MSG}
