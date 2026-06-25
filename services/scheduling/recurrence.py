"""Séries recorrentes: regras, expansão e gestão de ocorrências materializadas."""
from __future__ import annotations

import calendar
import logging
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta, timezone
from typing import Any

from database.models import SchedulingAppointmentModel, SchedulingRecurrenceSeriesModel, Tables
from services.scheduling import repository
from services.scheduling.slot_engine import _get_tz
from services.scheduling.timezones import normalize_timezone

logger = logging.getLogger(__name__)

HORIZON_DAYS = 90
SERIES_ACTIVE = "active"
SERIES_PAUSED = "paused"
SERIES_ENDED = "ended"

_WEEKDAY_LABELS = ("Seg", "Ter", "Qua", "Qui", "Sex", "Sáb", "Dom")


@dataclass
class ExpansionResult:
    created: int = 0
    skipped_conflict: int = 0
    skipped_skip: int = 0
    skipped_existing: int = 0
    synced: int = 0
    sync_pending: int = 0
    conflicts: list[dict[str, Any]] = field(default_factory=list)


def _parse_time_local(value: Any) -> time | None:
    if isinstance(value, time):
        return value
    s = str(value or "").strip()
    if not s:
        return None
    if len(s) >= 5 and ":" in s:
        parts = s.split(":")
        try:
            return time(int(parts[0]), int(parts[1]), int(parts[2]) if len(parts) > 2 else 0)
        except (TypeError, ValueError):
            return None
    return None


def _parse_date(value: Any) -> date | None:
    if isinstance(value, date) and not isinstance(value, datetime):
        return value
    s = str(value or "").strip()[:10]
    if not s:
        return None
    try:
        return date.fromisoformat(s)
    except ValueError:
        return None


def normalize_rule(frequency: str, rule: dict[str, Any] | None) -> dict[str, Any]:
    freq = (frequency or "").strip().lower()
    data = dict(rule or {})
    if freq == "daily":
        mode = str(data.get("mode") or "all_days").strip().lower()
        if mode not in ("all_days", "weekdays"):
            mode = "all_days"
        return {"mode": mode}
    if freq == "weekly":
        raw = data.get("days_of_week") or []
        days = sorted({int(d) for d in raw if str(d).isdigit() and 0 <= int(d) <= 6})
        return {"days_of_week": days}
    if freq == "monthly":
        try:
            dom = int(data.get("day_of_month") or 1)
        except (TypeError, ValueError):
            dom = 1
        return {"day_of_month": max(1, min(31, dom))}
    return {}


def validate_recurrence_rule(frequency: str, rule: dict[str, Any] | None) -> str | None:
    freq = (frequency or "").strip().lower()
    if freq not in ("daily", "weekly", "monthly"):
        return "frequencia_invalida"
    norm = normalize_rule(freq, rule)
    if freq == "weekly" and not norm.get("days_of_week"):
        return "dias_semana_obrigatorios"
    if freq == "monthly" and not norm.get("day_of_month"):
        return "dia_mes_invalido"
    return None


def _date_matches_rule(local_day: date, frequency: str, rule: dict[str, Any]) -> bool:
    freq = (frequency or "").strip().lower()
    norm = normalize_rule(freq, rule)
    if freq == "daily":
        if norm.get("mode") == "weekdays":
            return local_day.weekday() < 5
        return True
    if freq == "weekly":
        return local_day.weekday() in set(norm.get("days_of_week") or [])
    if freq == "monthly":
        dom = int(norm.get("day_of_month") or 1)
        if dom > calendar.monthrange(local_day.year, local_day.month)[1]:
            return False
        return local_day.day == dom
    return False


def compute_occurrence_dates(
    *,
    frequency: str,
    rule: dict[str, Any],
    starts_on: date,
    ends_on: date | None,
    from_date: date,
    to_date: date,
) -> list[date]:
    """Datas locais de ocorrência no intervalo [from_date, to_date]."""
    start = max(starts_on, from_date)
    end = min(to_date, ends_on) if ends_on else to_date
    if end < start:
        return []
    out: list[date] = []
    cur = start
    while cur <= end:
        if _date_matches_rule(cur, frequency, rule):
            out.append(cur)
        cur += timedelta(days=1)
    return out


def occurrence_starts_at_utc(
    local_day: date,
    time_local: time,
    tz_name: str,
) -> datetime:
    tz = _get_tz(normalize_timezone(tz_name))
    local_dt = datetime.combine(local_day, time_local, tzinfo=tz)
    return local_dt.astimezone(timezone.utc)


