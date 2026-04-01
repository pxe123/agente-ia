# panel/routes/meta_oauth.py
"""
OAuth Meta: fluxos separados por canal (WhatsApp, Instagram, Messenger).
Cada canal tem seu próprio botão de login e callback salva apenas os dados daquele canal.

Rotas:
  GET /meta/connect/whatsapp  → login Meta (escopos WhatsApp)
  GET /meta/connect/instagram → login Meta (escopos Instagram)
  GET /meta/connect/messenger → login Meta (escopos Messenger)
  GET /meta/oauth/callback?code=xxx&state=xxx → state contém canal (wa|ig|fb)
"""
import os
import sys
import hmac
import hashlib
import base64
import json
import secrets
import urllib.parse
import requests
from flask import Blueprint, redirect, request, url_for, current_app, jsonify
from flask_login import login_required, current_user

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../..")))

from base.config import settings
from base.auth import get_current_cliente_id
from database.supabase_sq import supabase
from database.models import Tables, ClienteModel
from services.app_settings import get_global_channel_flags
from services.entitlements import can_use_channel

META_GRAPH = "https://graph.facebook.com/v18.0"
META_OAUTH_DIALOG = "https://www.facebook.com/v18.0/dialog/oauth"

# Escopos por canal (cada login pede só o necessário)
SCOPES_WHATSAPP = (
    "business_management,"
    "whatsapp_business_management,"
    "whatsapp_business_messaging"
)
# business_management: necessário para /me/accounts listar páginas vinculadas ao Business Suite (Meta mudou isso; sem esse escopo a lista vem vazia)
# Ref: https://developers.facebook.com/community/threads/1101493734381397/ e docs Meta
SCOPES_INSTAGRAM = (
    "business_management,"
    "pages_show_list,"
    "instagram_basic,"
    "instagram_manage_messages"
)
SCOPES_MESSENGER = (
    "business_management,"
    "pages_show_list,"
    "pages_manage_metadata,"
    "pages_messaging,"
    "pages_read_engagement"
)

CHANNELS = ("wa", "ig", "fb")


def _sign_state(cliente_id: str, channel: str) -> str:
    """Gera state assinado: base64(cliente_id|channel).signature"""
    if channel not in CHANNELS:
        channel = "wa"
    raw = f"{cliente_id}|{channel}"
    sig = hmac.new(
        (settings.SECRET_KEY or "default").encode(),
        raw.encode(),
        hashlib.sha256
    ).hexdigest()[:16]
    b64 = base64.urlsafe_b64encode(raw.encode()).decode().rstrip("=")
    return f"{b64}.{sig}"


def _verify_state(state: str):
    """Valida state e retorna (cliente_id, channel) ou (None, None)."""
    if not state or "." not in state:
        return None, None
    b64, sig = state.split(".", 1)
    try:
        raw = base64.urlsafe_b64decode(b64 + "==").decode()
    except Exception:
        return None, None
    expected = hmac.new(
        (settings.SECRET_KEY or "default").encode(),
        raw.encode(),
        hashlib.sha256
    ).hexdigest()[:16]
    if not hmac.compare_digest(sig, expected):
        return None, None
    parts = raw.split("|", 1)
    cliente_id = parts[0] if parts else None
    channel = parts[1] if len(parts) > 1 else "wa"
    if channel not in CHANNELS:
        channel = "wa"
    return cliente_id, channel


def _app_config():
    app_id = getattr(settings, "META_APP_ID", None) or os.getenv("META_APP_ID", "")
    app_secret = getattr(settings, "META_APP_SECRET", None) or os.getenv("META_APP_SECRET", "")
    redirect_uri = getattr(settings, "META_OAUTH_REDIRECT_URI", None) or os.getenv("META_OAUTH_REDIRECT_URI", "")
    if not redirect_uri:
        redirect_uri = request.url_root.rstrip("/") + "/meta/oauth/callback"
    return app_id.strip(), app_secret.strip(), redirect_uri


meta_oauth_bp = Blueprint("meta_oauth", __name__)


