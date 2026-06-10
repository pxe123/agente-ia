from datetime import datetime, timezone
import os
import uuid

from flask import Blueprint, render_template, request, redirect, url_for, flash
from database.supabase_sq import supabase, supabase_public
from database.models import Tables, ClienteModel
from database.embed_key import gerar_embed_key
from base.config import settings
from base.signup_security import signup_rate_limit_exceeded
from services.plans import list_active_plans, get_plan, get_plan_for_cliente, plan_trial_ends_at, cliente_acesso_flags_for_plan
from services.signup_protection import (
    check_turnstile_for_signup,
    get_client_ip,
    honeypot_triggered,
    is_disposable_email,
    log_signup_event,
    normalize_signup_email,
)


public_bp = Blueprint("public", __name__)


def _public_signup_disabled() -> bool:
    return bool(getattr(settings, "PUBLIC_SIGNUP_DISABLED", False))


def _render_cadastro(
    *,
    mensagem: str | None = None,
    erro: bool = False,
    plan_key: str = "social",
    plan=None,
    **ctx,
):
    use_onboarding_funnel = bool(getattr(settings, "USE_ONBOARDING_FUNNEL", False))
    if plan is None:
        plan = get_plan_for_cliente(plan_key) or get_plan("social")
    return render_template(
        "cadastro_publico.html",
        mensagem=mensagem,
        erro=erro,
        use_onboarding_funnel=use_onboarding_funnel,
        plan=plan,
        plan_key=plan_key,
        turnstile_site_key=(getattr(settings, "TURNSTILE_SITE_KEY", None) or "").strip(),
        signup_disabled=_public_signup_disabled(),
        **ctx,
    )


def _cadastro_fake_success_redirect(email: str, plan_key: str):
    from base.domain_redirects import public_base_url

    success_url = f"{public_base_url()}{url_for('public.cadastro_sucesso', email=email, plano=plan_key)}"
    return redirect(success_url)


@public_bp.route("/precos", methods=["GET"])
def precos():
    plans = list_active_plans()
    use_onboarding_funnel = bool(getattr(settings, "USE_ONBOARDING_FUNNEL", False))
    return render_template("precos.html", plans=plans, use_onboarding_funnel=use_onboarding_funnel)


@public_bp.route("/cadastro", methods=["GET"])
def cadastro_get():
    plan_key = (request.args.get("plano") or "").strip() or "social"
    if _public_signup_disabled():
        return _render_cadastro(
            mensagem="Cadastro temporariamente indisponível. Tente novamente mais tarde.",
            erro=True,
            plan_key=plan_key,
        )
    plan = get_plan_for_cliente(plan_key) or get_plan("social")
    return _render_cadastro(plan=plan, plan_key=plan_key)


