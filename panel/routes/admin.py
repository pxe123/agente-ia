# panel/routes/admin.py
"""
Painel administrativo completo do SaaS.
Acesso restrito ao usuário com email = ADMIN_EMAIL.
"""
from flask import Blueprint, render_template, jsonify, request, redirect, url_for, flash, Response, current_app
from flask_login import login_required, current_user
from werkzeug.security import generate_password_hash
import json
import re
import time
import os
import uuid
import requests
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from database.supabase_sq import supabase
from database.embed_key import gerar_embed_key
from database.models import (
    Tables,
    ClienteModel,
    PlanModel,
    BillingEventModel,
    AppSettingsModel,
    AdminLogModel,
    MensagemModel,
    UsuarioInternoModel,
    ChatbotModel,
    EgressProfileModel,
    EgressAssignmentModel,
)
from base.auth import is_admin
from base.request_security import strip_untrusted_tenant_ids

admin_bp = Blueprint("admin", __name__, template_folder="../templates")


def _require_admin():
    if not current_user.is_authenticated or not is_admin(current_user):
        return None
    return True


# plan_key novo no catálogo: minúsculas (slug estável para URLs e billing)
_PLAN_KEY_SLUG = re.compile(r"^[a-z0-9][a-z0-9_-]{0,62}$")
# Filtro ?plano= na listagem: aceita chaves já gravadas no banco (legado pode ter maiúsculas, ex.: Plan_test)
_PLAN_KEY_FILTER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,62}$")


def _validate_plan_key_slug(plan_key: str):
    if not plan_key or not _PLAN_KEY_SLUG.match(plan_key):
        return False, (
            "plan_key inválido: use apenas letras minúsculas, números, hífen e underscore; "
            "comece com letra ou número (ex.: social, pro_anual)."
        )
    return True, ""


def _log_admin_action(action: str, target_id: str | None = None) -> None:
    """Auditoria em admin_logs (falha silenciosa se tabela não existir)."""
    if supabase is None:
        return
    try:
        admin_id = (
            (getattr(current_user, "email", None) or str(getattr(current_user, "id", "") or "")).strip() or None
        )
        row = {
            AdminLogModel.ADMIN_ID: admin_id,
            AdminLogModel.ACTION: (action or "")[:2000],
        }
        tid = (target_id or "").strip()[:500]
        row[AdminLogModel.TARGET_ID] = tid or None
        supabase.table(Tables.ADMIN_LOGS).insert(row).execute()
    except Exception:
        pass


def _validate_plano_filter_param(value: str):
    """Parâmetro ?plano= só leitura: permite coincidir com plan_key real no DB (inclui legado com maiúsculas)."""
    if not value:
        return True, ""
    if not _PLAN_KEY_FILTER.match(value):
        return False, (
            "Valor de plano inválido no filtro: use letras, números, ponto, hífen e underscore "
            "(máx. 63 caracteres); não use vírgulas."
        )
    return True, ""


def _mp_subscriptions_admin_url(preapproval_id: str) -> str | None:
    pid = (preapproval_id or "").strip()
    if not pid:
        return None
    return f"https://www.mercadopago.com.br/subscriptions/detail?id={pid}"


def _fetch_processed_billing_events(cliente_id: str, preapproval_id: str | None) -> list:
    """Eventos processados do cliente: por cliente_id (novo) ou data_id = preapproval (legado)."""
    if supabase is None:
        return []
    pid = (preapproval_id or "").strip() or None
    try:
        q = (
            supabase.table(Tables.BILLING_EVENTS)
            .select("*")
            .eq(BillingEventModel.STATUS, "processed")
        )
        if pid:
            q = q.or_(
                f"{BillingEventModel.CLIENTE_ID}.eq.{cliente_id},{BillingEventModel.DATA_ID}.eq.{pid}"
            )
        else:
            q = q.eq(BillingEventModel.CLIENTE_ID, cliente_id)
        r = q.order(BillingEventModel.PROCESSED_AT, desc=True).limit(80).execute()
        return r.data or []
    except Exception:
        if not pid:
            return []
        try:
            r = (
                supabase.table(Tables.BILLING_EVENTS)
                .select("*")
                .eq(BillingEventModel.STATUS, "processed")
                .eq(BillingEventModel.DATA_ID, pid)
                .order(BillingEventModel.PROCESSED_AT, desc=True)
                .limit(80)
                .execute()
            )
            return r.data or []
        except Exception:
            return []


@admin_bp.route("/")
@admin_bp.route("/dashboard")
@login_required
def dashboard():
    if not _require_admin():
        return "Acesso negado", 403
    return render_template("admin/dashboard.html")


@admin_bp.route("/clientes")
@login_required
def clientes():
    if not _require_admin():
        return "Acesso negado", 403
    return render_template("admin/clientes.html")


@admin_bp.route("/planos")
@login_required
def planos():
    if not _require_admin():
        return "Acesso negado", 403
    return render_template("admin/planos.html")


@admin_bp.route("/canais-globais")
@login_required
def canais_globais():
    if not _require_admin():
        return "Acesso negado", 403
    return render_template("admin/canais-globais.html")


@admin_bp.route("/egress")
@login_required
def egress():
    if not _require_admin():
        return "Acesso negado", 403
    return render_template("admin/egress.html")


def _egress_profile_public(row: dict) -> dict:
    """Profile sem credenciais sensíveis."""
    return {
        "id": row.get(EgressProfileModel.ID),
        "name": row.get(EgressProfileModel.NAME),
        "host": row.get(EgressProfileModel.HOST),
        "port": row.get(EgressProfileModel.PORT),
        "username": row.get(EgressProfileModel.USERNAME),
        "type": row.get(EgressProfileModel.TYPE),
        "country": row.get(EgressProfileModel.COUNTRY),
        "is_active": row.get(EgressProfileModel.IS_ACTIVE),
        "max_clients": row.get(EgressProfileModel.MAX_CLIENTS),
        "last_test_ip": row.get(EgressProfileModel.LAST_TEST_IP),
        "last_test_latency": row.get(EgressProfileModel.LAST_TEST_LATENCY),
        "last_test_at": row.get(EgressProfileModel.LAST_TEST_AT),
        "created_at": row.get(EgressProfileModel.CREATED_AT),
        "updated_at": row.get(EgressProfileModel.UPDATED_AT),
    }


@admin_bp.route("/api/egress", methods=["GET"])
@login_required
def api_egress_list():
    if not _require_admin():
        return jsonify({"ok": False, "erro": "Acesso negado"}), 403
    if supabase is None:
        return jsonify({"ok": True, "profiles": []}), 200
    try:
        pr = supabase.table(Tables.EGRESS_PROFILES).select("*").order(EgressProfileModel.CREATED_AT, desc=True).execute()
        ar = supabase.table(Tables.EGRESS_ASSIGNMENTS).select(EgressAssignmentModel.EGRESS_PROFILE_ID, EgressAssignmentModel.CLIENTE_ID).execute()
        assigns = ar.data or []
        used_by_profile: dict[str, int] = defaultdict(int)
        tenants_by_profile: dict[str, list[str]] = defaultdict(list)
        for a in assigns:
            pid = str(a.get(EgressAssignmentModel.EGRESS_PROFILE_ID) or "")
            cid = str(a.get(EgressAssignmentModel.CLIENTE_ID) or "")
            if not pid:
                continue
            used_by_profile[pid] += 1
            if cid:
                tenants_by_profile[pid].append(cid)
        profiles_out = []
        for row in (pr.data or []):
            pid = str(row.get(EgressProfileModel.ID) or "")
            pub = _egress_profile_public(row)
            used = used_by_profile.get(pid, 0)
            mx = int(row.get(EgressProfileModel.MAX_CLIENTS) or 2)
            pub["used_clients"] = used
            pub["usage_pct"] = int(round((used / mx) * 100)) if mx > 0 else 0
            pub["tenants"] = tenants_by_profile.get(pid, [])
            profiles_out.append(pub)
        return jsonify({"ok": True, "profiles": profiles_out}), 200
    except Exception as e:
        return jsonify({"ok": False, "erro": str(e)}), 500


