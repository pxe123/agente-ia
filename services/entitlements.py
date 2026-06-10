from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional, Tuple

from base.config import settings
from database.supabase_sq import supabase
from database.models import Tables, ClienteModel
from services.plans import plan_entitlements
from services.app_settings import get_global_settings


def _admin_full_access() -> bool:
    """Admins da plataforma (g.admin_full_access): ignoram plano, billing e limites de canal em requisição HTTP."""
    try:
        from flask import has_request_context, g

        if not has_request_context():
            return False
        return bool(getattr(g, "admin_full_access", False))
    except Exception:
        return False


def _parse_limit_int(v: Any) -> Optional[int]:
    if v is None:
        return None
    try:
        n = int(v)
        return n if n >= 0 else None
    except (TypeError, ValueError):
        return None


def check_limit_reached(cliente_id: str, feature_key: str, current_count: int) -> bool:
    """
    True se current_count já atingiu ou ultrapassou o limite numérico em entitlements_json
    para feature_key (ex.: max_operadores, max_usuarios_internos).
    Chave ausente ou inválida = sem limite (retorna False).
    """
    if _admin_full_access():
        return False
    cid = str(cliente_id or "").strip()
    if not cid or not feature_key:
        return False
    _, _, _, plan_key = get_billing_state(cid)
    if not plan_key:
        return False
    ent_map: Dict[str, Any] = plan_entitlements(plan_key)
    if not ent_map:
        return False
    lim = _parse_limit_int(ent_map.get(feature_key))
    if lim is None:
        return False
    return int(current_count) >= lim


@dataclass(frozen=True)
class EntitlementResult:
    allowed: bool
    status: str
    reason: str


def _parse_dt(value: str) -> Optional[datetime]:
    if not value:
        return None
    try:
        # Aceita ISO com timezone
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except Exception:
        return None


def get_billing_state(cliente_id: str) -> Tuple[str, Optional[datetime], Optional[datetime], Optional[str]]:
    """
    Retorna (billing_status, current_period_end_dt, trial_ends_at_dt, plan_key).
    Se colunas não existirem ainda, retorna ('active', None) para não quebrar o app.
    """
    if not supabase:
        return "active", None, None, None

    # Fonte de verdade (Fase 3): subscriptions por tenant, com fallback para clientes.billing_*
    try:
        from services.billing.subscription_service import get_tenant_subscription_state

        st, period_end, trial_end, plan_key = get_tenant_subscription_state(str(cliente_id))
        return st, period_end, trial_end, plan_key
    except Exception:
        pass
    try:
        res = (
            supabase.table(Tables.CLIENTES)
            .select(
                ",".join(
                    [
                        getattr(ClienteModel, "BILLING_STATUS", "billing_status"),
                        getattr(ClienteModel, "BILLING_CURRENT_PERIOD_END", "billing_current_period_end"),
                        getattr(ClienteModel, "TRIAL_ENDS_AT", "trial_ends_at"),
                        getattr(ClienteModel, "BILLING_PLAN_KEY", "billing_plan_key"),
                        getattr(ClienteModel, "BILLING_CANCEL_AT_PERIOD_END", "billing_cancel_at_period_end"),
                    ]
                )
            )
            .eq(ClienteModel.ID, cliente_id)
            .limit(1)
            .execute()
        )
        row = res.data[0] if res.data else {}
        status = (row.get(getattr(ClienteModel, "BILLING_STATUS", "billing_status")) or "active").strip().lower()
        period_end = row.get(getattr(ClienteModel, "BILLING_CURRENT_PERIOD_END", "billing_current_period_end")) or None
        dt = _parse_dt(str(period_end)) if period_end else None
        trial_end = row.get(getattr(ClienteModel, "TRIAL_ENDS_AT", "trial_ends_at")) or None
        trial_dt = _parse_dt(str(trial_end)) if trial_end else None
        plan_key = (row.get(getattr(ClienteModel, "BILLING_PLAN_KEY", "billing_plan_key")) or "").strip() or None

        # Cancelamento agendado: mantém acesso até o fim do período atual
        try:
            cancel_flag = bool(row.get(getattr(ClienteModel, "BILLING_CANCEL_AT_PERIOD_END", "billing_cancel_at_period_end")))
        except Exception:
            cancel_flag = False
        if cancel_flag and dt and datetime.now(timezone.utc) <= dt:
            status = "cancel_scheduled"
        return status, dt, trial_dt, plan_key
    except Exception:
        # Schema antigo (sem colunas) ou RLS bloqueando select
        return "active", None, None, None


