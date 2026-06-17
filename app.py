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

# Login no ZapAction + sessão na API: cookie precisa SameSite=None (com Secure) para XHR entre domínios.
from base.domain_redirects import use_split_public_app_routing as _split_hosts_for_cookie

if _production and _split_hosts_for_cookie():
    app.config["SESSION_COOKIE_SAMESITE"] = "None"


def _socketio_cors_allowed_origins():
    """União de CORS_ORIGINS + URLs canónicas público/app (defaults ZapAction + API)."""
    from base.domain_redirects import app_base_url, public_base_url

    seen = set()
    out = []
    for o in settings.CORS_ORIGINS:
        o = (o or "").strip().rstrip("/")
        if o and o not in seen:
            seen.add(o)
            out.append(o)
    for u in (public_base_url(), app_base_url()):
        if u and u not in seen:
            seen.add(u)
            out.append(u)
    if out:
        return out
    if not _production:
        return "*"
    return "*"


# Configuração de CORS (login no ZapAction → POST na API: origens públicas têm de estar permitidas).
from base.domain_redirects import auth_cors_allowed_origins as _auth_cors_origins

_auth_o = _auth_cors_origins()

if settings.CORS_ORIGINS:
    _merged = list(dict.fromkeys([*settings.CORS_ORIGINS, *_auth_o]))
    CORS(
        app,
        resources={
            r"/*": {
                "origins": _merged,
                "supports_credentials": True,
                "allow_headers": ["Content-Type", "Accept", "X-CSRF-Token"],
            }
        },
    )
else:
    if not _production:
        CORS(app)
    elif _auth_o:
        CORS(
            app,
            resources={
                r"/auth/*": {
                    "origins": _auth_o,
                    "supports_credentials": True,
                    "allow_headers": ["Content-Type", "Accept"],
                }
            },
        )

# Configuração SocketIO: usa gevent se disponível (servidor Linux/Gunicorn), senão threading (ex.: Windows local)
try:
    socketio = SocketIO(
        app,
        cors_allowed_origins=_socketio_cors_allowed_origins(),
        async_mode="gevent",
    )
