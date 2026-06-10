"""Painel: módulo de agenda (wizard em abas)."""
from __future__ import annotations

from datetime import datetime, timezone

from flask import Blueprint, abort, flash, jsonify, redirect, render_template, request, url_for, current_app
from flask_login import current_user, login_required

from base.auth import get_current_cliente_id
from database.models import (
    Tables,
    SchedulingAppointmentModel,
    SchedulingBlockedTimeModel,
    SchedulingProfessionalModel,
    SchedulingServiceModel,
    SchedulingSettingsModel,
    SchedulingWorkingHoursModel,
)
from database.supabase_sq import supabase

scheduling_bp = Blueprint(
    "scheduling",
    __name__,
    template_folder="../templates",
)

VALID_TABS = frozenset({"clinica", "profissionais", "servicos", "horarios", "agendamentos"})
TAB_ORDER = ["clinica", "profissionais", "servicos", "horarios", "agendamentos"]


def _after_agenda_mutation(cid: str) -> None:
    """Sincroniza snapshot com Agendamento IA se `AGENDAMENTO_IA_CLINIC_SYNC_URL` estiver definida."""
    from services.agendamento_ia_bridge import scheduling_uses_internal_motor
    from services.agendamento_ia_sync import clinic_sync_configured, maybe_sync_after_panel_change

    if scheduling_uses_internal_motor(cid) or not clinic_sync_configured():
        return
    err = maybe_sync_after_panel_change(cid)
    if err:
        flash(
            "Os dados foram guardados no ZapAction. "
            + (
                f"A sincronização com o Agendamento IA falhou ({err}). "
                "Confirme AGENDAMENTO_IA_CLINIC_SYNC_URL, AGENT_BEARER_TOKEN (= API key) e "
                "AGENDAMENTO_IA_BASE_URL. "
                "Se o erro persistir, faça deploy da imagem agendamento-ia mais recente "
                "(tenant-snapshot com serviços e provider_services)."
            ),
            "warning",
        )
    else:
        flash("Dados sincronizados com o Agendamento IA.", "success")


def _cliente_id() -> str | None:
    if not current_user.is_authenticated:
        return None
    return get_current_cliente_id(current_user)