def _is_super_admin_tenant(cliente_id: str | None) -> bool:
    """True se cliente_id está em SUPER_ADMIN_TENANT_IDS (.env); não depende de request/sessão."""
    cid = str(cliente_id or "").strip().lower()
    if not cid:
        return False
    try:
        raw = list(getattr(settings, "SUPER_ADMIN_TENANT_IDS", []) or [])
    except Exception:
        raw = []
    allow = {str(x).strip().lower() for x in raw if str(x).strip()}
    return cid in allow


def _get_signup_flow_version(cliente_id: str) -> int:
    """
    Versão do funil de signup.
    Best-effort: se coluna não existir/RLS falhar, assume legado (1).
    """
    if not supabase:
        return 1
    try:
        # Evita depender de schema em signatures: usa literal da coluna.
        r = (
            supabase.table(Tables.CLIENTES)
            .select(getattr(ClienteModel, "SIGNUP_FLOW_VERSION", "signup_flow_version"))
            .eq(ClienteModel.ID, cliente_id)
            .limit(1)
            .execute()
        )
        row = r.data[0] if r.data else {}
        v = row.get(getattr(ClienteModel, "SIGNUP_FLOW_VERSION", "signup_flow_version"))
        return int(v) if v is not None else 1
    except Exception:
        return 1


def can_use_product(cliente_id: str) -> EntitlementResult:
    if _admin_full_access():
        return EntitlementResult(True, "active", "admin_master")
    if _is_super_admin_tenant(cliente_id):
        return EntitlementResult(True, "active", "super_admin_tenant")
    status, period_end, trial_end, plan_key = get_billing_state(cliente_id)

    # Expiração de trial (best-effort). Se expirou, bloqueia.
    if status == "trialing" and trial_end and datetime.now(timezone.utc) > trial_end:
        # Legacy (v1): trial expirou -> bloqueia.
        # Onboarding funnel (v2): trial expirou -> ativa automaticamente (pending->trialing->active).
        flow_v = _get_signup_flow_version(cliente_id)
        if flow_v != 2:
            try:
                supabase.table(Tables.CLIENTES).update(
                    {getattr(ClienteModel, "BILLING_STATUS", "billing_status"): "inactive"}
                ).eq(ClienteModel.ID, cliente_id).execute()
            except Exception:
                pass
            return EntitlementResult(False, "inactive", "trial_expirado")

        # v2: promove trial -> active.
        try:
            supabase.table(Tables.CLIENTES).update(
                {
                    getattr(ClienteModel, "BILLING_STATUS", "billing_status"): "active",
                    getattr(ClienteModel, "TRIAL_ENDS_AT", "trial_ends_at"): None,
                }
            ).eq(ClienteModel.ID, cliente_id).execute()
        except Exception:
            pass
        try:
            from database.models import SubscriptionModel
            supabase.table(Tables.SUBSCRIPTIONS).upsert(
                {
                    SubscriptionModel.CLIENTE_ID: str(cliente_id),
                    SubscriptionModel.PROVIDER: "stripe",
                    SubscriptionModel.STATUS: "active",
                    SubscriptionModel.UPDATED_AT: datetime.utcnow().isoformat(),
                },
                on_conflict=SubscriptionModel.CLIENTE_ID,
            ).execute()
        except Exception:
            pass
        return EntitlementResult(True, "active", "ok")

    # Onboarding funnel: sem acesso operacional até checkout Stripe confirmar.
    if status == "onboarding":
        return EntitlementResult(False, "onboarding", "conta_em_onboarding")

    # Pendente: checkout iniciado ou cobrança ainda não confirmada.
    # Nunca deve liberar acesso (mesmo em ambiente de desenvolvimento).
    if status == "pending":
        return EntitlementResult(False, status, "assinatura_pendente")

    # Blindagem: não liberar acesso "ativo" sem assinatura válida referenciada.
    # Stripe (padrão): exige stripe_subscription_id em produção.
    # Legacy MP (graça read-only): mp_preapproval_id + período ainda válido.
    if status in ("active", "authorized", "cancel_scheduled"):
        try:
            from services.billing.subscription_service import is_legacy_mercadopago_grace

            r = (
                supabase.table(Tables.CLIENTES)
                .select(
                    ",".join(
                        [
                            getattr(ClienteModel, "MP_PREAPPROVAL_ID", "mp_preapproval_id"),
                            "stripe_subscription_id",
                            getattr(ClienteModel, "BILLING_CURRENT_PERIOD_END", "billing_current_period_end"),
                        ]
                    )
                )
                .eq(ClienteModel.ID, cliente_id)
                .limit(1)
                .execute()
            )
            row = r.data[0] if r.data else {}
            pid = (row.get(getattr(ClienteModel, "MP_PREAPPROVAL_ID", "mp_preapproval_id")) or "").strip()
            sid = (row.get("stripe_subscription_id") or "").strip()
            period_end_raw = row.get(getattr(ClienteModel, "BILLING_CURRENT_PERIOD_END", "billing_current_period_end"))
            period_end_dt = _parse_dt(str(period_end_raw)) if period_end_raw else None
        except Exception:
            pid = ""
            sid = ""
            period_end_dt = None

        if sid:
            pass  # Stripe ativo — ok
        elif pid and is_legacy_mercadopago_grace(str(cliente_id), status, period_end_dt):
            pass  # graça MP até fim do período
        elif getattr(settings, "ENVIRONMENT", "development") == "production":
            return EntitlementResult(False, "inactive", "assinatura_inativa")

    # status normalizados (Stripe / interno)
    # Regras de acesso: pending/past_due/cancel/inactive bloqueiam imediatamente.
    # trialing e cancel_scheduled continuam liberados até o fim do período.
    if status in ("active", "authorized", "trialing", "cancel_scheduled"):
        return EntitlementResult(True, status, "ok")

    if status == "past_due":
        grace_days = int(getattr(settings, "BILLING_GRACE_DAYS", 0) or 0)
        if grace_days > 0 and period_end:
            from datetime import timedelta

            grace_until = period_end + timedelta(days=grace_days)
            if datetime.now(timezone.utc) <= grace_until:
                return EntitlementResult(True, status, "past_due_grace")
        return EntitlementResult(False, status, "assinatura_em_atraso")

    if status in ("canceled", "cancelled", "inactive"):
        return EntitlementResult(False, status, "assinatura_inativa")

    # Desconhecido: por segurança, bloqueia em produção; em dev permite
    if getattr(settings, "ENVIRONMENT", "development") == "production":
        return EntitlementResult(False, status, "status_desconhecido")
    return EntitlementResult(True, status, "status_desconhecido_dev")


