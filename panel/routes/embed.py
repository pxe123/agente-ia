# panel/routes/embed.py
"""
Rotas para o chat embed (widget instalável no site do cliente).
- GET /api/embed/key: retorna ou gera a chave de embed do cliente logado.
- POST /api/embed/rotate-key: substitui embed_key (autenticado; invalida snippet antigo no site).
- POST /api/embed/send: envia mensagem do painel para um visitante (session_id).
- POST /api/embed/message: widget envia mensagem (sem Socket.IO). Autenticação: header X-Embed-Key e/ou body.key.
- GET /api/embed/poll: widget busca respostas. Autenticação: header X-Embed-Key e/ou query key.
- POST /api/embed/media: multipart. Autenticação: header X-Embed-Key e/ou form key.

Respostas do chatbot para o canal website são persistidas em historico_mensagens; o poll lê do banco
em vez de fila em memória, garantindo entrega persistente.
"""
import threading
import json
import os
import time
from datetime import datetime, timezone
from flask import Blueprint, request, jsonify, current_app
from flask_login import login_required, current_user
from base.auth import get_current_cliente_id

from database.supabase_sq import supabase
from database.models import Tables, ClienteModel, MensagemModel
from database.embed_key import gerar_embed_key

embed_bp = Blueprint("embed", __name__)
_debug_log_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "debug-1db042.log"))

# Header suportado em CORS + widget (além de body/query `key` por compatibilidade).
_EMBED_KEY_HEADER = "X-Embed-Key"


def _embed_key_from_widget_request() -> str:
    """Prioridade: header X-Embed-Key, depois JSON body key, form key, query key."""
    h = (request.headers.get(_EMBED_KEY_HEADER) or "").strip()
    if h:
        return h
    body = request.get_json(silent=True)
    if isinstance(body, dict):
        k = (body.get("key") or "").strip()
        if k:
            return k
    fk = (request.form.get("key") or "").strip()
    if fk:
        return fk
    return (request.args.get("key") or "").strip()


def _cliente_id_from_embed_key(embed_key: str):
    """
    Valida embed_key na tabela clientes. Retorna id do cliente ou None se inválido.
    """
    if not embed_key or supabase is None:
        return None
    r = (
        supabase.table(Tables.CLIENTES)
        .select(ClienteModel.ID)
        .eq(ClienteModel.EMBED_KEY, embed_key)
        .limit(1)
        .execute()
    )
    if not r.data:
        return None
    return r.data[0]["id"]


@embed_bp.before_request
def _embed_cors_preflight():
    """CORS preflight para widget em domínio público (ex.: zapaction.com.br) chamando API em outro host."""
    if request.method != "OPTIONS":
        return None
    p = request.path or ""
    if not p.startswith("/api/embed/"):
        return None
    from flask import Response

    r = Response(status=204)
    r.headers["Access-Control-Allow-Origin"] = "*"
    r.headers["Access-Control-Allow-Methods"] = "GET, POST, OPTIONS"
    r.headers["Access-Control-Allow-Headers"] = "Content-Type, X-Embed-Key"
    r.headers["Access-Control-Max-Age"] = "86400"
    return r


@embed_bp.after_request
def _embed_cors_headers(resp):
    p = request.path or ""
    if p.startswith("/api/embed/"):
        resp.headers["Access-Control-Allow-Origin"] = "*"
    return resp

# Último created_at por room (website:cliente_id:session_id) para retornar só mensagens novas no poll
_embed_last_poll_at = {}


@embed_bp.route("/api/embed/key", methods=["GET"])
@login_required
def get_or_create_embed_key():
    """Retorna a chave de embed do cliente. Cria uma nova se não existir."""
    if getattr(current_user, "acesso_site", True) is False:
        return jsonify({"status": "erro", "mensagem": "Acesso ao chat para site não permitido."}), 403
    try:
        cid = get_current_cliente_id(current_user)
        r = supabase.table(Tables.CLIENTES).select(ClienteModel.WEBSITE_CHAT_EMBED_KEY).eq("id", cid).execute()
        if not r.data:
            return jsonify({"status": "erro", "mensagem": "Cliente não encontrado"}), 404
        key = (r.data[0] or {}).get(ClienteModel.WEBSITE_CHAT_EMBED_KEY)
        if not key:
            key = gerar_embed_key()
            supabase.table(Tables.CLIENTES).update({ClienteModel.WEBSITE_CHAT_EMBED_KEY: key}).eq("id", cid).execute()
        return jsonify({"status": "sucesso", "key": key})
    except Exception as e:
        current_app.logger.exception("embed get_or_create_embed_key")
        return jsonify({"status": "erro", "mensagem": str(e)}), 500


