"""
Web Push: envia notificação ao navegador mesmo com a aba em segundo plano.
Requer VAPID no .env e tabela painel_push_subscriptions no Supabase.
"""
import json
from database.supabase_sq import supabase
from database.models import Tables
from base.config import settings


def send_web_push_to_cliente(cliente_id, title: str, body: str) -> None:
    """
    Envia notificação Web Push para todos os dispositivos inscritos do cliente.
    Se VAPID não estiver configurado ou não houver inscrições, não faz nada.
    """
    if not getattr(settings, "VAPID_PRIVATE_KEY", None) or not settings.VAPID_PRIVATE_KEY.strip():
        return
    if supabase is None:
        return
    try:
        res = supabase.table(Tables.PUSH_SUBSCRIPTIONS).select("endpoint, p256dh, auth").eq("cliente_id", str(cliente_id)).execute()
        rows = res.data or []
    except Exception:
        return
    payload = json.dumps({"title": title, "body": body or "Nova mensagem"})
    for row in rows:
        try:
            from pywebpush import webpush
            sub = {
                "endpoint": row["endpoint"],
                "keys": {"p256dh": row["p256dh"], "auth": row["auth"]},
            }
            webpush(
                subscription_info=sub,
                data=payload,
                vapid_private_key=settings.VAPID_PRIVATE_KEY,
                vapid_claims={"sub": "mailto:agente@painel.local"},
            )
        except Exception as e:
            # 404/410 = inscrição expirada; remover do banco evita tentativas futuras
            if hasattr(e, "response") and e.response is not None:
                status = getattr(e.response, "status_code", None)
                if status in (404, 410):
                    try:
                        supabase.table(Tables.PUSH_SUBSCRIPTIONS).delete().eq("cliente_id", str(cliente_id)).eq("endpoint", row["endpoint"]).execute()
                    except Exception:
                        pass
            continue