def _handle_post(cid: str) -> str:
    """Processa POST do wizard; devolve tab para redirect."""
    action = (request.form.get("action") or "").strip()
    ret = (request.form.get("return_tab") or "clinica").strip()
    if ret not in VALID_TABS:
        ret = "clinica"

    if action == "save_clinica":
        from services.scheduling.slug import normalize_public_slug

        name = (request.form.get("public_name") or "").strip()
        slug_raw = (request.form.get("public_slug") or "").strip()
        slug = normalize_public_slug(slug_raw)
        if slug_raw and not slug:
            flash(
                "Slug inválido. Use apenas letras, números e hífens (ex.: minha-clinica).",
                "error",
            )
            return ret
        from services.scheduling.timezones import normalize_timezone

        tz = normalize_timezone(request.form.get("timezone"))
        now_iso = datetime.now(timezone.utc).isoformat()
        payload = {
            SchedulingSettingsModel.PUBLIC_NAME: name or None,
            SchedulingSettingsModel.PUBLIC_SLUG: slug,
            SchedulingSettingsModel.TIMEZONE: tz,
            SchedulingSettingsModel.UPDATED_AT: now_iso,
        }
        try:
            from services.scheduling import repository as sched_repo

            sched_repo.ensure_settings(cid)
            supabase.table(Tables.SCHEDULING_SETTINGS).update(payload).eq(
                SchedulingSettingsModel.CLIENTE_ID, cid
            ).execute()
            msg = "Dados da clínica guardados."
            if slug and slug_raw.strip().lower() != slug:
                msg += f" Slug normalizado para: {slug}"
            elif slug:
                msg += f" Slug: {slug}"
            flash(msg, "success")
        except Exception as e:
            err = str(e).lower()
            current_app.logger.warning("save_clinica cliente_id=%s err=%s", cid, e)
            if "scheduling_settings_public_slug" in err or "unique" in err or "23505" in err:
                flash(
                    "Este slug já está em uso por outra conta. Escolha outro (apenas letras minúsculas, números e hífens).",
                    "error",
                )
            else:
                flash(f"Não foi possível guardar os dados da clínica: {e}", "error")
            return ret
        _after_agenda_mutation(cid)
        return ret

    if action == "add_wh_clinic":
        try:
            dow = int(request.form.get("day_of_week") or 0)
        except ValueError:
            dow = 0
        st = (request.form.get("start_time") or "09:00").strip()
        et = (request.form.get("end_time") or "18:00").strip()
        row = {
            SchedulingWorkingHoursModel.CLIENTE_ID: cid,
            SchedulingWorkingHoursModel.PROFESSIONAL_ID: None,
            SchedulingWorkingHoursModel.DAY_OF_WEEK: max(0, min(6, dow)),
            SchedulingWorkingHoursModel.START_TIME: st,
            SchedulingWorkingHoursModel.END_TIME: et,
        }
        supabase.table(Tables.SCHEDULING_WORKING_HOURS).insert(row).execute()
        flash("Horário da clínica adicionado.", "success")
        _after_agenda_mutation(cid)
        return "clinica"

    if action == "delete_wh":
        hid = (request.form.get("id") or "").strip()
        if hid:
            supabase.table(Tables.SCHEDULING_WORKING_HOURS).delete().eq(
                SchedulingWorkingHoursModel.ID, hid
            ).eq(SchedulingWorkingHoursModel.CLIENTE_ID, cid).execute()
            flash("Horário excluído e sincronizado com o Agenda.", "success")
            _after_agenda_mutation(cid)
        return (request.form.get("return_tab") or "clinica").strip() if (request.form.get("return_tab") or "").strip() in VALID_TABS else "clinica"

    if action == "add_wh_prof":
        pid = (request.form.get("professional_id") or "").strip() or None
        try:
            dow = int(request.form.get("day_of_week") or 0)
        except ValueError:
            dow = 0
        st = (request.form.get("start_time") or "09:00").strip()
        et = (request.form.get("end_time") or "18:00").strip()
        row = {
            SchedulingWorkingHoursModel.CLIENTE_ID: cid,
            SchedulingWorkingHoursModel.PROFESSIONAL_ID: pid,
            SchedulingWorkingHoursModel.DAY_OF_WEEK: max(0, min(6, dow)),
            SchedulingWorkingHoursModel.START_TIME: st,
            SchedulingWorkingHoursModel.END_TIME: et,
        }
        supabase.table(Tables.SCHEDULING_WORKING_HOURS).insert(row).execute()
        flash("Horário do profissional adicionado.", "success")
        _after_agenda_mutation(cid)
        return "horarios"

    if action == "add_professional":
        name = (request.form.get("name") or "").strip()
        if name:
            supabase.table(Tables.SCHEDULING_PROFESSIONALS).insert(
                {
                    SchedulingProfessionalModel.CLIENTE_ID: cid,
                    SchedulingProfessionalModel.NAME: name,
                    SchedulingProfessionalModel.ACTIVE: True,
                    SchedulingProfessionalModel.SORT_ORDER: 0,
                }
            ).execute()
            flash("Profissional adicionado.", "success")
            _after_agenda_mutation(cid)
        return "profissionais"

    if action == "delete_professional":
        pid = (request.form.get("id") or "").strip()
        if pid:
            supabase.table(Tables.SCHEDULING_PROFESSIONALS).delete().eq(
                SchedulingProfessionalModel.ID, pid
            ).eq(SchedulingProfessionalModel.CLIENTE_ID, cid).execute()
            flash("Profissional excluído e sincronizado com o Agenda.", "success")
            _after_agenda_mutation(cid)
        return "profissionais"

    if action == "update_service_professional":
        sid = (request.form.get("service_id") or "").strip()
        pid_raw = (request.form.get("professional_id") or "").strip()
        pid = pid_raw if pid_raw else None
        if sid:
            supabase.table(Tables.SCHEDULING_SERVICES).update(
                {
                    SchedulingServiceModel.PROFESSIONAL_ID: pid,
                    SchedulingServiceModel.UPDATED_AT: datetime.now(timezone.utc).isoformat(),
                }
            ).eq(SchedulingServiceModel.ID, sid).eq(
                SchedulingServiceModel.CLIENTE_ID, cid
            ).execute()
            flash("Vínculo profissional ↔ serviço atualizado.", "success")
            _after_agenda_mutation(cid)
        return "servicos"

    if action == "add_service":
        name = (request.form.get("name") or "").strip()
        dur = int(request.form.get("duration_minutes") or 30)
        pid_raw = (request.form.get("professional_id") or "").strip()
        pid = pid_raw if pid_raw else None
        if name:
            supabase.table(Tables.SCHEDULING_SERVICES).insert(
                {
                    SchedulingServiceModel.CLIENTE_ID: cid,
                    SchedulingServiceModel.NAME: name,
                    SchedulingServiceModel.DURATION_MINUTES: max(5, dur),
                    SchedulingServiceModel.PROFESSIONAL_ID: pid,
                    SchedulingServiceModel.ACTIVE: True,
                    SchedulingServiceModel.SORT_ORDER: 0,
                }
            ).execute()
            flash("Serviço adicionado.", "success")
            _after_agenda_mutation(cid)
        return "servicos"

    if action == "delete_service":
        sid = (request.form.get("id") or "").strip()
        if sid:
            try:
                supabase.table(Tables.SCHEDULING_SERVICES).delete().eq(
                    SchedulingServiceModel.ID, sid
                ).eq(SchedulingServiceModel.CLIENTE_ID, cid).execute()
                flash("Serviço excluído e sincronizado com o Agenda.", "success")
                _after_agenda_mutation(cid)
            except Exception as e:
                err = str(e).lower()
                if "restrict" in err or "23503" in err:
                    flash(
                        "Não foi possível excluir: existem agendamentos com este serviço. "
                        "Cancele ou exclua os agendamentos na aba Agendamentos primeiro.",
                        "error",
                    )
                else:
                    flash(f"Erro ao excluir serviço: {e}", "error")
        return "servicos"

    if action == "clear_clinica":
        from services.scheduling import repository as sched_repo

        sched_repo.clear_clinica_config(cid)
        flash(
            "Dados da clínica (nome, slug e horários gerais) foram limpos. "
            "Profissionais e serviços mantidos.",
            "success",
        )
        _after_agenda_mutation(cid)
        return "clinica"

    if action == "reset_agenda":
        from services.scheduling import repository as sched_repo

        err = sched_repo.reset_agenda_catalog(cid)
        if err:
            flash(
                "Não foi possível repor a agenda por completo. "
                + (
                    "Existem referências pendentes — tente de novo ou contacte suporte."
                    if err == "existem_agendamentos_ou_referencias"
                    else err
                ),
                "error",
            )
        else:
            flash(
                "Agenda reposta: clínica, profissionais, serviços, horários e agendamentos locais "
                "foram removidos. Sincronizado com o Agenda.",
                "success",
            )
            _after_agenda_mutation(cid)
        return "clinica"

    if action == "sync_tenant_snapshot":
        from services.agendamento_ia_sync import clinic_sync_configured, sync_catalog_to_agendamento_ia

        ret_tab = (request.form.get("return_tab") or "clinica").strip()
        if ret_tab not in VALID_TABS:
            ret_tab = "clinica"
        if not clinic_sync_configured():
            flash(
                "Configure AGENDAMENTO_IA_BASE_URL (ou AGENDAMENTO_IA_CLINIC_SYNC_URL) "
                "e AGENDAMENTO_IA_API_KEY para sincronizar com o Agendamento IA.",
                "warning",
            )
            return ret_tab
        err = sync_catalog_to_agendamento_ia(cid, force=True)
        if err:
            flash(f"Não foi possível sincronizar o catálogo: {err}", "error")
        else:
            flash(
                "Catálogo sincronizado: clínica, profissionais, serviços e horários "
                "no Agendamento IA estão alinhados com este painel.",
                "success",
            )
        return ret_tab

    if action == "sync_agenda_appointments":
        from services.agendamento_ia_appointments_import import sync_appointments_from_agenda
        from services.agendamento_ia_urls import agendamento_ia_configured

        if not agendamento_ia_configured():
            flash("Agendamento IA não está configurado no servidor.", "error")
        else:
            imported, sync_err = sync_appointments_from_agenda(cid)
            if sync_err and imported == 0:
                flash(f"Sincronização falhou: {sync_err}", "error")
            elif imported > 0:
                flash(f"{imported} agendamento(s) importado(s) do Agendamento IA.", "success")
            else:
                flash("Nenhum agendamento novo no período (últimos 90 dias).", "info")
        return "agendamentos"

    if action == "delete_appointment":
        aid = (request.form.get("appointment_id") or "").strip()
        if aid:
            from services.scheduling import repository as sched_repo

            if sched_repo.delete_appointment_row(cid, aid):
                flash("Agendamento excluído do painel.", "success")
            else:
                flash("Não foi possível excluir o agendamento.", "error")
        return "agendamentos"

    if action == "generate_agenda_link":
        phone = (request.form.get("link_remote_id") or "").strip()
        if not phone:
            flash("Indique o telefone (WhatsApp) para gerar o link.", "error")
            return "clinica"
        from services.agendamento_ia_link import generate_appointment_link
        from services.agendamento_ia_urls import link_generate_available

        if not link_generate_available():
            flash(
                "Geração de link não configurada. Defina AGENDAMENTO_IA_BASE_URL no servidor.",
                "error",
            )
            return "clinica"
        gen = generate_appointment_link(
            cliente_id=cid,
            remote_id=phone,
            canal="whatsapp",
            node_id="painel",
        )
        if gen.get("ok") and gen.get("url"):
            flash(f"Link gerado (válido por tempo limitado): {gen['url']}", "success")
        else:
            flash(
                f"Não foi possível gerar o link ({gen.get('error') or 'erro'}). "
                "Verifique AGENDAMENTO_IA_API_KEY e o deploy do Agenda.",
                "error",
            )
        return "clinica"

    if action == "add_blocked_time":
        from services.scheduling import repository as sched_repo
        from services.scheduling.datetime_parse import parse_datetime_local
        from services.scheduling.timezones import normalize_timezone

        st = sched_repo.get_settings(cid) or {}
        tz = normalize_timezone(str(st.get("timezone") or ""))
        starts_local = parse_datetime_local(request.form.get("starts_at") or "", tz)
        ends_local = parse_datetime_local(request.form.get("ends_at") or "", tz)
        if not starts_local or not ends_local:
            flash("Indique início e fim do bloqueio.", "error")
            return "horarios"
        if starts_local >= ends_local:
            flash("O fim do bloqueio deve ser depois do início.", "error")
            return "horarios"
        pid_raw = (request.form.get("professional_id") or "").strip()
        pid = pid_raw if pid_raw else None
        reason = (request.form.get("reason") or "").strip() or None
        row = sched_repo.insert_blocked_time(
            cliente_id=cid,
            starts_at=starts_local,
            ends_at=ends_local,
            professional_id=pid,
            reason=reason,
        )
        if row:
            flash("Bloqueio de agenda adicionado.", "success")
        else:
            flash("Não foi possível guardar o bloqueio.", "error")
        return "horarios"

    if action == "delete_blocked_time":
        from services.scheduling import repository as sched_repo

        bid = (request.form.get("id") or "").strip()
        if bid and sched_repo.delete_blocked_time(cid, bid):
            flash("Bloqueio removido.", "success")
        return "horarios"

    if action == "reschedule_appointment":
        aid = (request.form.get("appointment_id") or "").strip()
        slot_iso = (request.form.get("slot_iso") or "").strip()
        if not aid or not slot_iso:
            flash("Escolha um novo horário para remarcar.", "error")
            return "agendamentos"
        from services.agendamento_ia_appointment_webhook import appointment_origin_label
        from services.scheduling import repository as sched_repo
        from services.scheduling.bookings import reschedule_appointment

        existing = sched_repo.get_appointment(cid, aid)
        if not existing:
            flash("Agendamento não encontrado.", "error")
            return "agendamentos"
        if str(existing.get("status") or "") == "cancelled":
            flash("Não é possível remarcar um agendamento cancelado.", "error")
            return "agendamentos"
        if appointment_origin_label(existing) == "agenda":
            flash(
                "Esta marcação veio do Agendamento IA. Remarque pelo WhatsApp ou link enviado ao cliente.",
                "warning",
            )
            return "agendamentos"
        svc = sched_repo.get_service(cid, str(existing.get("service_id") or ""))
        dur = int((svc or {}).get("duration_minutes") or 30)
        try:
            new_start = datetime.fromisoformat(slot_iso.replace("Z", "+00:00"))
        except Exception:
            flash("Horário inválido.", "error")
            return "agendamentos"
        ok, rerr = reschedule_appointment(
            cliente_id=cid,
            appointment_id=aid,
            new_starts_at=new_start,
            duration_minutes=dur,
            professional_id=str(existing.get("professional_id") or "") or None,
        )
        if ok:
            flash("Agendamento remarcado.", "success")
        else:
            flash(f"Não foi possível remarcar ({rerr or 'erro'}).", "error")
        return "agendamentos"

    if action == "cancel_appointment":
        from services.agendamento_ia_appointment_webhook import appointment_origin_label

        aid = (request.form.get("appointment_id") or "").strip()
        if aid:
            row = (
                supabase.table(Tables.SCHEDULING_APPOINTMENTS)
                .select("*")
                .eq(SchedulingAppointmentModel.ID, aid)
                .eq(SchedulingAppointmentModel.CLIENTE_ID, cid)
                .limit(1)
                .execute()
                .data
            )
            existing = row[0] if row else None
            if existing and appointment_origin_label(existing) == "agenda":
                ext_id = (
                    existing.get(SchedulingAppointmentModel.EXTERNAL_AGENDA_APPOINTMENT_ID)
                    or existing.get("external_agenda_appointment_id")
                    or ""
                )
                ext_id = str(ext_id).strip()
                if ext_id:
                    from services.agendamento_ia_cancel import cancel_appointment_in_agendamento_ia

                    ok_cancel, cerr = cancel_appointment_in_agendamento_ia(
                        cliente_id=cid,
                        external_appointment_id=ext_id,
                        remote_id=str(existing.get(SchedulingAppointmentModel.REMOTE_ID) or ""),
                    )
                    if ok_cancel:
                        flash("Agendamento cancelado no Agendamento IA.", "success")
                    else:
                        flash(
                            "Não foi possível cancelar no Agendamento IA "
                            f"({cerr or 'erro'}). Tente pelo WhatsApp ou link enviado ao cliente.",
                            "warning",
                        )
                    return "agendamentos"
                flash(
                    "Este agendamento foi criado no Agendamento IA (sem ID externo). "
                    "Cancele pelo WhatsApp ou pelo link de agendamento enviado ao cliente.",
                    "warning",
                )
                return "agendamentos"
            supabase.table(Tables.SCHEDULING_APPOINTMENTS).update(
                {
                    SchedulingAppointmentModel.STATUS: "cancelled",
                    SchedulingAppointmentModel.UPDATED_AT: datetime.now(timezone.utc).isoformat(),
                }
            ).eq(SchedulingAppointmentModel.ID, aid).eq(
                SchedulingAppointmentModel.CLIENTE_ID, cid
            ).execute()
            flash("Agendamento cancelado.", "success")
        return "agendamentos"

    flash("Ação não reconhecida.", "error")
    return ret


