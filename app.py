import os
import secrets
import json
import time
from flask import Flask, g, request, session, redirect
from flask_cors import CORS
from flask_login import LoginManager
from flask_socketio import SocketIO

# Importações de configuração
from base.config import settings 
from base.auth import load_user_helper

# Observabilidade (opcional)
if getattr(settings, "SENTRY_DSN", ""):
    try:
        import sentry_sdk  # type: ignore
        from sentry_sdk.integrations.flask import FlaskIntegration  # type: ignore

        sentry_sdk.init(
            dsn=settings.SENTRY_DSN,
            environment=getattr(settings, "ENVIRONMENT", "development"),
            integrations=[FlaskIntegration()],
            traces_sample_rate=float(os.getenv("SENTRY_TRACES_SAMPLE_RATE", "0") or "0"),
        )
    except Exception:
        pass

# --- CONFIGURAÇÃO DE CAMINHOS ---
base_dir = os.path.abspath(os.path.dirname(__file__))
template_dir = os.path.join(base_dir, 'panel', 'templates')
static_dir = os.path.join(base_dir, 'panel', 'static')
debug_log_path = os.path.join(base_dir, "debug-1db042.log")

def _agent_debug_log(hypothesis_id: str, location: str, message: str, data=None, run_id: str = "pre-debug") -> None:
    """Log NDJSON para evidência do modo DEBUG (sem expor segredos)."""
    try:
        payload = {
            "sessionId": "1db042",
            "runId": run_id,
            "hypothesisId": hypothesis_id,
            "location": location,
            "message": message,
            "data": data or {},
            "timestamp": int(time.time() * 1000),
        }
        with open(debug_log_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(payload, ensure_ascii=False) + "\n")
    except Exception:
        # Nunca quebre a resposta do servidor por causa de log.
        pass

# 1. Inicialização do Flask (O App deve vir ANTES dos Blueprints)
app = Flask(__name__, template_folder=template_dir, static_folder=static_dir)
app.config['SECRET_KEY'] = settings.SECRET_KEY
# Cookies de sessão mais seguros
app.config['SESSION_COOKIE_HTTPONLY'] = True  # não acessível por JavaScript
app.config['SESSION_COOKIE_SAMESITE'] = 'Lax' # reduz risco de CSRF
# Em produção (HTTPS), cookie só vai por HTTPS
_production = os.getenv("FLASK_ENV") == "production" or os.getenv("PRODUCTION", "").lower() in ("1", "true", "yes")
app.config['SESSION_COOKIE_SECURE'] = _production

# Configuração de CORS:
# Se CORS_ORIGINS estiver definido no .env, restringimos às origens indicadas.
# Caso contrário, mantemos comportamento permissivo (equivalente a "*").
if settings.CORS_ORIGINS:
    CORS(app, resources={r"/*": {"origins": settings.CORS_ORIGINS}})
else:
    # Em produção, preferimos sem CORS (same-origin) para reduzir risco com cookies.
    if not _production:
        CORS(app)

# Configuração SocketIO: usa gevent se disponível (servidor Linux/Gunicorn), senão threading (ex.: Windows local)
try:
    socketio = SocketIO(
        app,
        cors_allowed_origins=(settings.CORS_ORIGINS if settings.CORS_ORIGINS else ([] if _production else "*")),
        async_mode="gevent",
    )
except ValueError:
    socketio = SocketIO(
        app,
        cors_allowed_origins=(settings.CORS_ORIGINS if settings.CORS_ORIGINS else ([] if _production else "*")),
        async_mode="threading",
    )

# 2. Configuração do Flask-Login
login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'customer.login'

@login_manager.user_loader
def load_user(user_id):
    return load_user_helper(user_id)


@login_manager.unauthorized_handler
def unauthorized():
    """Quando sessão expira: API recebe 401 JSON (evita 'Unexpected token <' no chat)."""
    from flask import request, redirect, url_for, jsonify
    if request.path.startswith("/api/"):
        return jsonify({"erro": "Sessão expirada", "redirect": "/"}), 401
    return redirect(url_for("customer.login"))


