# services/flow_executor.py
"""
Máquina de estados do Flow Builder.
- Lê o JSON do fluxo (nodes/edges no padrão React Flow).
- Persiste o current_node_id por (cliente_id, canal, remote_id) no banco.
- Resolve o próximo nó pela resposta do usuário (botão clicado ou texto).
- Envia mensagem (texto ou interactive com botões) via Evolution/Meta.
"""
from __future__ import annotations

import json
import re
from datetime import datetime, timezone

from database.supabase_sq import supabase
from database.models import Tables, LeadModel, ConversacaoSetorModel
from services.routing_service import RoutingService
from services.message_service import MessageService
from services.flow_helpers import (
    PENDING_COLLECT_KEYS,
    is_reiniciar_comando,
    nodes_and_edges,
    node_by_id,
    entry_node_id,
    find_next_node_id,
    questionnaire_collect_keys,
    format_questionnaire_message,
    collected_data_for_lead,
    next_node_after,
    get_questionnaire_lead_sequence,
    parse_lead_from_text,
)
from services.flow_state import get_flow, get_state, set_state, clear_state


def _norm_url_for_compare(url: str | None) -> str:
    """Normaliza URL para comparação simples (sem parse completo)."""
    u = (url or "").strip()
    if not u:
        return ""
    u = u.lower()
    # Remove barras finais para reduzir falso negativo.
    while u.endswith("/"):
        u = u[:-1]
    return u


def _urls_match(expected: str | None, actual: str | None) -> bool:
    ne = _norm_url_for_compare(expected)
    na = _norm_url_for_compare(actual)
    if not ne or not na:
        return False
    return ne == na or ne in na or na in ne


def _norm_free_text(v: str | None) -> str:
    """Normaliza texto livre para comparação tolerante a espaços/pontuação."""
    s = (v or "").strip().lower()
    s = re.sub(r"\s+", " ", s)
    return s.strip()


def _norm_choice_value(v: str | None) -> str:
    """Normaliza valor tipo '1', '1)', '1.' para comparar rapidamente."""
    s = (v or "").strip().lower()
    # Remove qualquer coisa que não seja alfanumérico.
    s = re.sub(r"[^a-z0-9]+", "", s)
    return s


def _send_node_message(
    cliente_id: str,
    canal: str,
    remote_id: str,
    instancia: str | None,
    node: dict,
    socketio=None,
    website_room: str | None = None,
    embed_reply_store: dict | None = None,
) -> tuple[bool, str | None]:
    """
    Envia a mensagem do nó e garante persistência em historico_mensagens (funcao='assistant').
    Canal "website": apenas salva no banco. Demais canais: RoutingService + registrar_mensagem_saida.
    Retorna (True, None) ou (False, mensagem_erro).
    """
    node_type = node.get("type") or "message"
    data = node.get("data") or {}

    if node_type == "questionnaire":
        text = format_questionnaire_message(data)
        buttons = []
    else:
        text = (data.get("text") or data.get("content") or "").strip()
        buttons = data.get("buttons") or []
    if not isinstance(buttons, list):
        buttons = []
    buttons = [b for b in buttons[:3] if isinstance(b, dict) and (b.get("id") or b.get("title") or b.get("label"))]

    # Evita enviar "mensagem vazia" (um espaço) que pode travar/atrapalhar o fluxo no WhatsApp.
    # Se não há texto nem botões, não há nada útil para entregar — consideramos sucesso.
    if not (text or "").strip() and not buttons:
        return (True, None)

    if canal == "website":
        if buttons:
            payload = {
                "text": text,
                "buttons": [{"id": b.get("id"), "title": (b.get("title") or b.get("label") or "").strip() or str(i + 1)} for i, b in enumerate(buttons)]
            }
            conteudo = json.dumps(payload, ensure_ascii=False)
        else:
            conteudo = text
        try:
            MessageService.registrar_mensagem_saida(cliente_id, remote_id, canal, conteudo, socketio)
        except Exception as e:
            print(f"[FlowExecutor] website registrar_mensagem_saida: {e}", flush=True)
        return (True, None)
    if buttons:
        ok, err = RoutingService.enviar_resposta_interativa(
            canal, instancia or "default", remote_id, text, buttons, cliente_id
        )
    else:
        ok, err = RoutingService.enviar_resposta(
            canal, instancia or "default", remote_id, text, cliente_id
        )
    if ok and socketio:
        try:
            MessageService.registrar_mensagem_saida(
                cliente_id, remote_id, canal, text, socketio
            )
        except Exception:
            pass
    return (ok, err)


def _save_lead(
    cliente_id: str,
    canal: str,
    remote_id: str,
    contact_id: str | None,
    flow_id: str,
    collected_data: dict,
    lead_node_data: dict,
) -> None:
    """Salva um lead na tabela leads a partir dos dados coletados no fluxo."""
    print(
        f"[LEAD] _save_lead chamado canal={canal} remote_id={remote_id!r} contact_id={contact_id!r} collected_data keys={list((collected_data or {}).keys())}",
        flush=True,
    )
    if not supabase or not cliente_id:
        print(f"[LEAD] _save_lead abortado: supabase ou cliente_id ausente", flush=True)
        return
    try:
        dados = collected_data_for_lead(collected_data)
        print(f"[LEAD] dados apos collected_data_for_lead: {list(dados.keys())} valores={{(k, (v or '')[:50] if isinstance(v, str) else v) for k, v in dados.items()}}", flush=True)
        for k, v in list(dados.items()):
            if v and isinstance(v, str) and v.strip():
                kl = (k or "").strip().lower()
                if kl in ("nome", "name") and not (dados.get("nome") or "").strip():
                    dados = {**dados, "nome": v.strip()}
                if kl in ("email", "e-mail") and not (dados.get("email") or "").strip():
                    dados = {**dados, "email": v.strip()}
                if kl in ("telefone", "phone", "celular") and not (dados.get("telefone") or "").strip():
                    dados = {**dados, "telefone": v.strip()}
        nome = (dados.get("nome") or dados.get("name") or dados.get("campo_1") or "").strip() or None
        if nome:
            nome = re.sub(r"^[\s,;.\-]+|[\s,;.\-]+$", "", nome).strip() or None
        email = (dados.get("email") or dados.get("e-mail") or dados.get("campo_2") or "").strip() or None
        telefone = (dados.get("telefone") or dados.get("phone") or dados.get("celular") or dados.get("campo_3") or "").strip() or None
        print(f"[LEAD] extraido nome={nome!r} email={email!r} telefone={telefone!r}", flush=True)
        if not nome and not email and not telefone:
            print(f"[LEAD] _save_lead abortado: nome, email e telefone vazios", flush=True)
            return

        # Se o fluxo marcou uma qualificação antes de salvar o lead, aplicamos aqui.
        forced_status = (collected_data or {}).get("__lead_force_status")
        forced_status = (forced_status or "").strip().lower()
        if forced_status not in ("qualificado", "desqualificado"):
            forced_status = ""
        status_to_save = forced_status or "pendente"

        payload = {
            LeadModel.CLIENTE_ID: cliente_id,
            LeadModel.CANAL: canal,
            LeadModel.REMOTE_ID: remote_id,
            LeadModel.CONTACT_ID: contact_id,
            LeadModel.FLOW_ID: flow_id,
            LeadModel.NOME: nome or None,
            LeadModel.EMAIL: email or None,
            LeadModel.TELEFONE: telefone or None,
            LeadModel.DADOS: dados,
            LeadModel.STATUS: status_to_save,
        }

        # Evita criar uma pilha de leads pendentes para o mesmo contato.
        # Se já existir um pendente recente, reaproveita esse registro atualizando os dados.
        try:
            existing_pending = (
                supabase.table(Tables.LEADS)
                .select(LeadModel.ID, LeadModel.STATUS)
                .eq(LeadModel.CLIENTE_ID, cliente_id)
                .eq(LeadModel.CANAL, canal)
            )
            if contact_id:
                existing_pending = existing_pending.eq(LeadModel.CONTACT_ID, contact_id)
            else:
                existing_pending = existing_pending.eq(LeadModel.REMOTE_ID, remote_id)
            existing_pending = (
                existing_pending
                .or_(f"{LeadModel.STATUS}.is.null,{LeadModel.STATUS}.eq.pendente")
                .order(LeadModel.CREATED_AT, desc=True)
                .limit(1)
                .execute()
            )
            if existing_pending.data and len(existing_pending.data) > 0:
                lead_id = existing_pending.data[0].get(LeadModel.ID)
                if lead_id:
                    supabase.table(Tables.LEADS).update({
                        LeadModel.FLOW_ID: flow_id,
                        LeadModel.CONTACT_ID: contact_id,
                        LeadModel.NOME: nome or None,
                        LeadModel.EMAIL: email or None,
                        LeadModel.TELEFONE: telefone or None,
                        LeadModel.DADOS: dados,
                        LeadModel.STATUS: status_to_save,
                    }).eq(LeadModel.ID, lead_id).execute()
                    print(f"[LEAD] update pendente OK id={lead_id!r} nome={nome!r} email={email!r} telefone={telefone!r}", flush=True)
                    return
        except Exception as e:
            print(f"[LEAD] tentativa update pendente falhou: {e}", flush=True)

        supabase.table(Tables.LEADS).insert(payload).execute()
        print(f"[LEAD] insert OK nome={nome!r} email={email!r} telefone={telefone!r}", flush=True)
    except Exception as e:
        print(f"[LEAD] _save_lead ERRO: {e}", flush=True)