@embed_bp.route("/api/embed/rotate-key", methods=["POST"])
@login_required
def rotate_embed_key():
    """
    Gera nova embed_key, grava em clientes e invalida a chave anterior (widgets com snippet antigo deixam de autenticar).
    Exige sessão do painel + CSRF (mesmas regras das demais rotas /api/*).
    """
    if supabase is None:
        return jsonify({"status": "erro", "mensagem": "Serviço indisponível."}), 503
    if getattr(current_user, "acesso_site", True) is False:
        return jsonify({"status": "erro", "mensagem": "Acesso ao chat para site não permitido."}), 403
    cid = get_current_cliente_id(current_user)
    if not cid:
        return jsonify({"status": "erro", "mensagem": "Cliente não identificado."}), 401
    new_key = gerar_embed_key()
    try:
        supabase.table(Tables.CLIENTES).update({ClienteModel.EMBED_KEY: new_key}).eq(ClienteModel.ID, cid).execute()
        current_app.logger.info("embed rotate-key: cliente_id=%s", cid)
        return jsonify({"status": "sucesso", "key": new_key}), 200
    except Exception as e:
        current_app.logger.exception("embed rotate_embed_key")
        return jsonify({"status": "erro", "mensagem": str(e)}), 500


@embed_bp.route("/api/embed/send", methods=["POST"])
@login_required
def send_to_visitor():
    """Envia mensagem do painel para um visitante do site (canal website)."""
    if getattr(current_user, "acesso_site", True) is False:
        return jsonify({"status": "erro", "mensagem": "Acesso ao chat para site não permitido."}), 403
    data = request.json or {}
    session_id = (data.get("session_id") or "").strip()
    texto = data.get("texto") or ""
    if not session_id or not texto:
        return jsonify({"status": "erro", "mensagem": "session_id e texto são obrigatórios"}), 400
    try:
        from services.message_service import MessageService
        cid = get_current_cliente_id(current_user)
        MessageService.salvar_mensagem(
            cliente_id=cid,
            remote_id=session_id,
            canal="website",
            funcao="assistant",
            conteudo=texto,
        )
        room = f"website:{cid}:{session_id}"
        socketio = current_app.extensions.get("socketio")
        if socketio:
            socketio.emit("embed_reply", {"conteudo": texto}, room=room)
        return jsonify({"status": "sucesso"}), 200
    except Exception as e:
        current_app.logger.exception("embed send_to_visitor")
        return jsonify({"status": "erro", "mensagem": str(e)}), 500


@embed_bp.route("/api/embed/message", methods=["POST"])
def widget_send_message():
    """Widget do site envia mensagem (sem Socket.IO). Valida X-Embed-Key ou body key; processa em background."""
    data = request.get_json(silent=True) or {}
    embed_key = _embed_key_from_widget_request()
    session_id = (data.get("session_id") or "").strip()
    text = (data.get("text") or data.get("mensagem") or "").strip()
    #region agent log widget_send_message_enter
    try:
        payload = {
            "sessionId": "1db042",
            "runId": "pre-debug",
            "hypothesisId": "H3_widget_route_reached",
            "location": "panel/routes/embed.py:widget_send_message",
            "message": "Widget endpoint reached (CSRF allowlist mismatch?)",
            "data": {
                "key_len": len(embed_key),
                "session_id_len": len(session_id),
                "text_len": len(text),
            },
            "timestamp": int(time.time() * 1000),
        }
        with open(_debug_log_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(payload, ensure_ascii=False) + "\n")
    except Exception:
        pass
    #endregion
    if not embed_key or not session_id or not text:
        return jsonify({"status": "erro", "mensagem": "key (header X-Embed-Key ou body), session_id e text são obrigatórios"}), 400
    try:
        cliente_id = _cliente_id_from_embed_key(embed_key)
        if not cliente_id:
            return jsonify({"status": "erro", "mensagem": "Chave inválida"}), 403
        socketio = current_app.extensions.get("socketio")
        def processar():
            try:
                from services.message_service import MessageService
                MessageService.processar_mensagem_entrada(
                    "website", session_id, text, cliente_id, None, socketio,
                )
            except Exception as e:
                current_app.logger.exception("embed processar_mensagem_entrada: %s", e)
        threading.Thread(target=processar, daemon=True).start()
        return jsonify({"status": "sucesso"}), 200
    except Exception as e:
        current_app.logger.exception("embed widget_send_message")
        return jsonify({"status": "erro", "mensagem": str(e)}), 500