@scheduling_bp.route("/", methods=["GET", "POST"])
@login_required
def home():
    cid = _cliente_id()
    if not cid or not supabase:
        flash("Sessão inválida ou base indisponível.", "error")
        return redirect(url_for("customer.dashboard"))
    from services.agendamento_ia_sync import clinic_sync_configured
    from services.agendamento_ia_urls import (
        agendamento_ia_base_url,
        agendamento_ia_configured,
        check_agendamento_ia_health,
        is_production_environment,
        link_generate_available,
        resolved_clinic_sync_url,
        agendamento_webhook_url_misconfigured,
    )
    from services.scheduling import repository as sched_repo

    sched_repo.ensure_settings(cid)

    from services.agendamento_ia_bridge import scheduling_uses_internal_motor

    uses_internal_scheduling = scheduling_uses_internal_motor(cid)

    tab_pre = (request.args.get("tab") or "clinica").strip()
    if tab_pre not in VALID_TABS:
        tab_pre = "clinica"

    if request.method == "GET" and tab_pre == "agendamentos":
        from services.agendamento_ia_urls import agendamento_ia_configured
        from services.agendamento_ia_appointments_import import sync_appointments_from_agenda

        if agendamento_ia_configured() and not uses_internal_scheduling:
            try:
                imported, sync_err = sync_appointments_from_agenda(cid)
            except Exception as e:
                imported, sync_err = 0, str(e)[:120]
            if sync_err and imported == 0:
                flash(
                    "Não foi possível carregar agendamentos do Agendamento IA. "
                    f"({sync_err}) Verifique AGENDAMENTO_IA_BASE_URL e AGENDAMENTO_IA_API_KEY.",
                    "warning",
                )
            elif imported > 0:
                flash(f"{imported} agendamento(s) sincronizado(s) do Agendamento IA.", "success")

    if request.method == "POST":
        tab = _handle_post(cid)
        params: dict[str, str] = {"tab": tab}
        for key in ("period", "date", "professional_id", "status", "q"):
            val = (request.args.get(key) or request.form.get(key) or "").strip()
            if val:
                params[key] = val
        if tab == "agendamentos" and "period" not in params and "date" not in params:
            params["period"] = "today"
        return redirect(url_for("scheduling.home", **params))

    if request.method == "GET" and clinic_sync_configured() and not uses_internal_scheduling:
        from services.agendamento_ia_sync import sync_catalog_to_agendamento_ia

        force_sync = (request.args.get("sync") or "").strip() in ("1", "true", "yes")
        sync_err = sync_catalog_to_agendamento_ia(cid, force=force_sync)
        if force_sync:
            if sync_err:
                flash(f"Sincronização com o Agendamento IA falhou: {sync_err}", "error")
            else:
                flash(
                    "Catálogo sincronizado com o Agendamento IA (o que está aqui é o que o motor usa).",
                    "success",
                )

    tab = (request.args.get("tab") or "clinica").strip()
    if tab not in VALID_TABS:
        tab = "clinica"
    tab_index = TAB_ORDER.index(tab) if tab in TAB_ORDER else 0

    google_result = (request.args.get("google") or "").strip().lower()
    if google_result == "ok":
        flash("Google Calendar conectado com sucesso.", "success")
    elif google_result == "error":
        reason = (request.args.get("google_reason") or "").strip()
        if reason:
            flash(f"Não foi possível conectar o Google Calendar: {reason[:300]}", "error")
        else:
            flash("Não foi possível conectar o Google Calendar. Tente novamente.", "error")

    settings = sched_repo.get_settings(cid) or {}
    upcoming = sched_repo.list_upcoming_appointments(cid, limit=15)
    professionals = (
        supabase.table(Tables.SCHEDULING_PROFESSIONALS)
        .select("*")
        .eq(SchedulingProfessionalModel.CLIENTE_ID, cid)
        .order(SchedulingProfessionalModel.SORT_ORDER)
        .execute()
        .data
        or []
    )
    services = (
        supabase.table(Tables.SCHEDULING_SERVICES)
        .select("*")
        .eq(SchedulingServiceModel.CLIENTE_ID, cid)
        .order(SchedulingServiceModel.SORT_ORDER)
        .execute()
        .data
        or []
    )
    working_hours = (
        supabase.table(Tables.SCHEDULING_WORKING_HOURS)
        .select("*")
        .eq(SchedulingWorkingHoursModel.CLIENTE_ID, cid)
        .execute()
        .data
        or []
    )
    clinic_hours = [h for h in working_hours if h.get("professional_id") in (None, "")]
    prof_hours = [h for h in working_hours if h.get("professional_id") not in (None, "")]
    from datetime import timedelta

    from services.scheduling.appointments_filter import parse_filter_date, resolve_appointments_period
    from services.scheduling.timezones import DEFAULT_TIMEZONE, normalize_timezone

    tz_name = normalize_timezone(str((settings or {}).get("timezone") or DEFAULT_TIMEZONE))

    filter_status = (request.args.get("status") or "").strip().lower()
    filter_prof = (request.args.get("professional_id") or "").strip()
    filter_q = (request.args.get("q") or "").strip()
    filter_date_raw = (request.args.get("date") or "").strip()
    filter_period = (request.args.get("period") or "").strip().lower()

    if tab == "agendamentos" and not filter_date_raw and not filter_period:
        filter_period = "today"

    anchor_day = parse_filter_date(filter_date_raw, tz_name) if filter_date_raw else None
    list_from, list_to, filter_period, period_label = resolve_appointments_period(
        period=filter_period if not anchor_day else None,
        anchor_date=anchor_day,
        tz_name=tz_name,
    )

    appointments = sched_repo.list_appointments_in_range(
        cid,
        list_from,
        list_to,
        professional_id=filter_prof or None,
        status=filter_status or None,
        search=filter_q or None,
        limit=500,
    )
    appointments.sort(key=lambda r: str(r.get("starts_at") or ""))
    dias = ["Segunda", "Terça", "Quarta", "Quinta", "Sexta", "Sábado", "Domingo"]
    prof_names = {str(p.get("id") or ""): (p.get("name") or "") for p in professionals if p.get("id")}

    public_agenda_url = ""
    public_book_url = ""
    slug = str((settings or {}).get("public_slug") or "").strip()
    try:
        from services.agendamento_ia_bridge import scheduling_uses_internal_motor
        from services.agendamento_ia_link import build_zapaction_public_agenda_url
        from services.agendamento_ia_urls import build_public_book_page_url

        if slug:
            public_agenda_url = build_zapaction_public_agenda_url(slug)
        if scheduling_uses_internal_motor(cid) and slug:
            public_book_url = public_agenda_url
        elif agendamento_ia_configured() and slug:
            public_book_url = build_public_book_page_url(slug)
    except Exception:
        public_agenda_url = ""
        public_book_url = ""

    from services.agendamento_ia_sync import sync_status_for_panel

    agenda_sync_status = sync_status_for_panel(cid)
    agenda_health = check_agendamento_ia_health() if agendamento_ia_configured() else None

    from services.agendamento_ia_appointment_webhook import appointment_origin_label

    appointment_origins = {
        str(a.get("id") or ""): appointment_origin_label(a) for a in appointments if a.get("id")
    }

    from services.scheduling.timezones import (
        DEFAULT_TIMEZONE,
        TIMEZONE_CHOICE_GROUPS,
        normalize_timezone,
        timezone_label,
    )

    tz_name = normalize_timezone(str((settings or {}).get("timezone") or DEFAULT_TIMEZONE))
    from services.scheduling.display import enrich_appointments_display

    appointments = enrich_appointments_display(appointments, tz_name)
    service_names = {str(s.get("id") or ""): str(s.get("name") or "") for s in services if s.get("id")}
    from services.scheduling.display import parse_iso_datetime
    from services.scheduling.slot_engine import _get_tz

    tz_obj = _get_tz(tz_name)
    for row in appointments:
        row["prof_name"] = prof_names.get(str(row.get("professional_id") or ""), "—")
        row["service_name"] = service_names.get(str(row.get("service_id") or ""), "—")
        if filter_period in ("today", "tomorrow", "day"):
            dt = parse_iso_datetime(row.get("starts_at"))
            if dt:
                row["starts_time_display"] = dt.astimezone(tz_obj).strftime("%H:%M")
    nav_view_date = None
    nav_prev_date = ""
    nav_next_date = ""
    nav_is_today = False
    is_single_day_view = filter_period in ("today", "tomorrow", "day")
    if tab == "agendamentos":
        from services.scheduling.appointments_filter import shift_view_date, view_date_for_period

        nav_view_date = view_date_for_period(
            period=filter_period,
            anchor_date=anchor_day,
            tz_name=tz_name,
        )
        nav_prev_date = shift_view_date(nav_view_date, -1).isoformat()
        nav_next_date = shift_view_date(nav_view_date, 1).isoformat()
        today_ref = view_date_for_period(period="today", anchor_date=None, tz_name=tz_name)
        nav_is_today = nav_view_date == today_ref
    upcoming = enrich_appointments_display(upcoming, tz_name)

    blocked_times_raw = sched_repo.list_blocked_times(cid, limit=50)
    from services.scheduling.display import format_datetime_br

    blocked_times = [
        {
            **b,
            "starts_display": format_datetime_br(b.get("starts_at"), tz_name),
            "ends_display": format_datetime_br(b.get("ends_at"), tz_name),
            "prof_name": prof_names.get(str(b.get("professional_id") or ""), "Toda a clínica"),
        }
        for b in blocked_times_raw
    ]

    reschedule_id = (request.args.get("reschedule") or "").strip()
    reschedule_row: dict | None = None
    reschedule_slots: list[str] = []
    reschedule_slot_labels: list[str] = []
    if reschedule_id:
        row_rs = sched_repo.get_appointment(cid, reschedule_id)
        if row_rs and str(row_rs.get("status") or "") != "cancelled":
            reschedule_row = enrich_appointments_display([row_rs], tz_name)[0]
            svc_rs = sched_repo.get_service(cid, str(row_rs.get("service_id") or ""))
            pid_rs = str(row_rs.get("professional_id") or "")
            if pid_rs and svc_rs:
                from services.scheduling.slots_public import compute_available_slot_isos

                reschedule_slots = compute_available_slot_isos(
                    cliente_id=cid,
                    service_id=str(row_rs.get("service_id") or ""),
                    professional_id=pid_rs,
                    tz_name=tz_name,
                    working_rows=working_hours,
                    duration_minutes=int(svc_rs.get("duration_minutes") or 30),
                    num_days=21,
                    max_slots=40,
                    exclude_appointment_id=reschedule_id,
                )
                reschedule_slot_labels = [
                    format_datetime_br(iso, tz_name) for iso in reschedule_slots
                ]

    google_status: dict | None = None
    google_status_by_provider: dict[str, dict] = {}
    if agendamento_ia_configured():
        from services.agendamento_ia_google_status import (
            fetch_google_status,
            fetch_google_status_by_providers,
        )

        try:
            if tab == "profissionais" and professionals:
                active_ids = [
                    str(p.get("id"))
                    for p in professionals
                    if p.get("id") and bool(p.get("active", True))
                ]
                google_status_by_provider = fetch_google_status_by_providers(cid, active_ids)
            google_status = fetch_google_status(cid)
        except Exception as exc:
            current_app.logger.warning("google_status fetch failed: %s", exc)
            google_status = {"error": "falha_diagnostico_google"}

    from services.google_calendar_oauth import (
        google_oauth_configured,
        google_oauth_env_present,
        google_oauth_libs_missing,
    )

    google_oauth_ready = google_oauth_configured() and agendamento_ia_configured()
    google_oauth_libs_missing_flag = google_oauth_libs_missing()
    google_oauth_env_present_flag = google_oauth_env_present()

    from services.scheduling.engine import (
        ENGINE_ZAPACTION_INTERNAL,
        get_scheduling_engine,
        scheduling_uses_internal_motor,
    )

    scheduling_engine = get_scheduling_engine(cid)
    scheduling_engine_label = (
        "ZapAction interno"
        if scheduling_engine == ENGINE_ZAPACTION_INTERNAL
        else "Agenda externa (Agendamento IA)"
    )

    try:
        return render_template(
            "scheduling/wizard.html",
            tab=tab,
            tab_index=tab_index,
            agendamento_ia_sync=clinic_sync_configured(),
            agendamento_ia_base_url=agendamento_ia_base_url(),
            agenda_sync_url=resolved_clinic_sync_url(),
            webhook_url_misconfigured=agendamento_webhook_url_misconfigured(),
            agendamento_ia_configured=agendamento_ia_configured(),
            link_generate_available=link_generate_available(),
            agenda_health=agenda_health,
            production_env=is_production_environment(),
            settings=settings,
            public_agenda_url=public_agenda_url,
            public_book_url=public_book_url,
            agenda_sync_status=agenda_sync_status,
            upcoming=upcoming,
            professionals=professionals,
            prof_names=prof_names,
            services=services,
            working_hours=working_hours,
            clinic_hours=clinic_hours,
            prof_hours=prof_hours,
            appointments=appointments,
            appointment_origins=appointment_origins,
            scheduling_timezone=tz_name,
            timezone_choice_groups=TIMEZONE_CHOICE_GROUPS,
            timezone_label=timezone_label,
            google_status=google_status,
            google_status_by_provider=google_status_by_provider,
            google_oauth_ready=google_oauth_ready,
            google_oauth_libs_missing=google_oauth_libs_missing_flag,
            google_oauth_env_present=google_oauth_env_present_flag,
            scheduling_engine=scheduling_engine,
            scheduling_engine_label=scheduling_engine_label,
            scheduling_uses_internal=scheduling_uses_internal_motor(cid),
            dias=dias,
            blocked_times=blocked_times,
            reschedule_row=reschedule_row,
            reschedule_slots=reschedule_slots,
            reschedule_slot_labels=reschedule_slot_labels,
            filter_status=filter_status,
            filter_professional_id=filter_prof,
            filter_q=filter_q,
            filter_period=filter_period,
            period_label=period_label,
            filter_date=filter_date_raw,
            appointments_count=len(appointments),
            nav_view_date=nav_view_date.isoformat() if nav_view_date else "",
            nav_prev_date=nav_prev_date,
            nav_next_date=nav_next_date,
            nav_is_today=nav_is_today,
            is_single_day_view=is_single_day_view,
        )
    except Exception:
        current_app.logger.exception("scheduling.home render failed cliente_id=%s tab=%s", cid[:8], tab)
        flash(
            "Não foi possível carregar a agenda. Tente de novo ou use «Sincronizar do Agendamento IA» na aba Agendamentos.",
            "error",
        )
        return redirect(url_for("customer.dashboard"))