@admin_bp.route("/api/egress", methods=["POST"])
@login_required
def api_egress_create():
    if not _require_admin():
        return jsonify({"ok": False, "erro": "Acesso negado"}), 403
    if supabase is None:
        return jsonify({"ok": False, "erro": "Supabase indisponível"}), 503
    data = strip_untrusted_tenant_ids(request.json or request.form or {})
    name = (data.get("name") or "").strip()
    host = (data.get("host") or "").strip()
    port = int(data.get("port") or 0)
    username = (data.get("username") or "").strip() or None
    password = (data.get("password") or "").strip() or None
    typ = (data.get("type") or "").strip() or None
    country = (data.get("country") or "").strip() or None
    is_active = bool(data.get("is_active", True))
    max_clients = int(data.get("max_clients") or 2)
    if not name or not host or not port:
        return jsonify({"ok": False, "erro": "name/host/port são obrigatórios."}), 400
    try:
        row = {
            EgressProfileModel.NAME: name,
            EgressProfileModel.HOST: host,
            EgressProfileModel.PORT: port,
            EgressProfileModel.USERNAME: username,
            EgressProfileModel.PASSWORD: password,
            EgressProfileModel.TYPE: typ,
            EgressProfileModel.COUNTRY: country,
            EgressProfileModel.IS_ACTIVE: is_active,
            EgressProfileModel.MAX_CLIENTS: max(1, max_clients),
            EgressProfileModel.UPDATED_AT: datetime.now(timezone.utc).isoformat(),
        }
        r = supabase.table(Tables.EGRESS_PROFILES).insert(row).execute()
        _log_admin_action("egress_create", target_id=name)
        return jsonify({"ok": True, "profile": _egress_profile_public((r.data or [{}])[0])}), 200
    except Exception as e:
        return jsonify({"ok": False, "erro": str(e)}), 400


@admin_bp.route("/api/egress/<profile_id>", methods=["PUT"])
@login_required
def api_egress_update(profile_id: str):
    if not _require_admin():
        return jsonify({"ok": False, "erro": "Acesso negado"}), 403
    if supabase is None:
        return jsonify({"ok": False, "erro": "Supabase indisponível"}), 503
    pid = (profile_id or "").strip()
    data = strip_untrusted_tenant_ids(request.json or request.form or {})
    patch: dict = {}
    for k in ("name", "host", "type", "country"):
        if k in data:
            patch[k] = (data.get(k) or "").strip() or None
    if "port" in data:
        patch["port"] = int(data.get("port") or 0)
    if "username" in data:
        patch["username"] = (data.get("username") or "").strip() or None
    # password é write-only: só atualiza se vier preenchida
    if (data.get("password") or "").strip():
        patch["password"] = (data.get("password") or "").strip()
    if "is_active" in data:
        patch["is_active"] = bool(data.get("is_active"))
    if "max_clients" in data:
        patch["max_clients"] = max(1, int(data.get("max_clients") or 2))
    patch["updated_at"] = datetime.now(timezone.utc).isoformat()
    try:
        r = supabase.table(Tables.EGRESS_PROFILES).update(patch).eq(EgressProfileModel.ID, pid).execute()
        _log_admin_action("egress_update", target_id=pid)
        return jsonify({"ok": True, "profile": _egress_profile_public((r.data or [{}])[0])}), 200
    except Exception as e:
        return jsonify({"ok": False, "erro": str(e)}), 400


@admin_bp.route("/api/egress/<profile_id>", methods=["DELETE"])
@login_required
def api_egress_delete(profile_id: str):
    if not _require_admin():
        return jsonify({"ok": False, "erro": "Acesso negado"}), 403
    if supabase is None:
        return jsonify({"ok": False, "erro": "Supabase indisponível"}), 503
    pid = (profile_id or "").strip()
    try:
        # Não permitir deletar se em uso
        c = supabase.table(Tables.EGRESS_ASSIGNMENTS).select(EgressAssignmentModel.ID, count="exact").eq(EgressAssignmentModel.EGRESS_PROFILE_ID, pid).execute()
        used = int(getattr(c, "count", None) or len(c.data or []))
        if used > 0:
            return jsonify({"ok": False, "erro": f"Perfil em uso por {used} cliente(s)."}), 400
        supabase.table(Tables.EGRESS_PROFILES).delete().eq(EgressProfileModel.ID, pid).execute()
        _log_admin_action("egress_delete", target_id=pid)
        return jsonify({"ok": True}), 200
    except Exception as e:
        return jsonify({"ok": False, "erro": str(e)}), 400


@admin_bp.route("/api/egress/<profile_id>/assign", methods=["POST"])
@login_required
def api_egress_assign(profile_id: str):
    if not _require_admin():
        return jsonify({"ok": False, "erro": "Acesso negado"}), 403
    data = strip_untrusted_tenant_ids(request.json or request.form or {})
    cliente_id = (data.get("cliente_id") or "").strip()
    pid = (profile_id or "").strip()
    if not cliente_id or not pid:
        return jsonify({"ok": False, "erro": "cliente_id/profile_id obrigatórios."}), 400
    try:
        from services.network.egress_manager import assign_profile

        assign_profile(cliente_id, pid)
        _log_admin_action("egress_assign", target_id=f"{pid}:{cliente_id}")
        return jsonify({"ok": True}), 200
    except Exception as e:
        return jsonify({"ok": False, "erro": str(e)}), 400


@admin_bp.route("/api/egress/<profile_id>/release", methods=["POST"])
@login_required
def api_egress_release(profile_id: str):
    if not _require_admin():
        return jsonify({"ok": False, "erro": "Acesso negado"}), 403
    data = strip_untrusted_tenant_ids(request.json or request.form or {})
    cliente_id = (data.get("cliente_id") or "").strip()
    if not cliente_id:
        return jsonify({"ok": False, "erro": "cliente_id obrigatório."}), 400
    try:
        from services.network.egress_manager import release_profile

        release_profile(cliente_id)
        _log_admin_action("egress_release", target_id=f"{profile_id}:{cliente_id}")
        return jsonify({"ok": True}), 200
    except Exception as e:
        return jsonify({"ok": False, "erro": str(e)}), 400