# 3. Registro de Blueprints (Importamos aqui para evitar erros de importação circular)
from panel.routes.customer import customer_bp
from panel.routes.admin import admin_bp
from panel.routes.embed import embed_bp
from panel.routes.meta_oauth import meta_oauth_bp
from panel.routes.legal import legal_bp
from panel.routes.exports import exports_bp
from panel.routes.billing import billing_bp
from panel.routes.public import public_bp
from panel.routes.seo import seo_bp
from panel.routes.auth_routes import auth_bp
from webhooks.meta_cloud import meta_bp
from webhooks.waha_webhook import waha_webhook_bp
from webhooks.mercadopago_webhook import mercadopago_bp

# Registrar rotas
app.register_blueprint(customer_bp)                      # Raiz: /
app.register_blueprint(admin_bp, url_prefix='/admin')    # Ex: /admin/dashboard
app.register_blueprint(meta_oauth_bp, url_prefix='/meta')  # GET /meta/connect, /meta/oauth/callback, /meta/status
app.register_blueprint(legal_bp)                         # /politica, /termos, /exclusao-de-dados (páginas legais Meta)
app.register_blueprint(exports_bp)                       # /painel/export/*
app.register_blueprint(billing_bp)                       # /api/billing/*
app.register_blueprint(auth_bp, url_prefix='/auth')
app.register_blueprint(public_bp)                        # /precos, /cadastro, /assinatura
app.register_blueprint(seo_bp)                           # /sitemap.xml, /robots.txt

from base.auth import is_admin, get_current_cliente_id

app.jinja_env.globals["getattr"] = getattr

def csrf_token() -> str:
    """
    Token CSRF simples por sessão (double-submit via header/campo hidden).
    """
    tok = session.get("csrf_token")
    if not tok:
        tok = secrets.token_hex(32)
        session["csrf_token"] = tok
    return tok


@app.context_processor
def inject_csrf():
    return {"csrf_token": csrf_token}

@app.context_processor
def inject_domain_urls():
    """
    URLs canônicas de domínio para separar público e app.
    - Público: zapaction.com.br
    - App/API: api.updigitalbrasil.com.br
    """
    public_base = (os.getenv("PUBLIC_BASE_URL") or "https://zapaction.com.br").strip().rstrip("/")
    app_base = (os.getenv("APP_BASE_URL") or "https://api.updigitalbrasil.com.br").strip().rstrip("/")
    return {
        "PUBLIC_BASE_URL": public_base,
        "APP_BASE_URL": app_base,
    }

@app.context_processor
def inject_features():
    """
    Helper para templates: esconder recursos que não existem no plano.
    Uso no Jinja: {% if has_feature('exports') %}...{% endif %}
    """
    try:
        from flask_login import current_user
        from base.auth import get_current_cliente_id, is_admin
        from services.entitlements import can_access_feature, can_use_channel

        def has_feature(feature_key: str) -> bool:
            try:
                if not (current_user and getattr(current_user, "is_authenticated", False) and current_user.is_authenticated):
                    return False
                # Admin master sempre vê tudo no app
                if is_admin(current_user):
                    return True
                cid = get_current_cliente_id(current_user)
                if not cid:
                    return False
                return bool(can_access_feature(str(cid), feature_key))
            except Exception:
                return False

        def _canal_ui_conhecido(canal: str) -> bool:
            c = (canal or "").strip().lower()
            if c == "messenger":
                c = "facebook"
            return c in ("whatsapp", "website", "site", "instagram", "facebook")

        def can_use_channel_ui(canal: str) -> bool:
            """Plano + kill switch global (Instagram/Messenger). Admin mestre ignora plano."""
            try:
                if not (current_user and getattr(current_user, "is_authenticated", False) and current_user.is_authenticated):
                    return False
                # Não depender só de g.admin_full_access: mostrar redes no painel para o admin mestre
                if is_admin(current_user):
                    return _canal_ui_conhecido(canal)
                cid = get_current_cliente_id(current_user)
                if not cid:
                    return False
                return bool(can_use_channel(str(cid), canal))
            except Exception:
                return False

        def has_any_channel() -> bool:
            try:
                if not (current_user and getattr(current_user, "is_authenticated", False) and current_user.is_authenticated):
                    return False
                if is_admin(current_user):
                    return True
                cid = get_current_cliente_id(current_user)
                if not cid:
                    return False
                return any(
                    can_use_channel(str(cid), k) for k in ("whatsapp", "instagram", "messenger", "website")
                )
            except Exception:
                return False

        global_channel_banner = None
        try:
            if (
                current_user
                and getattr(current_user, "is_authenticated", False)
                and current_user.is_authenticated
                and not is_admin(current_user)
            ):
                from services.app_settings import get_global_settings

                gs = get_global_settings()
                off: list[str] = []
                if not bool(gs.get("whatsapp_enabled", True)):
                    off.append("WhatsApp")
                if not bool(gs.get("instagram_enabled", True)):
                    off.append("Instagram")
                if not bool(gs.get("messenger_enabled", True)):
                    off.append("Messenger")
                if off:
                    global_channel_banner = {
                        "channels": off,
                        "message": (
                            "Manutenção na plataforma: "
                            + ", ".join(off)
                            + " está(ão) temporariamente indisponível(is) para todos. "
                            "Envio pelo painel e automações nesses canais ficam bloqueados até o administrador reativar."
                        ),
                    }
        except Exception:
            global_channel_banner = None

        return {
            "has_feature": has_feature,
            "has_any_channel": has_any_channel,
            "can_use_channel_ui": can_use_channel_ui,
            "global_channel_banner": global_channel_banner,
        }
    except Exception:
        return {
            "has_feature": lambda _k: False,
            "has_any_channel": lambda: False,
            "can_use_channel_ui": lambda _c: False,
            "global_channel_banner": None,
        }