@scheduling_bp.route("/profissionais", methods=["GET", "POST"])
@login_required
def profissionais():
    return redirect(url_for("scheduling.home", tab="profissionais"))


@scheduling_bp.route("/servicos", methods=["GET", "POST"])
@login_required
def servicos():
    return redirect(url_for("scheduling.home", tab="servicos"))


@scheduling_bp.route("/horarios", methods=["GET", "POST"])
@login_required
def horarios():
    return redirect(url_for("scheduling.home", tab="horarios"))


@scheduling_bp.route("/agendamentos", methods=["GET", "POST"])
@scheduling_bp.route("/marcacoes", methods=["GET", "POST"])
@login_required
def agendamentos():
    """`/marcacoes` mantém-se como alias (links antigos)."""
    return redirect(url_for("scheduling.home", tab="agendamentos", period="today"))


@scheduling_bp.route("/config", methods=["GET", "POST"])
@login_required
def config():
    return redirect(url_for("scheduling.home", tab="clinica"))


@scheduling_bp.route("/calendario", methods=["GET"])
@login_required
def calendario():
    """Calendário visual (dia / semana / mês) com dashboard."""
    cid = _cliente_id()
    if not cid or not supabase:
        flash("Sessão inválida ou base indisponível.", "error")
        return redirect(url_for("customer.dashboard"))
    from datetime import timedelta

    from services.agendamento_ia_appointment_webhook import appointment_origin_label
    from services.scheduling import repository as sched_repo
    from services.scheduling.calendar import build_calendar_view, parse_anchor_date
    from services.scheduling.display import enrich_appointments_display
    from services.scheduling.stats import compute_dashboard_stats
    from services.scheduling.timezones import DEFAULT_TIMEZONE, normalize_timezone

    view = (request.args.get("view") or "day").strip().lower()
    st = sched_repo.get_settings(cid) or {}
    tz_name = normalize_timezone(str(st.get("timezone") or DEFAULT_TIMEZONE))
    anchor = parse_anchor_date(request.args.get("date"), tz_name)
    filter_prof = (request.args.get("professional_id") or "").strip()
    filter_status = (request.args.get("status") or "all").strip().lower()

    if view == "day":
        range_start = anchor
        range_end = anchor + timedelta(days=1)
    elif view == "month":
        first = anchor.replace(day=1)
        range_start = first - timedelta(days=first.weekday())
        range_end = range_start + timedelta(days=42)
    else:
        view = "week"
        range_start = anchor - timedelta(days=anchor.weekday())
        range_end = range_start + timedelta(days=7)

    from services.scheduling.slot_engine import _get_tz

    tz = _get_tz(tz_name)
    from_utc = datetime.combine(range_start, datetime.min.time(), tzinfo=tz).astimezone(timezone.utc)
    to_utc = datetime.combine(range_end, datetime.min.time(), tzinfo=tz).astimezone(timezone.utc)

    raw_appts = sched_repo.list_appointments_in_range(
        cid,
        from_utc,
        to_utc,
        professional_id=filter_prof or None,
        status=None if filter_status in ("", "all") else filter_status,
        limit=500,
    )
    professionals = sched_repo.list_professionals(cid, active_only=False)
    services = sched_repo.list_services(cid, active_only=False)
    prof_names = {str(p.get("id") or ""): str(p.get("name") or "") for p in professionals}
    service_names = {str(s.get("id") or ""): str(s.get("name") or "") for s in services}
    enriched = enrich_appointments_display(raw_appts, tz_name)
    for row in enriched:
        row["origin"] = "agenda" if appointment_origin_label(row) == "agenda" else "local"

    cal = build_calendar_view(
        view=view,
        anchor=anchor,
        appointments=enriched,
        tz_name=tz_name,
        prof_names=prof_names,
        service_names=service_names,
    )
    stats_from = datetime.now(timezone.utc) - timedelta(days=30)
    stats_to = datetime.now(timezone.utc) + timedelta(days=60)
    stats_rows = sched_repo.list_appointments_in_range(cid, stats_from, stats_to, limit=500)
    stats = compute_dashboard_stats(enrich_appointments_display(stats_rows, tz_name), tz_name=tz_name)

    prev_date = (anchor - timedelta(days=1 if view == "day" else 7 if view == "week" else 28)).isoformat()
    next_date = (anchor + timedelta(days=1 if view == "day" else 7 if view == "week" else 28)).isoformat()

    return render_template(
        "scheduling/calendario.html",
        view=view,
        anchor=anchor.isoformat(),
        calendar=cal,
        stats=stats,
        professionals=professionals,
        filter_professional_id=filter_prof,
        filter_status=filter_status,
        scheduling_timezone=tz_name,
        settings=st,
        prev_date=prev_date,
        next_date=next_date,
        public_agenda_url="",
    )