@admin_bp.route("/api/egress/<profile_id>/test", methods=["POST"])
@login_required
def api_egress_test(profile_id: str):
    if not _require_admin():
        return jsonify({"ok": False, "erro": "Acesso negado"}), 403
    if supabase is None:
        return jsonify({"ok": False, "erro": "Supabase indisponível"}), 503
    pid = (profile_id or "").strip()
    try:
        r = (
            supabase.table(Tables.EGRESS_PROFILES)
            .select("*")
            .eq(EgressProfileModel.ID, pid)
            .limit(1)
            .execute()
        )
        if not r.data:
            return jsonify({"ok": False, "erro": "Perfil não encontrado."}), 404
        row = r.data[0]
        host = (row.get(EgressProfileModel.HOST) or "").strip()
        port = int(row.get(EgressProfileModel.PORT) or 0)
        username = (row.get(EgressProfileModel.USERNAME) or "").strip()
        password = (row.get(EgressProfileModel.PASSWORD) or "").strip()
        if not host or not port:
            return jsonify({"ok": False, "erro": "host/port inválidos no perfil."}), 400

        proxy_url = f"http://{host}:{port}"
        proxies = {"http": proxy_url, "https": proxy_url}
        auth = (username, password) if username and password else None

        def _call(url: str) -> tuple[bool, dict, int]:
            t0 = time.time()
            try:
                rr = requests.get(url, proxies=proxies, auth=auth, timeout=20)
                ms = int(round((time.time() - t0) * 1000))
                ok = rr.status_code >= 200 and rr.status_code < 300
                data = {}
                try:
                    data = rr.json()
                except Exception:
                    data = {"text": rr.text[:2000]}
                return ok, data, ms
            except Exception as e:
                ms = int(round((time.time() - t0) * 1000))
                return False, {"error": str(e)}, ms

        ok1, d1, ms1 = _call("https://api.ipify.org?format=json")
        ok2, d2, ms2 = _call("https://httpbin.org/ip")

        ip1 = (d1.get("ip") if isinstance(d1, dict) else None) or None
        ip2 = None
        if isinstance(d2, dict):
            if isinstance(d2.get("origin"), str):
                ip2 = d2.get("origin")
        ip_eff = ip1 or ip2
        latency_ms = ms1 + ms2

        now_iso = datetime.now(timezone.utc).isoformat()
        supabase.table(Tables.EGRESS_PROFILES).update(
            {
                EgressProfileModel.LAST_TEST_IP: (ip_eff or None),
                EgressProfileModel.LAST_TEST_LATENCY: int(latency_ms),
                EgressProfileModel.LAST_TEST_AT: now_iso,
                EgressProfileModel.UPDATED_AT: now_iso,
            }
        ).eq(EgressProfileModel.ID, pid).execute()

        _log_admin_action("egress_test", target_id=pid)
        return jsonify(
            {
                "ok": bool(ok1 and ok2 and ip_eff),
                "ipify": {"ok": ok1, "data": d1, "latency_ms": ms1},
                "httpbin": {"ok": ok2, "data": d2, "latency_ms": ms2},
                "ip_efetivo": ip_eff,
                "latency_ms": latency_ms,
            }
        ), 200
    except Exception as e:
        return jsonify({"ok": False, "erro": str(e)}), 400


@admin_bp.route("/financeiro")
@login_required
def financeiro():
    if not _require_admin():
        return "Acesso negado", 403
    return render_template("admin/financeiro.html")


@admin_bp.route("/cobranca")
@login_required
def cobranca():
    if not _require_admin():
        return "Acesso negado", 403
    return redirect(url_for("admin.clientes"))


@admin_bp.route("/cadastro", methods=["GET"])
@login_required
def cadastro():
    if not _require_admin():
        return "Acesso negado", 403
    return render_template("admin/cadastro.html")


def _auth_user_id_from_response(resp):
    """Extrai o id do usuário da resposta do auth.admin.create_user (supabase-py)."""
    if hasattr(resp, "user") and resp.user is not None and hasattr(resp.user, "id"):
        return str(resp.user.id)
    if isinstance(resp, dict):
        u = resp.get("user") or resp.get("data", {}).get("user")
        if isinstance(u, dict) and u.get("id"):
            return str(u["id"])
    return None


@admin_bp.route("/cadastro", methods=["POST"])
@login_required
def cadastro_post():
    if not _require_admin():
        return "Acesso negado", 403
    nome = (request.form.get("nome") or "").strip()
    email = (request.form.get("email") or "").strip().lower()
    senha = request.form.get("senha") or ""
    senha2 = request.form.get("senha2") or ""
    plano = (request.form.get("plano") or "social").strip() or "social"
    if not email:
        return render_template("admin/cadastro.html", mensagem="E-mail é obrigatório.", erro=True)
    if len(senha) < 6:
        return render_template("admin/cadastro.html", mensagem="Senha deve ter no mínimo 6 caracteres.", erro=True, nome=nome, email=email)
    if senha != senha2:
        return render_template("admin/cadastro.html", mensagem="As senhas não coincidem.", erro=True, nome=nome, email=email)
    try:
        r = supabase.table(Tables.CLIENTES).select("id").eq("email", email).execute()
        if r.data and len(r.data) > 0:
            return render_template("admin/cadastro.html", mensagem="Já existe um cliente com este e-mail.", erro=True, nome=nome, email=email)

        auth_user_id = None
        if supabase is not None:
            try:
                resp = supabase.auth.admin.create_user({
                    "email": email,
                    "password": senha,
                    "email_confirm": True,
                    "user_metadata": {"full_name": nome or email},
                })
                auth_user_id = _auth_user_id_from_response(resp)
            except Exception as auth_err:
                err_msg = str(auth_err).lower()
                if "already" in err_msg or "registered" in err_msg or "exists" in err_msg:
                    return render_template(
                        "admin/cadastro.html",
                        mensagem="Este e-mail já está registrado no login (Supabase Auth). Use outro e-mail ou peça ao cliente para acessar o painel.",
                        erro=True, nome=nome, email=email,
                    )
                raise

        cliente_pk = str(uuid.uuid4())
        payload = {
            ClienteModel.ID: cliente_pk,
            ClienteModel.AUTH_ID: auth_user_id,
            ClienteModel.EMAIL: email,
            ClienteModel.EMBED_KEY: gerar_embed_key(),
            ClienteModel.PLANO: plano,
            ClienteModel.ACESSO_WHATSAPP: True,
            ClienteModel.ACESSO_INSTAGRAM: True,
            ClienteModel.ACESSO_MESSENGER: True,
            ClienteModel.ACESSO_SITE: True,
        }
        if nome:
            payload[ClienteModel.NOME] = nome
        try:
            supabase.table(Tables.CLIENTES).insert(payload).execute()
        except Exception as col_err:
            if nome and ClienteModel.NOME in payload and ("nome" in str(col_err).lower() or "column" in str(col_err).lower()):
                del payload[ClienteModel.NOME]
                supabase.table(Tables.CLIENTES).insert(payload).execute()
            else:
                raise
        flash(
            "Cliente cadastrado com sucesso. Ele já pode fazer login na tela de login com este e-mail e a senha definida.",
            "success",
        )
        return redirect(url_for("admin.clientes"))
    except Exception as e:
        return render_template("admin/cadastro.html", mensagem="Erro ao cadastrar: " + str(e), erro=True, nome=nome, email=email)


# --- APIs ---

@admin_bp.route("/api/stats")
@login_required
def api_stats():
    if not _require_admin():
        return jsonify({"erro": "Não autorizado"}), 403
    try:
        r = supabase.table(Tables.CLIENTES).select("id, meta_wa_phone_number_id, plano").execute()
        lista = r.data or []
        total_clientes = len(lista)
        clientes_com_whatsapp = sum(1 for x in lista if x.get("meta_wa_phone_number_id"))
        planos = {}
        for c in lista:
            p = c.get("plano") or "sem_plano"
            planos[p] = planos.get(p, 0) + 1

        r2 = supabase.table("historico_mensagens").select("id").limit(1).execute()
        try:
            r2_count = supabase.table("historico_mensagens").select("id", count="exact").execute()
            total_mensagens = getattr(r2_count, "count", None) or len(r2_count.data or [])
        except Exception:
            total_mensagens = 0

        return jsonify({
            "total_clientes": total_clientes,
            "total_mensagens": total_mensagens,
            "clientes_com_whatsapp": clientes_com_whatsapp,
            "por_plano": planos,
        })
    except Exception as e:
        return jsonify({"erro": str(e)}), 500


@admin_bp.route("/api/waha-status", methods=["GET"])
@login_required
def api_waha_status():
    """Health check do WAHA (WAHA_URL / WAHA_API_KEY no .env)."""
    if not _require_admin():
        return jsonify({"erro": "Não autorizado"}), 403
    from services.waha_health import probe_waha_status

    return jsonify(probe_waha_status())