@app.before_request
def request_context():
    host = (request.host or "").split(":", 1)[0].lower()
    path = request.path or "/"
    public_base = (os.getenv("PUBLIC_BASE_URL") or "https://zapaction.com.br").strip().rstrip("/")
    app_base = (os.getenv("APP_BASE_URL") or "https://api.updigitalbrasil.com.br").strip().rstrip("/")
    public_host = ""
    app_host = ""
    try:
        from urllib.parse import urlparse
        public_host = (urlparse(public_base).hostname or "").lower()
        app_host = (urlparse(app_base).hostname or "").lower()
    except Exception:
        public_host = "zapaction.com.br"
        app_host = "api.updigitalbrasil.com.br"
    is_local = host in ("127.0.0.1", "localhost") or host.startswith("192.168.") or host.startswith("10.") or host.endswith(".local")

    # Fallback no Flask: páginas públicas não devem responder no host do app/API.
    # Preferimos 301 para preservar SEO e evitar quebra de links antigos.
    public_paths = {
        "/",
        "/precos",
        "/cadastro",
        "/assinatura",
        "/politica",
        "/termos",
        "/exclusao-de-dados",
        "/whatsapp-atendimento",
    }
    if (
        not is_local
        and app_host
        and host == app_host
        and path in public_paths
    ):
        qs = request.query_string.decode("utf-8") if request.query_string else ""
        target = f"{public_base}{path}"
        if qs:
            target = f"{target}?{qs}"
        return redirect(target, code=301)

    # request_id para logs/diagnóstico
    rid = request.headers.get("X-Request-Id") or secrets.token_hex(8)
    g.request_id = rid
    # Admin mestre: entitlements ignoram plano/billing (ver services.entitlements._admin_full_access)
    try:
        from flask_login import current_user as _cu

        g.admin_full_access = bool(
            getattr(_cu, "is_authenticated", False) and _cu.is_authenticated and is_admin(_cu)
        )
    except Exception:
        g.admin_full_access = False

    # Garante token CSRF para sessões autenticadas (para JS e forms)
    try:
        from flask_login import current_user
        if getattr(current_user, "is_authenticated", False) and current_user.is_authenticated:
            csrf_token()
    except Exception:
        pass

    # CSRF enforcement para endpoints com cookie (painel/admin/api)
    if request.method in ("POST", "PUT", "PATCH", "DELETE"):
        p = request.path or ""
        # Exceções: webhooks e auth bootstrap
        if p.startswith("/webhook/"):
            return None
        if p.startswith("/api/auth/"):
            return None
        # Widget do site: visitantes sem sessão não têm CSRF; validação por data-key + session_id
        ep = p
        if ep.startswith("/api/embed/message") or ep.startswith("/api/embed/poll") or ep.startswith("/api/embed/media"):
            return None
        # Export é GET; não entra aqui
        if p.startswith("/api/") or p.startswith("/admin/api/") or p.startswith("/painel/"):
            # aceita token no header (JS) ou em form field
            token_header = (request.headers.get("X-CSRF-Token") or "").strip()
            token_form = (request.form.get("csrf_token") or "").strip() if request.form else ""
            token = token_header or token_form
            expected = (session.get("csrf_token") or "").strip()
            #region agent log csrf_enforce_enter
            _agent_debug_log(
                hypothesis_id="H1_embed_csrf_missing",
                location="app.py:before_request:csrf_enforce",
                message="CSRF check reached",
                data={
                    "path": p,
                    "method": request.method,
                    "is_embed_api": p.startswith("/api/embed/"),
                    "token_header_len": len(token_header),
                    "token_form_len": len(token_form),
                    "token_len": len(token),
                    "expected_len": len(expected),
                    # Evita criar/emitir tokens em rotas sem login; ajuda a explicar "esperado vazio".
                    "user_authenticated": bool(getattr(request, "user", None)),
                },
            )
            #endregion
            if not expected or not token or token != expected:
                #region agent log csrf_enforce_403
                _agent_debug_log(
                    hypothesis_id="H2_csrf_failure_reason",
                    location="app.py:before_request:csrf_enforce",
                    message="CSRF failed -> 403",
                    data={
                        "path": p,
                        "method": request.method,
                        "expected_empty": not bool(expected),
                        "token_empty": not bool(token),
                        "mismatch": bool(expected and token and token != expected),
                        "token_header_len": len(token_header),
                        "token_form_len": len(token_form),
                        "expected_len": len(expected),
                        "is_embed_api": p.startswith("/api/embed/"),
                    },
                )
                #endregion
                from flask import jsonify
                return jsonify({"erro": "CSRF inválido ou ausente."}), 403

    # Entitlements/billing: bloquear ações pagas quando assinatura não estiver ok
    try:
        from flask_login import current_user
        if getattr(current_user, "is_authenticated", False) and current_user.is_authenticated:
            p = request.path or ""
            # Admin master nunca deve ser bloqueado por billing
            try:
                from base.auth import is_admin
                if is_admin(current_user):
                    return None
            except Exception:
                pass
            # Sempre permitir billing/status/auth/páginas legais
            allow_prefixes = (
                "/api/billing/",
                "/api/auth/",
                "/api/csrf-token",
                "/admin",
                "/politica",
                "/termos",
                "/exclusao-de-dados",
                "/precos",
                "/cadastro",
                "/assinatura",
                "/whatsapp-atendimento",
                "/login",
                "/logout",
                "/static/",
                "/panel/static/",
                "/favicon.ico",
                "/sw.js",
            )
            if not p.startswith(allow_prefixes):
                # Bloqueio estrito: se o billing não estiver ok, o cliente/sublogin perde acesso a tudo
                # (exceto allowlist acima). A fonte da verdade é o webhook (billing_status no Supabase).
                from base.auth import get_current_cliente_id
                from services.entitlements import can_use_product, can_access_feature

                cliente_id = get_current_cliente_id(current_user)
                if cliente_id:
                    ent = can_use_product(str(cliente_id))
                    if not ent.allowed:
                        from flask import jsonify, url_for
                        if p.startswith("/api/"):
                            return jsonify(
                                {
                                    "erro": "Assinatura inativa. Atualize o pagamento para continuar.",
                                    "billing_status": ent.status,
                                    "reason": ent.reason,
                                }
                            ), 402
                        # Para endpoints de download (export), evitamos redirect "na marra"
                        if p.startswith("/painel/export/"):
                            return jsonify(
                                {
                                    "erro": "Assinatura inativa. Atualize o pagamento para continuar.",
                                    "billing_status": ent.status,
                                    "reason": ent.reason,
                                }
                            ), 402
                        return redirect(url_for("public.precos"))

                    # Enforcement por feature (plano): exports e flow builder
                    if p.startswith("/painel/export/") and not can_access_feature(str(cliente_id), "exports"):
                        from flask import jsonify
                        return jsonify({"erro": "Seu plano não inclui exportações."}), 403
                    if p.startswith("/flow") and not can_access_feature(str(cliente_id), "flow_builder"):
                        from flask import jsonify
                        return jsonify({"erro": "Seu plano não inclui o Flow Builder."}), 403
    except Exception:
        pass