@scheduling_bp.route("/api/appointment/reschedule", methods=["POST"])
@login_required
def api_appointment_reschedule():
    """Remarcação via drag-and-drop no calendário (JSON)."""
    cid = _cliente_id()
    if not cid:
        return jsonify({"ok": False, "error": "sessao_invalida"}), 401
    data = request.get_json(silent=True) or {}
    aid = str(data.get("appointment_id") or "").strip()
    slot_iso = str(data.get("starts_at") or data.get("slot_iso") or "").strip()
    if not aid or not slot_iso:
        return jsonify({"ok": False, "error": "dados_em_falta"}), 400
    from services.agendamento_ia_appointment_webhook import appointment_origin_label
    from services.scheduling import repository as sched_repo
    from services.scheduling.bookings import reschedule_appointment

    existing = sched_repo.get_appointment(cid, aid)
    if not existing:
        return jsonify({"ok": False, "error": "nao_encontrado"}), 404
    if appointment_origin_label(existing) == "agenda":
        return jsonify({"ok": False, "error": "origem_agenda"}), 400
    svc = sched_repo.get_service(cid, str(existing.get("service_id") or ""))
    dur = int((svc or {}).get("duration_minutes") or 30)
    try:
        new_start = datetime.fromisoformat(slot_iso.replace("Z", "+00:00"))
    except Exception:
        return jsonify({"ok": False, "error": "horario_invalido"}), 400
    ok, err = reschedule_appointment(
        cliente_id=cid,
        appointment_id=aid,
        new_starts_at=new_start,
        duration_minutes=dur,
        professional_id=str(existing.get("professional_id") or "") or None,
    )
    if not ok:
        return jsonify({"ok": False, "error": err or "falha"}), 409
    return jsonify({"ok": True})


