"""
Sincronização painel ZapAction → Agendamento IA (HTTP).

Quando `AGENDAMENTO_IA_CLINIC_SYNC_URL` está definida, após alterações na agenda
do painel enviamos um JSON com o estado atual do tenant (clínica, horários da
clínica, profissionais, serviços, horários por profissional).

O serviço Agendamento IA deve expor um endpoint que aceite POST JSON com o
contrato abaixo (pode ignorar campos que não use).

Implementação de referência (FastAPI): POST
``/v1/integrations/zapaction/tenant-snapshot`` no projeto agendamento-ia,
com Bearer ``AGENT_BEARER_TOKEN`` (ou o mesmo token usado em ``/v1/ops/*``).

Contrato (request_schema_version = 1):
{
  "event": "zapaction.scheduling.tenant_snapshot",
  "request_schema_version": 1,
  "cliente_id": "<uuid>",
  "clinic": {
    "public_name": str | null,
    "public_slug": str | null,
    "timezone": str,
    "working_hours_clinic": [
      {"day_of_week": 0-6, "start_time": "HH:MM", "end_time": "HH:MM"}
    ],
    "working_hours_by_professional": [
      {"professional_id": "<uuid>", "day_of_week": 0-6,
       "start_time": "...", "end_time": "..."}
    ]
  },
  "professionals": [{"id": "...", "name": "...", "active": true, "sort_order": 0}],
  "services": [
    {"id": "...", "name": "...", "duration_minutes": 30,
     "professional_id": "<uuid>|null", "active": true, "sort_order": 0}
  ],
  "provider_services": [
    {"provider_id": "<uuid>", "service_id": "<uuid>"}
  ]
}

provider_services: vínculos explícitos no Agenda. Serviço com professional_id → um par;
sem professional_id («Qualquer») → um par por cada profissional ativo.

No Agenda, cada snapshot substitui o catálogo: profissionais/serviços removidos no painel
deixam de existir após o POST (exceto o provider placeholder da clínica).
"""
from __future__ import annotations

import logging
import time
from typing import Any

import requests

from base.config import settings
from services.agendamento_ia_urls import resolved_clinic_sync_url, scheduling_integration_headers
from services.scheduling import repository as sched_repo

logger = logging.getLogger(__name__)

SYNC_REQUEST_SCHEMA_VERSION = 1


