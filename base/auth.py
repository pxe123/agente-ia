# core/auth.py
from flask_login import UserMixin
from database.supabase_sq import supabase
from base.config import settings

# Prefixos no session id para distinguir cliente principal vs sublogin (operador)
_USER_ID_PREFIX_CLIENTE = "c:"
_USER_ID_PREFIX_OPERADOR = "o:"


# 1. Definição do Objeto de Utilizador (Normalizado)
# Suporta cliente principal (dono da conta) e sublogins (usuarios_internos).
# cliente_id = tenant (sempre preenchido). operador_id = preenchido apenas para sublogin.
class User(UserMixin):
    def __init__(self, id, email, plano='social', status_ia=True, ia_ativa=True, whatsapp_instancia=None,
                 acesso_whatsapp=True, acesso_instagram=True, acesso_messenger=True, acesso_site=True,
                 cliente_id=None, operador_id=None, nome=None, is_admin_cliente=False, acesso_menus=None):
        self.id = id
        self.email = email
        self.plano = plano
        self.status_ia = status_ia
        self.ia_ativa = ia_ativa
        self.whatsapp_instancia = whatsapp_instancia
        self.acesso_whatsapp = acesso_whatsapp if acesso_whatsapp is not None else True
        self.acesso_instagram = acesso_instagram if acesso_instagram is not None else True
        self.acesso_messenger = acesso_messenger if acesso_messenger is not None else True
        self.acesso_site = acesso_site if acesso_site is not None else True
        # Tenant: sempre o id do cliente (conta). Para sublogin, operador_id é o id do usuario_interno.
        self.cliente_id = cliente_id
        self.operador_id = operador_id
        self.nome = nome or ""
        self.is_admin_cliente = is_admin_cliente
        # Lista de chaves de menu que o sublogin pode ver/usar (chat, conexoes, chatbots, usuarios_setores). Dono ignora.
        self.acesso_menus = list(acesso_menus) if acesso_menus is not None else []

    def is_operador(self):
        """True se for sublogin (funcionário), False se for dono da conta."""
        return self.operador_id is not None

    def can_access_menu(self, menu_key):
        """True se pode ver/usar o menu. Dono sempre True; operador conforme acesso_menus."""
        if not self.is_operador():
            return True
        return menu_key in self.acesso_menus

    def can_manage_usuarios_setores(self):
        """True se pode gerenciar usuários internos e setores (dono da conta ou admin do cliente)."""
        return not self.is_operador() or bool(self.is_admin_cliente)

def _pk_from_cliente_row(u):
    """
    Retorna o identificador do cliente a ser usado como User.id.
    Deve ser sempre a chave primária da tabela (ex.: UUID), nunca o e-mail.
    Se a coluna 'id' vier como e-mail (schema incorreto), tenta uuid/cliente_uuid.
    """
    if not u:
        return None
    id_val = u.get("id")
    if id_val is None:
        return None
    s = str(id_val).strip()
    if "@" in s:
        return u.get("uuid") or u.get("cliente_uuid") or id_val
    return id_val


# Timeout para load_user: evita travar o worker quando o Supabase está lento (ex.: JWT/rede).
# Qualquer página que use current_user (inclusive a inicial /) chama load_user; sem timeout o app trava.
_LOAD_USER_TIMEOUT = 5


# Colunas usadas ao carregar o dono da conta.
# Importante: incluir `nome` para que o chat mostre o nome do perfil (e não o e-mail de login).
_CLIENTES_SELECT = "id,auth_id,nome,email,plano,whatsapp_instancia,acesso_whatsapp,acesso_instagram,acesso_messenger,acesso_site"


def _load_cliente_as_user_by_auth_id(auth_id_str):
    """Carrega o dono da conta pelo auth_id (Supabase). Flask-Login id = 'c:' + auth_id."""
    if supabase is None or not auth_id_str:
        return None
    try:
        res = supabase.table("clientes").select(_CLIENTES_SELECT).eq("auth_id", auth_id_str).execute()
    except Exception:
        return None
    if not res.data:
        return None
    u = res.data[0]
    pk = _pk_from_cliente_row(u)
    if pk is None:
        return None
    aid = u.get("auth_id")
    if not aid:
        return None
    session_id = _USER_ID_PREFIX_CLIENTE + str(aid).strip()
    return User(
        id=session_id,
        email=u.get('email') or '',
        plano=u.get('plano', 'social'),
        status_ia=u.get('status_ia', True),
        ia_ativa=u.get('ia_ativa', True),
        whatsapp_instancia=u.get('whatsapp_instancia'),
        acesso_whatsapp=u.get('acesso_whatsapp'),
        acesso_instagram=u.get('acesso_instagram'),
        acesso_messenger=u.get('acesso_messenger'),
        acesso_site=u.get('acesso_site'),
        cliente_id=pk,
        operador_id=None,
        nome=u.get("nome") or "",
        is_admin_cliente=False,
    )


