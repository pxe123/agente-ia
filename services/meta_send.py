# services/meta_send.py
"""
Envio de mensagens via API oficial da Meta:
- WhatsApp Cloud API
- Instagram Messaging API
- Facebook Messenger API
"""
import requests

META_GRAPH_BASE = "https://graph.facebook.com/v18.0"


def send_whatsapp_cloud(phone_number_id: str, token: str, to_wa_id: str, text: str) -> tuple[bool, str | None]:
    """
    Envia mensagem de texto via WhatsApp Cloud API.
    to_wa_id: número em E.164 sem + (ex: 5511999999999).
    Retorna (True, None) em sucesso ou (False, mensagem_erro) em falha.
    """
    phone_number_id = (phone_number_id or "").strip()
    token = (token or "").strip()
    # Meta exige só dígitos no "to" (E.164 sem + nem espaços)
    to_raw = (to_wa_id or "").replace("+", "").replace("@s.whatsapp.net", "").strip()
    to_clean = "".join(c for c in to_raw if c.isdigit()) or to_raw
    if not to_clean:
        return (False, "Número do destinatário inválido (vazio).")
    url = f"{META_GRAPH_BASE}/{phone_number_id}/messages"
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    payload = {
        "messaging_product": "whatsapp",
        "recipient_type": "individual",
        "to": to_clean,
        "type": "text",
        "text": {"body": text},
    }
    print(f"[MetaSend] WhatsApp: enviando para to=…{to_clean[-4:]} texto_len={len(text)}", flush=True)
    try:
        r = requests.post(url, json=payload, headers=headers, timeout=30)
        if r.status_code in (200, 201):
            try:
                j = r.json()
                msg_id = (j.get("messages") or [{}])[0].get("id") if isinstance(j.get("messages"), list) else None
                print(f"[MetaSend] WhatsApp: enviado para …{to_clean[-4:]} id={msg_id[:40] if msg_id else '?'}…", flush=True)
                if not msg_id:
                    print(f"[MetaSend] Resposta Meta (body): {str(j)[:200]}", flush=True)
            except Exception as e:
                print(f"[MetaSend] WhatsApp: resposta {r.status_code} para …{to_clean[-4:]}. Parse: {e}", flush=True)
            return (True, None)
        msg = r.text[:500]
        try:
            j = r.json()
            err = j.get("error", {})
            msg = err.get("message", msg)
            if err.get("code"):
                msg = f"[{err['code']}] {msg}"
        except Exception:
            pass
        print(f"[MetaSend] Erro WhatsApp Cloud {r.status_code}: {msg}", flush=True)
        return (False, msg or "Erro ao enviar pela API Meta.")
    except Exception as e:
        print(f"[MetaSend] Exceção WhatsApp Cloud: {e}", flush=True)
        return (False, str(e))


