import json
from typing import Any, Dict, Optional

from flask import Blueprint, current_app, jsonify, request
from flask_login import login_required, current_user

from base.auth import get_current_cliente_id
from base.request_security import strip_untrusted_tenant_ids
from base.config import settings
from database.supabase_sq import supabase
from database.models import Tables, ClienteModel, BillingEventModel
from services.plans import plan_price
from services.billing.mercadopago import (
    create_preapproval,
    get_preapproval,
    now_iso,
    verify_webhook_signature,
)
from services.queue import enqueue


billing_bp = Blueprint("billing", __name__, url_prefix="/api/billing")


def _require_supabase():
    if supabase is None:
        return jsonify({"ok": False, "erro": "Supabase não configurado no servidor."}), 503
    return None


def _cliente_row(cliente_id: str) -> Optional[Dict[str, Any]]:
    r = (
        supabase.table(Tables.CLIENTES)
        .select(
            ",".join(
                [
                    ClienteModel.ID,
                    ClienteModel.EMAIL,
                    ClienteModel.PLANO,
                    getattr(ClienteModel, "BILLING_PLAN_KEY", "billing_plan_key"),
                    getattr(ClienteModel, "BILLING_STATUS", "billing_status"),
                    getattr(ClienteModel, "BILLING_CURRENT_PERIOD_END", "billing_current_period_end"),
                    getattr(ClienteModel, "TRIAL_ENDS_AT", "trial_ends_at"),
                    getattr(ClienteModel, "MP_PREAPPROVAL_ID", "mp_preapproval_id"),
                    getattr(ClienteModel, "BILLING_CANCEL_AT_PERIOD_END", "billing_cancel_at_period_end"),
                    getattr(ClienteModel, "BILLING_CANCEL_SCHEDULED_AT", "billing_cancel_scheduled_at"),
                ]
            )
        )
        .eq(ClienteModel.ID, cliente_id)
        .execute()
    )
    if r.data and len(r.data) > 0:
        return r.data[0]
    return None


@billing_bp.route("/mp/checkout", methods=["POST"])
@login_required
def mp_checkout():
    """
    Cria uma assinatura recorrente no Mercado Pago (preapproval) e retorna init_point/URL.
    """
    sup = _require_supabase()
    if sup:
        return sup

    cliente_id = get_current_cliente_id(current_user)
    if not cliente_id:
        return jsonify({"ok": False, "erro": "Cliente não identificado na sessão."}), 400

    body = strip_untrusted_tenant_ids(request.get_json(silent=True) or {})
    plan_key = (body.get("plan_key") or "default").strip()
    payer_email = (body.get("payer_email") or getattr(current_user, "email", "") or "").strip().lower()
    if not payer_email:
        return jsonify({"ok": False, "erro": "E-mail do pagador é obrigatório."}), 400

    amount, currency = plan_price(plan_key)
    if amount is None:
        return jsonify({"ok": False, "erro": f"Plano inválido: {plan_key}"}), 400

    ok, data = create_preapproval(
        plan_key=plan_key,
        reason=f"Assinatura {plan_key} - ZapAction",
        payer_email=payer_email,
        cliente_id=str(cliente_id),
        amount=amount,
        currency_id=currency,
        back_url=settings.MERCADOPAGO_BACK_URL or "",
    )
    if not ok:
        try:
            current_app.logger.error("billing: mp preapproval create failed cliente_id=%s plan_key=%s resp=%s", cliente_id, plan_key, data)
        except Exception:
            pass
        return jsonify({"ok": False, "erro": "Falha ao criar assinatura no Mercado Pago.", "detalhe": data}), 400

    preapproval_id = (data.get("id") or "").strip()
    init_point = data.get("init_point") or data.get("sandbox_init_point")

    # Salva referência no cliente (se as colunas existirem no Supabase)
    try:
        supabase.table(Tables.CLIENTES).update(
            {
                getattr(ClienteModel, "BILLING_PLAN_KEY", "billing_plan_key"): plan_key,
                getattr(ClienteModel, "MP_PREAPPROVAL_ID", "mp_preapproval_id"): preapproval_id or None,
            }
        ).eq(ClienteModel.ID, cliente_id).execute()
    except Exception as e:
        current_app.logger.warning("billing: falha ao salvar preapproval no cliente: %s", e)

    return jsonify(
        {
            "ok": True,
            "provider": "mercadopago",
            "preapproval_id": preapproval_id,
            "init_point": init_point,
        }
    )


