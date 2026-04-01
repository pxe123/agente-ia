# webhooks/waha_webhook.py
"""
Webhook para receber eventos do WAHA (mensagens WhatsApp).
Configure no WAHA a URL: https://api.updigitalbrasil.com.br/webhook/waha
Eventos sugeridos: message (ou message.any, mas não ambos para evitar duplicatas).
Deduplicação: por payload.id e por (sessão, remetente, texto) para nunca enviar 2 respostas ao WhatsApp.
"""
from flask import Blueprint, request, jsonify, current_app
import hashlib
import hmac
import os
import threading
import time
from collections import OrderedDict
from typing import Any

from database.supabase_sq import supabase
from database.models import Tables, ClienteModel
from base.config import settings
from services.message_service import MessageService
from services.sent_message_cache import foi_envio_recente

waha_webhook_bp = Blueprint("waha_webhook", __name__)

# Deduplicação: IDs de mensagens já processadas (evita duplicata quando WAHA envia message + message.any).
_MAX_RECENT_IDS = 2000
_recent_message_ids = OrderedDict()

# Deduplicação por conteúdo: mesma mensagem recebida (sessão, remetente, texto) em poucos segundos = só processar uma vez (evita 2 envios ao WhatsApp).
_recent_incoming = OrderedDict()  # (session, remote_normalized, text_preview) -> timestamp
_RECENT_INCOMING_TTL = 25
_MAX_RECENT_INCOMING = 1000


def _waha_hmac_key() -> str:
    v = (os.getenv("WAHA_WEBHOOK_HMAC_KEY") or "").strip()
    if v:
        return v
    return (getattr(settings, "SECRET_KEY", None) or "").strip()


def _is_valid_webhook_hmac() -> bool:
    key = _waha_hmac_key()
    if not key:
        return True
    provided = (request.headers.get("X-Webhook-Hmac") or "").strip().lower()
    if not provided:
        return False
    body = request.get_data(cache=True) or b""
    expected = hmac.new(key.encode("utf-8"), body, hashlib.sha512).hexdigest().lower()
    return hmac.compare_digest(expected, provided)


def _dbg(event: str, hypothesisId: str, data: dict) -> None:
    # #region agent log
    try:
        import json
        import time as _t
        payload = {
            "sessionId": "3bd729",
            "runId": "pre-fix",
            "hypothesisId": hypothesisId,
            "location": "webhooks/waha_webhook.py",
            "message": event,
            "data": data,
            "timestamp": int(_t.time() * 1000),
        }
        # Em produção (systemd), o arquivo pode não estar no cwd esperado.
        # Então também emitimos no stdout para capturar via journalctl.
        try:
            print("[DBG3bd729] " + json.dumps(payload, ensure_ascii=False), flush=True)
        except Exception:
            pass
        with open("debug-3bd729.log", "a", encoding="utf-8") as f:
            f.write(json.dumps(payload, ensure_ascii=False) + "\n")
    except Exception:
        pass
    # #endregion


def _normalizar_remote_para_dedup(remote_id: str) -> str:
    s = (remote_id or "").strip()
    if "@" in s:
        s = s.split("@")[0].strip()
    return s or remote_id or ""


def _ja_processado_incoming(session: str, remote_id: str, texto: str, meta: str | None = None) -> bool:
    """True se já processamos esta mensagem recebida recentemente (evita enviar 2 respostas ao cliente)."""
    key = (session.strip(), _normalizar_remote_para_dedup(remote_id), (texto or "").strip()[:300])
    if meta is not None:
        key = (*key, (meta or "").strip()[:120])
    now = time.time()
    # Limpar entradas antigas
    to_del = [k for k, ts in _recent_incoming.items() if now - ts > _RECENT_INCOMING_TTL]
    for k in to_del:
        _recent_incoming.pop(k, None)
    if key in _recent_incoming:
        return True
    _recent_incoming[key] = now
    while len(_recent_incoming) > _MAX_RECENT_INCOMING:
        _recent_incoming.popitem(last=False)
    return False


def _ja_processado(message_id: str) -> bool:
    """True se esta mensagem já foi processada (evita duplicata no chat)."""
    if not (message_id or str(message_id).strip()):
        return False
    key = str(message_id).strip()
    if key in _recent_message_ids:
        return True
    _recent_message_ids[key] = True
    while len(_recent_message_ids) > _MAX_RECENT_IDS:
        _recent_message_ids.popitem(last=False)
    return False