@admin_bp.route("/api/meta-status", methods=["GET"])
@login_required
def api_meta_status():
    """
    Conectividade com a Graph API (app_id|app_secret). Usada por Instagram e Messenger.
    Query opcional: ?channel=instagram|messenger (só para eco na resposta / UI).
    """
    if not _require_admin():
        return jsonify({"erro": "Não autorizado"}), 403
    from services.meta_health import probe_meta_graph_app

    ch = (request.args.get("channel") or "").strip().lower()
    if ch not in ("instagram", "messenger", "facebook", ""):
        ch = ""
    out = probe_meta_graph_app()
    if ch:
        out["channel"] = ch
    return jsonify(out)


@admin_bp.route("/api/clientes/overview", methods=["GET"])
@login_required
def api_clientes_overview():
    if not _require_admin():
        return jsonify({"erro": "Não autorizado"}), 403
    if supabase is None:
        return jsonify({"ok": False, "erro": "Supabase indisponível."}), 503
    plans_price: dict[str, float] = {}
    try:
        pr = supabase.table(Tables.PLANS).select(f"{PlanModel.PLAN_KEY},{PlanModel.PRICE}").execute()
        for p in pr.data or []:
            k = (p.get(PlanModel.PLAN_KEY) or "").strip()
            if not k:
                continue
            try:
                plans_price[k] = float(p.get(PlanModel.PRICE) or 0)
            except Exception:
                plans_price[k] = 0.0
    except Exception:
        pass

    active = 0
    past_due = 0
    mrr = 0.0
    try:
        cr = (
            supabase.table(Tables.CLIENTES)
            .select(f"{ClienteModel.BILLING_STATUS},{ClienteModel.BILLING_PLAN_KEY},{ClienteModel.PLANO}")
            .execute()
        )
        for row in cr.data or []:
            st = (row.get(ClienteModel.BILLING_STATUS) or "").strip().lower()
            pk = (row.get(ClienteModel.BILLING_PLAN_KEY) or row.get(ClienteModel.PLANO) or "").strip()
            price = plans_price.get(pk, 0.0)
            if st in ("active", "authorized"):
                active += 1
                mrr += price
            elif st == "past_due":
                past_due += 1
    except Exception as e:
        return jsonify({"ok": False, "erro": str(e)}), 500

    return jsonify(
        {
            "ok": True,
            "active_subscribers": active,
            "past_due": past_due,
            "mrr_estimated": round(mrr, 2),
            "currency": "BRL",
        }
    )


@admin_bp.route("/api/clientes")
@login_required
def api_clientes():
    if not _require_admin():
        return jsonify({"erro": "Não autorizado"}), 403
    try:
        plano_filtro = (request.args.get("plano") or "").strip()
        ok_pf, err_pf = _validate_plano_filter_param(plano_filtro)
        if not ok_pf:
            return jsonify({"erro": err_pf}), 400

        order = request.args.get("order") or "created_at"
        if order not in ("created_at", "email", "plano"):
            order = "created_at"
        col = order

        def _clientes_base_query():
            bq = supabase.table(Tables.CLIENTES).select("*")
            if plano_filtro:
                bq = bq.or_(
                    f"{ClienteModel.PLANO}.eq.{plano_filtro},{ClienteModel.BILLING_PLAN_KEY}.eq.{plano_filtro}"
                )
            return bq

        try:
            res = _clientes_base_query().order(col, desc=True).execute()
        except Exception:
            try:
                res = _clientes_base_query().order("criado_em", desc=True).execute()
            except Exception:
                res = _clientes_base_query().order("email").execute()
        data = res.data or []

        plans_by_key: dict = {}
        try:
            pr = supabase.table(Tables.PLANS).select("*").execute()
            for p in pr.data or []:
                k = (p.get(PlanModel.PLAN_KEY) or "").strip()
                if k:
                    plans_by_key[k] = p
        except Exception:
            pass

        op_count = defaultdict(int)
        try:
            r_ops = (
                supabase.table(Tables.USUARIOS_INTERNOS)
                .select(UsuarioInternoModel.CLIENTE_ID)
                .eq(UsuarioInternoModel.ATIVO, True)
                .execute()
            )
            for row in r_ops.data or []:
                cid = row.get(UsuarioInternoModel.CLIENTE_ID)
                if cid:
                    op_count[str(cid)] += 1
        except Exception:
            pass

        bot_count = defaultdict(int)
        try:
            r_bots = supabase.table(Tables.CHATBOTS).select(ChatbotModel.CLIENTE_ID).execute()
            for row in r_bots.data or []:
                cid = row.get(ChatbotModel.CLIENTE_ID)
                if cid:
                    bot_count[str(cid)] += 1
        except Exception:
            pass

        last_by_c: dict[str, str] = {}
        try:
            msg_res = (
                supabase.table(Tables.MENSAGENS)
                .select(f"{MensagemModel.CLIENTE_ID},{MensagemModel.CRIADO_EM}")
                .order(MensagemModel.CRIADO_EM, desc=True)
                .limit(8000)
                .execute()
            )
            for row in msg_res.data or []:
                cid = row.get(MensagemModel.CLIENTE_ID)
                if cid is None:
                    continue
                cs = str(cid)
                if cs not in last_by_c:
                    last_by_c[cs] = row.get(MensagemModel.CRIADO_EM)
        except Exception:
            pass

        for c in data:
            c["_tem_whatsapp"] = bool(c.get("whatsapp_instancia"))
            c["_tem_wa_meta"] = bool(c.get(ClienteModel.META_WA_PHONE_NUMBER_ID))
            c["_tem_instagram"] = bool(c.get(ClienteModel.META_IG_PAGE_ID))
            c["_tem_messenger"] = bool(c.get(ClienteModel.META_FB_PAGE_ID))
            c["_tem_site"] = bool(c.get(ClienteModel.WEBSITE_CHAT_EMBED_KEY))
            created = c.get("created_at") or c.get("criado_em")
            c["_conta_desde"] = created

            pk = (c.get(ClienteModel.BILLING_PLAN_KEY) or "").strip() or (c.get(ClienteModel.PLANO) or "").strip()
            prow = plans_by_key.get(pk) or {}
            c["_plan_display_name"] = (prow.get(PlanModel.NAME) or "").strip() or (pk or "—")
            ent = prow.get(PlanModel.ENTITLEMENTS_JSON) or {}
            if isinstance(ent, str):
                try:
                    ent = json.loads(ent)
                except Exception:
                    ent = {}
            lim_op = None
            lim_bots = None
            if isinstance(ent, dict):
                for lk in ("max_operadores", "max_usuarios_internos"):
                    v = ent.get(lk)
                    if v is not None:
                        try:
                            vi = int(v)
                            lim_op = vi if lim_op is None else min(lim_op, vi)
                        except Exception:
                            pass
                vcb = ent.get("max_chatbots")
                if vcb is not None:
                    try:
                        lim_bots = int(vcb)
                    except Exception:
                        pass
            cid_str = str(c.get("id") or "")
            n_op = op_count.get(cid_str, 0)
            c["_operadores_uso"] = f"{n_op} / {lim_op}" if lim_op is not None else f"{n_op} / ∞"
            n_bot = bot_count.get(cid_str, 0)
            c["_chatbots_uso"] = f"{n_bot} / {lim_bots}" if lim_bots is not None else f"{n_bot} / ∞"
            c["_ultima_atividade"] = last_by_c.get(cid_str)

        return jsonify(data)
    except Exception as e:
        return jsonify({"erro": str(e)}), 500