def send_whatsapp_cloud_interactive_buttons(
    phone_number_id: str, token: str, to_wa_id: str, body_text: str, buttons: list[dict]
) -> tuple[bool, str | None]:
    """
    Envia mensagem interativa com botões (Reply Buttons) via WhatsApp Cloud API.
    buttons: lista de até 3 itens [ {"id": "btn_1", "title": "Sim"}, ... ].
    title: até 20 caracteres; id: até 256 (usado no webhook em interactive.button_reply).
    Retorna (True, None) em sucesso ou (False, mensagem_erro).
    """
    phone_number_id = (phone_number_id or "").strip()
    token = (token or "").strip()
    to_raw = (to_wa_id or "").replace("+", "").replace("@s.whatsapp.net", "").strip()
    to_clean = "".join(c for c in to_raw if c.isdigit()) or to_raw
    if not to_clean:
        return (False, "Número do destinatário inválido (vazio).")
    # Máximo 3 botões; title até 20 chars
    action_buttons = []
    for b in (buttons or [])[:3]:
        bid = (b.get("id") or str(b.get("title", "")) or "").strip()[:256]
        title = (b.get("title") or b.get("label") or str(bid))[:20]
        if not title:
            continue
        if not bid:
            bid = title
        action_buttons.append({"type": "reply", "reply": {"id": bid, "title": title}})
    if not action_buttons:
        return send_whatsapp_cloud(phone_number_id, token, to_wa_id, body_text or " ")
    url = f"{META_GRAPH_BASE}/{phone_number_id}/messages"
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    payload = {
        "messaging_product": "whatsapp",
        "recipient_type": "individual",
        "to": to_clean,
        "type": "interactive",
        "interactive": {
            "type": "button",
            "body": {"text": (body_text or " ").strip()[:1024]},
            "action": {"buttons": action_buttons},
        },
    }
    print(f"[MetaSend] WhatsApp interactive: to=…{to_clean[-4:]} buttons={len(action_buttons)}", flush=True)
    try:
        r = requests.post(url, json=payload, headers=headers, timeout=30)
        if r.status_code in (200, 201):
            print(f"[MetaSend] WhatsApp interactive: enviado.", flush=True)
            return (True, None)
        msg = r.text[:500]
        try:
            j = r.json()
            err = j.get("error", {})
            msg = err.get("message", msg)
            if err.get("code"):
                msg = f"[{err['code']}] {msg}"
        except Exception:
            pass
        print(f"[MetaSend] Erro WhatsApp Cloud interactive {r.status_code}: {msg}", flush=True)
        return (False, msg or "Erro ao enviar interactive.")
    except Exception as e:
        print(f"[MetaSend] Exceção WhatsApp Cloud interactive: {e}", flush=True)
        return (False, str(e))


def send_instagram(ig_page_id: str, token: str, ig_psid: str, text: str) -> tuple[bool, str | None]:
    """
    Envia mensagem de texto via Instagram Messaging API.
    ig_page_id: Facebook Page ID vinculado ao Instagram (não o Instagram Business Account ID).
    ig_psid: Page-Scoped ID do usuário no Instagram (sender id do webhook).
    Retorna (True, None) em sucesso ou (False, mensagem_erro).
    """
    url = f"{META_GRAPH_BASE}/{ig_page_id}/messages"
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    payload = {
        "recipient": {"id": ig_psid},
        "message": {"text": text},
    }
    print(f"[MetaSend] Instagram: enviando page_id={ig_page_id} psid={ig_psid} text_len={len(text)}", flush=True)
    try:
        r = requests.post(url, json=payload, headers=headers, timeout=30)
        if r.status_code in (200, 201):
            print(f"[MetaSend] Instagram: enviado com sucesso.", flush=True)
            return (True, None)
        err_msg = r.text[:500]
        try:
            j = r.json()
            err_msg = (j.get("error") or {}).get("message", err_msg)
            if (j.get("error") or {}).get("code"):
                err_msg = f"[{j['error']['code']}] {err_msg}"
        except Exception:
            pass
        print(f"[MetaSend] Instagram: falha status={r.status_code} body={err_msg}", flush=True)
        return (False, f"Instagram API: {err_msg}")
    except Exception as e:
        print(f"[MetaSend] Exceção Instagram: {e}", flush=True)
        return (False, str(e))


def send_messenger(page_id: str, token: str, psid: str, text: str) -> bool:
    """
    Envia mensagem de texto via Facebook Messenger API.
    psid: Page-Scoped ID do usuário no Messenger.
    """
    url = f"{META_GRAPH_BASE}/{page_id}/messages"
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    payload = {
        "recipient": {"id": psid},
        "message": {"text": text},
    }
    print(f"[MetaSend] Messenger: enviando page_id={page_id} psid={psid} text_len={len(text)}", flush=True)
    try:
        r = requests.post(url, json=payload, headers=headers, timeout=30)
        if r.status_code in (200, 201):
            print(f"[MetaSend] Messenger: enviado com sucesso.", flush=True)
            return True
        err_body = r.text[:500] if r.text else ""
        print(f"[MetaSend] Messenger: falha status={r.status_code} body={err_body}", flush=True)
        return False
    except Exception as e:
        print(f"[MetaSend] Messenger: exceção {e}", flush=True)
        return False