def _professional_owned_by_cliente(cid: str, provider_id: str) -> bool:
    pid = (provider_id or "").strip()
    if not pid:
        return False
    try:
        r = (
            supabase.table(Tables.SCHEDULING_PROFESSIONALS)
            .select(SchedulingProfessionalModel.ID)
            .eq(SchedulingProfessionalModel.CLIENTE_ID, cid)
            .eq(SchedulingProfessionalModel.ID, pid)
            .limit(1)
            .execute()
        )
        return bool(r.data)
    except Exception:
        return False


@scheduling_bp.route("/google/connect", methods=["GET"])
@login_required
def google_connect():
    """Redireciona direto para login Google (OAuth no domínio ZapAction)."""
    cid = _cliente_id()
    if not cid:
        flash("Sessão inválida.", "error")
        return redirect(url_for("customer.dashboard"))
    provider_id = (request.args.get("provider_id") or "").strip()
    if not provider_id:
        flash("Profissional não indicado.", "error")
        return redirect(url_for("scheduling.home", tab="profissionais"))
    if not _professional_owned_by_cliente(cid, provider_id):
        flash("Profissional não encontrado.", "error")
        return redirect(url_for("scheduling.home", tab="profissionais"))

    from services.agendamento_ia_urls import agendamento_ia_configured
    from services.google_calendar_oauth import (
        build_google_authorize_url,
        google_oauth_configured,
        google_redirect_uri,
    )

    if not agendamento_ia_configured():
        flash(
            "Integração com o Agendamento IA não está configurada. "
            "Defina AGENDAMENTO_IA_BASE_URL e AGENDAMENTO_IA_API_KEY.",
            "warning",
        )
        return redirect(url_for("scheduling.home", tab="profissionais"))
    if not google_oauth_configured():
        flash(
            "Google Calendar não está configurado no ZapAction. "
            "Defina GOOGLE_CLIENT_ID e GOOGLE_CLIENT_SECRET no .env "
            "(mesmo projeto Google Cloud do Agenda) e "
            "GOOGLE_OAUTH_REDIRECT_URI apontando para este painel.",
            "warning",
        )
        return redirect(url_for("scheduling.home", tab="profissionais"))

    redirect_uri = google_redirect_uri(request.url_root)
    if not redirect_uri:
        flash("Não foi possível determinar a URL de callback OAuth.", "error")
        return redirect(url_for("scheduling.home", tab="profissionais"))

    from services.agendamento_ia_sync import sync_catalog_to_agendamento_ia

    sync_err = sync_catalog_to_agendamento_ia(cid, force=True)
    if sync_err:
        flash(
            (sync_err or "Não foi possível sincronizar a agenda com o Agendamento IA.")
            + " Use «Sincronizar catálogo» no topo da agenda e tente de novo.",
            "warning",
        )
        return redirect(url_for("scheduling.home", tab="profissionais"))

    try:
        auth_url = build_google_authorize_url(
            cliente_id=cid,
            provider_id=provider_id,
            redirect_uri=redirect_uri,
            force_consent=True,
        )
    except ValueError as e:
        flash(f"Não foi possível iniciar a ligação ao Google: {e}", "error")
        return redirect(url_for("scheduling.home", tab="profissionais"))
    except Exception as e:
        current_app.logger.exception("google_connect failed cliente_id=%s provider_id=%s", cid[:8], provider_id[:8])
        flash(
            "Erro interno ao abrir login Google. Confira GOOGLE_CLIENT_ID/SECRET, "
            "redirect URI no Google Console e se instalou as dependências (pip install -r requirements.txt).",
            "error",
        )
        return redirect(url_for("scheduling.home", tab="profissionais"))
    return redirect(auth_url)


