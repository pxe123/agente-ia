"""
Motor interno multi-turno: mesma forma de saída que `parse_api_response` em agendamento_ia_bridge.
"""
from __future__ import annotations

import re
import unicodedata
from datetime import datetime, timedelta, timezone
from typing import Any

from services.agendamento_ia_contact import (
    contact_hints_from_collected,
    normalize_collected_for_agendamento,
)
from services.scheduling import repository as scheduling_repository
from services.scheduling.bookings import book_appointment
from services.scheduling.slot_engine import slot_starts_in_range


def _booking_contact_from_context(ctx: dict[str, Any]) -> tuple[str, str, str, str | None]:
    """(nome, email, telefone, notes) a partir de collected_data / hints do fluxo."""
    collected = ctx.get("collected_data") if isinstance(ctx.get("collected_data"), dict) else {}
    cd = normalize_collected_for_agendamento(collected)
    hints = contact_hints_from_collected(cd)
    nome = (cd.get("nome") or hints.get("contact_name") or ctx.get("contact_name") or "").strip()
    email = (cd.get("email") or hints.get("contact_email") or ctx.get("contact_email") or "").strip()
    tel = (cd.get("telefone") or hints.get("contact_phone") or ctx.get("contact_phone") or "").strip()
    parts = [p for p in (nome, email) if p]
    notes = " — ".join(parts) if parts else None
    return nome, email, tel, notes


def _norm(s: str) -> str:
    s = (s or "").strip().lower()
    s = "".join(c for c in unicodedata.normalize("NFD", s) if unicodedata.category(c) != "Mn")
    return s


def _parsed(
    *,
    api_status: str,
    done: bool,
    data: dict[str, Any] | None,
    session: dict[str, Any] | None,
    reply: str = "",
    action: dict[str, Any] | None = None,
    err: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "reply": reply,
        "done": done,
        "action": action,
        "session": session,
        "raw_error": None,
        "api_version": 1,
        "api_status": api_status,
        "data": data,
        "error": err,
        "status": api_status,
    }


def _eligible_professionals(
    services: list[dict[str, Any]], professionals: list[dict[str, Any]], service_id: str
) -> list[dict[str, Any]]:
    svc = next((x for x in services if str(x.get("id")) == str(service_id)), None)
    if not svc:
        return []
    pid = svc.get("professional_id")
    if pid:
        return [p for p in professionals if str(p.get("id")) == str(pid)]
    return list(professionals)


def _match_by_name_or_index(items: list[dict[str, Any]], text: str, name_key: str = "name") -> dict[str, Any] | None:
    t = _norm(text)
    if not t:
        return None
    if t.isdigit():
        i = int(t) - 1
        if 0 <= i < len(items):
            return items[i]
    for it in items:
        nm = _norm(str(it.get(name_key) or ""))
        if nm and (nm in t or t in nm):
            return it
    first = re.split(r"\s+", t, maxsplit=1)[0] if t else ""
    if first and first.isdigit():
        i = int(first) - 1
        if 0 <= i < len(items):
            return items[i]
    for it in items:
        nm = _norm(str(it.get(name_key) or ""))
        if first and first in nm:
            return it
    return None


def _service_lines(services: list[dict[str, Any]]) -> str:
    lines = [f"{i + 1}) {s.get('name')}" for i, s in enumerate(services)]
    return "Escolha o serviço (número ou nome):\n" + "\n".join(lines)


def _prof_lines(profs: list[dict[str, Any]]) -> str:
    lines = [f"{i + 1}) {p.get('name')}" for i, p in enumerate(profs)]
    return "Escolha o profissional (número ou nome):\n" + "\n".join(lines)


def _slot_lines(slot_starts: list[datetime], tz_name: str) -> str:
    from services.scheduling.slot_engine import _get_tz

    tz = _get_tz(tz_name)
    lines = []
    for i, st in enumerate(slot_starts):
        local = st.astimezone(tz)
        lines.append(f"{i + 1}) {local.strftime('%d/%m %H:%M')}")
    return "Horários disponíveis (número):\n" + "\n".join(lines)