@app.context_processor
def inject_admin():
    try:
        from flask_login import current_user
        current_cliente_id = None
        if getattr(current_user, "is_authenticated", False) and current_user.is_authenticated:
            current_cliente_id = get_current_cliente_id(current_user)
        return dict(is_admin=is_admin, current_cliente_id=current_cliente_id)
    except Exception:
        return dict(is_admin=is_admin, current_cliente_id=None)
app.register_blueprint(embed_bp)                         # /api/embed/key, /api/embed/send
app.register_blueprint(meta_bp, url_prefix='/webhook')   # GET/POST /webhook/meta (WhatsApp, Instagram, Messenger)
app.register_blueprint(waha_webhook_bp, url_prefix='/webhook')  # POST /webhook/waha (eventos WAHA)
app.register_blueprint(mercadopago_bp, url_prefix="/webhook")  # POST /webhook/mercadopago


@app.route("/webhook/meta/static/embed/chat-widget.js")
def legacy_embed_chat_widget_js():
    """Compat: instalações antigas usam esta URL; mesmo arquivo que /static/embed/chat-widget.js."""
    from flask import send_from_directory
    return send_from_directory(
        os.path.join(static_dir, "embed"),
        "chat-widget.js",
        mimetype="application/javascript",
        max_age=86400,
    )


