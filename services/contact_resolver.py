from __future__ import annotations

from database.supabase_sq import supabase
from database.models import Tables
from services.contact_identity import normalize_whatsapp_phone


def resolve_contact_id(cliente_id: str, canal: str, remote_id: str) -> tuple[str | None, str | None]:
    """
    Resolve (ou cria) um contact_id estável para este usuário, e garante o mapeamento
    em contact_channels.

    Retorna (contact_id, phone_normalized).

    Estratégia (WhatsApp):
    - tenta derivar phone_normalized confiável do remote_id
    - se tiver phone_normalized: busca/insere em contacts por (cliente_id, phone_normalized)
    - senão: tenta achar mapping existente em contact_channels por (cliente_id, canal, remote_id)
    - se não achar: cria contact sem telefone (phone_normalized NULL)
    - garante mapping em contact_channels (unique por cliente+canal+remote_id)
    """
    if supabase is None:
        return (None, None)

    cid = (str(cliente_id).strip() if cliente_id is not None else "") or ""
    ch = (str(canal).strip().lower() if canal is not None else "") or ""
    rid = (str(remote_id).strip() if remote_id is not None else "") or ""
    if not cid or not ch or not rid:
        return (None, None)

    phone_norm = normalize_whatsapp_phone(rid) if ch == "whatsapp" else None

    contact_id: str | None = None
    try:
        if phone_norm:
            r = (
                supabase.table(Tables.CONTACTS)
                .select("id")
                .eq("cliente_id", cid)
                .eq("phone_normalized", phone_norm)
                .limit(1)
                .execute()
            )
            if r.data and len(r.data) > 0:
                contact_id = r.data[0].get("id")
            else:
                ins = (
                    supabase.table(Tables.CONTACTS)
                    .insert({"cliente_id": cid, "phone_normalized": phone_norm})
                    .execute()
                )
                if ins.data and len(ins.data) > 0:
                    contact_id = ins.data[0].get("id")

        if not contact_id:
            r2 = (
                supabase.table(Tables.CONTACT_CHANNELS)
                .select("contact_id")
                .eq("cliente_id", cid)
                .eq("canal", ch)
                .eq("remote_id", rid)
                .limit(1)
                .execute()
            )
            if r2.data and len(r2.data) > 0:
                contact_id = r2.data[0].get("contact_id")

        if not contact_id:
            ins2 = (
                supabase.table(Tables.CONTACTS)
                .insert({"cliente_id": cid, "phone_normalized": phone_norm or None})
                .execute()
            )
            if ins2.data and len(ins2.data) > 0:
                contact_id = ins2.data[0].get("id")

        if contact_id:
            # Garante mapping (idempotente via on_conflict)
            try:
                supabase.table(Tables.CONTACT_CHANNELS).upsert(
                    {"cliente_id": cid, "contact_id": contact_id, "canal": ch, "remote_id": rid},
                    on_conflict="cliente_id,canal,remote_id",
                ).execute()
            except Exception:
                # Não falhar o fluxo por falha de mapping.
                pass
    except Exception:
        return (None, phone_norm)

    return (contact_id, phone_norm)

