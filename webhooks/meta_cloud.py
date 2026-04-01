# webhooks/meta_cloud.py
"""
Webhook único para a Meta (WhatsApp Cloud, Instagram, Messenger).
GET: verificação do app (hub.mode, hub.verify_token, hub.challenge).
POST: eventos de mensagens; identifica cliente por phone_number_id ou page_id.
Conforme: https://developers.facebook.com/docs/graph-api/webhooks/getting-started
          https://developers.facebook.com/docs/messenger-platform/webhooks
"""
from flask import Blueprint, request, current_app, Response
import threading
import json
import hmac
import hashlib
import requests
from database.supabase_sq import supabase
from database.models import Tables, ClienteModel
from services.message_service import MessageService
from base.config import settings

meta_bp = Blueprint("meta_cloud", __name__)

# Cache: phone_number_id -> nosso wa_id (só dígitos) para detectar echo (mensagem enviada por nós)
_our_wa_id_cache = {}
META_GRAPH_BASE = "https://graph.facebook.com/v18.0"


def _normalize_wa_id(wa_id: str) -> str:
    """Retorna só os dígitos do wa_id para comparação."""
    if not wa_id:
        return ""
    return "".join(c for c in str(wa_id) if c.isdigit())


def _get_our_wa_id(phone_number_id: str, token: str) -> str:
    """
    Obtém o número de telefone do negócio (wa_id) na Meta para detectar mensagens
    enviadas por nós (app/Web). Usado para tratar echo quando a Meta envia 'from' = nosso número.
    """
    pid = (phone_number_id or "").strip()
    if not pid or not (token or "").strip():
        return ""
    if pid in _our_wa_id_cache:
        return _our_wa_id_cache[pid]
    try:
        url = f"{META_GRAPH_BASE}/{pid}?fields=display_phone_number"
        r = requests.get(url, headers={"Authorization": f"Bearer {token}"}, timeout=10)
        if r.status_code == 200:
            data = r.json()
            display = (data.get("display_phone_number") or "").strip()
            our_id = _normalize_wa_id(display)
            if our_id:
                _our_wa_id_cache[pid] = our_id
                return our_id
    except Exception as e:
        current_app.logger.warning("Meta: falha ao obter display_phone_number: %s", e)
    return ""


@meta_bp.route("/meta", methods=["GET"])
@meta_bp.route("/meta/", methods=["GET"])
def meta_verify():
    """Verificação do webhook pela Meta (hub.verify_token deve bater com META_VERIFY_TOKEN)."""
    mode = (request.args.get("hub.mode") or "").strip()
    token = (request.args.get("hub.verify_token") or "").strip().replace("\r", "").replace("\n", "")
    # Meta envia hub.challenge; garantir que pegamos como string
    challenge = request.args.get("hub.challenge")
    if challenge is not None:
        challenge = str(challenge).strip()
    else:
        challenge = ""
    expected = (settings.META_VERIFY_TOKEN or "").strip().replace("\r", "").replace("\n", "")
    # Log sem expor tokens (nunca logar token/expected em produção)
    try:
        current_app.logger.info(
            "Meta verify: mode=%s token_len=%d expected_ok=%s challenge_len=%d",
            mode, len(token), bool(expected), len(challenge),
        )
    except Exception:
        pass
    if mode != "subscribe" or not expected or token != expected or not challenge:
        return Response("Forbidden", status=403, mimetype="text/plain")
    # Resposta exata: só o valor do challenge, 200, text/plain (sem BOM, sem charset extra)
    resp = Response(challenge, status=200)
    resp.headers["Content-Type"] = "text/plain"
    return resp


def _find_cliente_by_phone_number_id(phone_number_id: str):
    """Retorna cliente_id e dados do cliente pelo meta_wa_phone_number_id."""
    pid = (str(phone_number_id).strip() if phone_number_id is not None else "") or None
    if not pid:
        return None, None
    r = supabase.table(Tables.CLIENTES).select("id, meta_wa_token").eq(
        ClienteModel.META_WA_PHONE_NUMBER_ID, pid
    ).execute()
    if r.data and len(r.data) > 0:
        return r.data[0]["id"], r.data[0]
    return None, None


