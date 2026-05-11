from __future__ import annotations

import time
from typing import Optional, Tuple

from services.network.egress_manager import (
    enforce_on_waha_sessions,
    get_proxy_config_for_waha,
)
from services.network.egress_manager import get_profile
from services.network.egress_observability import emit


def ensure_waha_session_ready(*, cliente_id: str, session_name: str) -> Tuple[bool, Optional[str]]:
    """
    Garante que a sessão WAHA exista e esteja iniciada.
    Aplica proxy apenas na criação (via waha_client.ensure_session(proxy_config=...)).

    Retorna (ok, erro).
    """
    cid = str(cliente_id or "").strip()
    sess = (session_name or "default").strip()
    if not cid:
        # Em alguns fluxos internos o cliente pode ser None; não bloqueie globalmente.
        return True, None

    try:
        proxy_cfg = get_proxy_config_for_waha(cid)
    except Exception as e:
        emit("egress_proxy_error", cliente_id=cid, session_name=sess, data={"stage": "get_proxy_config", "error": str(e)[:500]})
        return False, str(e)

    if enforce_on_waha_sessions() and not proxy_cfg:
        return False, "Egress obrigatório: nenhum perfil de egress associado ao tenant."

    prof = None
    try:
        prof = get_profile(cid)
    except Exception:
        prof = None

    # Fail-safe/retry (3 tentativas com backoff simples)
    last_err: Optional[str] = None
    for attempt in range(1, 4):
        try:
            from integrations.whatsapp import waha_client

            waha_client.ensure_session(sess, tenant_id=cid, proxy_config=proxy_cfg)
            emit(
                "egress_profile_used",
                cliente_id=cid,
                session_name=sess,
                profile_id=(prof.id if prof else None),
            )
            return True, None
        except Exception as e:
            last_err = str(e)
            emit(
                "egress_proxy_error",
                cliente_id=cid,
                session_name=sess,
                profile_id=(prof.id if prof else None),
                data={"attempt": attempt, "error": last_err[:500]},
            )
            time.sleep(min(2 ** attempt, 8))

    return False, last_err or "Falha ao garantir sessão WAHA."

