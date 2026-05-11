from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Any, Dict

from database.supabase_sq import supabase
from database.models import Tables, MensagemModel, LeadModel


def snapshot_usage_daily(cliente_id: str, *, day: date | None = None) -> Dict[str, Any]:
    """
    Base mínima de usage por tenant.
    Best-effort: calcula contagens simples e tenta gravar em tenant_usage_daily.
    """
    cid = str(cliente_id or "").strip()
    if not cid or not supabase:
        return {"ok": False, "cliente_id": cid, "day": None}

    day = day or datetime.now(timezone.utc).date()
    start = datetime(day.year, day.month, day.day, tzinfo=timezone.utc).isoformat()
    end = datetime(day.year, day.month, day.day, tzinfo=timezone.utc).replace(hour=23, minute=59, second=59).isoformat()

    messages_count = 0
    leads_count = 0
    try:
        r = (
            supabase.table(Tables.MENSAGENS)
            .select(MensagemModel.ID)
            .eq(MensagemModel.CLIENTE_ID, cid)
            .gte(MensagemModel.CRIADO_EM, start)
            .lte(MensagemModel.CRIADO_EM, end)
            .execute()
        )
        messages_count = len(r.data or [])
    except Exception:
        messages_count = 0

    try:
        r2 = (
            supabase.table(Tables.LEADS)
            .select(LeadModel.ID)
            .eq(LeadModel.CLIENTE_ID, cid)
            .gte(LeadModel.CREATED_AT, start)
            .lte(LeadModel.CREATED_AT, end)
            .execute()
        )
        leads_count = len(r2.data or [])
    except Exception:
        leads_count = 0

    payload = {
        "cliente_id": cid,
        "day": str(day),
        "messages_count": int(messages_count),
        "conversations_count": 0,
        "leads_count": int(leads_count),
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }
    try:
        supabase.table("tenant_usage_daily").upsert(payload, on_conflict="cliente_id,day").execute()
    except Exception:
        pass
    return {"ok": True, **payload}