def get_existing_lead_with_data(
    cliente_id: str,
    canal: str,
    remote_id: str,
    contact_id: str | None = None,
) -> dict | None:
    """
    Retorna o lead mais recente para (cliente_id, canal, remote_id) que tenha
    nome, email e telefone preenchidos. Não exige status qualificado.
    Retorna None se não houver ou se faltar algum dos três campos.
    """
    if not supabase or not cliente_id:
        return None
    try:
        q = (
            supabase.table(Tables.LEADS)
            .select("*")
            .eq(LeadModel.CLIENTE_ID, cliente_id)
            .eq(LeadModel.CANAL, canal)
        )
        if contact_id:
            q = q.eq(LeadModel.CONTACT_ID, contact_id)
        else:
            q = q.eq(LeadModel.REMOTE_ID, remote_id)
        res = q.order(LeadModel.CREATED_AT, desc=True).limit(1).execute()
        row = (res.data or [{}])[0] if res.data else None
        if not row or not isinstance(row, dict):
            return None
        nome = (row.get(LeadModel.NOME) or "").strip()
        email = (row.get(LeadModel.EMAIL) or "").strip()
        telefone = (row.get(LeadModel.TELEFONE) or "").strip()
        if nome and email and telefone:
            return row
        return None
    except Exception as e:
        print(f"[FlowExecutor] get_existing_lead_with_data: {e}", flush=True)
        return None