def format_series_summary(series: dict[str, Any], tz_name: str | None = None) -> str:
    freq = str(series.get(SchedulingRecurrenceSeriesModel.FREQUENCY) or "")
    rule = series.get(SchedulingRecurrenceSeriesModel.RULE) or {}
    if not isinstance(rule, dict):
        rule = {}
    norm = normalize_rule(freq, rule)
    tl = _parse_time_local(series.get(SchedulingRecurrenceSeriesModel.TIME_LOCAL))
    time_txt = tl.strftime("%H:%M") if tl else "—"
    if freq == "daily":
        mode = norm.get("mode")
        when = "dias úteis" if mode == "weekdays" else "todos os dias"
        return f"{when} às {time_txt}"
    if freq == "weekly":
        days = norm.get("days_of_week") or []
        labels = [_WEEKDAY_LABELS[d] for d in days if 0 <= d < 7]
        return f"{', '.join(labels)} às {time_txt}"
    if freq == "monthly":
        dom = norm.get("day_of_month")
        return f"dia {dom} de cada mês às {time_txt}"
    return f"Recorrente às {time_txt}"


def _overlap(a0: datetime, a1: datetime, b0: datetime, b1: datetime) -> bool:
    return a0 < b1 and a1 > b0


def book_series_occurrence(
    *,
    cliente_id: str,
    series: dict[str, Any],
    local_day: date,
    duration_minutes: int,
    tz_name: str,
) -> tuple[dict[str, Any] | None, str | None]:
    from services.scheduling.motor_adapters import BookOccurrenceRequest, get_motor_adapter

    series_id = str(series.get(SchedulingRecurrenceSeriesModel.ID) or "")
    tl = _parse_time_local(series.get(SchedulingRecurrenceSeriesModel.TIME_LOCAL))
    if not tl:
        return None, "horario_invalido"
    starts_at = occurrence_starts_at_utc(local_day, tl, tz_name)
    occurrence_at = starts_at
    existing = repository.get_appointment_by_series_occurrence(series_id, occurrence_at)
    if existing and str(existing.get("status") or "") != "cancelled":
        return existing, None

    ends_at = starts_at + timedelta(minutes=max(1, int(duration_minutes or 30)))
    prof_id = series.get(SchedulingRecurrenceSeriesModel.PROFESSIONAL_ID)
    prof_id = str(prof_id) if prof_id else None

    contact_name = (series.get(SchedulingRecurrenceSeriesModel.CONTACT_NAME) or "").strip()
    contact_phone = (series.get(SchedulingRecurrenceSeriesModel.CONTACT_PHONE) or "").strip() or None
    notes = (series.get(SchedulingRecurrenceSeriesModel.NOTES) or "").strip() or None
    meta = dict(series.get(SchedulingRecurrenceSeriesModel.META) or {})
    meta.setdefault("source", "panel_recurrence")
    if contact_name:
        meta.setdefault("contact_name", contact_name)

    adapter = get_motor_adapter(cliente_id)
    result = adapter.book_occurrence(
        BookOccurrenceRequest(
            cliente_id=cliente_id,
            service_id=str(series.get(SchedulingRecurrenceSeriesModel.SERVICE_ID) or ""),
            professional_id=prof_id,
            starts_at=starts_at,
            ends_at=ends_at,
            contact_name=contact_name or "Cliente",
            contact_phone=contact_phone,
            notes=notes,
            status="confirmed",
            meta=meta,
            recurrence_series_id=series_id,
            series_occurrence_at=occurrence_at,
        )
    )
    if result.row:
        return result.row, None
    return None, result.error or "erro"


def expand_series(
    cliente_id: str,
    series_id: str,
    *,
    horizon_days: int = HORIZON_DAYS,
    tz_name: str | None = None,
) -> ExpansionResult:
    result = ExpansionResult()
    series = repository.get_recurrence_series(cliente_id, series_id)
    if not series:
        return result
    if str(series.get(SchedulingRecurrenceSeriesModel.STATUS) or "") != SERIES_ACTIVE:
        return result

    st = repository.get_settings(cliente_id) or {}
    tz = normalize_timezone(tz_name or str(st.get("timezone") or ""))
    local_today = datetime.now(timezone.utc).astimezone(_get_tz(tz)).date()

    starts_on = _parse_date(series.get(SchedulingRecurrenceSeriesModel.STARTS_ON))
    ends_on = _parse_date(series.get(SchedulingRecurrenceSeriesModel.ENDS_ON))
    if not starts_on:
        return result

    materialized_until = _parse_date(series.get(SchedulingRecurrenceSeriesModel.MATERIALIZED_UNTIL))
    from_date = max(starts_on, local_today)
    if materialized_until and materialized_until >= from_date:
        from_date = materialized_until + timedelta(days=1)

    target_end = local_today + timedelta(days=max(1, int(horizon_days)))
    if ends_on and ends_on < target_end:
        target_end = ends_on
    if target_end < from_date:
        return result

    svc = repository.get_service(cliente_id, str(series.get(SchedulingRecurrenceSeriesModel.SERVICE_ID) or ""))
    duration = int((svc or {}).get("duration_minutes") or 30)
    skips = repository.list_recurrence_skips(series_id)
    freq = str(series.get(SchedulingRecurrenceSeriesModel.FREQUENCY) or "")
    rule = series.get(SchedulingRecurrenceSeriesModel.RULE) or {}

    dates = compute_occurrence_dates(
        frequency=freq,
        rule=rule if isinstance(rule, dict) else {},
        starts_on=starts_on,
        ends_on=ends_on,
        from_date=from_date,
        to_date=target_end,
    )

    last_materialized: date | None = materialized_until
    for local_day in dates:
        day_key = local_day.isoformat()
        if day_key in skips:
            result.skipped_skip += 1
            continue
        occ_utc = occurrence_starts_at_utc(
            local_day,
            _parse_time_local(series.get(SchedulingRecurrenceSeriesModel.TIME_LOCAL)) or time(9, 0),
            tz,
        )
        existing = repository.get_appointment_by_series_occurrence(series_id, occ_utc)
        if existing and str(existing.get("status") or "") != "cancelled":
            result.skipped_existing += 1
            last_materialized = max(last_materialized or local_day, local_day)
            continue
        row, err = book_series_occurrence(
            cliente_id=cliente_id,
            series=series,
            local_day=local_day,
            duration_minutes=duration,
            tz_name=tz,
        )
        if row:
            result.created += 1
            meta = row.get("meta") if isinstance(row.get("meta"), dict) else {}
            if str(meta.get("motor_sync") or "") == "pending":
                result.sync_pending += 1
            elif str(meta.get("motor_sync") or "") in ("synced", "local_only", ""):
                result.synced += 1
            last_materialized = max(last_materialized or local_day, local_day)
        elif err == "slot_ocupado":
            result.skipped_conflict += 1
            result.conflicts.append(
                {"date": day_key, "reason": "slot_ocupado", "starts_at": occ_utc.isoformat()}
            )
        else:
            result.conflicts.append({"date": day_key, "reason": err or "erro"})

    if last_materialized:
        repository.update_recurrence_series(
            cliente_id,
            series_id,
            {SchedulingRecurrenceSeriesModel.MATERIALIZED_UNTIL: last_materialized.isoformat()},
        )
    return result


