from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from flask import Blueprint, current_app, jsonify, request
from flask_login import login_required, current_user
from stripe import StripeError

from base.auth import get_current_cliente_id
from base.config import settings
from base.request_security import strip_untrusted_tenant_ids
from billing.decorators import subscription_required
from billing.stripe_service import (
    cliente_billing_patch,
    construct_webhook_event,
    create_checkout_session,
    create_customer_portal,
    log_event_summary,
    parse_subscription_from_event,
    resolve_cliente_id_for_webhook,
    stripe_checkout_ready_for_plan,
    stripe_env_diagnostics,
)
from services.plans import get_plan
from database.models import BillingEventModel, ClienteModel, SubscriptionModel, Tables
from database.supabase_sq import supabase
from services.billing.subscription_service import upsert_tenant_subscription
from services.plans import get_plan_for_cliente

logger = logging.getLogger(__name__)

billing_bp = Blueprint("billing", __name__, url_prefix="/api/billing")
stripe_billing_bp = Blueprint("stripe_billing", __name__, url_prefix="/api/billing/stripe")


def _require_supabase():
    if supabase is None:
        return jsonify({"ok": False, "erro": "Supabase não configurado no servidor."}), 503
    return None


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _cliente_row(cliente_id: str) -> Dict[str, Any]:
    if supabase is None:
        return {}
    try:
        r = (
            supabase.table(Tables.CLIENTES)
            .select(
                ",".join(
                    [
                        ClienteModel.ID,
                        ClienteModel.EMAIL,
                        getattr(ClienteModel, "BILLING_PLAN_KEY", "billing_plan_key"),
                        getattr(ClienteModel, "BILLING_STATUS", "billing_status"),
                        getattr(ClienteModel, "BILLING_CURRENT_PERIOD_END", "billing_current_period_end"),
                        getattr(ClienteModel, "TRIAL_ENDS_AT", "trial_ends_at"),
                        "stripe_customer_id",
                        "stripe_subscription_id",
                        "stripe_price_id",
                        getattr(ClienteModel, "MP_PREAPPROVAL_ID", "mp_preapproval_id"),
                    ]
                )
            )
            .eq(ClienteModel.ID, cliente_id)
            .limit(1)
            .execute()
        )
        return r.data[0] if r.data else {}
    except Exception:
        # Compat: schema antigo sem colunas Stripe -> retorna somente colunas já garantidas
        try:
            r = (
                supabase.table(Tables.CLIENTES)
                .select(
                    ",".join(
                        [
                            ClienteModel.ID,
                            ClienteModel.EMAIL,
                            getattr(ClienteModel, "BILLING_PLAN_KEY", "billing_plan_key"),
                            getattr(ClienteModel, "BILLING_STATUS", "billing_status"),
                            getattr(ClienteModel, "BILLING_CURRENT_PERIOD_END", "billing_current_period_end"),
                            getattr(ClienteModel, "TRIAL_ENDS_AT", "trial_ends_at"),
                        ]
                    )
                )
                .eq(ClienteModel.ID, cliente_id)
                .limit(1)
                .execute()
            )
            return r.data[0] if r.data else {}
        except Exception:
            return {}


@billing_bp.route("/status", methods=["GET"])
@login_required
def billing_status():
    sup = _require_supabase()
    if sup:
        return sup

    cliente_id = get_current_cliente_id(current_user)
    if not cliente_id:
        return jsonify({"ok": False, "erro": "Cliente não identificado na sessão."}), 400

    row = _cliente_row(str(cliente_id))
    if not row:
        return jsonify({"ok": False, "erro": "Cliente não encontrado."}), 404
    return jsonify({"ok": True, "cliente": row})


