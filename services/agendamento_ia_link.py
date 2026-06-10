"""
Cliente HTTP: POST /v1/link/generate no Agendamento IA.
"""
from __future__ import annotations

import json
import time
from typing import Any

import requests

from base.config import settings
from services.agendamento_ia_urls import (
    link_generate_available,
    resolved_link_generate_url,
    scheduling_integration_headers,
)


def build_zapaction_public_agenda_url(
    slug: str,
    *,
    phone: str = "",
    name: str = "",
) -> str:
    """URL pública /agenda/{slug} no domínio de marketing (motor interno)."""
    from urllib.parse import urlencode

    from base.domain_redirects import public_base_url

    s = (slug or "").strip()
    if not s:
        return ""
    base = f"{public_base_url().rstrip('/')}/agenda/{s}"
    params: dict[str, str] = {}
    if (phone or "").strip():
        params["phone"] = phone.strip()
    if (name or "").strip():
        params["name"] = name.strip()
    if params:
        return f"{base}?{urlencode(params)}"
    return base


def generate_appointment_link(
    *,
    cliente_id: str,
    remote_id: str,
    canal: str = "whatsapp",
    node_id: str | None = None,
) -> dict[str, Any]:
    """
    Gera link tokenizado para agendamento no browser (Agendamento IA).

    Retorno: ok, url, http_status, error, duration_ms, raw (dict|None).
    """
    t0 = time.perf_counter()
    out: dict[str, Any] = {
        "ok": False,
        "url": "",
        "http_status": None,
        "error": None,
        "duration_ms": 0,
        "raw": None,
    }
    url_endpoint = resolved_link_generate_url()
    if not url_endpoint:
        out["error"] = "link_generate_nao_configurado"
        out["duration_ms"] = int((time.perf_counter() - t0) * 1000)
        return out

    cid = (cliente_id or "").strip()
    rid = (remote_id or "").strip()
    if not cid or not rid:
        out["error"] = "cliente_id_ou_remote_id_em_falta"
        out["duration_ms"] = int((time.perf_counter() - t0) * 1000)
        return out

    body: dict[str, Any] = {
        "cliente_id": cid,
        "remote_id": rid,
        "canal": (canal or "whatsapp").strip() or "whatsapp",
    }
    if node_id and str(node_id).strip():
        body["node_id"] = str(node_id).strip()

    timeout = int(getattr(settings, "AGENDAMENTO_IA_TIMEOUT_SEC", 25) or 25)
    try:
        r = requests.post(
            url_endpoint,
            json=body,
            headers=scheduling_integration_headers(),
            timeout=timeout,
        )
        out["http_status"] = r.status_code
        out["ok"] = 200 <= r.status_code < 300
        if out["ok"] and r.text:
            try:
                data = json.loads(r.text)
            except json.JSONDecodeError:
                data = None
            if isinstance(data, dict):
                out["raw"] = data
                link = (data.get("url") or data.get("link") or "").strip()
                if link:
                    out["url"] = link
                    out["ok"] = True
                else:
                    out["ok"] = False
                    out["error"] = "resposta_sem_url"
            else:
                out["ok"] = False
                out["error"] = "resposta_invalida"
        elif not out["ok"]:
            out["error"] = f"http_{r.status_code}"
    except requests.Timeout:
        out["error"] = "timeout"
    except Exception as e:
        out["error"] = f"request:{e!s}"
    out["duration_ms"] = int((time.perf_counter() - t0) * 1000)
    return out


def resolve_booking_url_for_contact(
    *,
    cliente_id: str,
    remote_id: str,
    canal: str = "whatsapp",
    node_id: str | None = None,
    contact_name: str = "",
    contact_phone: str = "",
    prefer_token_link: bool = False,
) -> tuple[str, str]:
    """
    URL para o cliente marcar horário.

    Prioridade (prod com Agenda):
    1. ``/v1/book/{slug}/page?phone=&name=`` (canónico)
    2. ``POST /v1/link/generate`` se ``prefer_token_link`` ou book indisponível
    3. ``/agenda/{slug}`` no domínio ZapAction (motor interno / dev)

    Retorno: (url, fonte): ``book_page``, ``agenda_link``, ``public_slug`` ou ``""``.
    """
    try:
        from services.agendamento_ia_bridge import scheduling_uses_internal_motor
        from services.agendamento_ia_contact import booking_phone_for_public_url
        from services.agendamento_ia_urls import (
            agendamento_ia_configured,
            build_public_book_page_url,
        )
        from services.scheduling import repository as sched_repo
    except Exception:
        return "", ""

    book_phone = booking_phone_for_public_url(
        remote_id=remote_id or "",
        contact_phone=contact_phone or "",
        canal=canal,
    )

    slug = ""
    if sched_repo.supabase_available():
        st = sched_repo.get_settings(str(cliente_id))
        if st:
            slug = str(st.get("public_slug") or "").strip()

    if scheduling_uses_internal_motor(str(cliente_id)) and slug:
        return (
            build_zapaction_public_agenda_url(
                slug,
                phone=book_phone,
                name=(contact_name or "").strip(),
            ),
            "public_slug",
        )

    if agendamento_ia_configured() and slug and not prefer_token_link:
        book_url = build_public_book_page_url(
            slug,
            phone=book_phone,
            name=(contact_name or "").strip(),
        )
        if book_url:
            return book_url, "book_page"

    if link_generate_available() and (remote_id or "").strip():
        gen = generate_appointment_link(
            cliente_id=cliente_id,
            remote_id=remote_id,
            canal=canal,
            node_id=node_id,
        )
        if gen.get("ok") and (gen.get("url") or "").strip():
            return str(gen["url"]).strip(), "agenda_link"

    if not slug:
        return "", ""

    try:
        book_url = build_public_book_page_url(
            slug,
            phone=book_phone,
            name=(contact_name or "").strip(),
        )
        if book_url:
            return book_url, "book_page"
    except Exception:
        pass

    return build_zapaction_public_agenda_url(
        slug,
        phone=book_phone,
        name=(contact_name or "").strip(),
    ), "public_slug"