@admin_bp.route("/api/toggle-acesso/<user_id>", methods=["POST"])
@login_required
def toggle_acesso(user_id):
    if not _require_admin():
        return jsonify({"erro": "Não autorizado"}), 403
    data = strip_untrusted_tenant_ids(request.json or {})
    campo = data.get("campo")
    if campo not in (ClienteModel.ACESSO_WHATSAPP, ClienteModel.ACESSO_INSTAGRAM,
                    ClienteModel.ACESSO_MESSENGER, ClienteModel.ACESSO_SITE):
        return jsonify({"erro": "Campo inválido"}), 400
    try:
        res = supabase.table(Tables.CLIENTES).select(campo).eq("id", user_id).execute()
        if not res.data:
            return jsonify({"erro": "Cliente não encontrado"}), 404
        atual = res.data[0].get(campo)
        if atual is None:
            atual = True
        novo = not atual
        supabase.table(Tables.CLIENTES).update({campo: novo}).eq("id", user_id).execute()
        return jsonify({"status": "ok", "valor": novo})
    except Exception as e:
        return jsonify({"erro": str(e)}), 500


@admin_bp.route("/api/cliente/<user_id>")
@login_required
def api_cliente(user_id):
    if not _require_admin():
        return jsonify({"erro": "Não autorizado"}), 403
    try:
        res = supabase.table(Tables.CLIENTES).select("*").eq("id", user_id).single().execute()
        if not res.data:
            return jsonify({"erro": "Cliente não encontrado"}), 404
        return jsonify(res.data)
    except Exception as e:
        return jsonify({"erro": str(e)}), 500


# --- Plans APIs ---

@admin_bp.route("/api/plans", methods=["GET"])
@login_required
def api_plans_list():
    if not _require_admin():
        return jsonify({"erro": "Não autorizado"}), 403
    try:
        r = supabase.table(Tables.PLANS).select("*").order(PlanModel.PRICE).execute()
        plans = r.data or []

        plano_counts = defaultdict(int)
        billing_counts = defaultdict(int)
        try:
            cr = (
                supabase.table(Tables.CLIENTES)
                .select(f"{ClienteModel.PLANO},{ClienteModel.BILLING_PLAN_KEY}")
                .execute()
            )
            for row in cr.data or []:
                pk = (row.get(ClienteModel.PLANO) or "").strip() or None
                bk = (row.get(ClienteModel.BILLING_PLAN_KEY) or "").strip() or None
                if pk:
                    plano_counts[pk] += 1
                if bk:
                    billing_counts[bk] += 1
        except Exception:
            pass

        for p in plans:
            key = (p.get(PlanModel.PLAN_KEY) or "").strip()
            p["usage"] = {
                "clientes_plano": plano_counts.get(key, 0),
                "clientes_billing": billing_counts.get(key, 0),
            }

        return jsonify({"ok": True, "plans": plans})
    except Exception as e:
        return jsonify({"ok": False, "erro": str(e)}), 500


def _ent_json_obj(v):
    if isinstance(v, dict):
        return dict(v)
    if isinstance(v, str):
        try:
            p = json.loads(v)
            if isinstance(p, dict):
                return p
        except Exception:
            return {}
    return {}


def _plan_private_fields(data: dict) -> tuple[bool, str | None]:
    is_private = bool(data.get("is_private", False))
    private_cliente_id = (data.get("private_cliente_id") or "").strip() or None
    if is_private and not private_cliente_id:
        raise ValueError("Informe o ID do cliente para um plano privado.")
    if is_private:
        try:
            private_cliente_id = str(uuid.UUID(private_cliente_id or ""))
        except Exception:
            raise ValueError("ID do cliente inválido para plano privado.")
    if is_private and supabase is not None:
        exists = (
            supabase.table(Tables.CLIENTES)
            .select(ClienteModel.ID)
            .eq(ClienteModel.ID, private_cliente_id)
            .limit(1)
            .execute()
        )
        if not (exists.data or []):
            raise ValueError("Cliente informado para o plano privado não foi encontrado.")
    if not is_private:
        private_cliente_id = None
    return is_private, private_cliente_id


def _normalize_featured_plans(selected_plan_key: str):
    """Mantém apenas 1 plano como featured=true no entitlements_json."""
    if supabase is None or not selected_plan_key:
        return
    try:
        r = supabase.table(Tables.PLANS).select(f"{PlanModel.PLAN_KEY},{PlanModel.ENTITLEMENTS_JSON}").execute()
        for row in (r.data or []):
            pk = (row.get(PlanModel.PLAN_KEY) or "").strip()
            if not pk:
                continue
            ent = _ent_json_obj(row.get(PlanModel.ENTITLEMENTS_JSON))
            should_be_featured = (pk == selected_plan_key)
            if bool(ent.get("featured")) == should_be_featured:
                continue
            ent["featured"] = should_be_featured
            supabase.table(Tables.PLANS).update({PlanModel.ENTITLEMENTS_JSON: ent}).eq(PlanModel.PLAN_KEY, pk).execute()
    except Exception:
        pass


@admin_bp.route("/api/plans", methods=["POST"])
@login_required
def api_plans_create():
    if not _require_admin():
        return jsonify({"erro": "Não autorizado"}), 403
    data = strip_untrusted_tenant_ids(request.json or {})
    plan_key = (data.get("plan_key") or "").strip()
    name = (data.get("name") or plan_key).strip()
    price = data.get("price")
    currency = (data.get("currency") or "BRL").strip() or "BRL"
    trial_days = data.get("trial_days", 7)
    active = bool(data.get("active", True))
    entitlements_json = data.get("entitlements_json") or {}
    if not plan_key:
        return jsonify({"ok": False, "erro": "plan_key é obrigatório."}), 400
    ok_pk, err_pk = _validate_plan_key_slug(plan_key)
    if not ok_pk:
        return jsonify({"ok": False, "erro": err_pk}), 400
    try:
        is_private, private_cliente_id = _plan_private_fields(data)
        payload = {
            PlanModel.PLAN_KEY: plan_key,
            PlanModel.NAME: name,
            PlanModel.PRICE: float(price or 0),
            PlanModel.CURRENCY: currency,
            PlanModel.TRIAL_DAYS: int(trial_days or 0),
            PlanModel.ACTIVE: active,
            PlanModel.ENTITLEMENTS_JSON: entitlements_json,
            getattr(PlanModel, "IS_PRIVATE", "is_private"): is_private,
            getattr(PlanModel, "PRIVATE_CLIENTE_ID", "private_cliente_id"): private_cliente_id,
        }
        supabase.table(Tables.PLANS).insert(payload).execute()
        ent_obj = _ent_json_obj(entitlements_json)
        if bool(ent_obj.get("featured")):
            _normalize_featured_plans(plan_key)
        _log_admin_action(f"plan.create {plan_key} name={name} private={is_private}", plan_key)
        return jsonify({"ok": True})
    except ValueError as e:
        return jsonify({"ok": False, "erro": str(e)}), 400
    except Exception as e:
        return jsonify({"ok": False, "erro": str(e)}), 500