def _resolve_professional_for_series(
    cliente_id: str,
    service_id: str,
    professional_id: str | None,
) -> tuple[str | None, dict[str, Any]]:
    """Fixa profissional na série; usa auto_distribution se necessário."""
    meta: dict[str, Any] = {"source": "panel_recurrence"}
    if professional_id:
        return str(professional_id), meta

    from services.scheduling.assignment import (
        build_auto_booking_meta,
        order_candidates_for_assignment,
        uses_auto_distribution_for_panel,
    )
    from services.scheduling.eligible import eligible_professionals

    if not uses_auto_distribution_for_panel(cliente_id):
        return None, meta

    services = repository.list_services(cliente_id)
    profs = repository.list_professionals(cliente_id, active_only=True)
    eligible = eligible_professionals(services, profs, service_id)
    candidate_ids = [str(p.get("id") or "") for p in eligible]
    ordered = order_candidates_for_assignment(cliente_id, candidate_ids, professionals=profs)
    if not ordered:
        return None, meta
    meta.update(build_auto_booking_meta())
    return ordered[0], meta


def create_recurrence_series(
    *,
    cliente_id: str,
    service_id: str,
    professional_id: str | None,
    frequency: str,
    rule: dict[str, Any],
    time_local: time,
    starts_on: date,
    ends_on: date | None,
    contact_name: str,
    contact_phone: str | None = None,
    notes: str | None = None,
    horizon_days: int = HORIZON_DAYS,
) -> tuple[dict[str, Any] | None, ExpansionResult | None, str | None]:
    err_rule = validate_recurrence_rule(frequency, rule)
    if err_rule:
        return None, None, err_rule
    if ends_on and ends_on < starts_on:
        return None, None, "data_final_invalida"

    st = repository.get_settings(cliente_id) or {}
    tz = normalize_timezone(str(st.get("timezone") or ""))
    svc = repository.get_service(cliente_id, service_id)
    if not svc:
        return None, None, "servico_invalido"

    prof_id, meta = _resolve_professional_for_series(cliente_id, service_id, professional_id)

    now_iso = datetime.now(timezone.utc).isoformat()
    row = {
        SchedulingRecurrenceSeriesModel.CLIENTE_ID: str(cliente_id),
        SchedulingRecurrenceSeriesModel.SERVICE_ID: str(service_id),
        SchedulingRecurrenceSeriesModel.PROFESSIONAL_ID: prof_id,
        SchedulingRecurrenceSeriesModel.STATUS: SERIES_ACTIVE,
        SchedulingRecurrenceSeriesModel.FREQUENCY: frequency.strip().lower(),
        SchedulingRecurrenceSeriesModel.RULE: normalize_rule(frequency, rule),
        SchedulingRecurrenceSeriesModel.TIME_LOCAL: time_local.strftime("%H:%M:%S"),
        SchedulingRecurrenceSeriesModel.STARTS_ON: starts_on.isoformat(),
        SchedulingRecurrenceSeriesModel.ENDS_ON: ends_on.isoformat() if ends_on else None,
        SchedulingRecurrenceSeriesModel.CONTACT_NAME: (contact_name or "").strip(),
        SchedulingRecurrenceSeriesModel.CONTACT_PHONE: (contact_phone or "").strip() or None,
        SchedulingRecurrenceSeriesModel.NOTES: (notes or "").strip() or None,
        SchedulingRecurrenceSeriesModel.META: meta,
        SchedulingRecurrenceSeriesModel.MATERIALIZED_UNTIL: None,
        SchedulingRecurrenceSeriesModel.UPDATED_AT: now_iso,
    }
    series = repository.insert_recurrence_series(row)
    if not series:
        return None, None, "insert_falhou"

    series_id = str(series.get(SchedulingRecurrenceSeriesModel.ID) or "")
    expansion = expand_series(cliente_id, series_id, horizon_days=horizon_days, tz_name=tz)
    return series, expansion, None