@embed_bp.route("/api/embed/media", methods=["POST"])
def widget_send_media():
    """Widget do site envia mídia (imagem/arquivo) via multipart FormData."""
    embed_key = _embed_key_from_widget_request()
    session_id = (request.form.get("session_id") or "").strip()
    file_storage = request.files.get("file")

    if not embed_key or not session_id or not file_storage:
        return jsonify({"status": "erro", "mensagem": "key (header X-Embed-Key ou form), session_id e file são obrigatórios"}), 400

    try:
        cliente_id = _cliente_id_from_embed_key(embed_key)
        if not cliente_id:
            return jsonify({"status": "erro", "mensagem": "Chave inválida"}), 403
        socketio = current_app.extensions.get("socketio")

        from services.anexo_service import save_uploaded_file

        # Salva o anexo agora (para retornar anexo_url imediatamente para o widget).
        anexo_url, _path_file, mimetype, nome_original = save_uploaded_file(file_storage, str(cliente_id))
        if not anexo_url:
            return jsonify({"status": "erro", "mensagem": "Falha ao salvar mídia."}), 500

        texto_base = "[imagem enviada]" if (mimetype or "").lower().startswith("image/") else "[arquivo enviado]"

        def processar():
            try:
                from services.message_service import MessageService
                MessageService.processar_mensagem_entrada(
                    "website",
                    session_id,
                    texto_base,
                    cliente_id,
                    None,
                    socketio,
                    anexo_url=anexo_url,
                    anexo_nome=nome_original,
                    anexo_tipo=mimetype,
                )
            except Exception as e:
                current_app.logger.exception("embed processar_mensagem_entrada (media): %s", e)

        threading.Thread(target=processar, daemon=True).start()
        return jsonify({"status": "sucesso", "anexo_url": anexo_url}), 200
    except Exception as e:
        current_app.logger.exception("embed widget_send_media")
        return jsonify({"status": "erro", "mensagem": str(e)}), 500


@embed_bp.route("/api/embed/poll", methods=["GET"])
def widget_poll():
    """Widget busca respostas do bot em historico_mensagens. Retorna só mensagens novas (created_at > last_at).
    last_at: opcional, ISO do cliente; se não enviado, usa _embed_last_poll_at (fallback). 100% stateless se o cliente enviar last_at."""
    embed_key = _embed_key_from_widget_request()
    session_id = (request.args.get("session_id") or "").strip()
    last_at_param = (request.args.get("last_at") or "").strip()
    if not embed_key or not session_id:
        return jsonify({"status": "erro", "mensagens": []}), 400
    try:
        cliente_id = _cliente_id_from_embed_key(embed_key)
        if not cliente_id:
            return jsonify({"status": "erro", "mensagens": []}), 403
        room = f"website:{cliente_id}:{session_id}"
        last_at = last_at_param if last_at_param else _embed_last_poll_at.get(room)
        now_iso = datetime.now(timezone.utc).isoformat()
        if last_at:
            q = (
                supabase.table(Tables.MENSAGENS)
                .select(MensagemModel.CONTEUDO, MensagemModel.CRIADO_EM)
                .eq(MensagemModel.CLIENTE_ID, cliente_id)
                .eq(MensagemModel.REMOTE_ID, session_id)
                .eq(MensagemModel.CANAL, "website")
                .eq(MensagemModel.FUNCAO, "assistant")
                .gt(MensagemModel.CRIADO_EM, last_at)
                .order(MensagemModel.CRIADO_EM, desc=False)
            )
        else:
            q = (
                supabase.table(Tables.MENSAGENS)
                .select(MensagemModel.CONTEUDO, MensagemModel.CRIADO_EM)
                .eq(MensagemModel.CLIENTE_ID, cliente_id)
                .eq(MensagemModel.REMOTE_ID, session_id)
                .eq(MensagemModel.CANAL, "website")
                .eq(MensagemModel.FUNCAO, "assistant")
                .order(MensagemModel.CRIADO_EM, desc=True)
                .limit(50)
            )
        res = q.execute()
        rows = list(res.data or [])
        if not last_at and rows:
            rows = list(reversed(rows))
        mensagens = [
            {"conteudo": (row.get(MensagemModel.CONTEUDO) or "").strip() or "", "created_at": row.get(MensagemModel.CRIADO_EM)}
            for row in rows
        ]
        if rows:
            _embed_last_poll_at[room] = rows[-1].get(MensagemModel.CRIADO_EM) or now_iso
        else:
            _embed_last_poll_at[room] = now_iso
        return jsonify({"status": "sucesso", "mensagens": mensagens}), 200
    except Exception as e:
        current_app.logger.exception("embed widget_poll")
        return jsonify({"status": "erro", "mensagens": []}), 500