@admin_bp.route("/api/plans/<plan_key>", methods=["PATCH"])
@login_required
def api_plans_update(plan_key):
    if not _require_admin():
        return jsonify({"erro": "Não autorizado"}), 403
    data = strip_untrusted_tenant_ids(request.json or {})
    payload = {}
    for k in ("name", "price", "currency", "trial_days", "active", "entitlements_json"):
        if k in data:
            payload[k] = data[k]
    if "is_private" in data or "private_cliente_id" in data:
        try:
            is_private, private_cliente_id = _plan_private_fields(data)
        except ValueError as e:
            return jsonify({"ok": False, "erro": str(e)}), 400
        payload[getattr(PlanModel, "IS_PRIVATE", "is_private")] = is_private
        payload[getattr(PlanModel, "PRIVATE_CLIENTE_ID", "private_cliente_id")] = private_cliente_id
    if "price" in payload:
        try:
            payload["price"] = float(payload["price"] or 0)
        except Exception:
            payload["price"] = 0.0
    if "trial_days" in payload:
        try:
            payload["trial_days"] = int(payload["trial_days"] or 0)
        except Exception:
            payload["trial_days"] = 0
    if not payload:
        return jsonify({"ok": False, "erro": "Nenhum campo para atualizar."}), 400
    try:
        supabase.table(Tables.PLANS).update(payload).eq(PlanModel.PLAN_KEY, plan_key).execute()
        if "entitlements_json" in payload:
            ent_obj = _ent_json_obj(payload.get("entitlements_json"))
            if bool(ent_obj.get("featured")):
                _normalize_featured_plans(plan_key)
        keys = ",".join(sorted(payload.keys()))
        _log_admin_action(f"plan.update {plan_key} fields={keys}", plan_key)
        return jsonify({"ok": True})
    except Exception as e:
        return jsonify({"ok": False, "erro": str(e)}), 500


@admin_bp.route("/api/plans/<plan_key>", methods=["DELETE"])
@login_required
def api_plans_delete(plan_key):
    if not _require_admin():
        return jsonify({"erro": "Não autorizado"}), 403
    try:
        # Verifica se há clientes usando este plano (campo plano ou billing_plan_key)
        if supabase is not None:
            try:
                # qualquer cliente com plano igual ao plan_key
                r1 = supabase.table(Tables.CLIENTES).select(ClienteModel.ID).eq(ClienteModel.PLANO, plan_key).limit(1).execute()
            except Exception:
                r1 = type("R", (), {"data": []})()  # fallback simples
            try:
                r2 = supabase.table(Tables.CLIENTES).select(ClienteModel.ID).eq(ClienteModel.BILLING_PLAN_KEY, plan_key).limit(1).execute()
            except Exception:
                r2 = type("R", (), {"data": []})()
            has_plano = bool(getattr(r1, "data", None))
            has_billing_plan = bool(getattr(r2, "data", None))
            if has_plano or has_billing_plan:
                return jsonify(
                    {
                        "ok": False,
                        "erro": "Não é possível excluir este plano porque há clientes usando este plan_key. Primeiro migre os clientes para outro plano.",
                    }
                ), 400

        supabase.table(Tables.PLANS).delete().eq(PlanModel.PLAN_KEY, plan_key).execute()
        _log_admin_action(f"plan.delete {plan_key}", plan_key)
        return jsonify({"ok": True})
    except Exception as e:
        return jsonify({"ok": False, "erro": str(e)}), 500


# --- Cliente billing/plan management ---

@admin_bp.route("/api/clientes/<cliente_id>/set-plano", methods=["POST"])
@login_required
def api_set_plano_cliente(cliente_id):
    if not _require_admin():
        return jsonify({"erro": "Não autorizado"}), 403
    data = strip_untrusted_tenant_ids(request.json or {})
    plan_key = (data.get("plan_key") or "").strip()
    if not plan_key:
        return jsonify({"ok": False, "erro": "plan_key é obrigatório."}), 400
    try:
        # carrega entitlements do plano para cache nos acessos
        plan = supabase.table(Tables.PLANS).select("*").eq(PlanModel.PLAN_KEY, plan_key).single().execute()
        p = plan.data or {}
        if bool(p.get(getattr(PlanModel, "IS_PRIVATE", "is_private"))):
            allowed_cliente_id = str(p.get(getattr(PlanModel, "PRIVATE_CLIENTE_ID", "private_cliente_id")) or "").strip()
            if allowed_cliente_id != str(cliente_id).strip():
                return jsonify({"ok": False, "erro": "Este plano privado pertence a outro cliente."}), 403
        ent = p.get("entitlements_json") or {}
        if not isinstance(ent, dict):
            ent = {}
        payload = {
            ClienteModel.PLANO: plan_key,
            ClienteModel.BILLING_PLAN_KEY: plan_key,
            ClienteModel.ACESSO_WHATSAPP: bool(ent.get("whatsapp", True)),
            ClienteModel.ACESSO_INSTAGRAM: bool(ent.get("instagram", True)),
            ClienteModel.ACESSO_MESSENGER: bool(ent.get("messenger", True)),
            ClienteModel.ACESSO_SITE: bool(ent.get("site", True)),
        }
        supabase.table(Tables.CLIENTES).update(payload).eq(ClienteModel.ID, cliente_id).execute()
        return jsonify({"ok": True})
    except Exception as e:
        return jsonify({"ok": False, "erro": str(e)}), 500


@admin_bp.route("/api/clientes/<cliente_id>/set-billing", methods=["POST"])
@login_required
def api_set_billing_cliente(cliente_id):
    if not _require_admin():
        return jsonify({"erro": "Não autorizado"}), 403
    data = strip_untrusted_tenant_ids(request.json or {})
    billing_status = (data.get("billing_status") or "").strip().lower()
    mp_preapproval_id = (data.get("mp_preapproval_id") or "").strip() or None
    trial_ends_at = (data.get("trial_ends_at") or "").strip() or None
    notify_whatsapp = (data.get("notify_whatsapp") or "").strip() or None
    allowed = {"active", "authorized", "trialing", "pending", "past_due", "canceled", "inactive"}
    if billing_status and billing_status not in allowed:
        return jsonify({"ok": False, "erro": "billing_status inválido."}), 400
    payload = {}
    if billing_status:
        payload[ClienteModel.BILLING_STATUS] = billing_status
    if mp_preapproval_id is not None:
        payload[ClienteModel.MP_PREAPPROVAL_ID] = mp_preapproval_id
    if trial_ends_at is not None:
        payload[ClienteModel.TRIAL_ENDS_AT] = trial_ends_at
    if notify_whatsapp is not None:
        payload[ClienteModel.NOTIFY_WHATSAPP] = notify_whatsapp
    try:
        supabase.table(Tables.CLIENTES).update(payload).eq(ClienteModel.ID, cliente_id).execute()
        return jsonify({"ok": True})
    except Exception as e:
        return jsonify({"ok": False, "erro": str(e)}), 500


@admin_bp.route("/api/clientes/<cliente_id>/billing-profile", methods=["GET"])
@login_required
def api_cliente_billing_profile(cliente_id):
    if not _require_admin():
        return jsonify({"erro": "Não autorizado"}), 403
    if supabase is None:
        return jsonify({"ok": False, "erro": "Supabase indisponível."}), 503
    try:
        c = (
            supabase.table(Tables.CLIENTES)
            .select(
                ",".join(
                    [
                        ClienteModel.ID,
                        ClienteModel.EMAIL,
                        ClienteModel.PLANO,
                        ClienteModel.BILLING_PLAN_KEY,
                        ClienteModel.BILLING_STATUS,
                        ClienteModel.TRIAL_ENDS_AT,
                        ClienteModel.MP_PREAPPROVAL_ID,
                        ClienteModel.BILLING_CURRENT_PERIOD_END,
                    ]
                )
            )
            .eq(ClienteModel.ID, cliente_id)
            .single()
            .execute()
        )
        row = c.data or {}
        if not row.get(ClienteModel.ID):
            return jsonify({"ok": False, "erro": "Cliente não encontrado."}), 404
        pid = (row.get(ClienteModel.MP_PREAPPROVAL_ID) or "").strip() or None
        events = _fetch_processed_billing_events(str(cliente_id), pid)
        last_ev = events[0].get(BillingEventModel.PROCESSED_AT) if events else None
        return jsonify(
            {
                "ok": True,
                "cliente": {
                    "billing_status": row.get(ClienteModel.BILLING_STATUS),
                    "trial_ends_at": row.get(ClienteModel.TRIAL_ENDS_AT),
                    "mp_preapproval_id": pid,
                    "billing_current_period_end": row.get(ClienteModel.BILLING_CURRENT_PERIOD_END),
                    "billing_plan_key": row.get(ClienteModel.BILLING_PLAN_KEY) or row.get(ClienteModel.PLANO),
                    "email": row.get(ClienteModel.EMAIL),
                },
                "mp_receipt_url": _mp_subscriptions_admin_url(pid or ""),
                "last_payment_event_at": last_ev,
                "payment_history": events,
            }
        )
    except Exception as e:
        return jsonify({"ok": False, "erro": str(e)}), 500