def _find_cliente_by_page_id(page_id: str, canal: str):
    """Retorna cliente_id e dados. Instagram: webhook envia entry.id = Instagram Business Account ID (meta_ig_account_id)."""
    pid = (str(page_id).strip() if page_id is not None else "") or None
    if not pid:
        return None, None
    if canal == "instagram":
        # Webhook Instagram envia entry.id = Instagram Business Account ID (não Page ID)
        r = supabase.table(Tables.CLIENTES).select(
            f"id, {ClienteModel.META_IG_TOKEN}"
        ).eq(ClienteModel.META_IG_ACCOUNT_ID, pid).execute()
        if r.data and len(r.data) > 0:
            print(f"📋 Instagram: cliente encontrado por meta_ig_account_id={pid!r}", flush=True)
            return r.data[0]["id"], r.data[0]
        r = supabase.table(Tables.CLIENTES).select(
            f"id, {ClienteModel.META_IG_TOKEN}"
        ).eq(ClienteModel.META_IG_PAGE_ID, pid).execute()
        if r.data and len(r.data) > 0:
            print(f"📋 Instagram: cliente encontrado por meta_ig_page_id={pid!r}", flush=True)
            return r.data[0]["id"], r.data[0]
        print(f"📋 Instagram: nenhum cliente com meta_ig_account_id nem meta_ig_page_id = {pid!r}", flush=True)
        return None, None
    col = ClienteModel.META_FB_PAGE_ID
    token_col = ClienteModel.META_FB_TOKEN
    r = supabase.table(Tables.CLIENTES).select(f"id, {token_col}").eq(col, pid).execute()
    if r.data and len(r.data) > 0:
        return r.data[0]["id"], r.data[0]
    return None, None


def _extract_text_from_wa_message(msg: dict) -> str:
    """Extrai texto de uma mensagem WhatsApp Cloud (pode ser text, button, etc.)."""
    if not msg:
        return ""
    if "text" in msg:
        return (msg["text"] or {}).get("body", "")
    if "button" in msg:
        return (msg["button"] or {}).get("text", "")
    if "interactive" in msg:
        it = msg["interactive"] or {}
        if it.get("type") == "button_reply":
            return (it.get("button_reply") or {}).get("title", "")
        if it.get("type") == "list_reply":
            return (it.get("list_reply") or {}).get("title", "")
    return ""


def _process_whatsapp_entry(entry: dict) -> None:
    """
    Processa um entry do objeto whatsapp_business_account.
    Inclui mensagens enviadas pelo negócio (celular/WhatsApp Web): echo ou from=nosso número.
    """
    for change in entry.get("changes", []):
        val = change.get("value") or {}
        meta = val.get("metadata") or {}
        phone_number_id = meta.get("phone_number_id")
        if phone_number_id is not None:
            phone_number_id = str(phone_number_id).strip() or None
        messages = val.get("messages") or []
        print(f"📋 Meta WA: phone_number_id={phone_number_id!r} | messages count={len(messages)}", flush=True)
        cliente_id, cliente_row = _find_cliente_by_phone_number_id(phone_number_id)
        if not cliente_id:
            print(f"📌 Meta WA: Nenhum cliente com phone_number_id={phone_number_id}", flush=True)
            continue
        # Número do negócio (wa_id) para detectar mensagens enviadas por nós (app/Web)
        our_wa_id = _get_our_wa_id(phone_number_id, (cliente_row or {}).get("meta_wa_token") or "")
        contacts_list = val.get("contacts") or []
        contacts_by_wa = { c.get("wa_id"): (c.get("profile") or {}).get("name") for c in contacts_list if c.get("wa_id") }
        for msg in messages:
            # Mensagem enviada pelo negócio (app/WhatsApp Web): Meta pode enviar "to" (destinatário)
            # ou "from" = nosso número (echo). O destinatário (cliente) está sempre em "to".
            msg_from_norm = _normalize_wa_id(msg.get("from") or "")
            has_to = bool(msg.get("to"))
            is_echo = has_to or (bool(our_wa_id) and msg_from_norm == our_wa_id)
            if is_echo:
                remote_id = (msg.get("to") or "").strip()
                remote_id = _normalize_wa_id(remote_id) or remote_id
                if not remote_id:
                    # Echo sem "to" não dá para saber o cliente; ignora
                    continue
                texto = _extract_text_from_wa_message(msg)
                if not texto:
                    texto = "[mídia]"  # echo pode ser imagem/áudio sem texto
                print(f"✅ Meta WA: echo (enviada por nós – app/Web) to={remote_id} texto_len={len(texto)} -> cliente_id={cliente_id}", flush=True)
                app_obj = current_app._get_current_object()
                def _run_echo(rid, txt):
                    with app_obj.app_context():
                        socketio_ref = app_obj.extensions.get("socketio")
                        MessageService.registrar_mensagem_saida(
                            cliente_id, rid, "whatsapp", txt, socketio_ref
                        )
                threading.Thread(target=_run_echo, args=(remote_id, texto), daemon=True).start()
                continue

            if msg.get("from") and not str(msg.get("from", "")).endswith("@s.whatsapp.net"):
                remote_id = msg["from"]  # wa_id numérico
            else:
                remote_id = msg.get("from", "")
            push_name = contacts_by_wa.get(remote_id) or (msg.get("profile") or {}).get("name")
            texto = _extract_text_from_wa_message(msg)
            if not texto:
                print(f"📋 Meta WA: mensagem sem texto (type={msg.get('type')}, keys={list(msg.keys())})")
                continue
            print(f"✅ Meta WA: processando remote_id={remote_id} texto_len={len(texto)} -> cliente_id={cliente_id}", flush=True)
            app_obj = current_app._get_current_object()
            def _run_wa():
                with app_obj.app_context():
                    socketio_ref = app_obj.extensions.get("socketio")
                    MessageService.processar_mensagem_entrada(
                        "whatsapp", remote_id, texto, cliente_id, None, socketio_ref,
                        push_name=push_name
                    )
            threading.Thread(target=_run_wa, daemon=True).start()


