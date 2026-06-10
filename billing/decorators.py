from __future__ import annotations

from functools import wraps
from typing import Any, Callable, TypeVar, cast

from flask import jsonify, redirect, request, url_for
from flask_login import current_user

from base.auth import get_current_cliente_id
from services.entitlements import can_use_product

F = TypeVar("F", bound=Callable[..., Any])


def subscription_required(fn: F) -> F:
    """
    Bloqueia endpoint se a assinatura do tenant não estiver válida.

    Observação: o app já faz um bloqueio global em `app.py` para a maioria das rotas.
    Este decorator é útil para endpoints novos/pontuais e para deixar explícita a dependência.
    """

    @wraps(fn)
    def wrapper(*args: Any, **kwargs: Any):
        if not getattr(current_user, "is_authenticated", False):
            # Mantém comportamento consistente com o app (API = 401 JSON).
            if (request.path or "").startswith("/api/"):
                return jsonify({"erro": "Sessão expirada", "redirect": "/"}), 401
            return redirect(url_for("customer.login"))

        cid = get_current_cliente_id(current_user)
        if not cid:
            return jsonify({"erro": "Cliente não identificado na sessão."}), 400

        ent = can_use_product(str(cid))
        if not ent.allowed:
            if (request.path or "").startswith("/api/"):
                return (
                    jsonify(
                        {
                            "erro": "Assinatura inativa. Atualize o pagamento para continuar.",
                            "billing_status": ent.status,
                            "reason": ent.reason,
                        }
                    ),
                    402,
                )
            return redirect(url_for("customer.dashboard"))

        return fn(*args, **kwargs)

    return cast(F, wrapper)