@admin_bp.route("/api/clientes/<cliente_id>/extrato", methods=["GET"])
@login_required
def api_cliente_extrato(cliente_id):
    if not _require_admin():
        return jsonify({"erro": "Não autorizado"}), 403
    if supabase is None:
        return jsonify({"ok": False, "erro": "Supabase indisponível."}), 503
    fmt = (request.args.get("format") or "text").strip().lower()
    try:
        c = (
            supabase.table(Tables.CLIENTES)
            .select(
                ",".join(
                    [
                        ClienteModel.EMAIL,
                        ClienteModel.PLANO,
                        ClienteModel.BILLING_PLAN_KEY,
                        ClienteModel.MP_PREAPPROVAL_ID,
                    ]
                )
            )
            .eq(ClienteModel.ID, cliente_id)
            .single()
            .execute()
        )
        row = c.data or {}
    except Exception as e:
        return jsonify({"ok": False, "erro": str(e)}), 500

    pid = (row.get(ClienteModel.MP_PREAPPROVAL_ID) or "").strip() or None
    events = list(reversed(_fetch_processed_billing_events(str(cliente_id), pid)))
    pk = (row.get(ClienteModel.BILLING_PLAN_KEY) or row.get(ClienteModel.PLANO) or "").strip()
    email = (row.get(ClienteModel.EMAIL) or "").strip()

    if fmt == "json":
        return jsonify(
            {
                "ok": True,
                "cliente_id": cliente_id,
                "email": email,
                "plan_key": pk,
                "eventos_processados": len(events),
                "linhas": events,
            }
        )

    lines = [
        "Extrato de pagamentos / assinatura (eventos processados no sistema)",
        f"Cliente: {email or cliente_id}",
        f"ID: {cliente_id}",
        f"Plano (ref.): {pk or '—'}",
        f"Preapproval MP: {pid or '—'}",
        "",
    ]
    for e in events:
        lines.append(
            f"{e.get(BillingEventModel.PROCESSED_AT) or '—'}\t"
            f"{e.get(BillingEventModel.RESOURCE_TYPE) or '—'}\t"
            f"data_id={e.get(BillingEventModel.DATA_ID) or '—'}"
        )
    lines.append("")
    lines.append(f"Total de registros: {len(events)}")
    body = "\n".join(lines) + "\n"
    return Response(
        body,
        mimetype="text/plain; charset=utf-8",
        headers={
            "Content-Disposition": f'attachment; filename="extrato-{str(cliente_id)[:8]}.txt"'
        },
    )


@admin_bp.route("/api/clientes/<cliente_id>/reset-trial", methods=["POST"])
@login_required
def api_cliente_reset_trial(cliente_id):
    if not _require_admin():
        return jsonify({"erro": "Não autorizado"}), 403
    if supabase is None:
        return jsonify({"ok": False, "erro": "Supabase indisponível."}), 503
    from services.plans import plan_trial_ends_at

    try:
        r = (
            supabase.table(Tables.CLIENTES)
            .select(f"{ClienteModel.BILLING_PLAN_KEY},{ClienteModel.PLANO}")
            .eq(ClienteModel.ID, cliente_id)
            .single()
            .execute()
        )
        row = r.data or {}
    except Exception as e:
        return jsonify({"ok": False, "erro": str(e)}), 404

    pk = (row.get(ClienteModel.BILLING_PLAN_KEY) or row.get(ClienteModel.PLANO) or "").strip()
    trial = plan_trial_ends_at(pk) if pk else None
    if not trial:
        trial = (datetime.now(timezone.utc) + timedelta(days=14)).isoformat()
    try:
        supabase.table(Tables.CLIENTES).update(
            {ClienteModel.TRIAL_ENDS_AT: trial, ClienteModel.BILLING_STATUS: "trialing"}
        ).eq(ClienteModel.ID, cliente_id).execute()
    except Exception as e:
        return jsonify({"ok": False, "erro": str(e)}), 500
    _log_admin_action("cliente.reset_trial", cliente_id)
    return jsonify({"ok": True, "trial_ends_at": trial})


@admin_bp.route("/api/clientes/<cliente_id>/pausar-assinatura", methods=["POST"])
@login_required
def api_cliente_pausar_assinatura(cliente_id):
    if not _require_admin():
        return jsonify({"erro": "Não autorizado"}), 403
    if supabase is None:
        return jsonify({"ok": False, "erro": "Supabase indisponível."}), 503
    from services.billing.mercadopago import cancel_preapproval

    try:
        r = (
            supabase.table(Tables.CLIENTES)
            .select(ClienteModel.MP_PREAPPROVAL_ID)
            .eq(ClienteModel.ID, cliente_id)
            .single()
            .execute()
        )
        row = r.data or {}
    except Exception as e:
        return jsonify({"ok": False, "erro": str(e)}), 404

    pid = (row.get(ClienteModel.MP_PREAPPROVAL_ID) or "").strip()
    mp_out = None
    if pid:
        ok_mp, mp_out = cancel_preapproval(pid)
        if not ok_mp:
            return (
                jsonify(
                    {
                        "ok": False,
                        "erro": "Falha ao cancelar assinatura no Mercado Pago.",
                        "detalhe": mp_out,
                    }
                ),
                502,
            )
    try:
        supabase.table(Tables.CLIENTES).update({ClienteModel.BILLING_STATUS: "canceled"}).eq(
            ClienteModel.ID, cliente_id
        ).execute()
    except Exception as e:
        return jsonify({"ok": False, "erro": str(e)}), 500
    _log_admin_action("cliente.pausar_assinatura", cliente_id)
    return jsonify({"ok": True, "mp": mp_out})


@admin_bp.route("/api/billing-events/<cliente_id>", methods=["GET"])
@login_required
def api_billing_events(cliente_id):
    if not _require_admin():
        return jsonify({"erro": "Não autorizado"}), 403
    try:
        c = (
            supabase.table(Tables.CLIENTES)
            .select(ClienteModel.MP_PREAPPROVAL_ID)
            .eq(ClienteModel.ID, cliente_id)
            .single()
            .execute()
        )
        pid = (c.data or {}).get(ClienteModel.MP_PREAPPROVAL_ID)
        pid = (pid or "").strip() or None
        q = supabase.table(Tables.BILLING_EVENTS).select("*")
        if pid:
            q = q.or_(
                f"{BillingEventModel.CLIENTE_ID}.eq.{cliente_id},{BillingEventModel.DATA_ID}.eq.{pid}"
            )
        else:
            q = q.eq(BillingEventModel.CLIENTE_ID, cliente_id)
        r = q.order(BillingEventModel.RECEIVED_AT, desc=True).limit(50).execute()
        return jsonify({"ok": True, "events": r.data or []})
    except Exception as e:
        return jsonify({"ok": False, "erro": str(e)}), 500


