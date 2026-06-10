from flask import Blueprint, jsonify, request

from base.config import settings
from services.agendamento_ia_appointment_webhook import (
    parse_json_body,
    process_appointment_webhook_payload,
    verify_zapaction_webhook_signature,
)

agendamento_ia_appointments_bp = Blueprint("agendamento_ia_appointments_webhook", __name__)


@agendamento_ia_appointments_bp.route("/agendamento-ia/appointments", methods=["POST"])
def agendamento_ia_appointments_webhook():
    """
    POST /webhook/agendamento-ia/appointments — eventos appointment.* do motor Agendamento IA.
    """
    secret = (getattr(settings, "ZAPACTION_WEBHOOK_SECRET", None) or "").strip()
    if not secret:
        return jsonify({"ok": False, "erro": "ZAPACTION_WEBHOOK_SECRET não configurado."}), 503

    raw_body = request.get_data(cache=False) or b""
    ts = (request.headers.get("X-Zapaction-Timestamp") or request.headers.get("x-zapaction-timestamp") or "").strip()
    sig = (request.headers.get("X-Zapaction-Signature") or request.headers.get("x-zapaction-signature") or "").strip()

    ok_sig, err_sig = verify_zapaction_webhook_signature(
        secret=secret, raw_body=raw_body, timestamp_header=ts, signature_header=sig
    )
    if not ok_sig:
        return jsonify({"ok": False, "erro": err_sig or "assinatura_invalida"}), 403

    payload, err_parse = parse_json_body(raw_body)
    if err_parse or not payload:
        return jsonify({"ok": False, "erro": err_parse or "payload_invalido"}), 400

    ok, err_proc, code = process_appointment_webhook_payload(payload)
    if not ok:
        return jsonify({"ok": False, "erro": err_proc or "processamento_falhou"}), code
    return jsonify({"ok": True}), 200