@billing_bp.route("/cancel-at-period-end", methods=["POST"])
@login_required
def billing_cancel_at_period_end():
    """
    Agenda cancelamento no fim do período (somente legado MP sem Stripe).
    Não chama API externa — entitlements bloqueiam após period_end.
    """
    sup = _require_supabase()
    if sup:
        return sup

    cliente_id = get_current_cliente_id(current_user)
    if not cliente_id:
        return jsonify({"ok": False, "erro": "Cliente não identificado na sessão."}), 400

    row = _cliente_row(str(cliente_id)) or {}
    sid = (row.get("stripe_subscription_id") or "").strip()
    if sid:
        return jsonify(
            {
                "ok": False,
                "erro": "Use o portal Stripe para gerenciar cancelamento (assinatura Stripe ativa).",
            }
        ), 400

    pid = (row.get(getattr(ClienteModel, "MP_PREAPPROVAL_ID", "mp_preapproval_id")) or "").strip()
    if not pid:
        return jsonify({"ok": False, "erro": "Nenhuma assinatura ativa para cancelar."}), 400

    try:
        supabase.table(Tables.CLIENTES).update(
            {
                getattr(ClienteModel, "BILLING_CANCEL_AT_PERIOD_END", "billing_cancel_at_period_end"): True,
                getattr(ClienteModel, "BILLING_CANCEL_SCHEDULED_AT", "billing_cancel_scheduled_at"): _now_iso(),
            }
        ).eq(ClienteModel.ID, cliente_id).execute()
    except Exception as e:
        return jsonify({"ok": False, "erro": f"Falha ao agendar cancelamento: {e}"}), 400

    row2 = _cliente_row(str(cliente_id)) or row
    return jsonify({"ok": True, "scheduled": True, "cliente": row2})


@stripe_billing_bp.route("/config", methods=["GET"])
@login_required
def stripe_config():
    """
    Retorna config pública para o frontend (publishable_key).
    """
    diag = stripe_env_diagnostics()
    return jsonify(
        {
            "ok": True,
            "publishable_key": (getattr(settings, "STRIPE_PUBLISHABLE_KEY", "") or "").strip(),
            "stripe_ready": bool(diag.get("ready")),
            "stripe": diag,
        }
    )


def _checkout_failure(message: str, detail: str, *, status: int = 400):
    return jsonify({"ok": False, "erro": message, "detail": detail[:500]}), status


@stripe_billing_bp.route("/create-checkout-session", methods=["POST"])
@login_required
def stripe_create_checkout_session():
    try:
        sup = _require_supabase()
        if sup:
            return sup

        cliente_id = get_current_cliente_id(current_user)
        if not cliente_id:
            return jsonify({"ok": False, "erro": "Cliente não identificado na sessão."}), 400

        body = strip_untrusted_tenant_ids(request.get_json(silent=True) or {})
        plan_key_raw = (body.get("plan_key") or "").strip()
        if not plan_key_raw:
            return jsonify({"ok": False, "erro": "plan_key é obrigatório."}), 400

        plan = get_plan(plan_key_raw)
        if not plan:
            return _checkout_failure(
                "Plano inválido para checkout.",
                f"unknown_plan_key:{plan_key_raw}",
            )

        ready, ready_detail = stripe_checkout_ready_for_plan(plan_key_raw)
        if not ready:
            return _checkout_failure(
                "Stripe não está configurado para este plano.",
                ready_detail,
                status=503,
            )

        row = _cliente_row(str(cliente_id))
        email = (row.get(ClienteModel.EMAIL) or getattr(current_user, "email", "") or "").strip().lower()

        success_url = (body.get("success_url") or getattr(settings, "STRIPE_SUCCESS_URL", "") or "").strip()
        cancel_url = (body.get("cancel_url") or getattr(settings, "STRIPE_CANCEL_URL", "") or "").strip()
        if not success_url or not cancel_url:
            return (
                jsonify(
                    {
                        "ok": False,
                        "erro": "STRIPE_SUCCESS_URL e STRIPE_CANCEL_URL precisam estar configuradas (ou enviar success_url/cancel_url).",
                    }
                ),
                503,
            )
        for label, url in (("success_url", success_url), ("cancel_url", cancel_url)):
            if not url.startswith(("http://", "https://")):
                return _checkout_failure(
                    "URL de retorno inválida.",
                    f"{label} deve começar com https:// (recebido: {url[:80]})",
                )

        trial_days: Optional[int] = None
        try:
            trial_end = row.get(getattr(ClienteModel, "TRIAL_ENDS_AT", "trial_ends_at"))
            plan_obj = get_plan_for_cliente(plan_key_raw, str(cliente_id))
            td = int((plan_obj or {}).get("trial_days") or 0)
            if td > 0 and not trial_end:
                trial_days = td
        except Exception:
            trial_days = None

        stripe_customer_id = (row.get("stripe_customer_id") or "").strip() or None
        checkout_url, customer_id, session_id = create_checkout_session(
            cliente_id=str(cliente_id),
            user_id=str(getattr(current_user, "id", "") or ""),
            email=email,
            plan_key=plan_key_raw,
            stripe_customer_id=stripe_customer_id,
            success_url=success_url,
            cancel_url=cancel_url,
            trial_days=trial_days,
        )
    except ValueError as e:
        current_app.logger.warning(
            "billing: stripe checkout failed cliente_id=%s err=%s",
            locals().get("cliente_id"),
            str(e),
        )
        return _checkout_failure("Falha ao criar checkout Stripe.", str(e))
    except StripeError as e:
        detail = (getattr(e, "user_message", None) or str(e) or "stripe_error")
        current_app.logger.warning(
            "billing: stripe checkout api error cliente_id=%s err=%s",
            locals().get("cliente_id"),
            detail[:500],
        )
        return _checkout_failure("Falha ao criar checkout Stripe.", detail)
    except Exception as e:
        current_app.logger.exception(
            "billing: stripe checkout exception cliente_id=%s",
            locals().get("cliente_id"),
        )
        return _checkout_failure("Falha ao criar checkout Stripe.", str(e), status=500)

    # Compat: marca pending até webhook confirmar.
    try:
        supabase.table(Tables.CLIENTES).update(
            {
                getattr(ClienteModel, "BILLING_PLAN_KEY", "billing_plan_key"): plan_key_raw,
                getattr(ClienteModel, "PLANO", "plano"): plan_key_raw,
                getattr(ClienteModel, "BILLING_STATUS", "billing_status"): "pending",
                "stripe_customer_id": customer_id,
                "stripe_price_id": None,
                "stripe_subscription_id": None,
                getattr(ClienteModel, "BILLING_PENDING_PLAN_KEY", "billing_pending_plan_key"): None,
                getattr(ClienteModel, "BILLING_PENDING_PLAN_CHANGE_AT", "billing_pending_plan_change_at"): None,
                getattr(ClienteModel, "BILLING_PENDING_PLAN_CHANGE_TYPE", "billing_pending_plan_change_type"): None,
            }
        ).eq(ClienteModel.ID, cliente_id).execute()
    except Exception:
        pass

    # Fonte de verdade: subscriptions (best-effort)
    try:
        upsert_tenant_subscription(
            cliente_id=str(cliente_id),
            provider="stripe",
            provider_subscription_id=None,
            plan_key=plan_key_raw,
            status="pending",
        )
    except Exception:
        pass

    current_app.logger.info(
        "billing: stripe checkout created cliente_id=%s plan_key=%s customer_id=%s session_id=%s",
        cliente_id,
        plan_key_raw,
        customer_id,
        session_id,
    )
    return jsonify({"ok": True, "provider": "stripe", "checkout_url": checkout_url})


