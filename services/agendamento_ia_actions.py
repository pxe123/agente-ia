# services/agendamento_ia_actions.py
"""
Ações pluggáveis do nó agendamento_ia (ZapAction ↔ webhook externo).
v1: enum canónica, normalização de sinónimos, stubs com log; idempotência simples.
"""
from __future__ import annotations

import hashlib
import json
from typing import Any

# Tipos canónicos devolvidos pela API (após normalização)
ACTION_NONE = "none"
ACTION_SCHEDULE = "schedule"
ACTION_CANCEL = "cancel"
ACTION_LIST_SLOTS = "list_slots"

_CANON = {
    "none": ACTION_NONE,
    "noop": ACTION_NONE,
    "agendar": ACTION_SCHEDULE,
    "schedule": ACTION_SCHEDULE,
    "booking": ACTION_SCHEDULE,
    "cancel": ACTION_CANCEL,
    "cancelar": ACTION_CANCEL,
    "list_slots": ACTION_LIST_SLOTS,
    "listar": ACTION_LIST_SLOTS,
    "list": ACTION_LIST_SLOTS,
    "horarios": ACTION_LIST_SLOTS,
}


def normalize_action_type(raw: str | None) -> str:
    t = (raw or "none").strip().lower().replace(" ", "_")
    return _CANON.get(t, ACTION_NONE)


def _stable_json(obj: Any) -> str:
    try:
        return json.dumps(obj, sort_keys=True, ensure_ascii=False, default=str)
    except Exception:
        return str(obj)


def action_from_parsed(parsed: dict[str, Any] | None) -> dict[str, Any] | None:
    """
    Constrói ação a partir de `data.intent` quando a API de dados não envia `action`.
    """
    if not isinstance(parsed, dict):
        return None
    d = parsed.get("data")
    if not isinstance(d, dict):
        return None
    at = normalize_action_type(str(d.get("intent") or "none"))
    payload: dict[str, Any] = {"intent": d.get("intent"), "metadata": d.get("metadata") or {}}
    if d.get("appointment") is not None:
        payload["appointment"] = d.get("appointment")
    if d.get("slots") is not None:
        payload["slots"] = d.get("slots")
    if d.get("selected_slot") is not None:
        payload["selected_slot"] = d.get("selected_slot")
    if d.get("cancelled_appointment_id") is not None:
        payload["cancelled_appointment_id"] = d.get("cancelled_appointment_id")
    if at == ACTION_NONE:
        return None
    return {"type": at, "payload": payload}


def pick_or_derive_action(parsed: dict[str, Any] | None) -> dict[str, Any] | None:
    if not isinstance(parsed, dict):
        return None
    a = parsed.get("action")
    if isinstance(a, dict):
        t = str(a.get("type") or a.get("action") or "").strip()
        if t:
            return {**a, "type": t} if a.get("type") is None and a.get("action") else a
    return action_from_parsed(parsed) or None


def action_fingerprint(
    inbound_user_message_id: str | None,
    action_type: str,
    payload: dict | None,
) -> str:
    p = _stable_json(payload or {})
    base = f"{inbound_user_message_id or ''}|{action_type}|{p}"
    return hashlib.sha256(base.encode("utf-8")).hexdigest()[:32]


def apply_agendamento_action(
    ctx: dict[str, Any],
    action: dict | None,
    ag_state: dict[str, Any] | None,
) -> dict[str, Any]:
    """
    ctx: cliente_id, canal, remote_id, contact_id?, flow_id, node_id, message_meta
    ag_state: sub-objeto __agendamento_ia (mutável pelo caller a partir do retorno)
    Retorno: { "ag_state": dict, "action_type": str, "skipped_duplicate": bool }
    """
    ag: dict[str, Any] = dict(ag_state or {})
    if not action or not isinstance(action, dict):
        return {"ag_state": ag, "action_type": ACTION_NONE, "skipped_duplicate": False}

    at = normalize_action_type(
        (action.get("type") or action.get("action") or "") if isinstance(action, dict) else ""
    )
    payload = action.get("payload") if isinstance(action.get("payload"), dict) else {}
    inbound = ctx.get("inbound_user_message_id")
    fp = action_fingerprint(str(inbound) if inbound else None, at, payload)
    last_fp = (ag.get("last_fingerprint") or "").strip()
    if last_fp and last_fp == fp:
        return {"ag_state": ag, "action_type": at, "skipped_duplicate": True}

    if at == ACTION_NONE:
        _act_none(ctx, payload)
    elif at == ACTION_SCHEDULE:
        _act_schedule(ctx, payload)
    elif at == ACTION_CANCEL:
        _act_cancel(ctx, payload)
    elif at == ACTION_LIST_SLOTS:
        _act_list_slots(ctx, payload)
    else:
        _act_none(ctx, payload)

    ag["last_fingerprint"] = fp
    if at == ACTION_SCHEDULE and isinstance(payload, dict):
        appt = payload.get("appointment")
        if isinstance(appt, dict):
            ag["last_scheduled_appointment"] = appt
    elif at == ACTION_CANCEL and isinstance(payload, dict):
        cid_cancel = payload.get("cancelled_appointment_id")
        if cid_cancel:
            ag["last_cancelled_appointment_id"] = str(cid_cancel)
    return {"ag_state": ag, "action_type": at, "skipped_duplicate": False}


def _act_none(ctx: dict[str, Any], payload: dict[str, Any]) -> None:
    try:
        cid = (ctx.get("cliente_id") or "")[-4:]
        print(
            f"[agendamento_ia] action=none cliente_id=…{cid} node={ctx.get('node_id')!r}",
            flush=True,
        )
    except Exception:
        pass


def _act_schedule(ctx: dict[str, Any], payload: dict[str, Any]) -> None:
    """Regista appointment devolvido pelo motor (espelho no Supabase vem via webhook)."""
    try:
        cid = (ctx.get("cliente_id") or "")[-4:]
        appt = payload.get("appointment")
        appt_id = None
        if isinstance(appt, dict):
            appt_id = appt.get("id") or appt.get("appointment_id")
        print(
            f"[agendamento_ia] action=schedule cliente_id=…{cid} appointment_id={appt_id!r}",
            flush=True,
        )
    except Exception:
        pass


def _act_cancel(ctx: dict[str, Any], payload: dict[str, Any]) -> None:
    try:
        cid = (ctx.get("cliente_id") or "")[-4:]
        print(
            f"[agendamento_ia] action=cancel (stub) cliente_id=…{cid} payload_keys={list(payload.keys())!r}",
            flush=True,
        )
    except Exception:
        pass


def _act_list_slots(ctx: dict[str, Any], payload: dict[str, Any]) -> None:
    try:
        cid = (ctx.get("cliente_id") or "")[-4:]
        print(
            f"[agendamento_ia] action=list_slots (stub) cliente_id=…{cid} payload_keys={list(payload.keys())!r}",
            flush=True,
        )
    except Exception:
        pass