def build_provider_services_links(
    professionals: list[dict[str, Any]],
    services: list[dict[str, Any]],
) -> list[dict[str, str]]:
    """
    Matriz profissional ↔ serviço para o motor Agenda (provider_services).

    - Serviço com professional_id: um vínculo.
    - Sem professional_id («Qualquer»): todos os profissionais ativos.
    """
    active_prof_ids = {
        str(p.get("id"))
        for p in professionals
        if p.get("id") and bool(p.get("active", True))
    }
    links: list[dict[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for s in services:
        if not s.get("id") or not bool(s.get("active", True)):
            continue
        sid = str(s["id"])
        pid = s.get("professional_id")
        if pid:
            pid_str = str(pid)
            targets = [pid_str] if pid_str in active_prof_ids else []
        else:
            targets = sorted(active_prof_ids)
        for p in targets:
            if not p:
                continue
            key = (p, sid)
            if key in seen:
                continue
            seen.add(key)
            links.append({"provider_id": p, "service_id": sid})
    return links


def clinic_sync_configured() -> bool:
    return bool(resolved_clinic_sync_url())


def ensure_tenant_synced_for_agenda(cliente_id: str) -> tuple[bool, str | None]:
    """
    Envia tenant-snapshot ao Agendamento IA (profissionais, serviços, horários).
    Necessário antes de gravar tokens Google (provider_id tem de existir no Agenda).
    """
    if not clinic_sync_configured():
        return False, (
            "Sincronização com o Agendamento IA não está configurada. "
            "Defina AGENDAMENTO_IA_BASE_URL ou AGENDAMENTO_IA_CLINIC_SYNC_URL e "
            "AGENDAMENTO_IA_API_KEY no .env."
        )
    ok, err, _partial = push_tenant_snapshot_to_agendamento_ia(cliente_id)
    record_sync_result(
        cliente_id,
        ok=ok,
        error=err if not ok else None,
        partial=_partial,
    )
    if not ok:
        return False, err or "sincronização_falhou"
    return True, None


_SYNC_THROTTLE_SEC = 90


def _sync_throttle_key(cliente_id: str) -> str:
    return f"agenda_sync_push_at_{(cliente_id or '')[:36]}"


def _should_throttle_agenda_push(cliente_id: str) -> bool:
    try:
        from flask import has_request_context, session

        if not has_request_context():
            return False
        key = _sync_throttle_key(cliente_id)
        last = float(session.get(key) or 0)
        return (time.time() - last) < _SYNC_THROTTLE_SEC
    except Exception:
        return False


def _mark_agenda_push_synced(cliente_id: str) -> None:
    try:
        from flask import has_request_context, session

        if not has_request_context():
            return
        session[_sync_throttle_key(cliente_id)] = time.time()
        session.modified = True
    except Exception:
        pass


def sync_catalog_to_agendamento_ia(
    cliente_id: str,
    *,
    force: bool = False,
) -> str | None:
    """
    Espelha o catálogo do painel (Supabase) no Agendamento IA.
    Com force=True ignora throttle (botão «Sincronizar agora»).
    Retorna mensagem de erro ou None se OK / ignorado por throttle.
    """
    if not clinic_sync_configured():
        return None
    if not force and _should_throttle_agenda_push(cliente_id):
        return None
    ok, err = ensure_tenant_synced_for_agenda(cliente_id)
    if ok:
        _mark_agenda_push_synced(cliente_id)
        return None
    return err


def _normalize_time(v: Any) -> str:
    if v is None:
        return ""
    s = str(v).strip()
    if len(s) >= 5 and s[2] == ":":
        return s[:5]
    return s


def build_tenant_snapshot_payload(cliente_id: str) -> dict[str, Any] | None:
    if not sched_repo.supabase_available():
        return None
    st = sched_repo.get_settings(cliente_id) or {}
    wh_all = sched_repo.list_working_hours_all(cliente_id)
    clinic_wh: list[dict[str, Any]] = []
    prof_wh: list[dict[str, Any]] = []
    for h in wh_all:
        pid = h.get("professional_id")
        if pid in (None, ""):
            clinic_wh.append(
                {
                    "day_of_week": int(h.get("day_of_week") or 0),
                    "start_time": _normalize_time(h.get("start_time")),
                    "end_time": _normalize_time(h.get("end_time")),
                }
            )
        else:
            prof_wh.append(
                {
                    "professional_id": str(pid),
                    "day_of_week": int(h.get("day_of_week") or 0),
                    "start_time": _normalize_time(h.get("start_time")),
                    "end_time": _normalize_time(h.get("end_time")),
                }
            )
    professionals = sched_repo.list_professionals(cliente_id, active_only=False)
    services = sched_repo.list_services(cliente_id, active_only=False)
    prof_out = [
        {
            "id": str(p.get("id")),
            "name": p.get("name") or "",
            "active": bool(p.get("active", True)),
            "sort_order": int(p.get("sort_order") or 0),
        }
        for p in professionals
        if p.get("id")
    ]
    svc_out = [
        {
            "id": str(s.get("id")),
            "name": s.get("name") or "",
            "duration_minutes": int(s.get("duration_minutes") or 30),
            "professional_id": str(s["professional_id"]) if s.get("professional_id") else None,
            "active": bool(s.get("active", True)),
            "sort_order": int(s.get("sort_order") or 0),
        }
        for s in services
        if s.get("id")
    ]
    provider_services = build_provider_services_links(prof_out, svc_out)
    from services.scheduling.slug import normalize_public_slug

    slug_norm = normalize_public_slug(st.get("public_slug"))
    return {
        "event": "zapaction.scheduling.tenant_snapshot",
        "request_schema_version": SYNC_REQUEST_SCHEMA_VERSION,
        "cliente_id": str(cliente_id),
        "clinic": {
            "public_name": st.get("public_name"),
            "public_slug": slug_norm,
            "timezone": (st.get("timezone") or "America/Sao_Paulo") or "America/Sao_Paulo",
            "working_hours_clinic": clinic_wh,
            "working_hours_by_professional": prof_wh,
            "confirmation_policy": st.get("confirmation_policy") or "auto",
            "confirmation_pending_ttl_hours": int(st.get("confirmation_pending_ttl_hours") or 48),
        },
        "professionals": prof_out,
        "services": svc_out,
        "provider_services": provider_services,
    }


def _response_detail_snippet(response: requests.Response) -> str:
    text = (response.text or "").strip()
    if not text:
        return ""
    try:
        data = response.json()
    except Exception:
        return text[:240]
    if isinstance(data, dict):
        detail = data.get("detail")
        if isinstance(detail, str) and detail.strip():
            return detail.strip()[:240]
        if isinstance(detail, dict):
            err = detail.get("error") or detail.get("code")
            reason = detail.get("reason")
            if err and reason:
                return f"{err}: {reason}"[:240]
            return str(detail)[:240]
    return text[:240]


def _post_snapshot(
    url: str, payload: dict[str, Any], *, cliente_id: str, timeout: int
) -> tuple[bool, str | None, requests.Response | None]:
    try:
        r = requests.post(url, json=payload, headers=scheduling_integration_headers(), timeout=timeout)
    except requests.Timeout:
        logger.warning("agendamento_ia_sync timeout cliente_id=%s", cliente_id[:8])
        return False, "timeout", None
    except Exception as e:
        logger.warning("agendamento_ia_sync erro cliente_id=%s err=%s", cliente_id[:8], e)
        return False, str(e), None
    if 200 <= r.status_code < 300:
        return True, None, r
    detail = _response_detail_snippet(r)
    err = f"http_{r.status_code}"
    if detail:
        err = f"{err}: {detail}"
    logger.warning(
        "agendamento_ia_sync falhou cliente_id=%s %s body=%s",
        cliente_id[:8],
        err,
        (r.text or "")[:500],
    )
    return False, err, r


def push_tenant_snapshot_to_agendamento_ia(
    cliente_id: str,
) -> tuple[bool, str | None, str | None]:
    """
    POST do snapshot completo.

    Retorno: (ok, mensagem_erro, aviso_parcial). Falha com HTTP 500 devolve o motivo
    quando o Agenda expõe ``detail.reason``.
    """
    url = resolved_clinic_sync_url()
    if not url:
        return True, None, None
    payload = build_tenant_snapshot_payload(cliente_id)
    if payload is None:
        return False, "supabase_indisponível", None
    timeout = int(getattr(settings, "AGENDAMENTO_IA_CLINIC_SYNC_TIMEOUT_SEC", 30) or 30)
    t0 = time.perf_counter()
    ok, err, _r = _post_snapshot(url, payload, cliente_id=cliente_id, timeout=timeout)
    ms = int((time.perf_counter() - t0) * 1000)
    if ok:
        logger.info(
            "agendamento_ia_sync ok cliente_id=%s http=200 ms=%s services=%s",
            cliente_id[:8],
            ms,
            len(payload.get("services") or []),
        )
        return True, None, None

    return False, err, None


def sync_status_for_panel(cliente_id: str) -> dict[str, Any]:
    """
    Estado da última sincronização (para o wizard).
    Não executa sync — apenas lê o registo em memória de sessão Flask, se existir.
    """
    try:
        from flask import has_request_context, session

        if not has_request_context():
            return {}
        key = f"agenda_sync_{(cliente_id or '')[:36]}"
        raw = session.get(key)
        return dict(raw) if isinstance(raw, dict) else {}
    except Exception:
        return {}


def record_sync_result(
    cliente_id: str,
    *,
    ok: bool,
    error: str | None = None,
    partial: str | None = None,
) -> None:
    """Guarda resultado do último snapshot na sessão do utilizador (painel)."""
    try:
        from datetime import datetime, timezone

        from flask import has_request_context, session

        if not has_request_context():
            return
        key = f"agenda_sync_{(cliente_id or '')[:36]}"
        session[key] = {
            "ok": ok,
            "error": error,
            "partial": partial,
            "at": datetime.now(timezone.utc).isoformat(),
            "url": resolved_clinic_sync_url() or None,
        }
        session.modified = True
    except Exception:
        pass


def maybe_sync_after_panel_change(cliente_id: str) -> str | None:
    """
    Chamar após mutações no painel.
    Devolve None se sync desligada ou sucesso total; string de aviso/erro se falhou ou parcial.
    """
    if not clinic_sync_configured():
        record_sync_result(cliente_id, ok=True, error=None, partial=None)
        return None
    ok, err, partial = push_tenant_snapshot_to_agendamento_ia(cliente_id)
    record_sync_result(
        cliente_id,
        ok=ok,
        error=err if not ok else None,
        partial=partial,
    )
    if not ok:
        return err or "erro_desconhecido"
    _mark_agenda_push_synced(cliente_id)
    return partial