@admin_bp.route("/api/financeiro/overview")
@login_required
def api_financeiro_overview():
    if not _require_admin():
        return jsonify({"erro": "Não autorizado"}), 403
    try:
        days = int(request.args.get("days") or "30")
    except ValueError:
        days = 30
    days = max(1, min(days, 365))
    try:
        # Puxa snapshots do Supabase (últimos N dias)
        r = (
            supabase.table("billing_snapshots_daily")
            .select("*")
            .order("day", desc=True)
            .limit(days)
            .execute()
        )
        rows = r.data or []
        # overview = último dia
        latest = rows[0] if rows else {}
        return jsonify({"ok": True, "latest": latest, "series": list(reversed(rows))})
    except Exception as e:
        return jsonify({"ok": False, "erro": str(e)}), 500


@admin_bp.route("/api/cobranca/clientes")
@login_required
def api_cobranca_clientes():
    if not _require_admin():
        return jsonify({"erro": "Não autorizado"}), 403
    status = (request.args.get("status") or "").strip().lower()
    try:
        q = supabase.table(Tables.CLIENTES).select(
            ",".join(
                [
                    ClienteModel.ID,
                    ClienteModel.EMAIL,
                    ClienteModel.PLANO,
                    ClienteModel.BILLING_PLAN_KEY,
                    ClienteModel.BILLING_STATUS,
                    ClienteModel.TRIAL_ENDS_AT,
                    ClienteModel.MP_PREAPPROVAL_ID,
                    ClienteModel.BILLING_CURRENT_PERIOD_END,
                ]
            )
        )
        if status:
            q = q.eq(ClienteModel.BILLING_STATUS, status)
        res = q.order(ClienteModel.CRIADO_EM, desc=True).limit(500).execute()
        return jsonify({"ok": True, "clientes": res.data or []})
    except Exception as e:
        return jsonify({"ok": False, "erro": str(e)}), 500


@admin_bp.route("/api/cobranca/reconciliar/<cliente_id>", methods=["POST"])
@login_required
def api_cobranca_reconciliar(cliente_id):
    if not _require_admin():
        return jsonify({"erro": "Não autorizado"}), 403
    try:
        from services.queue import enqueue
        job_id = enqueue("services.jobs.reconcile_mercadopago.reconcile_cliente", str(cliente_id))
        if job_id:
            return jsonify({"ok": True, "job_id": job_id})
        from services.jobs.reconcile_mercadopago import reconcile_cliente
        out = reconcile_cliente(str(cliente_id))
        return jsonify(out)
    except Exception as e:
        return jsonify({"ok": False, "erro": str(e)}), 500


@admin_bp.route("/api/financeiro/mercadopago/reprocess-payment", methods=["POST"])
@login_required
def api_financeiro_reprocess_payment():
    if not _require_admin():
        return jsonify({"erro": "Não autorizado"}), 403
    if supabase is None:
        return jsonify({"ok": False, "erro": "Supabase indisponível."}), 503
    data = strip_untrusted_tenant_ids(request.json or request.form or {})
    payment_id = "".join(ch for ch in str(data.get("payment_id") or "").strip() if ch.isdigit())
    if not payment_id:
        return jsonify({"ok": False, "erro": "Informe um ID de pagamento válido."}), 400

    request_id = "manual-reconcile"
    raw_body = json.dumps(
        {
            "manual": True,
            "source": "admin.financeiro",
            "type": "payment",
            "data": {"id": payment_id},
            "requested_by": getattr(current_user, "email", None),
        },
        ensure_ascii=False,
    )
    event_id = f"payment:{payment_id}:{request_id}"
    try:
        from panel.routes.billing import _mark_event_received, process_mercadopago_event

        _mark_event_received(event_id, request_id, "payment", payment_id, raw_body)
        process_mercadopago_event("payment", payment_id, request_id, raw_body)

        ev = (
            supabase.table(Tables.BILLING_EVENTS)
            .select("*")
            .eq(BillingEventModel.EVENT_ID, event_id)
            .limit(1)
            .execute()
        )
        row = (ev.data or [None])[0]
        _log_admin_action("financeiro.reprocess_payment", payment_id)
        return jsonify(
            {
                "ok": True,
                "payment_id": payment_id,
                "event_id": event_id,
                "event": row,
                "message": "Reprocessamento executado. Confira o status do evento retornado.",
            }
        )
    except Exception as e:
        current_app.logger.exception("api_financeiro_reprocess_payment")
        return jsonify({"ok": False, "erro": str(e)}), 500


@admin_bp.route("/api/canais-globais", methods=["GET"])
@login_required
def api_canais_globais_get():
    if not _require_admin():
        return jsonify({"ok": False, "erro": "Não autorizado"}), 403
    try:
        from services.app_settings import get_global_channel_flags
        flags = get_global_channel_flags()
        return jsonify({"ok": True, **flags})
    except Exception as e:
        return jsonify({"ok": False, "erro": str(e)}), 500


@admin_bp.route("/api/canais-globais", methods=["PATCH"])
@login_required
def api_canais_globais_patch():
    if not _require_admin():
        return jsonify({"ok": False, "erro": "Não autorizado"}), 403
    if supabase is None:
        return jsonify({"ok": False, "erro": "Supabase indisponível."}), 503
    data = strip_untrusted_tenant_ids(request.json or {})
    if (
        "instagram_enabled" not in data
        and "messenger_enabled" not in data
        and "whatsapp_enabled" not in data
    ):
        return jsonify(
            {"ok": False, "erro": "Envie instagram_enabled, messenger_enabled e/ou whatsapp_enabled."}
        ), 400

    ig = True
    ms = True
    wa = True
    try:
        r = (
            supabase.table(Tables.APP_SETTINGS)
            .select(
                ",".join(
                    [
                        AppSettingsModel.INSTAGRAM_ENABLED,
                        AppSettingsModel.MESSENGER_ENABLED,
                        AppSettingsModel.WHATSAPP_ENABLED,
                    ]
                )
            )
            .eq(AppSettingsModel.ID, 1)
            .limit(1)
            .execute()
        )
        row = (r.data or [{}])[0] if r.data else {}
        ig = bool(row.get(AppSettingsModel.INSTAGRAM_ENABLED, True))
        ms = bool(row.get(AppSettingsModel.MESSENGER_ENABLED, True))
        wa = bool(row.get(AppSettingsModel.WHATSAPP_ENABLED, True))
    except Exception:
        pass

    if "instagram_enabled" in data:
        ig = bool(data.get("instagram_enabled"))
    if "messenger_enabled" in data:
        ms = bool(data.get("messenger_enabled"))
    if "whatsapp_enabled" in data:
        wa = bool(data.get("whatsapp_enabled"))

    now = datetime.now(timezone.utc).isoformat()
    payload = {
        AppSettingsModel.ID: 1,
        AppSettingsModel.INSTAGRAM_ENABLED: ig,
        AppSettingsModel.MESSENGER_ENABLED: ms,
        AppSettingsModel.WHATSAPP_ENABLED: wa,
        AppSettingsModel.UPDATED_AT: now,
    }
    try:
        supabase.table(Tables.APP_SETTINGS).upsert(payload, on_conflict=str(AppSettingsModel.ID)).execute()
        from services.app_settings import invalidate_global_channel_flags_cache, get_global_channel_flags
        invalidate_global_channel_flags_cache()
        flags = get_global_channel_flags()
        _log_admin_action(
            f"canais_globais whatsapp_enabled={wa} instagram_enabled={ig} messenger_enabled={ms}",
            "app_settings:1",
        )
        return jsonify({"ok": True, **flags})
    except Exception as e:
        return jsonify({"ok": False, "erro": str(e)}), 500