def _execute_action(
    cliente_id: str,
    canal: str,
    remote_id: str,
    contact_id: str | None,
    node_data: dict,
    instancia: str | None,
    socketio=None,
    website_room: str | None = None,
    embed_reply_store: dict | None = None,
) -> tuple[bool, str | None]:
    """
    Executa a ação do nó (transfer_human, transfer_to_sector ou send_link).
    Retorna (True, None) em sucesso ou (False, mensagem_erro).
    """
    data = node_data or {}
    action_type = (data.get("actionType") or data.get("action_type") or "").strip().lower().replace(" ", "_")
    if not action_type:
        return (True, None)

    if action_type in ("transfer_human", "transfer_to_sector"):
        try:
            now = datetime.now(timezone.utc).isoformat()
            payload = {
                "cliente_id": str(cliente_id),
                "canal": canal,
                "remote_id": remote_id,
                "setor": "atendimento_humano",
                "updated_at": now,
            }
            if action_type == "transfer_to_sector":
                setor_id = data.get("setor_id") or data.get("setorId")
                if setor_id is not None and str(setor_id).strip() == "":
                    setor_id = None
                payload[ConversacaoSetorModel.SETOR_ID] = setor_id
            supabase.table(Tables.CONVERSACAO_SETOR).upsert(
                payload,
                on_conflict="cliente_id,canal,remote_id",
            ).execute()
        except Exception as e:
            print(f"[FlowExecutor] _execute_action {action_type} upsert: {e}", flush=True)
        clear_state(cliente_id, canal, remote_id, contact_id=contact_id)
        msg = (data.get("message") or data.get("messageBeforeTransfer") or "Um atendente vai te atender.").strip() or "Um atendente vai te atender."
        if canal == "website":
            try:
                MessageService.registrar_mensagem_saida(cliente_id, remote_id, canal, msg, socketio)
            except Exception as e:
                print(f"[FlowExecutor] _execute_action website msg: {e}", flush=True)
            if website_room and embed_reply_store is not None:
                if website_room not in embed_reply_store:
                    embed_reply_store[website_room] = []
                embed_reply_store[website_room].append({"conteudo": msg})
        else:
            ok, err = RoutingService.enviar_resposta(canal, instancia or "default", remote_id, msg, cliente_id)
            if not ok:
                return (False, err)
            if socketio:
                try:
                    MessageService.registrar_mensagem_saida(cliente_id, remote_id, canal, msg, socketio)
                except Exception:
                    pass
        return (True, None)

    if action_type == "send_link":
        # Compatibilidade: ao longo do tempo o builder pode ter persistido chaves diferentes.
        url = (
            data.get("url")
            or data.get("link")
            or data.get("href")
            or data.get("linkUrl")
            or data.get("link_url")
            or ""
        )
        url = (str(url) if url is not None else "").strip()
        # WhatsApp só transforma em link clicável de forma confiável quando há esquema.
        if url and not (url.lower().startswith("http://") or url.lower().startswith("https://")):
            url = "https://" + url.lstrip("/")

        link_text = (data.get("linkText") or data.get("link_text") or "").strip()
        if not link_text:
            link_text = url or "Clique aqui"

        raw_message = (data.get("message") or data.get("text") or "").strip()
        if not url:
            # Se o fluxo chegou aqui sem URL, preferimos sinalizar claramente (evita parecer "bugado").
            missing_msg = "Link não configurado. Edite o bloco Ação → Enviar link e preencha a URL."
            if canal == "website":
                try:
                    MessageService.registrar_mensagem_saida(cliente_id, remote_id, canal, missing_msg, socketio)
                except Exception:
                    pass
                if website_room and embed_reply_store is not None:
                    if website_room not in embed_reply_store:
                        embed_reply_store[website_room] = []
                    embed_reply_store[website_room].append({"conteudo": missing_msg})
            else:
                RoutingService.enviar_resposta(canal, instancia or "default", remote_id, missing_msg, cliente_id)
                if socketio:
                    try:
                        MessageService.registrar_mensagem_saida(cliente_id, remote_id, canal, missing_msg, socketio)
                    except Exception:
                        pass
            return (True, None)
        if raw_message:
            # Se o usuário configurou mensagem, garantimos que a URL esteja presente.
            text = raw_message
            if url and (url not in text):
                # Colocar em nova linha ajuda o WhatsApp a detectar e "pré-visualizar" o link.
                text = f"{text}\n{url}".strip()
        else:
            # Sem mensagem customizada, enviamos "TextoDoLink URL".
            if url:
                text = f"{link_text}\n{url}".strip()
            else:
                text = (link_text or "Clique aqui").strip() or "Clique aqui"
        if canal == "website":
            try:
                MessageService.registrar_mensagem_saida(cliente_id, remote_id, canal, text, socketio)
            except Exception as e:
                print(f"[FlowExecutor] _execute_action send_link website: {e}", flush=True)
            if website_room and embed_reply_store is not None:
                if website_room not in embed_reply_store:
                    embed_reply_store[website_room] = []
                embed_reply_store[website_room].append({"conteudo": text})
        else:
            ok, err = RoutingService.enviar_resposta(canal, instancia or "default", remote_id, text, cliente_id)
            if not ok:
                return (False, err)
            if socketio:
                try:
                    MessageService.registrar_mensagem_saida(cliente_id, remote_id, canal, text, socketio)
                except Exception:
                    pass

            # WAHA geralmente NÃO envia webhook ao apenas "abrir/clicar" o link puro.
            # Para o fluxo avançar de forma confiável, enviamos uma confirmação quick-reply.
            confirm_title = (data.get("confirmTitle") or data.get("confirm_title") or "Já cliquei").strip() or "Já cliquei"
            confirm_id = (data.get("confirmId") or data.get("confirm_id") or "send_link_confirm").strip() or "send_link_confirm"
            confirm_body = (
                data.get("confirmMessage")
                or data.get("confirm_message")
                or "Para continuar, toque no botão abaixo (confirmar que abriu o link)."
            ).strip() or "Para continuar, toque no botão abaixo (confirmar que abriu o link)."

            ok2, err2 = RoutingService.enviar_resposta_interativa(
                canal,
                instancia or "default",
                remote_id,
                confirm_body,
                [{"id": confirm_id, "title": confirm_title}],
                cliente_id,
            )
            if not ok2:
                # Fallback se interactive não estiver disponível.
                ok3, err3 = RoutingService.enviar_resposta(
                    canal,
                    instancia or "default",
                    remote_id,
                    "Para continuar, responda 1 para confirmar que abriu o link.",
                    cliente_id,
                )
                if not ok3:
                    return (False, err3 or err2)
        return (True, None)

    if action_type == "qualificar_lead":
        status_val = (data.get("qualifyStatus") or data.get("status") or "").strip().lower()
        # Fallback defensivo: se o builder não persistiu o status, assumimos "qualificado"
        # (não travar o fluxo por configuração incompleta).
        if not status_val:
            status_val = "qualificado"
        try:
            res = (
                supabase.table(Tables.LEADS)
                .select(LeadModel.ID, LeadModel.STATUS)
                .eq(LeadModel.CLIENTE_ID, cliente_id)
                .eq(LeadModel.CANAL, canal)
            )
            if contact_id:
                res = res.eq(LeadModel.CONTACT_ID, contact_id)
            else:
                res = res.eq(LeadModel.REMOTE_ID, remote_id)
            res = res.order(LeadModel.CREATED_AT, desc=True).limit(20).execute()
            if res.data and len(res.data) > 0:
                # Prioriza qualificar o pendente mais recente para evitar "qualificar o registro errado".
                target_id = None
                for row in (res.data or []):
                    row_status = (row.get(LeadModel.STATUS) or "").strip().lower()
                    if not row_status or row_status == "pendente":
                        target_id = row.get(LeadModel.ID)
                        if target_id:
                            break
                if not target_id:
                    target_id = res.data[0].get(LeadModel.ID)
                if target_id:
                    supabase.table(Tables.LEADS).update({LeadModel.STATUS: status_val}).eq(LeadModel.ID, target_id).execute()
                    print(f"[LEAD] qualificar_lead update OK id={target_id!r} status={status_val!r}", flush=True)
                return (True, None)

            # Nenhum lead encontrado ainda (fluxo pode qualificar antes de "Salvar lead").
            # Não criamos registro “mínimo” (pode falhar por constraints). Em vez disso,
            # gravamos a intenção no state para aplicar quando o lead for salvo.
            try:
                current_node_id, state_flow_id, collected = get_state(cliente_id, canal, remote_id, contact_id=contact_id)
                if state_flow_id:
                    updated = dict(collected or {})
                    updated["__lead_force_status"] = status_val
                    set_state(cliente_id, canal, remote_id, state_flow_id, current_node_id, updated, contact_id=contact_id)
                    print(f"[LEAD] qualificar_lead marcou __lead_force_status={status_val!r} (sem lead ainda)", flush=True)
                else:
                    print(f"[LEAD] qualificar_lead sem lead e sem state_flow_id; mantendo apenas log", flush=True)
            except Exception as mark_e:
                print(f"[FlowExecutor] qualificar_lead marcar state falhou: {mark_e}", flush=True)
            return (True, None)
        except Exception as e:
            print(f"[FlowExecutor] _execute_action qualificar_lead: {e}", flush=True)
            # Não bloquear fluxo por falha de qualificação; apenas logar.
            return (True, None)

    return (True, None)


def _deliver_website_message(
    text: str,
    website_room: str | None,
    embed_reply_store: dict | None,
    socketio=None,
) -> bool:
    """Entrega mensagem ao chat do site: embed_reply_store + SocketIO embed_reply."""
    if not (text or "").strip():
        return True
    if not website_room and not embed_reply_store:
        return False
    if embed_reply_store is not None and website_room:
        if website_room not in embed_reply_store:
            embed_reply_store[website_room] = []
        embed_reply_store[website_room].append({"conteudo": text})
    if socketio and website_room:
        try:
            socketio.emit("embed_reply", {"conteudo": text}, room=website_room)
        except Exception as e:
            print(f"[FlowExecutor] _deliver_website_message SocketIO emit falhou: {e}", flush=True)
    return True