def _process_messaging_entry(entry: dict, object_type: str) -> None:
    """Processa entry de Instagram (object=instagram) ou Page (object=page) com messaging."""
    raw_id = entry.get("id")
    page_id = str(raw_id).strip() if raw_id is not None else None
    canal = "instagram" if object_type == "instagram" else "facebook"
    messaging_list = entry.get("messaging") or []
    print(f"📋 Meta {canal}: entry.id={page_id!r} | messaging count={len(messaging_list)}", flush=True)
    cliente_id, _ = _find_cliente_by_page_id(page_id, canal)
    if not cliente_id:
        print(f"📌 Meta {canal}: Nenhum cliente com entry.id={page_id!r} (Instagram: confira meta_ig_account_id no banco e reconecte em Conexões)", flush=True)
        return
    print(f"📋 Meta {canal}: cliente_id={cliente_id} encontrado, processando {len(messaging_list)} evento(s)", flush=True)
    for ev in messaging_list:
        ev_keys = list(ev.keys()) if ev else []
        sender = (ev.get("sender") or {}).get("id")
        # message: envio normal | message_edit: edição de mensagem (Instagram; texto em message_edit.text)
        msg = ev.get("message") or {}
        msg_edit = ev.get("message_edit") or {}
        # Debug: ver payload que a Meta envia (útil quando mensagem não aparece no chat)
        if object_type == "instagram" and (ev_keys or msg or msg_edit):
            msg_keys = list(msg.keys()) if msg else []
            print(f"📋 Meta instagram: ev_keys={ev_keys} sender={sender!r} msg_keys={msg_keys} msg.text={msg.get('text')!r}", flush=True)
        if msg_edit:
            texto = (msg_edit.get("text") or (msg_edit.get("message") or {}).get("text") or "")
            if isinstance(texto, dict):
                texto = (texto.get("body") or texto.get("text") or "").strip()
            else:
                texto = (texto or "").strip()
        else:
            text_obj = msg.get("text")
            texto = (text_obj.get("text") or text_obj.get("body") or "") if isinstance(text_obj, dict) else (text_obj or "")
            texto = (texto or "").strip()
        if not sender or not texto:
            # Pode ser delivery, read, reaction, ou message_edit sem sender no payload
            if msg_edit and texto and not sender:
                print(f"📋 Meta {canal}: message_edit com texto mas sender ausente no payload (ev_keys={ev_keys}); ignorando.", flush=True)
            else:
                print(f"📋 Meta {canal}: evento ignorado (sem texto ou sender) ev_keys={ev_keys} sender={sender!r} msg_keys={list(msg.keys()) if msg else []}", flush=True)
            continue
        print(f"✅ Meta {canal}: processando de sender={sender} texto_len={len(texto)} -> cliente_id={cliente_id}", flush=True)
        app_obj = current_app._get_current_object()
        def _run_messaging():
            try:
                print(f"📩 Thread iniciada: canal={canal} sender={sender} -> processar_mensagem_entrada", flush=True)
                with app_obj.app_context():
                    socketio_ref = app_obj.extensions.get("socketio")
                    MessageService.processar_mensagem_entrada(
                        canal, sender, texto, cliente_id, None, socketio_ref
                    )
            except Exception as e:
                print(f"❌ Erro na thread de mensagem {canal}: {e}", flush=True)
        threading.Thread(target=_run_messaging, daemon=True).start()