@stripe_billing_bp.route("/customer-portal", methods=["POST"])
@login_required
@subscription_required
def stripe_customer_portal():
    sup = _require_supabase()
    if sup:
        return sup
    cliente_id = get_current_cliente_id(current_user)
    if not cliente_id:
        return jsonify({"ok": False, "erro": "Cliente não identificado na sessão."}), 400

    row = _cliente_row(str(cliente_id))
    stripe_customer_id = (row.get("stripe_customer_id") or "").strip()
    if not stripe_customer_id:
        return jsonify({"ok": False, "erro": "Cliente Stripe ainda não criado. Faça checkout primeiro."}), 400

    return_url = (getattr(settings, "STRIPE_PORTAL_RETURN_URL", "") or "").strip()
    if not return_url:
        return jsonify({"ok": False, "erro": "STRIPE_PORTAL_RETURN_URL não configurada."}), 503
    try:
        url = create_customer_portal(stripe_customer_id=stripe_customer_id, return_url=return_url)
        return jsonify({"ok": True, "url": url})
    except ValueError as e:
        return jsonify({"ok": False, "erro": "Falha ao abrir portal Stripe.", "detail": str(e)}), 400
    except StripeError as e:
        detail = (getattr(e, "user_message", None) or str(e) or "stripe_error")[:500]
        current_app.logger.warning("billing: stripe portal api error cliente_id=%s err=%s", cliente_id, detail)
        return jsonify({"ok": False, "erro": "Falha ao abrir portal Stripe.", "detail": detail}), 400
    except Exception as e:
        current_app.logger.exception("billing: stripe portal failed cliente_id=%s", cliente_id)
        return jsonify({"ok": False, "erro": "Falha ao abrir portal Stripe.", "detail": str(e)[:500]}), 500