@billing_bp.route("/mp/return", methods=["GET"])
def mp_return():
    """
    Rota de retorno (back_url) para UX/auditoria.
    Fonte da verdade continua sendo o webhook; esta rota NÃO altera `clientes.billing_status`.
    """
    sup = _require_supabase()
    if sup:
        return sup

    args = request.args.to_dict(flat=True)
    # Alguns cenários podem mandar `status` (approved/rejected/pending) e `external_reference`
    # (na nossa integração, external_reference = cliente_id).
    status = (args.get("status") or args.get("collection_status") or "").strip().lower() or "unknown"
    external_reference = (args.get("external_reference") or "").strip()

    # Identificador do retorno (pode ser `id`, `preference_id`, `payment_id`, etc.)
    identifier = (
        (args.get("id") or "")
        or (args.get("preapproval_id") or "")
        or (args.get("preference_id") or "")
        or (args.get("payment_id") or "")
    ).strip() or ""

    request_id = (args.get("router-request-id") or args.get("request_id") or "").strip() or "mp_return"
    raw_body = json.dumps(args, ensure_ascii=False)

    # event_id precisa ser único; usamos status/identifier para reduzir colisões.
    cliente_id_part = external_reference or "unknown_cliente"
    ident_part = identifier or request_id
    event_id = f"mp_return:{cliente_id_part}:{status}:{ident_part}"

    # Best-effort: se já existe, não duplicamos.
    try:
        existing = (
            supabase.table(Tables.BILLING_EVENTS)
            .select(BillingEventModel.EVENT_ID)
            .eq(BillingEventModel.EVENT_ID, event_id)
            .limit(1)
            .execute()
        )
        if not existing.data:
            supabase.table(Tables.BILLING_EVENTS).insert(
                {
                    BillingEventModel.EVENT_ID: event_id,
                    BillingEventModel.REQUEST_ID: request_id,
                    BillingEventModel.RESOURCE_TYPE: "mp_return",
                    BillingEventModel.DATA_ID: identifier or None,
                    BillingEventModel.RAW_BODY: raw_body[:50000],
                    BillingEventModel.RECEIVED_AT: now_iso(),
                    BillingEventModel.STATUS: "received",
                }
            ).execute()
    except Exception:
        pass

    # UX simples (não depende de login).
    msg = (
        "Recebemos seu retorno do Mercado Pago. "
        "Estamos confirmando a transação via webhook. "
        "Se o acesso ainda não liberou, aguarde alguns instantes e/ou verifique o histórico no painel."
    )
    return (
        "<!doctype html>"
        "<html><head><meta charset='utf-8'><title>Pagamento</title></head>"
        "<body style='font-family:system-ui,Arial,sans-serif;padding:24px'>"
        f"<h2>Pagamento: {status}</h2>"
        f"<p>{msg}</p>"
        "<p><a href='/precos'>Ir para preços / assinatura</a></p>"
        "</body></html>"
    )


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


