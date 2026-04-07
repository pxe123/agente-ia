from flask import Blueprint, current_app, jsonify, request

from base.config import settings
from database.supabase_sq import supabase
from database.models import Tables, BillingEventModel
from panel.routes.billing import _mark_event_received, process_mercadopago_event
from services.billing.mercadopago import verify_webhook_signature
from services.queue import enqueue


mercadopago_bp = Blueprint("mercadopago_webhook", __name__)


@mercadopago_bp.route("/mercadopago", methods=["POST"])
def mercadopago_webhook():
    """
    Recebe webhooks do Mercado Pago em /webhook/mercadopago.
    Valida assinatura via x-signature + x-request-id + data.id (quando REQUIRE_WEBHOOK_SIGNATURES=1).
    """
    if supabase is None:
        return jsonify({"ok": False, "erro": "Supabase não configurado no servidor."}), 503

    x_signature = (request.headers.get("x-signature") or request.headers.get("X-Signature") or "").strip()
    x_request_id = (request.headers.get("x-request-id") or request.headers.get("X-Request-Id") or "").strip()
    # MP pode enviar via querystring (type + data.id) e/ou no corpo JSON
    resource_type = (request.args.get("type") or request.args.get("topic") or "").strip()
    data_id = (request.args.get("data.id") or request.args.get("id") or "").strip()
    raw_body_bytes = request.get_data() or b""
    raw_body = raw_body_bytes.decode("utf-8", errors="replace")
    try:
        body_json = request.get_json(silent=True) or {}
    except Exception:
        body_json = {}
    if not resource_type:
        resource_type = (body_json.get("type") or "").strip()
    # Compat: MP às vezes envia "payments" (plural)
    if resource_type == "payments":
        resource_type = "payment"
    if not data_id:
        # padrão do MP: data: { id: "..." }
        data = body_json.get("data") or {}
        if isinstance(data, dict) and data.get("id"):
            data_id = str(data.get("id")).strip()
        elif body_json.get("id"):
            data_id = str(body_json.get("id")).strip()

    if getattr(settings, "REQUIRE_WEBHOOK_SIGNATURES", False):
        # Sem data_id não há como validar o manifest do MP
        if not data_id:
            return jsonify({"ok": False, "erro": "Webhook sem data.id (não é possível validar assinatura)."}), 400
        ok_sig = verify_webhook_signature(
            x_signature=x_signature,
            x_request_id=x_request_id,
            data_id=data_id,
        )
        if not ok_sig:
            return jsonify({"ok": False, "erro": "Assinatura do webhook inválida."}), 403

    normalized_request_id = x_request_id or "no_request_id"
    event_id = f"{resource_type}:{data_id}:{normalized_request_id}"

    # idempotência (se já existe, ack 200)
    try:
        existing = (
            supabase.table(Tables.BILLING_EVENTS)
            .select(f"{BillingEventModel.EVENT_ID},{BillingEventModel.STATUS}")
            .eq(BillingEventModel.EVENT_ID, event_id)
            .limit(1)
            .execute()
        )
        if existing.data:
            # Se já foi processado, não reprocessa. Se ficou em 'received' (job falhou), reprocessa.
            st = (existing.data[0].get(BillingEventModel.STATUS) or "").strip().lower()
            if st == "processed":
                return "", 200
    except Exception:
        pass

    _mark_event_received(event_id, normalized_request_id, resource_type, data_id, raw_body)

    job_id = enqueue(
        "panel.routes.billing.process_mercadopago_event",
        resource_type,
        data_id,
        normalized_request_id,
        raw_body,
    )
    if job_id:
        return "", 200

    try:
        process_mercadopago_event(resource_type, data_id, normalized_request_id, raw_body)
    except Exception as e:
        current_app.logger.warning("mercadopago_webhook inline falhou: %s", e)
    return "", 200