def _sync_series_cancel_to_motor(
    cliente_id: str,
    series_id: str,
    *,
    scope: str,
    from_starts_at: datetime | None = None,
) -> None:
    from services.scheduling.motor_adapters import get_motor_adapter
    from services.scheduling.engine import scheduling_uses_internal_motor

    if scheduling_uses_internal_motor(cliente_id):
        return
    adapter = get_motor_adapter(cliente_id)
    from_iso = from_starts_at.isoformat() if from_starts_at else None
    rows = []
    if from_iso:
        rows = repository.list_series_appointments_from(cliente_id, series_id, from_iso)
    adapter.cancel_series_remote(
        cliente_id=cliente_id,
        series_id=series_id,
        scope=scope,
        from_starts_at=from_starts_at,
        appointment_rows=rows,
    )


def retry_pending_motor_sync(
    cliente_id: str | None = None,
    *,
    limit: int = 50,
) -> dict[str, int]:
    """Reenvia marcações com meta.motor_sync=pending ao Agendamento IA."""
    from services.agendamento_ia_book import create_appointment_in_agendamento_ia
    from services.scheduling.engine import scheduling_uses_internal_motor

    stats = {"attempted": 0, "synced": 0, "failed": 0}
    if cliente_id and scheduling_uses_internal_motor(cliente_id):
        return stats

    pending = repository.list_appointments_pending_motor_sync(cliente_id, limit=limit)
    for row in pending:
        cid = str(row.get("cliente_id") or "")
        aid = str(row.get("id") or "")
        if not cid or not aid:
            continue
        stats["attempted"] += 1
        meta = row.get("meta") if isinstance(row.get("meta"), dict) else {}
        zaid = str(meta.get("zapaction_appointment_id") or aid)
        starts = repository.parse_row_datetime(row.get("starts_at"))
        ends = repository.parse_row_datetime(row.get("ends_at"))
        if not starts or not ends:
            stats["failed"] += 1
            continue
        ext, err = create_appointment_in_agendamento_ia(
            cliente_id=cid,
            zapaction_appointment_id=zaid,
            service_id=str(row.get("service_id") or ""),
            provider_id=str(row.get("professional_id") or "") or None,
            starts_at=starts,
            ends_at=ends,
            contact_name=str(meta.get("contact_name") or "Cliente"),
            contact_phone=row.get("contact_phone"),
            notes=row.get("notes"),
            status=str(row.get("status") or "confirmed"),
            metadata=meta,
            recurrence_series_id=str(row.get("recurrence_series_id") or "") or None,
            series_occurrence_at=repository.parse_row_datetime(row.get("series_occurrence_at")),
        )
        if ext:
            repository.set_appointment_external_id(
                cid, aid, ext, meta_patch={"motor_sync": "synced", "motor_sync_error": None}
            )
            stats["synced"] += 1
        else:
            repository.merge_appointment_meta(
                cid, aid, {"motor_sync": "pending", "motor_sync_error": err or "retry_falhou"}
            )
            stats["failed"] += 1
    return stats


def pause_recurrence_series(cliente_id: str, series_id: str, *, tz_name: str | None = None) -> bool:
    series = repository.get_recurrence_series(cliente_id, series_id)
    if not series:
        return False
    st = repository.get_settings(cliente_id) or {}
    tz = normalize_timezone(tz_name or str(st.get("timezone") or ""))
    local_today = datetime.now(timezone.utc).astimezone(_get_tz(tz)).date()
    from_local = datetime.combine(local_today, time.min, tzinfo=_get_tz(tz))
    _sync_series_cancel_to_motor(
        cliente_id, series_id, scope="following", from_starts_at=from_local.astimezone(timezone.utc)
    )
    local_today_iso = local_today.isoformat()
    repository.cancel_series_appointments_from(cliente_id, series_id, local_today_iso, tz_name=tz)
    return repository.update_recurrence_series(
        cliente_id, series_id, {SchedulingRecurrenceSeriesModel.STATUS: SERIES_PAUSED}
    )


def resume_recurrence_series(
    cliente_id: str,
    series_id: str,
    *,
    horizon_days: int = HORIZON_DAYS,
    tz_name: str | None = None,
) -> ExpansionResult | None:
    series = repository.get_recurrence_series(cliente_id, series_id)
    if not series:
        return None
    repository.update_recurrence_series(
        cliente_id, series_id, {SchedulingRecurrenceSeriesModel.STATUS: SERIES_ACTIVE}
    )
    st = repository.get_settings(cliente_id) or {}
    tz = normalize_timezone(tz_name or str(st.get("timezone") or ""))
    return expand_series(cliente_id, series_id, horizon_days=horizon_days, tz_name=tz)


