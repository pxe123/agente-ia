# core/config.py
import os
from dotenv import load_dotenv

# Garante que o .env seja buscado na raiz do projeto (onde fica app.py), não no cwd do processo.
# Em produção o cwd pode ser / ou outro; assim o .env é sempre encontrado.
_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_env_path = os.path.join(_root, ".env")
load_dotenv(_env_path, override=True)
# Exposto para diagnóstico (scripts/verify_supabase_env.py)
ENV_FILE_PATH = _env_path


def _first_env(*names: str) -> str:
    """Primeira variável de ambiente não vazia (aliases para deploy)."""
    for name in names:
        val = (os.getenv(name) or "").strip()
        if val:
            return val
    return ""


class Settings:
    """
    Centraliza todas as configurações do SaaS. 
    Se mudar uma chave no .env, todo o sistema atualiza automaticamente aqui.
    """

    ENV_FILE_PATH = _env_path

    # --- SUPABASE ---
    SUPABASE_URL = _first_env("SUPABASE_URL")
    # Service role (server-side). Aliases comuns em deploy/Docker.
    SUPABASE_KEY = _first_env(
        "SUPABASE_KEY",
        "SUPABASE_SERVICE_ROLE_KEY",
        "SUPABASE_SECRET_KEY",
    )
    # Chave anon (pública): login Auth, nova senha no browser. NUNCA use SUPABASE_KEY aqui.
    SUPABASE_ANON_KEY = _first_env(
        "SUPABASE_ANON_KEY",
        "SUPABASE_PUBLISHABLE_KEY",
        "NEXT_PUBLIC_SUPABASE_ANON_KEY",
        "VITE_SUPABASE_ANON_KEY",
    )
    # JWT Secret do projeto (Supabase: Settings → API → JWT Secret) para validar o token no backend
    SUPABASE_JWT_SECRET = os.getenv("SUPABASE_JWT_SECRET", "").strip()
    
    # --- OPENAI (Juliana.IA) ---
    OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")

    # --- WAHA (WhatsApp HTTP API) - opcional; se definido, envio WhatsApp usa WAHA em vez de Meta ---
    WAHA_URL = (os.getenv("WAHA_URL") or "").strip().rstrip("/")
    WAHA_API_KEY = (os.getenv("WAHA_API_KEY") or "").strip()
    # Apenas a origem (ex: https://api.seudominio.com.br). No app Meta use: WEBHOOK_URL + /webhook/meta
    WEBHOOK_URL = (os.getenv("WEBHOOK_URL") or "").strip().rstrip("/")
    
    # --- FLASK ---
    SECRET_KEY = (os.getenv("SECRET_KEY") or "").strip()
    if not SECRET_KEY:
        raise RuntimeError(
            "SECRET_KEY não definido no .env. "
            "Defina uma chave forte (32+ caracteres aleatórios) antes de iniciar a aplicação."
        )
    if len(SECRET_KEY) < 32 or "uma-chave-secreta" in SECRET_KEY.lower():
        import warnings
        warnings.warn(
            "SECRET_KEY parece fraca ou é o valor padrão. Gere uma chave aleatória: "
            "python -c \"import secrets; print(secrets.token_hex(32))\" e coloque no .env",
            UserWarning,
            stacklevel=2,
        )
    
    # --- SEGURANÇA ---
    ADMIN_EMAIL = os.getenv("ADMIN_EMAIL", "master@sistema.com")  # Centraliza o email do admin
    # Admins adicionais (lista separada por vírgula). Ex.: "a@x.com,b@y.com"
    # Observação: ADMIN_EMAIL também é incluído nessa lista automaticamente.
    ADMIN_EMAILS = [
        e.strip()
        for e in (os.getenv("ADMIN_EMAILS", "") or "").split(",")
        if e.strip()
    ]

    # Super-admin (bypass total): fail-safe por env para evitar lockout mesmo se DB/RLS estiverem fora.
    # Lista separada por vírgula. Ex.: "root@empresa.com,cto@empresa.com"
    SUPER_ADMIN_EMAILS = [
        e.strip()
        for e in (os.getenv("SUPER_ADMIN_EMAILS", "") or "").split(",")
        if e.strip()
    ]

    # Tenants (UUID em clientes.id) que ignoram billing/pending no backend inteiro.
    # Útil para a conta do dono da plataforma: webhooks WA/Meta não têm sessão Flask nem g.admin_full_access.
    # Lista separada por vírgula. Ex.: "uuid-do-seu-tenant,uuid-outro"
    SUPER_ADMIN_TENANT_IDS = [
        x.strip().lower()
        for x in (os.getenv("SUPER_ADMIN_TENANT_IDS", "") or "").split(",")
        if x.strip()
    ]

    # Feature flag: pipeline nova de autorização (role -> billing -> quota).
    # Default = false (mantém comportamento legado).
    USE_NEW_AUTHZ_PIPELINE = (os.getenv("USE_NEW_AUTHZ_PIPELINE") or "").strip().lower() in (
        "1",
        "true",
        "yes",
        "on",
    )

    # Feature flag: onboarding/signup com funil (plano -> cadastro -> checkout/cartão -> pending -> trialing -> active).
    # Por padrão, desativado para não quebrar clientes existentes.
    USE_ONBOARDING_FUNNEL = (os.getenv("USE_ONBOARDING_FUNNEL") or "").strip().lower() in (
        "1",
        "true",
        "yes",
        "on",
    )

    # --- CORS / ORIGENS PERMITIDAS ---
    # Ex.: CORS_ORIGINS="https://meupainel.com,https://app.cliente.com"
    CORS_ORIGINS = [
        o.strip() for o in os.getenv("CORS_ORIGINS", "").split(",") if o.strip()
    ]

    # --- META (WhatsApp Cloud, Instagram, Messenger) ---
    # Webhook: Meta envia GET com hub.mode, hub.verify_token, hub.challenge. Use META_VERIFY_TOKEN no app Meta.
    _meta_token = (os.getenv("META_VERIFY_TOKEN") or os.getenv("VERIFY_TOKEN") or "").strip().replace("\r", "").replace("\n", "")
    META_VERIFY_TOKEN = _meta_token
    META_APP_SECRET = os.getenv("META_APP_SECRET", "")  # OAuth e, se META_WEBHOOK_APP_SECRET não existir, assinatura do webhook
    META_WEBHOOK_APP_SECRET = os.getenv("META_WEBHOOK_APP_SECRET", "").strip()  # Opcional: chave do app que ENVIA o webhook (valida X-Hub-Signature-256)
    # OAuth: conectar WhatsApp sem colar token manualmente
    META_APP_ID = os.getenv("META_APP_ID", "").strip()
    META_OAUTH_REDIRECT_URI = os.getenv("META_OAUTH_REDIRECT_URI", "").strip()  # Ex: https://seu-dominio.com/meta/oauth/callback

    # --- WEB PUSH (notificações mesmo com aba em segundo plano) ---
    # Chaves VAPID: gere com python -c "from pywebpush import webpush; k=webpush.WebPushVAPID(); print('PRIVATE', k.private_key.decode()); print('PUBLIC', k.public_key.decode())"
    VAPID_PRIVATE_KEY = (os.getenv("VAPID_PRIVATE_KEY") or "").strip().replace("\\n", "\n")
    VAPID_PUBLIC_KEY = (os.getenv("VAPID_PUBLIC_KEY") or "").strip().replace("\\n", "\n")

    # --- BILLING (Stripe) ---
    STRIPE_SECRET_KEY = (os.getenv("STRIPE_SECRET_KEY") or "").strip()
    STRIPE_PUBLISHABLE_KEY = (os.getenv("STRIPE_PUBLISHABLE_KEY") or "").strip()
    STRIPE_WEBHOOK_SECRET = (os.getenv("STRIPE_WEBHOOK_SECRET") or "").strip()
    # Preços: fonte de verdade em plans (Supabase). stripe_price_id sincronizado via admin/API Stripe.
    # Checkout/Portal URLs
    STRIPE_SUCCESS_URL = (os.getenv("STRIPE_SUCCESS_URL") or "").strip()
    STRIPE_CANCEL_URL = (os.getenv("STRIPE_CANCEL_URL") or "").strip()
    STRIPE_PORTAL_RETURN_URL = (os.getenv("STRIPE_PORTAL_RETURN_URL") or "").strip()

    # Enforce billing/entitlements (legacy MP grace até period_end)
    BILLING_GRACE_DAYS = int(os.getenv("BILLING_GRACE_DAYS", "5") or "5")

    # --- AGENDAMENTO IA (serviço FastAPI externo: motor + link tokenizado) ---
    # Base canónica (ex.: https://agenda.zapaction.com.br). Deriva /v1/agendamento, /v1/link/generate, tenant-snapshot.
    AGENDAMENTO_IA_BASE_URL = (os.getenv("AGENDAMENTO_IA_BASE_URL") or "").strip().rstrip("/")
    # Host público nos links gerados (opcional; default = BASE_URL).
    AGENDAMENTO_IA_PUBLIC_BASE_URL = (os.getenv("AGENDAMENTO_IA_PUBLIC_BASE_URL") or "").strip().rstrip("/")
    AGENDAMENTO_IA_WEBHOOK_URL = (os.getenv("AGENDAMENTO_IA_WEBHOOK_URL") or "").strip()
    AGENDAMENTO_IA_LINK_GENERATE_URL = (os.getenv("AGENDAMENTO_IA_LINK_GENERATE_URL") or "").strip()
    AGENDAMENTO_IA_API_KEY = (os.getenv("AGENDAMENTO_IA_API_KEY") or "").strip()
    AGENDAMENTO_IA_TIMEOUT_SEC = int(os.getenv("AGENDAMENTO_IA_TIMEOUT_SEC", "25") or "25")
    AGENDAMENTO_IA_FALLBACK_MESSAGE = (
        os.getenv("AGENDAMENTO_IA_FALLBACK_MESSAGE")
        or "Não consegui concluir o agendamento agora. Tente de novo em instantes."
    ).strip() or "Não consegui concluir o agendamento agora. Tente de novo em instantes."
    # Painel → Agendamento IA: POST JSON ao guardar agenda (criar/atualizar clínica lá). Opcional.
    AGENDAMENTO_IA_CLINIC_SYNC_URL = (os.getenv("AGENDAMENTO_IA_CLINIC_SYNC_URL") or "").strip()
    AGENDAMENTO_IA_CLINIC_SYNC_API_KEY = (os.getenv("AGENDAMENTO_IA_CLINIC_SYNC_API_KEY") or "").strip()
    AGENDAMENTO_IA_CLINIC_SYNC_TIMEOUT_SEC = int(
        os.getenv("AGENDAMENTO_IA_CLINIC_SYNC_TIMEOUT_SEC", "30") or "30"
    )
    # Webhook reverso: Agendamento IA → ZapAction (POST /webhook/agendamento-ia/appointments).
    # Mesmo valor que ZAPACTION_WEBHOOK_SECRET no serviço Agendamento IA (HMAC §5.3 do plano técnico).
    ZAPACTION_WEBHOOK_SECRET = (os.getenv("ZAPACTION_WEBHOOK_SECRET") or "").strip()
    # Força motor interno de agenda (ignora webhook). Se false: interno só quando AGENDAMENTO_IA_WEBHOOK_URL vazio.
    USE_INTERNAL_SCHEDULING = (os.getenv("USE_INTERNAL_SCHEDULING") or "").strip().lower() in (
        "1",
        "true",
        "yes",
        "on",
    )
    # Rollout motor interno por tenant (UUIDs separados por vírgula). Ver docs/scheduling_internal_rollout_runbook.md
    SCHEDULING_INTERNAL_CLIENTE_IDS = (os.getenv("SCHEDULING_INTERNAL_CLIENTE_IDS") or "").strip()
    SCHEDULING_FORCE_AGENDA_CLIENTE_IDS = (os.getenv("SCHEDULING_FORCE_AGENDA_CLIENTE_IDS") or "").strip()
    SCHEDULING_REMINDERS_ENABLED = (os.getenv("SCHEDULING_REMINDERS_ENABLED") or "").strip().lower() in (
        "1",
        "true",
        "yes",
        "on",
    )
    SCHEDULING_REMINDER_HOURS_BEFORE = (os.getenv("SCHEDULING_REMINDER_HOURS_BEFORE") or "24").strip()

    # Google Calendar OAuth no painel ZapAction (login direto; tokens enviados ao Agenda via API)
    GOOGLE_CLIENT_ID = (os.getenv("GOOGLE_CLIENT_ID") or "").strip()
    GOOGLE_CLIENT_SECRET = (os.getenv("GOOGLE_CLIENT_SECRET") or "").strip()
    GOOGLE_OAUTH_REDIRECT_URI = (os.getenv("GOOGLE_OAUTH_REDIRECT_URI") or "").strip()

    # --- JOBS / FILA ---
    REDIS_URL = (os.getenv("REDIS_URL") or "").strip()

    # --- OBSERVABILIDADE ---
    SENTRY_DSN = (os.getenv("SENTRY_DSN") or "").strip()
    ENVIRONMENT = (os.getenv("ENVIRONMENT") or os.getenv("FLASK_ENV") or "").strip() or "development"

    # --- CADASTRO PÚBLICO (anti-bot) ---
    TURNSTILE_SITE_KEY = (os.getenv("TURNSTILE_SITE_KEY") or "").strip()
    TURNSTILE_SECRET_KEY = (os.getenv("TURNSTILE_SECRET_KEY") or "").strip()
    PUBLIC_SIGNUP_DISABLED = (os.getenv("PUBLIC_SIGNUP_DISABLED") or "").strip().lower() in (
        "1",
        "true",
        "yes",
        "on",
    )

    # --- HARDENING ---
    # Em produção, exigir assinaturas válidas em webhooks (Meta + Mercado Pago).
    REQUIRE_WEBHOOK_SIGNATURES = (os.getenv("REQUIRE_WEBHOOK_SIGNATURES") or "").strip().lower() in ("1", "true", "yes", "on")
    if os.getenv("FLASK_ENV") == "production" or os.getenv("PRODUCTION", "").lower() in ("1", "true", "yes"):
        # Default seguro em produção
        if os.getenv("REQUIRE_WEBHOOK_SIGNATURES") is None:
            REQUIRE_WEBHOOK_SIGNATURES = True

# Instância global para ser importada pelos outros módulos
settings = Settings()