def _redirect_connect(channel: str):
    """Redireciona para o diálogo OAuth da Meta com o canal no state."""
    app_id, app_secret, redirect_uri = _app_config()
    if not app_id:
        return redirect(url_for("customer.conexoes", meta_error="META_APP_ID não configurado no servidor"))
    if channel == "wa":
        scope = SCOPES_WHATSAPP
    elif channel == "ig":
        scope = SCOPES_INSTAGRAM
    elif channel == "fb":
        scope = SCOPES_MESSENGER
    else:
        scope = SCOPES_WHATSAPP
    state = _sign_state(str(get_current_cliente_id(current_user)), channel)
    params = {
        "client_id": app_id,
        "redirect_uri": redirect_uri,
        "state": state,
        "scope": scope,
        "response_type": "code",
    }
    url = META_OAUTH_DIALOG + "?" + urllib.parse.urlencode(params)
    print(f"[OAuth] Redirecionando para Meta: canal={channel} redirect_uri={redirect_uri} state_len={len(state)}", flush=True)
    return redirect(url)


@meta_oauth_bp.route("/connect")
@meta_oauth_bp.route("/connect/whatsapp")
@login_required
def meta_connect_whatsapp():
    """Login Meta só para WhatsApp."""
    cid = str(get_current_cliente_id(current_user) or "")
    if cid and not can_use_channel(cid, "whatsapp"):
        return redirect(url_for("customer.conexoes", meta_error="WhatsApp está temporariamente indisponível na plataforma."))
    return _redirect_connect("wa")


@meta_oauth_bp.route("/connect/instagram")
@login_required
def meta_connect_instagram():
    """Login Meta só para Instagram Direct."""
    flags = get_global_channel_flags()
    if not flags.get("instagram_enabled", True):
        return redirect(url_for("customer.conexoes", meta_error="Instagram está temporariamente indisponível na plataforma."))
    return _redirect_connect("ig")


@meta_oauth_bp.route("/connect/messenger")
@login_required
def meta_connect_messenger():
    """Login Meta só para Facebook Messenger."""
    flags = get_global_channel_flags()
    if not flags.get("messenger_enabled", True):
        return redirect(url_for("customer.conexoes", meta_error="Messenger está temporariamente indisponível na plataforma."))
    return _redirect_connect("fb")