except ValueError:
    socketio = SocketIO(
        app,
        cors_allowed_origins=_socketio_cors_allowed_origins(),
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
    from flask import request, jsonify
    from base.domain_redirects import redirect_to_app_login

    if request.path.startswith("/api/"):
        return jsonify({"erro": "Sessão expirada", "redirect": "/"}), 401
    return redirect_to_app_login()


# 3. Registro de Blueprints (Importamos aqui para evitar erros de importação circular)
from panel.routes.customer import customer_bp
from panel.routes.admin import admin_bp
from panel.routes.embed import embed_bp
from panel.routes.meta_oauth import meta_oauth_bp
from panel.routes.legal import legal_bp
from panel.routes.exports import exports_bp
from billing.routes import billing_bp, stripe_billing_bp
from panel.routes.public import public_bp
from panel.routes.seo import seo_bp
from panel.routes.scheduling import scheduling_bp
from panel.routes.auth_routes import auth_bp
from webhooks.meta_cloud import meta_bp
from webhooks.waha_webhook import waha_webhook_bp
from webhooks.agendamento_ia_appointments import agendamento_ia_appointments_bp

# Registrar rotas
app.register_blueprint(customer_bp)                      # Raiz: /
app.register_blueprint(scheduling_bp, url_prefix="/painel/agenda")
app.register_blueprint(admin_bp, url_prefix='/admin')    # Ex: /admin/dashboard
app.register_blueprint(meta_oauth_bp, url_prefix='/meta')  # GET /meta/connect, /meta/oauth/callback, /meta/status
app.register_blueprint(legal_bp)                         # /politica, /termos, /exclusao-de-dados (páginas legais Meta)
app.register_blueprint(exports_bp)                       # /painel/export/*
app.register_blueprint(billing_bp)                       # /api/billing/*
app.register_blueprint(stripe_billing_bp)                # /api/billing/stripe/*
app.register_blueprint(auth_bp, url_prefix='/auth')
app.register_blueprint(public_bp)                        # /precos, /cadastro, /assinatura
app.register_blueprint(seo_bp)                           # /sitemap.xml, /robots.txt

from base.auth import is_admin, is_admin_like, get_current_cliente_id

app.jinja_env.globals["getattr"] = getattr


@app.template_filter("format_scheduling_datetime")
def _format_scheduling_datetime(value, tz_name=None):
    """Data/hora pt-BR no fuso da clínica (ex.: 21/05/2026 14:30)."""
    from services.scheduling.display import format_datetime_br

    return format_datetime_br(value, tz_name or "America/Sao_Paulo")


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
    Em produção: PUBLIC_BASE_URL = propaganda (default zapaction.com.br); APP_BASE_URL = app (default API).
    Em localhost: ambos = origem do pedido (links relativos ao dev server).
    """
    from flask import request
    from base.domain_redirects import (
        app_base_url,
        canonical_public_url,
        get_support_whatsapp_url,
        is_local_request,
        path_allowed_on_public_host,
        public_base_url,
    )

    path = (request.path or "/").strip() or "/"
    if is_local_request(request):
        root = request.url_root.rstrip("/")
        public_chat_key = (os.getenv("PUBLIC_CHAT_EMBED_KEY") or "").strip()
        canon = None
        if path_allowed_on_public_host(path):
            canon = f"{root}/" if path == "/" else f"{root}{path}"
        return {
            "PUBLIC_BASE_URL": root,
            "APP_BASE_URL": root,
            "PUBLIC_CHAT_EMBED_KEY": public_chat_key,
            "support_whatsapp_url": get_support_whatsapp_url(),
            "CANONICAL_PAGE_URL": canon,
        }
    public_chat_key = (os.getenv("PUBLIC_CHAT_EMBED_KEY") or "").strip()
    canon = canonical_public_url(path) if path_allowed_on_public_host(path) else None
    return {
        "PUBLIC_BASE_URL": public_base_url(),
        "APP_BASE_URL": app_base_url(),
        "PUBLIC_CHAT_EMBED_KEY": public_chat_key,
        "support_whatsapp_url": get_support_whatsapp_url(),
        "CANONICAL_PAGE_URL": canon,
    }

@app.context_processor
def inject_embed_key():
    """Chave embed do tenant logado (painel cliente). Templates usam {{ embed_key }}; administradores da plataforma não recebem chave."""
    try:
        from flask_login import current_user
        from base.auth import get_current_cliente_id, is_admin_like
        from database.supabase_sq import supabase
        from database.models import Tables, ClienteModel

        if (
            supabase is None
            or not current_user.is_authenticated
            or is_admin_like(current_user)
        ):
            return {"embed_key": None}
        if getattr(current_user, "acesso_site", True) is False:
            return {"embed_key": None}
        cid = get_current_cliente_id(current_user)
        if not cid:
            return {"embed_key": None}
        r = (
            supabase.table(Tables.CLIENTES)
            .select(ClienteModel.EMBED_KEY)
            .eq(ClienteModel.ID, cid)
            .limit(1)
            .execute()
        )
        row = (r.data or [{}])[0] if r.data else {}
        key = (row.get(ClienteModel.EMBED_KEY) or "").strip() or None
        return {"embed_key": key}
    except Exception:
        return {"embed_key": None}


@app.context_processor
def inject_features():
    """
    Helper para templates: esconder recursos que não existem no plano.
    Uso no Jinja: {% if has_feature('exports') %}...{% endif %}
    """
    try:
        from flask_login import current_user
        from base.auth import get_current_cliente_id, is_admin_like
        from services.entitlements import can_access_feature, can_use_channel

        def has_feature(feature_key: str) -> bool:
            try:
                if not (current_user and getattr(current_user, "is_authenticated", False) and current_user.is_authenticated):
                    return False
                # Admins da plataforma sempre veem tudo no app
                if is_admin_like(current_user):
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
            """Plano + kill switch global (Instagram/Messenger). Admins da plataforma ignoram plano."""
            try:
                if not (current_user and getattr(current_user, "is_authenticated", False) and current_user.is_authenticated):
                    return False
                # Não depender só de g.admin_full_access: mostrar redes no painel para admins da plataforma
                if is_admin_like(current_user):
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
                if is_admin_like(current_user):
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
                and not is_admin_like(current_user)
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


@app.context_processor
def inject_billing_paywall():
    """
    Paywall dentro do painel.
    Motivo: evitar redirecionar para páginas públicas (que podem levar a novo cadastro/trial)
    e permitir que o cliente escolha um plano e vá direto ao checkout.
    """
    try:
        from flask_login import current_user
        from base.auth import is_admin_like, get_current_cliente_id
        from services.entitlements import can_use_product, get_billing_state
        from services.plans import get_plan_for_cliente, list_active_plans

        if not (current_user and getattr(current_user, "is_authenticated", False) and current_user.is_authenticated):
            return {"billing_paywall": None}
        if is_admin_like(current_user):
            return {"billing_paywall": None}

        cid = get_current_cliente_id(current_user)
        if not cid:
            return {"billing_paywall": None}

        ent = can_use_product(str(cid))
        if ent.allowed:
            return {"billing_paywall": None}
        if ent.reason not in ("trial_expirado", "assinatura_inativa", "assinatura_em_atraso", "conta_em_onboarding"):
            return {"billing_paywall": None}

        from datetime import datetime, timezone

        status, period_end, trial_end, plan_key = get_billing_state(str(cid))
        plans = list_active_plans()

        # No funil de onboarding o plano já foi escolhido no cadastro público: não repetir a grelha de planos.
        selected_plan = None
        onboarding_checkout_only = ent.reason == "conta_em_onboarding"
        if onboarding_checkout_only:
            pk = (plan_key or "").strip()
            if pk:
                selected_plan = get_plan_for_cliente(pk, str(cid)) or get_plan_for_cliente(pk)

        # Trial deve existir apenas na primeira vez. Depois que `trial_ends_at` existe,
        # não exibimos novo trial no paywall e também não prometemos "dias de teste" nos cards.
        has_used_trial = bool(trial_end)
        show_trial = bool(status == "trialing" and trial_end and datetime.now(timezone.utc) < trial_end)
        if has_used_trial and plans and not onboarding_checkout_only:
            try:
                for p in plans:
                    if isinstance(p, dict) and (p.get("trial_days") or 0):
                        p["trial_days"] = 0
            except Exception:
                pass
        return {
            "billing_paywall": {
                "required": True,
                "reason": ent.reason,
                "status": status,
                "trial_end": trial_end.isoformat() if trial_end else None,
                "period_end": period_end.isoformat() if period_end else None,
                "current_plan_key": plan_key,
                "plans": plans,
                "show_trial": show_trial,
                "email": (getattr(current_user, "email", "") or "").strip().lower(),
                "onboarding_checkout_only": onboarding_checkout_only,
                "selected_plan": selected_plan,
            }
        }
    except Exception:
        return {"billing_paywall": None}


def _maybe_log_split_redirect(code: int, target: str, reason: str) -> None:
    """Amostragem opcional: SPLIT_REDIRECT_LOG_SAMPLE_RATE em ]0,1] (ex.: 0.01 = 1%)."""
    try:
        rate = float((os.getenv("SPLIT_REDIRECT_LOG_SAMPLE_RATE") or "0").strip() or "0")
    except ValueError:
        return
    if rate <= 0:
        return
    import random

    if random.random() > min(rate, 1.0):
        return
    try:
        from flask import current_app, has_request_context, request as rq

        if not has_request_context():
            return
        host = (rq.host or "").split(":", 1)[0].lower()
        path = rq.path or "/"
        ua = (rq.headers.get("User-Agent") or "")[:240]
        current_app.logger.info(
            "split_host_redirect code=%s reason=%s host=%s path=%s target=%s ua=%s",
            code,
            reason,
            host,
            path,
            target,
            ua,
        )
    except Exception:
        return


@app.before_request
def request_context():
    from base.domain_redirects import (
        PATHS_CANONICAL_ON_PUBLIC_HOST,
        app_base_url,
        app_hosts,
        path_allowed_on_public_host,
        public_base_url,
        public_marketing_hosts,
        use_split_public_app_routing,
    )

    host = (request.host or "").split(":", 1)[0].lower()
    path = request.path or "/"
    public_base = public_base_url()
    app_base = app_base_url()
    pub_hosts = public_marketing_hosts()
    application_hosts = app_hosts()
    is_local = host in ("127.0.0.1", "localhost") or host.startswith("192.168.") or host.startswith("10.") or host.endswith(".local")
    split_hosts = use_split_public_app_routing()

    # Dois domínios: host de propaganda só marketing; resto → APP_BASE_URL.
    if (
        split_hosts
        and not is_local
        and pub_hosts
        and app_base
        and host in pub_hosts
        and not path_allowed_on_public_host(path)
        and not path.startswith("/webhook/")
    ):
        qs = request.query_string.decode("utf-8") if request.query_string else ""
        target = f"{app_base}{path}"
        if qs:
            target = f"{target}?{qs}"
        code = 308 if request.method != "GET" else 301
        _maybe_log_split_redirect(code, target, "public_host_non_marketing_path")
        return redirect(target, code=code)

    # Dois domínios: marketing canónico no domínio de propaganda (SEO).
    if (
        split_hosts
        and not is_local
        and application_hosts
        and host in application_hosts
        and path in PATHS_CANONICAL_ON_PUBLIC_HOST
    ):
        qs = request.query_string.decode("utf-8") if request.query_string else ""
        target = f"{public_base}{path}"
        if qs:
            target = f"{target}?{qs}"
        _maybe_log_split_redirect(301, target, "app_host_marketing_canonical")
        return redirect(target, code=301)

    # request_id para logs/diagnóstico
    rid = request.headers.get("X-Request-Id") or secrets.token_hex(8)
    g.request_id = rid
    # Authorization context (fail-safe + feature flag)
    # - g.admin_full_access é consumido por services.entitlements._admin_full_access
    # - g.authz_role / g.authz_role_source são para auditoria/diagnóstico
    g.authz_role = None
    g.authz_role_source = None
    try:
        from flask_login import current_user as _cu
        from services.authz.roles import resolve_role

        if getattr(settings, "USE_NEW_AUTHZ_PIPELINE", False):
            rr = resolve_role(_cu)
            g.authz_role = rr.role
            g.authz_role_source = rr.source
            g.admin_full_access = bool(rr.role == "super_admin")
        else:
            # Legado: admin-like por e-mail (ADMIN_EMAIL/ADMIN_EMAILS)
            g.admin_full_access = bool(
                getattr(_cu, "is_authenticated", False) and _cu.is_authenticated and is_admin_like(_cu)
            )
            g.authz_role = "super_admin" if g.admin_full_access else None
            g.authz_role_source = "legacy_admin_like" if g.admin_full_access else None
    except Exception:
        g.admin_full_access = False
        g.authz_role = None
        g.authz_role_source = None

    # Garante token CSRF para sessões autenticadas (só em GET — em POST não gerar antes da validação)
    try:
        from flask_login import current_user
        if getattr(current_user, "is_authenticated", False) and current_user.is_authenticated:
            if request.method == "GET":
                csrf_token()
    except Exception:
        pass

    # CSRF enforcement para endpoints com cookie (painel/admin/api)
    if request.method in ("POST", "PUT", "PATCH", "DELETE"):
        p = request.path or ""
        # Exceções: webhooks e auth bootstrap
        if p.startswith("/webhook/"):
            return None
        if p.startswith("/socket.io/"):
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
            token_header = (
                (request.headers.get("X-CSRF-Token") or request.headers.get("X-CSRFToken") or "")
                .strip()
            )
            token_form = (request.form.get("csrf_token") or "").strip() if request.form else ""
            token = token_header or token_form
            if not token and request.is_json:
                data = request.get_json(silent=True) or {}
                if isinstance(data, dict):
                    token = (data.get("csrf_token") or "").strip()
            expected = (session.get("csrf_token") or "").strip()
            # Sessão nova (ex.: remember-me) com formulário ainda válido: alinhar uma vez
            if not expected and token:
                try:
                    from flask_login import current_user as _cu
                    if getattr(_cu, "is_authenticated", False) and _cu.is_authenticated:
                        session["csrf_token"] = token
                        expected = token
                except Exception:
                    pass
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
                from flask import flash, jsonify, redirect

                # POST de formulário HTML no painel: não devolver JSON cru no browser
                if (
                    p.startswith("/painel/")
                    and "/api/" not in p
                    and (token_form or request.accept_mimetypes.accept_html)
                ):
                    flash(
                        "Sessão expirada ou pedido inválido. Atualize a página (Ctrl+F5) e tente novamente.",
                        "error",
                    )
                    return redirect(request.referrer or "/login")
                return jsonify({"erro": "CSRF inválido ou ausente."}), 403

    # Entitlements/billing: bloquear ações pagas quando assinatura não estiver ok
    try:
        from flask_login import current_user
        if getattr(current_user, "is_authenticated", False) and current_user.is_authenticated:
            p = request.path or ""
            # Bypass: super_admin nunca deve ser bloqueado por billing (fail-safe por env)
            try:
                if bool(getattr(g, "admin_full_access", False)):
                    return None
            except Exception:
                pass
            # Sempre permitir billing/status/auth/páginas legais
            allow_prefixes = (
                # Billing precisa funcionar mesmo sem assinatura (para pagar e reativar)
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
                "/agenda",
                "/login",
                "/logout",
                # Páginas do painel: permitimos o dashboard para exibir o paywall,
                # mas não liberamos navegação livre em /painel/* sem assinatura ok.
                "/painel",
                "/perfil",
                "/static/",
                "/panel/static/",
                "/favicon.ico",
                "/sw.js",
                "/socket.io/",
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
                        # Audit log (somente quando a flag nova estiver ativa)
                        try:
                            if getattr(settings, "USE_NEW_AUTHZ_PIPELINE", False):
                                from services.authz.audit import log_authz_event
                                log_authz_event(
                                    allowed=False,
                                    reason=str(ent.reason or "billing_blocked"),
                                    role=str(getattr(g, "authz_role", "") or ""),
                                    role_source=str(getattr(g, "authz_role_source", "") or ""),
                                    tenant_id=str(cliente_id),
                                    subscription_status=str(ent.status or ""),
                                    route=p,
                                    method=request.method,
                                    request_id=str(getattr(g, "request_id", "") or ""),
                                )
                        except Exception:
                            pass
                        from flask import jsonify, url_for
                        if p.startswith("/api/"):
                            if getattr(ent, "status", "") == "onboarding":
                                erro = "Complete o onboarding adicionando cartão para ativar o trial e liberar o produto."
                            else:
                                erro = "Assinatura inativa. Atualize o pagamento para continuar."
                            return jsonify(
                                {
                                    "erro": erro,
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
                        # Não redirecionar para páginas públicas. Mantém o usuário no painel:
                        # o paywall é exibido via modal no `panel/templates/layout.html`.
                        # Evita loop: se já estamos no dashboard, permite renderizar.
                        if p in ("/painel", "/painel/"):
                            return None
                        return redirect(url_for("customer.dashboard"))

                    # Enforcement por feature (plano): exports e flow builder
                    if p.startswith("/painel/export/") and not can_access_feature(str(cliente_id), "exports"):
                        from flask import jsonify
                        return jsonify({"erro": "Seu plano não inclui exportações."}), 403
                    if p.startswith("/flow") and not can_access_feature(str(cliente_id), "flow_builder"):
                        from flask import jsonify
                        return jsonify({"erro": "Seu plano não inclui o Flow Builder."}), 403
                    # Audit log de allow (somente quando a flag nova estiver ativa)
                    try:
                        if getattr(settings, "USE_NEW_AUTHZ_PIPELINE", False):
                            from services.authz.audit import log_authz_event
                            log_authz_event(
                                allowed=True,
                                reason="ok",
                                role=str(getattr(g, "authz_role", "") or ""),
                                role_source=str(getattr(g, "authz_role_source", "") or ""),
                                tenant_id=str(cliente_id),
                                subscription_status=str(ent.status or ""),
                                route=p,
                                method=request.method,
                                request_id=str(getattr(g, "request_id", "") or ""),
                            )
                    except Exception:
                        pass
            else:
                # Está na allowlist: ainda assim, se o billing estiver bloqueado,
                # só permitimos o dashboard (/painel) e assets; impede acesso a /painel/*.
                try:
                    if p.startswith("/painel/") and p not in ("/painel", "/painel/"):
                        from base.auth import get_current_cliente_id
                        from services.entitlements import can_use_product
                        from flask import url_for

                        cliente_id = get_current_cliente_id(current_user)
                        if cliente_id:
                            ent = can_use_product(str(cliente_id))
                            if not ent.allowed:
                                try:
                                    if getattr(settings, "USE_NEW_AUTHZ_PIPELINE", False):
                                        from services.authz.audit import log_authz_event
                                        log_authz_event(
                                            allowed=False,
                                            reason=str(ent.reason or "billing_blocked_allowlist"),
                                            role=str(getattr(g, "authz_role", "") or ""),
                                            role_source=str(getattr(g, "authz_role_source", "") or ""),
                                            tenant_id=str(cliente_id),
                                            subscription_status=str(ent.status or ""),
                                            route=p,
                                            method=request.method,
                                            request_id=str(getattr(g, "request_id", "") or ""),
                                        )
                                except Exception:
                                    pass
                                return redirect(url_for("customer.dashboard"))
                except Exception:
                    pass
    except Exception:
        pass


@app.context_processor
def inject_admin():
    try:
        from flask_login import current_user
        current_cliente_id = None
        if getattr(current_user, "is_authenticated", False) and current_user.is_authenticated:
            current_cliente_id = get_current_cliente_id(current_user)
        return dict(is_admin=is_admin, is_admin_like=is_admin_like, current_cliente_id=current_cliente_id)
    except Exception:
        return dict(is_admin=is_admin, is_admin_like=is_admin_like, current_cliente_id=None)
app.register_blueprint(embed_bp)                         # /api/embed/key, rotate-key, send, message, poll, media
app.register_blueprint(meta_bp, url_prefix='/webhook')   # GET/POST /webhook/meta (WhatsApp, Instagram, Messenger)
app.register_blueprint(waha_webhook_bp, url_prefix='/webhook')  # POST /webhook/waha (eventos WAHA)
app.register_blueprint(
    agendamento_ia_appointments_bp, url_prefix="/webhook"
)  # POST /webhook/agendamento-ia/appointments


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
        from base.domain_redirects import redirect_to_app_login

        return redirect_to_app_login()
    try:
        from base.auth import get_current_cliente_id
        from services.entitlements import can_access_feature
        cliente_id = get_current_cliente_id(current_user)
        if cliente_id and not can_access_feature(str(cliente_id), "flow_builder"):
            flash("Seu plano não inclui o Flow Builder.", "error")
            return redirect(url_for("customer.dashboard"))
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
        # Execução local via `python app.py` (sem Gunicorn): permitir Werkzeug.
        # Em produção, o recomendado é iniciar via Gunicorn (gevent/eventlet), não por aqui.
        socketio.run(
            app,
            host="0.0.0.0",
            port=port,
            debug=use_debug,
            use_reloader=False,
            allow_unsafe_werkzeug=bool(use_debug) or (os.getenv("ALLOW_UNSAFE_WERKZEUG", "") == "1"),
        )
        
    except Exception as e:
        print(f"\n[ERRO CRITICO] {e}")
        import traceback
        traceback.print_exc()