def end_recurrence_series(
    cliente_id: str,
    series_id: str,
    *,
    end_date: date | None = None,
    tz_name: str | None = None,
) -> bool:
    series = repository.get_recurrence_series(cliente_id, series_id)
    if not series:
        return False
    st = repository.get_settings(cliente_id) or {}
    tz = normalize_timezone(tz_name or str(st.get("timezone") or ""))
    local_today = datetime.now(timezone.utc).astimezone(_get_tz(tz)).date()
    ends = end_date or local_today
    cancel_from = (ends + timedelta(days=1)).isoformat() if ends >= local_today else local_today.isoformat()
    try:
        anchor = date.fromisoformat(cancel_from[:10])
        from_local = datetime.combine(anchor, time.min, tzinfo=_get_tz(tz))
        _sync_series_cancel_to_motor(
            cliente_id,
            series_id,
            scope="following",
            from_starts_at=from_local.astimezone(timezone.utc),
        )
    except ValueError:
        pass
    repository.cancel_series_appointments_from(cliente_id, series_id, cancel_from, tz_name=tz)
    patch = {
        SchedulingRecurrenceSeriesModel.STATUS: SERIES_ENDED,
        SchedulingRecurrenceSeriesModel.ENDS_ON: ends.isoformat(),
    }
    return repository.update_recurrence_series(cliente_id, series_id, patch)


def cancel_recurrence_scope(
    cliente_id: str,
    *,
    scope: str,
    series_id: str | None = None,
    appointment_id: str | None = None,
    from_local_date: str | None = None,
    tz_name: str | None = None,
) -> tuple[bool, str | None]:
    """scope: this_only | following | all"""
    scope = (scope or "this_only").strip().lower()
    st = repository.get_settings(cliente_id) or {}
    tz = normalize_timezone(tz_name or str(st.get("timezone") or ""))
    local_today = datetime.now(timezone.utc).astimezone(_get_tz(tz)).date()

    if scope == "this_only":
        if not appointment_id:
            return False, "appointment_obrigatorio"
        appt = repository.get_appointment(cliente_id, appointment_id)
        if not appt:
            return False, "nao_encontrado"
        sid = str(appt.get("recurrence_series_id") or series_id or "")
        if not sid:
            from services.scheduling.motor_adapters import get_motor_adapter

            adapter = get_motor_adapter(cliente_id)
            ok_cancel, cerr = adapter.cancel_appointment(cliente_id=cliente_id, local_row=appt)
            return ok_cancel, cerr
        starts = repository.parse_row_datetime(appt.get("series_occurrence_at") or appt.get("starts_at"))
        if starts:
            local = starts.astimezone(_get_tz(tz)).date().isoformat()
            repository.add_recurrence_skip(cliente_id, sid, local)
        from services.scheduling.motor_adapters import get_motor_adapter

        adapter = get_motor_adapter(cliente_id)
        ok_cancel, cerr = adapter.cancel_appointment(cliente_id=cliente_id, local_row=appt)
        if not ok_cancel and cerr:
            return False, cerr
        return True, None

    if not series_id:
        if appointment_id:
            appt = repository.get_appointment(cliente_id, appointment_id)
            series_id = str(appt.get("recurrence_series_id") or "") if appt else ""
        if not series_id:
            return False, "serie_obrigatoria"

    if scope == "following":
        anchor = from_local_date
        if not anchor and appointment_id:
            appt = repository.get_appointment(cliente_id, appointment_id)
            if appt:
                starts = repository.parse_row_datetime(appt.get("series_occurrence_at") or appt.get("starts_at"))
                if starts:
                    anchor = starts.astimezone(_get_tz(tz)).date().isoformat()
        if not anchor:
            anchor = local_today.isoformat()
        try:
            anchor_date = date.fromisoformat(anchor[:10])
            from_local = datetime.combine(anchor_date, time.min, tzinfo=_get_tz(tz))
            _sync_series_cancel_to_motor(
                cliente_id,
                series_id,
                scope="following",
                from_starts_at=from_local.astimezone(timezone.utc),
            )
        except ValueError:
            pass
        repository.cancel_series_appointments_from(cliente_id, series_id, anchor, tz_name=tz)
        try:
            end_prev = date.fromisoformat(anchor[:10]) - timedelta(days=1)
        except ValueError:
            end_prev = local_today
        repository.update_recurrence_series(
            cliente_id,
            series_id,
            {
                SchedulingRecurrenceSeriesModel.ENDS_ON: end_prev.isoformat(),
                SchedulingRecurrenceSeriesModel.STATUS: SERIES_ENDED,
            },
        )
        return True, None

    if scope == "all":
        _sync_series_cancel_to_motor(cliente_id, series_id, scope="all")
        repository.cancel_series_appointments_from(
            cliente_id, series_id, local_today.isoformat(), tz_name=tz
        )
        repository.update_recurrence_series(
            cliente_id,
            series_id,
            {
                SchedulingRecurrenceSeriesModel.STATUS: SERIES_ENDED,
                SchedulingRecurrenceSeriesModel.ENDS_ON: local_today.isoformat(),
            },
        )
        return True, None

    return False, "escopo_invalido"


