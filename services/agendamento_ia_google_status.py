"""Integração Google Calendar com o Agendamento IA (status, connect, disconnect)."""
from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any

import requests

from services.agendamento_ia_urls import agendamento_ia_base_url, scheduling_integration_headers

logger = logging.getLogger(__name__)

_GOOGLE_STATUS_PATH = "/v1/integrations/zapaction/google/status"
_GOOGLE_CONNECT_PATH = "/v1/integrations/zapaction/google/connect"
_GOOGLE_DISCONNECT_PATH = "/v1/integrations/zapaction/google/disconnect"
_GOOGLE_TOKENS_PATH = "/v1/integrations/zapaction/google/tokens"


def _integration_url(path: str) -> str | None:
    base = agendamento_ia_base_url()
    if not base:
        return None
    return f"{base.rstrip('/')}{path}"


def fetch_google_status(
    cliente_id: str,
    *,
    provider_id: str | None = None,
    timeout_sec: int = 15,
) -> dict[str, Any] | None:
    url = _integration_url(_GOOGLE_STATUS_PATH)
    if not url:
        return None
    params: dict[str, str] = {"cliente_id": str(cliente_id).strip()}
    if provider_id:
        params["provider_id"] = str(provider_id).strip()
    try:
        r = requests.get(
            url,
            params=params,
            headers=scheduling_integration_headers(),
            timeout=timeout_sec,
        )
        if r.status_code >= 400:
            return {"error": f"http_{r.status_code}", "detail": (r.text or "")[:200]}
        data = r.json()
        if isinstance(data, dict):
            data = _normalize_provider_status(data)
        return data
    except requests.RequestException as e:
        logger.warning("google status fetch failed: %s", e)
        return {"error": "falha_ligacao_agenda", "detail": str(e)[:200]}


def fetch_google_status_by_providers(
    cliente_id: str,
    provider_ids: list[str],
    *,
    timeout_sec: int = 8,
    max_workers: int = 6,
) -> dict[str, dict[str, Any]]:
    """Status Google por profissional (paralelo, tolerante a falhas)."""
    ids = [str(p).strip() for p in provider_ids if str(p).strip()]
    if not ids:
        return {}
    out: dict[str, dict[str, Any]] = {}
    workers = min(max_workers, max(1, len(ids)))

    def _one(pid: str) -> tuple[str, dict[str, Any]]:
        st = fetch_google_status(cliente_id, provider_id=pid, timeout_sec=timeout_sec)
        return pid, st if isinstance(st, dict) else {"error": "status_indisponivel"}

    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {pool.submit(_one, pid): pid for pid in ids}
        for fut in as_completed(futures):
            pid, st = fut.result()
            out[pid] = st
    return out


def push_google_tokens_to_agendamento_ia(
    cliente_id: str,
    *,
    provider_id: str,
    refresh_token: str,
    calendar_id: str = "primary",
    timeout_sec: int = 15,
) -> tuple[bool, str | None]:
    """Envia refresh_token ao motor Agenda após OAuth no ZapAction."""
    url = _integration_url(_GOOGLE_TOKENS_PATH)
    if not url:
        return False, "agendamento_ia_nao_configurado"
    body = {
        "cliente_id": str(cliente_id).strip(),
        "provider_id": str(provider_id).strip(),
        "refresh_token": str(refresh_token).strip(),
        "calendar_id": (calendar_id or "primary").strip(),
    }
    try:
        r = requests.post(
            url,
            json=body,
            headers=scheduling_integration_headers(),
            timeout=timeout_sec,
        )
        if r.status_code == 404:
            return False, "provider_not_found"
        if r.status_code >= 400:
            detail = (r.text or "")[:200]
            try:
                payload = r.json()
                if isinstance(payload, dict) and payload.get("detail"):
                    detail = str(payload["detail"])[:200]
            except Exception:
                pass
            return False, f"http_{r.status_code}:{detail}"
        return True, None
    except requests.RequestException as e:
        logger.warning("google tokens push failed: %s", e)
        return False, "falha_ligacao_agenda"


def fetch_google_connect_authorize_url(
    cliente_id: str,
    *,
    provider_id: str,
    return_url: str,
    timeout_sec: int = 15,
) -> tuple[str | None, str | None]:
    """
    Obtém URL de autorização Google no Agendamento IA.
    Retorno: (authorize_url, erro).
    """
    url = _integration_url(_GOOGLE_CONNECT_PATH)
    if not url:
        return None, "agendamento_ia_nao_configurado"
    params = {
        "cliente_id": str(cliente_id).strip(),
        "provider_id": str(provider_id).strip(),
        "return_url": (return_url or "").strip(),
    }
    try:
        r = requests.get(
            url,
            params=params,
            headers=scheduling_integration_headers(),
            timeout=timeout_sec,
        )
        if r.status_code == 404:
            try:
                body = r.json()
                detail = body.get("detail") if isinstance(body, dict) else ""
                if detail == "provider_not_found":
                    return None, "provider_not_found"
            except Exception:
                pass
            return None, "endpoint_connect_indisponivel"
        if r.status_code >= 400:
            detail = (r.text or "")[:200]
            try:
                body = r.json()
                if isinstance(body, dict) and body.get("detail"):
                    detail = str(body["detail"])[:200]
            except Exception:
                pass
            return None, f"http_{r.status_code}:{detail}"
        data = r.json()
        if not isinstance(data, dict):
            return None, "resposta_invalida"
        auth = (data.get("authorize_url") or "").strip()
        if not auth:
            return None, "authorize_url_em_falta"
        return auth, None
    except requests.RequestException as e:
        logger.warning("google connect fetch failed: %s", e)
        return None, "falha_ligacao_agenda"


def disconnect_google_provider(
    cliente_id: str,
    *,
    provider_id: str,
    timeout_sec: int = 15,
) -> tuple[bool, str | None]:
    url = _integration_url(_GOOGLE_DISCONNECT_PATH)
    if not url:
        return False, "agendamento_ia_nao_configurado"
    params = {
        "cliente_id": str(cliente_id).strip(),
        "provider_id": str(provider_id).strip(),
    }
    try:
        r = requests.post(
            url,
            params=params,
            headers=scheduling_integration_headers(),
            timeout=timeout_sec,
        )
        if r.status_code == 404:
            return False, "provider_not_found"
        if r.status_code >= 400:
            return False, f"http_{r.status_code}"
        return True, None
    except requests.RequestException as e:
        logger.warning("google disconnect failed: %s", e)
        return False, "falha_ligacao_agenda"


def _normalize_provider_status(data: dict[str, Any]) -> dict[str, Any]:
    """Expõe `connected` de forma consistente para o template."""
    if data.get("error"):
        return data
    if "connected" not in data:
        has_refresh = bool(data.get("refresh_token"))
        cal_ok = bool(data.get("calendar_access") or data.get("freebusy_ok"))
        err = data.get("last_error")
        data["connected"] = bool(has_refresh and cal_ok and not err)
    return data


def google_provider_ui_status(status: dict[str, Any] | None) -> str:
    """
    Rótulo UI: connected | needs_reconnect | disconnected | error | unavailable
    """
    if not status:
        return "unavailable"
    if status.get("error"):
        return "error"
    if status.get("connected"):
        return "connected"
    if status.get("last_error"):
        return "needs_reconnect"
    if status.get("refresh_token") or status.get("provider_connected"):
        return "needs_reconnect"
    return "disconnected"
