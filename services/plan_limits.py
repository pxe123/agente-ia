"""
Limites numéricos definidos em plans.entitlements_json (ex.: max_usuarios_internos, max_chatbots).
Chave ausente ou valor inválido = sem limite para aquela métrica.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

from database.supabase_sq import supabase
from database.models import Tables, ChatbotModel, UsuarioInternoModel
from services.entitlements import _admin_full_access, get_billing_state
from services.plans import plan_entitlements

LIMIT_MAX_USUARIOS_INTERNOS = "max_usuarios_internos"
LIMIT_MAX_OPERADORES = "max_operadores"
LIMIT_MAX_CHATBOTS = "max_chatbots"


def _parse_limit_value(v) -> Optional[int]:
    if v is None:
        return None
    try:
        n = int(v)
        return n if n >= 0 else None
    except (TypeError, ValueError):
        return None


def get_plan_limit_int(cliente_id: str, limit_key: str) -> Optional[int]:
    if _admin_full_access():
        return None
    if not supabase or not cliente_id:
        return None
    _, _, _, plan_key = get_billing_state(str(cliente_id))
    if not plan_key:
        return None
    ent = plan_entitlements(plan_key)
    return _parse_limit_value(ent.get(limit_key))


def count_usuarios_internos_ativos(cliente_id: str) -> int:
    if not supabase:
        return 0
    try:
        r = (
            supabase.table(Tables.USUARIOS_INTERNOS)
            .select(UsuarioInternoModel.ID)
            .eq(UsuarioInternoModel.CLIENTE_ID, cliente_id)
            .eq(UsuarioInternoModel.ATIVO, True)
            .execute()
        )
        return len(r.data or [])
    except Exception:
        return 0


def count_chatbots_cliente(cliente_id: str) -> int:
    if not supabase:
        return 0
    try:
        r = (
            supabase.table(Tables.CHATBOTS)
            .select(ChatbotModel.ID)
            .eq(ChatbotModel.CLIENTE_ID, cliente_id)
            .execute()
        )
        return len(r.data or [])
    except Exception:
        return 0


def check_usuario_interno_create_allowed(cliente_id: str) -> Tuple[bool, Optional[str]]:
    """Considera o limite mais restritivo entre max_operadores e max_usuarios_internos, se ambos existirem."""
    cid = str(cliente_id or "")
    n = count_usuarios_internos_ativos(cid)
    candidates: List[Tuple[str, int]] = []
    for k in (LIMIT_MAX_OPERADORES, LIMIT_MAX_USUARIOS_INTERNOS):
        lim = get_plan_limit_int(cid, k)
        if lim is not None:
            candidates.append((k, lim))
    if not candidates:
        return True, None
    lim_eff = min(l for _, l in candidates)
    if n >= lim_eff:
        return False, (
            f"Limite do plano: no máximo {lim_eff} operador(es) / usuário(s) interno(s) ativo(s)."
        )
    return True, None


def check_chatbot_create_allowed(cliente_id: str) -> Tuple[bool, Optional[str]]:
    lim = get_plan_limit_int(str(cliente_id), LIMIT_MAX_CHATBOTS)
    if lim is None:
        return True, None
    n = count_chatbots_cliente(str(cliente_id))
    if n >= lim:
        return False, f"Limite do plano: no máximo {lim} chatbot(s)."
    return True, None


def get_chatbot_quota(cliente_id: str) -> Dict[str, Any]:
    """
    limit=None = ilimitado no plano.
    can_create=False quando used >= limit (inclui limit==0).
    """
    cid = str(cliente_id or "").strip()
    if not cid:
        return {"limit": None, "used": 0, "can_create": True}
    lim = get_plan_limit_int(cid, LIMIT_MAX_CHATBOTS)
    used = count_chatbots_cliente(cid)
    can_create = lim is None or used < lim
    return {"limit": lim, "used": used, "can_create": can_create}