def _extrair_texto(payload: dict) -> str:
    """Extrai o texto da mensagem do payload WAHA (message event).
    Inclui body, link/url e também respostas de botões/listas (campos variam por engine).
    """
    if not payload:
        return ""

    def _pick_str(obj, *keys) -> str:
        if not isinstance(obj, dict):
            return ""
        for k in keys:
            v = obj.get(k)
            if isinstance(v, str) and v.strip():
                return v.strip()
        return ""

    def _deep_pick_str(obj, keys_set: set[str], max_depth: int = 6) -> str:
        """Procura por chaves em dict/list aninhados (varia por engine do WAHA)."""
        if max_depth < 0 or obj is None:
            return ""
        if isinstance(obj, dict):
            for k, v in obj.items():
                if k in keys_set and isinstance(v, str) and v.strip():
                    return v.strip()
            for v in obj.values():
                found = _deep_pick_str(v, keys_set, max_depth - 1)
                if found:
                    return found
        elif isinstance(obj, list):
            for item in obj:
                found = _deep_pick_str(item, keys_set, max_depth - 1)
                if found:
                    return found
        return ""

    # 0) Respostas de botões/listas no nível raiz (alguns engines expõem assim).
    # Preferir texto/título; fallback para id (muitas vezes é "1/2/3", que também funciona no fluxo).
    direct_button_text = _pick_str(payload, "selectedButtonText", "buttonText", "title")
    if direct_button_text:
        return direct_button_text
    direct_button_id = _pick_str(payload, "selectedButtonId", "buttonId")
    if direct_button_id:
        return direct_button_id

    # 1) Texto comum (mensagem digitada).
    text = (
        payload.get("body")
        or payload.get("text")
        or payload.get("content")
        or payload.get("caption")  # legenda de mídia
        or ""
    )
    # Mensagem com link compartilhado: alguns engines colocam a URL em link/url
    if not text:
        text = payload.get("link") or payload.get("url") or ""
    if text:
        return str(text).strip()

    # 2) Campos internos (_data) variam por engine (inclui respostas de botão/lista).
    _data = payload.get("_data") or {}
    if isinstance(_data, dict):
        nested_button_text = _deep_pick_str(
            _data,
            {
                "selectedButtonText",
                "buttonText",
                "title",
                "displayText",
                "selectedDisplayText",
            },
            max_depth=7,
        )
        if nested_button_text:
            return nested_button_text
        nested_button_id = _deep_pick_str(
            _data,
            {
                "selectedButtonId",
                "buttonId",
                "selectedRowId",
                "rowId",
            },
            max_depth=7,
        )
        if nested_button_id:
            return nested_button_id

        text = (
            _data.get("body")
            or _data.get("text")
            or _data.get("content")
            or _data.get("caption")
            or _data.get("link")
            or _data.get("url")
            or ""
        )
    return str(text).strip() if text else ""


