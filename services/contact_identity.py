from __future__ import annotations

import re


def _digits_only(value: str | None) -> str:
    return "".join(c for c in (value or "") if c.isdigit())


def normalize_whatsapp_phone(remote_id: str | None) -> str | None:
    """
    Normaliza um identificador WhatsApp para um telefone E.164 em dígitos (sem '+'),
    **somente quando for confiável**.

    Regras:
    - Preserva apenas dígitos.
    - Se `remote_id` tiver sufixo tipo '@c.us' / '@s.whatsapp.net' / '@lid', usa apenas o prefixo.
    - Aceita como telefone Brasil:
      - 10 ou 11 dígitos (DDD + número) -> prefixa '55'
      - 12 ou 13 dígitos começando com '55' -> mantém
    - Qualquer outra coisa (ex.: IDs longos @lid) retorna None.
    """
    s = (remote_id or "").strip()
    if not s:
        return None

    # Se vier JID, isolamos a parte antes do '@'. (Ex.: 5511999999999@c.us / 3017...@lid)
    if "@" in s:
        s = s.split("@", 1)[0].strip()

    # Remove '+' e tudo que não for dígito
    d = _digits_only(s.replace("+", ""))
    if not d:
        return None

    # Heurística Brasil / E.164 (dígitos):
    # - 10/11 dígitos: assume BR sem DDI, prefixa 55
    # - 12/13 dígitos começando com 55: já está em E.164 (sem '+')
    if len(d) in (10, 11):
        return f"55{d}"
    if len(d) in (12, 13) and d.startswith("55"):
        return d

    # Para não "inventar" telefone a partir de @lid (geralmente muito longo),
    # rejeitamos tudo fora desses padrões.
    return None


def normalize_whatsapp_remote_key(remote_id: str | None) -> str:
    """
    Normalização leve do remote_id para comparações/dedup (não é telefone).
    Ex.: '5511...@c.us' -> '5511...'
    """
    s = (remote_id or "").strip()
    if "@" in s:
        s = s.split("@", 1)[0].strip()
    return s