def _load_cliente_as_user(cliente_pk):
    """Carrega dono pelo PK (id) — exige auth_id preenchido."""
    if supabase is None:
        return None
    try:
        res = supabase.table("clientes").select(_CLIENTES_SELECT).eq("id", cliente_pk).execute()
    except Exception:
        return None
    if not res.data:
        return None
    u = res.data[0]
    aid = u.get("auth_id")
    if not aid:
        return None
    return _load_cliente_as_user_by_auth_id(str(aid).strip())


def _load_operador_as_user(operador_id):
    """Carrega um usuario_interno pelo id e retorna User (sublogin) com cliente_id do tenant."""
    if supabase is None:
        return None
    try:
        from database.models import Tables, UsuarioInternoModel
        try:
            res = supabase.table(Tables.USUARIOS_INTERNOS).select(
                "id,cliente_id,nome,email_login,ativo,is_admin_cliente,acesso_menus"
            ).eq("id", operador_id).execute()
        except Exception:
            res = supabase.table(Tables.USUARIOS_INTERNOS).select(
                "id,cliente_id,nome,email_login,ativo,is_admin_cliente"
            ).eq("id", operador_id).execute()
        if not res.data:
            return None
        u = res.data[0]
        if not u.get("ativo"):
            return None
        cliente_id = u.get("cliente_id")
        if not cliente_id:
            return None
        res_c = supabase.table("clientes").select(_CLIENTES_SELECT).eq("id", cliente_id).execute()
        cliente = res_c.data[0] if res_c.data else {}
        session_id = _USER_ID_PREFIX_OPERADOR + str(u["id"])
        raw_menus = u.get("acesso_menus")
        if isinstance(raw_menus, list):
            acesso_menus = raw_menus
        elif raw_menus is not None:
            acesso_menus = list(raw_menus) if hasattr(raw_menus, "__iter__") and not isinstance(raw_menus, str) else []
        else:
            acesso_menus = []
        return User(
            id=session_id,
            email=u.get("email_login") or "",
            plano=cliente.get("plano", "social"),
            status_ia=cliente.get("status_ia", True),
            ia_ativa=cliente.get("ia_ativa", True),
            whatsapp_instancia=cliente.get("whatsapp_instancia"),
            acesso_whatsapp=cliente.get("acesso_whatsapp"),
            acesso_instagram=cliente.get("acesso_instagram"),
            acesso_messenger=cliente.get("acesso_messenger"),
            acesso_site=cliente.get("acesso_site"),
            cliente_id=cliente_id,
            operador_id=u["id"],
            nome=u.get("nome") or "",
            is_admin_cliente=bool(u.get("is_admin_cliente")),
            acesso_menus=acesso_menus,
        )
    except Exception:
        return None


def _load_user_from_supabase(user_id):
    """Chamada ao Supabase (para rodar com timeout). user_id vem do get_id(): 'c:uuid' ou 'o:uuid'."""
    if not user_id or not isinstance(user_id, str):
        return None
    user_id = user_id.strip()
    if user_id.startswith(_USER_ID_PREFIX_OPERADOR):
        operador_id = user_id[len(_USER_ID_PREFIX_OPERADOR):].strip()
        if operador_id:
            return _load_operador_as_user(operador_id)
        return None
    if user_id.startswith(_USER_ID_PREFIX_CLIENTE):
        auth_part = user_id[len(_USER_ID_PREFIX_CLIENTE):].strip()
        if auth_part:
            return _load_cliente_as_user_by_auth_id(auth_part)
        return None
    return _load_cliente_as_user_by_auth_id(user_id.strip())


# 2. O Carregador de Utilizador (User Loader)
# Esta função será chamada pelo Flask-Login em cada clique/página
def load_user_helper(user_id):
    """
    Busca os dados atualizados do cliente no Supabase.
    Com timeout para não travar o app quando o Supabase está lento.
    """
    import concurrent.futures
    try:
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as ex:
            fut = ex.submit(_load_user_from_supabase, user_id)
            return fut.result(timeout=_LOAD_USER_TIMEOUT)
    except concurrent.futures.TimeoutError:
        print(f"❌ load_user timeout ({_LOAD_USER_TIMEOUT}s) para user_id={user_id} – Supabase lento?", flush=True)
        return None
    except Exception as e:
        print(f"❌ Erro ao carregar utilizador no auth.py: {e}", flush=True)
        return None

def get_current_cliente_id(user):
    """
    Retorna o cliente_id (tenant) do usuário logado.
    Use em todas as rotas que precisam do dono da conta (cliente principal ou conta do operador).
    """
    if not user or not getattr(user, "is_authenticated", False) or not user.is_authenticated:
        return None
    return getattr(user, "cliente_id", None) or getattr(user, "id", None)


# 3. Verificadores de Permissão (Baseado no seu terminal.py)
def is_admin(user):
    """
    Verifica se o utilizador logado é o administrador mestre do sistema.
    O e-mail do admin é definido centralmente em base.config.Settings.ADMIN_EMAIL.
    Comparação normalizada (strip + case-insensitive) para coincidir com o cadastro no Supabase.
    """
    if not user or not getattr(user, "is_authenticated", False) or not user.is_authenticated:
        return False
    email = (getattr(user, "email", None) or "").strip().casefold()
    master = (getattr(settings, "ADMIN_EMAIL", None) or "").strip().casefold()
    return bool(email and master and email == master)