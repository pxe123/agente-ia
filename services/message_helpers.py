# services/message_helpers.py
"""
Helpers para mensagens: setor da conversa, detecção de base64 em texto.
Usado por MessageService e outros.
"""
from database.supabase_sq import supabase
from database.models import Tables


def get_conversacao_setor(cliente_id, canal, remote_id) -> str:
    """Retorna setor da conversa (atendimento_ia | atendimento_humano | atendimento_encerrado)."""
    if not supabase or not remote_id or not canal:
        return "atendimento_ia"
    try:
        r = supabase.table(Tables.CONVERSACAO_SETOR).select("setor").eq(
            "cliente_id", str(cliente_id)
        ).eq("canal", (canal or "whatsapp").strip().lower()).eq("remote_id", str(remote_id)).limit(1).execute()
        if r.data and len(r.data) > 0:
            return (r.data[0].get("setor") or "atendimento_ia").strip().lower()
    except Exception:
        pass
    return "atendimento_ia"


def parece_base64_imagem(texto: str) -> bool:
    """True se o texto parece ser dados de imagem em base64 (não exibir/salvar o blob bruto)."""
    if not texto or len(texto) < 80:
        return False
    s = texto.strip()
    if s.startswith("/9j/") or s.startswith("data:image/jpeg") or s.startswith("data:image/jpg"):
        return True
    if s.startswith("iVBORw0KGgo") or s.startswith("data:image/png"):
        return True
    if s.startswith("data:image/"):
        return True
    return False
