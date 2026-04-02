# database/supabase_sq.py
from supabase import create_client, Client
from base.config import settings

# Clients Supabase:
# - `supabase`: SERVICE ROLE (chave completa) - usado apenas para operações server/admin/tabelas (RLS pode ser contornado).
# - `supabase_public`: ANON (pública) - usado para operações de autenticação do público (login/signup).

# Service role (admin)
try:
    if not settings.SUPABASE_URL or not settings.SUPABASE_KEY:
        raise ValueError("Configurações do Supabase (URL ou KEY) não encontradas no ambiente.")

    # create_client(url, key) — não passar options; algumas versões do supabase-py
    # falham com "'dict' object has no attribute 'headers'" ao usar options.
    supabase: Client = create_client(settings.SUPABASE_URL, settings.SUPABASE_KEY)
    print("[OK] Conexao com Supabase (service role) estabelecida com sucesso.")

except Exception as e:
    print(f"[ERRO] Erro ao conectar Supabase (service role): {e}")
    supabase = None

# Anon (public)
try:
    if not settings.SUPABASE_URL or not settings.SUPABASE_ANON_KEY:
        raise ValueError("Configurações do Supabase (URL ou ANON_KEY) não encontradas no ambiente.")
    supabase_public: Client = create_client(settings.SUPABASE_URL, settings.SUPABASE_ANON_KEY)
except Exception as e:
    # Não quebrar o app se ANON_KEY não estiver presente (caso de ambientes antigos).
    print(f"[WARN] Supabase anon (public) não configurado: {e}")
    supabase_public = None