@waha_webhook_bp.route("/waha", methods=["POST"])
def webhook_entrada():
    """
    Recebe eventos do WAHA (message = recebidas; message.any = qualquer, incl. enviadas pelo Web/app).
    Payload: { "event": "message" ou "message.any", "session": "default", "payload": { "from", "to", "fromMe", "body", ... } }
    """
    if not _is_valid_webhook_hmac():
        current_app.logger.warning("waha_webhook: assinatura HMAC inválida")
        return jsonify({"status": "erro", "motivo": "assinatura inválida"}), 401

    data = request.json or {}
    event = (data.get("event") or "").strip().lower()
    # Debug: confira nos logs se o WAHA está chamando o webhook ao enviar pelo WhatsApp Web
    if not data:
        print("📩 WAHA webhook: POST sem JSON (body vazio ou inválido)", flush=True)
    # WAHA pode enviar `session` no payload, mas em alguns cenários vem vazio.
    # Como também configuramos `X-WAHA-Session` no WAHA, fazemos fallback via header.
    session_name_payload = (data.get("session") or "").strip()
    header_session = (request.headers.get("X-WAHA-Session") or request.headers.get("x-waha-session") or "").strip()
    session_name = session_name_payload or header_session or "default"
    payload = data.get("payload") or {}
    _dbg(
        "waha_webhook_received",
        "H1",
        {
            "event": event,
            "session": (session_name or "")[:24],
            "session_source": "payload" if session_name_payload else ("header" if header_session else "default"),
            "payload_keys": list(payload.keys())[:20] if isinstance(payload, dict) else "not_dict",
        },
    )

    # message = mensagens recebidas; message.any = qualquer mensagem (incl. enviadas por nós no Web/app)
    if event not in ("message", "message.any"):
        return jsonify({"status": "ignorado", "event": event}), 200

    # Identificar remetente/destinatário: quando fromMe=True é mensagem enviada por nós (ex.: app WhatsApp oficial)
    from_me = payload.get("fromMe") is True
    if from_me:
        # Mensagem enviada pelo negócio: destinatário em "to" (chat 1:1) ou "from" (conversa)
        remote_id = (payload.get("to") or payload.get("from") or "").strip()
    else:
        remote_id = (payload.get("from") or "").strip()

    if not remote_id:
        _dbg("waha_webhook_drop_no_remote", "H1", {"event": event, "fromMe": bool(from_me)})
        return jsonify({"status": "erro", "motivo": "from/to vazio"}), 200

    # Deduplicação por id só para mensagens RECEBIDAS (from_me=false). Assim nunca ignoramos um "oi" do cliente por ter visto antes o id do eco da nossa resposta.
    _data = payload.get("_data")
    message_id = payload.get("id") or payload.get("messageId") or (_data.get("id") if isinstance(_data, dict) else None)
    remote_last4 = "".join([c for c in str(remote_id) if c.isdigit()])[-4:] if remote_id else ""
    mid_short = (str(message_id)[-24:] if message_id else "")
    _dbg(
        "waha_webhook_identified",
        "H1",
        {"event": event, "fromMe": bool(from_me), "remoteLast4": remote_last4, "messageIdTail": mid_short},
    )
    if not from_me and message_id and _ja_processado(str(message_id)):
        _dbg("waha_webhook_dedup_by_id", "H2", {"messageIdTail": mid_short, "remoteLast4": remote_last4})
        print(f"📩 WAHA webhook: mensagem recebida já processada (id={message_id}), ignorando duplicata.", flush=True)
        return jsonify({"status": "ok", "deduplicado": True}), 200

    # Preserva o JID completo (ex.: 5511999999999@c.us ou 30172715724804@lid) para poder responder pelo WAHA.
    if "@" not in remote_id:
        remote_id = "".join(c for c in remote_id if c.isdigit()) or remote_id

    # Log visível: confira nos logs do servidor se o webhook recebe mensagens do WhatsApp Web
    print(f"📩 WAHA webhook: event={event} fromMe={from_me} from={payload.get('from')} to={payload.get('to')} -> remote_id={remote_id}", flush=True)
    current_app.logger.info("waha_webhook: fromMe=%s from=%s to=%s -> remote_id=%s", from_me, payload.get("from"), payload.get("to"), remote_id)

    texto = _extrair_texto(payload)
    texto_norm = (texto or "").strip().lower()
    _dbg(
        "waha_webhook_extracted_text",
        "H3",
        {
            "remoteLast4": remote_last4,
            "textoLen": len(texto or ""),
            "textoIsChoice": texto_norm in ("1", "2", "3", "sim", "não", "nao"),
            "fromMe": bool(from_me),
            "event": event,
        },
    )
    push_name = (payload.get("notifyName") or payload.get("pushName") or payload.get("senderName") or "").strip()

    # WAHA Core: buscar cliente pela sessão
    try:
        res = supabase.table(Tables.CLIENTES).select("id").eq(ClienteModel.WHATSAPP_INSTANCIA, session_name).limit(1).execute()
        if res.data and len(res.data) > 0:
            cliente_id = res.data[0]["id"]
        else:
            res2 = supabase.table(Tables.CLIENTES).select("id").limit(1).execute()
            if not res2.data or len(res2.data) == 0:
                return jsonify({"status": "ignorado", "motivo": "nenhum cliente"}), 200
            cliente_id = res2.data[0]["id"]
    except Exception as e:
        current_app.logger.warning("waha_webhook: erro ao buscar cliente: %s", e)
        return jsonify({"status": "erro"}), 200

    anexo_url = None
    anexo_nome = None
    anexo_tipo = None
    payload_has_media = bool(payload.get("hasMedia"))
    if payload_has_media and payload.get("media"):
        media = payload.get("media") or {}
        media_url = (media.get("url") or "").strip()
        if media_url and not media.get("error"):
            from base.config import settings
            from services.anexo_service import download_and_save_anexo, nome_original_anexo
            api_key = (getattr(settings, "WAHA_API_KEY", None) or "").strip()
            anexo_url = download_and_save_anexo(
                media_url,
                str(cliente_id),
                mimetype=media.get("mimetype") or "",
                filename=media.get("filename") or "",
                api_key_header=api_key if api_key else None,
            )
            if anexo_url:
                anexo_nome = nome_original_anexo(media.get("filename") or "", media.get("mimetype") or "")
                anexo_tipo = (media.get("mimetype") or "").strip() or "application/octet-stream"
                if not texto:
                    if (anexo_tipo or "").startswith("image/"):
                        texto = "[imagem enviada]"
                    elif (anexo_tipo or "").startswith("audio/"):
                        texto = "[áudio enviado]"
                    else:
                        texto = "[arquivo enviado]"
        # Fallback: quando o WAHA sinaliza mídia, mas não há URL válida (ou veio com erro),
        # registramos placeholder para não "sumir" no chat.
        if not texto and not anexo_url:
            mime_hint = (media.get("mimetype") or "").strip().lower()
            if mime_hint.startswith("image/"):
                texto = "[imagem enviada]"
            elif mime_hint.startswith("audio/"):
                texto = "[áudio enviado]"
            else:
                texto = "[arquivo enviado]"
            _dbg(
                "waha_webhook_media_placeholder_fallback",
                "H3",
                {
                    "remoteLast4": remote_last4,
                    "hasMedia": True,
                    "mediaUrl": bool(media_url),
                    "mediaError": bool(media.get("error")),
                    "textoLen": len(texto or ""),
                },
            )
    elif payload_has_media and not texto:
        # Alguns payloads chegam com hasMedia=true sem bloco media.
        texto = "[arquivo enviado]"
        _dbg(
            "waha_webhook_media_missing_block",
            "H3",
            {"remoteLast4": remote_last4, "hasMedia": True, "textoLen": len(texto or "")},
        )

    socketio_instancia = current_app.extensions.get("socketio")
    app_obj = current_app._get_current_object()

    if from_me:
        # Mensagem enviada por nós (WhatsApp Web, app ou painel): registrar no histórico e notificar painel
        if not texto and not anexo_url:
            print(f"📩 WAHA webhook: fromMe=true mas sem texto nem mídia (payload keys: {list(payload.keys())})", flush=True)
            return jsonify({"status": "ignorado", "motivo": "fromMe sem conteúdo"}), 200

        # Eco da nossa própria resposta (enviada pela IA via API): já salvamos e emitimos no MessageService; não duplicar.
        # Também evitamos processar duplicatas reais do WAHA quando o message_id vem no payload.
        if message_id and _ja_processado(str(message_id)):
            _dbg("waha_webhook_dedup_by_id_fromme", "H4", {"remoteLast4": remote_last4, "messageIdTail": mid_short})
            return jsonify({"status": "ok", "deduplicado": True}), 200
        if foi_envio_recente(cliente_id, remote_id, texto or ""):
            _dbg("waha_webhook_ignored_echo", "H4", {"remoteLast4": remote_last4, "textoLen": len(texto or "")})
            print(f"📩 WAHA webhook: fromMe=true é eco da nossa resposta (cliente_id={cliente_id} remote_id={remote_id}), ignorando duplicata.", flush=True)
            return jsonify({"status": "ok", "eco_ignorado": True}), 200
        _dbg("waha_webhook_registering_fromme", "H4", {"remoteLast4": remote_last4, "textoLen": len(texto or "")})

        print(f"✅ WAHA: registrando mensagem enviada por nós -> remote_id={remote_id} cliente_id={cliente_id} texto_len={len(texto or '')}", flush=True)
        def _registrar_saida():
            with app_obj.app_context():
                MessageService.registrar_mensagem_saida(
                    cliente_id, remote_id, "whatsapp", texto or "[mídia]", socketio_instancia,
                    anexo_url=anexo_url, anexo_nome=anexo_nome, anexo_tipo=anexo_tipo,
                )

        threading.Thread(target=_registrar_saida, daemon=True).start()
        return jsonify({"status": "ok", "tipo": "mensagem_saida"}), 200

    # Mensagem sem conteúdo real (ex.: atualização de perfil ao abrir chat): não salvar nem acionar a IA
    if not texto and not anexo_url:
        _dbg("waha_webhook_drop_empty", "H3", {"remoteLast4": remote_last4, "event": event})
        print(f"📩 WAHA webhook: ignorando mensagem sem texto nem mídia (from={remote_id}) – evita [mídia] fantasma no chat", flush=True)
        return jsonify({"status": "ignorado", "motivo": "sem texto nem mídia"}), 200

    # Evitar processar a mesma mensagem recebida duas vezes.
    # IMPORTANTE: se temos message_id, a dedup por ID é suficiente. A dedup por conteúdo por 25s pode
    # causar o sintoma de "precisei mandar 1 várias vezes" quando o usuário repete a mesma resposta.
    if not message_id:
        if _ja_processado_incoming(session_name, remote_id, texto or ""):
            _dbg("waha_webhook_dedup_by_content", "H2", {"remoteLast4": remote_last4, "textoLen": len(texto or "")})
            print(f"📩 WAHA webhook: mensagem recebida já processada (conteúdo recente), ignorando para não duplicar envio.", flush=True)
            return jsonify({"status": "ok", "deduplicado_conteudo": True}), 200

    # Meta adicional para o Flow Builder (ex.: confirmar clique em links enviados pelo bot).
    # Importante: o WAHA frequentemente retorna "texto" como "1/2/3" (ou id de botão), então precisamos
    # de um critério extra baseado em payload (ex.: url/link presente no evento).
    def _deep_find_first_string(obj: Any, keys_set: set[str], max_depth: int = 7) -> str:
        if max_depth < 0 or obj is None:
            return ""
        if isinstance(obj, dict):
            for k, v in obj.items():
                if k in keys_set and isinstance(v, str) and v.strip():
                    return v.strip()
            for v in obj.values():
                found = _deep_find_first_string(v, keys_set, max_depth - 1)
                if found:
                    return found
        elif isinstance(obj, list):
            for item in obj:
                found = _deep_find_first_string(item, keys_set, max_depth - 1)
                if found:
                    return found
        return ""

    def _deep_has_any_key(obj: Any, keys_set: set[str], max_depth: int = 7) -> bool:
        if max_depth < 0 or obj is None:
            return False
        if isinstance(obj, dict):
            for k, v in obj.items():
                if k in keys_set and isinstance(v, (str, int, float)) and str(v).strip():
                    return True
            for v in obj.values():
                if _deep_has_any_key(v, keys_set, max_depth - 1):
                    return True
        elif isinstance(obj, list):
            for item in obj:
                if _deep_has_any_key(item, keys_set, max_depth - 1):
                    return True
        return False

    clicked_url = _deep_find_first_string(payload, {"url", "link"}, max_depth=7)
    is_interactive_selection = _deep_has_any_key(
        payload,
        {"selectedButtonId", "buttonId", "selectedRowId", "rowId", "selectedButtonText", "buttonText", "title", "displayText", "selectedDisplayText"},
        max_depth=7,
    )

    # Deduplicação extra para cliques interativos de botões.
    # Alguns engines do WAHA/WhatsApp podem disparar múltiplos eventos para o mesmo clique
    # com `message_id` diferente. Nesse caso, deduplicamos por metadados do botão.
    if is_interactive_selection:
        _btn_id = _deep_find_first_string(
            payload,
            {"selectedButtonId", "buttonId", "selectedRowId", "rowId"},
            max_depth=7,
        )
        _btn_text = _deep_find_first_string(
            payload,
            {"selectedButtonText", "buttonText", "title", "displayText", "selectedDisplayText"},
            max_depth=7,
        )
        _interactive_meta = (_btn_id or _btn_text or "").strip() or None
        if _interactive_meta and _ja_processado_incoming(session_name, remote_id, texto or "", meta=_interactive_meta):
            _dbg(
                "waha_webhook_dedup_interactive_meta",
                "H2",
                {"remoteLast4": remote_last4, "texto": (texto or "").strip()[:10], "metaLen": len(_interactive_meta)},
            )
            print(f"📩 WAHA webhook: mensagem interativa duplicada (meta={_interactive_meta[:30]!r}), ignorando.", flush=True)
            return jsonify({"status": "ok", "deduplicado_interativo": True}), 200
    message_meta = None
    if clicked_url or is_interactive_selection:
        message_meta = {
            "clicked_url": clicked_url or None,
            "is_interactive_selection": bool(is_interactive_selection),
        }

    def _processar_com_contexto():
        try:
            with app_obj.app_context():
                _dbg("waha_webhook_call_message_service", "H5", {"remoteLast4": remote_last4, "textoLen": len(texto or "")})
                MessageService.processar_mensagem_entrada(
                    "whatsapp", remote_id, texto or "[mídia]", cliente_id, session_name, socketio_instancia,
                    push_name=push_name or None,
                    anexo_url=anexo_url,
                    anexo_nome=anexo_nome,
                    anexo_tipo=anexo_tipo,
                    message_meta=message_meta,
                )
        except Exception as e:
            import traceback
            print(f"❌ WAHA webhook: erro ao processar mensagem entrada (remote_id={remote_id}): {e}", flush=True)
            traceback.print_exc()

    threading.Thread(target=_processar_com_contexto, daemon=True).start()

    return jsonify({"status": "ok"}), 200