@app.route("/favicon.ico")
def favicon():
    """Serve o logo do app como favicon."""
    from flask import send_from_directory
    return send_from_directory(os.path.join(static_dir, "images"), "logo.png", mimetype="image/png")


@app.route("/api/csrf-token", methods=["GET"])
def api_csrf_token():
    """Retorna o token CSRF da sessão para SPAs (ex.: Flow Builder) que não recebem o token pelo HTML."""
    from flask import jsonify
    from flask_login import current_user
    if not (current_user and getattr(current_user, "is_authenticated", False) and current_user.is_authenticated):
        return jsonify({"erro": "Não autenticado."}), 401
    token = (session.get("csrf_token") or "").strip()
    return jsonify({"csrf_token": token})


# Flow Builder (React app build em panel/static/flow-builder)
_flow_builder_dir = os.path.join(static_dir, "flow-builder")


@app.route("/flow")
@app.route("/flow/")
def flow_builder_index():
    """Serve a página do Flow Builder (requer login)."""
    from flask import send_from_directory, redirect, url_for, flash, request
    from flask_login import current_user
    if not (current_user and getattr(current_user, "is_authenticated", False) and current_user.is_authenticated):
        return redirect(url_for("customer.login"))
    try:
        from base.auth import get_current_cliente_id
        from services.entitlements import can_access_feature
        cliente_id = get_current_cliente_id(current_user)
        if cliente_id and not can_access_feature(str(cliente_id), "flow_builder"):
            return redirect(url_for("public.precos"))
    except Exception:
        pass
    # Meus Chatbots: ?chatbot_id= só se o bot existir e for deste cliente (evita abrir o builder sem registo válido)
    chatbot_id = (request.args.get("chatbot_id") or "").strip()
    if chatbot_id:
        try:
            from base.auth import get_current_cliente_id
            from database.supabase_sq import supabase
            from database.models import Tables, ChatbotModel

            cid = str(get_current_cliente_id(current_user) or "")
            if not cid or supabase is None:
                flash("Sessão inválida.", "error")
                return redirect(url_for("customer.chatbots_list"))
            r = (
                supabase.table(Tables.CHATBOTS)
                .select(ChatbotModel.ID)
                .eq(ChatbotModel.ID, chatbot_id)
                .eq(ChatbotModel.CLIENTE_ID, cid)
                .limit(1)
                .execute()
            )
            if not r.data:
                flash("Chatbot não encontrado. Crie um chatbot na lista antes de abrir o fluxo.", "error")
                return redirect(url_for("customer.chatbots_list"))
        except Exception:
            flash("Não foi possível validar o chatbot.", "error")
            return redirect(url_for("customer.chatbots_list"))
    index_path = os.path.join(_flow_builder_dir, "index.html")
    if not os.path.isfile(index_path):
        return "Flow Builder não construído. Execute em flow-builder: npm install && npm run build.", 404
    return send_from_directory(_flow_builder_dir, "index.html")


@app.route("/flow/<path:path>")
def flow_builder_assets(path):
    """Serve assets do Flow Builder (JS/CSS)."""
    from flask import send_from_directory
    return send_from_directory(_flow_builder_dir, path)


