# core/config.py
import os
from dotenv import load_dotenv

# Garante que o .env seja buscado na raiz do projeto (onde fica app.py), não no cwd do processo.
# Em produção o cwd pode ser / ou outro; assim o .env é sempre encontrado.
_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_env_path = os.path.join(_root, ".env")
load_dotenv(_env_path, override=True)

class Settings:
    """
    Centraliza todas as configurações do SaaS. 
    Se mudar uma chave no .env, todo o sistema atualiza automaticamente aqui.
    """
    
    # --- SUPABASE ---
    SUPABASE_URL = os.getenv("SUPABASE_URL", "").strip()
    SUPABASE_KEY = os.getenv("SUPABASE_KEY", "").strip()
    # Chave anon (pública) para o frontend fazer login com Supabase Auth. NUNCA use SUPABASE_KEY aqui.
    SUPABASE_ANON_KEY = os.getenv("SUPABASE_ANON_KEY", "").strip()
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

    # --- BILLING (Mercado Pago) ---
    # Access token (server-side). Ex.: APP_USR-... (prod) ou TEST-... (sandbox)
    MERCADOPAGO_ACCESS_TOKEN = (os.getenv("MERCADOPAGO_ACCESS_TOKEN") or "").strip()
    # Secret de assinatura de webhooks (configurado no painel "Suas integrações" → Webhooks → Assinatura secreta)
    MERCADOPAGO_WEBHOOK_SECRET = (os.getenv("MERCADOPAGO_WEBHOOK_SECRET") or "").strip()
    # URLs de retorno do checkout/assinatura (usadas no preapproval)
    MERCADOPAGO_BACK_URL = (os.getenv("MERCADOPAGO_BACK_URL") or "").strip()
    MERCADOPAGO_SUCCESS_URL = (os.getenv("MERCADOPAGO_SUCCESS_URL") or "").strip()
    MERCADOPAGO_FAILURE_URL = (os.getenv("MERCADOPAGO_FAILURE_URL") or "").strip()
    MERCADOPAGO_PENDING_URL = (os.getenv("MERCADOPAGO_PENDING_URL") or "").strip()

    # Enforce billing/entitlements
    BILLING_GRACE_DAYS = int(os.getenv("BILLING_GRACE_DAYS", "5") or "5")

    # --- JOBS / FILA ---
    REDIS_URL = (os.getenv("REDIS_URL") or "").strip()

    # --- OBSERVABILIDADE ---
    SENTRY_DSN = (os.getenv("SENTRY_DSN") or "").strip()
    ENVIRONMENT = (os.getenv("ENVIRONMENT") or os.getenv("FLASK_ENV") or "").strip() or "development"

    # --- HARDENING ---
    # Em produção, exigir assinaturas válidas em webhooks (Meta + Mercado Pago).
    REQUIRE_WEBHOOK_SIGNATURES = (os.getenv("REQUIRE_WEBHOOK_SIGNATURES") or "").strip().lower() in ("1", "true", "yes", "on")
    if os.getenv("FLASK_ENV") == "production" or os.getenv("PRODUCTION", "").lower() in ("1", "true", "yes"):
        # Default seguro em produção
        if os.getenv("REQUIRE_WEBHOOK_SIGNATURES") is None:
            REQUIRE_WEBHOOK_SIGNATURES = True

# Instância global para ser importada pelos outros módulos
settings = Settings()