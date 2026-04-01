"""
Cliente WAHA (WhatsApp HTTP API).

Inclui:
- Envio de mensagens (sendText)
- Gerenciamento de sessões (criar/listar/status/qr/restart/logout)

Requer WAHA_URL e WAHA_API_KEY no .env.
"""

from __future__ import annotations

import os
import re
from typing import Any

import requests

from base.config import settings


def _headers(accept: str | None = "application/json") -> dict[str, str]:
    h = {"X-Api-Key": settings.WAHA_API_KEY}
    if accept:
        h["Accept"] = accept
    return h


def _sanitize_session_slug(value: str) -> str:
    v = (value or "").strip()
    v = re.sub(r"[^a-zA-Z0-9_-]+", "_", v)
    v = re.sub(r"_+", "_", v).strip("_")
    return v[:48]  # mantém nomes pequenos e previsíveis


def _tenant_slug(cliente_id: Any) -> str:
    s = str(cliente_id or "").strip()
    s = "".join(ch for ch in s if ch.isalnum())
    return (s[:12] or "anon").lower()


def build_session_name(cliente_id: Any, slug: str = "default") -> str:
    """
    Nome determinístico para sessão WAHA do cliente.
    Ex.: c1a2b3c4d5e6_default
    """
    safe = _sanitize_session_slug(slug) or "default"
    return f"c{_tenant_slug(cliente_id)}_{safe}"


def build_session_prefix(cliente_id: Any) -> str:
    """Prefixo usado para agrupar sessões por cliente no WAHA."""
    return f"c{_tenant_slug(cliente_id)}_"


def _ensure_configured() -> None:
    if not settings.WAHA_URL or not settings.WAHA_API_KEY:
        raise RuntimeError("WAHA_URL/WAHA_API_KEY não configurados no .env.")


def _waha_webhook_url() -> str:
    # Permite sobrescrever explicitamente a URL do webhook WAHA.
    explicit = (os.getenv("WAHA_WEBHOOK_URL") or "").strip().rstrip("/")
    if explicit:
        return explicit

    base = (getattr(settings, "WEBHOOK_URL", None) or "").strip().rstrip("/")
    if not base:
        return ""

    # Evita duplicar caminhos quando WEBHOOK_URL já inclui rota de outro webhook.
    if base.endswith("/webhook/waha"):
        return base
    if base.endswith("/webhook/meta"):
        base = base[: -len("/webhook/meta")]
        return f"{base}/webhook/waha"
    if base.endswith("/webhook"):
        return f"{base}/waha"
    return f"{base}/webhook/waha"


def _waha_webhook_hmac_key() -> str:
    v = (os.getenv("WAHA_WEBHOOK_HMAC_KEY") or "").strip()
    if v:
        return v
    return (getattr(settings, "SECRET_KEY", None) or "").strip()


def _build_webhook_config(session_name: str) -> list[dict[str, Any]]:
    url = _waha_webhook_url()
    if not url:
        return []
    cfg: dict[str, Any] = {
        "url": url,
        "events": ["message", "session.status"],
        "retries": {"policy": "constant", "delaySeconds": 2, "attempts": 10},
        "customHeaders": [{"name": "X-WAHA-Session", "value": session_name}],
    }
    hmac_key = _waha_webhook_hmac_key()
    if hmac_key:
        cfg["hmac"] = {"key": hmac_key}
    return [cfg]


def _mensagem_erro_amigavel(status_code: int, body: str) -> str:
    """Traduz erros conhecidos do WAHA (ex.: 422 Plus) para mensagem clara ao usuário."""
    body_lower = (body or "").lower()
    if status_code == 422 and ("plus version" in body_lower or "only in plus" in body_lower or "webjs" in body_lower):
        return (
            "Envio de mídia ou áudio requer WAHA Plus. "
            "Na versão gratuita (WEBJS) só mensagens de texto estão disponíveis. "
            "Consulte: https://waha.devlike.pro/"
        )
    return f"WAHA {status_code}: {body}"


