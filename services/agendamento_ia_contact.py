"""
Normalização de dados de contacto (questionário / lead) para o motor Agendamento IA.
"""
from __future__ import annotations

import re
from typing import Any

from services.flow_helpers import collected_data_for_lead


def _digits_only(value: str | None) -> str:
    return "".join(c for c in (value or "") if c.isdigit())


def _pick_str(data: dict, *keys: str) -> str:
    for k in keys:
        v = data.get(k)
        if v is not None and str(v).strip():
            return str(v).strip()
    return ""


def normalize_collected_for_agendamento(collected: dict | None) -> dict[str, Any]:
    """
    Remove chaves internas (__*) e unifica aliases para nome, email, telefone.
    """
    if not isinstance(collected, dict):
        return {}
    base = collected_data_for_lead(collected)
    nome = _pick_str(base, "nome", "name", "Nome", "campo_1")
    if nome:
        nome = re.sub(r"^[\s,;.\-]+|[\s,;.\-]+$", "", nome).strip()
    email = _pick_str(base, "email", "e-mail", "e_mail", "mail", "E-mail", "campo_2")
    telefone = _pick_str(
        base, "telefone", "phone", "celular", "telemovel", "Telefone", "campo_3"
    )
    out: dict[str, Any] = {k: v for k, v in base.items() if not str(k).startswith("__")}
    if nome:
        out["nome"] = nome
    if email:
        out["email"] = email
    if telefone:
        out["telefone"] = telefone
    return out


def has_contact_fields(collected: dict | None) -> bool:
    cd = normalize_collected_for_agendamento(collected)
    return bool(cd.get("nome") or cd.get("email") or cd.get("telefone"))


def lead_row_to_collected(row: dict | None) -> dict[str, Any]:
    """Converte linha da tabela leads em collected_data normalizado."""
    if not row or not isinstance(row, dict):
        return {}
    from database.models import LeadModel

    merged: dict[str, Any] = {}
    dados = row.get(LeadModel.DADOS)
    if isinstance(dados, dict):
        merged.update(dados)
    for key, col in (
        ("nome", LeadModel.NOME),
        ("email", LeadModel.EMAIL),
        ("telefone", LeadModel.TELEFONE),
    ):
        val = (row.get(col) or "").strip()
        if val:
            merged[key] = val
    return normalize_collected_for_agendamento(merged)


def enrich_collected_from_lead(
    collected: dict | None, lead_row: dict | None
) -> dict[str, Any]:
    """Preenche campos em falta no estado do fluxo com o lead mais recente no Supabase."""
    out = normalize_collected_for_agendamento(collected)
    if not lead_row:
        return out
    from_lead = lead_row_to_collected(lead_row)
    for key in ("nome", "email", "telefone"):
        if not out.get(key) and from_lead.get(key):
            out[key] = from_lead[key]
    for k, v in from_lead.items():
        if k in ("nome", "email", "telefone"):
            continue
        if k not in out and v is not None and str(v).strip():
            out[k] = v
    return normalize_collected_for_agendamento(out)


def booking_phone_for_public_url(
    *,
    remote_id: str = "",
    contact_phone: str = "",
    canal: str = "whatsapp",
) -> str:
    """
    Telefone seguro para query ``?phone=`` na página /v1/book/....

    Evita passar JID/LID (ex. ``9130...@lid``) que quebra a agenda pública.
    """
    from services.contact_identity import normalize_whatsapp_phone

    for candidate in ((contact_phone or "").strip(), (remote_id or "").strip()):
        if not candidate:
            continue
        norm = normalize_whatsapp_phone(candidate)
        if norm:
            return norm
    if (canal or "").strip().lower() != "whatsapp":
        d = _digits_only(contact_phone or remote_id)
        if 8 <= len(d) <= 15:
            return d
    return ""


def contact_hints_from_collected(collected: dict | None) -> dict[str, str]:
    """Campos aceites pelo motor Agendamento IA (contact_name, contact_email, contact_phone)."""
    cd = normalize_collected_for_agendamento(collected)
    out: dict[str, str] = {}
    nome = (cd.get("nome") or "").strip()
    email = (cd.get("email") or "").strip()
    tel = (cd.get("telefone") or "").strip()
    if nome:
        out["contact_name"] = nome[:200]
    if email:
        out["contact_email"] = email[:200]
    if tel:
        out["contact_phone"] = tel[:80]
    return out


def prepare_agendamento_context(context: dict[str, Any]) -> dict[str, Any]:
    """Garante collected_data normalizado e hints de contacto no contexto do POST."""
    ctx = dict(context) if isinstance(context, dict) else {}
    collected = normalize_collected_for_agendamento(ctx.get("collected_data"))
    ctx["collected_data"] = collected
    hints = contact_hints_from_collected(collected)
    for k, v in hints.items():
        if v and not (ctx.get(k) or "").strip():
            ctx[k] = v
    if not (ctx.get("contact_phone") or "").strip():
        canal = (ctx.get("canal") or "").strip().lower()
        phone_url = booking_phone_for_public_url(
            remote_id=str(ctx.get("remote_id") or ""),
            contact_phone="",
            canal=canal or "whatsapp",
        )
        if phone_url:
            ctx["contact_phone"] = phone_url
    return ctx