def delete_recurrence_scope(
    cliente_id: str,
    *,
    scope: str,
    series_id: str | None = None,
    appointment_id: str | None = None,
    from_local_date: str | None = None,
    tz_name: str | None = None,
) -> tuple[bool, str | None]:
    """Remove ocorrências do painel. scope: this_only | following | all"""
    scope = (scope or "this_only").strip().lower()
    st = repository.get_settings(cliente_id) or {}
    tz = normalize_timezone(tz_name or str(st.get("timezone") or ""))
    local_today = datetime.now(timezone.utc).astimezone(_get_tz(tz)).date()

    def _delete_row(appt: dict[str, Any]) -> bool:
        from services.scheduling.panel_purge import purge_appointment_row

        ok, _err = purge_appointment_row(cliente_id, appt)
        return ok

    if scope == "this_only":
        if not appointment_id:
            return False, "appointment_obrigatorio"
        appt = repository.get_appointment(cliente_id, appointment_id)
        if not appt:
            return False, "nao_encontrado"
        sid = str(appt.get("recurrence_series_id") or series_id or "")
        if sid:
            starts = repository.parse_row_datetime(appt.get("series_occurrence_at") or appt.get("starts_at"))
            if starts:
                local = starts.astimezone(_get_tz(tz)).date().isoformat()
                repository.add_recurrence_skip(cliente_id, sid, local)
        if not _delete_row(appt):
            return False, "delete_falhou"
        return True, None

    if not series_id:
        if appointment_id:
            appt = repository.get_appointment(cliente_id, appointment_id)
            series_id = str(appt.get("recurrence_series_id") or "") if appt else ""
        if not series_id:
            return False, "serie_obrigatoria"

    if scope == "following":
        anchor = from_local_date
        if not anchor and appointment_id:
            appt = repository.get_appointment(cliente_id, appointment_id)
            if appt:
                starts = repository.parse_row_datetime(appt.get("series_occurrence_at") or appt.get("starts_at"))
                if starts:
                    anchor = starts.astimezone(_get_tz(tz)).date().isoformat()
        if not anchor:
            anchor = local_today.isoformat()
        try:
            anchor_date = date.fromisoformat(anchor[:10])
            from_local = datetime.combine(anchor_date, time.min, tzinfo=_get_tz(tz))
            _sync_series_cancel_to_motor(
                cliente_id,
                series_id,
                scope="following",
                from_starts_at=from_local.astimezone(timezone.utc),
            )
        except ValueError:
            pass
        deleted = repository.delete_series_appointments_from(
            cliente_id, series_id, anchor, tz_name=tz
        )
        if deleted == 0 and appointment_id:
            appt = repository.get_appointment(cliente_id, appointment_id)
            if appt:
                _delete_row(appt)
        try:
            end_prev = date.fromisoformat(anchor[:10]) - timedelta(days=1)
        except ValueError:
            end_prev = local_today
        repository.update_recurrence_series(
            cliente_id,
            series_id,
            {
                SchedulingRecurrenceSeriesModel.ENDS_ON: end_prev.isoformat(),
                SchedulingRecurrenceSeriesModel.STATUS: SERIES_ENDED,
            },
        )
        return True, None

    if scope == "all":
        try:
            _sync_series_cancel_to_motor(cliente_id, series_id, scope="all")
            repository.delete_all_series_appointments(cliente_id, series_id)
            repository.update_recurrence_series(
                cliente_id,
                series_id,
                {
                    SchedulingRecurrenceSeriesModel.STATUS: SERIES_ENDED,
                    SchedulingRecurrenceSeriesModel.ENDS_ON: local_today.isoformat(),
                },
            )
        except Exception:
            logger.exception(
                "delete_recurrence_scope all failed cliente_id=%s series_id=%s",
                cliente_id[:8],
                series_id[:8],
            )
            return False, "delete_falhou"
        return True, None

    return False, "escopo_invalido"


def reschedule_recurrence_scope(
    cliente_id: str,
    appointment_id: str,
    new_starts_at: datetime,
    duration_minutes: int,
    *,
    professional_id: str | None = None,
    scope: str = "this_only",
) -> tuple[bool, str | None]:
    """Remarca ocorrência única ou altera horário da série (following/all)."""
    from services.scheduling.bookings import reschedule_appointment

    scope = (scope or "this_only").strip().lower()
    appt = repository.get_appointment(cliente_id, appointment_id)
    if not appt:
        return False, "nao_encontrado"
    sid = str(appt.get("recurrence_series_id") or "")
    if not sid or scope == "this_only":
        ok, err, _swap = reschedule_appointment(
            cliente_id=cliente_id,
            appointment_id=appointment_id,
            new_starts_at=new_starts_at,
            duration_minutes=duration_minutes,
            professional_id=professional_id,
        )
        return ok, err

    st = repository.get_settings(cliente_id) or {}
    tz = normalize_timezone(str(st.get("timezone") or ""))
    local_start = new_starts_at.astimezone(_get_tz(tz))
    new_time = local_start.time().replace(second=0, microsecond=0)

    _updated, expansion, err = apply_series_edit(
        cliente_id,
        sid,
        scope=scope,
        appointment_id=appointment_id,
        time_local=new_time,
        professional_id=professional_id,
    )
    if err:
        return False, err

    ok, rerr, _swap = reschedule_appointment(
        cliente_id=cliente_id,
        appointment_id=appointment_id,
        new_starts_at=new_starts_at,
        duration_minutes=duration_minutes,
        professional_id=professional_id,
    )
    return ok, rerr


