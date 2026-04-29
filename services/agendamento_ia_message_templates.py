# services/agendamento_ia_message_templates.py
"""
Mensagem ao canal a partir de `node_data` + resposta da API (sem reply/message do backend).
Placeholders: {{status}}, {{intent}}, {{error_code}}, {{slot_list}}, {{start}}, {{end}}, {{appointment_id}}.
"""
from __future__ import annotations

import json
from typing import Any


def _as_str(d: Any, *keys: str) -> str:
    cur: Any = d
    for k in keys:
        if not isinstance(cur, dict):
            return ""
        cur = cur.get(k)
    if cur is None:
        return ""
    return str(cur).strip()


def _format_slots_for_display(data: dict[str, Any]) -> str:
    slots = data.get("slots")
    if not isinstance(slots, list) or not slots:
        return ""
    lines: list[str] = []
    for i, s in enumerate(slots, start=1):
        if not isinstance(s, dict):
            continue
        a = s.get("start", "")
        b = s.get("end", "")
        lines.append(f"{i}) {a} – {b}")
    return "\n".join(lines)


def _get_templates(node_data: dict[str, Any]) -> dict[str, str]:
    raw = node_data.get("message_templates")
    out: dict[str, str] = {}
    if isinstance(raw, str) and raw.strip().startswith("{"):
        try:
            j = json.loads(raw)
            if isinstance(j, dict):
                for k, v in j.items():
                    if v is not None and str(v).strip():
                        out[str(k)] = str(v)
        except Exception:
            out = {}
    elif isinstance(raw, dict):
        for k, v in raw.items():
            if isinstance(v, str) and v.strip():
                out[str(k)] = v
    for short, longk in (
        ("default", "template_default"),
        ("ok", "template_ok"),
        ("needs_input", "template_needs_input"),
        ("error", "template_error"),
    ):
        v = node_data.get(longk)
        if isinstance(v, str) and v.strip() and short not in out:
            out[short] = v
    if "default" not in out:
        m = (node_data.get("message_template") or "").strip()
        if m:
            out["default"] = m
    return out


def _placeholders(
    node_data: dict[str, Any], api_status: str, parsed: dict[str, Any]
) -> dict[str, str]:
    d = parsed.get("data")
    d = d if isinstance(d, dict) else {}
    ap = d.get("appointment")
    ap = ap if isinstance(ap, dict) else {}
    err = parsed.get("error")
    ecode = ""
    if isinstance(err, dict):
        ecode = str(err.get("code") or "").strip()
    sel = d.get("selected_slot")
    sel = sel if isinstance(sel, dict) else {}
    ph: dict[str, str] = {
        "status": api_status,
        "intent": str(d.get("intent") or ""),
        "error_code": ecode,
        "slot_list": _format_slots_for_display(d),
        "slots": _format_slots_for_display(d),
        "start": ap.get("start", "") or sel.get("start", "") or str(d.get("start", "")),
        "end": ap.get("end", "") or sel.get("end", "") or str(d.get("end", "")),
        "appointment_id": str(ap.get("id", "") or ""),
        "cancelled_appointment_id": str(d.get("cancelled_appointment_id") or ""),
    }
    extra = node_data.get("template_placeholders")
    if isinstance(extra, dict):
        for k, v in extra.items():
            ph[str(k)] = str(v) if v is not None else ""
    return ph


def _apply_template(tpl: str, ph: dict[str, str]) -> str:
    out = tpl
    for k, v in ph.items():
        out = out.replace("{{" + k + "}}", v)
    return out


def format_agendamento_user_message(
    node_data: dict[str, Any], parsed: dict[str, Any] | None
) -> str:
    if not isinstance(parsed, dict) or not isinstance(node_data, dict):
        return ""
    nd = node_data
    st = (parsed.get("api_status") or parsed.get("status") or "").strip() or "ok"
    if st not in ("ok", "needs_input", "error"):
        st = "ok" if (parsed.get("raw_error") or "") in ("", None) else "error"

    err_obj = parsed.get("error")
    ecode = str(err_obj.get("code", "")).strip() if isinstance(err_obj, dict) else ""

    tplmap = _get_templates(nd)
    if st == "error" and ecode:
        key_err = f"error_{ecode}"
        if key_err in tplmap and (tplmap.get(key_err) or "").strip():
            tpl = tplmap[key_err]
        else:
            tpl = tplmap.get("error", "") or tplmap.get("default", "")
    elif st == "ok" and (parsed.get("done") is True) and (tplmap.get("ok", "") or "").strip():
        tpl = tplmap["ok"]
    elif st == "needs_input" and (tplmap.get("needs_input", "") or "").strip():
        tpl = tplmap["needs_input"]
    else:
        tpl = (
            tplmap.get(st, "")
            or tplmap.get("default", "")
            or (nd.get("message_template") or "")
        )

    if not isinstance(tpl, str) or not tpl.strip():
        if st == "error" and ecode:
            return f"Erro: {ecode}"
        if st == "needs_input":
            ph0 = _placeholders(nd, st, parsed)
            if ph0.get("slot_list"):
                return f"Opções de horário:\n{ph0['slot_list']}"
        return ""
    ph = _placeholders(nd, st, parsed)
    return _apply_template(tpl, ph).strip()
