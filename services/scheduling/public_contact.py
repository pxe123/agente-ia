"""Nome e telefone na página pública /agenda/<slug>."""
from __future__ import annotations

import re

from services.contact_identity import normalize_whatsapp_phone


def digits_only(raw: str | None) -> str:
    return "".join(c for c in (raw or "") if c.isdigit())


def format_br_phone_input(raw: str | None) -> str:
    """Máscara visual BR: (11) 99999-9999 ou (11) 9999-9999."""
    d = digits_only(raw)
    if d.startswith("55") and len(d) > 11:
        d = d[2:]
    d = d[:11]
    if not d:
        return ""
    if len(d) <= 2:
        return f"({d}"
    if len(d) <= 6:
        return f"({d[:2]}) {d[2:]}"
    if len(d) <= 10:
        return f"({d[:2]}) {d[2:6]}-{d[6:]}"
    return f"({d[:2]}) {d[2:7]}-{d[7:11]}"


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

    norm = normalize_whatsapp_phone(local) or normalize_whatsapp_phone(f"55{local}")
    if not norm:
        return "", "", "Telefone inválido. Confira o DDD e o número."

    return nome, norm, None