@meta_oauth_bp.route("/oauth/callback")
@login_required
def meta_oauth_callback():
    """
    Callback único. Lê o canal no state e executa apenas o fluxo daquele canal:
    wa → salva meta_wa_*; ig → meta_ig_*; fb → meta_fb_*.
    """
    args_keys = list(request.args.keys())
    print(f"[OAuth] Callback recebido: args={args_keys}", flush=True)

    # Se a Meta redirecionou com erro (ex.: redirect_uri_mismatch, access_denied), exibir mensagem clara
    error = request.args.get("error")
    if error:
        reason = request.args.get("error_reason", "")
        desc = request.args.get("error_description", "")
        if error == "redirect_uri_mismatch":
            msg = "URI de redirecionamento não confere. No app Meta (Facebook Login > Configurações), em \"URIs de redirecionamento OAuth válidos\", adicione exatamente: " + (getattr(settings, "META_OAUTH_REDIRECT_URI", None) or os.getenv("META_OAUTH_REDIRECT_URI", ""))
        elif error == "access_denied":
            msg = "Você cancelou ou negou a permissão. Tente conectar de novo e aceite todas as permissões."
        else:
            msg = f"A Meta retornou: {error}. {reason} {desc}".strip()
        print(f"[OAuth] Meta retornou erro: error={error} reason={reason} desc={desc[:80] if desc else ''}", flush=True)
        return redirect(url_for("customer.conexoes", meta_error=msg))

    code = request.args.get("code")
    state = request.args.get("state")
    if not code or not state:
        print(f"[OAuth] Callback sem code ou state: code={bool(code)} state={bool(state)}", flush=True)
        return redirect(url_for("customer.conexoes", meta_error="Faltou code ou state no retorno da Meta. Confira se a URI de redirecionamento no app Meta está exatamente igual ao META_OAUTH_REDIRECT_URI do .env."))
    cliente_id, channel = _verify_state(state)
    if not cliente_id:
        print(f"[OAuth] State inválido ou não verificado", flush=True)
        return redirect(url_for("customer.conexoes", meta_error="State inválido. Tente conectar de novo."))
    cid = get_current_cliente_id(current_user)
    if str(cid) != str(cliente_id):
        print(f"[OAuth] Sessão não confere: current_cliente_id={cid} state_cliente_id={cliente_id}", flush=True)
        return redirect(url_for("customer.conexoes", meta_error="Sessão inválida. Faça login de novo e tente conectar."))

    print(f"[OAuth] State OK: cliente_id={cliente_id} channel={channel}", flush=True)
    flags = get_global_channel_flags()
    if channel == "ig" and not flags.get("instagram_enabled", True):
        return redirect(url_for("customer.conexoes", meta_error="Instagram está temporariamente indisponível na plataforma."))
    if channel == "fb" and not flags.get("messenger_enabled", True):
        return redirect(url_for("customer.conexoes", meta_error="Messenger está temporariamente indisponível na plataforma."))
    if channel == "wa" and not can_use_channel(str(cliente_id), "whatsapp"):
        return redirect(url_for("customer.conexoes", meta_error="WhatsApp está temporariamente indisponível na plataforma."))

    app_id, app_secret, redirect_uri = _app_config()
    if not app_id or not app_secret:
        return redirect(url_for("customer.conexoes", meta_error="META_APP_ID ou META_APP_SECRET não configurados"))

    # 1) Trocar code por access_token
    token_url = f"{META_GRAPH}/oauth/access_token"
    token_params = {
        "client_id": app_id,
        "client_secret": app_secret,
        "redirect_uri": redirect_uri,
        "code": code,
    }
    try:
        r = requests.get(token_url, params=token_params, timeout=15)
        print(f"[OAuth] Troca code por token: status={r.status_code}", flush=True)
        r.raise_for_status()
        data = r.json()
        access_token = data.get("access_token")
        if not access_token:
            print(f"[OAuth] Resposta Meta sem access_token: keys={list(data.keys()) if isinstance(data, dict) else 'n/a'}", flush=True)
            return redirect(url_for("customer.conexoes", meta_error="Meta não retornou access_token"))
    except Exception as e:
        print(f"[OAuth] Erro ao trocar code: {e}", flush=True)
        return redirect(url_for("customer.conexoes", meta_error=f"Erro ao trocar code: {e}"))

    # 2) Long-lived token (60 dias)
    try:
        ll_params = {
            "grant_type": "fb_exchange_token",
            "client_id": app_id,
            "client_secret": app_secret,
            "fb_exchange_token": access_token,
        }
        r2 = requests.get(f"{META_GRAPH}/oauth/access_token", params=ll_params, timeout=15)
        if r2.status_code == 200:
            ll_data = r2.json() or {}
            if ll_data.get("access_token") and "error" not in ll_data:
                access_token = ll_data["access_token"]
    except Exception:
        pass

    headers = {"Authorization": f"Bearer {access_token}"}
    print(f"[OAuth] Chamando callback do canal: {channel}", flush=True)

    if channel == "wa":
        return _callback_whatsapp(cliente_id, access_token, headers)
    if channel == "ig":
        return _callback_instagram(cliente_id, access_token, headers)
    if channel == "fb":
        return _callback_messenger(cliente_id, access_token, headers)
    print(f"[OAuth] Canal não reconhecido: {channel}", flush=True)
    return redirect(url_for("customer.conexoes", meta_error="Canal inválido"))