@billing_bp.route("/mp/cancel", methods=["POST"])
@login_required
def mp_cancel():
    """
    Agenda cancelamento no fim do período.
    MVP: registra flags no cliente; job assíncrono efetiva no MP quando o período terminar.
    """
    sup = _require_supabase()
    if sup:
        return sup

    cliente_id = get_current_cliente_id(current_user)
    if not cliente_id:
        return jsonify({"ok": False, "erro": "Cliente não identificado na sessão."}), 400

    row = _cliente_row(str(cliente_id)) or {}
    preapproval_id = (row.get(getattr(ClienteModel, "MP_PREAPPROVAL_ID", "mp_preapproval_id")) or "").strip()
    if not preapproval_id:
        return jsonify({"ok": False, "erro": "Assinatura não encontrada para cancelar (mp_preapproval_id vazio)."}), 400

    try:
        payload = {
            getattr(ClienteModel, "BILLING_CANCEL_AT_PERIOD_END", "billing_cancel_at_period_end"): True,
            getattr(ClienteModel, "BILLING_CANCEL_SCHEDULED_AT", "billing_cancel_scheduled_at"): now_iso(),
        }
        supabase.table(Tables.CLIENTES).update(payload).eq(ClienteModel.ID, cliente_id).execute()
    except Exception as e:
        return jsonify({"ok": False, "erro": f"Falha ao agendar cancelamento: {e}"}), 400

    # Retorna status atualizado (best-effort)
    row2 = _cliente_row(str(cliente_id)) or row
    return jsonify({"ok": True, "scheduled": True, "cliente": row2})


def _mark_event_received(event_id: str, request_id: str, resource_type: str, data_id: str, raw_body: str):
    """
    Best-effort: registra evento para idempotência.
    Requer tabela billing_events (com unique em event_id).
    """
    if supabase is None:
        return
    try:
        existing = (
            supabase.table(Tables.BILLING_EVENTS)
            .select(BillingEventModel.EVENT_ID)
            .eq(BillingEventModel.EVENT_ID, event_id)
            .limit(1)
            .execute()
        )
        if existing.data:
            raise RuntimeError("already_exists")
        supabase.table(Tables.BILLING_EVENTS).insert(
            {
                BillingEventModel.EVENT_ID: event_id,
                BillingEventModel.REQUEST_ID: request_id,
                BillingEventModel.RESOURCE_TYPE: resource_type,
                BillingEventModel.DATA_ID: data_id,
                BillingEventModel.RAW_BODY: raw_body[:50000],
                BillingEventModel.RECEIVED_AT: now_iso(),
                BillingEventModel.STATUS: "received",
            }
        ).execute()
    except Exception:
        # Se já existe ou falhou, seguimos o fluxo de idempotência via select no handler
        return