def _verify_meta_signature(raw_body: bytes, signature_header: str) -> bool:
    """
    Valida X-Hub-Signature-256 (recomendado pela Meta).
    Meta: HMAC SHA256 do body com App Secret; header: sha256=<hex>.
    Usa META_WEBHOOK_APP_SECRET se definido (app que envia o webhook), senão META_APP_SECRET.
    """
    webhook_secret = (getattr(settings, "META_WEBHOOK_APP_SECRET", None) or "").strip()
    app_secret = (getattr(settings, "META_APP_SECRET", None) or "").strip()
    secret_to_use = webhook_secret or app_secret
    if not raw_body or not signature_header or not secret_to_use:
        # Em produção, podemos exigir assinatura válida (hardening).
        if getattr(settings, "REQUIRE_WEBHOOK_SIGNATURES", False):
            return False
        return True  # ambiente permissivo (dev)
    secret = secret_to_use.encode("utf-8")
    expected = "sha256=" + hmac.new(secret, raw_body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, (signature_header or "").strip())


@meta_bp.route("/meta", methods=["POST"])
def meta_webhook():
    """Recebe eventos da Meta (mensagens WhatsApp Cloud, Instagram, Messenger)."""
    print("Meta webhook POST recebido (qualquer object)", flush=True)
    raw_body = request.get_data()
    sig = request.headers.get("X-Hub-Signature-256") or request.headers.get("x-hub-signature-256") or ""
    sig_ok = _verify_meta_signature(raw_body, sig)
    if not sig_ok:
        if getattr(settings, "REQUIRE_WEBHOOK_SIGNATURES", False):
            return Response("Forbidden", status=403, mimetype="text/plain")
        if sig:
            # Ambiente permissivo: loga e segue
            print("⚠️ Meta webhook: assinatura X-Hub-Signature-256 inválida (processando mesmo assim)", flush=True)
    try:
        data = json.loads(raw_body.decode("utf-8")) if raw_body else {}
    except Exception:
        data = {}
    obj = (data.get("object") or "").strip()
    entries = data.get("entry") or []
    n_entries = len(entries)
    # Log único para grep: object=whatsapp_business_account|instagram|page
    print(f"Meta webhook POST object={obj} entries={n_entries}", flush=True)
    entry_ids = [str(e.get("id", "")).strip() for e in entries if e.get("id") is not None]
    if entry_ids:
        print(f"📥 Meta webhook entry_ids={entry_ids}", flush=True)
    if not obj or not entries:
        print("📥 Meta: sem object ou entry, ignorando", flush=True)
        return "", 200

    # Debug Instagram: ver payload bruto que a Meta envia (útil para "Teste" no painel ou mensagem real)
    if obj == "instagram" and entries:
        try:
            first_entry = entries[0]
            messaging = first_entry.get("messaging") or []
            raw_snippet = json.dumps(messaging, ensure_ascii=False)[:2000]
            print(f"📥 Meta instagram payload (messaging): {raw_snippet}{'...' if len(json.dumps(messaging)) > 2000 else ''}", flush=True)
        except Exception:
            pass

    # Meta envia entrada em request.json
    for entry in data.get("entry", []):
        try:
            if obj == "whatsapp_business_account":
                _process_whatsapp_entry(entry)
            elif obj == "instagram":
                _process_messaging_entry(entry, "instagram")
            elif obj == "page":
                _process_messaging_entry(entry, "facebook")
            else:
                print(f"📥 Meta: object={obj!r} não tratado, ignorando entry")
        except Exception as e:
            print(f"❌ Erro ao processar entry Meta: {e}")

    return "", 200