def _callback_whatsapp(cliente_id, access_token, headers):
    """Salva apenas meta_wa_* e inscreve webhook."""
    try:
        biz_r = requests.get(f"{META_GRAPH}/me/businesses", headers=headers, timeout=15)
        biz_r.raise_for_status()
        businesses = (biz_r.json() or {}).get("data") or []
    except Exception as e:
        return redirect(url_for("customer.conexoes", meta_error=f"Erro ao listar negócios: {e}"))

    waba_id = None
    phone_number_id = None
    for biz in businesses:
        bid = biz.get("id")
        if not bid:
            continue
        try:
            wa_r = requests.get(
                f"{META_GRAPH}/{bid}/owned_whatsapp_business_accounts",
                headers=headers, timeout=15,
            )
            if wa_r.status_code != 200:
                continue
            waba_list = (wa_r.json() or {}).get("data") or []
            for waba in waba_list:
                waba_id = waba.get("id")
                if not waba_id:
                    continue
                ph_r = requests.get(
                    f"{META_GRAPH}/{waba_id}/phone_numbers",
                    headers=headers, timeout=15,
                )
                if ph_r.status_code != 200:
                    continue
                phones = (ph_r.json() or {}).get("data") or []
                if phones:
                    phone_number_id = phones[0].get("id")
                    break
            if phone_number_id:
                break
        except Exception:
            continue

    if not waba_id or not phone_number_id:
        return redirect(url_for("customer.conexoes", meta_error="Nenhuma conta WhatsApp Business encontrada. Vincule um número no Meta Business Suite."))

    payload = {
        ClienteModel.META_WA_PHONE_NUMBER_ID: phone_number_id,
        ClienteModel.META_WA_TOKEN: access_token,
        ClienteModel.META_WA_WABA_ID: waba_id,
    }
    try:
        supabase.table(Tables.CLIENTES).update(payload).eq("id", cliente_id).execute()
    except Exception as e:
        return redirect(url_for("customer.conexoes", meta_error=f"Erro ao salvar no banco: {e}"))

    try:
        sub_url = f"{META_GRAPH}/{waba_id}/subscribed_apps"
        requests.post(sub_url, json={"object": "whatsapp_business_account"}, headers=headers, timeout=10)
    except Exception:
        pass

    return redirect(url_for("customer.conexoes", meta_connected="wa"))


def _callback_instagram(cliente_id, access_token, headers):
    """Salva apenas meta_ig_* (Instagram vinculado a uma Página)."""
    try:
        acc_r = requests.get(
            f"{META_GRAPH}/me/accounts",
            params={"fields": "id,name,access_token,instagram_business_account{id}"},
            headers=headers,
            timeout=15,
        )
        if acc_r.status_code != 200:
            return redirect(url_for("customer.conexoes", meta_error="Não foi possível listar páginas. Verifique se o app tem o produto Instagram e as permissões corretas."))
        pages = (acc_r.json() or {}).get("data") or []
    except Exception as e:
        return redirect(url_for("customer.conexoes", meta_error=f"Erro ao buscar páginas: {e}"))

    # Preferir página que tenha Instagram vinculado.
    # Para ENVIAR: API exige Facebook Page ID em /PAGE-ID/messages → meta_ig_page_id.
    # Para RECEBER: webhook envia entry.id = Instagram Business Account ID → meta_ig_account_id.
    ig_page_id = None
    ig_account_id = None
    ig_token = None
    fb_page_id_for_sub = None
    for page in pages:
        ig_account = (page.get("instagram_business_account") or {}).get("id")
        page_token = (page.get("access_token") or "").strip()
        fb_page_id = str(page.get("id") or "").strip() if page.get("id") is not None else None
        if ig_account and page_token and fb_page_id:
            ig_page_id = fb_page_id
            ig_account_id = str(ig_account).strip() if ig_account else None
            ig_token = page_token
            fb_page_id_for_sub = fb_page_id
            break

    if not ig_page_id or not ig_token:
        print(f"[OAuth] Instagram: nenhuma página com Instagram encontrada (pages={len(pages)})", flush=True)
        return redirect(url_for("customer.conexoes", meta_error="Nenhuma conta Instagram vinculada a uma Página do Facebook encontrada. Vincule o Instagram à Página no Meta Business Suite."))

    payload = {
        ClienteModel.META_IG_PAGE_ID: ig_page_id,
        ClienteModel.META_IG_TOKEN: ig_token,
    }
    if ig_account_id:
        payload[ClienteModel.META_IG_ACCOUNT_ID] = ig_account_id
    try:
        supabase.table(Tables.CLIENTES).update(payload).eq("id", cliente_id).execute()
        print(f"[OAuth] Instagram: dados salvos no banco (meta_ig_page_id, meta_ig_token, meta_ig_account_id)", flush=True)
    except Exception as e:
        print(f"[OAuth] Instagram: erro ao salvar no banco: {e}", flush=True)
        return redirect(url_for("customer.conexoes", meta_error=f"Erro ao salvar no banco: {e}"))

    # Habilitar assinatura de webhook "messages" para a Página (exigido pela documentação Meta/Instagram)
    if fb_page_id_for_sub and ig_token:
        try:
            sub_url = f"{META_GRAPH}/{fb_page_id_for_sub}/subscribed_apps"
            requests.post(sub_url, params={"subscribed_fields": "messages", "access_token": ig_token}, timeout=10)
        except Exception:
            pass

    print(f"[OAuth] Instagram: redirecionando para Conexões (sucesso)", flush=True)
    return redirect(url_for("customer.conexoes", meta_connected="ig"))


