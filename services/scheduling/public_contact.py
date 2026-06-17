"""Nome e telefone na página pública /agenda/<slug>."""
from __future__ import annotations

import re

from services.contact_identity import normalize_whatsapp_phone


def digits_only(raw: str | None) -> str:
    return "".join(c for c in (raw or "") if c.isdigit())


def format_br_phone_input(raw: str | None, *, with_country: bool = False) -> str:
    """Máscara visual BR: (11) 99999-9999 ou +55 (11) 99999-9999."""
    d = digits_only(raw)
    if d.startswith("55") and len(d) > 11:
        d = d[2:]
    d = d[:11]
    if not d:
        return ""
    if len(d) <= 2:
        local = f"({d}"
    elif len(d) <= 6:
        local = f"({d[:2]}) {d[2:]}"
    elif len(d) <= 10:
        local = f"({d[:2]}) {d[2:6]}-{d[6:]}"
    else:
        local = f"({d[:2]}) {d[2:7]}-{d[7:11]}"
    if with_country and local:
        return f"+55 {local}"
    return local


def normalize_scheduling_contact_phone(phone: str | None) -> str | None:
    """E.164 em dígitos com DDI 55 (ex.: 5511999999999)."""
    local = digits_only(phone)
    if local.startswith("55") and len(local) > 11:
        local = local[2:]
    if len(local) not in (10, 11):
        return None
    return normalize_whatsapp_phone(local) or normalize_whatsapp_phone(f"55{local}")


def parse_panel_contact_phone(phone: str | None) -> tuple[str | None, str | None]:
    """
    Normaliza telefone do painel de agenda.
    Retorna (e164_digits, erro_pt); telefone vazio => (None, None).
    """
    raw = (phone or "").strip()
    if not raw:
        return None, None
    norm = normalize_scheduling_contact_phone(raw)
    if not norm:
        return None, "Telefone inválido. Use o formato (11) 99999-9999."
    return norm, None


def validate_public_contact(*, name: str, phone: str) -> tuple[str, str, str | None]:
    """
    Valida nome e telefone do formulário público.
    Retorna (nome, telefone_e164_digits, erro_pt).
    """
    nome = re.sub(r"\s+", " ", (name or "").strip())
    if len(nome) < 2:
        return "", "", "Informe seu nome."
    if len(nome) > 120:
        return "", "", "Nome muito longo."

    local = digits_only(phone)
    if local.startswith("55") and len(local) > 11:
        local = local[2:]
    if len(local) not in (10, 11):
        return "", "", "Telefone inválido. Use o formato (11) 99999-9999."

    norm = normalize_scheduling_contact_phone(phone)
    if not norm:
        return "", "", "Telefone inválido. Confira o DDD e o número."

    return nome, norm, None