def process_mercadopago_event(resource_type: str, data_id: str, request_id: str, raw_body: str):
    """
    Job assíncrono: busca estado no MP e aplica no cliente.
    Achar cliente pelo external_reference (cliente_id).
    """
    if supabase is None:
        return
    if resource_type not in ("preapproval", "subscription_preapproval"):
        return

    normalized_request_id = request_id or "no_request_id"
    event_id = f"{resource_type}:{data_id}:{normalized_request_id}"
    # Segurança: se já estiver 'processed', não reprocessa.
    try:
        existing = (
            supabase.table(Tables.BILLING_EVENTS)
            .select(BillingEventModel.STATUS)
            .eq(BillingEventModel.EVENT_ID, event_id)
            .limit(1)
            .execute()
        )
        if existing.data:
            st = (existing.data[0].get(BillingEventModel.STATUS) or "").strip().lower()
            if st == "processed":
                return
    except Exception:
        pass

    ok, pre = get_preapproval(data_id)
    if not ok:
        try:
            current_app.logger.warning(
                "mercadopago_event: get_preapproval falhou data_id=%s resp=%s", data_id, pre
            )
        except Exception:
            pass
        return

    cliente_id = (pre.get("external_reference") or "").strip()
    if not cliente_id:
        try:
            current_app.logger.warning(
                "mercadopago_event: preapproval sem external_reference data_id=%s", data_id
            )
        except Exception:
            pass
        return

    mp_field = getattr(ClienteModel, "MP_PREAPPROVAL_ID", "mp_preapproval_id")
    row = _cliente_row(cliente_id)
    if row is None:
        try:
            current_app.logger.warning(
                "mercadopago_event: external_reference não corresponde a cliente existente "
                "(cliente_id=%s, data_id=%s)",
                cliente_id,
                data_id,
            )
        except Exception:
            pass
        return
    existing_pid = (row.get(mp_field) or "").strip()
    if existing_pid and existing_pid != str(data_id).strip():
        try:
            current_app.logger.warning(
                "mercadopago_event: mp_preapproval_id no banco difere do evento "
                "(cliente_id=%s, db=%s, webhook=%s)",
                cliente_id,
                existing_pid,
                data_id,
            )
        except Exception:
            pass
        return

    status = (pre.get("status") or "").strip().lower() or "pending"
    plan_key = None
    try:
        meta = pre.get("metadata") or {}
        plan_key = (meta.get("plan_key") or "").strip() or None
    except Exception:
        plan_key = None

    # current_period_end não é padronizado no preapproval; guardamos next_payment_date se existir
    current_period_end = (pre.get("next_payment_date") or pre.get("end_date") or None)

    # Enriquecimento (valores monetários) do preapproval (auto_recurring)
    amount_value = None
    currency_value = None
    try:
        auto_rec = pre.get("auto_recurring") or {}
        raw_amount = auto_rec.get("transaction_amount")
        raw_currency = auto_rec.get("currency_id")
        if raw_amount is not None:
            amount_value = float(raw_amount)
        if raw_currency is not None:
            currency_value = str(raw_currency).strip().upper() or None
    except Exception:
        amount_value = None
        currency_value = None

    payload = {
        getattr(ClienteModel, "BILLING_STATUS", "billing_status"): status,
        getattr(ClienteModel, "MP_PREAPPROVAL_ID", "mp_preapproval_id"): data_id,
    }
    if plan_key:
        payload[getattr(ClienteModel, "BILLING_PLAN_KEY", "billing_plan_key")] = plan_key
    if current_period_end:
        payload[getattr(ClienteModel, "BILLING_CURRENT_PERIOD_END", "billing_current_period_end")] = current_period_end

    try:
        supabase.table(Tables.CLIENTES).update(payload).eq(ClienteModel.ID, cliente_id).execute()
    except Exception as e:
        try:
            current_app.logger.warning(
                "mercadopago_event: falha ao atualizar cliente %s: %s", cliente_id, e
            )
        except Exception:
            pass
        return

    # Marca evento como processado e associa ao cliente (best-effort)
    try:
        event_id = f"{resource_type}:{data_id}:{normalized_request_id}"
        upd = {
            BillingEventModel.PROCESSED_AT: now_iso(),
            BillingEventModel.STATUS: "processed",
            BillingEventModel.CLIENTE_ID: cliente_id,
            BillingEventModel.MP_STATUS: status,
            BillingEventModel.PLAN_KEY: plan_key,
            BillingEventModel.NEXT_PAYMENT_DATE: current_period_end,
            BillingEventModel.AMOUNT: amount_value,
            BillingEventModel.CURRENCY: currency_value,
        }
        supabase.table(Tables.BILLING_EVENTS).update(upd).eq(BillingEventModel.EVENT_ID, event_id).execute()
    except Exception:
        try:
            event_id = f"{resource_type}:{data_id}:{normalized_request_id}"
            supabase.table(Tables.BILLING_EVENTS).update(
                {
                    BillingEventModel.PROCESSED_AT: now_iso(),
                    BillingEventModel.STATUS: "processed",
                    BillingEventModel.MP_STATUS: status,
                    BillingEventModel.PLAN_KEY: plan_key,
                    BillingEventModel.NEXT_PAYMENT_DATE: current_period_end,
                    BillingEventModel.AMOUNT: amount_value,
                    BillingEventModel.CURRENCY: currency_value,
                }
            ).eq(BillingEventModel.EVENT_ID, event_id).execute()
        except Exception:
            pass


"""
Webhook Mercado Pago fica em /webhook/mercadopago (blueprint em webhooks/mercadopago_webhook.py)
para ficar fora de CSRF e sem login.
"""