@public_bp.route("/cadastro", methods=["POST"])
def cadastro_post():
    use_onboarding_funnel = bool(getattr(settings, "USE_ONBOARDING_FUNNEL", False))
    plan_key_raw = (request.form.get("plano") or "").strip()
    plan_key_early = plan_key_raw if plan_key_raw else ("" if use_onboarding_funnel else "social")

    if _public_signup_disabled():
        return _render_cadastro(
            mensagem="Cadastro temporariamente indisponível. Tente novamente mais tarde.",
            erro=True,
            plan_key=plan_key_early or "social",
        )

    client_ip = get_client_ip(request)

    if honeypot_triggered(request.form):
        log_signup_event("signup_blocked", ip=client_ip, reason="honeypot")
        email_hp = normalize_signup_email(request.form.get("email") or "") or "conta@exemplo.com"
        return _cadastro_fake_success_redirect(email_hp, plan_key_early or "social")

    if signup_rate_limit_exceeded(client_ip):
        log_signup_event("signup_blocked", ip=client_ip, reason="rate_limit")
        return _render_cadastro(
            mensagem="Muitas tentativas. Tente mais tarde.",
            erro=True,
            plan_key=plan_key_early or "social",
        )

    turnstile_token = (request.form.get("cf-turnstile-response") or "").strip()
    turnstile_ok, turnstile_reason = check_turnstile_for_signup(turnstile_token, client_ip)
    if not turnstile_ok:
        log_signup_event("signup_blocked", ip=client_ip, reason=turnstile_reason or "turnstile")
        return _render_cadastro(
            mensagem="Não foi possível validar o formulário. Recarregue a página e tente novamente.",
            erro=True,
            plan_key=plan_key_early or "social",
            email=normalize_signup_email(request.form.get("email") or ""),
            nome=(request.form.get("nome") or "").strip(),
        )

    if supabase is None:
        return _render_cadastro(
            mensagem="Supabase não configurado no servidor.",
            erro=True,
            plan_key="social",
        )
    if supabase_public is None:
        return _render_cadastro(
            mensagem="Autenticação pública do Supabase não configurada (ANON_KEY ausente).",
            erro=True,
            plan_key="social",
        )

    nome = (request.form.get("nome") or "").strip()
    email = normalize_signup_email(request.form.get("email") or "")
    senha = request.form.get("senha") or ""
    senha2 = request.form.get("senha2") or ""
    plan_key = plan_key_early

    if use_onboarding_funnel and not plan_key:
        return _render_cadastro(
            mensagem="Selecione um plano antes de criar a conta.",
            erro=True,
            plan_key="social",
        )

    plan = get_plan_for_cliente(plan_key)
    if not plan:
        return _render_cadastro(
            mensagem="Plano inválido.",
            erro=True,
            plan_key=plan_key or "social",
        )

    if not email:
        return _render_cadastro(
            mensagem="E-mail é obrigatório.",
            erro=True,
            plan=plan,
            plan_key=plan_key,
        )
    if is_disposable_email(email):
        log_signup_event("signup_blocked", ip=client_ip, reason="disposable", email=email)
        return _render_cadastro(
            mensagem="Não é possível usar este endereço de e-mail.",
            erro=True,
            plan=plan,
            plan_key=plan_key,
            email=email,
            nome=nome,
        )
    if len(senha) < 6:
        return _render_cadastro(
            mensagem="Senha deve ter no mínimo 6 caracteres.",
            erro=True,
            plan=plan,
            plan_key=plan_key,
            email=email,
            nome=nome,
        )
    if senha != senha2:
        return _render_cadastro(
            mensagem="As senhas não coincidem.",
            erro=True,
            plan=plan,
            plan_key=plan_key,
            email=email,
            nome=nome,
        )

    log_signup_event("signup_attempt", ip=client_ip, email=email)

    # já existe cliente?
    try:
        r = supabase.table(Tables.CLIENTES).select("id").eq(ClienteModel.EMAIL, email).execute()
        if r.data:
            return _render_cadastro(
                mensagem="Já existe uma conta com este e-mail.",
                erro=True,
                plan=plan,
                plan_key=plan_key,
                email=email,
                nome=nome,
            )
    except Exception:
        pass

    # cria no Supabase Auth (para login via JWT e consistência)
    auth_user_id = None
    try:
        from base.domain_redirects import public_base_url

        email_redirect_to = f"{public_base_url()}/login?confirmed=1"
        resp = supabase_public.auth.sign_up(
            {
                "email": email,
                "password": senha,
                "options": {
                    "data": {"full_name": nome or email},
                    "email_redirect_to": email_redirect_to,
                },
            }
        )

        # compat extração do user.id (supabase-py varia estrutura)
        u = getattr(resp, "user", None)
        if u is None and isinstance(resp, dict):
            u = resp.get("user") or resp.get("data", {}).get("user")
        if u is not None:
            uid = getattr(u, "id", None) if not isinstance(u, dict) else u.get("id")
            if uid:
                auth_user_id = str(uid)
    except Exception as e:
        return _render_cadastro(
            mensagem="Erro ao criar login: " + str(e),
            erro=True,
            plan=plan,
            plan_key=plan_key,
            email=email,
            nome=nome,
        )

    trial_ends_at = None
    signup_flow_version = 1
    billing_status = "inactive"
    onboarding_completed_at = None
    activated_at = None

    if use_onboarding_funnel:
        signup_flow_version = 2
        billing_status = "onboarding"
    else:
        trial_ends_at = plan_trial_ends_at(plan_key)
        billing_status = "trialing" if trial_ends_at else "inactive"

    cliente_pk = str(uuid.uuid4())
    payload = {
        ClienteModel.ID: cliente_pk,
        ClienteModel.AUTH_ID: auth_user_id,
        ClienteModel.EMAIL: email,
        ClienteModel.EMBED_KEY: gerar_embed_key(),
        ClienteModel.PLANO: plan_key,  # mantém compat com UI atual
        ClienteModel.BILLING_PLAN_KEY: plan_key,
        ClienteModel.BILLING_STATUS: billing_status,
        ClienteModel.TRIAL_ENDS_AT: trial_ends_at,
        ClienteModel.SIGNUP_FLOW_VERSION: signup_flow_version,
        ClienteModel.ONBOARDING_COMPLETED_AT: onboarding_completed_at,
        ClienteModel.ACTIVATED_AT: activated_at,
    }
    if nome:
        payload[ClienteModel.NOME] = nome
    payload.update(cliente_acesso_flags_for_plan(plan_key))

    try:
        try:
            supabase.table(Tables.CLIENTES).insert(payload).execute()
        except Exception:
            # Compatibilidade: caso as colunas novas ainda não existam no DB.
            minimal_payload = dict(payload)
            for k in (
                getattr(ClienteModel, "SIGNUP_FLOW_VERSION", "signup_flow_version"),
                getattr(ClienteModel, "ONBOARDING_COMPLETED_AT", "onboarding_completed_at"),
                getattr(ClienteModel, "ACTIVATED_AT", "activated_at"),
            ):
                minimal_payload.pop(k, None)
            minimal_payload.pop(ClienteModel.TRIAL_ENDS_AT, None)  # trial_ends_at fica null no onboarding
            supabase.table(Tables.CLIENTES).insert(minimal_payload).execute()
    except Exception as e:
        return _render_cadastro(
            mensagem="Erro ao criar conta: " + str(e),
            erro=True,
            plan=plan,
            plan_key=plan_key,
            email=email,
            nome=nome,
        )

    # Fonte de verdade (Fase 3): subscriptions por tenant (best-effort)
    try:
        from services.billing.subscription_service import upsert_tenant_subscription

        upsert_tenant_subscription(
            cliente_id=str(cliente_pk),
            provider="internal",
            provider_subscription_id=None,
            plan_key=plan_key,
            status=("trialing" if trial_ends_at else ("onboarding" if use_onboarding_funnel else "inactive")),
            current_period_end=None,
            trial_ends_at=trial_ends_at,
        )
    except Exception:
        pass

    # Garantir que a página de sucesso abra no domínio público (zapaction),
    # mesmo quando o POST do cadastro acontece em outro host.
    from base.domain_redirects import public_base_url

    success_url = f"{public_base_url()}{url_for('public.cadastro_sucesso', email=email, plano=plan_key)}"
    return redirect(success_url)


