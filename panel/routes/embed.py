# panel/routes/embed.py
"""
Rotas para o chat embed (widget instalável no site do cliente).
- GET /api/embed/key: retorna ou gera a chave de embed do cliente logado.
- POST /api/embed/send: envia mensagem do painel para um visitante (session_id).
- POST /api/embed/message: widget envia mensagem (sem Socket.IO).
- GET /api/embed/poll: widget busca respostas do bot em historico_mensagens (canal website, funcao=assistant).

Respostas do chatbot para o canal website são persistidas em historico_mensagens; o poll lê do banco
em vez de fila em memória, garantindo entrega persistente.
"""
import secrets
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

embed_bp = Blueprint("embed", __name__)
_debug_log_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "debug-1db042.log"))


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
    r.headers["Access-Control-Allow-Headers"] = "Content-Type"
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
            key = "emb_" + secrets.token_urlsafe(24)
            supabase.table(Tables.CLIENTES).update({ClienteModel.WEBSITE_CHAT_EMBED_KEY: key}).eq("id", cid).execute()
        return jsonify({"status": "sucesso", "key": key})
    except Exception as e:
        current_app.logger.exception("embed get_or_create_embed_key")
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
    """Widget do site envia mensagem (sem Socket.IO). Valida key e processa em background."""
    data = request.get_json() or {}
    key = (data.get("key") or "").strip()
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
                "key_len": len(key),
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
    if not key or not session_id or not text:
        return jsonify({"status": "erro", "mensagem": "key, session_id e text são obrigatórios"}), 400
    try:
        r = supabase.table(Tables.CLIENTES).select("id").eq(ClienteModel.WEBSITE_CHAT_EMBED_KEY, key).execute()
        if not r.data or len(r.data) == 0:
            return jsonify({"status": "erro", "mensagem": "Chave inválida"}), 403
        cliente_id = r.data[0]["id"]
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
    key = (request.form.get("key") or "").strip()
    session_id = (request.form.get("session_id") or "").strip()
    file_storage = request.files.get("file")

    if not key or not session_id or not file_storage:
        return jsonify({"status": "erro", "mensagem": "key, session_id e file são obrigatórios"}), 400

    try:
        r = supabase.table(Tables.CLIENTES).select("id").eq(ClienteModel.WEBSITE_CHAT_EMBED_KEY, key).execute()
        if not r.data or len(r.data) == 0:
            return jsonify({"status": "erro", "mensagem": "Chave inválida"}), 403
        cliente_id = r.data[0]["id"]
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
    key = (request.args.get("key") or "").strip()
    session_id = (request.args.get("session_id") or "").strip()
    last_at_param = (request.args.get("last_at") or "").strip()
    if not key or not session_id:
        return jsonify({"status": "erro", "mensagens": []}), 400
    try:
        r = supabase.table(Tables.CLIENTES).select("id").eq(ClienteModel.WEBSITE_CHAT_EMBED_KEY, key).execute()
        if not r.data or len(r.data) == 0:
            return jsonify({"status": "erro", "mensagens": []}), 403
        cliente_id = r.data[0]["id"]
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
