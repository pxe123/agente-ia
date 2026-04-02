from datetime import datetime, timezone
import uuid

from flask import Blueprint, render_template, request, redirect, url_for, flash
from database.supabase_sq import supabase
from database.models import Tables, ClienteModel
from database.embed_key import gerar_embed_key
from services.plans import list_active_plans, get_plan, plan_entitlements, plan_trial_ends_at


public_bp = Blueprint("public", __name__)


def _apply_entitlements_to_cliente_payload(plan_key: str) -> dict:
    ent = plan_entitlements(plan_key)
    # cache simples nos campos já existentes
    return {
        ClienteModel.ACESSO_WHATSAPP: bool(ent.get("whatsapp", True)),
        ClienteModel.ACESSO_INSTAGRAM: bool(ent.get("instagram", True)),
        ClienteModel.ACESSO_MESSENGER: bool(ent.get("messenger", True)),
        ClienteModel.ACESSO_SITE: bool(ent.get("site", True)),
    }


@public_bp.route("/precos", methods=["GET"])
def precos():
    plans = list_active_plans()
    return render_template("precos.html", plans=plans)


@public_bp.route("/cadastro", methods=["GET"])
def cadastro_get():
    plan_key = (request.args.get("plano") or "").strip() or "social"
    plan = get_plan(plan_key) or get_plan("social")
    return render_template("cadastro_publico.html", plan=plan, plan_key=plan_key)


@public_bp.route("/cadastro", methods=["POST"])
def cadastro_post():
    if supabase is None:
        return render_template("cadastro_publico.html", mensagem="Supabase não configurado no servidor.", erro=True)

    nome = (request.form.get("nome") or "").strip()
    email = (request.form.get("email") or "").strip().lower()
    senha = request.form.get("senha") or ""
    senha2 = request.form.get("senha2") or ""
    plan_key = (request.form.get("plano") or "social").strip() or "social"

    plan = get_plan(plan_key)
    if not plan:
        return render_template("cadastro_publico.html", mensagem="Plano inválido.", erro=True)

    if not email:
        return render_template("cadastro_publico.html", mensagem="E-mail é obrigatório.", erro=True, plan=plan, plan_key=plan_key)
    if len(senha) < 6:
        return render_template("cadastro_publico.html", mensagem="Senha deve ter no mínimo 6 caracteres.", erro=True, plan=plan, plan_key=plan_key, email=email, nome=nome)
    if senha != senha2:
        return render_template("cadastro_publico.html", mensagem="As senhas não coincidem.", erro=True, plan=plan, plan_key=plan_key, email=email, nome=nome)

    # já existe cliente?
    try:
        r = supabase.table(Tables.CLIENTES).select("id").eq(ClienteModel.EMAIL, email).execute()
        if r.data:
            return render_template("cadastro_publico.html", mensagem="Já existe uma conta com este e-mail.", erro=True, plan=plan, plan_key=plan_key, email=email, nome=nome)
    except Exception:
        pass

    # cria no Supabase Auth (para login via JWT e consistência)
    auth_user_id = None
    try:
        resp = supabase.auth.admin.create_user(
            {
                "email": email,
                "password": senha,
                "email_confirm": True,
                "user_metadata": {"full_name": nome or email},
            }
        )
        # compat extração (mesma lógica do admin.py)
        if hasattr(resp, "user") and resp.user is not None and hasattr(resp.user, "id"):
            auth_user_id = str(resp.user.id)
        elif isinstance(resp, dict):
            u = resp.get("user") or resp.get("data", {}).get("user")
            if isinstance(u, dict) and u.get("id"):
                auth_user_id = str(u["id"])
    except Exception as e:
        return render_template("cadastro_publico.html", mensagem="Erro ao criar login: " + str(e), erro=True, plan=plan, plan_key=plan_key, email=email, nome=nome)

    trial_ends_at = plan_trial_ends_at(plan_key)
    cliente_pk = str(uuid.uuid4())
    payload = {
        ClienteModel.ID: cliente_pk,
        ClienteModel.AUTH_ID: auth_user_id,
        ClienteModel.EMAIL: email,
        ClienteModel.EMBED_KEY: gerar_embed_key(),
        ClienteModel.PLANO: plan_key,  # mantém compat com UI atual
        ClienteModel.BILLING_PLAN_KEY: plan_key,
        ClienteModel.BILLING_STATUS: "trialing" if trial_ends_at else "inactive",
        ClienteModel.TRIAL_ENDS_AT: trial_ends_at,
    }
    if nome:
        payload[ClienteModel.NOME] = nome
    payload.update(_apply_entitlements_to_cliente_payload(plan_key))

    try:
        supabase.table(Tables.CLIENTES).insert(payload).execute()
    except Exception as e:
        return render_template("cadastro_publico.html", mensagem="Erro ao criar conta: " + str(e), erro=True, plan=plan, plan_key=plan_key, email=email, nome=nome)

    flash("Conta criada! Faça login para acessar o painel.", "success")
    return redirect(url_for("customer.login"))


@public_bp.route("/assinatura", methods=["GET"])
def assinatura():
    # tela pública simples (o bloqueio/redirecionamento real acontece após login)
    return render_template("assinatura.html")


@public_bp.route("/whatsapp-atendimento", methods=["GET"])
def whatsapp_atendimento():
    """Página satélite SEO: atendimento WhatsApp para empresas."""
    return render_template("whatsapp_atendimento.html")