def _normalize_chat_id(remote_id: str) -> tuple[str, str]:
    """
    Retorna (chat_id, numero_ou_id) para o WAHA.
    Preserva @lid e @c.us; converte @s.whatsapp.net para @c.us (exigência do WAHA).
    Assim conseguimos responder a contatos que vieram como LID.
    """
    raw = str(remote_id).strip().replace("+", "").replace(" ", "")
    if "@" in raw:
        numero = "".join(c for c in raw.split("@")[0] if c.isdigit())
        sufixo = raw.split("@", 1)[1].strip().lower()
        if sufixo in ("s.whatsapp.net", "c.us"):
            chat_id = f"{numero}@c.us" if numero else ""
        elif sufixo in ("lid", "g.us", "newsletter", "broadcast"):
            chat_id = f"{numero}@{sufixo}" if numero else ""
        else:
            chat_id = f"{numero}@c.us" if numero else ""
    else:
        numero = "".join(c for c in raw if c.isdigit()) or raw
        chat_id = f"{numero}@c.us" if numero else ""
    return chat_id, numero or raw


def enviar_texto(remote_id: str, texto: str, session: str = "default") -> tuple[bool, str | None]:
    """
    Envia mensagem de texto via WAHA.

    remote_id: número ou JID (ex: 5514999999999 ou 5514999999999@s.whatsapp.net)
    Retorna (True, None) em sucesso ou (False, mensagem_erro).
    """
    _ensure_configured()
    url = f"{settings.WAHA_URL}/api/sendText"
    headers = {"Content-Type": "application/json", **_headers(accept=None)}

    chat_id, para = _normalize_chat_id(remote_id)
    if not chat_id or not para:
        return (False, "Número de destino inválido.")

    payload = {"session": session, "chatId": chat_id, "text": texto}

    try:
        response = requests.post(url, json=payload, headers=headers, timeout=30)
        if response.status_code in (200, 201):
            import logging
            logging.getLogger(__name__).info("enviar_texto OK: chatId=%s", chat_id)
            return (True, None)
        body = response.text
        try:
            j = response.json()
            body = j.get("message", j.get("error", body))
        except Exception:
            pass
        err_msg = _mensagem_erro_amigavel(response.status_code, body)
        import logging
        logging.getLogger(__name__).warning("enviar_texto falhou: %s | payload session=%s chatId=%s", err_msg, session, chat_id)
        return (False, err_msg)
    except requests.exceptions.RequestException as e:
        return (False, f"Erro de conexão WAHA: {e}")


def enviar_botoes(
    remote_id: str,
    body_text: str,
    buttons: list[dict],
    session: str = "default",
) -> tuple[bool, str | None]:
    """
    Envia mensagem com botões de resposta (quick reply) via WAHA POST /api/sendButtons.
    Requer motor NOWEB (2024.10.5+). Em falha, o chamador deve fazer fallback para texto.
    buttons: [ {"id": "x", "title": "Sim"}, ... ] (até 3; title vira text do botão).
    """
    _ensure_configured()
    chat_id, _ = _normalize_chat_id(remote_id)
    if not chat_id:
        return (False, "Número de destino inválido.")
    reply_buttons = []
    for b in (buttons or [])[:3]:
        title = (b.get("title") or b.get("label") or "").strip() or "Opção"
        reply_buttons.append({"type": "reply", "text": title[:20]})
    if not reply_buttons:
        return (False, "Nenhum botão para enviar.")
    url = f"{settings.WAHA_URL}/api/sendButtons"
    headers = {"Content-Type": "application/json", **_headers(accept=None)}
    payload = {
        "session": session,
        "chatId": chat_id,
        "body": (body_text or "").strip() or " ",
        "buttons": reply_buttons,
    }
    try:
        response = requests.post(url, json=payload, headers=headers, timeout=30)
        if response.status_code in (200, 201):
            import logging
            logging.getLogger(__name__).info("enviar_botoes OK: chatId=%s buttons=%s", chat_id, len(reply_buttons))
            return (True, None)
        body = response.text
        try:
            j = response.json()
            body = j.get("message", j.get("error", body))
        except Exception:
            pass
        err_msg = _mensagem_erro_amigavel(response.status_code, body)
        import logging
        logging.getLogger(__name__).warning("enviar_botoes falhou: %s", err_msg)
        return (False, err_msg)
    except requests.exceptions.RequestException as e:
        return (False, f"Erro de conexão WAHA: {e}")


