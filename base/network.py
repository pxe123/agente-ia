import os
import requests
from base.config import settings

# 1. Configuração de Timeout Padrão
# Evita que o seu sistema fique "travado" se a API da Evolution ou OpenAI demorar a responder
DEFAULT_TIMEOUT = 15 

def get_session():
    """
    Cria uma sessão reutilizável do requests.
    Isso melhora a performance em produção pois mantém a conexão aberta (keep-alive).
    """
    session = requests.Session()
    # Se no futuro precisar de Headers globais, adicione aqui
    return session

# 2. Utilitário de Verificação de Saúde (Health Check)
def check_external_services():
    """
    Verifica se as URLs das APIs principais estão acessíveis.
    Útil para logs de inicialização.
    """
    try:
        if settings.SUPABASE_URL:
            requests.head(settings.SUPABASE_URL, timeout=5)
            print("Conexao com Supabase: OK")
        else:
            print("AVISO: SUPABASE_URL nao definido.")
    except Exception:
        print("AVISO: Supabase pode estar offline ou inacessivel.")

# 3. Blindagem de Rede (Opcional/Simplificada)
def apply_network_settings():
    """
    Caso note instabilidade no Windows durante o desenvolvimento, 
    pode reativar apenas o essencial aqui.
    """
    # Por agora, apenas garante que o log de rede está limpo
    pass