def _slot_lines_from_iso(iso_opts: list[str], tz_name: str) -> str:
    dts: list[datetime] = []
    for o in iso_opts:
        try:
            dts.append(datetime.fromisoformat(str(o).replace("Z", "+00:00")))
        except Exception:
            continue
    if not dts:
        return "Nenhum horário disponível."
    return _slot_lines(dts, tz_name)


def _handle_cancel_turn(
    body: dict[str, Any],
    *,
    ctx: dict[str, Any],
    cliente_id: str,
    remote_id: str | None,
    session: dict[str, Any],
) -> dict[str, Any]:
    from services.scheduling.bookings import cancel_appointment
    from services.scheduling.display import format_datetime_br

    booking = body.get("booking") if isinstance(body.get("booking"), dict) else {}
    appointment_id = str(booking.get("appointment_id") or "").strip()

    if appointment_id:
        row = scheduling_repository.get_appointment(cliente_id, appointment_id)
        if not row:
            return _parsed(
                api_status="error",
                done=True,
                data={"intent": "cancel"},
                session=session,
                err={"code": "appointment_not_found", "message": "Marcação não encontrada."},
            )
        row_rid = str(row.get("remote_id") or "").strip()
        if remote_id and row_rid and row_rid != remote_id:
            return _parsed(
                api_status="error",
                done=True,
                data={"intent": "cancel"},
                session=session,
                err={"code": "forbidden", "message": "Marcação não pertence a este contacto."},
            )
        if not cancel_appointment(cliente_id, appointment_id):
            return _parsed(
                api_status="error",
                done=True,
                data={"intent": "cancel"},
                session=session,
                err={"code": "cancel_failed", "message": "Não foi possível cancelar."},
            )
        session.clear()
        return _parsed(
            api_status="ok",
            done=True,
            data={"intent": "cancel", "cancelled_appointment_id": appointment_id},
            session=session,
            action={"type": "cancel", "payload": {"cancelled_appointment_id": appointment_id}},
            reply="",
        )

    if not remote_id:
        return _parsed(
            api_status="error",
            done=True,
            data={"intent": "cancel"},
            session=session,
            err={"code": "missing_remote_id", "message": "Sem contacto para localizar marcações."},
        )

    upcoming = scheduling_repository.list_upcoming_by_remote_id(cliente_id, remote_id, limit=5)
    if not upcoming:
        return _parsed(
            api_status="error",
            done=True,
            data={"intent": "cancel"},
            session=session,
            err={"code": "no_upcoming", "message": "Não há marcações futuras para cancelar."},
        )

    if len(upcoming) == 1:
        aid = str(upcoming[0].get("id") or "")
        if not aid or not cancel_appointment(cliente_id, aid):
            return _parsed(
                api_status="error",
                done=True,
                data={"intent": "cancel"},
                session=session,
                err={"code": "cancel_failed", "message": "Não foi possível cancelar."},
            )
        session.clear()
        return _parsed(
            api_status="ok",
            done=True,
            data={"intent": "cancel", "cancelled_appointment_id": aid},
            session=session,
            action={"type": "cancel", "payload": {"cancelled_appointment_id": aid}},
            reply="",
        )

    st = scheduling_repository.get_settings(cliente_id) or {}
    from services.scheduling.timezones import normalize_timezone

    tz_name = normalize_timezone(str(st.get("timezone") or ""))
    lines = [
        f"{i + 1}) {format_datetime_br(str(ap.get('starts_at') or ''), tz_name)}"
        for i, ap in enumerate(upcoming)
    ]
    session["scheduling_step"] = "cancel_pick"
    session["scheduling_cancel_options"] = [str(ap.get("id") or "") for ap in upcoming]
    return _parsed(
        api_status="needs_input",
        done=False,
        data={"intent": "cancel_list"},
        session=session,
        reply="Qual marcação deseja cancelar?\n" + "\n".join(lines),
    )


