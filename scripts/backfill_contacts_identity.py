"""
Backfill: contacts/contact_channels + leads.contact_id + flow_user_state.contact_id

Execute com o ambiente do servidor (SUPABASE_URL/SUPABASE_KEY configurados):

python scripts/backfill_contacts_identity.py

Opções:
- DRY_RUN=1: não faz updates, só loga
"""

from __future__ import annotations

import os

from database.supabase_sq import supabase
from database.models import Tables
from services.contact_resolver import resolve_contact_id


def _is_dry_run() -> bool:
    return (os.getenv("DRY_RUN") or "").strip() in ("1", "true", "True", "yes", "YES")


def backfill_leads(batch_size: int = 500) -> None:
    if supabase is None:
        raise RuntimeError("Supabase não configurado.")

    dry = _is_dry_run()
    offset = 0
    updated = 0
    scanned = 0

    while True:
        q = (
            supabase.table(Tables.LEADS)
            .select("id,cliente_id,canal,remote_id,contact_id")
            .is_("contact_id", "null")
            .range(offset, offset + batch_size - 1)
            .execute()
        )
        rows = q.data or []
        if not rows:
            break

        for row in rows:
            scanned += 1
            lead_id = row.get("id")
            cliente_id = row.get("cliente_id")
            canal = row.get("canal")
            remote_id = row.get("remote_id")
            if not lead_id or not cliente_id or not canal or not remote_id:
                continue

            contact_id, phone_norm = resolve_contact_id(str(cliente_id), str(canal), str(remote_id))
            if not contact_id:
                continue

            if dry:
                print(f"[DRY_RUN] lead {lead_id}: set contact_id={contact_id} phone={phone_norm!r}")
                continue

            supabase.table(Tables.LEADS).update({"contact_id": contact_id}).eq("id", lead_id).execute()
            updated += 1

        offset += batch_size

    print(f"[Backfill] leads: scanned={scanned} updated={updated} dry_run={dry}")


def backfill_flow_user_state(batch_size: int = 500) -> None:
    if supabase is None:
        raise RuntimeError("Supabase não configurado.")

    dry = _is_dry_run()
    offset = 0
    updated = 0
    scanned = 0

    while True:
        q = (
            supabase.table(Tables.FLOW_USER_STATE)
            .select("cliente_id,canal,remote_id,contact_id")
            .is_("contact_id", "null")
            .range(offset, offset + batch_size - 1)
            .execute()
        )
        rows = q.data or []
        if not rows:
            break

        for row in rows:
            scanned += 1
            cliente_id = row.get("cliente_id")
            canal = row.get("canal")
            remote_id = row.get("remote_id")
            if not cliente_id or not canal or not remote_id:
                continue

            contact_id, phone_norm = resolve_contact_id(str(cliente_id), str(canal), str(remote_id))
            if not contact_id:
                continue

            if dry:
                print(f"[DRY_RUN] flow_user_state {cliente_id}/{canal}/{remote_id}: set contact_id={contact_id} phone={phone_norm!r}")
                continue

            (
                supabase.table(Tables.FLOW_USER_STATE)
                .update({"contact_id": contact_id})
                .eq("cliente_id", str(cliente_id))
                .eq("canal", str(canal))
                .eq("remote_id", str(remote_id))
                .execute()
            )
            updated += 1

        offset += batch_size

    print(f"[Backfill] flow_user_state: scanned={scanned} updated={updated} dry_run={dry}")


def main() -> None:
    print("[Backfill] iniciando backfill contacts identity...")
    backfill_leads()
    backfill_flow_user_state()
    print("[Backfill] concluído.")


if __name__ == "__main__":
    main()

