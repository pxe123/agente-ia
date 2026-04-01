# services/setores_helpers.py
"""
Helpers para visibilidade por setor: retorna quais conversas (remote_id) um usuário pode ver
e quais setor_ids ele pode acessar. Usado em buscar_mensagens, contatos_nao_lidos e atribuição.
"""


def _normalizar_remote_id(remote_id):
    if not remote_id:
        return ""
    s = str(remote_id).strip()
    if "@" in s:
        s = s.split("@")[0].strip()
    return s


from database.supabase_sq import supabase
from database.models import Tables, UsuarioInternoSetorModel, ConversacaoSetorModel


def get_setor_ids_for_user(cliente_id, user):
    """
    Retorna os setor_id (UUIDs) que o usuário pode acessar.
    - Se não for operador (dono da conta) ou for is_admin_cliente: retorna None (acesso a todos).
    - Se for operador: retorna lista de setor_id da tabela usuarios_internos_setores.
    """
    if not user or not getattr(user, "is_authenticated", False) or not user.is_authenticated:
        return None
    if not getattr(user, "operador_id", None):
        return None  # dono da conta: vê tudo
    if getattr(user, "is_admin_cliente", False):
        return None  # admin do cliente: vê tudo
    if not supabase:
        return []
    try:
        r = supabase.table(Tables.USUARIOS_INTERNOS_SETORES).select(
            UsuarioInternoSetorModel.SETOR_ID
        ).eq(UsuarioInternoSetorModel.USUARIO_INTERNO_ID, user.operador_id).execute()
        if not r.data:
            return []
        return [row.get(UsuarioInternoSetorModel.SETOR_ID) for row in r.data if row.get(UsuarioInternoSetorModel.SETOR_ID)]
    except Exception:
        return []


def get_allowed_remote_ids_for_canal(cliente_id, canal, user):
    """
    Retorna o conjunto de remote_id que o usuário pode ver no canal, ou None = todos.
    - Cliente principal ou admin: None (todos). Geral = vê tudo.
    - Operador: apenas remote_ids de conversas onde setor_id está nos setores do operador.
      Conversas em Geral (setor_id null) ou sem linha em painel_conversacao_setor só o admin vê.
    """
    setor_ids = get_setor_ids_for_user(cliente_id, user)
    if setor_ids is None:
        return None  # dono ou admin: vê todas as conversas
    if not supabase:
        return set()
    try:
        setor_ids_str = {str(s) for s in setor_ids}
        q = supabase.table(Tables.CONVERSACAO_SETOR).select(
            ConversacaoSetorModel.REMOTE_ID, ConversacaoSetorModel.SETOR_ID
        ).eq(ConversacaoSetorModel.CLIENTE_ID, str(cliente_id)).eq(ConversacaoSetorModel.CANAL, canal).execute()
        allowed = set()
        for row in (q.data or []):
            rid = _normalizar_remote_id(row.get(ConversacaoSetorModel.REMOTE_ID))
            sid = row.get(ConversacaoSetorModel.SETOR_ID)
            if not rid or sid is None:
                continue
            if str(sid) in setor_ids_str:
                allowed.add(rid)
        return allowed
    except Exception:
        return set()


def can_user_access_conversation(cliente_id, canal, remote_id, user):
    """True se o usuário pode ver/atender essa conversa (canal + remote_id)."""
    allowed = get_allowed_remote_ids_for_canal(cliente_id, canal, user)
    if allowed is None:
        return True
    return _normalizar_remote_id(remote_id) in allowed


def can_user_assign_to_setor(setor_id, user, cliente_id):
    """
    True se o usuário pode atribuir/transferir a conversa para esse setor.
    Dono e admin: sempre True. Operador: pode transferir para qualquer setor do cliente (incluindo Geral).
    """
    setor_ids = get_setor_ids_for_user(cliente_id, user)
    if setor_ids is None:
        return True  # dono ou admin
    if setor_id is None:
        return True  # transferir para Geral: todos que acessam a conversa podem
    if not supabase:
        return False
    try:
        from database.models import SetorModel
        r = supabase.table(Tables.SETORES).select(SetorModel.ID).eq(
            SetorModel.CLIENTE_ID, str(cliente_id)
        ).eq(SetorModel.ID, setor_id).limit(1).execute()
        return bool(r.data and len(r.data) > 0)
    except Exception:
        return False