def _callback_messenger(cliente_id, access_token, headers):
    """Salva apenas meta_fb_* (Página do Facebook para Messenger)."""
    print(f"[OAuth] _callback_messenger: cliente_id={cliente_id}", flush=True)
    # Debug: confirmar usuário do token e permissões (ajuda quando me/accounts volta 0 páginas)
    try:
        me_r = requests.get(f"{META_GRAPH}/me", params={"fields": "id,name"}, headers=headers, timeout=10)
        if me_r.status_code == 200:
            me_data = me_r.json() or {}
            print(f"[OAuth] Messenger token user: id={me_data.get('id')} name={me_data.get('name')}", flush=True)
        perm_r = requests.get(f"{META_GRAPH}/me/permissions", headers=headers, timeout=10)
        if perm_r.status_code == 200:
            data = perm_r.json() or {}
            granted = [p.get("permission") for p in (data.get("data") or []) if p.get("status") == "granted"]
            print(f"[OAuth] Messenger token permissions: {granted}", flush=True)
        else:
            print(f"[OAuth] Messenger me/permissions: status={perm_r.status_code}", flush=True)
    except Exception as e:
        print(f"[OAuth] Messenger me/permissions exceção: {e}", flush=True)
    try:
        acc_r = requests.get(
            f"{META_GRAPH}/me/accounts",
            params={"fields": "id,name,access_token"},
            headers=headers,
            timeout=15,
        )
        print(f"[OAuth] Messenger me/accounts: status={acc_r.status_code} body_len={len(acc_r.text)} body={acc_r.text[:200]}", flush=True)
        if acc_r.status_code != 200:
            print(f"[OAuth] Messenger me/accounts falhou: {acc_r.text[:300]}", flush=True)
            return redirect(url_for("customer.conexoes", meta_error="Não foi possível listar páginas. Verifique se o app tem o produto Facebook e as permissões corretas."))
        pages = (acc_r.json() or {}).get("data") or []
        print(f"[OAuth] Messenger páginas retornadas: {len(pages)}", flush=True)
    except Exception as e:
        print(f"[OAuth] Messenger exceção ao buscar páginas: {e}", flush=True)
        return redirect(url_for("customer.conexoes", meta_error=f"Erro ao buscar páginas: {e}"))

    if not pages:
        print(f"[OAuth] Messenger: nenhuma página na conta", flush=True)
        return redirect(url_for("customer.conexoes", meta_error="Nenhuma Página do Facebook encontrada. Crie ou administre uma Página e tente novamente."))

    page = pages[0]
    page_id = page.get("id")
    page_id = str(page_id).strip() if page_id is not None else ""
    page_token = (page.get("access_token") or "").strip()
    if not page_id or not page_token:
        return redirect(url_for("customer.conexoes", meta_error="Não foi possível obter o token da Página."))

    payload = {
        ClienteModel.META_FB_PAGE_ID: page_id,
        ClienteModel.META_FB_TOKEN: page_token,
    }
    try:
        supabase.table(Tables.CLIENTES).update(payload).eq("id", cliente_id).execute()
        print(f"[OAuth] Messenger salvo no banco: page_id={page_id} cliente_id={cliente_id}", flush=True)
    except Exception as e:
        print(f"[OAuth] Messenger erro ao salvar no banco: {e}", flush=True)
        return redirect(url_for("customer.conexoes", meta_error=f"Erro ao salvar no banco: {e}"))

    # Habilitar assinatura de webhook "messages" para a Página (exigido pela documentação Meta/Messenger)
    try:
        sub_url = f"{META_GRAPH}/{page_id}/subscribed_apps"
        requests.post(sub_url, params={"subscribed_fields": "messages", "access_token": page_token}, timeout=10)
    except Exception:
        pass

    print(f"[OAuth] Messenger conectado com sucesso, redirecionando para conexoes", flush=True)
    return redirect(url_for("customer.conexoes", meta_connected="fb"))


