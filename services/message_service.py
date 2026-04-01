import os
from datetime import datetime, timezone

from database.supabase_sq import supabase
from database.models import Tables, MensagemModel
from base.config import settings
from services.message_helpers import get_conversacao_setor, parece_base64_imagem


class MessageService:
    @staticmethod
    def processar_mensagem_entrada(
        canal,
        remote_id,
        texto,
        cliente_id,
        instancia=None,
        socketio=None,
        website_room=None,
        push_name=None,
        embed_reply_store=None,
        anexo_url=None,
        anexo_nome=None,
        anexo_tipo=None,
        message_meta=None,
    ):
        """
        Coordena o fluxo: Salva User -> Notifica Painel -> FlowExecutor (e opcionalmente IA) -> Envia ao canal.

        website_room: str | None. Para canal "website", room SocketIO e chave da fila de respostas (website:cliente_id:session_id).
        embed_reply_store: dict | None. Fila de respostas para o widget (embed_pending_replies). Deve ser repassado a FlowExecutor.process
        para que as respostas do fluxo sejam depositadas em embed_reply_store[website_room] e entregues via GET /api/embed/poll.

        push_name: nome do remetente (ex.: Evolution envia pushName) para exibir no painel.
        anexo_url, anexo_nome, anexo_tipo: opcionais; quando a mensagem tem imagem/arquivo baixado (ex.: WAHA media).
        """
        try:
            # #region agent log
            try:
                import json as _json, time as _t
                rid_last4 = "".join([c for c in str(remote_id) if c.isdigit()])[-4:] if remote_id else ""
                _p = {
                    "sessionId": "3bd729",
                    "runId": "pre-fix",
                    "hypothesisId": "H5",
                    "location": "services/message_service.py",
                    "message": "message_service_entry",
                    "data": {
                        "canal": canal,
                        "remoteLast4": rid_last4,
                        "textoLen": len(texto or ""),
                        "textoIsChoice": (texto or "").strip().lower() in ("1", "2", "3", "sim", "não", "nao"),
                    },
                    "timestamp": int(_t.time() * 1000),
                }
                try:
                    print("[DBG3bd729] " + _json.dumps(_p, ensure_ascii=False), flush=True)
                except Exception:
                    pass
                with open("debug-3bd729.log", "a", encoding="utf-8") as f:
                    f.write(_json.dumps(_p, ensure_ascii=False) + "\n")
            except Exception:
                pass
            # #endregion
            if supabase is None:
                print("[MessageService] Supabase não inicializado (verifique SUPABASE_URL/SUPABASE_KEY no .env).", flush=True)
                return

            # Normalizar: se o cliente enviou imagem (base64), não salvar/enviar o blob; a IA recebe um placeholder
            if parece_base64_imagem(texto):
                texto = "[imagem enviada]"

            # 1. Salvar a mensagem do USUÁRIO no banco de dados
            MessageService.salvar_mensagem(
                cliente_id=cliente_id,
                remote_id=remote_id,
                canal=canal,
                funcao="user",
                conteudo=texto,
                anexo_url=anexo_url,
                anexo_nome=anexo_nome,
                anexo_tipo=anexo_tipo,
            )
            print(f"[MessageService] Mensagem salva: canal={canal} remote_id={remote_id} cliente_id={cliente_id} len={len(texto)}", flush=True)

            # 2. Notificar o Painel via SocketIO (room do cliente = notificação em tempo real sem clicar)
            if socketio:
                try:
                    payload = {
                        'canal': canal,
                        'remote_id': remote_id,
                        'conteudo': texto,
                        'funcao': 'user',
                        'cliente_id': str(cliente_id),
                        'created_at': datetime.now(timezone.utc).isoformat(),
                    }
                    if push_name:
                        payload['push_name'] = push_name
                    if anexo_url:
                        payload['anexo_url'] = anexo_url
                    if anexo_nome:
                        payload['anexo_nome'] = anexo_nome
                    if anexo_tipo:
                        payload['anexo_tipo'] = anexo_tipo
                    socketio.emit('nova_mensagem', payload, room=f"painel:{cliente_id}")
                    print(f"[MessageService] SocketIO nova_mensagem emitida para room painel:{cliente_id} canal={canal} remote_id={remote_id}", flush=True)
                except Exception as e:
                    print(f"[MessageService] Erro ao emitir SocketIO (User): {e}", flush=True)
            # Web Push: notificação mesmo com aba em segundo plano
            try:
                from services.push_service import send_web_push_to_cliente
                titulo = "Nova mensagem - ZapAction"
                corpo = (texto or "")[:60] + ("…" if len(texto or "") > 60 else "")
                send_web_push_to_cliente(cliente_id, titulo, corpo or "Nova mensagem")
            except Exception as e:
                pass  # opcional; não falha o fluxo

            # Se a conversa está com humano ou encerrada, não executar o fluxo (evitar que o bot responda).
            setor = get_conversacao_setor(cliente_id, canal, remote_id)
            if setor in ("atendimento_humano", "atendimento_encerrado"):
                # #region agent log
                try:
                    import json as _json, time as _t
                    rid_last4 = "".join([c for c in str(remote_id) if c.isdigit()])[-4:] if remote_id else ""
                    _p = {
                        "sessionId": "3bd729",
                        "runId": "pre-fix",
                        "hypothesisId": "H5",
                        "location": "services/message_service.py",
                        "message": "message_service_blocked_by_setor",
                        "data": {"canal": canal, "remoteLast4": rid_last4, "setor": setor},
                        "timestamp": int(_t.time() * 1000),
                    }
                    try:
                        print("[DBG3bd729] " + _json.dumps(_p, ensure_ascii=False), flush=True)
                    except Exception:
                        pass
                    with open("debug-3bd729.log", "a", encoding="utf-8") as f:
                        f.write(_json.dumps(_p, ensure_ascii=False) + "\n")
                except Exception:
                    pass
                # #endregion
                return

            # Flow Builder: executar máquina de estados. Repasse explícito de website_room e embed_reply_store
            # para o canal website (entrega via embed_pending_replies e SocketIO).
            try:
                from services.flow_executor import FlowExecutor
                print(
                    f"[MessageService] Chamando FlowExecutor.process cliente_id={cliente_id} canal={canal} remote_id={remote_id}",
                    flush=True,
                )
                handled = FlowExecutor.process(
                    cliente_id,
                    canal,
                    remote_id,
                    texto or "",
                    instancia=instancia,
                    socketio=socketio,
                    website_room=website_room,
                    embed_reply_store=embed_reply_store,
                    message_meta=message_meta,
                )
                print(
                    f"[MessageService] FlowExecutor.process retornou handled={handled} para canal={canal} remote_id={remote_id}",
                    flush=True,
                )
                # #region agent log
                try:
                    import json as _json, time as _t
                    rid_last4 = "".join([c for c in str(remote_id) if c.isdigit()])[-4:] if remote_id else ""
                    _p = {
                        "sessionId": "3bd729",
                        "runId": "pre-fix",
                        "hypothesisId": "H5",
                        "location": "services/message_service.py",
                        "message": "message_service_flow_return",
                        "data": {"canal": canal, "remoteLast4": rid_last4, "handled": bool(handled)},
                        "timestamp": int(_t.time() * 1000),
                    }
                    try:
                        print("[DBG3bd729] " + _json.dumps(_p, ensure_ascii=False), flush=True)
                    except Exception:
                        pass
                    with open("debug-3bd729.log", "a", encoding="utf-8") as f:
                        f.write(_json.dumps(_p, ensure_ascii=False) + "\n")
                except Exception:
                    pass
                # #endregion
                if handled:
                    return  # fluxo tratou e enviou resposta
            except Exception as e:
                print(f"[MessageService] FlowExecutor exceção: {e}", flush=True)
                import traceback
                traceback.print_exc()
                raise  # não ocultar exceção (ex.: banco); chamador pode logar e tratar

        except Exception as e:
            print(f"[MessageService] Erro crítico no fluxo: {e}", flush=True)

    @staticmethod
    def registrar_mensagem_saida(cliente_id, remote_id, canal, texto, socketio=None, anexo_url=None, anexo_nome=None, anexo_tipo=None,
                                 atendente_tipo="chatbot", atendente_nome_snapshot="Chatbot"):
        """
        Registra uma mensagem enviada pelo negócio (ex.: pelo app WhatsApp oficial) no histórico
        e notifica o painel. atendente_tipo/nome_snapshot: quem enviou (chatbot ou humano).
        """
        if supabase is None:
            return
        MessageService.salvar_mensagem(
            cliente_id=cliente_id,
            remote_id=remote_id,
            canal=canal,
            funcao="assistant",
            conteudo=texto or "",
            anexo_url=anexo_url,
            anexo_nome=anexo_nome,
            anexo_tipo=anexo_tipo,
            atendente_tipo=atendente_tipo,
            atendente_nome_snapshot=atendente_nome_snapshot,
        )
        if socketio:
            try:
                payload = {
                    "canal": canal,
                    "remote_id": remote_id,
                    "conteudo": texto or "",
                    "funcao": "assistant",
                    "cliente_id": str(cliente_id),
                    "created_at": datetime.now(timezone.utc).isoformat(),
                }
                if anexo_url:
                    payload["anexo_url"] = anexo_url
                if anexo_nome:
                    payload["anexo_nome"] = anexo_nome
                if anexo_tipo:
                    payload["anexo_tipo"] = anexo_tipo
                socketio.emit("nova_mensagem", payload, room=f"painel:{cliente_id}")
            except Exception as e:
                print(f"[MessageService] Erro ao emitir SocketIO (mensagem saída): {e}", flush=True)

    @staticmethod
    def salvar_mensagem(cliente_id, remote_id, canal, funcao, conteudo, anexo_url=None, anexo_nome=None, anexo_tipo=None,
                       atendente_tipo=None, atendente_usuario_id=None, atendente_nome_snapshot=None):
        """Inserir mensagens no histórico. atendente_*: quem atendeu (chatbot ou humano) para exibir no painel e nas redes."""
        data = {
            MensagemModel.CLIENTE_ID: cliente_id,
            MensagemModel.REMOTE_ID: remote_id,
            MensagemModel.CANAL: canal,
            MensagemModel.FUNCAO: funcao,
            MensagemModel.CONTEUDO: conteudo,
        }
        if anexo_url is not None:
            data[MensagemModel.ANEXO_URL] = anexo_url
        if anexo_nome is not None:
            data[MensagemModel.ANEXO_NOME] = anexo_nome
        if anexo_tipo is not None:
            data[MensagemModel.ANEXO_TIPO] = anexo_tipo
        if atendente_tipo is not None:
            data[MensagemModel.ATENDENTE_TIPO] = atendente_tipo
        if atendente_usuario_id is not None:
            data[MensagemModel.ATENDENTE_USUARIO_ID] = atendente_usuario_id
        if atendente_nome_snapshot is not None:
            data[MensagemModel.ATENDENTE_NOME_SNAPSHOT] = atendente_nome_snapshot
        try:
            return supabase.table(Tables.MENSAGENS).insert(data).execute()
        except Exception as e:
            err = str(e).lower()
            if "anexo" in err or "column" in err or "atendente" in err:
                for k in (MensagemModel.ANEXO_URL, MensagemModel.ANEXO_NOME, MensagemModel.ANEXO_TIPO,
                          MensagemModel.ATENDENTE_TIPO, MensagemModel.ATENDENTE_USUARIO_ID, MensagemModel.ATENDENTE_NOME_SNAPSHOT):
                    data.pop(k, None)
                return supabase.table(Tables.MENSAGENS).insert(data).execute()
            raise

    @staticmethod
    def obter_historico(cliente_id, remote_id, limite=10):
        """Busca as últimas mensagens para manter a memória da conversa"""
        try:
            res = supabase.table(Tables.MENSAGENS).select("*")\
                .eq(MensagemModel.CLIENTE_ID, cliente_id)\
                .eq(MensagemModel.REMOTE_ID, remote_id)\
                .order("created_at", desc=True)\
                .limit(limite).execute()
            
            # Inverte para que a conversa fique na ordem cronológica correta
            return res.data[::-1] if res.data else []
        except Exception as e:
            print(f"[MessageService] Erro ao buscar histórico: {e}", flush=True)
            return []