@scheduling_bp.route("/google/callback", methods=["GET"])
@login_required
def google_callback():
    """Callback OAuth Google no ZapAction; grava tokens no Agenda via API."""
    cid = _cliente_id()
    if not cid:
        flash("Sessão inválida.", "error")
        return redirect(url_for("customer.dashboard"))

    code = (request.args.get("code") or "").strip()
    state = (request.args.get("state") or "").strip()
    oauth_err = (request.args.get("error") or "").strip()

    if oauth_err:
        flash(f"Google cancelou ou recusou a ligação ({oauth_err}).", "error")
        return redirect(url_for("scheduling.home", tab="profissionais"))
    if not code or not state:
        flash("Resposta incompleta do Google. Tente Conectar Google novamente.", "error")
        return redirect(url_for("scheduling.home", tab="profissionais"))

    from services.google_calendar_oauth import (
        exchange_google_code,
        google_redirect_uri,
        verify_oauth_state,
    )
    from services.agendamento_ia_google_status import push_google_tokens_to_agendamento_ia

    parsed = verify_oauth_state(state)
    if not parsed:
        flash("Sessão OAuth expirada ou inválida. Clique Conectar Google novamente.", "error")
        return redirect(url_for("scheduling.home", tab="profissionais"))
    state_cid, provider_id = parsed
    if state_cid != cid:
        flash("Sessão não confere. Inicie a ligação novamente.", "error")
        return redirect(url_for("scheduling.home", tab="profissionais"))
    if not _professional_owned_by_cliente(cid, provider_id):
        flash("Profissional não encontrado.", "error")
        return redirect(url_for("scheduling.home", tab="profissionais"))

    redirect_uri = google_redirect_uri(request.url_root)
    try:
        refresh_token = exchange_google_code(
            code=code,
            redirect_uri=redirect_uri,
            authorization_response=request.url,
        )
    except ValueError as e:
        flash(str(e)[:400], "error")
        return redirect(url_for("scheduling.home", tab="profissionais"))
    except Exception as e:
        current_app.logger.exception("google_callback exchange failed cliente_id=%s", cid[:8])
        flash(
            "Erro ao concluir ligação Google. Tente Conectar Google novamente.",
            "error",
        )
        return redirect(url_for("scheduling.home", tab="profissionais"))

    from services.agendamento_ia_sync import sync_catalog_to_agendamento_ia

    ok, err = push_google_tokens_to_agendamento_ia(
        cid, provider_id=provider_id, refresh_token=refresh_token
    )
    if not ok and err == "provider_not_found":
        sync_err = sync_catalog_to_agendamento_ia(cid, force=True)
        if not sync_err:
            ok, err = push_google_tokens_to_agendamento_ia(
                cid, provider_id=provider_id, refresh_token=refresh_token
            )
        else:
            err = f"provider_not_found após sync: {sync_err}"

    if ok:
        flash("Google Calendar conectado com sucesso.", "success")
    elif err == "provider_not_found" or (
        err and str(err).startswith("provider_not_found")
    ):
        flash(
            "O profissional não foi encontrado no Agendamento IA. "
            "Na aba Clínica, guarde os dados da clínica (slug e nome), volte a Profissionais "
            "e clique em Conectar Google. Se persistir, confira AGENDAMENTO_IA_CLINIC_SYNC_URL "
            "e faça deploy do serviço agendamento-ia mais recente.",
            "warning",
        )
    else:
        flash(
            f"Google autorizou, mas falhou ao guardar no Agenda ({err or 'erro'}). "
            "Tente Reconectar.",
            "error",
        )
    return redirect(url_for("scheduling.home", tab="profissionais"))


@scheduling_bp.route("/google/disconnect", methods=["POST"])
@login_required
def google_disconnect():
    cid = _cliente_id()
    if not cid:
        flash("Sessão inválida.", "error")
        return redirect(url_for("customer.dashboard"))
    provider_id = (request.form.get("provider_id") or "").strip()
    if not provider_id or not _professional_owned_by_cliente(cid, provider_id):
        flash("Profissional não encontrado.", "error")
        return redirect(url_for("scheduling.home", tab="profissionais"))

    from services.agendamento_ia_google_status import disconnect_google_provider

    ok, err = disconnect_google_provider(cid, provider_id=provider_id)
    if ok:
        flash("Google Calendar desligado deste profissional.", "success")
    elif err:
        flash(f"Não foi possível desligar o Google: {err}", "error")
    else:
        flash("Não foi possível desligar o Google.", "error")
    return redirect(url_for("scheduling.home", tab="profissionais"))