def _base64_url_decode(data: str) -> bytes:
    """Decodifica base64url (Meta usa - e _ em vez de + e /)."""
    data = data.replace("-", "+").replace("_", "/")
    padding = (4 - len(data) % 4) % 4
    data += "=" * padding
    return base64.b64decode(data)


def _parse_signed_request(signed_request: str, app_secret: str):
    """
    Valida e decodifica o signed_request da Meta (Data Deletion Callback).
    Retorna o payload (dict com user_id, etc.) ou None se inválido.
    """
    if not signed_request or not app_secret:
        return None
    parts = signed_request.split(".", 1)
    if len(parts) != 2:
        return None
    encoded_sig, payload_encoded = parts[0], parts[1]
    try:
        sig = _base64_url_decode(encoded_sig)
        payload_bytes = _base64_url_decode(payload_encoded)
        expected_sig = hmac.new(
            app_secret.encode(),
            payload_encoded.encode(),
            hashlib.sha256
        ).digest()
        if not hmac.compare_digest(sig, expected_sig):
            return None
        return json.loads(payload_bytes.decode("utf-8"))
    except Exception:
        return None


@meta_oauth_bp.route("/data-deletion-callback", methods=["POST"])
def meta_data_deletion_callback():
    """
    Data Deletion Request Callback exigido pela Meta.
    Quando um usuário remove o app em Configurações > Apps e Websites e solicita exclusão,
    a Meta envia POST com signed_request. Devemos retornar JSON com url e confirmation_code.
    """
    app_secret = getattr(settings, "META_APP_SECRET", None) or os.getenv("META_APP_SECRET", "")
    if not app_secret:
        return jsonify({"url": "", "confirmation_code": ""}), 200

    signed_request = (request.form.get("signed_request") or (request.json or {}).get("signed_request") or "").strip()
    payload = _parse_signed_request(signed_request, app_secret)

    # URL onde o usuário pode ver o status da exclusão (nossa página de instruções)
    base_url = getattr(settings, "META_OAUTH_REDIRECT_URI", None) or os.getenv("META_OAUTH_REDIRECT_URI", "") or request.url_root
    base_url = base_url.strip().rstrip("/")
    if base_url and "/" in base_url[8:]:  # depois de https://
        from urllib.parse import urlparse
        p = urlparse(base_url)
        base_url = f"{p.scheme}://{p.netloc}"
    status_url = (base_url or request.url_root.rstrip("/")) + "/exclusao-de-dados"
    confirmation_code = secrets.token_hex(8)

    if payload:
        user_id = payload.get("user_id")
        try:
            current_app.logger.info(f"Meta Data Deletion Request: user_id={user_id} confirmation_code={confirmation_code}")
        except Exception:
            print(f"Meta Data Deletion Request: user_id={user_id} confirmation_code={confirmation_code}")

    return jsonify({"url": status_url, "confirmation_code": confirmation_code}), 200


@meta_oauth_bp.route("/status")
@login_required
def meta_status():
    """Retorna se o WhatsApp está conectado (para o frontend)."""
    try:
        r = supabase.table(Tables.CLIENTES).select(
            "meta_wa_phone_number_id", "meta_wa_token", "meta_wa_waba_id"
        ).eq("id", get_current_cliente_id(current_user)).single().execute()
        if not r.data:
            return {"connected": False}
        d = r.data
        connected = bool(d.get("meta_wa_phone_number_id") and d.get("meta_wa_token"))
        return {
            "connected": connected,
            "phone_number_id": d.get("meta_wa_phone_number_id"),
            "waba_id": d.get("meta_wa_waba_id"),
        }
    except Exception:
        return {"connected": False}