@app.route("/sw.js")
def service_worker():
    """Service Worker na raiz para escopo global (Web Push)."""
    from flask import send_from_directory
    return send_from_directory(os.path.join(base_dir, "panel", "static"), "sw.js", mimetype="application/javascript")


# --- Embed (chat para site): mapeamento socket sid -> dados do visitante ---
embed_sockets = {}  # sid -> {cliente_id, session_id, room}


@socketio.on("connect")
def on_connect(auth=None):
    from flask import request, session
    from flask_socketio import join_room
    from flask_login import current_user
    key = (request.args.get("key") or "").strip()
    session_id = (request.args.get("session_id") or "").strip()

    # Widget do site (embed): exige key + session_id e entra na room do visitante.
    if key and session_id:
        try:
            from database.supabase_sq import supabase
            from database.models import Tables, ClienteModel
            r = supabase.table(Tables.CLIENTES).select("id").eq(ClienteModel.WEBSITE_CHAT_EMBED_KEY, key).execute()
            if not r.data or len(r.data) == 0:
                print("[Embed] Conexão rejeitada: chave não encontrada no banco.", flush=True)
                return False
            cliente_id = r.data[0]["id"]
            room = f"website:{cliente_id}:{session_id}"
            embed_sockets[request.sid] = {"cliente_id": cliente_id, "session_id": session_id, "room": room}
            join_room(room)
        except Exception as e:
            print(f"[Embed] Conexão rejeitada (erro): {e}", flush=True)
            return False
    else:
        # Painel: entra na room do cliente para receber notificações (nova_mensagem).
        uid = None
        if current_user.is_authenticated:
            uid = get_current_cliente_id(current_user)
            if uid is None:
                uid = getattr(current_user, "id", None)
        if not uid and session:
            uid = session.get("_user_id") or session.get("_id")
        if uid:
            try:
                join_room(f"painel:{str(uid)}")
            except Exception as e:
                print(f"[SocketIO] join_room painel falhou: {e}", flush=True)


@socketio.on("disconnect")
def on_disconnect():
    from flask import request
    embed_sockets.pop(request.sid, None)


@socketio.on("embed_message")
def on_embed_message(data):
    import threading
    from flask import request
    from services.message_service import MessageService
    info = embed_sockets.get(request.sid)
    if not info:
        return
    text = (data or {}).get("text") or (data or {}).get("conteudo") or ""
    if not text.strip():
        return
    socketio_ref = app.extensions.get("socketio")
    room = info["room"]
    threading.Thread(
        target=MessageService.processar_mensagem_entrada,
        args=("website", info["session_id"], text.strip(), info["cliente_id"], None, socketio_ref),
        daemon=True,
    ).start()
# --- DEBUG ---
webhook_base = (getattr(settings, "WEBHOOK_URL", None) or "").strip().rstrip("/")
# Garantir que é só a origem (sem /webhook/meta), para exibir a URL correta
if webhook_base.endswith("/webhook/meta"):
    webhook_base = webhook_base[:-len("/webhook/meta")].rstrip("/")
elif webhook_base.endswith("/webhook"):
    webhook_base = webhook_base[:-len("/webhook")].rstrip("/")
print(f"\n--- VERIFICAÇÃO DE AMBIENTE ---")
print(f"Raiz do Projeto: {base_dir}")
if webhook_base:
    print(f"Webhook Meta (WhatsApp/Instagram/Messenger): {webhook_base}/webhook/meta")
else:
    print(f"Webhook Meta: configure WEBHOOK_URL no .env e use .../webhook/meta no app da Meta.")
print(f"-------------------------------\n")

# 4. Execução do Servidor
if __name__ == '__main__':
    print("Iniciando verificação de serviços externos...") 
    try:
        from base.network import check_external_services 
        check_external_services()
        
        print("SaaS Multicanal iniciando no SocketIO...")
        # Em produção (PRODUCTION=1): sem debug/reload para o app não cair sozinho
        use_debug = not _production
        port = int(os.getenv("PORT", "5000"))
        socketio.run(app, host='0.0.0.0', port=port, debug=use_debug, use_reloader=False)
        
    except Exception as e:
        print(f"\n[ERRO CRITICO] {e}")
        import traceback
        traceback.print_exc()