def apply_series_edit(
    cliente_id: str,
    series_id: str,
    *,
    scope: str,
    appointment_id: str | None = None,
    from_local_date: str | None = None,
    frequency: str | None = None,
    rule: dict[str, Any] | None = None,
    time_local: time | None = None,
    professional_id: str | None = None,
    contact_name: str | None = None,
    contact_phone: str | None = None,
    notes: str | None = None,
    ends_on: date | None = None,
    no_end_date: bool = False,
    horizon_days: int = HORIZON_DAYS,
) -> tuple[dict[str, Any] | None, ExpansionResult | None, str | None]:
    scope = (scope or "all").strip().lower()
    series = repository.get_recurrence_series(cliente_id, series_id)
    if not series:
        return None, None, "nao_encontrado"

    st = repository.get_settings(cliente_id) or {}
    tz = normalize_timezone(str(st.get("timezone") or ""))

    if scope == "this_only":
        if not appointment_id:
            return None, None, "appointment_obrigatorio"
        appt_patch: dict[str, Any] = {SchedulingAppointmentModel.IS_SERIES_EXCEPTION: True}
        if professional_id is not None:
            appt_patch[SchedulingAppointmentModel.PROFESSIONAL_ID] = professional_id or None
        if notes is not None:
            appt_patch[SchedulingAppointmentModel.NOTES] = notes
        if contact_phone is not None:
            appt_patch[SchedulingAppointmentModel.CONTACT_PHONE] = contact_phone or None
        if not supabase_update_appointment(cliente_id, appointment_id, appt_patch):
            return None, None, "update_falhou"
        if contact_name:
            repository.merge_appointment_meta(cliente_id, appointment_id, {"contact_name": contact_name})
        repository.merge_appointment_meta(cliente_id, appointment_id, {"series_exception": True})
        updated = repository.get_appointment(cliente_id, appointment_id)
        return updated, None, None

    new_freq = (frequency or series.get(SchedulingRecurrenceSeriesModel.FREQUENCY) or "").strip().lower()
    new_rule = normalize_rule(new_freq, rule if rule is not None else series.get(SchedulingRecurrenceSeriesModel.RULE))
    err = validate_recurrence_rule(new_freq, new_rule)
    if err:
        return None, None, err

    tl = time_local or _parse_time_local(series.get(SchedulingRecurrenceSeriesModel.TIME_LOCAL))
    if not tl:
        return None, None, "horario_invalido"

    if scope == "following":
        anchor = from_local_date
        if not anchor and appointment_id:
            appt = repository.get_appointment(cliente_id, appointment_id)
            if appt:
                starts = repository.parse_row_datetime(appt.get("series_occurrence_at") or appt.get("starts_at"))
                if starts:
                    anchor = starts.astimezone(_get_tz(tz)).date().isoformat()
        if not anchor:
            return None, None, "data_obrigatoria"
        try:
            split_date = date.fromisoformat(anchor[:10])
        except ValueError:
            return None, None, "data_invalida"
        end_prev = split_date - timedelta(days=1)
        repository.update_recurrence_series(
            cliente_id,
            series_id,
            {
                SchedulingRecurrenceSeriesModel.ENDS_ON: end_prev.isoformat(),
                SchedulingRecurrenceSeriesModel.STATUS: SERIES_ENDED,
            },
        )
        repository.cancel_series_appointments_from(cliente_id, series_id, anchor, tz_name=tz)
        new_series, expansion, cerr = create_recurrence_series(
            cliente_id=cliente_id,
            service_id=str(series.get(SchedulingRecurrenceSeriesModel.SERVICE_ID) or ""),
            professional_id=professional_id or str(series.get(SchedulingRecurrenceSeriesModel.PROFESSIONAL_ID) or "") or None,
            frequency=new_freq,
            rule=new_rule,
            time_local=tl,
            starts_on=split_date,
            ends_on=None if no_end_date else (ends_on or _parse_date(series.get(SchedulingRecurrenceSeriesModel.ENDS_ON))),
            contact_name=contact_name or str(series.get(SchedulingRecurrenceSeriesModel.CONTACT_NAME) or ""),
            contact_phone=contact_phone if contact_phone is not None else series.get(SchedulingRecurrenceSeriesModel.CONTACT_PHONE),
            notes=notes if notes is not None else series.get(SchedulingRecurrenceSeriesModel.NOTES),
            horizon_days=horizon_days,
        )
        return new_series, expansion, cerr

    # scope == all
    local_today = datetime.now(timezone.utc).astimezone(_get_tz(tz)).date()
    repository.cancel_series_appointments_from(
        cliente_id, series_id, local_today.isoformat(), tz_name=tz
    )
    patch_series = {
        SchedulingRecurrenceSeriesModel.FREQUENCY: new_freq,
        SchedulingRecurrenceSeriesModel.RULE: new_rule,
        SchedulingRecurrenceSeriesModel.TIME_LOCAL: tl.strftime("%H:%M:%S"),
        SchedulingRecurrenceSeriesModel.STATUS: SERIES_ACTIVE,
        SchedulingRecurrenceSeriesModel.MATERIALIZED_UNTIL: None,
    }
    if professional_id is not None:
        patch_series[SchedulingRecurrenceSeriesModel.PROFESSIONAL_ID] = professional_id or None
    if contact_name is not None:
        patch_series[SchedulingRecurrenceSeriesModel.CONTACT_NAME] = contact_name
    if contact_phone is not None:
        patch_series[SchedulingRecurrenceSeriesModel.CONTACT_PHONE] = contact_phone or None
    if notes is not None:
        patch_series[SchedulingRecurrenceSeriesModel.NOTES] = notes or None
    if no_end_date:
        patch_series[SchedulingRecurrenceSeriesModel.ENDS_ON] = None
    elif ends_on is not None:
        patch_series[SchedulingRecurrenceSeriesModel.ENDS_ON] = ends_on.isoformat()
    repository.update_recurrence_series(cliente_id, series_id, patch_series)
    expansion = expand_series(cliente_id, series_id, horizon_days=horizon_days, tz_name=tz)
    updated = repository.get_recurrence_series(cliente_id, series_id)
    return updated, expansion, None


