from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Any, Dict, Optional

from database.supabase_sq import supabase
from database.models import Tables, ClienteModel
from services.routing_service import RoutingService


def _today() -> date:
    return datetime.now(timezone.utc).date()


def _normalize_phone_e164_digits(phone: str) -> str:
    # Mercado/WAHA/Meta aceitam dígitos E.164 sem '+'
    s = (phone or "").strip().replace("+", "")
    return "".join(c for c in s if c.isdigit())


def _dedupe_insert(cliente_id: str, notif_type: str, payload: Dict[str, Any]) -> bool:
    """
    Retorna True se pode enviar (inseriu dedupe), False se já enviou hoje.
    """
    if supabase is None:
        return False
    d = _today().isoformat()
    try:
        # tenta inserir; unique(cliente_id,type,day) evita duplicatas
        supabase.table("customer_notifications").insert(
            {
                "cliente_id": str(cliente_id),
                "type": notif_type,
                "day": d,
                "channel": "whatsapp",
                "status": "sent",
                "payload": payload or {},
            }
        ).execute()
        return True
    except Exception:
        return False


def send_whatsapp_notification(cliente_id: str, notif_type: str, text: str, payload: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """
    Envia notificação de cobrança via WhatsApp para o número do cliente (`clientes.notify_whatsapp`).
    Usa a infra global WAHA (settings.WAHA_URL/WAHA_API_KEY), ou seja: é o WhatsApp do seu SaaS.
    """
    if supabase is None:
        return {"ok": False, "erro": "Supabase não configurado."}

    try:
        r = (
            supabase.table(Tables.CLIENTES)
            .select(",".join([ClienteModel.ID, ClienteModel.EMAIL, ClienteModel.NOTIFY_WHATSAPP]))
            .eq(ClienteModel.ID, cliente_id)
            .single()
            .execute()
        )
        row = r.data or {}
    except Exception as e:
        return {"ok": False, "erro": str(e)}

    phone = _normalize_phone_e164_digits(row.get(ClienteModel.NOTIFY_WHATSAPP) or "")
    if not phone:
        return {"ok": False, "erro": "Cliente sem notify_whatsapp configurado."}

    # dedupe diário
    can = _dedupe_insert(cliente_id, notif_type, payload or {})
    if not can:
        return {"ok": True, "skipped": True, "motivo": "dedupe"}

    ok, err = RoutingService.enviar_resposta("whatsapp", "default", phone, text or " ", cliente_id=None)
    return {"ok": ok, "erro": err, "to": phone}