def _enviar_midia(
    remote_id: str,
    file_base64: str,
    mimetype: str,
    filename: str,
    caption: str,
    session: str,
    endpoint: str,
) -> tuple[bool, str | None]:
    """Envia mídia (imagem ou arquivo) via WAHA. file_base64 = conteúdo em base64 (sem data:...)."""
    _ensure_configured()
    chat_id, _ = _normalize_chat_id(remote_id)
    if not chat_id:
        return (False, "Número de destino inválido.")
    payload: dict[str, Any] = {
        "session": session,
        "chatId": chat_id,
        "file": {
            "mimetype": (mimetype or "application/octet-stream").strip(),
            "filename": (filename or "arquivo").strip() or "arquivo",
            "data": file_base64.strip(),
        },
        "caption": (caption or "").strip() or "",
    }
    url = f"{settings.WAHA_URL}{endpoint}"
    headers = {"Content-Type": "application/json", **_headers(accept=None)}
    try:
        response = requests.post(url, json=payload, headers=headers, timeout=60)
        if response.status_code in (200, 201):
            import logging
            logging.getLogger(__name__).info("WAHA %s OK chatId=%s", endpoint, chat_id)
            return (True, None)
        body = response.text
        try:
            j = response.json()
            body = j.get("message", j.get("error", body))
        except Exception:
            pass
        err_msg = _mensagem_erro_amigavel(response.status_code, body)
        import logging
        logging.getLogger(__name__).warning("WAHA %s falhou: %s", endpoint, err_msg)
        return (False, err_msg)
    except requests.exceptions.RequestException as e:
        return (False, f"Erro de conexão WAHA: {e}")


def enviar_imagem(
    remote_id: str,
    file_base64: str,
    mimetype: str = "image/jpeg",
    filename: str = "image.jpg",
    caption: str = "",
    session: str = "default",
) -> tuple[bool, str | None]:
    """Envia imagem via WAHA (POST /api/sendImage)."""
    return _enviar_midia(remote_id, file_base64, mimetype, filename, caption, session, "/api/sendImage")


def enviar_documento(
    remote_id: str,
    file_base64: str,
    mimetype: str = "application/octet-stream",
    filename: str = "documento",
    caption: str = "",
    session: str = "default",
) -> tuple[bool, str | None]:
    """Envia documento/arquivo via WAHA (POST /api/sendFile)."""
    return _enviar_midia(remote_id, file_base64, mimetype, filename, caption, session, "/api/sendFile")


def enviar_audio(
    remote_id: str,
    file_base64: str,
    mimetype: str = "audio/ogg; codecs=opus",
    filename: str = "audio.ogg",
    caption: str = "",
    session: str = "default",
    convert: bool = True,
) -> tuple[bool, str | None]:
    """
    Envia mensagem de voz/áudio via WAHA (POST /api/sendVoice).
    WhatsApp aceita OPUS em OGG; use convert=True para WAHA converter outros formatos (ex.: webm).
    """
    _ensure_configured()
    chat_id, _ = _normalize_chat_id(remote_id)
    if not chat_id:
        return (False, "Número de destino inválido.")
    payload: dict[str, Any] = {
        "session": session,
        "chatId": chat_id,
        "file": {
            "mimetype": (mimetype or "audio/ogg; codecs=opus").strip(),
            "filename": (filename or "audio.ogg").strip() or "audio.ogg",
            "data": file_base64.strip(),
        },
        "convert": bool(convert),
    }
    if caption:
        payload["caption"] = caption.strip()
    url = f"{settings.WAHA_URL}/api/sendVoice"
    headers = {"Content-Type": "application/json", **_headers(accept=None)}
    try:
        response = requests.post(url, json=payload, headers=headers, timeout=60)
        if response.status_code in (200, 201):
            import logging
            logging.getLogger(__name__).info("WAHA sendVoice OK chatId=%s", chat_id)
            return (True, None)
        body = response.text
        try:
            j = response.json()
            body = j.get("message", j.get("error", body))
        except Exception:
            pass
        err_msg = _mensagem_erro_amigavel(response.status_code, body)
        import logging
        logging.getLogger(__name__).warning("WAHA sendVoice falhou: %s", err_msg)
        return (False, err_msg)
    except requests.exceptions.RequestException as e:
        return (False, f"Erro de conexão WAHA: {e}")


def get_chats_overview(session: str = "default", limit: int = 100, offset: int = 0) -> list[dict[str, Any]]:
    """
    GET /api/{session}/chats/overview - nome e foto de cada chat para exibir no painel.
    Retorna lista de { "id": "123@c.us", "name": "...", "picture": "url ou null", ... }.
    """
    _ensure_configured()
    s = (session or "default").strip()
    url = f"{settings.WAHA_URL}/api/{s}/chats/overview"
    params = {"limit": limit, "offset": offset}
    r = requests.get(url, headers=_headers(), params=params, timeout=30)
    r.raise_for_status()
    data = r.json()
    return data if isinstance(data, list) else []


