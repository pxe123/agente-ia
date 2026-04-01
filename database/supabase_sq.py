# database/supabase_sq.py
from supabase import create_client, Client
from base.config import settings

# A instância do cliente Supabase é inicializada uma única vez para todo o sistema.
# O uso de 'settings' garante que as chaves URLs estão sempre corretas e limpas.
try:
    if not settings.SUPABASE_URL or not settings.SUPABASE_KEY:
        raise ValueError("Configurações do Supabase (URL ou KEY) não encontradas no ambiente.")

    # create_client(url, key) — não passar options; algumas versões do supabase-py
    # falham com "'dict' object has no attribute 'headers'" ao usar options.
    supabase: Client = create_client(settings.SUPABASE_URL, settings.SUPABASE_KEY)
    print("[OK] Conexao com Supabase estabelecida com sucesso.")

except Exception as e:
    print(f"[ERRO] Erro critico ao conectar ao Supabase: {e}")
    # Definimos como None para evitar que o app quebre no arranque, 
    # permitindo logs de erro mais claros.
    supabase = None