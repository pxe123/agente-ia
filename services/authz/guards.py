from __future__ import annotations

from functools import wraps
from typing import Callable, Optional

from flask import jsonify, redirect, request, url_for
from flask_login import current_user

from base.auth import get_current_cliente_id
from services.authz.roles import resolve_role
from services.entitlements import can_use_product


def require_role(*, role: str) -> Callable:
    """
    Guard simples por role (super_admin | tenant_admin | tenant_user).
    """

    def decorator(fn: Callable) -> Callable:
        @wraps(fn)
        def wrapper(*args, **kwargs):
            rr = resolve_role(current_user)
            if rr.role == "super_admin":
                return fn(*args, **kwargs)
            if rr.role != role:
                if (request.path or "").startswith("/api/"):
                    return jsonify({"erro": "Não autorizado."}), 403
                return "Acesso negado", 403
            return fn(*args, **kwargs)

        return wrapper

    return decorator


def require_subscription(*, allow_reasons: Optional[set[str]] = None) -> Callable:
    """
    Guard comercial por tenant (não bloqueia super_admin).
    allow_reasons: reasons que não devem bloquear (ex.: só mostrar paywall).
    """
    allow_reasons = allow_reasons or set()

    def decorator(fn: Callable) -> Callable:
        @wraps(fn)
        def wrapper(*args, **kwargs):
            rr = resolve_role(current_user)
            if rr.role == "super_admin":
                return fn(*args, **kwargs)
            tenant_id = get_current_cliente_id(current_user)
            if not tenant_id:
                return jsonify({"erro": "Cliente não identificado."}), 400
            ent = can_use_product(str(tenant_id))
            if ent.allowed or ent.reason in allow_reasons:
                return fn(*args, **kwargs)
            if (request.path or "").startswith("/api/"):
                return jsonify({"erro": "Assinatura inativa.", "billing_status": ent.status, "reason": ent.reason}), 402
            return redirect(url_for("customer.dashboard"))

        return wrapper

    return decorator