@stripe_billing_bp.route("/webhook", methods=["POST"])
def stripe_webhook():
    sup = _require_supabase()
    if sup:
        return sup

    payload = request.get_data() or b""
    sig_header = (request.headers.get("Stripe-Signature") or "").strip()
    if not sig_header:
        return jsonify({"ok": False, "erro": "Missing Stripe-Signature header."}), 400

    try:
        event = construct_webhook_event(payload=payload, sig_header=sig_header)
    except Exception as e:
        current_app.logger.warning("stripe webhook signature invalid: %s", str(e)[:200])
        return jsonify({"ok": False, "erro": "Invalid signature."}), 400

    log_event_summary(event)
    event_id = str(event.get("id") or "").strip()
    event_type = str(event.get("type") or "").strip()
    raw_body = payload.decode("utf-8", errors="replace")

    # Idempotência: billing_events.event_id (chave primária) = Stripe event.id
    try:
        existing = (
            supabase.table(Tables.BILLING_EVENTS)
            .select(f"{BillingEventModel.EVENT_ID},{BillingEventModel.STATUS}")
            .eq(BillingEventModel.EVENT_ID, event_id)
            .limit(1)
            .execute()
        )
        if existing.data:
            st = (existing.data[0].get(BillingEventModel.STATUS) or "").strip().lower()
            if st == "processed":
                return "", 200
    except Exception:
        pass

    try:
        supabase.table(Tables.BILLING_EVENTS).upsert(
            {
                BillingEventModel.EVENT_ID: event_id,
                BillingEventModel.REQUEST_ID: (request.headers.get("X-Request-Id") or "")[:100] or None,
                BillingEventModel.RESOURCE_TYPE: "stripe",
                BillingEventModel.DATA_ID: event_type,
                BillingEventModel.RAW_BODY: raw_body,
                BillingEventModel.RECEIVED_AT: _now_iso(),
                BillingEventModel.STATUS: "received",
            },
            on_conflict=BillingEventModel.EVENT_ID,
        ).execute()
    except Exception:
        pass

    obj = event.get("data", {}).get("object", {}) or {}
    if not isinstance(obj, dict):
        obj = {}

    cliente_id: str | None = None
    try:
        st = parse_subscription_from_event(event)
        cliente_id = resolve_cliente_id_for_webhook(
            event_type=event_type,
            event_object=obj,
            st=st,
        )

        if not cliente_id:
            current_app.logger.error(
                "stripe webhook: cliente_id não resolvido event=%s type=%s sub=%s cust=%s",
                event_id,
                event_type,
                st.stripe_subscription_id,
                st.stripe_customer_id,
            )
            try:
                supabase.table(Tables.BILLING_EVENTS).update(
                    {
                        BillingEventModel.STATUS: "failed",
                        BillingEventModel.PROCESSED_AT: _now_iso(),
                    }
                ).eq(BillingEventModel.EVENT_ID, event_id).execute()
            except Exception:
                pass
            return jsonify({"ok": False, "erro": "cliente_id_unresolved"}), 500

        upsert_tenant_subscription(
            cliente_id=str(cliente_id),
            provider="stripe",
            provider_subscription_id=st.stripe_subscription_id,
            plan_key=st.plan_key or None,
            status=st.status or None,
            current_period_end=st.current_period_end.isoformat() if st.current_period_end else None,
        )

        payload_cli = cliente_billing_patch(st)
        if payload_cli:
            supabase.table(Tables.CLIENTES).update(payload_cli).eq(ClienteModel.ID, cliente_id).execute()
        else:
            current_app.logger.warning(
                "stripe webhook: patch vazio event=%s type=%s cliente=%s",
                event_id,
                event_type,
                cliente_id,
            )

        # Marca evento processado
        supabase.table(Tables.BILLING_EVENTS).update(
            {
                BillingEventModel.PROCESSED_AT: _now_iso(),
                BillingEventModel.STATUS: "processed",
                BillingEventModel.CLIENTE_ID: cliente_id or None,
            }
        ).eq(BillingEventModel.EVENT_ID, event_id).execute()
    except Exception as e:
        current_app.logger.exception("stripe webhook processing failed event_id=%s type=%s", event_id, event_type)
        try:
            supabase.table(Tables.BILLING_EVENTS).update(
                {
                    BillingEventModel.STATUS: "failed",
                    BillingEventModel.PROCESSED_AT: _now_iso(),
                    BillingEventModel.CLIENTE_ID: cliente_id or None,
                }
            ).eq(BillingEventModel.EVENT_ID, event_id).execute()
        except Exception:
            pass
        # 500 para Stripe reenviar
        return jsonify({"ok": False, "erro": "webhook_failed"}), 500

    return "", 200

