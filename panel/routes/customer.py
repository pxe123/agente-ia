import os
import json
import re
import secrets
import time
import uuid
from datetime import datetime, timezone
from flask import Blueprint, render_template, redirect, url_for, request, jsonify, flash, current_app, session
from flask_login import login_user, logout_user, login_required, current_user
from werkzeug.security import check_password_hash, generate_password_hash

from database.supabase_sq import supabase
from database.models import Tables, ClienteModel, FlowModel, ChatbotModel, FlowUserStateModel, LeadModel
from base.auth import User, get_current_cliente_id, _USER_ID_PREFIX_CLIENTE, _USER_ID_PREFIX_OPERADOR, _CLIENTES_SELECT
from base.template_helpers import with_embed_template_kwargs
from base.request_security import strip_untrusted_tenant_ids
from base.config import settings
from services.entitlements import can_access_feature, can_use_channel
from services.plans import list_active_plans
from services.flow_builder_helpers import (
    normalize_flow_json,
    flow_json_serializable,
    FLOW_CHANNELS,
)
#region agent debug log helper
_DEBUG_LOG_PATH = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "debug-1db042.log"))

def _agent_debug_log(hypothesis_id: str, location: str, message: str, data=None, run_id: str = "pre-debug") -> None:
    """Escreve NDJSON no debug-1db042.log (sem PII)."""
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
        with open(_DEBUG_LOG_PATH, "a", encoding="utf-8") as f:
            f.write(json.dumps(payload, ensure_ascii=False) + "\n")
    except Exception:
        pass
#endregion


# Rate limit login: por IP, máx 5 tentativas a cada 15 min
_LOGIN_ATTEMPTS = {}
_LOGIN_RATE_LIMIT = 5
_LOGIN_WINDOW_SEC = 15 * 60


def _login_rate_limit_exceeded(ip):
    now = time.time()
    if ip not in _LOGIN_ATTEMPTS:
        _LOGIN_ATTEMPTS[ip] = []
    # Remove tentativas fora da janela
    _LOGIN_ATTEMPTS[ip] = [t for t in _LOGIN_ATTEMPTS[ip] if now - t < _LOGIN_WINDOW_SEC]
    if len(_LOGIN_ATTEMPTS[ip]) >= _LOGIN_RATE_LIMIT:
        return True
    _LOGIN_ATTEMPTS[ip].append(now)
    return False


def _require_menu(menu_key):
    """Para operador (sublogin), exige permissão do menu. Retorna (response, status) se negado; (None, None) se permitido."""
    if not current_user.is_authenticated:
        return None, None
    if not getattr(current_user, "is_operador", lambda: False)():
        return None, None
    if getattr(current_user, "can_access_menu", lambda k: False)(menu_key):
        return None, None
    flash("Você não tem permissão para acessar esta página.", "error")
    return redirect(url_for("customer.dashboard")), 302


def _sanitize_meta_token(token: str) -> str:
    """
    Meta tokens às vezes são colados com 'Bearer ', aspas ou quebras de linha.
    Padroniza para só o token.
    """
    s = (token or "").strip()
    if not s:
        return ""
    if s.lower().startswith("bearer "):
        s = s.split(" ", 1)[1].strip()
    # remove aspas comuns ao copiar/colar
    s = s.strip("\"'`")
    # token nunca deve conter espaços/quebras de linha
    s = re.sub(r"\s+", "", s)
    return s

customer_bp = Blueprint(
    'customer',
    __name__,
    template_folder='../templates',
    static_folder='../static'
)

# --- ROTAS DE PÁGINAS ---
@customer_bp.route('/')
def index():
    """Página inicial pública (landing). Usuário logado é redirecionado ao painel."""
    if current_user.is_authenticated:
        return redirect(url_for('customer.dashboard'))
    # Landing principal é Jinja (mantém layout base e header). A landing React fica opcional em /landing-preview.
    plans = list_active_plans()
    return render_template('inicio.html', plans=plans)


@customer_bp.route("/landing-preview", methods=["GET"])
def landing_preview():
    """Preview opcional da landing React (não substitui a home)."""
    if current_user.is_authenticated:
        return redirect(url_for('customer.dashboard'))
    try:
        base_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
        landing_dir = os.path.join(base_dir, "panel", "static", "landing")
        index_path = os.path.join(landing_dir, "index.html")
        if os.path.isfile(index_path):
            from flask import send_from_directory
            return send_from_directory(landing_dir, "index.html")
    except Exception:
        pass
    return redirect(url_for("customer.index"))


@customer_bp.route("/landing/<path:path>")
def landing_assets(path):
    """
    Assets do build da landing premium (Vite base=/landing/).
    Mantém tudo fora de login/CSRF.
    """
    try:
        base_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
        landing_dir = os.path.join(base_dir, "panel", "static", "landing")
        from flask import send_from_directory
        return send_from_directory(landing_dir, path)
    except Exception:
        from flask import abort
        return abort(404)