def handle_turn(body: dict[str, Any]) -> dict[str, Any]:
    """
    body: request_schema_version, user_message, context, session, zapaction_turn_id, inbound_user_message_id
    """
    ctx = body.get("context") if isinstance(body.get("context"), dict) else {}
    cliente_id = str(ctx.get("cliente_id") or "").strip()
    remote_id = str(ctx.get("remote_id") or "").strip() or None
    user_message = str(body.get("user_message") or "").strip()
    sess_in = body.get("session") if isinstance(body.get("session"), dict) else {}
    session = dict(sess_in)

    if not cliente_id:
        return _parsed(
            api_status="error",
            done=False,
            data={"intent": "none"},
            session=session,
            err={"code": "missing_cliente_id", "message": "Sem cliente_id no contexto."},
        )

    if not scheduling_repository.supabase_available():
        return _parsed(
            api_status="error",
            done=False,
            data={"intent": "none"},
            session=session,
            err={"code": "sem_supabase", "message": "Base de dados indisponível."},
        )

    operation = str(body.get("operation") or "").strip().lower()
    if operation == "cancel":
        return _handle_cancel_turn(
            body, ctx=ctx, cliente_id=cliente_id, remote_id=remote_id, session=session
        )

    settings = scheduling_repository.ensure_settings(cliente_id)
    from services.scheduling.timezones import normalize_timezone

    tz_name = normalize_timezone(str(settings.get("timezone") or ""))

    professionals = scheduling_repository.list_professionals(cliente_id, active_only=True)
    services = scheduling_repository.list_services(cliente_id, active_only=True)
    working_rows = scheduling_repository.list_working_hours_all(cliente_id)

    if not services or not professionals:
        return _parsed(
            api_status="error",
            done=False,
            data={"intent": "none"},
            session=session,
            err={
                "code": "agenda_nao_configurada",
                "message": "Configure serviços e profissionais no painel (Agenda).",
            },
        )

    nd = ctx.get("node_data") if isinstance(ctx.get("node_data"), dict) else {}
    pref_sid = str(nd.get("service_id") or "").strip()
    if pref_sid and not session.get("scheduling_service_id"):
        picked0 = next((x for x in services if str(x.get("id")) == pref_sid), None)
        if picked0:
            session["scheduling_service_id"] = pref_sid
            eprofs0 = _eligible_professionals(services, professionals, pref_sid)
            if len(eprofs0) <= 1:
                pid0 = (
                    str(eprofs0[0].get("id"))
                    if eprofs0
                    else (str(professionals[0].get("id")) if professionals else "")
                )
                session["scheduling_professional_id"] = pid0
                session["scheduling_step"] = "choose_slot"
                return _advance_to_slots(
                    cliente_id=cliente_id,
                    session=session,
                    services=services,
                    professionals=professionals,
                    working_rows=working_rows,
                    tz_name=tz_name,
                )
            session["scheduling_step"] = "choose_professional"
            return _parsed(
                api_status="needs_input",
                done=False,
                data={"intent": "list_professionals"},
                session=session,
                reply=_prof_lines(eprofs0),
            )

    low = _norm(user_message)

    if str(session.get("scheduling_step") or "") == "cancel_pick":
        opts = session.get("scheduling_cancel_options")
        if isinstance(opts, list) and opts:
            from services.scheduling.bookings import cancel_appointment

            idx: int | None = None
            if low.isdigit():
                idx = int(low) - 1
            if idx is not None and 0 <= idx < len(opts):
                aid = str(opts[idx] or "").strip()
                if aid and cancel_appointment(cliente_id, aid):
                    session.clear()
                    return _parsed(
                        api_status="ok",
                        done=True,
                        data={"intent": "cancel", "cancelled_appointment_id": aid},
                        session=session,
                        action={"type": "cancel", "payload": {"cancelled_appointment_id": aid}},
                        reply="",
                    )
                return _parsed(
                    api_status="error",
                    done=True,
                    data={"intent": "cancel"},
                    session=session,
                    err={"code": "cancel_failed", "message": "Não foi possível cancelar."},
                )
        session.pop("scheduling_step", None)
        session.pop("scheduling_cancel_options", None)

    if low in ("cancelar", "sair", "reset", "reiniciar"):
        for k in list(session.keys()):
            if str(k).startswith("scheduling_"):
                session.pop(k, None)
        return _parsed(
            api_status="needs_input",
            done=False,
            data={"intent": "list_services", "slots": []},
            session=session,
            reply=_service_lines(services),
        )

    step = str(session.get("scheduling_step") or "choose_service")

    # --- choose_service ---
    if step == "choose_service":
        picked = _match_by_name_or_index(services, user_message)
        if not picked:
            session["scheduling_step"] = "choose_service"
            return _parsed(
                api_status="needs_input",
                done=False,
                data={"intent": "list_services", "slots": []},
                session=session,
                reply=_service_lines(services),
            )
        session["scheduling_service_id"] = str(picked.get("id"))
        eprofs = _eligible_professionals(services, professionals, session["scheduling_service_id"])
        if len(eprofs) <= 1:
            pid = str(eprofs[0].get("id")) if eprofs else str(professionals[0].get("id"))
            session["scheduling_professional_id"] = pid
            session["scheduling_step"] = "choose_slot"
            return _advance_to_slots(
                cliente_id=cliente_id,
                session=session,
                services=services,
                professionals=professionals,
                working_rows=working_rows,
                tz_name=tz_name,
            )
        session["scheduling_step"] = "choose_professional"
        return _parsed(
            api_status="needs_input",
            done=False,
            data={"intent": "list_professionals"},
            session=session,
            reply=_prof_lines(eprofs),
        )

    # --- choose_professional ---
    if step == "choose_professional":
        eprofs = _eligible_professionals(services, professionals, str(session.get("scheduling_service_id")))
        picked = _match_by_name_or_index(eprofs, user_message)
        if not picked:
            return _parsed(
                api_status="needs_input",
                done=False,
                data={"intent": "list_professionals"},
                session=session,
                reply=_prof_lines(eprofs),
            )
        session["scheduling_professional_id"] = str(picked.get("id"))
        session["scheduling_step"] = "choose_slot"
        return _advance_to_slots(
            cliente_id=cliente_id,
            session=session,
            services=services,
            professionals=professionals,
            working_rows=working_rows,
            tz_name=tz_name,
        )

    # --- choose_slot ---
    if step == "choose_slot":
        opts = session.get("scheduling_slot_options")
        if not isinstance(opts, list) or not opts:
            return _advance_to_slots(
                cliente_id=cliente_id,
                session=session,
                services=services,
                professionals=professionals,
                working_rows=working_rows,
                tz_name=tz_name,
            )
        idx: int | None = None
        if low.isdigit():
            idx = int(low) - 1
        if idx is None or idx < 0 or idx >= len(opts):
            return _parsed(
                api_status="needs_input",
                done=False,
                data={
                    "intent": "list_slots",
                    "slots": [{"start": o, "end": ""} for o in opts[:20]],
                },
                session=session,
                reply=_slot_lines_from_iso(opts[:20], tz_name),
            )
        session["scheduling_pending_iso"] = str(opts[idx])
        session["scheduling_step"] = "confirm"
        return _parsed(
            api_status="needs_input",
            done=False,
            data={"intent": "confirm", "selected_slot": {"start": session["scheduling_pending_iso"], "end": ""}},
            session=session,
            reply="Confirma este horário? Responda **sim** para gravar ou **cancelar** para recomeçar.",
        )

    # --- confirm ---
    if step == "confirm":
        yes = low in ("sim", "s", "ok", "confirmar", "1", "quero", "pode", "isso")
        if not yes:
            session["scheduling_step"] = "choose_slot"
            session.pop("scheduling_pending_iso", None)
            return _advance_to_slots(
                cliente_id=cliente_id,
                session=session,
                services=services,
                professionals=professionals,
                working_rows=working_rows,
                tz_name=tz_name,
            )
        svc_id = str(session.get("scheduling_service_id") or "")
        prof_id = str(session.get("scheduling_professional_id") or "")
        iso = str(session.get("scheduling_pending_iso") or "")
        svc = scheduling_repository.get_service(cliente_id, svc_id)
        if not svc:
            return _parsed(api_status="error", done=False, data=None, session=session, err={"code": "service_gone"})
        try:
            starts = datetime.fromisoformat(iso.replace("Z", "+00:00"))
        except Exception:
            return _parsed(api_status="error", done=False, data=None, session=session, err={"code": "bad_slot"})
        dur = int(svc.get("duration_minutes") or 30)
        _nome, _email, contact_phone, notes = _booking_contact_from_context(ctx)
        meta: dict[str, Any] = {}
        if _email:
            meta["contact_email"] = _email
        if _nome:
            meta["contact_name"] = _nome
        row, err = book_appointment(
            cliente_id=cliente_id,
            service_id=svc_id,
            professional_id=prof_id or None,
            starts_at=starts,
            duration_minutes=dur,
            remote_id=remote_id,
            contact_phone=contact_phone or None,
            notes=notes,
            meta=meta or None,
        )
        if err or not row:
            return _parsed(
                api_status="error",
                done=False,
                data={"intent": "none"},
                session=session,
                err={"code": err or "book_failed"},
            )
        ends_iso = row.get("ends_at")
        session.clear()
        return _parsed(
            api_status="ok",
            done=True,
            data={
                "intent": "schedule",
                "appointment": {
                    "id": str(row.get("id")),
                    "start": row.get("starts_at"),
                    "end": ends_iso,
                },
            },
            session=session,
            action={"type": "schedule", "payload": {"appointment": row}},
            reply="",
        )

    session["scheduling_step"] = "choose_service"
    return _parsed(
        api_status="needs_input",
        done=False,
        data={"intent": "list_services", "slots": []},
        session=session,
        reply=_service_lines(services),
    )