def mark_chat_messages_read(session: str, chat_id: str) -> bool:
    """
    POST /api/{session}/chats/{chatId}/messages/read - marca mensagens do chat como lidas (ticks azuis).
    chat_id: JID completo (ex.: 5511999999999@c.us ou 123456@lid). O @ será codificado na URL.
    """
    _ensure_configured()
    s = (session or "default").strip()
    from urllib.parse import quote
    safe_chat_id = quote(chat_id, safe="")
    url = f"{settings.WAHA_URL}/api/{s}/chats/{safe_chat_id}/messages/read"
    r = requests.post(url, json={}, headers={"Content-Type": "application/json", **_headers()}, timeout=15)
    if r.status_code in (200, 201, 204):
        return True
    return False


def list_sessions(all_sessions: bool = True) -> list[dict[str, Any]]:
    _ensure_configured()
    url = f"{settings.WAHA_URL}/api/sessions"
    params = {"all": "true"} if all_sessions else None
    r = requests.get(url, headers=_headers(), params=params, timeout=20)
    r.raise_for_status()
    data = r.json()
    return data if isinstance(data, list) else []


def get_session(name: str) -> dict[str, Any]:
    _ensure_configured()
    s = (name or "").strip()
    url = f"{settings.WAHA_URL}/api/sessions/{s}"
    r = requests.get(url, headers=_headers(), timeout=20)
    r.raise_for_status()
    data = r.json()
    return data if isinstance(data, dict) else {}


def create_session(name: str, *, tenant_id: Any, start: bool = True) -> dict[str, Any]:
    _ensure_configured()
    url = f"{settings.WAHA_URL}/api/sessions"
    hooks = _build_webhook_config(name)
    payload: dict[str, Any] = {"name": name, "config": {"webhooks": hooks} if hooks else {}}
    if start is False:
        payload["start"] = False
    r = requests.post(url, json=payload, headers={"Content-Type": "application/json", **_headers()}, timeout=30)
    r.raise_for_status()
    try:
        data = r.json()
        return data if isinstance(data, dict) else {}
    except ValueError:
        # Algumas versões do WAHA retornam 201/204 sem corpo; nesse caso só sinalizamos sucesso vazio
        return {}


def _session_has_expected_hooks(sess: dict[str, Any], session_name: str) -> bool:
    cfg = sess.get("config") if isinstance(sess, dict) else None
    if not isinstance(cfg, dict):
        return False
    hooks = cfg.get("webhooks")
    if not isinstance(hooks, list) or not hooks:
        return False
    want_url = _waha_webhook_url()
    if not want_url:
        return True
    for h in hooks:
        if not isinstance(h, dict):
            continue
        if (h.get("url") or "").strip() != want_url:
            continue
        events = h.get("events") or []
        if isinstance(events, list) and "message" in events and "session.status" in events:
            return True
    return False


def _update_session_webhooks(session_name: str) -> None:
    hooks = _build_webhook_config(session_name)
    if not hooks:
        return
    url = f"{settings.WAHA_URL}/api/sessions/{session_name}"
    payload = {"name": session_name, "config": {"webhooks": hooks}}
    headers = {"Content-Type": "application/json", **_headers()}
    # Compatibilidade entre versões
    r = requests.put(url, json=payload, headers=headers, timeout=30)
    if r.status_code == 405:
        r = requests.post(url, json=payload, headers=headers, timeout=30)
    r.raise_for_status()


def restart_session(name: str) -> dict[str, Any]:
    _ensure_configured()
    s = (name or "").strip()
    url = f"{settings.WAHA_URL}/api/sessions/{s}/restart"
    try:
        r = requests.post(url, headers=_headers(), timeout=30)
        r.raise_for_status()
        data = r.json()
        return data if isinstance(data, dict) else {}
    except requests.exceptions.HTTPError as e:
        if e.response is not None and e.response.status_code == 502:
            raise RuntimeError(
                "O servidor WAHA respondeu 502 (Bad Gateway). "
                "Geralmente o processo do WAHA está parado ou indisponível. "
                "Verifique se o WAHA está rodando, se a WAHA_URL no .env está correta e se nenhum proxy está retornando 502."
            ) from e
        raise
    except requests.exceptions.ConnectionError as e:
        raise RuntimeError(
            "Não foi possível conectar ao WAHA. Verifique se o WAHA está rodando e se WAHA_URL no .env está acessível a partir deste servidor."
        ) from e
    except requests.exceptions.Timeout as e:
        raise RuntimeError("O WAHA demorou para responder (timeout). Tente novamente em alguns segundos.") from e


