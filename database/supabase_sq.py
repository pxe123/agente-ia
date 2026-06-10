# database/supabase_sq.py
from supabase import create_client, Client
from base.config import settings

# Clients Supabase:
# - `supabase`: SERVICE ROLE (chave completa) - usado apenas para operações server/admin/tabelas (RLS pode ser contornado).
# - `supabase_public`: ANON (pública) - usado para operações de autenticação do público (login/signup).

_PLACEHOLDER_HINTS = ("your-", "changeme", "xxx", "paste", "example", "replace")


def _validate_supabase_key(key: str, label: str) -> None:
    if not key or len(key) < 20:
        raise ValueError(f"{label} ausente ou inválida (mín. 20 caracteres).")
    low = key.lower()
    if any(p in low for p in _PLACEHOLDER_HINTS):
        raise ValueError(f"{label} parece placeholder; use a chave real do dashboard Supabase.")


def supabase_config_diagnostics() -> dict:
    """Status das variáveis (sem expor valores das chaves)."""
    url = (settings.SUPABASE_URL or "").strip()
    service = (settings.SUPABASE_KEY or "").strip()
    anon = (settings.SUPABASE_ANON_KEY or "").strip()
    return {
        "env_file": getattr(settings, "ENV_FILE_PATH", None),
        "url_set": bool(url),
        "url_host": url.split("//")[1].split("/")[0] if "//" in url else "",
        "service_key_set": bool(service),
        "service_key_len": len(service) if service else 0,
        "anon_key_set": bool(anon),
        "anon_key_len": len(anon) if anon else 0,
        "jwt_secret_set": bool((settings.SUPABASE_JWT_SECRET or "").strip()),
    }


# Service role (admin)
try:
    if not settings.SUPABASE_URL:
        raise ValueError("SUPABASE_URL não encontrada no ambiente.")
    _validate_supabase_key(settings.SUPABASE_KEY, "SUPABASE_KEY (service role)")

    # create_client(url, key) — não passar options; algumas versões do supabase-py
    # falham com "'dict' object has no attribute 'headers'" ao usar options.
    supabase: Client = create_client(settings.SUPABASE_URL, settings.SUPABASE_KEY)
    print("[OK] Conexao com Supabase (service role) estabelecida com sucesso.")

except Exception as e:
    print(f"[ERRO] Erro ao conectar Supabase (service role): {e}")
    supabase = None

# Anon (public) — obrigatória para login Auth (header apikey na Auth API)
try:
    if not settings.SUPABASE_URL:
        raise ValueError("SUPABASE_URL não encontrada no ambiente.")
    _validate_supabase_key(settings.SUPABASE_ANON_KEY, "SUPABASE_ANON_KEY (anon)")

    supabase_public: Client = create_client(settings.SUPABASE_URL, settings.SUPABASE_ANON_KEY)
    print("[OK] Conexao com Supabase (anon / Auth) estabelecida com sucesso.")

except Exception as e:
    print(f"[WARN] Supabase anon (public) não configurado: {e}")
    print(
        "[WARN] Login e /nova-senha exigem SUPABASE_ANON_KEY "
        "(Supabase → Settings → API → anon public). "
        "Aliases aceitos: SUPABASE_PUBLISHABLE_KEY, NEXT_PUBLIC_SUPABASE_ANON_KEY."
    )
    supabase_public = None