def _slot_lines_from_iso(iso_opts: list[str], tz_name: str) -> str:
    dts: list[datetime] = []
    for o in iso_opts:
        try:
            dts.append(datetime.fromisoformat(str(o).replace("Z", "+00:00")))
        except Exception:
            continue
    if not dts:
        return "Nenhum horário disponível."
    return _slot_lines(dts, tz_name)


def _advance_to_slots(
    *,
    cliente_id: str,
    session: dict[str, Any],
    services: list[dict[str, Any]],
    professionals: list[dict[str, Any]],
    working_rows: list[dict[str, Any]],
    tz_name: str,
) -> dict[str, Any]:
    from zoneinfo import ZoneInfo

    svc_id = str(session.get("scheduling_service_id") or "")
    prof_id = str(session.get("scheduling_professional_id") or "")
    svc = next((x for x in services if str(x.get("id")) == svc_id), None)
    if not svc or not prof_id:
        session["scheduling_step"] = "choose_service"
        return _parsed(
            api_status="needs_input",
            done=False,
            data={"intent": "list_services", "slots": []},
            session=session,
            reply=_service_lines(services),
        )
    dur = int(svc.get("duration_minutes") or 30)
    from services.scheduling.slot_engine import _get_tz

    tz = _get_tz(tz_name)
    today = datetime.now(timezone.utc).astimezone(tz).date()
    from_utc = datetime.combine(today, datetime.min.time(), tzinfo=tz).astimezone(timezone.utc)
    to_utc = from_utc + timedelta(days=21)
    busy = scheduling_repository.busy_intervals_utc(cliente_id, prof_id, from_utc, to_utc)
    slots = slot_starts_in_range(
        tz_name=tz_name,
        start_day=today,
        num_days=14,
        duration_minutes=dur,
        professional_id=prof_id,
        working_rows=working_rows,
        busy_intervals_utc=busy,
    )
    iso_opts = [s.astimezone(timezone.utc).isoformat() for s in slots]
    session["scheduling_slot_options"] = iso_opts
    session["scheduling_step"] = "choose_slot"
    if not iso_opts:
        return _parsed(
            api_status="error",
            done=False,
            data={"intent": "list_slots", "slots": []},
            session=session,
            err={"code": "sem_slots", "message": "Sem horários livres. Ajuste horários de trabalho no painel."},
        )
    return _parsed(
        api_status="needs_input",
        done=False,
        data={"intent": "list_slots", "slots": [{"start": o, "end": ""} for o in iso_opts[:20]]},
        session=session,
        reply=_slot_lines(slots[:20], tz_name),
    )


def build_parsed_response_for_flow(body: dict[str, Any]) -> dict[str, Any]:
    """Alias explícito para o bridge."""
    return handle_turn(body)
