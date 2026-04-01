from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List

from database.supabase_sq import supabase
from database.models import Tables, ClienteModel
from services.notifications_service import send_whatsapp_notification


def _parse_dt(value: str):
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except Exception:
        return None


def run_notifications() -> Dict[str, Any]:
    """
    Job periódico (ex.: diário) para disparar notificações de billing via WhatsApp.
    Regras:
    - trial_ends_at em 2 dias -> aviso
    - trial expirou (status trialing mas data passou) -> aviso
    - past_due -> aviso diário
    - canceled/inactive -> aviso diário
    - active/authorized -> (opcional) não spammar; só avisa se quiser (mantemos apenas quando virar active via webhook/reconcile no futuro)
    """
    if supabase is None:
        return {"ok": False, "erro": "Supabase não configurado."}

    now = datetime.now(timezone.utc)
    try:
        rows: List[dict] = (
            supabase.table(Tables.CLIENTES)
            .select(
                ",".join(
                    [
                        ClienteModel.ID,
                        ClienteModel.EMAIL,
                        ClienteModel.BILLING_STATUS,
                        ClienteModel.TRIAL_ENDS_AT,
                        ClienteModel.NOTIFY_WHATSAPP,
                    ]
                )
            )
            .limit(5000)
            .execute()
            .data
            or []
        )
    except Exception as e:
        return {"ok": False, "erro": str(e)}

    sent = 0
    skipped = 0
    failed = 0

    for c in rows:
        cid = c.get(ClienteModel.ID)
        if not cid:
            continue
        status = (c.get(ClienteModel.BILLING_STATUS) or "inactive").strip().lower()
        trial_dt = _parse_dt(c.get(ClienteModel.TRIAL_ENDS_AT) or "")
        phone = (c.get(ClienteModel.NOTIFY_WHATSAPP) or "").strip()
        if not phone:
            continue

        # trial expira em 2 dias
        if status == "trialing" and trial_dt:
            if now <= trial_dt and (trial_dt - now) <= timedelta(days=2):
                out = send_whatsapp_notification(
                    str(cid),
                    "trial_expira_em_breve",
                    "Seu período de teste do ZapAction está acabando. Para não perder acesso, ative sua assinatura no painel.",
                    {"trial_ends_at": trial_dt.isoformat()},
                )
                if out.get("skipped"):
                    skipped += 1
                elif out.get("ok"):
                    sent += 1
                else:
                    failed += 1
                continue
            if now > trial_dt:
                out = send_whatsapp_notification(
                    str(cid),
                    "trial_expirou",
                    "Seu período de teste do ZapAction expirou. Entre no painel para concluir o pagamento e reativar o acesso.",
                    {"trial_ends_at": trial_dt.isoformat()},
                )
                if out.get("skipped"):
                    skipped += 1
                elif out.get("ok"):
                    sent += 1
                else:
                    failed += 1
                continue

        if status == "past_due":
            out = send_whatsapp_notification(
                str(cid),
                "past_due",
                "Identificamos um problema no pagamento da sua assinatura. Entre no painel para regularizar e evitar bloqueio.",
                {"billing_status": status},
            )
            if out.get("skipped"):
                skipped += 1
            elif out.get("ok"):
                sent += 1
            else:
                failed += 1
            continue

        if status in ("canceled", "cancelled", "inactive"):
            out = send_whatsapp_notification(
                str(cid),
                "assinatura_inativa",
                "Sua assinatura do ZapAction está inativa. Entre no painel para reativar.",
                {"billing_status": status},
            )
            if out.get("skipped"):
                skipped += 1
            elif out.get("ok"):
                sent += 1
            else:
                failed += 1
            continue

    return {"ok": True, "sent": sent, "skipped": skipped, "failed": failed, "total": len(rows)}

