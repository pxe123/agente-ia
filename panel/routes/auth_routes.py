"""
Autenticação do dono da conta: Supabase Auth + clientes.auth_id.
"""
import os
import secrets
import time

from flask import Blueprint, request, jsonify, current_app, url_for
from flask_login import login_user

from database.supabase_sq import supabase
from database.models import Tables, ClienteModel
from base.auth import _load_cliente_as_user_by_auth_id

auth_bp = Blueprint("auth", __name__)

_AUTH_ATTEMPTS = {}
_AUTH_LIMIT = 10
_AUTH_WINDOW_SEC = 15 * 60


def _rate_limited(ip: str) -> bool:
    now = time.time()
    if ip not in _AUTH_ATTEMPTS:
        _AUTH_ATTEMPTS[ip] = []
    _AUTH_ATTEMPTS[ip] = [t for t in _AUTH_ATTEMPTS[ip] if now - t < _AUTH_WINDOW_SEC]
    if len(_AUTH_ATTEMPTS[ip]) >= _AUTH_LIMIT:
        return True
    _AUTH_ATTEMPTS[ip].append(now)
    return False


def _app_base_url() -> str:
    u = (os.getenv("APP_BASE_URL") or "").strip().rstrip("/")
    if u:
        return u
    return request.host_url.rstrip("/")


def _auth_user_id_from_create(resp):
    if hasattr(resp, "user") and resp.user is not None and hasattr(resp.user, "id"):
        return str(resp.user.id)
    if isinstance(resp, dict):
        u = resp.get("user") or resp.get("data", {}).get("user")
        if isinstance(u, dict) and u.get("id"):
            return str(u["id"])
    return None


def _create_user_email_conflict(exc: Exception) -> bool:
    """True se create_user falhou porque o e-mail já existe no Auth."""
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


def _find_auth_user_id_by_email_list(email: str) -> str | None:
    """
    Localiza auth.users.id por e-mail via Admin list_users (paginado).
    Usado só quando create_user indica conflito ou falha recuperável.
    """
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
            current_app.logger.warning("list_users page=%s: %s", page, e)
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


def _ensure_cliente_auth_id(cliente_pk, email: str) -> str | None:
    """
    Garante clientes.auth_id: tenta create_user; se e-mail já existir no Auth,
    obtém o id via list_users e grava em clientes. Não cria segundo usuário.
    """
    temp_pw = secrets.token_urlsafe(32)

    def _persist_auth_id(aid: str) -> str | None:
        try:
            supabase.table(Tables.CLIENTES).update({ClienteModel.AUTH_ID: aid}).eq(ClienteModel.ID, cliente_pk).execute()
            return aid
        except Exception as up_err:
            current_app.logger.warning("update_access gravar auth_id: %s", up_err)
            return None

    try:
        resp = supabase.auth.admin.create_user(
            {
                "email": email,
                "password": temp_pw,
                "email_confirm": True,
            }
        )
        new_id = _auth_user_id_from_create(resp)
        if new_id:
            return _persist_auth_id(new_id)
        current_app.logger.warning("update_access: create_user sem id na resposta; tentando localizar por e-mail")
        fallback = _find_auth_user_id_by_email_list(email)
        if fallback:
            return _persist_auth_id(fallback)
    except Exception as e:
        if not _create_user_email_conflict(e):
            current_app.logger.warning("update_access create_user: %s", e)
        existing_id = _find_auth_user_id_by_email_list(email)
        if existing_id:
            return _persist_auth_id(existing_id)
        current_app.logger.warning("update_access: não foi possível resolver auth_id para o e-mail após create: %s", e)
    return None


def _sign_in_with_password(email: str, password: str):
    if supabase is None:
        return None, "Supabase não configurado."
    try:
        res = supabase.auth.sign_in_with_password({"email": email.strip(), "password": password})
    except Exception as e:
        current_app.logger.warning("sign_in_with_password: %s", e)
        return None, "E-mail ou senha incorretos."
    u = getattr(res, "user", None)
    if u is None and hasattr(res, "session") and res.session is not None:
        u = getattr(res.session, "user", None)
    if u is None:
        return None, "E-mail ou senha incorretos."
    uid = getattr(u, "id", None) if not isinstance(u, dict) else u.get("id")
    if not uid:
        return None, "E-mail ou senha incorretos."
    return {"id": str(uid)}, None


@auth_bp.route("/update-access", methods=["POST"])
def update_access():
    if supabase is None:
        return jsonify({"success": False, "message": "Serviço indisponível."}), 503
    data = request.get_json(silent=True) or {}
    email = (data.get("email") or "").strip().lower()
    ip = request.remote_addr or "unknown"
    generic = {"success": True, "message": "Se o e-mail estiver cadastrado, você receberá instruções."}
    if _rate_limited(ip):
        return jsonify(generic), 200
    if not email or "@" not in email:
        return jsonify(generic), 200

    try:
        r = supabase.table(Tables.CLIENTES).select("id,email,auth_id").eq(ClienteModel.EMAIL, email).execute()
    except Exception as e:
        current_app.logger.warning("update_access select: %s", e)
        return jsonify(generic), 200

    if not r.data:
        return jsonify(generic), 200

    row = r.data[0]
    cliente_pk = row.get("id")
    auth_id = row.get("auth_id")

    if auth_id is None:
        auth_id = _ensure_cliente_auth_id(cliente_pk, email)

    if not auth_id:
        return jsonify(generic), 200

    redirect_to = f"{_app_base_url()}/nova-senha"
    try:
        supabase.auth.reset_password_for_email(email, {"redirect_to": redirect_to})
    except Exception as e:
        current_app.logger.warning("reset_password_for_email: %s", e)
        # Mesma resposta genérica (evita 4xx/5xx no cliente; e-mail pode falhar por entrega)
        return jsonify(generic), 200

    return jsonify(generic), 200


_LOGIN_ERRO_GENERICO = "E-mail ou senha incorretos."


@auth_bp.route("/login", methods=["POST"])
def login_auth():
    if supabase is None:
        return jsonify({"ok": False, "erro": "Supabase não configurado."}), 503
    data = request.get_json(silent=True) or {}
    email = (data.get("email") or "").strip()
    password = data.get("password") or ""
    if not email or not password:
        return jsonify({"ok": False, "erro": "Preencha e-mail e senha."}), 400
    ip = request.remote_addr or "unknown"
    if _rate_limited(ip):
        return jsonify({"ok": False, "erro": "Muitas tentativas. Aguarde alguns minutos."}), 429

    uauth, err = _sign_in_with_password(email, password)
    if err or not uauth:
        return jsonify({"ok": False, "erro": err or _LOGIN_ERRO_GENERICO}), 401

    auth_id = uauth["id"]
    user = _load_cliente_as_user_by_auth_id(auth_id)
    if not user:
        # Log só no servidor; resposta idêntica a credenciais inválidas (sem revelar que o Auth aceitou).
        current_app.logger.info("login_auth: Supabase autenticou mas sem clientes.auth_id=%s", auth_id)
        try:
            supabase.auth.sign_out()
        except Exception:
            pass
        return jsonify({"ok": False, "erro": _LOGIN_ERRO_GENERICO}), 401

    login_user(user)
    try:
        supabase.auth.sign_out()
    except Exception:
        pass
    return jsonify({"ok": True, "redirect": url_for("customer.dashboard")}), 200