def supabase_update_appointment(cliente_id: str, appointment_id: str, patch: dict[str, Any]) -> bool:
    from database.supabase_sq import supabase

    if not supabase:
        return False
    data = dict(patch)
    data[SchedulingAppointmentModel.UPDATED_AT] = datetime.now(timezone.utc).isoformat()
    supabase.table(Tables.SCHEDULING_APPOINTMENTS).update(data).eq(
        SchedulingAppointmentModel.ID, str(appointment_id)
    ).eq(SchedulingAppointmentModel.CLIENTE_ID, str(cliente_id)).execute()
    return True


def notify_recurrence_series_summary(cliente_id: str, series: dict[str, Any]) -> tuple[bool, str | None]:
    """WhatsApp resumo opcional na criação da série."""
    phone = (series.get(SchedulingRecurrenceSeriesModel.CONTACT_PHONE) or "").strip()
    if not phone:
        return False, "Telefone do cliente não informado."
    try:
        from services.scheduling.confirmation_notify import send_scheduling_whatsapp_text
        from services.scheduling.client_calendar_invite import (
            build_calendar_invite_append_for_row,
            client_calendar_invites_enabled,
        )

        st = repository.get_settings(cliente_id) or {}
        tz = normalize_timezone(str(st.get("timezone") or ""))
        summary = format_series_summary(series, tz)
        starts = _parse_date(series.get(SchedulingRecurrenceSeriesModel.STARTS_ON))
        starts_txt = starts.strftime("%d/%m/%Y") if starts else ""
        name = (series.get(SchedulingRecurrenceSeriesModel.CONTACT_NAME) or "").strip() or "Cliente"
        msg = (
            f"Olá {name}! Sua série de consultas foi agendada: {summary}, "
            f"a partir de {starts_txt}. Qualquer dúvida, responda esta mensagem."
        )
        series_id = str(series.get(SchedulingRecurrenceSeriesModel.ID) or "")
        if client_calendar_invites_enabled() and series_id and starts:
            first_rows = repository.list_series_appointments_from_date(
                cliente_id,
                series_id,
                starts.isoformat(),
            )
            if first_rows:
                calendar_append = build_calendar_invite_append_for_row(cliente_id, first_rows[0])
                if calendar_append:
                    msg += calendar_append
                    first_id = str(first_rows[0].get("id") or "")
                    if first_id:
                        from services.scheduling.display import parse_iso_datetime

                        starts_key = ""
                        parsed = parse_iso_datetime(first_rows[0].get("starts_at"))
                        if parsed:
                            starts_key = parsed.astimezone(timezone.utc).isoformat()
                        repository.merge_appointment_meta(
                            cliente_id,
                            first_id,
                            {
                                "calendar_invite_sent_at": datetime.now(timezone.utc).isoformat(),
                                "calendar_invite_for_starts_at": starts_key,
                                "calendar_invite_via": "recurrence_summary",
                            },
                        )
        return send_scheduling_whatsapp_text(cliente_id, phone, msg)
    except Exception:
        logger.exception("notify_recurrence_series_summary failed cliente_id=%s", cliente_id[:8])
        return False, "Erro interno ao enviar WhatsApp."