@public_bp.route("/cadastro/sucesso", methods=["GET"])
def cadastro_sucesso():
    email = (request.args.get("email") or "").strip().lower()
    plan_key = (request.args.get("plano") or "").strip() or None
    plan = get_plan_for_cliente(plan_key) if plan_key else None
    use_onboarding_funnel = bool(getattr(settings, "USE_ONBOARDING_FUNNEL", False))
    return render_template(
        "cadastro_sucesso.html",
        email=email,
        plan=plan,
        plan_key=plan_key,
        use_onboarding_funnel=use_onboarding_funnel,
    )


@public_bp.route("/assinatura", methods=["GET"])
def assinatura():
    # tela pública simples (o bloqueio/redirecionamento real acontece após login)
    return render_template("assinatura.html")


@public_bp.route("/whatsapp-atendimento", methods=["GET"])
def whatsapp_atendimento():
    """Página satélite SEO: atendimento WhatsApp para empresas."""
    return render_template("whatsapp_atendimento.html")


@public_bp.route("/agenda/<slug>", methods=["GET", "POST"])
def agenda_publica(slug: str):
    """Agendamento público por slug — escolha de serviço, profissional e horário."""
    from services.scheduling import repository as sched_repo
    from services.scheduling.bookings import book_appointment
    from services.scheduling.public_booking import (
        build_public_booking_calendar,
        day_time_slots,
        group_slot_isos_by_local_day,
        local_today,
        month_bounds,
        format_selected_date_long,
        parse_month_anchor,
        parse_selected_date,
    )
    from services.scheduling.slots_public import compute_available_slot_isos, eligible_professionals

    if not supabase:
        return render_template("agenda_publica.html", erro="Indisponível.", slug=slug), 503
    st = sched_repo.get_settings_by_slug(slug)
    if not st:
        return render_template("agenda_publica.html", erro="Página não encontrada.", slug=slug), 404

    from services.agendamento_ia_bridge import scheduling_uses_internal_motor
    from services.agendamento_ia_urls import agendamento_ia_configured

    cid = str(st.get("cliente_id") or "")
    if agendamento_ia_configured() and not scheduling_uses_internal_motor(cid):
        return render_template(
            "agenda_publica.html",
            erro=(
                "O agendamento desta clínica é feito pelo link enviado no WhatsApp "
                "(Agendamento IA). Esta página local está desativada em produção."
            ),
            slug=slug,
            nome_pub=(st.get("public_name") or "").strip() or "Agendar",
        ), 200
    from services.scheduling.timezones import normalize_timezone

    tz_name = normalize_timezone(str(st.get("timezone") or ""))
    nome_pub = (st.get("public_name") or "").strip() or "Agendar"
    profs = sched_repo.list_professionals(cid, active_only=True)
    services = sched_repo.list_services(cid, active_only=True)
    wh_all = sched_repo.list_working_hours_all(cid)

    def _field(name: str) -> str:
        if request.method == "POST":
            return (request.form.get(name) or "").strip()
        return (request.args.get(name) or "").strip()

    from services.scheduling.public_contact import format_br_phone_input

    contact_phone = _field("phone") or _field("contact_phone")
    contact_name = _field("name")
    contact_phone_display = format_br_phone_input(contact_phone)
    selected_service_id = _field("service_id")
    selected_professional_id = _field("professional_id")

    if not selected_service_id and services:
        selected_service_id = str(services[0].get("id") or "")
    eligible_profs = (
        eligible_professionals(services, profs, selected_service_id) if selected_service_id else list(profs)
    )
    if not selected_professional_id and eligible_profs:
        selected_professional_id = str(eligible_profs[0].get("id") or "")

    err = None
    ok = False
    if request.method == "POST" and (request.form.get("slot_iso") or "").strip():
        slot_iso = (request.form.get("slot_iso") or "").strip()
        sid = selected_service_id
        pid = selected_professional_id
        phone = contact_phone
        name = contact_name
        if not (slot_iso and sid and pid):
            err = "Preencha todos os campos."
        else:
            from services.scheduling.public_contact import format_br_phone_input, validate_public_contact

            nome_ok, phone_norm, contact_err = validate_public_contact(name=name, phone=phone)
            svc = sched_repo.get_service(cid, sid)
            dur = int((svc or {}).get("duration_minutes") or 30)
            try:
                starts = datetime.fromisoformat(slot_iso.replace("Z", "+00:00"))
            except Exception:
                starts = None
            if contact_err:
                err = contact_err
            elif not starts:
                err = "Horário inválido."
            else:
                meta: dict[str, str] = {"source": "public_agenda", "contact_name": nome_ok}
                row, berr = book_appointment(
                    cliente_id=cid,
                    service_id=sid,
                    professional_id=pid,
                    starts_at=starts,
                    duration_minutes=dur,
                    remote_id=phone_norm,
                    contact_phone=phone_norm,
                    meta=meta,
                )
                if berr:
                    err = berr
                else:
                    ok = True

    slots_iso: list[str] = []
    booking_calendar: dict | None = None
    selected_date = parse_selected_date(_field("date"))
    day_slots: list[dict[str, str]] = []
    month_anchor = parse_month_anchor(_field("month"), tz_name)

    if selected_service_id and selected_professional_id:
        svc_sel = sched_repo.get_service(cid, selected_service_id)
        dur_sel = int((svc_sel or {}).get("duration_minutes") or 30)
        month_start, month_end = month_bounds(month_anchor)
        today_local = local_today(tz_name)
        range_start = max(month_start, today_local)
        num_days = max(0, (month_end - range_start).days + 1)
        if num_days > 0:
            slots_iso = compute_available_slot_isos(
                cliente_id=cid,
                service_id=selected_service_id,
                professional_id=selected_professional_id,
                tz_name=tz_name,
                working_rows=wh_all,
                duration_minutes=dur_sel,
                start_day=range_start,
                num_days=num_days,
                max_slots=200,
            )
        slots_by_day = group_slot_isos_by_local_day(slots_iso, tz_name)
        booking_calendar = build_public_booking_calendar(
            month_anchor=month_anchor,
            slots_by_day=slots_by_day,
            tz_name=tz_name,
            selected_date=selected_date,
        )
        if selected_date:
            day_slots = day_time_slots(slots_by_day.get(selected_date.isoformat(), []), tz_name)

    return render_template(
        "agenda_publica.html",
        slug=slug,
        nome_pub=nome_pub,
        professionals=profs,
        eligible_professionals=eligible_profs,
        services=services,
        selected_service_id=selected_service_id,
        selected_professional_id=selected_professional_id,
        contact_phone=contact_phone,
        contact_phone_display=contact_phone_display,
        contact_name=contact_name,
        booking_calendar=booking_calendar,
        selected_date=selected_date.isoformat() if selected_date else "",
        selected_date_label=selected_date.strftime("%d/%m/%Y") if selected_date else "",
        selected_date_long=format_selected_date_long(selected_date) if selected_date else "",
        day_slots=day_slots,
        scheduling_timezone=tz_name,
        erro=err,
        ok=ok,
    )