def start_session(name: str) -> dict[str, Any]:
    _ensure_configured()
    s = (name or "").strip()
    url = f"{settings.WAHA_URL}/api/sessions/{s}/start"
    r = requests.post(url, headers=_headers(), timeout=30)
    r.raise_for_status()
    data = r.json()
    return data if isinstance(data, dict) else {}


def logout_session(name: str) -> dict[str, Any]:
    _ensure_configured()
    s = (name or "").strip()
    url = f"{settings.WAHA_URL}/api/sessions/{s}/logout"
    r = requests.post(url, headers=_headers(), timeout=30)
    r.raise_for_status()
    data = r.json()
    return data if isinstance(data, dict) else {}


def get_qr_base64(name: str) -> dict[str, Any]:
    """
    Retorna { mimetype, data } (base64) do QR.
    Endpoint: GET /api/{session}/auth/qr?format=image, Accept: application/json
    """
    _ensure_configured()
    s = (name or "").strip()
    url = f"{settings.WAHA_URL}/api/{s}/auth/qr"
    r = requests.get(url, headers=_headers(accept="application/json"), params={"format": "image"}, timeout=20)
    r.raise_for_status()
    data = r.json()
    return data if isinstance(data, dict) else {}


def ensure_default_session() -> dict[str, Any]:
    """
    Garante que a sessão 'default' exista e esteja iniciada.
    (WAHA Core suporta apenas 'default'.)
    """
    _ensure_configured()
    url = f"{settings.WAHA_URL}/api/sessions/default"
    r = requests.get(url, headers=_headers(), timeout=20)
    if r.status_code == 404 or r.status_code == 204:
        # cria 'default'
        create_session("default", tenant_id="core", start=True)
        r = requests.get(url, headers=_headers(), timeout=20)
    r.raise_for_status()
    try:
        sess = r.json() if r.content else {}
    except ValueError:
        sess = {}
    if isinstance(sess, dict) and sess.get("status") == "STOPPED":
        try:
            start_session("default")
            r2 = requests.get(url, headers=_headers(), timeout=20)
            if r2.ok:
                try:
                    sess = r2.json() if r2.content else {}
                except ValueError:
                    pass
        except Exception:
            pass
    return sess if isinstance(sess, dict) else {}


def ensure_session(name: str, *, tenant_id: Any) -> dict[str, Any]:
    """Garante existência da sessão por nome e tenta manter webhooks por sessão."""
    _ensure_configured()
    s = (name or "").strip()
    if not s:
        raise RuntimeError("Nome de sessão WAHA inválido.")
    url = f"{settings.WAHA_URL}/api/sessions/{s}"
    r = requests.get(url, headers=_headers(), timeout=20)
    if r.status_code in (404, 204):
        create_session(s, tenant_id=tenant_id, start=True)
        r = requests.get(url, headers=_headers(), timeout=20)
    r.raise_for_status()
    try:
        sess = r.json() if r.content else {}
    except ValueError:
        sess = {}
    if isinstance(sess, dict) and not _session_has_expected_hooks(sess, s):
        try:
            _update_session_webhooks(s)
            sess = get_session(s)
        except Exception:
            pass
    if isinstance(sess, dict) and sess.get("status") == "STOPPED":
        try:
            start_session(s)
            r2 = requests.get(url, headers=_headers(), timeout=20)
            if r2.ok:
                try:
                    sess = r2.json() if r2.content else {}
                except ValueError:
                    pass
        except Exception:
            pass
    return sess if isinstance(sess, dict) else {}


def recover_session(name: str) -> dict[str, Any]:
    """
    Recupera sessão em estado FAILED conforme recomendação:
    restart -> se continuar ruim, logout + start.
    """
    s = (name or "").strip()
    if not s:
        raise RuntimeError("Nome de sessão WAHA inválido.")
    try:
        restart_session(s)
    except Exception:
        pass
    try:
        sess = get_session(s)
    except Exception:
        sess = {}
    status = (sess.get("status") or "").strip().upper() if isinstance(sess, dict) else ""
    if status == "FAILED":
        try:
            logout_session(s)
        except Exception:
            pass
        try:
            start_session(s)
        except Exception:
            pass
        try:
            sess = get_session(s)
        except Exception:
            sess = {}
    return sess if isinstance(sess, dict) else {}