class FlowExecutor:
    """
    Executor do fluxo: recebe mensagem do usuário, atualiza estado e envia o próximo nó.
    Retorna True se o fluxo tratou a mensagem; False para deixar outro handler (ex.: IA) tratar.
    """

    @staticmethod
    def process(
        cliente_id: str,
        canal: str,
        remote_id: str,
        texto: str,
        instancia: str | None = None,
        socketio=None,
        website_room: str | None = None,
        embed_reply_store: dict | None = None,
        message_meta: dict | None = None,
    ) -> bool:
        contact_id = None
        try:
            if isinstance(message_meta, dict):
                contact_id = message_meta.get("contact_id")
                if contact_id is not None:
                    contact_id = str(contact_id).strip() or None
        except Exception:
            contact_id = None
        flow_json, flow_id = get_flow(cliente_id, canal)
        if not flow_json or not flow_id:
            return False
        nodes, edges = nodes_and_edges(flow_json)
        if not nodes:
            return False

        if is_reiniciar_comando(texto or ""):
            clear_state(cliente_id, canal, remote_id, contact_id=contact_id)
            try:
                MessageService.registrar_mensagem_saida(
                    cliente_id, remote_id, canal,
                    "Atendimento reiniciado. Como posso ajudar?",
                    socketio,
                )
            except Exception as e:
                print(f"[FlowExecutor] reiniciar mensagem: {e}", flush=True)
            return True

        current_node_id, state_flow_id, collected_data = get_state(cliente_id, canal, remote_id, contact_id=contact_id)
        if state_flow_id != flow_id:
            current_node_id = None
        print(f"[LEAD] process canal={canal} remote_id={remote_id!r} texto_len={len(texto or '')} current_node_id={current_node_id!r} state_flow_id={state_flow_id!r} flow_id={flow_id!r}", flush=True)
        # #region agent log
        try:
            import json as _json, time as _t
            rid_last4 = "".join([c for c in str(remote_id) if c.isdigit()])[-4:] if remote_id else ""
            _p = {
                "sessionId": "3bd729",
                "runId": "pre-fix",
                "hypothesisId": "H6",
                "location": "services/flow_executor.py",
                "message": "flow_executor_state",
                "data": {"canal": canal, "remoteLast4": rid_last4, "currentNode": current_node_id or "", "flowIdTail": str(flow_id)[-8:]},
                "timestamp": int(_t.time() * 1000),
            }
            with open("debug-3bd729.log", "a", encoding="utf-8") as f:
                f.write(_json.dumps(_p, ensure_ascii=False) + "\n")
        except Exception:
            pass
        # #endregion

        # --- send_link: aguardar clique (não avançar em resposta numérica solta) ---
        awaiting_send_link = (collected_data or {}).get("__awaiting_send_link_click")
        if (
            awaiting_send_link
            and current_node_id
            and (current_node_id or "").strip()
        ):
            current_node = node_by_id(nodes, current_node_id)
            if current_node and (current_node.get("type") or "").strip().lower() == "action":
                node_data = current_node.get("data") or {}
                action_type = (node_data.get("actionType") or node_data.get("action_type") or "").strip().lower().replace(" ", "_")
                if action_type == "send_link":
                    expected_url = (collected_data or {}).get("__expected_url")
                    next_after_id = (collected_data or {}).get("__awaiting_send_link_next_after_id")
                    tries = (collected_data or {}).get("__awaiting_send_link_tries") or 0
                    try:
                        tries = int(tries)
                    except Exception:
                        tries = 0

                    clicked_url = (message_meta or {}).get("clicked_url") if isinstance(message_meta, dict) else None
                    incoming_text = (texto or "").strip()
                    incoming_title_norm = _norm_free_text(incoming_text)
                    incoming_choice_norm = _norm_choice_value(incoming_text)

                    expected_title = (collected_data or {}).get("__awaiting_send_link_confirm_title")
                    expected_confirm_id = (collected_data or {}).get("__awaiting_send_link_confirm_id")
                    expected_choice = (collected_data or {}).get("__awaiting_send_link_confirm_choice") or "1"

                    is_confirm_title = bool(expected_title) and incoming_title_norm == _norm_free_text(expected_title)
                    is_confirm_id = bool(expected_confirm_id) and incoming_title_norm == _norm_free_text(expected_confirm_id)
                    is_confirm_choice = incoming_choice_norm == _norm_choice_value(expected_choice)

                    if _urls_match(expected_url, clicked_url) or is_confirm_title or is_confirm_id or is_confirm_choice:
                        # Limpa marcadores e segue para o próximo nó configurado no fluxo.
                        clean_data = dict(collected_data or {})
                        for k in (
                            "__awaiting_send_link_click",
                            "__expected_url",
                            "__awaiting_send_link_next_after_id",
                            "__awaiting_send_link_tries",
                            "__awaiting_send_link_confirm_title",
                            "__awaiting_send_link_confirm_id",
                            "__awaiting_send_link_confirm_choice",
                        ):
                            clean_data.pop(k, None)

                        # Atualiza estado para que qualquer lead a seguir use collected_data sem os marcadores.
                        set_state(cliente_id, canal, remote_id, flow_id, current_node_id, clean_data, contact_id=contact_id)

                        if not next_after_id:
                            set_state(cliente_id, canal, remote_id, flow_id, None, contact_id=contact_id)
                            return True

                        # Dispara o próximo nó como faria no fluxo normal.
                        next_id = next_after_id
                        next_node = node_by_id(nodes, next_id)
                        if not next_node:
                            set_state(cliente_id, canal, remote_id, flow_id, None, contact_id=contact_id)
                            return True

                        saved_lead_once = False
                        while next_node and next_node.get("type") == "lead":
                            _, _, _lead_collected = get_state(cliente_id, canal, remote_id, contact_id=contact_id)
                            if not saved_lead_once:
                                _save_lead(
                                    cliente_id,
                                    canal,
                                    remote_id,
                                    contact_id,
                                    flow_id,
                                    _lead_collected,
                                    next_node.get("data") or {},
                                )
                                saved_lead_once = True
                            next_id = next_node_after(next_id, edges)
                            next_node = node_by_id(nodes, next_id) if next_id else None

                        if not next_node:
                            set_state(cliente_id, canal, remote_id, flow_id, None, contact_id=contact_id)
                            return True

                        if next_node.get("type") == "action":
                            data = next_node.get("data") or {}
                            next_action_type = (data.get("actionType") or data.get("action_type") or "").strip().lower().replace(" ", "_")
                            ok, err = _execute_action(
                                cliente_id,
                                canal,
                                remote_id,
                                contact_id,
                                data,
                                instancia,
                                socketio,
                                website_room,
                                embed_reply_store,
                            )
                            if not ok:
                                print(f"[FlowExecutor] _execute_action falhou: {err}", flush=True)
                            if next_action_type in ("transfer_human", "transfer_to_sector"):
                                return True
                            next_after_id2 = next_node_after(next_id, edges)
                            set_state(cliente_id, canal, remote_id, flow_id, next_after_id2, contact_id=contact_id)
                            return True

                        if next_node.get("type") == "end":
                            text = (next_node.get("data") or {}).get("text") or ""
                            if (text or "").strip():
                                if canal == "website":
                                    try:
                                        MessageService.registrar_mensagem_saida(cliente_id, remote_id, canal, text.strip(), socketio)
                                    except Exception as e:
                                        print(f"[FlowExecutor] website end: {e}", flush=True)
                                else:
                                    RoutingService.enviar_resposta(canal, instancia or "default", remote_id, text.strip(), cliente_id)
                                    if socketio:
                                        try:
                                            MessageService.registrar_mensagem_saida(cliente_id, remote_id, canal, text.strip(), socketio)
                                        except Exception:
                                            pass
                            set_state(cliente_id, canal, remote_id, flow_id, None, contact_id=contact_id)
                            return True

                        # Mensagem/questionário
                        ok, err = _send_node_message(
                            cliente_id,
                            canal,
                            remote_id,
                            instancia,
                            next_node,
                            socketio,
                            website_room,
                            embed_reply_store,
                        )
                        if ok:
                            if next_node.get("type") == "questionnaire":
                                keys = questionnaire_collect_keys(next_node.get("data") or {})
                                collect_state = {PENDING_COLLECT_KEYS: keys} if keys else {}
                                set_state(cliente_id, canal, remote_id, flow_id, next_id, collect_state, contact_id=contact_id)
                            else:
                                set_state(cliente_id, canal, remote_id, flow_id, next_id, contact_id=contact_id)
                        else:
                            print(f"[FlowExecutor] Falha ao enviar nó {next_id}: {err}", flush=True)
                        return True

                    # Ainda não clicou (ou meta veio vazia): incrementa tentativas e evita avançar.
                    tries += 1
                    if tries >= 2:
                        ok, err = _execute_action(
                            cliente_id,
                            canal,
                            remote_id,
                            contact_id,
                            {"actionType": "transfer_human", "message": "Um atendente vai te atender."},
                            instancia,
                            socketio,
                            website_room,
                            embed_reply_store,
                        )
                        if not ok:
                            print(f"[FlowExecutor] anti-loop transfer_human falhou: {err}", flush=True)
                        return True

                    # Reenvia a instrução (1ª tentativa não-confirmatória) para reduzir loop.
                    confirm_title = (collected_data or {}).get("__awaiting_send_link_confirm_title") or "Já cliquei"
                    confirm_id = (collected_data or {}).get("__awaiting_send_link_confirm_id") or "send_link_confirm"
                    resend_text = "Envie 1 para continuar"

                    if canal == "website":
                        try:
                            MessageService.registrar_mensagem_saida(cliente_id, remote_id, canal, resend_text, socketio)
                        except Exception:
                            pass
                    else:
                        try:
                            ok2, err2 = RoutingService.enviar_resposta_interativa(
                                canal,
                                instancia or "default",
                                remote_id,
                                resend_text,
                                [{"id": confirm_id, "title": confirm_title}],
                                cliente_id,
                            )
                            if not ok2:
                                ok3, err3 = RoutingService.enviar_resposta(
                                    canal,
                                    instancia or "default",
                                    remote_id,
                                    resend_text,
                                    cliente_id,
                                )
                                if not ok3:
                                    print(f"[FlowExecutor] resend send_link instruction falhou: {err3 or err2}", flush=True)
                        except Exception:
                            pass

                    updated_data = dict(collected_data or {})
                    updated_data["__awaiting_send_link_tries"] = tries
                    set_state(cliente_id, canal, remote_id, flow_id, current_node_id, updated_data, contact_id=contact_id)
                    return True

        # --- Se o estado ficou preso em um nó de ação (ex.: qualificar_lead), avançar automaticamente ---
        # Isso evita o sintoma: usuário responde "1" e find_next_node_id retorna vazio porque action não é nó de entrada.
        if current_node_id:
            stuck_node = node_by_id(nodes, current_node_id)
            if stuck_node and (stuck_node.get("type") or "").strip().lower() == "action":
                stuck_data = stuck_node.get("data") or {}
                stuck_action_type = (
                    (stuck_data.get("actionType") or stuck_data.get("action_type") or "")
                    .strip()
                    .lower()
                    .replace(" ", "_")
                )
                # send_link é especial e já é tratado acima via __awaiting_send_link_click.
                if stuck_action_type and stuck_action_type != "send_link":
                    next_after_id = next_node_after(current_node_id, edges)
                    set_state(cliente_id, canal, remote_id, flow_id, next_after_id, contact_id=contact_id)

                    if not next_after_id:
                        return True

                    next_node = node_by_id(nodes, next_after_id)
                    if not next_node:
                        set_state(cliente_id, canal, remote_id, flow_id, None, contact_id=contact_id)
                        return True

                    # Reaproveita a lógica existente: lead->action->end->message.
                    saved_lead_once = False
                    next_id = next_after_id
                    while next_node and next_node.get("type") == "lead":
                        _, _, cdata = get_state(cliente_id, canal, remote_id, contact_id=contact_id)
                        if not saved_lead_once:
                            _save_lead(cliente_id, canal, remote_id, contact_id, flow_id, cdata, next_node.get("data") or {})
                            saved_lead_once = True
                        next_id = next_node_after(next_id, edges)
                        next_node = node_by_id(nodes, next_id) if next_id else None

                    if not next_node:
                        set_state(cliente_id, canal, remote_id, flow_id, None, contact_id=contact_id)
                        return True

                    if next_node.get("type") == "action":
                        data = next_node.get("data") or {}
                        action_type2 = (data.get("actionType") or data.get("action_type") or "").strip().lower().replace(" ", "_")
                        ok, err = _execute_action(cliente_id, canal, remote_id, contact_id, data, instancia, socketio, website_room, embed_reply_store)
                        if not ok:
                            print(f"[FlowExecutor] _execute_action (unstick) falhou: {err}", flush=True)
                        if action_type2 in ("transfer_human", "transfer_to_sector"):
                            return True
                        next_after_id2 = next_node_after(next_id, edges)
                        set_state(cliente_id, canal, remote_id, flow_id, next_after_id2, contact_id=contact_id)
                        return True

                    if next_node.get("type") == "end":
                        text = (next_node.get("data") or {}).get("text") or ""
                        if (text or "").strip():
                            if canal == "website":
                                try:
                                    MessageService.registrar_mensagem_saida(cliente_id, remote_id, canal, text.strip(), socketio)
                                except Exception as e:
                                    print(f"[FlowExecutor] website end (unstick): {e}", flush=True)
                            else:
                                RoutingService.enviar_resposta(canal, instancia or "default", remote_id, text.strip(), cliente_id)
                                if socketio:
                                    try:
                                        MessageService.registrar_mensagem_saida(cliente_id, remote_id, canal, text.strip(), socketio)
                                    except Exception:
                                        pass
                        set_state(cliente_id, canal, remote_id, flow_id, None, contact_id=contact_id)
                        return True

                    # message/questionnaire
                    ok, err = _send_node_message(cliente_id, canal, remote_id, instancia, next_node, socketio, website_room, embed_reply_store)
                    if ok:
                        if next_node.get("type") == "questionnaire":
                            keys = questionnaire_collect_keys(next_node.get("data") or {})
                            collect_state = {PENDING_COLLECT_KEYS: keys} if keys else {}
                            set_state(cliente_id, canal, remote_id, flow_id, next_id, collect_state, contact_id=contact_id)
                        else:
                            set_state(cliente_id, canal, remote_id, flow_id, next_id, contact_id=contact_id)
                    else:
                        print(f"[FlowExecutor] Falha ao enviar nó (unstick) {next_id}: {err}", flush=True)
                    return True

        pending_keys = (collected_data or {}).get(PENDING_COLLECT_KEYS)
        if (
            current_node_id
            and isinstance(pending_keys, list)
            and len(pending_keys) > 0
        ):
            print(f"[LEAD] ramo questionario: pending_keys={pending_keys}", flush=True)
            new_data = dict(collected_data)
            parsed = parse_lead_from_text(texto or "")
            print(f"[LEAD] parse_lead_from_text resultado: nome={parsed.get('nome')!r} email={parsed.get('email')!r} telefone={parsed.get('telefone')!r}", flush=True)
            key_to_parsed = {"nome": "nome", "name": "nome", "email": "email", "e-mail": "email", "telefone": "telefone", "phone": "telefone", "celular": "telefone", "campo_1": "nome", "campo_2": "email", "campo_3": "telefone"}
            still_pending = []
            for k in pending_keys:
                source = key_to_parsed.get(k, k)
                if source in ("nome", "email", "telefone") and (parsed.get(source) or "").strip():
                    new_data[k] = (parsed[source] or "").strip()
                else:
                    still_pending.append(k)
            if len(still_pending) == len(pending_keys):
                key = pending_keys[0]
                new_data[key] = (texto or "").strip()
                still_pending = pending_keys[1:]
                print(f"[LEAD] parser nao preencheu nada: atribuido texto inteiro ao primeiro key={key!r}", flush=True)
            for std_key, parse_key in [("nome", "nome"), ("email", "email"), ("telefone", "telefone")]:
                val = (parsed.get(parse_key) or "").strip()
                if val:
                    new_data[std_key] = val
                    if std_key == "email":
                        new_data["e-mail"] = val
            new_data[PENDING_COLLECT_KEYS] = still_pending
            print(f"[LEAD] apos preenchimento new_data keys={[k for k in new_data if k != PENDING_COLLECT_KEYS]} still_pending={still_pending}", flush=True)
            if not new_data[PENDING_COLLECT_KEYS]:
                del new_data[PENDING_COLLECT_KEYS]
                print(f"[LEAD] questionario completo, indo para nos lead. new_data (sem __pending)={{(k, v) for k, v in new_data.items()}}", flush=True)
                next_id = next_node_after(current_node_id, edges)
                saved_lead = False
                while next_id:
                    next_node = node_by_id(nodes, next_id)
                    if not next_node or next_node.get("type") != "lead":
                        break
                    if not saved_lead:
                        _save_lead(cliente_id, canal, remote_id, contact_id, flow_id, new_data, next_node.get("data") or {})
                        saved_lead = True
                    next_id = next_node_after(next_id, edges)
                set_state(cliente_id, canal, remote_id, flow_id, next_id, new_data, contact_id=contact_id)
                if next_id:
                    next_node = node_by_id(nodes, next_id)
                    if next_node:
                        if next_node.get("type") == "end":
                            text = (next_node.get("data") or {}).get("text") or ""
                            if (text or "").strip():
                                if canal == "website":
                                    try:
                                        MessageService.registrar_mensagem_saida(cliente_id, remote_id, canal, text.strip(), socketio)
                                    except Exception as e:
                                        print(f"[FlowExecutor] website end: {e}", flush=True)
                                else:
                                    RoutingService.enviar_resposta(canal, instancia or "default", remote_id, text.strip(), cliente_id)
                                    if socketio:
                                        try:
                                            MessageService.registrar_mensagem_saida(cliente_id, remote_id, canal, text.strip(), socketio)
                                        except Exception:
                                            pass
                        elif next_node.get("type") != "lead":
                            ok, err = _send_node_message(cliente_id, canal, remote_id, instancia, next_node, socketio, website_room, embed_reply_store)
                            if not ok:
                                print(f"[FlowExecutor] send após coleta: {err}", flush=True)
                return True
            set_state(cliente_id, canal, remote_id, flow_id, current_node_id, new_data, contact_id=contact_id)
            return True

        current_node = node_by_id(nodes, current_node_id) if current_node_id else None
        if (
            current_node_id
            and current_node
            and (current_node.get("type") or "").strip().lower() == "questionnaire"
            and (not pending_keys or len(pending_keys) == 0)
        ):
            print(f"[LEAD] ramo questionario sem pending_keys (uma pergunta so): parsear texto e salvar lead", flush=True)
            parsed = parse_lead_from_text(texto or "")
            print(f"[LEAD] parse_lead_from_text resultado: nome={parsed.get('nome')!r} email={parsed.get('email')!r} telefone={parsed.get('telefone')!r}", flush=True)
            new_data = {k: v for k, v in (collected_data or {}).items() if k != PENDING_COLLECT_KEYS}
            for std_key, parse_key in [("nome", "nome"), ("email", "email"), ("telefone", "telefone")]:
                val = (parsed.get(parse_key) or "").strip()
                if val:
                    new_data[std_key] = val
                    if std_key == "email":
                        new_data["e-mail"] = val
            if not (new_data.get("nome") or new_data.get("email") or new_data.get("telefone")):
                new_data["campo_1"] = (texto or "").strip()
            next_id = next_node_after(current_node_id, edges)
            saved_lead = False
            while next_id:
                next_node = node_by_id(nodes, next_id)
                if not next_node or next_node.get("type") != "lead":
                    break
                if not saved_lead:
                    _save_lead(cliente_id, canal, remote_id, contact_id, flow_id, new_data, next_node.get("data") or {})
                    saved_lead = True
                next_id = next_node_after(next_id, edges)
            set_state(cliente_id, canal, remote_id, flow_id, next_id, new_data, contact_id=contact_id)
            if next_id:
                next_node = node_by_id(nodes, next_id)
                if next_node and next_node.get("type") == "end":
                    text = (next_node.get("data") or {}).get("text") or ""
                    if (text or "").strip():
                        if canal == "website":
                            try:
                                MessageService.registrar_mensagem_saida(cliente_id, remote_id, canal, text.strip(), socketio)
                            except Exception as e:
                                print(f"[FlowExecutor] website end: {e}", flush=True)
                        else:
                            RoutingService.enviar_resposta(canal, instancia or "default", remote_id, text.strip(), cliente_id)
                            if socketio:
                                try:
                                    MessageService.registrar_mensagem_saida(cliente_id, remote_id, canal, text.strip(), socketio)
                                except Exception:
                                    pass
                    set_state(cliente_id, canal, remote_id, flow_id, None, contact_id=contact_id)
                elif next_node:
                    _send_node_message(cliente_id, canal, remote_id, instancia, next_node, socketio, website_room, embed_reply_store)
            return True

        if current_node_id is None or current_node_id == "":
            print(f"[LEAD] ramo entrada sem estado (current_node vazio)", flush=True)
            entry_id = entry_node_id(nodes, edges)
            if not entry_id:
                print(f"[LEAD] entry_id nao encontrado, return False", flush=True)
                return False
            entry_node = node_by_id(nodes, entry_id)
            if not entry_node:
                return False
            if entry_node.get("type") == "start":
                next_id = None
                for e in edges:
                    if isinstance(e, dict) and e.get("source") == entry_id:
                        next_id = e.get("target")
                        break
                if next_id:
                    next_node = node_by_id(nodes, next_id)
                    print(f"[LEAD] primeiro no apos start: next_id={next_id!r} type={next_node.get('type') if next_node else None!r}", flush=True)
                    if next_node and next_node.get("type") == "end":
                        text = (next_node.get("data") or {}).get("text") or ""
                        if (text or "").strip():
                            if canal == "website":
                                try:
                                    MessageService.registrar_mensagem_saida(cliente_id, remote_id, canal, text.strip(), socketio)
                                except Exception as e:
                                    print(f"[FlowExecutor] website end node: {e}", flush=True)
                            else:
                                RoutingService.enviar_resposta(canal, instancia or "default", remote_id, text.strip(), cliente_id)
                        set_state(cliente_id, canal, remote_id, flow_id, None, contact_id=contact_id)
                    elif next_node and next_node.get("type") == "questionnaire":
                        print(f"[LEAD] primeiro no e questionario, verificando lead existente...", flush=True)
                        existing_lead = get_existing_lead_with_data(cliente_id, canal, remote_id, contact_id=contact_id)
                        if existing_lead:
                            print(f"[LEAD] lead existente com dados encontrado, pulando questionario", flush=True)
                            # Fluxos antigos podem ter múltiplos questionários em sequência (nome -> email -> telefone).
                            # Neste caso, precisamos pular TODOS os questionários consecutivos e depois os nós de lead.
                            _q_id, lead_ids, next_after_leads = get_questionnaire_lead_sequence(nodes, edges, next_id)
                            scan_id = next_id
                            while scan_id:
                                nscan = node_by_id(nodes, scan_id)
                                if not nscan or (nscan.get("type") or "").strip().lower() != "questionnaire":
                                    break
                                scan_id = next_node_after(scan_id, edges)
                            while scan_id:
                                nscan = node_by_id(nodes, scan_id)
                                if not nscan or (nscan.get("type") or "").strip().lower() != "lead":
                                    break
                                if scan_id not in lead_ids:
                                    lead_ids.append(scan_id)
                                scan_id = next_node_after(scan_id, edges)
                            next_after_leads = scan_id
                            collected_data = {
                                "nome": (existing_lead.get(LeadModel.NOME) or "").strip(),
                                "email": (existing_lead.get(LeadModel.EMAIL) or "").strip(),
                                "telefone": (existing_lead.get(LeadModel.TELEFONE) or "").strip(),
                            }
                            dados = existing_lead.get(LeadModel.DADOS)
                            if isinstance(dados, dict):
                                collected_data = {**collected_data, **dados}
                            if lead_ids:
                                ln = node_by_id(nodes, lead_ids[0])
                                if ln:
                                    _save_lead(cliente_id, canal, remote_id, contact_id, flow_id, collected_data, ln.get("data") or {})
                            set_state(cliente_id, canal, remote_id, flow_id, next_after_leads, collected_data, contact_id=contact_id)
                            if next_after_leads:
                                next_node_after_lead = node_by_id(nodes, next_after_leads)
                                if next_node_after_lead and next_node_after_lead.get("type") == "end":
                                    text = (next_node_after_lead.get("data") or {}).get("text") or ""
                                    if (text or "").strip():
                                        if canal == "website":
                                            try:
                                                MessageService.registrar_mensagem_saida(cliente_id, remote_id, canal, text.strip(), socketio)
                                            except Exception as e:
                                                print(f"[FlowExecutor] website end skip: {e}", flush=True)
                                        else:
                                            RoutingService.enviar_resposta(canal, instancia or "default", remote_id, text.strip(), cliente_id)
                                            if socketio:
                                                try:
                                                    MessageService.registrar_mensagem_saida(cliente_id, remote_id, canal, text.strip(), socketio)
                                                except Exception:
                                                    pass
                                    set_state(cliente_id, canal, remote_id, flow_id, None, contact_id=contact_id)
                                elif next_node_after_lead:
                                    _send_node_message(cliente_id, canal, remote_id, instancia, next_node_after_lead, socketio, website_room, embed_reply_store)
                        else:
                            print(f"[LEAD] sem lead existente, enviando questionario e set_state next_id={next_id!r}", flush=True)
                            ok, err = _send_node_message(cliente_id, canal, remote_id, instancia, next_node, socketio, website_room, embed_reply_store)
                            if ok:
                                set_state(cliente_id, canal, remote_id, flow_id, next_id, contact_id=contact_id)
                            else:
                                print(f"[FlowExecutor] Falha ao enviar após start: {err}", flush=True)
                    else:
                        ok, err = _send_node_message(cliente_id, canal, remote_id, instancia, next_node, socketio, website_room, embed_reply_store)
                        if ok:
                            set_state(cliente_id, canal, remote_id, flow_id, next_id, contact_id=contact_id)
                        else:
                            print(f"[FlowExecutor] Falha ao enviar após start: {err}", flush=True)
                else:
                    set_state(cliente_id, canal, remote_id, flow_id, entry_id, contact_id=contact_id)
            else:
                ok, err = _send_node_message(cliente_id, canal, remote_id, instancia, entry_node, socketio, website_room, embed_reply_store)
                if not ok:
                    print(f"[FlowExecutor] Falha ao enviar nó entrada: {err}", flush=True)
                set_state(cliente_id, canal, remote_id, flow_id, entry_id, contact_id=contact_id)
            return True

        next_id = find_next_node_id(nodes, edges, current_node_id, texto or "")
        # #region agent log
        try:
            import json as _json, time as _t
            rid_last4 = "".join([c for c in str(remote_id) if c.isdigit()])[-4:] if remote_id else ""
            _p = {
                "sessionId": "3bd729",
                "runId": "pre-fix",
                "hypothesisId": "H6",
                "location": "services/flow_executor.py",
                "message": "flow_executor_next",
                "data": {
                    "canal": canal,
                    "remoteLast4": rid_last4,
                    "fromNode": current_node_id or "",
                    "nextNode": next_id or "",
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

        if next_id:
            next_node = node_by_id(nodes, next_id)
            if next_node:
                saved_lead_once = False
                while next_node and next_node.get("type") == "lead":
                    _, _, collected_data = get_state(cliente_id, canal, remote_id, contact_id=contact_id)
                    if not saved_lead_once:
                        _save_lead(
                            cliente_id, canal, remote_id, contact_id, flow_id,
                            collected_data,
                            next_node.get("data") or {},
                        )
                        saved_lead_once = True
                    next_id = next_node_after(next_id, edges)
                    next_node = node_by_id(nodes, next_id) if next_id else None

                if not next_node:
                    set_state(cliente_id, canal, remote_id, flow_id, None, contact_id=contact_id)
                    return True

                if next_node.get("type") == "action":
                    data = next_node.get("data") or {}
                    action_type = (data.get("actionType") or data.get("action_type") or "").strip().lower().replace(" ", "_")
                    ok, err = _execute_action(
                        cliente_id, canal, remote_id, contact_id, data, instancia,
                        socketio, website_room, embed_reply_store,
                    )
                    if not ok:
                        print(f"[FlowExecutor] _execute_action falhou: {err}", flush=True)
                    if action_type in ("transfer_human", "transfer_to_sector"):
                        return True
                    if action_type == "send_link":
                        # Não avançar o fluxo ainda: aguardamos o clique para concluir.
                        expected_url = (data.get("url") or "").strip()
                        next_after_id = next_node_after(next_id, edges)

                        confirm_title = (data.get("confirmTitle") or data.get("confirm_title") or "Já cliquei").strip() or "Já cliquei"
                        confirm_id = (data.get("confirmId") or data.get("confirm_id") or "send_link_confirm").strip() or "send_link_confirm"

                        updated_collected = dict(collected_data or {})
                        updated_collected["__awaiting_send_link_click"] = True
                        updated_collected["__expected_url"] = expected_url
                        updated_collected["__awaiting_send_link_next_after_id"] = next_after_id
                        updated_collected["__awaiting_send_link_tries"] = 0
                        updated_collected["__awaiting_send_link_confirm_title"] = confirm_title
                        updated_collected["__awaiting_send_link_confirm_id"] = confirm_id
                        updated_collected["__awaiting_send_link_confirm_choice"] = "1"

                        set_state(cliente_id, canal, remote_id, flow_id, next_id, updated_collected, contact_id=contact_id)
                        return True

                    next_after_id = next_node_after(next_id, edges)
                    set_state(cliente_id, canal, remote_id, flow_id, next_after_id, contact_id=contact_id)

                    # Para ações imediatas (ex.: qualificar_lead), avançar automaticamente para o próximo nó.
                    if next_after_id:
                        after_node = node_by_id(nodes, next_after_id)
                        if after_node:
                            # Se a ação leva para nós de lead, precisamos processá-los imediatamente;
                            # caso contrário, o fluxo "parece travado" (fica em lead/action sem enviar nada).
                            saved_lead_once2 = False
                            scan_id2 = next_after_id
                            scan_node2 = after_node
                            while scan_node2 and scan_node2.get("type") == "lead":
                                _, _, cdata2 = get_state(cliente_id, canal, remote_id, contact_id=contact_id)
                                if not saved_lead_once2:
                                    _save_lead(
                                        cliente_id,
                                        canal,
                                        remote_id,
                                        contact_id,
                                        flow_id,
                                        cdata2,
                                        scan_node2.get("data") or {},
                                    )
                                    saved_lead_once2 = True
                                scan_id2 = next_node_after(scan_id2, edges)
                                scan_node2 = node_by_id(nodes, scan_id2) if scan_id2 else None

                            # Se acabaram os nós, encerra estado.
                            if not scan_node2:
                                set_state(cliente_id, canal, remote_id, flow_id, None, contact_id=contact_id)
                                return True

                            # Se o próximo também for ação imediata, executa e avança 1 passo.
                            if scan_node2.get("type") == "action":
                                data2 = scan_node2.get("data") or {}
                                action_type2 = (data2.get("actionType") or data2.get("action_type") or "").strip().lower().replace(" ", "_")
                                ok_a, err_a = _execute_action(
                                    cliente_id,
                                    canal,
                                    remote_id,
                                    contact_id,
                                    data2,
                                    instancia,
                                    socketio,
                                    website_room,
                                    embed_reply_store,
                                )
                                if not ok_a:
                                    print(f"[FlowExecutor] _execute_action (after action) falhou: {err_a}", flush=True)
                                if action_type2 in ("transfer_human", "transfer_to_sector"):
                                    return True
                                next_after_id3 = next_node_after(scan_id2, edges)
                                set_state(cliente_id, canal, remote_id, flow_id, next_after_id3, contact_id=contact_id)
                                return True

                            if scan_node2.get("type") == "end":
                                text = (scan_node2.get("data") or {}).get("text") or ""
                                if (text or "").strip():
                                    if canal == "website":
                                        try:
                                            MessageService.registrar_mensagem_saida(cliente_id, remote_id, canal, text.strip(), socketio)
                                        except Exception as e:
                                            print(f"[FlowExecutor] website end after action: {e}", flush=True)
                                    else:
                                        RoutingService.enviar_resposta(canal, instancia or "default", remote_id, text.strip(), cliente_id)
                                        if socketio:
                                            try:
                                                MessageService.registrar_mensagem_saida(cliente_id, remote_id, canal, text.strip(), socketio)
                                            except Exception:
                                                pass
                                set_state(cliente_id, canal, remote_id, flow_id, None, contact_id=contact_id)
                                return True

                            ok2, err2 = _send_node_message(
                                cliente_id,
                                canal,
                                remote_id,
                                instancia,
                                scan_node2,
                                socketio,
                                website_room,
                                embed_reply_store,
                            )
                            if ok2:
                                if scan_node2.get("type") == "questionnaire":
                                    keys2 = questionnaire_collect_keys(scan_node2.get("data") or {})
                                    collect_state2 = {PENDING_COLLECT_KEYS: keys2} if keys2 else {}
                                    set_state(cliente_id, canal, remote_id, flow_id, scan_id2, collect_state2, contact_id=contact_id)
                                else:
                                    set_state(cliente_id, canal, remote_id, flow_id, scan_id2, contact_id=contact_id)
                            else:
                                print(f"[FlowExecutor] Falha ao auto-avançar após ação {next_id}: {err2}", flush=True)
                    return True

                if next_node.get("type") == "end":
                    text = (next_node.get("data") or {}).get("text") or ""
                    if (text or "").strip():
                        if canal == "website":
                            try:
                                MessageService.registrar_mensagem_saida(cliente_id, remote_id, canal, text.strip(), socketio)
                            except Exception as e:
                                print(f"[FlowExecutor] website end: {e}", flush=True)
                        else:
                            RoutingService.enviar_resposta(canal, instancia or "default", remote_id, text.strip(), cliente_id)
                            if socketio:
                                try:
                                    MessageService.registrar_mensagem_saida(cliente_id, remote_id, canal, text.strip(), socketio)
                                except Exception:
                                    pass
                    set_state(cliente_id, canal, remote_id, flow_id, None, contact_id=contact_id)
                else:
                    ok, err = _send_node_message(cliente_id, canal, remote_id, instancia, next_node, socketio, website_room, embed_reply_store)
                    if ok:
                        if next_node.get("type") == "questionnaire":
                            keys = questionnaire_collect_keys(next_node.get("data") or {})
                            collect_state = {PENDING_COLLECT_KEYS: keys} if keys else {}
                            set_state(cliente_id, canal, remote_id, flow_id, next_id, collect_state, contact_id=contact_id)
                        else:
                            set_state(cliente_id, canal, remote_id, flow_id, next_id, contact_id=contact_id)
                    else:
                        print(f"[FlowExecutor] Falha ao enviar nó {next_id}: {err}", flush=True)
                return True

        current_node = node_by_id(nodes, current_node_id)
        if current_node and ((current_node.get("data") or {}).get("buttons")):
            fallback = "Por favor, use um dos botões acima para continuar."
            if canal == "website":
                try:
                    MessageService.registrar_mensagem_saida(cliente_id, remote_id, canal, fallback, socketio)
                except Exception as e:
                    print(f"[FlowExecutor] website fallback: {e}", flush=True)
            else:
                RoutingService.enviar_resposta(canal, instancia or "default", remote_id, fallback, cliente_id)
                if socketio:
                    try:
                        MessageService.registrar_mensagem_saida(cliente_id, remote_id, canal, fallback, socketio)
                    except Exception:
                        pass
        return True