@customer_bp.route('/painel')
@login_required
def dashboard():
    """
    Dashboard gerencial do painel.
    Mostra KPIs resumidos de atendimento para o cliente logado.
    """
    from database.supabase_sq import supabase
    from database.models import Tables, MensagemModel, LeadModel, UsuarioInternoModel

    is_dashboard_sublogin = getattr(current_user, "is_operador", lambda: False)()

    # Cliente "dono" da conta (para operadores usamos cliente_id associado)
    cliente_id = getattr(current_user, "cliente_id", None)
    # Se trial expirou ou assinatura inativa, manda para paywall (admin mestre ignora)
    try:
        from base.auth import is_admin
        from services.entitlements import can_use_product
        if cliente_id and not is_admin(current_user):
            ent = can_use_product(str(cliente_id))
            if not ent.allowed and ent.reason in ("trial_expirado", "assinatura_inativa", "assinatura_em_atraso"):
                return redirect(url_for("public.assinatura"))
    except Exception:
        pass

    # Filtro de período simples: últimos 7 dias
    from datetime import datetime, timedelta, timezone

    hoje_utc = datetime.now(timezone.utc)
    inicio_7d = hoje_utc - timedelta(days=7)

    kpis = {
        "total_mensagens_7d": 0,
        "total_conversas_7d": 0,
        "clientes_unicos_7d": 0,
        "total_leads_30d": 0,
        "total_leads_qualificados_30d": 0,
        "total_leads_desqualificados_30d": 0,
        "total_operadores": 0,
        "canais_distribuicao": {},
        "horas_distribuicao": {},
    }

    if supabase is not None and cliente_id:
        try:
            # Mensagens dos últimos 7 dias (apenas do cliente atual)
            res = (
                supabase.table(Tables.MENSAGENS)
                .select(
                    ",".join(
                        [
                            MensagemModel.REMOTE_ID,
                            MensagemModel.CANAL,
                            MensagemModel.FUNCAO,
                            MensagemModel.CRIADO_EM,
                        ]
                    )
                )
                .eq(MensagemModel.CLIENTE_ID, cliente_id)
                .gte(MensagemModel.CRIADO_EM, inicio_7d.isoformat())
                .execute()
            )
            msgs = res.data or []

            kpis["total_mensagens_7d"] = len(msgs)

            conversas_set = set()
            canais_contagem = {}
            horas_contagem = {}

            for m in msgs:
                remote_id = m.get(MensagemModel.REMOTE_ID)
                canal = m.get(MensagemModel.CANAL) or "desconhecido"
                created_raw = m.get(MensagemModel.CRIADO_EM)

                if remote_id:
                    conversas_set.add((canal, remote_id))

                canais_contagem[canal] = canais_contagem.get(canal, 0) + 1

                try:
                    # created_at vem em ISO 8601; usamos apenas a hora (0-23)
                    dt = datetime.fromisoformat(str(created_raw).replace("Z", "+00:00"))
                    hora = dt.hour
                    horas_contagem[hora] = horas_contagem.get(hora, 0) + 1
                except Exception:
                    continue

            kpis["total_conversas_7d"] = len(conversas_set)
            kpis["clientes_unicos_7d"] = len({rid for _canal, rid in conversas_set})
            kpis["canais_distribuicao"] = canais_contagem
            kpis["horas_distribuicao"] = horas_contagem
        except Exception:
            # Em caso de erro nos gráficos, o painel ainda carrega com valores neutros
            pass

        try:
            # Leads dos últimos 30 dias
            inicio_30d = hoje_utc - timedelta(days=30)
            res_leads = (
                supabase.table(Tables.LEADS)
                .select(LeadModel.ID)
                .eq(LeadModel.CLIENTE_ID, cliente_id)
                .gte(LeadModel.CREATED_AT, inicio_30d.isoformat())
                .execute()
            )
            kpis["total_leads_30d"] = len(res_leads.data or [])
            # Leads qualificados e desqualificados (30 dias)
            try:
                rq = supabase.table(Tables.LEADS).select(LeadModel.ID).eq(LeadModel.CLIENTE_ID, cliente_id).gte(LeadModel.CREATED_AT, inicio_30d.isoformat()).eq(LeadModel.STATUS, "qualificado").execute()
                kpis["total_leads_qualificados_30d"] = len(rq.data or [])
            except Exception:
                pass
            try:
                rd = supabase.table(Tables.LEADS).select(LeadModel.ID).eq(LeadModel.CLIENTE_ID, cliente_id).gte(LeadModel.CREATED_AT, inicio_30d.isoformat()).eq(LeadModel.STATUS, "desqualificado").execute()
                kpis["total_leads_desqualificados_30d"] = len(rd.data or [])
            except Exception:
                pass
        except Exception:
            pass

        try:
            # Quantidade de operadores/sublogins ativos
            res_ops = (
                supabase.table(Tables.USUARIOS_INTERNOS)
                .select(UsuarioInternoModel.ID)
                .eq(UsuarioInternoModel.CLIENTE_ID, cliente_id)
                .eq(UsuarioInternoModel.ATIVO, True)
                .execute()
            )
            kpis["total_operadores"] = len(res_ops.data or [])
        except Exception:
            pass

    billing_banner = None
    try:
        from base.auth import is_admin
        if cliente_id and not is_admin(current_user):
            from services.entitlements import get_billing_state
            st, _, trial_end, _ = get_billing_state(str(cliente_id))
            if st in ("inactive", "past_due", "canceled", "cancelled"):
                billing_banner = {"type": "danger", "status": st, "message": "Sua assinatura está inativa. Ative para continuar usando o sistema."}
            elif st == "trialing" and trial_end:
                from datetime import datetime, timezone
                now = datetime.now(timezone.utc)
                dias = int(max(0, (trial_end - now).total_seconds() // 86400))
                if dias <= 2:
                    billing_banner = {"type": "warning", "status": st, "message": f"Seu teste expira em {dias} dia(s). Ative a assinatura para não perder acesso."}
    except Exception:
        billing_banner = None

    return render_template(
        "dashboard.html",
        is_dashboard_sublogin=is_dashboard_sublogin,
        kpis=kpis,
        billing_banner=billing_banner,
    )

@customer_bp.route('/chat')
@login_required
def chat():
    resp, _ = _require_menu("chat")
    if resp is not None:
        return resp
    try:
        from base.auth import get_current_cliente_id
        cid = get_current_cliente_id(current_user)
        # Chat depende do canal; aqui só garantimos que pelo menos 1 canal está habilitado
        if cid and not any(
            can_use_channel(str(cid), k) for k in ("whatsapp", "instagram", "messenger", "website")
        ):
            return redirect(url_for("public.precos"))
    except Exception:
        pass
    return render_template('chat.html')

# Chaves que a página Conexões pode receber — nunca passar email, senha, mail ou outras colunas sensíveis
_CONEXOES_KEYS = (
    "meta_wa_phone_number_id", "meta_wa_token", "meta_ig_account_id", "meta_ig_page_id", "meta_ig_token",
    "meta_fb_page_id", "meta_fb_token", "embed_key",
)


@customer_bp.route('/conexoes')
@login_required
def conexoes():
    resp, _ = _require_menu("conexoes")
    if resp is not None:
        return resp
    try:
        from base.auth import get_current_cliente_id
        cid = get_current_cliente_id(current_user)
        if cid and not any(
            can_use_channel(str(cid), k) for k in ("whatsapp", "instagram", "messenger", "website")
        ):
            return redirect(url_for("public.precos"))
    except Exception:
        pass
    cliente = {}
    try:
        res = supabase.table("clientes").select(",".join(_CONEXOES_KEYS)).eq("id", get_current_cliente_id(current_user)).single().execute()
        if res.data:
            raw = res.data
            row = raw[0] if isinstance(raw, list) and len(raw) > 0 else raw
            if isinstance(row, dict):
                # Só passar as chaves de conexão; nunca mail, email, senha, etc.
                cliente = {k: row.get(k) for k in _CONEXOES_KEYS}
    except Exception:
        pass
    # Nunca exibir login/senha nos campos do Messenger: só Page ID (numérico) e Page Access Token (token Meta).
    from database.models import ClienteModel
    updates = {}
    fb_page_id = (cliente.get("meta_fb_page_id") or "").strip()
    if fb_page_id and "@" in fb_page_id:
        cliente["meta_fb_page_id"] = ""
        updates[ClienteModel.META_FB_PAGE_ID] = None
    fb_token = (cliente.get("meta_fb_token") or "").strip()
    if fb_token and fb_token.startswith(("pbkdf2:", "scrypt:", "argon2:", "bcrypt")):
        cliente["meta_fb_token"] = ""
        updates[ClienteModel.META_FB_TOKEN] = None
    if updates:
        try:
            supabase.table("clientes").update(updates).eq("id", get_current_cliente_id(current_user)).execute()
        except Exception:
            pass
    meta_connected = request.args.get("meta_connected")
    meta_error = request.args.get("meta_error")
    meta_oauth_available = bool(
        getattr(settings, "META_APP_ID", None) or os.getenv("META_APP_ID", "")
    )
    waha_configured = bool(getattr(settings, "WAHA_URL", None) and getattr(settings, "WAHA_API_KEY", None))
    return render_template(
        "conexoes.html",
        **with_embed_template_kwargs(
            cliente=cliente,
            meta_connected=meta_connected,
            meta_error=meta_error,
            meta_oauth_available=meta_oauth_available,
            waha_configured=waha_configured,
        ),
    )


@customer_bp.route('/fluxos')
@login_required
def fluxos():
    """Redireciona para Meus Chatbots (fluxo legado por canal removido)."""
    return redirect(url_for('customer.chatbots_list'))


@customer_bp.route('/leads')
@login_required
def leads_list():
    """Lista de leads do cliente com filtro por status e período; permite alterar status manualmente."""
    cliente_id = get_current_cliente_id(current_user)
    if not cliente_id:
        flash('Cliente não identificado.', 'danger')
        return redirect(url_for('customer.dashboard'))
    status_filter = (request.args.get('status') or '').strip().lower()
    if status_filter not in ('qualificado', 'desqualificado', 'pendente', ''):
        status_filter = ''
    canal_filter = (request.args.get('canal') or '').strip().lower()
    canais_validos = ('whatsapp', 'instagram', 'facebook', 'messenger', 'website')
    if canal_filter not in canais_validos:
        canal_filter = ''
    busca = (request.args.get('busca') or request.args.get('q') or '').strip()
    try:
        dias = int(request.args.get('dias') or '30')
    except ValueError:
        dias = 30
    if dias < 1:
        dias = 30
    if dias > 365:
        dias = 365
    from datetime import timedelta
    inicio = (datetime.now(timezone.utc) - timedelta(days=dias)).isoformat()
    if supabase is None:
        leads = []
    else:
        try:
            q = (
                supabase.table(Tables.LEADS)
                .select('id,nome,email,telefone,canal,created_at,status')
                .eq(LeadModel.CLIENTE_ID, cliente_id)
                .gte(LeadModel.CREATED_AT, inicio)
                .order(LeadModel.CREATED_AT, desc=True)
            )
            if status_filter:
                if status_filter == 'pendente':
                    q = q.or_(f"{LeadModel.STATUS}.is.null,{LeadModel.STATUS}.eq.pendente")
                else:
                    q = q.eq(LeadModel.STATUS, status_filter)
            if canal_filter:
                q = q.eq(LeadModel.CANAL, canal_filter)
            res = q.execute()
            leads = res.data or []
            if busca:
                termo = busca.lower()
                termo_tel = termo.replace(' ', '')
                leads = [
                    r for r in leads
                    if termo in (r.get(LeadModel.NOME) or '').lower()
                    or termo in (r.get(LeadModel.EMAIL) or '').lower()
                    or termo_tel in (r.get(LeadModel.TELEFONE) or '').replace(' ', '')
                ]
        except Exception as e:
            current_app.logger.warning("leads_list: %s", e)
            leads = []
    return render_template(
        'leads.html',
        leads=leads,
        status_filter=status_filter,
        canal_filter=canal_filter,
        busca=busca,
        dias=dias,
    )


@customer_bp.route('/chatbots')
@login_required
def chatbots_list():
    """Lista de chatbots do cliente (Meus Chatbots)."""
    resp, _ = _require_menu("chatbots")
    if resp is not None:
        return resp
    try:
        from base.auth import get_current_cliente_id
        cid = get_current_cliente_id(current_user)
        if cid and not can_access_feature(str(cid), "chatbots"):
            return redirect(url_for("public.precos"))
    except Exception:
        pass
    return render_template('chatbots.html')


@customer_bp.route('/chatbots/novo', methods=['GET', 'POST'])
@login_required
def chatbot_novo():
    """Criar novo chatbot: formulário e POST."""
    resp, _ = _require_menu("chatbots")
    if resp is not None:
        return resp
    cid_cb = str(get_current_cliente_id(current_user) or "")
    from services.plan_limits import get_chatbot_quota

    quota = get_chatbot_quota(cid_cb)
    if request.method == 'GET' and not quota["can_create"]:
        lim = quota.get("limit")
        used = quota.get("used", 0)
        flash(
            f"Limite do plano atingido ({used} de {lim} chatbot(s)). "
            "Exclua um chatbot na lista ou faça upgrade do plano para criar outro e editar o fluxo.",
            "error",
        )
        return redirect(url_for("customer.chatbots_list"))

    if request.method == 'POST':
        nome = (request.form.get('nome') or '').strip()
        if not nome:
            flash('Informe o nome do chatbot.', 'error')
            return render_template('chatbot_novo.html', quota=quota)
        if supabase is None:
            flash('Serviço indisponível. Tente mais tarde.', 'error')
            return render_template('chatbot_novo.html', quota=quota)
        from services.plan_limits import count_chatbots_cliente
        from services.entitlements import check_limit_reached

        if check_limit_reached(cid_cb, "max_chatbots", count_chatbots_cliente(cid_cb)):
            flash("Limite de chatbots atingido", "error")
            return render_template("chatbot_novo.html", quota=quota)
        try:
            now = datetime.now(timezone.utc).isoformat()
            payload = {
                ChatbotModel.CLIENTE_ID: get_current_cliente_id(current_user),
                ChatbotModel.NOME: nome,
                ChatbotModel.DESCRICAO: (request.form.get('descricao') or '').strip() or None,
                ChatbotModel.CHANNELS: [],
                ChatbotModel.UPDATED_AT: now,
            }
            r = supabase.table(Tables.CHATBOTS).insert(payload).execute()
            row = (r.data or [{}])[0] if r.data else {}
            cb_id = row.get(ChatbotModel.ID)
            if cb_id:
                flow_payload = {
                    FlowModel.CLIENTE_ID: get_current_cliente_id(current_user),
                    FlowModel.CHATBOT_ID: cb_id,
                    FlowModel.CHANNEL: "default",
                    FlowModel.NAME: nome,
                    FlowModel.FLOW_JSON: {"nodes": [], "edges": []},
                    FlowModel.UPDATED_AT: now,
                }
                supabase.table(Tables.FLOWS).insert(flow_payload).execute()
                flash('Chatbot criado. Clique em "Editar fluxo" para configurar.', 'success')
                return redirect(url_for('customer.chatbots_list'))
            flash('Falha ao criar chatbot.', 'error')
        except Exception as e:
            current_app.logger.exception("chatbot_novo")
            flash('Erro ao criar chatbot. Tente novamente.', 'error')
    return render_template('chatbot_novo.html', quota=quota)


@customer_bp.route('/chatbots/<chatbot_id>/fluxo')
@login_required
def chatbot_fluxo(chatbot_id):
    """Abre o canvas do flow builder para o chatbot (iframe)."""
    resp, _ = _require_menu("chatbots")
    if resp is not None:
        return resp
    if supabase is None:
        flash('Serviço indisponível.', 'error')
        return redirect(url_for('customer.chatbots_list'))
    try:
        r = supabase.table(Tables.CHATBOTS).select(ChatbotModel.ID, ChatbotModel.NOME, ChatbotModel.CHANNELS).eq(ChatbotModel.ID, chatbot_id).eq(ChatbotModel.CLIENTE_ID, get_current_cliente_id(current_user)).limit(1).execute()
        if not r.data or len(r.data) == 0:
            flash('Chatbot não encontrado.', 'error')
            return redirect(url_for('customer.chatbots_list'))
        row = r.data[0]
        nome = row.get(ChatbotModel.NOME, 'Chatbot')
        channels = row.get(ChatbotModel.CHANNELS) if isinstance(row.get(ChatbotModel.CHANNELS), list) else []
        return render_template('chatbot_fluxo.html', chatbot_id=chatbot_id, chatbot_nome=nome, channels=channels, channel_options=FLOW_CHANNELS)
    except Exception as e:
        current_app.logger.exception("chatbot_fluxo")
        flash('Erro ao abrir o editor.', 'error')
        return redirect(url_for('customer.chatbots_list'))


# --- WAHA (WhatsApp HTTP API) - Sessões/Instâncias ---
def _waha_enabled() -> bool:
    return bool(getattr(settings, "WAHA_URL", None) and getattr(settings, "WAHA_API_KEY", None))


def _waha_whatsapp_denied_response():
    """403 se plano ou kill switch global bloquear WhatsApp para o tenant logado."""
    cid = str(get_current_cliente_id(current_user) or "")
    if not cid or not can_use_channel(cid, "whatsapp"):
        return jsonify({"ok": False, "erro": "WhatsApp (WAHA) não está disponível no momento."}), 403
    return None


def _waha_tenant_id() -> str:
    return str(get_current_cliente_id(current_user) or "")


def _waha_is_session_owned(session_obj: dict, tenant_id: str) -> bool:
    if not isinstance(session_obj, dict):
        return False
    name = (session_obj.get("name") or "").strip()
    if not name:
        return False
    expected = _get_cliente_whatsapp_instancia(str(tenant_id or ""))
    return bool(expected) and expected == name


def _get_cliente_whatsapp_instancia(cliente_id: str) -> str:
    cid = str(cliente_id or "").strip()
    if not cid:
        return ""
    try:
        r = supabase.table(Tables.CLIENTES).select(ClienteModel.WHATSAPP_INSTANCIA).eq(ClienteModel.ID, cid).limit(1).execute()
        if r.data and len(r.data) > 0:
            return str(r.data[0].get(ClienteModel.WHATSAPP_INSTANCIA) or "").strip()
    except Exception:
        pass
    return ""


def _save_cliente_whatsapp_instancia(cliente_id: str, session_name: str) -> None:
    cid = str(cliente_id or "").strip()
    session = (session_name or "").strip()
    if not cid or not session:
        raise RuntimeError("cliente_id/sessão inválidos para persistir instância.")
    supabase.table(Tables.CLIENTES).update({ClienteModel.WHATSAPP_INSTANCIA: session}).eq(ClienteModel.ID, cid).execute()


def _generate_cliente_session_uuid() -> str:
    return f"wa_{uuid.uuid4().hex}"


def _resolve_or_create_cliente_waha_session() -> tuple[str, bool]:
    """
    Retorna (session_name, created_now):
    - se cliente já tem whatsapp_instancia, reutiliza
    - se não tem, gera UUID, salva e cria no WAHA
    """
    tenant_id = _waha_tenant_id()
    if not tenant_id:
        raise RuntimeError("Cliente não identificado.")
    from integrations.whatsapp import waha_client
    current = _get_cliente_whatsapp_instancia(tenant_id)
    created_now = False
    if not current:
        current = _generate_cliente_session_uuid()
        _save_cliente_whatsapp_instancia(tenant_id, current)
        created_now = True
    try:
        waha_client.ensure_session(current, tenant_id=tenant_id)
    except Exception:
        if created_now:
            raise
    return current, created_now


def _guard_session_ownership_or_403(requested_session: str):
    tenant_id = _waha_tenant_id()
    if not tenant_id:
        return jsonify({"ok": False, "erro": "Cliente não identificado."}), 401
    expected = _get_cliente_whatsapp_instancia(tenant_id)
    if not expected:
        return jsonify({"ok": False, "erro": "Instância WAHA ainda não criada para este cliente."}), 404
    if (requested_session or "").strip() != expected:
        return jsonify({"ok": False, "erro": "Sessão WAHA não pertence a este cliente."}), 403
    return None


@customer_bp.route("/api/waha/sessions", methods=["GET"])
@login_required
def api_waha_list_sessions():
    if not _waha_enabled():
        return jsonify({"ok": False, "erro": "WAHA não configurado no servidor."}), 400
    guard = _waha_whatsapp_denied_response()
    if guard is not None:
        return guard
    try:
        from integrations.whatsapp import waha_client
        tenant_id = _waha_tenant_id()
        session_name = _get_cliente_whatsapp_instancia(tenant_id)
        if not session_name:
            return jsonify({"ok": True, "sessions": []}), 200
        sess = waha_client.ensure_session(session_name, tenant_id=tenant_id)
        if not _waha_is_session_owned(sess, tenant_id):
            return jsonify({"ok": False, "erro": "Sessão WAHA não pertence ao cliente logado."}), 403
        return jsonify({"ok": True, "sessions": [sess]}), 200
    except Exception as e:
        current_app.logger.exception("api_waha_list_sessions")
        return jsonify({"ok": False, "erro": str(e)}), 500


@customer_bp.route("/api/waha/sessions", methods=["POST"])
@login_required
def api_waha_create_session():
    if not _waha_enabled():
        return jsonify({"ok": False, "erro": "WAHA não configurado no servidor."}), 400
    guard = _waha_whatsapp_denied_response()
    if guard is not None:
        return guard
    try:
        from integrations.whatsapp import waha_client
        session_name, created_now = _resolve_or_create_cliente_waha_session()
        sess = waha_client.ensure_session(session_name, tenant_id=_waha_tenant_id())
        return jsonify({"ok": True, "session": sess, "created_now": created_now, "session_name": session_name}), 200
    except Exception as e:
        current_app.logger.exception("api_waha_create_session")
        msg = str(e)
        return jsonify({"ok": False, "erro": msg}), 400


@customer_bp.route("/api/waha/sessions/<session>/qr", methods=["GET"])
@login_required
def api_waha_get_qr(session: str):
    if not _waha_enabled():
        return jsonify({"ok": False, "erro": "WAHA não configurado no servidor."}), 400
    try:
        from integrations.whatsapp import waha_client
        guard = _guard_session_ownership_or_403(session)
        if guard is not None:
            return guard
        sess = waha_client.get_session(session)
        status = str(sess.get("status") or "").upper() if isinstance(sess, dict) else ""
        if status == "FAILED":
            sess = waha_client.recover_session(session)
        qr = waha_client.get_qr_base64(session)
        if not qr.get("data"):
            return jsonify({"ok": False, "erro": "QR indisponível (a sessão pode não estar em SCAN_QR_CODE)."}), 400
        return jsonify({"ok": True, "qr": qr, "status": sess.get("status") if isinstance(sess, dict) else None}), 200
    except Exception as e:
        current_app.logger.exception("api_waha_get_qr")
        return jsonify({"ok": False, "erro": str(e)}), 400


@customer_bp.route("/api/waha/sessions/<session>/restart", methods=["POST"])
@login_required
def api_waha_restart(session: str):
    if not _waha_enabled():
        return jsonify({"ok": False, "erro": "WAHA não configurado no servidor."}), 400
    try:
        from integrations.whatsapp import waha_client
        guard = _guard_session_ownership_or_403(session)
        if guard is not None:
            return guard
        out = waha_client.restart_session(session)
        return jsonify({"ok": True, "session": out}), 200
    except Exception as e:
        current_app.logger.exception("api_waha_restart")
        return jsonify({"ok": False, "erro": str(e)}), 400


@customer_bp.route("/api/waha/sessions/<session>/logout", methods=["POST"])
@login_required
def api_waha_logout(session: str):
    if not _waha_enabled():
        return jsonify({"ok": False, "erro": "WAHA não configurado no servidor."}), 400
    try:
        from integrations.whatsapp import waha_client
        guard = _guard_session_ownership_or_403(session)
        if guard is not None:
            return guard
        out = waha_client.logout_session(session)
        return jsonify({"ok": True, "session": out}), 200
    except Exception as e:
        current_app.logger.exception("api_waha_logout")
        return jsonify({"ok": False, "erro": str(e)}), 400


@customer_bp.route("/api/waha/chats/overview", methods=["GET"])
@login_required
def api_waha_chats_overview():
    """Retorna nome e foto dos chats WhatsApp (GET /api/{session}/chats/overview) para exibir no painel."""
    if not _waha_enabled():
        return jsonify({"chats": []}), 200
    cid_ov = str(get_current_cliente_id(current_user) or "")
    if not cid_ov or not can_use_channel(cid_ov, "whatsapp"):
        return jsonify({"chats": []}), 200
    try:
        from integrations.whatsapp import waha_client
        tenant_id = _waha_tenant_id()
        session_name = _get_cliente_whatsapp_instancia(tenant_id)
        if not session_name:
            return jsonify({"chats": []}), 200
        limit = request.args.get("limit", 100, type=int)
        offset = request.args.get("offset", 0, type=int)
        chats = waha_client.get_chats_overview(session=session_name, limit=min(limit, 200), offset=offset)
        return jsonify({"chats": chats}), 200
    except Exception as e:
        current_app.logger.warning("api_waha_chats_overview: %s", e)
        return jsonify({"chats": []}), 200


@customer_bp.route('/api/conexoes/whatsapp', methods=['POST'])
@login_required
def api_salvar_whatsapp():
    """Salva meta_wa_phone_number_id e meta_wa_token do cliente logado. Token vazio = não alterar."""
    from database.models import ClienteModel
    data = strip_untrusted_tenant_ids(request.json or request.form or {})
    phone_id = (data.get('meta_wa_phone_number_id') or data.get('phone_number_id') or '').strip()
    token = (data.get('meta_wa_token') or data.get('token') or '').strip()
    payload = {}
    payload[ClienteModel.META_WA_PHONE_NUMBER_ID] = phone_id or None
    if token:
        payload[ClienteModel.META_WA_TOKEN] = token
    try:
        supabase.table("clientes").update(payload).eq("id", get_current_cliente_id(current_user)).execute()
        flash("WhatsApp (Meta) atualizado com sucesso.", "success")
        return jsonify({"status": "sucesso"}), 200
    except Exception as e:
        return jsonify({"status": "erro", "mensagem": str(e)}), 500


@customer_bp.route('/api/conexoes/instagram', methods=['POST'])
@login_required
def api_salvar_instagram():
    """Salva meta_ig_account_id (ID do Instagram), meta_ig_page_id (ID da página Facebook) e meta_ig_token do cliente logado."""
    from database.models import ClienteModel
    cid = str(get_current_cliente_id(current_user) or "")
    if cid and not can_use_channel(cid, "instagram"):
        return jsonify({"status": "erro", "mensagem": "Instagram não está disponível no momento."}), 400
    data = strip_untrusted_tenant_ids(request.json or request.form or {})
    ig_account_id = (data.get('meta_ig_account_id') or '').strip() or None
    page_id = (data.get('meta_ig_page_id') or '').strip() or None
    token = _sanitize_meta_token(data.get('meta_ig_token') or '')
    payload = {
        ClienteModel.META_IG_ACCOUNT_ID: ig_account_id,
        ClienteModel.META_IG_PAGE_ID: page_id,
    }
    if token:
        payload[ClienteModel.META_IG_TOKEN] = token
    try:
        supabase.table("clientes").update(payload).eq("id", get_current_cliente_id(current_user)).execute()
        flash("Instagram (Meta) atualizado com sucesso.", "success")
        return jsonify({"status": "sucesso"}), 200
    except Exception as e:
        return jsonify({"status": "erro", "mensagem": str(e)}), 500


@customer_bp.route('/api/conexoes/facebook', methods=['POST'])
@login_required
def api_salvar_facebook():
    """Salva meta_fb_page_id e meta_fb_token do cliente logado. Page ID deve ser numérico (ID da página Meta), nunca e-mail."""
    from database.models import ClienteModel
    cid = str(get_current_cliente_id(current_user) or "")
    if cid and not can_use_channel(cid, "facebook"):
        return jsonify({"status": "erro", "mensagem": "Messenger não está disponível no momento."}), 400
    data = strip_untrusted_tenant_ids(request.json or request.form or {})
    page_id = (data.get('meta_fb_page_id') or '').strip()
    if page_id and "@" in page_id:
        return jsonify({"status": "erro", "mensagem": "Use o ID numérico da página (Page ID), não o e-mail. Obtenha no Graph API Explorer ou na Meta Business Suite."}), 400
    token = _sanitize_meta_token(data.get('meta_fb_token') or '')
    payload = {ClienteModel.META_FB_PAGE_ID: page_id or None}
    if token:
        payload[ClienteModel.META_FB_TOKEN] = token
    try:
        supabase.table("clientes").update(payload).eq("id", get_current_cliente_id(current_user)).execute()
        flash("Facebook Messenger (Meta) atualizado com sucesso.", "success")
        return jsonify({"status": "sucesso"}), 200
    except Exception as e:
        return jsonify({"status": "erro", "mensagem": str(e)}), 500


@customer_bp.route('/api/conexoes/whatsapp/desconectar', methods=['POST'])
@login_required
def api_desconectar_whatsapp():
    """Remove phone_number_id e token do WhatsApp do cliente (limpa dados no banco)."""
    from database.models import ClienteModel
    try:
        supabase.table("clientes").update({
            ClienteModel.META_WA_PHONE_NUMBER_ID: None,
            ClienteModel.META_WA_TOKEN: None,
        }).eq("id", get_current_cliente_id(current_user)).execute()
        return jsonify({"status": "sucesso"}), 200
    except Exception as e:
        return jsonify({"status": "erro", "mensagem": str(e)}), 500


@customer_bp.route('/api/conexoes/instagram/desconectar', methods=['POST'])
@login_required
def api_desconectar_instagram():
    """Remove page_id e token do Instagram do cliente (limpa dados no banco)."""
    from database.models import ClienteModel
    try:
        supabase.table("clientes").update({
            ClienteModel.META_IG_PAGE_ID: None,
            ClienteModel.META_IG_TOKEN: None,
        }).eq("id", get_current_cliente_id(current_user)).execute()
        return jsonify({"status": "sucesso"}), 200
    except Exception as e:
        return jsonify({"status": "erro", "mensagem": str(e)}), 500


@customer_bp.route('/api/conexoes/facebook/desconectar', methods=['POST'])
@login_required
def api_desconectar_facebook():
    """Remove page_id e token do Messenger do cliente (limpa dados no banco)."""
    from database.models import ClienteModel
    try:
        supabase.table("clientes").update({
            ClienteModel.META_FB_PAGE_ID: None,
            ClienteModel.META_FB_TOKEN: None,
        }).eq("id", get_current_cliente_id(current_user)).execute()
        return jsonify({"status": "sucesso"}), 200
    except Exception as e:
        return jsonify({"status": "erro", "mensagem": str(e)}), 500


def _load_perfil_data():
    """Carrega dados do cliente e conta_desde para o template de perfil (dono da conta)."""
    try:
        res = supabase.table("clientes").select("*").eq("id", get_current_cliente_id(current_user)).single().execute()
        cliente = res.data if res.data else {}
    except Exception:
        cliente = {}
    created = cliente.get("created_at") or cliente.get("criado_em")
    conta_desde = "—"
    if created:
        try:
            d = datetime.fromisoformat(str(created).replace("Z", "+00:00"))
            conta_desde = d.strftime("%d/%m/%Y")
        except Exception:
            conta_desde = str(created)[:10] if created else "—"
    return cliente, conta_desde


def _load_perfil_sublogin():
    """Carrega dados do usuario_interno para o template de perfil (sublogin). Retorna dict com nome, email, conta_desde."""
    if not getattr(current_user, "operador_id", None):
        return None
    try:
        from database.models import Tables, UsuarioInternoModel
        res = supabase.table(Tables.USUARIOS_INTERNOS).select("nome,email_login,created_at").eq(UsuarioInternoModel.ID, current_user.operador_id).limit(1).execute()
        if not res.data or len(res.data) == 0:
            return None
        u = res.data[0]
        created = u.get("created_at")
        conta_desde = "—"
        if created:
            try:
                d = datetime.fromisoformat(str(created).replace("Z", "+00:00"))
                conta_desde = d.strftime("%d/%m/%Y")
            except Exception:
                conta_desde = str(created)[:10] if created else "—"
        return {
            "nome": u.get("nome") or "",
            "email": u.get("email_login") or current_user.email or "",
            "conta_desde": conta_desde,
        }
    except Exception:
        return None


@customer_bp.route('/perfil', methods=['GET'])
@login_required
def perfil():
    if current_user.is_operador():
        perfil_data = _load_perfil_sublogin()
        if not perfil_data:
            perfil_data = {"nome": getattr(current_user, "nome", "") or "", "email": getattr(current_user, "email", ""), "conta_desde": "—"}
        return render_template(
            "perfil.html",
            **with_embed_template_kwargs(
                is_perfil_sublogin=True,
                perfil=perfil_data,
                cliente=perfil_data,
                conta_desde=perfil_data.get("conta_desde", "—"),
            ),
        )
    cliente, conta_desde = _load_perfil_data()
    if not cliente:
        cliente = {"email": getattr(current_user, "email", "")}
    return render_template(
        "perfil.html",
        **with_embed_template_kwargs(
            is_perfil_sublogin=False,
            perfil=None,
            cliente=cliente,
            conta_desde=conta_desde,
        ),
    )


@customer_bp.route('/perfil', methods=['POST'])
@login_required
def perfil_post():
    nome = (request.form.get("nome") or "").strip()
    nova_senha = request.form.get("nova_senha") or ""
    nova_senha2 = request.form.get("nova_senha2") or ""

    if current_user.is_operador():
        perfil_data = _load_perfil_sublogin() or {}
        if nome is not None:
            perfil_data["nome"] = nome
        if nova_senha:
            if len(nova_senha) < 6:
                return render_template(
                    "perfil.html",
                    **with_embed_template_kwargs(
                        is_perfil_sublogin=True,
                        perfil=perfil_data,
                        cliente=perfil_data,
                        conta_desde=perfil_data.get("conta_desde", "—"),
                        mensagem="Nova senha deve ter no mínimo 6 caracteres.",
                        erro=True,
                    ),
                )
            if nova_senha != nova_senha2:
                return render_template(
                    "perfil.html",
                    **with_embed_template_kwargs(
                        is_perfil_sublogin=True,
                        perfil=perfil_data,
                        cliente=perfil_data,
                        conta_desde=perfil_data.get("conta_desde", "—"),
                        mensagem="As senhas não coincidem.",
                        erro=True,
                    ),
                )
        from database.models import Tables, UsuarioInternoModel
        payload = {UsuarioInternoModel.UPDATED_AT: datetime.now(timezone.utc).isoformat()}
        if nome is not None:
            payload[UsuarioInternoModel.NOME] = nome or None
        if nova_senha:
            payload[UsuarioInternoModel.SENHA] = generate_password_hash(nova_senha, method="pbkdf2:sha256")
        if len(payload) > 1:
            try:
                supabase.table(Tables.USUARIOS_INTERNOS).update(payload).eq(UsuarioInternoModel.ID, current_user.operador_id).execute()
                flash("Perfil atualizado com sucesso.", "success")
            except Exception as e:
                return render_template(
                    "perfil.html",
                    **with_embed_template_kwargs(
                        is_perfil_sublogin=True,
                        perfil=perfil_data,
                        cliente=perfil_data,
                        conta_desde=perfil_data.get("conta_desde", "—"),
                        mensagem="Erro ao atualizar: " + str(e),
                        erro=True,
                    ),
                )
        return redirect(url_for("customer.perfil"))

    from database.models import ClienteModel
    cliente, conta_desde = _load_perfil_data()
    if nome is not None:
        cliente["nome"] = nome
    if nova_senha:
        if len(nova_senha) < 6:
            return render_template(
                "perfil.html",
                **with_embed_template_kwargs(
                    is_perfil_sublogin=False,
                    perfil=None,
                    cliente=cliente,
                    conta_desde=conta_desde,
                    mensagem="Nova senha deve ter no mínimo 6 caracteres.",
                    erro=True,
                ),
            )
        if nova_senha != nova_senha2:
            return render_template(
                "perfil.html",
                **with_embed_template_kwargs(
                    is_perfil_sublogin=False,
                    perfil=None,
                    cliente=cliente,
                    conta_desde=conta_desde,
                    mensagem="As senhas não coincidem.",
                    erro=True,
                ),
            )
    payload = {}
    if nome is not None:
        payload[ClienteModel.NOME] = nome
    if nova_senha:
        payload[ClienteModel.SENHA] = generate_password_hash(nova_senha, method="pbkdf2:sha256")
    if payload:
        try:
            supabase.table("clientes").update(payload).eq("id", get_current_cliente_id(current_user)).execute()
            flash("Perfil atualizado com sucesso.", "success")
        except Exception as e:
            if ClienteModel.NOME in payload and ("nome" in str(e).lower() or "column" in str(e).lower()):
                del payload[ClienteModel.NOME]
                try:
                    supabase.table("clientes").update(payload).eq("id", get_current_cliente_id(current_user)).execute()
                    flash("Perfil atualizado (nome não salvo: coluna não existe no banco).", "success")
                except Exception as e2:
                    return render_template(
                        "perfil.html",
                        **with_embed_template_kwargs(
                            is_perfil_sublogin=False,
                            perfil=None,
                            cliente=cliente,
                            conta_desde=conta_desde,
                            mensagem="Erro ao atualizar: " + str(e2),
                            erro=True,
                        ),
                    )
            else:
                return render_template(
                    "perfil.html",
                    **with_embed_template_kwargs(
                        is_perfil_sublogin=False,
                        perfil=None,
                        cliente=cliente,
                        conta_desde=conta_desde,
                        mensagem="Erro ao atualizar: " + str(e),
                        erro=True,
                    ),
                )
    return redirect(url_for("customer.perfil"))


# --- Usuários e setores (sublogins e áreas de atuação) ---
# Chaves de permissão de menu para sublogins (acesso_menus em usuarios_internos)
MENU_KEYS_VALIDOS = frozenset(("chat", "conexoes", "chatbots", "usuarios_setores"))


def _normalize_acesso_menus(raw):
    """Retorna lista de strings válidas para acesso_menus; inválidas são ignoradas."""
    if not raw or not isinstance(raw, list):
        return []
    return [str(x).strip() for x in raw if str(x).strip() in MENU_KEYS_VALIDOS]


def _require_can_view_usuarios_setores():
    """Permite ver listas se dono ou operador com permissão do menu usuarios_setores. Retorna (resp, code) se negado."""
    if not current_user.is_authenticated:
        return jsonify({"erro": "Não autenticado."}), 401
    if not getattr(current_user, "is_operador", lambda: False)():
        return None, None
    if getattr(current_user, "can_access_menu", lambda k: False)("usuarios_setores"):
        return None, None
    return jsonify({"erro": "Sem permissão para acessar usuários e setores."}), 403


def _require_can_list_setores():
    """Permite listar setores (ex.: dropdown do chat) se dono ou operador com chat ou usuarios_setores. Retorna (resp, code) se negado."""
    if not current_user.is_authenticated:
        return jsonify({"erro": "Não autenticado."}), 401
    if not getattr(current_user, "is_operador", lambda: False)():
        return None, None
    if getattr(current_user, "can_access_menu", lambda k: False)("chat"):
        return None, None
    if getattr(current_user, "can_access_menu", lambda k: False)("usuarios_setores"):
        return None, None
    return jsonify({"erro": "Sem permissão para listar setores."}), 403


def _require_can_manage_usuarios_setores():
    """Retorna (response, status) se o usuário não pode gerenciar; (None, None) se pode."""
    if not getattr(current_user, "can_manage_usuarios_setores", lambda: False)():
        return jsonify({"erro": "Sem permissão para gerenciar usuários e setores."}), 403
    return None, None


@customer_bp.route('/usuarios-setores')
@login_required
def usuarios_setores():
    """Página de gestão de setores e usuários internos (sublogins). Operador precisa de permissão do menu; criar/editar/excluir exige can_manage (APIs)."""
    resp, _ = _require_menu("usuarios_setores")
    if resp is not None:
        return resp
    return render_template("usuarios_setores.html")


@customer_bp.route('/api/setores', methods=['GET'])
@login_required
def api_setores_list():
    if supabase is None:
        return jsonify({"erro": "Serviço indisponível."}), 503
    resp, code = _require_can_list_setores()
    if resp is not None:
        return resp, code
    try:
        from database.models import Tables, SetorModel
        r = supabase.table(Tables.SETORES).select("*").eq(SetorModel.CLIENTE_ID, get_current_cliente_id(current_user)).order(SetorModel.CREATED_AT, desc=True).execute()
        return jsonify({"setores": r.data or []}), 200
    except Exception as e:
        current_app.logger.warning("api_setores_list: %s", e)
        return jsonify({"erro": str(e)}), 500


@customer_bp.route('/api/setores', methods=['POST'])
@login_required
def api_setores_create():
    if supabase is None:
        return jsonify({"erro": "Serviço indisponível."}), 503
    resp, code = _require_can_manage_usuarios_setores()
    if resp is not None:
        return resp, code
    data = strip_untrusted_tenant_ids(request.get_json() or {})
    nome = (data.get("nome") or "").strip()
    if not nome:
        return jsonify({"erro": "Nome do setor é obrigatório."}), 400
    try:
        from database.models import Tables, SetorModel
        now = datetime.now(timezone.utc).isoformat()
        payload = {
            SetorModel.CLIENTE_ID: get_current_cliente_id(current_user),
            SetorModel.NOME: nome,
            SetorModel.ATIVO: True,
            SetorModel.UPDATED_AT: now,
        }
        r = supabase.table(Tables.SETORES).insert(payload).execute()
        row = (r.data or [{}])[0]
        return jsonify({"ok": True, "setor": row}), 201
    except Exception as e:
        current_app.logger.warning("api_setores_create: %s", e)
        return jsonify({"erro": str(e)}), 500


@customer_bp.route('/api/setores/<setor_id>', methods=['PATCH'])
@login_required
def api_setores_patch(setor_id):
    if supabase is None:
        return jsonify({"erro": "Serviço indisponível."}), 503
    resp, code = _require_can_manage_usuarios_setores()
    if resp is not None:
        return resp, code
    data = strip_untrusted_tenant_ids(request.get_json() or {})
    try:
        from database.models import Tables, SetorModel
        cliente_id = get_current_cliente_id(current_user)
        r = supabase.table(Tables.SETORES).select(SetorModel.ID).eq(SetorModel.ID, setor_id).eq(SetorModel.CLIENTE_ID, cliente_id).limit(1).execute()
        if not r.data or len(r.data) == 0:
            return jsonify({"erro": "Setor não encontrado."}), 404
        payload = {SetorModel.UPDATED_AT: datetime.now(timezone.utc).isoformat()}
        if "nome" in data:
            payload[SetorModel.NOME] = (data.get("nome") or "").strip() or None
        if "ativo" in data:
            payload[SetorModel.ATIVO] = bool(data.get("ativo"))
        supabase.table(Tables.SETORES).update(payload).eq(SetorModel.ID, setor_id).eq(SetorModel.CLIENTE_ID, cliente_id).execute()
        return jsonify({"ok": True}), 200
    except Exception as e:
        current_app.logger.warning("api_setores_patch: %s", e)
        return jsonify({"erro": str(e)}), 500


@customer_bp.route('/api/setores/<setor_id>', methods=['DELETE'])
@login_required
def api_setores_delete(setor_id):
    if supabase is None:
        return jsonify({"erro": "Serviço indisponível."}), 503
    resp, code = _require_can_manage_usuarios_setores()
    if resp is not None:
        return resp, code
    try:
        from database.models import Tables, SetorModel
        cliente_id = get_current_cliente_id(current_user)
        r = supabase.table(Tables.SETORES).select(SetorModel.ID).eq(SetorModel.ID, setor_id).eq(SetorModel.CLIENTE_ID, cliente_id).limit(1).execute()
        if not r.data or len(r.data) == 0:
            return jsonify({"erro": "Setor não encontrado."}), 404
        supabase.table(Tables.SETORES).delete().eq(SetorModel.ID, setor_id).eq(SetorModel.CLIENTE_ID, cliente_id).execute()
        return jsonify({"ok": True}), 200
    except Exception as e:
        current_app.logger.warning("api_setores_delete: %s", e)
        return jsonify({"erro": str(e)}), 500


@customer_bp.route('/api/usuarios-internos', methods=['GET'])
@login_required
def api_usuarios_internos_list():
    if supabase is None:
        return jsonify({"erro": "Serviço indisponível."}), 503
    resp, code = _require_can_view_usuarios_setores()
    if resp is not None:
        return resp, code
    try:
        from database.models import Tables, UsuarioInternoModel, UsuarioInternoSetorModel
        cliente_id = get_current_cliente_id(current_user)
        r = supabase.table(Tables.USUARIOS_INTERNOS).select("*").eq(UsuarioInternoModel.CLIENTE_ID, cliente_id).order(UsuarioInternoModel.CREATED_AT, desc=True).execute()
        usuarios = r.data or []
        for u in usuarios:
            rid = supabase.table(Tables.USUARIOS_INTERNOS_SETORES).select(UsuarioInternoSetorModel.SETOR_ID).eq(UsuarioInternoSetorModel.USUARIO_INTERNO_ID, u["id"]).execute()
            u["setor_ids"] = [x.get(UsuarioInternoSetorModel.SETOR_ID) for x in (rid.data or []) if x.get(UsuarioInternoSetorModel.SETOR_ID)]
        return jsonify({"usuarios": usuarios}), 200
    except Exception as e:
        current_app.logger.warning("api_usuarios_internos_list: %s", e)
        return jsonify({"erro": str(e)}), 500


@customer_bp.route('/api/usuarios-internos', methods=['POST'])
@login_required
def api_usuarios_internos_create():
    if supabase is None:
        return jsonify({"erro": "Serviço indisponível."}), 503
    resp, code = _require_can_manage_usuarios_setores()
    if resp is not None:
        return resp, code
    cliente_id = get_current_cliente_id(current_user)
    from services.plan_limits import count_usuarios_internos_ativos
    from services.entitlements import check_limit_reached

    n_ops = count_usuarios_internos_ativos(str(cliente_id))
    if check_limit_reached(str(cliente_id), "max_operadores", n_ops) or check_limit_reached(
        str(cliente_id), "max_usuarios_internos", n_ops
    ):
        return jsonify({"erro": "Limite de operadores atingido"}), 403
    data = strip_untrusted_tenant_ids(request.get_json() or {})
    nome = (data.get("nome") or "").strip()
    email_login = (data.get("email_login") or data.get("email") or "").strip().lower()
    senha = data.get("senha") or ""
    setor_ids = data.get("setor_ids") if isinstance(data.get("setor_ids"), list) else []
    is_admin_cliente = bool(data.get("is_admin_cliente"))
    acesso_menus = _normalize_acesso_menus(data.get("acesso_menus"))
    if not nome:
        return jsonify({"erro": "Nome é obrigatório."}), 400
    if not email_login:
        return jsonify({"erro": "E-mail de login é obrigatório."}), 400
    if len(senha) < 6:
        return jsonify({"erro": "Senha deve ter no mínimo 6 caracteres."}), 400
    try:
        from database.models import Tables, UsuarioInternoModel, UsuarioInternoSetorModel
        exist = supabase.table(Tables.USUARIOS_INTERNOS).select("id").eq(UsuarioInternoModel.CLIENTE_ID, cliente_id).eq(UsuarioInternoModel.EMAIL_LOGIN, email_login).limit(1).execute()
        if exist.data and len(exist.data) > 0:
            return jsonify({"erro": "Já existe um usuário com este e-mail de login."}), 400
        now = datetime.now(timezone.utc).isoformat()
        payload = {
            UsuarioInternoModel.CLIENTE_ID: cliente_id,
            UsuarioInternoModel.NOME: nome,
            UsuarioInternoModel.EMAIL_LOGIN: email_login,
            UsuarioInternoModel.SENHA: generate_password_hash(senha, method="pbkdf2:sha256"),
            UsuarioInternoModel.ATIVO: True,
            UsuarioInternoModel.IS_ADMIN_CLIENTE: is_admin_cliente,
            UsuarioInternoModel.ACESSO_MENUS: acesso_menus,
            UsuarioInternoModel.UPDATED_AT: now,
        }
        r = supabase.table(Tables.USUARIOS_INTERNOS).insert(payload).execute()
        row = (r.data or [{}])[0]
        uid = row.get("id")
        if not uid:
            return jsonify({"erro": "Falha ao criar usuário."}), 500
        for setor_id in setor_ids:
            if setor_id:
                try:
                    supabase.table(Tables.USUARIOS_INTERNOS_SETORES).insert({
                        UsuarioInternoSetorModel.USUARIO_INTERNO_ID: uid,
                        UsuarioInternoSetorModel.SETOR_ID: setor_id,
                    }).execute()
                except Exception:
                    pass
        row["setor_ids"] = [s for s in setor_ids if s]
        return jsonify({"ok": True, "usuario": row}), 201
    except Exception as e:
        current_app.logger.warning("api_usuarios_internos_create: %s", e)
        return jsonify({"erro": str(e)}), 500


@customer_bp.route('/api/usuarios-internos/<usuario_id>', methods=['PATCH'])
@login_required
def api_usuarios_internos_patch(usuario_id):
    if supabase is None:
        return jsonify({"erro": "Serviço indisponível."}), 503
    resp, code = _require_can_manage_usuarios_setores()
    if resp is not None:
        return resp, code
    data = strip_untrusted_tenant_ids(request.get_json() or {})
    try:
        from database.models import Tables, UsuarioInternoModel, UsuarioInternoSetorModel
        cliente_id = get_current_cliente_id(current_user)
        r = supabase.table(Tables.USUARIOS_INTERNOS).select("*").eq(UsuarioInternoModel.ID, usuario_id).eq(UsuarioInternoModel.CLIENTE_ID, cliente_id).limit(1).execute()
        if not r.data or len(r.data) == 0:
            return jsonify({"erro": "Usuário não encontrado."}), 404
        now = datetime.now(timezone.utc).isoformat()
        payload = {UsuarioInternoModel.UPDATED_AT: now}
        if "nome" in data:
            payload[UsuarioInternoModel.NOME] = (data.get("nome") or "").strip() or None
        if "ativo" in data:
            payload[UsuarioInternoModel.ATIVO] = bool(data.get("ativo"))
        if "is_admin_cliente" in data:
            payload[UsuarioInternoModel.IS_ADMIN_CLIENTE] = bool(data.get("is_admin_cliente"))
        if "acesso_menus" in data:
            payload[UsuarioInternoModel.ACESSO_MENUS] = _normalize_acesso_menus(data.get("acesso_menus"))
        nova_senha = (data.get("nova_senha") or "").strip()
        if len(nova_senha) >= 6:
            payload[UsuarioInternoModel.SENHA] = generate_password_hash(nova_senha, method="pbkdf2:sha256")
        if payload:
            supabase.table(Tables.USUARIOS_INTERNOS).update(payload).eq(UsuarioInternoModel.ID, usuario_id).eq(UsuarioInternoModel.CLIENTE_ID, cliente_id).execute()
        if "setor_ids" in data and isinstance(data["setor_ids"], list):
            supabase.table(Tables.USUARIOS_INTERNOS_SETORES).delete().eq(UsuarioInternoSetorModel.USUARIO_INTERNO_ID, usuario_id).execute()
            for setor_id in data["setor_ids"]:
                if setor_id:
                    try:
                        supabase.table(Tables.USUARIOS_INTERNOS_SETORES).insert({
                            UsuarioInternoSetorModel.USUARIO_INTERNO_ID: usuario_id,
                            UsuarioInternoSetorModel.SETOR_ID: setor_id,
                        }).execute()
                    except Exception:
                        pass
        return jsonify({"ok": True}), 200
    except Exception as e:
        current_app.logger.warning("api_usuarios_internos_patch: %s", e)
        return jsonify({"erro": str(e)}), 500


@customer_bp.route('/api/usuarios-internos/<usuario_id>', methods=['DELETE'])
@login_required
def api_usuarios_internos_delete(usuario_id):
    if supabase is None:
        return jsonify({"erro": "Serviço indisponível."}), 503
    resp, code = _require_can_manage_usuarios_setores()
    if resp is not None:
        return resp, code
    try:
        from database.models import Tables, UsuarioInternoModel
        cliente_id = get_current_cliente_id(current_user)
        r = supabase.table(Tables.USUARIOS_INTERNOS).select(UsuarioInternoModel.ID).eq(UsuarioInternoModel.ID, usuario_id).eq(UsuarioInternoModel.CLIENTE_ID, cliente_id).limit(1).execute()
        if not r.data or len(r.data) == 0:
            return jsonify({"erro": "Usuário não encontrado."}), 404
        supabase.table(Tables.USUARIOS_INTERNOS).delete().eq(UsuarioInternoModel.ID, usuario_id).eq(UsuarioInternoModel.CLIENTE_ID, cliente_id).execute()
        return jsonify({"ok": True}), 200
    except Exception as e:
        current_app.logger.warning("api_usuarios_internos_delete: %s", e)
        return jsonify({"erro": str(e)}), 500


@customer_bp.route('/api/leads/<lead_id>', methods=['PATCH'])
@login_required
def api_leads_patch(lead_id):
    """Atualiza o status de um lead (qualificado / desqualificado / pendente). Apenas leads do cliente logado."""
    if supabase is None:
        return jsonify({"erro": "Serviço indisponível."}), 503
    data = strip_untrusted_tenant_ids(request.get_json() or {})
    status = (data.get("status") or "").strip().lower()
    if status not in ("qualificado", "desqualificado", "pendente"):
        return jsonify({"erro": "Status inválido. Use qualificado, desqualificado ou pendente."}), 400
    cliente_id = get_current_cliente_id(current_user)
    if not cliente_id:
        return jsonify({"erro": "Cliente não identificado."}), 403
    try:
        r = supabase.table(Tables.LEADS).select(LeadModel.ID).eq(LeadModel.ID, lead_id).eq(LeadModel.CLIENTE_ID, cliente_id).limit(1).execute()
        if not r.data or len(r.data) == 0:
            return jsonify({"erro": "Lead não encontrado."}), 404
        supabase.table(Tables.LEADS).update({LeadModel.STATUS: status}).eq(LeadModel.ID, lead_id).eq(LeadModel.CLIENTE_ID, cliente_id).execute()
        return jsonify({"ok": True, "status": status}), 200
    except Exception as e:
        current_app.logger.warning("api_leads_patch: %s", e)
        return jsonify({"erro": str(e)}), 500


# --- ENVIO DE MENSAGENS (WhatsApp via Meta, Instagram, Messenger, Site) ---
from services.message_service import MessageService
from services.anexo_service import servir_anexo, save_uploaded_file
import base64

@customer_bp.route('/api/anexo/<path:filename>')
@login_required
def api_anexo(filename):
    """Serve anexo de mensagem (imagem/arquivo) se o arquivo pertencer ao cliente logado."""
    resp, code = servir_anexo(filename, get_current_cliente_id(current_user))
    if code != 200:
        return jsonify(resp) if isinstance(resp, dict) else resp, code
    return resp


@customer_bp.route("/api/flows", methods=["GET"])
@login_required
def api_flows_list():
    """Lista todos os fluxos (gatilhos/canais) do cliente para o menu do Flow Builder."""
    if supabase is None:
        return jsonify({"erro": "Serviço indisponível."}), 503
    cliente_id = str(get_current_cliente_id(current_user) or "")
    # #region agent log
    _debug_log("api_flows_list_entry", "GET /api/flows", {"cliente_id": cliente_id}, "E")
    # #endregion
    if not cliente_id:
        return jsonify({"erro": "Usuário não identificado."}), 401
    try:
        r = supabase.table(Tables.FLOWS).select(FlowModel.ID, FlowModel.CHANNEL, FlowModel.NAME).eq(FlowModel.CLIENTE_ID, cliente_id).execute()
        by_channel = {row.get(FlowModel.CHANNEL): row for row in (r.data or []) if row.get(FlowModel.CHANNEL)}
        list_ = []
        for ch in FLOW_CHANNELS:
            cid = ch["id"]
            row = by_channel.get(cid)
            list_.append({
                "channel": cid,
                "label": ch["label"],
                "description": ch["description"],
                "id": row.get(FlowModel.ID) if row else None,
                "name": row.get(FlowModel.NAME) if row else ch["label"],
            })
        return jsonify({"flows": list_}), 200
    except Exception as e:
        # #region agent log
        try:
            import json as _json
            with open("debug-6a61e7.log", "a", encoding="utf-8") as _f:
                _f.write(_json.dumps({"sessionId": "6a61e7", "handler": "api_flows_list_except", "message": "GET /api/flows exception", "data": {"type": type(e).__name__, "message": str(e)}, "hypothesisId": "E", "timestamp": int(datetime.now(timezone.utc).timestamp() * 1000)}) + "\n")
        except Exception:
            pass
        # #endregion
        current_app.logger.exception("api_flows_list")
        return jsonify({"erro": str(e)}), 500


@customer_bp.route("/api/flows/delete-all", methods=["POST", "DELETE"])
@login_required
def api_flows_delete_all():
    """Apaga todos os fluxos do cliente. Use para limpar fluxos antigos e depois salvar só o fluxo do canvas."""
    if supabase is None:
        return jsonify({"ok": False, "erro": "Serviço indisponível."}), 503
    cliente_id = str(get_current_cliente_id(current_user) or "")
    if not cliente_id:
        return jsonify({"ok": False, "erro": "Usuário não identificado."}), 401
    try:
        r = supabase.table(Tables.FLOWS).delete().eq(FlowModel.CLIENTE_ID, cliente_id).execute()
        count = len(r.data) if r.data else 0
        current_app.logger.info("api_flows_delete_all: cliente_id=%s removidos=%s", cliente_id, count)
        return jsonify({"ok": True, "message": "Todos os fluxos foram apagados.", "removidos": count}), 200
    except Exception as e:
        current_app.logger.exception("api_flows_delete_all")
        return jsonify({"ok": False, "erro": str(e)}), 500


# #region agent log
def _debug_log(handler, message, data, hypothesis_id="A"):
    try:
        import json
        with open("debug-6a61e7.log", "a", encoding="utf-8") as f:
            f.write(json.dumps({"sessionId": "6a61e7", "id": f"log_{handler}", "handler": handler, "message": message, "data": data, "hypothesisId": hypothesis_id, "timestamp": int(datetime.now(timezone.utc).timestamp() * 1000)}) + "\n")
    except Exception:
        pass
# #endregion

@customer_bp.route("/api/flow", methods=["GET"])
@login_required
def api_flow_get():
    """Retorna o fluxo.
    - Modo legado: ?channel=default
    - Meus Chatbots: ?chatbot_id=uuid [&channel=whatsapp|instagram|messenger|website|default|welcome]
    """
    cliente_id = str(get_current_cliente_id(current_user) or "")
    # #region agent log
    _debug_log("api_flow_get_entry", "GET /api/flow", {"cliente_id": cliente_id, "chatbot_id_arg": request.args.get("chatbot_id"), "channel_arg": request.args.get("channel")}, "A")
    # #endregion
    if not cliente_id:
        return jsonify({"erro": "Usuário não identificado."}), 401
    chatbot_id = (request.args.get("chatbot_id") or "").strip() or None
    channel = (request.args.get("channel") or "default").strip() or "default"
    if supabase is None:
        return jsonify({"erro": "Serviço indisponível."}), 503
    try:
        if chatbot_id:
            # Meus Chatbots:
            # 1) tenta fluxo específico por channel para o chatbot
            r = (
                supabase.table(Tables.FLOWS)
                .select("*")
                .eq(FlowModel.CLIENTE_ID, cliente_id)
                .eq(FlowModel.CHATBOT_ID, chatbot_id)
                .eq(FlowModel.CHANNEL, channel)
                .limit(1)
                .execute()
            )
            row = None
            if r.data and len(r.data) > 0:
                row = r.data[0]
            else:
                # 2) fallback: qualquer fluxo existente para o chatbot (ex.: legado "default")
                r_any = (
                    supabase.table(Tables.FLOWS)
                    .select("*")
                    .eq(FlowModel.CLIENTE_ID, cliente_id)
                    .eq(FlowModel.CHATBOT_ID, chatbot_id)
                    .limit(1)
                    .execute()
                )
                if r_any.data and len(r_any.data) > 0:
                    row = r_any.data[0]
            cb = supabase.table(Tables.CHATBOTS).select(
                ChatbotModel.NOME, ChatbotModel.DESCRICAO, ChatbotModel.CHANNELS
            ).eq(ChatbotModel.ID, chatbot_id).eq(
                ChatbotModel.CLIENTE_ID, cliente_id
            ).limit(1).execute()
            nome = (cb.data or [{}])[0].get(ChatbotModel.NOME, (row or {}).get(FlowModel.NAME)) if cb.data else (row or {}).get(FlowModel.NAME)
            if row:
                return jsonify({
                    "id": row.get(FlowModel.ID),
                    "channel": row.get(FlowModel.CHANNEL) or channel,
                    "chatbot_id": chatbot_id,
                    "name": nome,
                    "flow_json": normalize_flow_json(row.get(FlowModel.FLOW_JSON)),
                }), 200
            # Nenhum fluxo ainda para este chatbot/canal: devolve canvas vazio
            return jsonify({
                "chatbot_id": chatbot_id,
                "channel": channel,
                "name": nome or "",
                "flow_json": {"nodes": [], "edges": []},
            }), 200
        r = supabase.table(Tables.FLOWS).select("*").eq(FlowModel.CLIENTE_ID, cliente_id).eq(FlowModel.CHANNEL, channel).limit(1).execute()
        if r.data and len(r.data) > 0:
            row = r.data[0]
            return jsonify({
                "id": row.get(FlowModel.ID),
                "channel": row.get(FlowModel.CHANNEL),
                "name": row.get(FlowModel.NAME),
                "flow_json": normalize_flow_json(row.get(FlowModel.FLOW_JSON)),
            }), 200
        label = next((c["label"] for c in FLOW_CHANNELS if c["id"] == channel), channel)
        return jsonify({"channel": channel, "name": label, "flow_json": {"nodes": [], "edges": []}}), 200
    except Exception as e:
        # #region agent log
        _debug_log("api_flow_get_except", "GET /api/flow exception", {"type": type(e).__name__, "message": str(e)}, "A")
        # #endregion
        current_app.logger.exception("api_flow_get")
        return jsonify({"erro": str(e)}), 500


@customer_bp.route("/api/flow", methods=["POST"])
@login_required
def api_flow_post():
    """Salva o fluxo. Marreta: DELETE + INSERT por (cliente_id, channel) evita 23505. Suporte a chatbot_id (Meus Chatbots)."""
    try:
        data = strip_untrusted_tenant_ids(request.get_json(silent=True) or {})
    except Exception as parse_err:
        current_app.logger.error("api_flow_post: request.get_json falhou: %s", parse_err)
        data = {}
    # Log de depuração: o que o frontend enviou (sem logar o JSON inteiro para não poluir)
    _keys = list(data.keys()) if isinstance(data, dict) else []
    _flow_type = type(data.get("flow_json")).__name__ if data else "N/A"
    current_app.logger.info("api_flow_post recebido: keys=%s, flow_json type=%s", _keys, _flow_type)
    cliente_id = str(get_current_cliente_id(current_user) or "")
    # #region agent log
    _debug_log("api_flow_post_entry", "POST /api/flow", {"cliente_id": cliente_id}, "A")
    # #endregion
    if not cliente_id:
        return jsonify({"ok": False, "error": "Usuário não identificado."}), 401
    channel = (data.get("channel") or "default").strip() or "default"
    try:
        flow_json = flow_json_serializable(normalize_flow_json(data.get("flow_json")))
    except Exception as norm_err:
        # #region agent log
        _debug_log("api_flow_post_norm", "normalize/serialize failed", {"type": type(norm_err).__name__, "message": str(norm_err)}, "B")
        # #endregion
        raise
    name = (data.get("name") or "Novo Fluxo").strip() or "Novo Fluxo"
    chatbot_id = (data.get("chatbot_id") or "").strip() or None

    if supabase is None:
        return jsonify({"ok": False, "error": "Serviço indisponível."}), 503

    try:
        now = datetime.now(timezone.utc).isoformat()
        if chatbot_id:
            cb = supabase.table(Tables.CHATBOTS).select(ChatbotModel.NOME).eq(ChatbotModel.ID, chatbot_id).eq(ChatbotModel.CLIENTE_ID, cliente_id).limit(1).execute()
            if not cb.data:
                return jsonify({"ok": False, "error": "Chatbot não encontrado."}), 404
            name = (cb.data or [{}])[0].get(ChatbotModel.NOME, name)
            # Um fluxo por (chatbot_id, channel). Apagar SOMENTE o fluxo DESTE chatbot para este canal,
            # para não apagar fluxos de outros chatbots (ex.: salvar WhatsApp não pode apagar Messenger/Website).
            supabase.table(Tables.FLOWS).delete().eq(FlowModel.CHATBOT_ID, chatbot_id).eq(FlowModel.CHANNEL, channel).execute()
            payload = {
                FlowModel.CLIENTE_ID: cliente_id,
                FlowModel.CHATBOT_ID: chatbot_id,
                # CHANNEL agora reflete o gatilho/canal selecionado no Flow Builder (ex.: whatsapp, website, default, welcome)
                FlowModel.CHANNEL: channel,
                FlowModel.NAME: name,
                FlowModel.FLOW_JSON: flow_json,
                FlowModel.UPDATED_AT: now,
            }
            r = supabase.table(Tables.FLOWS).insert(payload).execute()
            row = (r.data or [{}])[0]
            return jsonify({"ok": True, "message": "Salvo com sucesso", "id": row.get(FlowModel.ID), "chatbot_id": chatbot_id}), 200
        # Marreta: limpa o que existe e insere o novo (impossível 23505). Não envia chatbot_id no insert (coluna aceita NULL).
        supabase.table(Tables.FLOWS).delete().eq(FlowModel.CLIENTE_ID, cliente_id).eq(FlowModel.CHANNEL, channel).execute()
        payload = {
            FlowModel.CLIENTE_ID: cliente_id,
            FlowModel.CHANNEL: channel,
            FlowModel.FLOW_JSON: flow_json,
            FlowModel.NAME: name,
            FlowModel.UPDATED_AT: now,
        }
        res = supabase.table(Tables.FLOWS).insert(payload).execute()
        return jsonify({"ok": True, "message": "Salvo com sucesso"}), 200
    except Exception as e:
        # #region agent log
        _debug_log("api_flow_post_except", "POST /api/flow exception", {"type": type(e).__name__, "message": str(e)}, "A")
        # #endregion
        current_app.logger.exception("api_flow_post")
        return jsonify({"ok": False, "error": str(e)}), 500


# --- Meus Chatbots ---
@customer_bp.route("/api/chatbots", methods=["GET"])
@login_required
def api_chatbots_list():
    """Lista chatbots do cliente."""
    if supabase is None:
        return jsonify({"erro": "Serviço indisponível."}), 503
    try:
        cid = str(get_current_cliente_id(current_user) or "")
        from services.plan_limits import get_chatbot_quota

        r = supabase.table(Tables.CHATBOTS).select("*").eq(ChatbotModel.CLIENTE_ID, get_current_cliente_id(current_user)).order(ChatbotModel.CREATED_AT, desc=True).execute()
        return jsonify({"chatbots": r.data or [], "quota": get_chatbot_quota(cid)}), 200
    except Exception as e:
        current_app.logger.exception("api_chatbots_list")
        return jsonify({"erro": str(e)}), 500


@customer_bp.route("/api/chatbots/<chatbot_id>", methods=["GET"])
@login_required
def api_chatbots_get(chatbot_id):
    """Retorna um chatbot do cliente (para edição de canais etc.)."""
    if supabase is None:
        return jsonify({"erro": "Serviço indisponível."}), 503
    try:
        r = supabase.table(Tables.CHATBOTS).select("*").eq(ChatbotModel.ID, chatbot_id).eq(ChatbotModel.CLIENTE_ID, get_current_cliente_id(current_user)).limit(1).execute()
        if not r.data or len(r.data) == 0:
            return jsonify({"erro": "Chatbot não encontrado."}), 404
        row = r.data[0]
        channels = row.get(ChatbotModel.CHANNELS)
        if not isinstance(channels, list):
            channels = []
        return jsonify({"id": row.get(ChatbotModel.ID), "nome": row.get(ChatbotModel.NOME), "descricao": row.get(ChatbotModel.DESCRICAO), "channels": channels}), 200
    except Exception as e:
        current_app.logger.exception("api_chatbots_get")
        return jsonify({"erro": str(e)}), 500


@customer_bp.route("/api/chatbots/<chatbot_id>", methods=["PATCH"])
@login_required
def api_chatbots_patch(chatbot_id):
    """Atualiza chatbot (canais onde o chatbot roda). Body: { channels?: string[] }."""
    if supabase is None:
        return jsonify({"erro": "Serviço indisponível."}), 503
    data = strip_untrusted_tenant_ids(request.get_json() or {})
    channels = data.get("channels")
    if channels is not None and not isinstance(channels, list):
        channels = [c for c in (channels,) if isinstance(c, str)]
    try:
        r = supabase.table(Tables.CHATBOTS).select(ChatbotModel.ID).eq(ChatbotModel.ID, chatbot_id).eq(ChatbotModel.CLIENTE_ID, get_current_cliente_id(current_user)).limit(1).execute()
        if not r.data or len(r.data) == 0:
            return jsonify({"erro": "Chatbot não encontrado."}), 404
        now = datetime.now(timezone.utc).isoformat()
        payload = {ChatbotModel.UPDATED_AT: now}
        if channels is not None:
            payload[ChatbotModel.CHANNELS] = [str(c).strip() for c in channels if str(c).strip()]
        up = supabase.table(Tables.CHATBOTS).update(payload).eq(ChatbotModel.ID, chatbot_id).eq(ChatbotModel.CLIENTE_ID, get_current_cliente_id(current_user)).execute()
        row = (up.data or [{}])[0] if up.data else {}
        return jsonify({"ok": True, "chatbot": row}), 200
    except Exception as e:
        current_app.logger.exception("api_chatbots_patch")
        return jsonify({"erro": str(e)}), 500


@customer_bp.route("/api/chatbots", methods=["POST"])
@login_required
def api_chatbots_create():
    """Cria chatbot e seu fluxo vazio. Body: { nome, descricao? }."""
    data = strip_untrusted_tenant_ids(request.get_json() or {})
    nome = (data.get("nome") or "").strip()
    if not nome:
        return jsonify({"erro": "Nome do chatbot é obrigatório."}), 400
    if supabase is None:
        return jsonify({"erro": "Serviço indisponível."}), 503
    cid_cb = str(get_current_cliente_id(current_user) or "")
    from services.plan_limits import count_chatbots_cliente
    from services.entitlements import check_limit_reached

    n_cb = count_chatbots_cliente(cid_cb)
    if check_limit_reached(cid_cb, "max_chatbots", n_cb):
        return jsonify({"erro": "Limite de chatbots atingido"}), 403
    try:
        now = datetime.now(timezone.utc).isoformat()
        payload = {
            ChatbotModel.CLIENTE_ID: get_current_cliente_id(current_user),
            ChatbotModel.NOME: nome,
            ChatbotModel.DESCRICAO: (data.get("descricao") or "").strip() or None,
            ChatbotModel.CHANNELS: data.get("channels") if isinstance(data.get("channels"), list) else [],
            ChatbotModel.UPDATED_AT: now,
        }
        r = supabase.table(Tables.CHATBOTS).insert(payload).execute()
        row = (r.data or [{}])[0] if r.data else {}
        chatbot_id = row.get(ChatbotModel.ID)
        if not chatbot_id:
            return jsonify({"erro": "Falha ao criar chatbot."}), 500
        flow_payload = {
            FlowModel.CLIENTE_ID: get_current_cliente_id(current_user),
            FlowModel.CHATBOT_ID: chatbot_id,
            FlowModel.CHANNEL: "default",
            FlowModel.NAME: nome,
            FlowModel.FLOW_JSON: {"nodes": [], "edges": []},
            FlowModel.UPDATED_AT: now,
        }
        supabase.table(Tables.FLOWS).insert(flow_payload).execute()
        return jsonify({"ok": True, "chatbot": row}), 201
    except Exception as e:
        current_app.logger.exception("api_chatbots_create")
        return jsonify({"erro": str(e)}), 500


@customer_bp.route("/api/chatbots/<chatbot_id>", methods=["DELETE"])
@login_required
def api_chatbots_delete(chatbot_id):
    """Remove chatbot e seu fluxo (apaga fluxo antes se não houver CASCADE)."""
    if supabase is None:
        return jsonify({"erro": "Serviço indisponível."}), 503
    cid = get_current_cliente_id(current_user)
    if not cid:
        return jsonify({"erro": "Cliente não identificado na sessão."}), 401
    cliente_id = str(cid)
    try:
        supabase.table(Tables.FLOWS).delete().eq(FlowModel.CLIENTE_ID, cliente_id).eq(FlowModel.CHATBOT_ID, chatbot_id).execute()
    except Exception:
        pass
    try:
        r = supabase.table(Tables.CHATBOTS).delete().eq(ChatbotModel.ID, chatbot_id).eq(ChatbotModel.CLIENTE_ID, cliente_id).execute()
        if r.data is not None:
            return jsonify({"ok": True}), 200
        return jsonify({"erro": "Chatbot não encontrado."}), 404
    except Exception as e:
        current_app.logger.exception("api_chatbots_delete")
        return jsonify({"erro": str(e)}), 500


@customer_bp.route('/api/enviar', methods=['POST'])
@login_required
def api_enviar():
    """Envio de mensagens do painel. WhatsApp apenas via API oficial Meta."""
    data = strip_untrusted_tenant_ids(request.json or {})
    remote_id = str(data.get('remote_id', '')).strip()
    texto = data.get('texto')
    canal = data.get('canal') or 'whatsapp'
    cliente_id = get_current_cliente_id(current_user)
    texto_len = len(texto) if texto else 0
    print(f"📤 api/enviar RECEBIDO | canal={canal!r} remote_id={remote_id!r} texto_len={texto_len} cliente_id={cliente_id}", flush=True)

    if not remote_id or not texto:
        msg = "Selecione um contato e digite uma mensagem."
        print(f"📤 api/enviar 400: {msg} (canal={canal}, remote_id={remote_id!r})")
        return jsonify({"status": "erro", "mensagem": msg}), 400

    r = supabase.table("clientes").select("meta_wa_phone_number_id, meta_wa_token, meta_ig_page_id, meta_ig_token, meta_fb_page_id, meta_fb_token").eq("id", cliente_id).execute()
    cliente = r.data[0] if r.data and len(r.data) > 0 else {}
    if canal == 'whatsapp':
        if not can_use_channel(str(cliente_id), "whatsapp"):
            msg = "O canal WhatsApp está temporariamente indisponível."
            print(f"📤 api/enviar 400: {msg}")
            return jsonify({"status": "erro", "mensagem": msg}), 400
        from base.config import settings
        if not getattr(settings, "WAHA_URL", None) or not getattr(settings, "WAHA_API_KEY", None):
            msg = "Configure o WhatsApp (WAHA): defina WAHA_URL e WAHA_API_KEY no .env."
            print(f"📤 api/enviar 400: {msg}")
            return jsonify({"status": "erro", "mensagem": msg}), 400
    elif canal == 'instagram':
        if not cliente.get('meta_ig_page_id') or not cliente.get('meta_ig_token'):
            msg = "Conecte o Instagram em Conexões (Conectar Instagram)."
            print(f"📤 api/enviar 400: {msg}")
            return jsonify({"status": "erro", "mensagem": msg}), 400
    elif canal == 'facebook':
        if not cliente.get('meta_fb_page_id') or not cliente.get('meta_fb_token'):
            msg = "Conecte o Messenger em Conexões (Conectar Messenger)."
            print(f"📤 api/enviar 400: {msg}")
            return jsonify({"status": "erro", "mensagem": msg}), 400

    if canal in ("instagram", "facebook") and not can_use_channel(str(cliente_id), canal):
        msg = (
            "O canal Instagram está temporariamente indisponível."
            if canal == "instagram"
            else "O canal Messenger está temporariamente indisponível."
        )
        return jsonify({"status": "erro", "mensagem": msg}), 400

    nome_val = (getattr(current_user, "nome", None) or "").strip()
    email_val = (getattr(current_user, "email", None) or "").strip()
    display_name = (nome_val or email_val or "Atendente").strip() or "Atendente"
    #region agent log display_name_source_api_enviar
    _agent_debug_log(
        hypothesis_id="H8_display_name_source",
        location="panel/routes/customer.py:api_enviar",
        message="computed_display_name",
        data={
            "is_operador": bool(getattr(current_user, "is_operador", lambda: False)()),
            "operador_id_present": bool(getattr(current_user, "operador_id", None)),
            "nome_len": len(nome_val),
            "email_len": len(email_val),
            "display_name_len": len(display_name),
            "display_name_is_email": bool(email_val and display_name == email_val),
            "canal": canal,
        },
    )
    #endregion
    text_to_send = f"{display_name}: {texto}"
    try:
        from services.routing_service import RoutingService
        destinatario = remote_id if "@" in remote_id else (f"{remote_id}@s.whatsapp.net" if canal == "whatsapp" else remote_id)
        sucesso, erro_msg = RoutingService.enviar_resposta(canal, None, destinatario, text_to_send, cliente_id=cliente_id)
        print(f"📤 api/enviar resultado | canal={canal} sucesso={sucesso} erro_msg={erro_msg or ''}", flush=True)
        if sucesso:
            MessageService.salvar_mensagem(
                cliente_id, remote_id, canal, "assistant", texto,
                atendente_tipo="humano",
                atendente_usuario_id=getattr(current_user, "operador_id", None),
                atendente_nome_snapshot=display_name,
            )
            socketio = current_app.extensions.get('socketio')
            if socketio:
                socketio.emit('nova_mensagem', {
                    'canal': canal,
                    'remote_id': remote_id,
                    'conteudo': texto,
                    'funcao': 'assistant',
                    'cliente_id': cliente_id,
                    'atendente_nome_snapshot': display_name,
                }, room=f"painel:{cliente_id}")
            print(f"📤 api/enviar 200 OK | canal={canal} remote_id={remote_id!r}", flush=True)
            return jsonify({"status": "sucesso", "atendente_nome_snapshot": display_name}), 200
        msg = (erro_msg or "Falha no envio. Verifique as credenciais em Conexões.").strip()
        print(f"📤 api/enviar 400: {msg} (canal={canal})", flush=True)
        return jsonify({"status": "erro", "mensagem": msg}), 400
    except Exception as e:
        print(f"📤 api/enviar 500: {e}")
        return jsonify({"status": "erro", "mensagem": str(e)}), 500


@customer_bp.route('/api/enviar-midia', methods=['POST'])
@login_required
def api_enviar_midia():
    """Envio de imagem ou documento do painel. Multipart: remote_id, canal, texto (caption), file. WhatsApp via WAHA."""
    if "file" not in request.files:
        return jsonify({"status": "erro", "mensagem": "Nenhum arquivo enviado."}), 400
    arquivo = request.files["file"]
    if not arquivo or not arquivo.filename:
        return jsonify({"status": "erro", "mensagem": "Selecione um arquivo (imagem ou documento)."}), 400
    remote_id = (request.form.get("remote_id") or "").strip()
    canal = (request.form.get("canal") or "whatsapp").strip().lower()
    texto = (request.form.get("texto") or "").strip()
    cliente_id = get_current_cliente_id(current_user)
    if not remote_id:
        return jsonify({"status": "erro", "mensagem": "Selecione um contato."}), 400
    if canal not in ("whatsapp", "facebook", "instagram", "website"):
        return jsonify({"status": "erro", "mensagem": "Canal inválido."}), 400
    if canal != "whatsapp":
        return jsonify({"status": "erro", "mensagem": "Envio de mídia por enquanto só para WhatsApp."}), 400
    if not can_use_channel(str(cliente_id), "whatsapp"):
        return jsonify({"status": "erro", "mensagem": "O canal WhatsApp está temporariamente indisponível."}), 400
    from base.config import settings
    if not getattr(settings, "WAHA_URL", None) or not getattr(settings, "WAHA_API_KEY", None):
        return jsonify({"status": "erro", "mensagem": "Configure WAHA (WhatsApp) no .env."}), 400

    anexo_url, path_file, mimetype, nome_original = save_uploaded_file(arquivo, str(cliente_id))
    if not anexo_url or not path_file:
        return jsonify({"status": "erro", "mensagem": "Falha ao salvar o arquivo."}), 500
    try:
        with open(path_file, "rb") as f:
            file_b64 = base64.b64encode(f.read()).decode("ascii")
    except Exception as e:
        current_app.logger.warning("api_enviar_midia: erro ao ler arquivo: %s", e)
        return jsonify({"status": "erro", "mensagem": "Erro ao processar arquivo."}), 500

    nome_val = (getattr(current_user, "nome", None) or "").strip()
    email_val = (getattr(current_user, "email", None) or "").strip()
    display_name = (nome_val or email_val or "Atendente").strip() or "Atendente"
    #region agent log display_name_source_api_enviar_midia
    _agent_debug_log(
        hypothesis_id="H8_display_name_source",
        location="panel/routes/customer.py:api_enviar_midia",
        message="computed_display_name",
        data={
            "is_operador": bool(getattr(current_user, "is_operador", lambda: False)()),
            "operador_id_present": bool(getattr(current_user, "operador_id", None)),
            "nome_len": len(nome_val),
            "email_len": len(email_val),
            "display_name_len": len(display_name),
            "display_name_is_email": bool(email_val and display_name == email_val),
            "canal": canal,
        },
    )
    #endregion
    caption_to_send = f"{display_name}: {texto}" if texto else ""
    try:
        from services.routing_service import RoutingService
        destinatario = remote_id if "@" in remote_id else f"{remote_id}@s.whatsapp.net"
        sucesso, erro_msg = RoutingService.enviar_resposta(
            canal, None, destinatario, caption_to_send, cliente_id=cliente_id,
            anexo_base64=file_b64, anexo_mimetype=mimetype, anexo_filename=nome_original,
        )
        if sucesso:
            if texto:
                conteudo_msg = texto
            elif (mimetype or "").strip().lower().startswith("audio/"):
                conteudo_msg = "[áudio enviado]"
            elif (mimetype or "").strip().lower().startswith("image/"):
                conteudo_msg = "[imagem enviada]"
            else:
                conteudo_msg = "[arquivo enviado]"
            if canal == "whatsapp":
                # Garante que o webhook ignore o eco (fromMe=true) e não dependa de gravação via webhook.
                try:
                    from services.sent_message_cache import registrar_envio
                    registrar_envio(cliente_id, remote_id, caption_to_send or conteudo_msg)
                except Exception:
                    pass

            MessageService.salvar_mensagem(
                cliente_id, remote_id, canal, "assistant", conteudo_msg,
                anexo_url=anexo_url, anexo_nome=nome_original, anexo_tipo=mimetype,
                atendente_tipo="humano",
                atendente_usuario_id=getattr(current_user, "operador_id", None),
                atendente_nome_snapshot=display_name,
            )
            socketio = current_app.extensions.get("socketio")
            if socketio:
                payload = {
                    "canal": canal,
                    "remote_id": remote_id,
                    "conteudo": conteudo_msg,
                    "funcao": "assistant",
                    "cliente_id": cliente_id,
                    "anexo_url": anexo_url,
                    "anexo_nome": nome_original,
                    "anexo_tipo": mimetype,
                    "atendente_nome_snapshot": display_name,
                }
                socketio.emit("nova_mensagem", payload, room=f"painel:{cliente_id}")
            return jsonify({"status": "sucesso", "anexo_url": anexo_url}), 200
        msg = (erro_msg or "Falha no envio.").strip()
        return jsonify({"status": "erro", "mensagem": msg}), 400
    except Exception as e:
        current_app.logger.exception("api_enviar_midia: %s", e)
        return jsonify({"status": "erro", "mensagem": str(e)}), 500


# Hash fictício para comparação constante no tempo quando o e-mail não existe (evita timing attack)
_DUMMY_HASH = generate_password_hash("dummy", method="pbkdf2:sha256")


def _login_template_ctx():
    url = (getattr(settings, "SUPABASE_URL", None) or "").strip()
    jwt_secret = (getattr(settings, "SUPABASE_JWT_SECRET", None) or "").strip()
    # Só enviar a chave ANON (pública) ao frontend. NUNCA usar SUPABASE_KEY (service role) aqui.
    anon_key = (getattr(settings, "SUPABASE_ANON_KEY", None) or "").strip()
    use_supabase_auth = bool(url and jwt_secret and anon_key)
    return {
        "login_csrf": session.get("login_csrf", ""),
        "use_supabase_auth": use_supabase_auth,
        "supabase_url": url,
        "supabase_anon_key": anon_key,
    }


# --- AUTENTICAÇÃO ---
@customer_bp.route('/login', methods=['GET', 'POST'])
def login():
    if current_user.is_authenticated:
        return redirect(url_for('customer.dashboard'))

    if request.method == 'GET':
        session["login_csrf"] = secrets.token_hex(32)
        return render_template("login.html", **{**_login_template_ctx(), "login_csrf": session["login_csrf"]})

    # POST: validar CSRF
    if request.form.get("csrf_token") != session.pop("login_csrf", None):
        flash("Sessão inválida. Recarregue a página e tente novamente.", "danger")
        session["login_csrf"] = secrets.token_hex(32)
        return render_template("login.html", **{**_login_template_ctx(), "login_csrf": session["login_csrf"]}), 400

    # Rate limit por IP
    ip = request.remote_addr or "unknown"
    if _login_rate_limit_exceeded(ip):
        flash("Muitas tentativas. Aguarde alguns minutos e tente novamente.", "danger")
        session["login_csrf"] = secrets.token_hex(32)
        return render_template("login.html", **{**_login_template_ctx(), "login_csrf": session["login_csrf"]}), 429

    email = (request.form.get("username") or "").strip()
    senha = request.form.get("password") or ""

    # Tentar login como sublogin (usuario_interno) por email_login
    u_interno = None
    senha_interno = _DUMMY_HASH
    email_login_normalized = email.lower().strip() if email else ""
    try:
        from database.models import Tables, UsuarioInternoModel
        res = supabase.table(Tables.USUARIOS_INTERNOS).select("*").eq(
            UsuarioInternoModel.EMAIL_LOGIN, email_login_normalized
        ).eq(UsuarioInternoModel.ATIVO, True).execute()
        if (not res.data or len(res.data) == 0) and email_login_normalized != email:
            res = supabase.table(Tables.USUARIOS_INTERNOS).select("*").eq(
                UsuarioInternoModel.EMAIL_LOGIN, email
            ).eq(UsuarioInternoModel.ATIVO, True).execute()
        if res.data and len(res.data) > 0:
            u_interno = res.data[0]
            senha_interno = (u_interno.get("senha") or "").strip() or _DUMMY_HASH
    except Exception as e:
        current_app.logger.warning("login sublogin lookup: %s", e)

    if senha_interno.startswith(("pbkdf2:", "scrypt:", "argon2:", "bcrypt")):
        try:
            if check_password_hash(senha_interno, senha) and u_interno:
                operador_id = u_interno.get("id")
                cliente_id = u_interno.get("cliente_id")
                if not operador_id or not cliente_id:
                    current_app.logger.warning("login sublogin: operador_id ou cliente_id vazio")
                else:
                    res_c = supabase.table("clientes").select(_CLIENTES_SELECT).eq("id", cliente_id).execute()
                    cliente = res_c.data[0] if res_c.data else {}
                    user = User(
                        id=_USER_ID_PREFIX_OPERADOR + str(operador_id),
                        email=u_interno.get("email_login") or "",
                        plano=cliente.get("plano", "social"),
                        status_ia=cliente.get("status_ia", True),
                        ia_ativa=cliente.get("ia_ativa", True),
                        whatsapp_instancia=cliente.get("whatsapp_instancia"),
                        acesso_whatsapp=cliente.get("acesso_whatsapp"),
                        acesso_instagram=cliente.get("acesso_instagram"),
                        acesso_messenger=cliente.get("acesso_messenger"),
                        acesso_site=cliente.get("acesso_site"),
                        cliente_id=cliente_id,
                        operador_id=operador_id,
                        nome=u_interno.get("nome") or "",
                        is_admin_cliente=bool(u_interno.get("is_admin_cliente")),
                        acesso_menus=list(u_interno.get("acesso_menus") or []),
                    )
                    login_user(user)
                    return redirect(url_for("customer.dashboard"))
        except Exception as e:
            current_app.logger.warning("login sublogin: %s", e)

    flash("E-mail ou senha incorretos.", "danger")
    session["login_csrf"] = secrets.token_hex(32)
    return render_template("login.html", **{**_login_template_ctx(), "login_csrf": session["login_csrf"]})


@customer_bp.route("/api/auth/operador-login", methods=["POST"])
def api_operador_login():
    """Login apenas para usuarios_internos (senha local). Separado do fluxo Supabase dos clientes."""
    if current_user.is_authenticated:
        return jsonify({"ok": True, "redirect": url_for("customer.dashboard")}), 200
    data = strip_untrusted_tenant_ids(request.get_json() or {})
    email = (data.get("email") or data.get("username") or "").strip()
    senha = data.get("password") or ""
    if not email or not senha:
        return jsonify({"ok": False, "erro": "Preencha e-mail e senha."}), 400
    ip = request.remote_addr or "unknown"
    if _login_rate_limit_exceeded(ip):
        return jsonify({"ok": False, "erro": "Muitas tentativas. Aguarde alguns minutos."}), 429

    u_interno = None
    senha_interno = _DUMMY_HASH
    email_login_normalized = email.lower().strip()
    try:
        from database.models import Tables, UsuarioInternoModel
        res = supabase.table(Tables.USUARIOS_INTERNOS).select("*").eq(
            UsuarioInternoModel.EMAIL_LOGIN, email_login_normalized
        ).eq(UsuarioInternoModel.ATIVO, True).execute()
        if (not res.data or len(res.data) == 0) and email_login_normalized != email:
            res = supabase.table(Tables.USUARIOS_INTERNOS).select("*").eq(
                UsuarioInternoModel.EMAIL_LOGIN, email
            ).eq(UsuarioInternoModel.ATIVO, True).execute()
        if res.data and len(res.data) > 0:
            u_interno = res.data[0]
            senha_interno = (u_interno.get("senha") or "").strip() or _DUMMY_HASH
    except Exception as e:
        current_app.logger.warning("api_operador_login sublogin lookup: %s", e)
    if senha_interno.startswith(("pbkdf2:", "scrypt:", "argon2:", "bcrypt")):
        try:
            if check_password_hash(senha_interno, senha) and u_interno:
                operador_id = u_interno.get("id")
                cliente_id = u_interno.get("cliente_id")
                if operador_id and cliente_id:
                    res_c = supabase.table("clientes").select(_CLIENTES_SELECT).eq("id", cliente_id).execute()
                    cliente = res_c.data[0] if res_c.data else {}
                    user = User(
                        id=_USER_ID_PREFIX_OPERADOR + str(operador_id),
                        email=u_interno.get("email_login") or "",
                        plano=cliente.get("plano", "social"),
                        status_ia=cliente.get("status_ia", True),
                        ia_ativa=cliente.get("ia_ativa", True),
                        whatsapp_instancia=cliente.get("whatsapp_instancia"),
                        acesso_whatsapp=cliente.get("acesso_whatsapp"),
                        acesso_instagram=cliente.get("acesso_instagram"),
                        acesso_messenger=cliente.get("acesso_messenger"),
                        acesso_site=cliente.get("acesso_site"),
                        cliente_id=cliente_id,
                        operador_id=operador_id,
                        nome=u_interno.get("nome") or "",
                        is_admin_cliente=bool(u_interno.get("is_admin_cliente")),
                        acesso_menus=list(u_interno.get("acesso_menus") or []),
                    )
                    login_user(user)
                    return jsonify({"ok": True, "redirect": url_for("customer.dashboard")}), 200
        except Exception as e:
            current_app.logger.warning("api_operador_login sublogin: %s", e)
    if u_interno:
        return jsonify({"ok": False, "erro": "E-mail ou senha incorretos."}), 401
    return jsonify({"ok": False, "erro": "E-mail ou senha incorretos."}), 401


@customer_bp.route("/nova-senha", methods=["GET"])
def nova_senha():
    """Página estática: troca de senha via Supabase JS (recovery)."""
    return render_template(
        "nova_senha.html",
        **{k: v for k, v in _login_template_ctx().items() if k in ("supabase_url", "supabase_anon_key")},
    )


@customer_bp.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect(url_for('customer.login'))

@customer_bp.route('/api/mensagens/<canal>')
@login_required
def buscar_mensagens(canal):
    if supabase is None:
        return jsonify({"erro": "Supabase não inicializado. Verifique SUPABASE_URL e SUPABASE_KEY no .env."}), 500
    canal = (canal or "").strip().lower()
    if canal not in ("whatsapp", "facebook", "instagram", "website"):
        return jsonify([]), 200
    cliente_id = get_current_cliente_id(current_user)
    if canal == "whatsapp" and not can_use_channel(str(cliente_id), "whatsapp"):
        return jsonify([]), 200
    if canal in ("instagram", "facebook") and not can_use_channel(str(cliente_id), canal):
        return jsonify([]), 200
    before = request.args.get("before")  # ISO datetime: carregar mensagens mais antigas que esta
    remote_id_arg = request.args.get("remote_id")  # opcional: filtrar por conversa (paginação por chat)
    limit = min(int(request.args.get("limit", 100)), 100)
    if before:
        limit = min(int(request.args.get("limit", 50)), 50)
    try:
        from services.setores_helpers import get_allowed_remote_ids_for_canal
        allowed = get_allowed_remote_ids_for_canal(cliente_id, canal, current_user)
        if allowed is not None and remote_id_arg:
            rid_norm = _normalizar_remote_id(remote_id_arg)
            if rid_norm not in allowed:
                return jsonify([]), 200

        # Modo lista: sempre retorna as conversas mais recentes sem “encolher”.
        # Sem `remote_id` e sem `before`, o frontend monta a lista com 1 item por `remote_id`,
        # então aqui retornamos 1 mensagem (a mais recente) por conversa.
        #
        # Regra: escolher as top 300 conversas por recência real (created_at) varrendo historico_mensagens
        # do mais recente para o mais antigo e deduplicando por remote_id normalizado.
        if not remote_id_arg and not before:
            target_conversations = 300
            batch_size = 200
            max_pages = 20  # evita loops infinitos em bases muito grandes

            allowed_set = set(allowed) if allowed is not None else None

            latest_by_remote: dict[str, dict] = {}
            cursor_created_at = None
            prev_cursor = None

            for _page in range(max_pages):
                q = (
                    supabase.table("historico_mensagens")
                    .select("*")
                    .eq("cliente_id", cliente_id)
                    .eq("canal", canal)
                    .order("created_at", desc=True)
                    .limit(batch_size)
                )
                if cursor_created_at:
                    q = q.lt("created_at", cursor_created_at)

                res = q.execute()
                batch = res.data or []
                if not batch:
                    break

                # Como estamos varrendo do mais recente para o mais antigo, a primeira ocorrência
                # de cada remote_id normalizado é a mensagem mais recente daquela conversa.
                for row in batch:
                    rid = _normalizar_remote_id(row.get("remote_id"))
                    if not rid:
                        continue
                    if allowed_set is not None and rid not in allowed_set:
                        continue
                    if rid in latest_by_remote:
                        continue
                    latest_by_remote[rid] = row
                    if len(latest_by_remote) >= target_conversations:
                        break

                if len(latest_by_remote) >= target_conversations:
                    break

                cursor_created_at = batch[-1].get("created_at")
                if not cursor_created_at or cursor_created_at == prev_cursor:
                    break
                prev_cursor = cursor_created_at

            data = sorted(
                latest_by_remote.values(),
                key=lambda r: r.get("created_at") or "",
                reverse=True,
            )
            return jsonify(data)

        q = supabase.table("historico_mensagens").select("*").eq("cliente_id", cliente_id).eq("canal", canal)
        if remote_id_arg:
            q = q.eq("remote_id", remote_id_arg.strip())
        if before:
            q = q.lt("created_at", before.strip())
        res = q.order("created_at", desc=True).limit(limit).execute()
        data = res.data if res.data is not None else []
        if allowed is not None and not remote_id_arg:
            data = [row for row in data if _normalizar_remote_id(row.get("remote_id")) in allowed]
        return jsonify(data)
    except Exception as e:
        current_app.logger.warning("buscar_mensagens: %s", e)
        return jsonify({"erro": str(e)}), 500


@customer_bp.route('/api/mensagens/marcar-lido', methods=['POST'])
@login_required
def marcar_conversacao_lida():
    """Marca a conversa (canal + remote_id) como lida para zerar notificação ao abrir o chat."""
    if supabase is None:
        return jsonify({"status": "ok"}), 200
    try:
        data = strip_untrusted_tenant_ids(request.get_json() or {})
        canal = (data.get("canal") or "").strip().lower()
        remote_id = _normalizar_remote_id(data.get("remote_id") or "")
        if not canal or not remote_id:
            return jsonify({"erro": "canal e remote_id obrigatórios"}), 400
        if canal not in ("whatsapp", "facebook", "instagram", "website"):
            return jsonify({"erro": "canal inválido"}), 400
        if canal == "whatsapp" and not can_use_channel(str(get_current_cliente_id(current_user)), "whatsapp"):
            return jsonify({"erro": "Canal indisponível."}), 403
        if canal in ("instagram", "facebook") and not can_use_channel(str(get_current_cliente_id(current_user)), canal):
            return jsonify({"erro": "Canal indisponível."}), 403
        if canal == "whatsapp" and _waha_enabled():
            try:
                from integrations.whatsapp import waha_client
                chat_id = f"{remote_id}@c.us"
                cliente_id = str(get_current_cliente_id(current_user) or "")
                session_name = _get_cliente_whatsapp_instancia(cliente_id) or "default"
                waha_client.mark_chat_messages_read(session_name, chat_id)
            except Exception:
                pass
        from datetime import datetime, timezone
        supabase.table("painel_ultima_leitura").upsert({
            "cliente_id": str(get_current_cliente_id(current_user)),
            "canal": canal,
            "remote_id": remote_id,
            "ultima_leitura_at": datetime.now(timezone.utc).isoformat(),
        }, on_conflict="cliente_id,canal,remote_id").execute()
        return jsonify({"status": "ok"}), 200
    except Exception as e:
        current_app.logger.warning("marcar_conversacao_lida: %s", e)
        return jsonify({"status": "ok"}), 200


# --- Web Push (notificação em qualquer aba / dispositivo) ---
@customer_bp.route('/api/push/vapid-public')
@login_required
def push_vapid_public():
    """Retorna a chave pública VAPID para o front inscrever-se em push."""
    pub = getattr(settings, "VAPID_PUBLIC_KEY", None) or ""
    if not pub.strip():
        return jsonify({"erro": "Web Push não configurado (VAPID_PUBLIC_KEY)"}), 503
    return jsonify({"publicKey": pub.strip()})


@customer_bp.route('/api/push/subscribe', methods=['POST'])
@login_required
def push_subscribe():
    """Registra a inscrição Web Push do navegador para este cliente."""
    if not getattr(settings, "VAPID_PUBLIC_KEY", None) or not settings.VAPID_PUBLIC_KEY.strip():
        return jsonify({"status": "ok"}), 200
    data = strip_untrusted_tenant_ids(request.get_json() or {})
    sub = data.get("subscription")
    if not sub or not sub.get("endpoint"):
        return jsonify({"erro": "subscription com endpoint obrigatório"}), 400
    keys = sub.get("keys") or {}
    p256dh = keys.get("p256dh") or keys.get("p256dh")
    auth = keys.get("auth")
    if not p256dh or not auth:
        return jsonify({"erro": "subscription.keys (p256dh, auth) obrigatórios"}), 400
    if supabase is None:
        return jsonify({"status": "ok"}), 200
    try:
        supabase.table(Tables.PUSH_SUBSCRIPTIONS).upsert({
            "cliente_id": str(get_current_cliente_id(current_user)),
            "endpoint": sub["endpoint"],
            "p256dh": p256dh,
            "auth": auth,
        }, on_conflict="cliente_id,endpoint").execute()
        return jsonify({"status": "ok"}), 200
    except Exception as e:
        current_app.logger.warning("push_subscribe: %s", e)
        return jsonify({"status": "ok"}), 200


@customer_bp.route('/api/mensagens/contatos-nao-lidos')
@login_required
def contatos_nao_lidos():
    """Retorna por canal os remote_id de conversas com mensagem de usuário ainda não lidas (última abertura do chat)."""
    if supabase is None:
        return jsonify({"whatsapp": [], "facebook": [], "instagram": [], "website": []}), 200
    cliente_id = get_current_cliente_id(current_user)
    try:
        from services.setores_helpers import get_allowed_remote_ids_for_canal
        res = supabase.table(Tables.MENSAGENS).select("canal, remote_id, created_at").eq("cliente_id", cliente_id).eq("funcao", "user").execute()
        data = res.data if res.data else []
        max_por_conversa = {}
        for row in data:
            c = (row.get("canal") or "whatsapp").strip().lower()
            rid = _normalizar_remote_id(row.get("remote_id") or "")
            if c not in ("whatsapp", "facebook", "instagram", "website") or not rid:
                continue
            key = (c, rid)
            created = row.get("created_at") or ""
            if key not in max_por_conversa or (created and created > max_por_conversa[key]):
                max_por_conversa[key] = created
        try:
            res2 = supabase.table("painel_ultima_leitura").select("canal, remote_id, ultima_leitura_at").eq("cliente_id", cliente_id).execute()
            leituras = {(r.get("canal", "").strip().lower(), _normalizar_remote_id(r.get("remote_id") or "")): (r.get("ultima_leitura_at") or "") for r in (res2.data or [])}
        except Exception:
            leituras = {}
        por_canal = {"whatsapp": [], "facebook": [], "instagram": [], "website": []}
        seen = {c: set() for c in por_canal}
        for (c, rid), ultima_msg in max_por_conversa.items():
            if c not in por_canal or rid in seen[c]:
                continue
            if c == "whatsapp" and not can_use_channel(str(cliente_id), "whatsapp"):
                continue
            if c == "instagram" and not can_use_channel(str(cliente_id), "instagram"):
                continue
            if c == "facebook" and not can_use_channel(str(cliente_id), "facebook"):
                continue
            allowed = get_allowed_remote_ids_for_canal(cliente_id, c, current_user)
            if allowed is not None and rid not in allowed:
                continue
            ultima_leitura = leituras.get((c, rid)) or ""
            if ultima_leitura and ultima_msg and ultima_msg <= ultima_leitura:
                continue
            seen[c].add(rid)
            por_canal[c].append(rid)
        return jsonify(por_canal)
    except Exception as e:
        current_app.logger.warning("contatos_nao_lidos: %s", e)
        return jsonify({"whatsapp": [], "facebook": [], "instagram": [], "website": []}), 200


def _normalizar_remote_id(remote_id):
    """Canonicaliza remote_id: remove sufixo @... (ex.: @s.whatsapp.net)."""
    if not remote_id:
        return ""
    s = str(remote_id).strip()
    if "@" in s:
        s = s.split("@")[0].strip()
    return s


# --- Atribuição de conversa (setor de negócio + responsável) ---
@customer_bp.route('/api/conversas/atribuir', methods=['POST'])
@login_required
def api_conversas_atribuir():
    """Atribui conversa a um setor e/ou responsável (assumir conversa). Operador só pode em setores que tem acesso."""
    data = strip_untrusted_tenant_ids(request.get_json() or {})
    canal = (data.get("canal") or "whatsapp").strip().lower()
    remote_id = (data.get("remote_id") or "").strip() or None
    setor_id = data.get("setor_id")  # uuid do setor de negócio (opcional)
    responsavel_usuario_id = data.get("responsavel_usuario_id")  # uuid do usuario_interno (opcional)
    if not remote_id or canal not in ("whatsapp", "facebook", "instagram", "website"):
        return jsonify({"erro": "canal e remote_id obrigatórios"}), 400
    cliente_id = get_current_cliente_id(current_user)
    if canal == "whatsapp" and not can_use_channel(str(cliente_id), "whatsapp"):
        return jsonify({"erro": "Canal indisponível."}), 403
    if canal in ("instagram", "facebook") and not can_use_channel(str(cliente_id), canal):
        return jsonify({"erro": "Canal indisponível."}), 403
    from services.setores_helpers import can_user_access_conversation, can_user_assign_to_setor
    if not can_user_access_conversation(cliente_id, canal, remote_id, current_user):
        return jsonify({"erro": "Sem permissão para esta conversa"}), 403
    if setor_id and not can_user_assign_to_setor(setor_id, current_user, cliente_id):
        return jsonify({"erro": "Sem permissão para este setor"}), 403
    if supabase is None:
        return jsonify({"erro": "Serviço indisponível"}), 503
    try:
        from database.models import ConversacaoSetorModel
        now = datetime.now(timezone.utc).isoformat()
        payload = {
            "cliente_id": str(cliente_id),
            "canal": canal,
            "remote_id": remote_id,
            "setor": "atendimento_humano",
            "updated_at": now,
        }
        # Se o frontend enviar a chave (mesmo null), garantimos que o upsert atualize
        # o setor/responsável para limpar valores antigos.
        if "setor_id" in data:
            payload[ConversacaoSetorModel.SETOR_ID] = setor_id
        if "responsavel_usuario_id" in data:
            payload[ConversacaoSetorModel.RESPONSAVEL_USUARIO_ID] = responsavel_usuario_id
            # Buscar nome do responsável para snapshot (somente se vier um id válido)
            if responsavel_usuario_id is not None:
                r = supabase.table(Tables.USUARIOS_INTERNOS).select("nome").eq("id", responsavel_usuario_id).eq("cliente_id", cliente_id).limit(1).execute()
                if r.data and len(r.data) > 0:
                    payload[ConversacaoSetorModel.RESPONSAVEL_NOME_SNAPSHOT] = (r.data[0].get("nome") or "").strip() or None
        supabase.table(Tables.CONVERSACAO_SETOR).upsert(payload, on_conflict="cliente_id,canal,remote_id").execute()
        # Quando um operador assume, zeramos o estado do Flow Builder para evitar
        # que o bot retome algum nó antigo quando o setor voltar para IA.
        try:
            supabase.table(Tables.FLOW_USER_STATE).delete().eq(
                FlowUserStateModel.CLIENTE_ID, str(get_current_cliente_id(current_user))
            ).eq(FlowUserStateModel.CANAL, canal).eq(
                FlowUserStateModel.REMOTE_ID, remote_id
            ).execute()
        except Exception as e:
            current_app.logger.warning("api_conversas_atribuir clear flow state: %s", e)
        return jsonify({"status": "ok"}), 200
    except Exception as e:
        current_app.logger.warning("api_conversas_atribuir: %s", e)
        return jsonify({"erro": str(e)}), 500


# Stub: etiqueta de conversa (tabelas ai_* removidas). Valores fixos para o chat não quebrar.
@customer_bp.route('/api/conversacao-setor', methods=['GET'])
@login_required
def api_get_conversacao_setor():
    """Retorna o setor da conversa (atendimento_ia | atendimento_humano | atendimento_encerrado) para exibir no painel."""
    remote_id = (request.args.get("remote_id") or "").strip() or None
    canal = (request.args.get("canal") or "whatsapp").strip().lower()
    if not remote_id:
        return jsonify({"setor": "atendimento_ia", "responsavel": "IA"}), 200
    try:
        if supabase:
            try:
                r = supabase.table(Tables.CONVERSACAO_SETOR).select(
                    "setor, setor_id, responsavel_usuario_id, responsavel_nome_snapshot"
                ).eq("cliente_id", str(get_current_cliente_id(current_user))).eq("canal", canal).eq("remote_id", remote_id).limit(1).execute()
            except Exception:
                r = supabase.table(Tables.CONVERSACAO_SETOR).select("setor").eq(
                    "cliente_id", str(get_current_cliente_id(current_user))
                ).eq("canal", canal).eq("remote_id", remote_id).limit(1).execute()
            if r.data and len(r.data) > 0:
                row = r.data[0]
                setor = (row.get("setor") or "atendimento_ia").strip().lower()
                responsavel = "HUMANO" if setor == "atendimento_humano" else ("HUMANO" if setor == "atendimento_encerrado" else "IA")
                out = {"setor": setor, "responsavel": responsavel}
                setor_id_val = row.get("setor_id")
                if setor_id_val is not None:
                    out["setor_id"] = str(setor_id_val)
                    try:
                        from database.models import SetorModel
                        sr = supabase.table(Tables.SETORES).select(SetorModel.NOME).eq(
                            SetorModel.ID, setor_id_val
                        ).eq(SetorModel.CLIENTE_ID, str(get_current_cliente_id(current_user))).limit(1).execute()
                        if sr.data and len(sr.data) > 0 and sr.data[0].get(SetorModel.NOME):
                            out["setor_nome"] = (sr.data[0].get(SetorModel.NOME) or "").strip()
                    except Exception:
                        pass
                if row.get("responsavel_usuario_id") is not None:
                    out["responsavel_usuario_id"] = str(row["responsavel_usuario_id"])
                if row.get("responsavel_nome_snapshot"):
                    out["responsavel_nome_snapshot"] = row["responsavel_nome_snapshot"]
                return jsonify(out), 200
    except Exception as e:
        current_app.logger.warning("api_get_conversacao_setor: %s", e)
    return jsonify({"setor": "atendimento_ia", "responsavel": "IA"}), 200


@customer_bp.route('/api/conversacao-setor', methods=['POST', 'PUT', 'PATCH'])
@login_required
def api_atualizar_conversacao_setor():
    data = strip_untrusted_tenant_ids(request.get_json() or {})
    setor_recebido = (data.get("setor") or "atendimento_humano").strip().lower()
    remote_id = (data.get("remote_id") or "").strip() or None
    canal = (data.get("canal") or "whatsapp").strip().lower()
    # Finalizar: voltar para IA (bot responde novamente; Flow reinicia do começo na próxima mensagem)
    if setor_recebido == "atendimento_encerrado":
        setor_gravar = "atendimento_ia"
        responsavel = "IA"
    else:
        setor_gravar = setor_recebido
        responsavel = "HUMANO" if setor_gravar == "atendimento_humano" else "IA"
    if remote_id and supabase:
        try:
            from database.models import ConversacaoSetorModel
            now = datetime.now(timezone.utc).isoformat()
            payload = {
                "cliente_id": str(get_current_cliente_id(current_user)),
                "canal": canal,
                "remote_id": remote_id,
                "setor": setor_gravar,
                "updated_at": now,
            }
            if setor_recebido == "atendimento_encerrado":
                payload[ConversacaoSetorModel.SETOR_ID] = None
                payload[ConversacaoSetorModel.RESPONSAVEL_USUARIO_ID] = None
                payload[ConversacaoSetorModel.RESPONSAVEL_NOME_SNAPSHOT] = None
            else:
                if data.get("setor_id") is not None:
                    payload[ConversacaoSetorModel.SETOR_ID] = data.get("setor_id")
                if data.get("responsavel_usuario_id") is not None:
                    payload[ConversacaoSetorModel.RESPONSAVEL_USUARIO_ID] = data.get("responsavel_usuario_id")
                    payload[ConversacaoSetorModel.RESPONSAVEL_NOME_SNAPSHOT] = (data.get("responsavel_nome_snapshot") or "").strip() or None
            supabase.table(Tables.CONVERSACAO_SETOR).upsert(payload, on_conflict="cliente_id,canal,remote_id").execute()
        except Exception as e:
            current_app.logger.warning("api_atualizar_conversacao_setor upsert: %s", e)
    # Ao encerrar ou assumir humano, limpar estado do fluxo (chatbot) para essa conversa
    if setor_recebido in ("atendimento_encerrado", "atendimento_humano") and remote_id and supabase:
        try:
            supabase.table(Tables.FLOW_USER_STATE).delete().eq(
                FlowUserStateModel.CLIENTE_ID, str(get_current_cliente_id(current_user))
            ).eq(FlowUserStateModel.CANAL, canal).eq(
                FlowUserStateModel.REMOTE_ID, remote_id
            ).execute()
        except Exception as e:
            current_app.logger.warning("conversacao-setor clear flow state: %s", e)
    return jsonify({"status": "ok", "setor": setor_gravar, "responsavel": responsavel})