def can_access_feature(cliente_id: str, feature_key: str) -> bool:
    """
    Verifica entitlement por feature no plano associado ao cliente.
    Feature keys: whatsapp, instagram, messenger, site, exports, flow_builder, chatbots,
    usuarios_setores, agenda, etc.
    """
    if _admin_full_access():
        return True
    # se não pode usar produto, não acessa feature paga
    ent = can_use_product(cliente_id)
    if not ent.allowed:
        return False
    _, _, _, plan_key = get_billing_state(cliente_id)
    if not plan_key:
        return True  # compat: sem plano cadastrado, não bloqueia
    ent_map: Dict[str, Any] = plan_entitlements(plan_key)
    if not ent_map:
        return True
    v = ent_map.get(feature_key)
    if v is None:
        return True
    return bool(v)


def can_use_channel(cliente_id: str | None, canal: str) -> bool:
    """
    Flags globais (app_settings / cache) primeiro; depois entitlements do plano.
    Site: só plano (sem kill switch global nesta tabela).
    """
    if _admin_full_access():
        c = (canal or "").strip().lower()
        if c == "messenger":
            c = "facebook"
        return c in ("whatsapp", "website", "site", "instagram", "facebook")
    if not cliente_id:
        return False
    cid = str(cliente_id).strip()
    if not cid:
        return False

    c = (canal or "").strip().lower()
    if c == "messenger":
        c = "facebook"

    flags = get_global_settings()

    if c == "whatsapp":
        if not bool(flags.get("whatsapp_enabled", True)):
            return False
        return can_access_feature(cid, "whatsapp")
    if c in ("website", "site"):
        return can_access_feature(cid, "site")
    if c == "instagram":
        if not bool(flags.get("instagram_enabled", True)):
            return False
        return can_access_feature(cid, "instagram")
    if c == "facebook":
        if not bool(flags.get("messenger_enabled", True)):
            return False
        return can_access_feature(cid, "messenger")
    return False

