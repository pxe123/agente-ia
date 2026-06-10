# services/agendamento_ia_bridge.py
"""
Cliente HTTP e parsing para o webhook do nó agendamento_ia.

Request: user_message, context, session?, zapaction_turn_id, inbound_user_message_id, request_schema_version

Resposta da API (motor, sem chatbot):
- api_version, status, done, data, session, error? — sem `reply`/`message` (texto no Flow com templates)

Compatibilidade legada: ainda lê `reply`/`message` se existir (API antiga).
"""
from __future__ import annotations

import json
import time
from typing import Any

import requests

from base.config import settings
from services.agendamento_ia_contact import prepare_agendamento_context
from services.agendamento_ia_urls import resolved_agendamento_webhook_url

REQUEST_SCHEMA_VERSION = 1
HISTORY_LIMIT = 15


def build_request_body(
    *,
    user_message: str,
    context: dict[str, Any],
    session: dict[str, Any] | None,
    zapaction_turn_id: str,
    inbound_user_message_id: str | None,
) -> dict[str, Any]:
    return {
        "request_schema_version": REQUEST_SCHEMA_VERSION,
        "user_message": user_message,
        "context": prepare_agendamento_context(context),
        "session": session,
        "zapaction_turn_id": zapaction_turn_id,
        "inbound_user_message_id": inbound_user_message_id,
    }


def _extract_reply(d: dict[str, Any]) -> str:
    r = d.get("reply")
    if r is not None and str(r).strip():
        return str(r).strip()
    m = d.get("message")
    if m is not None and str(m).strip():
        return str(m).strip()
    return ""


def _as_bool(v: Any) -> bool:
    if v is True:
        return True
    if v is False or v is None:
        return False
    if isinstance(v, str) and v.strip().lower() in ("true", "1", "yes", "sim"):
        return True
    return False


def parse_api_response(data: str | bytes | None) -> dict[str, Any]:
    """
    Aceita corpo bruto (JSON) da API.
    Inclui campos canónicos: api_status, data, error, api_version (motor só dados);
    `reply` só se a API ainda o enviar; o template local no nó gera a cópia ao canal.
    """
    out: dict[str, Any] = {
        "reply": "",
        "done": False,
        "action": None,
        "session": None,
        "raw_error": None,
        "api_version": 1,
        "api_status": "ok",
        "data": None,
        "error": None,
    }
    if not data:
        out["raw_error"] = "empty_response"
        return out
    try:
        if isinstance(data, bytes):
            text = data.decode("utf-8", errors="replace")
        else:
            text = str(data)
        text = text.strip()
        d = json.loads(text) if text else None
    except Exception as e:
        out["raw_error"] = f"invalid_json:{e!s}"
        return out

    if not isinstance(d, dict):
        out["raw_error"] = "not_object"
        return out

    if isinstance(d.get("api_version"), (int, float)):
        out["api_version"] = int(d.get("api_version", 1))

    st = d.get("status")
    if st in ("ok", "needs_input", "error"):
        out["api_status"] = st
    else:
        out["api_status"] = "ok"

    data_field = d.get("data")
    if isinstance(data_field, dict) or data_field is None:
        out["data"] = data_field
    elif isinstance(data_field, list):
        out["data"] = data_field

    if isinstance(d.get("error"), dict) or d.get("error") is None:
        out["error"] = d.get("error")

    # múltiplas ações (v2): v1 usa só a primeira, espelhando action singular
    if isinstance(d.get("actions"), list) and d.get("actions"):
        first = d.get("actions")[0]
        if isinstance(first, dict) and d.get("action") is None:
            d = {**d, "action": first}

    out["reply"] = _extract_reply(d)
    out["done"] = _as_bool(d.get("done"))
    act = d.get("action")
    if act is not None and not isinstance(act, dict):
        out["action"] = None
    else:
        out["action"] = act

    sess = d.get("session")
    if isinstance(sess, dict):
        out["session"] = sess
    else:
        out["session"] = None
    if out.get("api_status") is None:
        out["api_status"] = "ok"
    out["status"] = out["api_status"]
    return out


def call_webhook(body: dict[str, Any]) -> dict[str, Any]:
    """
    POST JSON para AGENDAMENTO_IA_WEBHOOK_URL.
    Retorno: {
      "ok": bool, "http_status": int|None, "text": str, "parsed": dict, "error": str|None,
      "duration_ms": int
    }
    """
    url = resolved_agendamento_webhook_url()
    t0 = time.perf_counter()
    out: dict[str, Any] = {
        "ok": False,
        "http_status": None,
        "text": "",
        "parsed": None,
        "error": None,
        "duration_ms": 0,
    }
    if not url:
        out["error"] = "no_webhook_url"
        out["duration_ms"] = int((time.perf_counter() - t0) * 1000)
        return out

    headers = {"Content-Type": "application/json"}
    key = (getattr(settings, "AGENDAMENTO_IA_API_KEY", None) or "").strip()
    if key:
        headers["Authorization"] = f"Bearer {key}"

    timeout = getattr(settings, "AGENDAMENTO_IA_TIMEOUT_SEC", 25) or 25
    try:
        r = requests.post(
            url,
            json=body,
            headers=headers,
            timeout=timeout,
        )
        out["http_status"] = r.status_code
        out["text"] = r.text or ""
        out["ok"] = 200 <= r.status_code < 300
        if not out["ok"] and not out.get("error"):
            out["error"] = f"http_{r.status_code}"
    except requests.Timeout:
        out["error"] = "timeout"
    except Exception as e:
        out["error"] = f"request:{e!s}"
    out["duration_ms"] = int((time.perf_counter() - t0) * 1000)
    if out.get("ok") and out.get("text") is not None:
        out["parsed"] = parse_api_response(out["text"])
    return out


def scheduling_uses_internal_motor(cliente_id: str | None) -> bool:
    """
    True: nó agendamento_ia usa SchedulingService interno (Supabase).
    False: POST para Agendamento IA (/v1/agendamento).

    Implementação: services.scheduling.engine (BD + fallback env).
    """
    from services.scheduling.engine import scheduling_uses_internal_motor as _resolve

    return _resolve(cliente_id)


def agendamento_use_internal_scheduling(cliente_id: str | None = None) -> bool:
    """Compat: sem cliente_id usa regras globais/dev (sem allowlist)."""
    return scheduling_uses_internal_motor(cliente_id)


def call_agendamento_motor(body: dict[str, Any]) -> dict[str, Any]:
    """
    Mesma forma de retorno que `call_webhook` (parsed compatível com parse_api_response).
    """
    t0 = time.perf_counter()
    out: dict[str, Any] = {
        "ok": False,
        "http_status": 200,
        "text": "",
        "parsed": None,
        "error": None,
        "duration_ms": 0,
    }
    try:
        from services.scheduling.service import handle_turn

        parsed = handle_turn(body)
        out["parsed"] = parsed
        out["ok"] = True
        try:
            out["text"] = json.dumps(parsed, ensure_ascii=False, default=str)
        except Exception:
            out["text"] = ""
    except Exception as e:
        out["ok"] = False
        out["error"] = f"internal_scheduling:{e!s}"
        out["http_status"] = None
    out["duration_ms"] = int((time.perf_counter() - t0) * 1000)
    return out
