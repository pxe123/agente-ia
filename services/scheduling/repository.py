"""
Acesso Supabase ao domínio de agenda (service role).
"""
from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone
from typing import Any

from database.models import (
    Tables,
    SchedulingAppointmentModel,
    SchedulingAppointmentProposalModel,
    SchedulingBlockedTimeModel,
    SchedulingConfirmationTokenModel,
    SchedulingProfessionalModel,
    SchedulingRecurrenceSeriesModel,
    SchedulingRecurrenceSkipModel,
    SchedulingServiceModel,
    SchedulingSettingsModel,
    SchedulingWorkingHoursModel,
)
from database.supabase_sq import supabase


def supabase_available() -> bool:
    return supabase is not None


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def get_settings(cliente_id: str) -> dict[str, Any] | None:
    if not supabase:
        return None
    r = (
        supabase.table(Tables.SCHEDULING_SETTINGS)
        .select("*")
        .eq(SchedulingSettingsModel.CLIENTE_ID, str(cliente_id))
        .limit(1)
        .execute()
    )
    rows = r.data or []
    return dict(rows[0]) if rows else None


def ensure_settings(cliente_id: str) -> dict[str, Any]:
    if not supabase:
        return {}
    existing = get_settings(cliente_id)
    if existing:
        return existing
    row = {
        SchedulingSettingsModel.CLIENTE_ID: str(cliente_id),
        SchedulingSettingsModel.TIMEZONE: "America/Sao_Paulo",
        SchedulingSettingsModel.PUBLIC_NAME: None,
        SchedulingSettingsModel.PUBLIC_SLUG: None,
        SchedulingSettingsModel.SCHEDULING_ENGINE: "agendamento_ia",
    }
    supabase.table(Tables.SCHEDULING_SETTINGS).insert(row).execute()
    return get_settings(cliente_id) or row


def get_scheduling_engine(cliente_id: str) -> str | None:
    """None se não existir linha em scheduling_settings."""
    if not supabase:
        return None
    r = (
        supabase.table(Tables.SCHEDULING_SETTINGS)
        .select(SchedulingSettingsModel.SCHEDULING_ENGINE)
        .eq(SchedulingSettingsModel.CLIENTE_ID, str(cliente_id))
        .limit(1)
        .execute()
    )
    rows = r.data or []
    if not rows:
        return None
    eng = (rows[0].get(SchedulingSettingsModel.SCHEDULING_ENGINE) or "").strip().lower()
    if eng in ("agendamento_ia", "zapaction_internal"):
        return eng
    return "agendamento_ia"


def set_scheduling_engine(
    cliente_id: str,
    engine: str,
    *,
    changed_by: str | None = None,
) -> dict[str, Any]:
    if not supabase:
        return {}
    cid = str(cliente_id)
    eng = (engine or "agendamento_ia").strip().lower()
    if eng not in ("agendamento_ia", "zapaction_internal"):
        eng = "agendamento_ia"
    now = _now_iso()
    payload = {
        SchedulingSettingsModel.SCHEDULING_ENGINE: eng,
        SchedulingSettingsModel.SCHEDULING_ENGINE_CHANGED_AT: now,
        SchedulingSettingsModel.SCHEDULING_ENGINE_CHANGED_BY: changed_by,
        SchedulingSettingsModel.UPDATED_AT: now,
    }
    existing = get_settings(cid)
    if existing:
        supabase.table(Tables.SCHEDULING_SETTINGS).update(payload).eq(
            SchedulingSettingsModel.CLIENTE_ID, cid
        ).execute()
    else:
        payload.update(
            {
                SchedulingSettingsModel.CLIENTE_ID: cid,
                SchedulingSettingsModel.TIMEZONE: "America/Sao_Paulo",
                SchedulingSettingsModel.PUBLIC_NAME: None,
                SchedulingSettingsModel.PUBLIC_SLUG: None,
            }
        )
        supabase.table(Tables.SCHEDULING_SETTINGS).insert(payload).execute()
    return get_settings(cid) or payload


VALID_ASSIGNMENT_MODES = frozenset({"manual", "auto_distribution"})
VALID_DISTRIBUTION_STRATEGIES = frozenset({"round_robin", "least_busy"})
VALID_CONFIRMATION_POLICIES = frozenset({"auto", "professional", "reception"})


def get_assignment_mode(cliente_id: str) -> str:
    """manual | auto_distribution. Default manual se ausente."""
    st = get_settings(cliente_id) or {}
    mode = (st.get(SchedulingSettingsModel.PROFESSIONAL_ASSIGNMENT_MODE) or "manual").strip().lower()
    return mode if mode in VALID_ASSIGNMENT_MODES else "manual"


def get_distribution_strategy(cliente_id: str) -> str:
    st = get_settings(cliente_id) or {}
    strat = (st.get(SchedulingSettingsModel.DISTRIBUTION_STRATEGY) or "round_robin").strip().lower()
    return strat if strat in VALID_DISTRIBUTION_STRATEGIES else "round_robin"


def get_distribution_cursor(cliente_id: str) -> str | None:
    st = get_settings(cliente_id) or {}
    raw = st.get(SchedulingSettingsModel.DISTRIBUTION_LAST_PROFESSIONAL_ID)
    return str(raw) if raw else None


def set_distribution_cursor(cliente_id: str, professional_id: str | None) -> None:
    if not supabase:
        return
    supabase.table(Tables.SCHEDULING_SETTINGS).update(
        {
            SchedulingSettingsModel.DISTRIBUTION_LAST_PROFESSIONAL_ID: professional_id or None,
            SchedulingSettingsModel.UPDATED_AT: _now_iso(),
        }
    ).eq(SchedulingSettingsModel.CLIENTE_ID, str(cliente_id)).execute()


def set_assignment_mode(
    cliente_id: str,
    mode: str,
    *,
    strategy: str | None = None,
    changed_by: str | None = None,
) -> dict[str, Any]:
    if not supabase:
        return {}
    cid = str(cliente_id)
    m = (mode or "manual").strip().lower()
    if m not in VALID_ASSIGNMENT_MODES:
        m = "manual"
    strat = (strategy or get_distribution_strategy(cid)).strip().lower()
    if strat not in VALID_DISTRIBUTION_STRATEGIES:
        strat = "round_robin"
    now = _now_iso()
    payload = {
        SchedulingSettingsModel.PROFESSIONAL_ASSIGNMENT_MODE: m,
        SchedulingSettingsModel.DISTRIBUTION_STRATEGY: strat,
        SchedulingSettingsModel.ASSIGNMENT_MODE_CHANGED_AT: now,
        SchedulingSettingsModel.ASSIGNMENT_MODE_CHANGED_BY: changed_by,
        SchedulingSettingsModel.UPDATED_AT: now,
    }
    if m == "manual":
        payload[SchedulingSettingsModel.DISTRIBUTION_LAST_PROFESSIONAL_ID] = None
    existing = get_settings(cid)
    if existing:
        supabase.table(Tables.SCHEDULING_SETTINGS).update(payload).eq(
            SchedulingSettingsModel.CLIENTE_ID, cid
        ).execute()
    else:
        payload.update(
            {
                SchedulingSettingsModel.CLIENTE_ID: cid,
                SchedulingSettingsModel.TIMEZONE: "America/Sao_Paulo",
                SchedulingSettingsModel.SCHEDULING_ENGINE: "agendamento_ia",
            }
        )
        supabase.table(Tables.SCHEDULING_SETTINGS).insert(payload).execute()
    return get_settings(cid) or payload


def get_confirmation_policy(cliente_id: str) -> str:
    st = get_settings(cliente_id) or {}
    mode = (st.get(SchedulingSettingsModel.CONFIRMATION_POLICY) or "auto").strip().lower()
    return mode if mode in VALID_CONFIRMATION_POLICIES else "auto"


def get_confirmation_pending_ttl_hours(cliente_id: str) -> int:
    st = get_settings(cliente_id) or {}
    try:
        ttl = int(st.get(SchedulingSettingsModel.CONFIRMATION_PENDING_TTL_HOURS) or 48)
    except (TypeError, ValueError):
        ttl = 48
    return max(1, min(ttl, 720))


def set_confirmation_policy(
    cliente_id: str,
    policy: str,
    *,
    ttl_hours: int | None = None,
    changed_by: str | None = None,
) -> dict[str, Any]:
    if not supabase:
        return {}
    cid = str(cliente_id)
    p = (policy or "auto").strip().lower()
    if p not in VALID_CONFIRMATION_POLICIES:
        p = "auto"
    if p == "reception":
        p = "auto"
    ttl = get_confirmation_pending_ttl_hours(cid) if ttl_hours is None else max(1, min(int(ttl_hours), 720))
    now = _now_iso()
    payload = {
        SchedulingSettingsModel.CONFIRMATION_POLICY: p,
        SchedulingSettingsModel.CONFIRMATION_PENDING_TTL_HOURS: ttl,
        SchedulingSettingsModel.CONFIRMATION_POLICY_CHANGED_AT: now,
        SchedulingSettingsModel.CONFIRMATION_POLICY_CHANGED_BY: changed_by,
        SchedulingSettingsModel.UPDATED_AT: now,
    }
    existing = get_settings(cid)
    if existing:
        supabase.table(Tables.SCHEDULING_SETTINGS).update(payload).eq(
            SchedulingSettingsModel.CLIENTE_ID, cid
        ).execute()
    else:
        payload.update(
            {
                SchedulingSettingsModel.CLIENTE_ID: cid,
                SchedulingSettingsModel.TIMEZONE: "America/Sao_Paulo",
                SchedulingSettingsModel.SCHEDULING_ENGINE: "agendamento_ia",
            }
        )
        supabase.table(Tables.SCHEDULING_SETTINGS).insert(payload).execute()
    return get_settings(cid) or payload


def update_professional_whatsapp_notify(
    cliente_id: str, professional_id: str, phone: str | None
) -> bool:
    if not supabase:
        return False
    supabase.table(Tables.SCHEDULING_PROFESSIONALS).update(
        {
            SchedulingProfessionalModel.WHATSAPP_NOTIFY_PHONE: (phone or None),
            SchedulingProfessionalModel.UPDATED_AT: _now_iso(),
        }
    ).eq(SchedulingProfessionalModel.ID, str(professional_id)).eq(
        SchedulingProfessionalModel.CLIENTE_ID, str(cliente_id)
    ).execute()
    return True


def insert_proposal(
    *,
    cliente_id: str,
    appointment_id: str,
    proposed_starts_at: datetime,
    proposed_ends_at: datetime,
    proposed_by: str,
) -> dict[str, Any] | None:
    if not supabase:
        return None
    row = {
        SchedulingAppointmentProposalModel.APPOINTMENT_ID: str(appointment_id),
        SchedulingAppointmentProposalModel.CLIENTE_ID: str(cliente_id),
        SchedulingAppointmentProposalModel.PROPOSED_STARTS_AT: proposed_starts_at.astimezone(
            timezone.utc
        ).isoformat(),
        SchedulingAppointmentProposalModel.PROPOSED_ENDS_AT: proposed_ends_at.astimezone(
            timezone.utc
        ).isoformat(),
        SchedulingAppointmentProposalModel.PROPOSED_BY: proposed_by,
        SchedulingAppointmentProposalModel.STATUS: "open",
    }
    r = supabase.table(Tables.SCHEDULING_APPOINTMENT_PROPOSALS).insert(row).execute()
    rows = r.data or []
    return dict(rows[0]) if rows else None


def get_proposal(cliente_id: str, proposal_id: str) -> dict[str, Any] | None:
    if not supabase:
        return None
    r = (
        supabase.table(Tables.SCHEDULING_APPOINTMENT_PROPOSALS)
        .select("*")
        .eq(SchedulingAppointmentProposalModel.ID, str(proposal_id))
        .eq(SchedulingAppointmentProposalModel.CLIENTE_ID, str(cliente_id))
        .limit(1)
        .execute()
    )
    rows = r.data or []
    return dict(rows[0]) if rows else None


def update_proposal_status(cliente_id: str, proposal_id: str, status: str) -> bool:
    if not supabase:
        return False
    supabase.table(Tables.SCHEDULING_APPOINTMENT_PROPOSALS).update(
        {SchedulingAppointmentProposalModel.STATUS: status}
    ).eq(SchedulingAppointmentProposalModel.ID, str(proposal_id)).eq(
        SchedulingAppointmentProposalModel.CLIENTE_ID, str(cliente_id)
    ).execute()
    return True


def supersede_open_proposals(cliente_id: str, appointment_id: str) -> None:
    if not supabase:
        return
    supabase.table(Tables.SCHEDULING_APPOINTMENT_PROPOSALS).update(
        {SchedulingAppointmentProposalModel.STATUS: "superseded"}
    ).eq(SchedulingAppointmentProposalModel.APPOINTMENT_ID, str(appointment_id)).eq(
        SchedulingAppointmentProposalModel.CLIENTE_ID, str(cliente_id)
    ).eq(SchedulingAppointmentProposalModel.STATUS, "open").execute()


def insert_confirmation_token(
    *,
    token_hash: str,
    cliente_id: str,
    appointment_id: str,
    action: str,
    expires_at: datetime,
    proposal_id: str | None = None,
) -> dict[str, Any] | None:
    if not supabase:
        return None
    row = {
        SchedulingConfirmationTokenModel.TOKEN_HASH: token_hash,
        SchedulingConfirmationTokenModel.APPOINTMENT_ID: str(appointment_id),
        SchedulingConfirmationTokenModel.CLIENTE_ID: str(cliente_id),
        SchedulingConfirmationTokenModel.ACTION: action,
        SchedulingConfirmationTokenModel.EXPIRES_AT: expires_at.astimezone(timezone.utc).isoformat(),
        SchedulingConfirmationTokenModel.PROPOSAL_ID: str(proposal_id) if proposal_id else None,
    }
    r = supabase.table(Tables.SCHEDULING_CONFIRMATION_TOKENS).insert(row).execute()
    rows = r.data or []
    return dict(rows[0]) if rows else None


def get_confirmation_token_by_hash(token_hash: str) -> dict[str, Any] | None:
    if not supabase:
        return None
    r = (
        supabase.table(Tables.SCHEDULING_CONFIRMATION_TOKENS)
        .select("*")
        .eq(SchedulingConfirmationTokenModel.TOKEN_HASH, token_hash)
        .limit(1)
        .execute()
    )
    rows = r.data or []
    return dict(rows[0]) if rows else None


def mark_confirmation_token_used(token_id: str) -> bool:
    if not supabase:
        return False
    supabase.table(Tables.SCHEDULING_CONFIRMATION_TOKENS).update(
        {SchedulingConfirmationTokenModel.USED_AT: _now_iso()}
    ).eq(SchedulingConfirmationTokenModel.ID, str(token_id)).execute()
    return True


def list_expired_pending_appointments(*, limit: int = 200) -> list[dict[str, Any]]:
    """Marcações pending cuja idade excede TTL do tenant."""
    if not supabase:
        return []
    now = datetime.now(timezone.utc)
    r = (
        supabase.table(Tables.SCHEDULING_APPOINTMENTS)
        .select("*")
        .eq(SchedulingAppointmentModel.STATUS, "pending")
        .limit(limit)
        .execute()
    )
    out: list[dict[str, Any]] = []
    for row in r.data or []:
        cid = str(row.get(SchedulingAppointmentModel.CLIENTE_ID) or "")
        created_raw = row.get(SchedulingAppointmentModel.CREATED_AT) or row.get("created_at")
        if not created_raw:
            continue
        try:
            created = datetime.fromisoformat(str(created_raw).replace("Z", "+00:00"))
            if created.tzinfo is None:
                created = created.replace(tzinfo=timezone.utc)
        except Exception:
            continue
        ttl_h = get_confirmation_pending_ttl_hours(cid)
        if created + timedelta(hours=ttl_h) <= now:
            out.append(dict(row))
    return out


def update_appointment_professional(
    cliente_id: str,
    appointment_id: str,
    professional_id: str,
    *,
    meta_patch: dict[str, Any] | None = None,
) -> bool:
    if not supabase:
        return False
    row = get_appointment(cliente_id, appointment_id)
    if not row:
        return False
    meta = row.get(SchedulingAppointmentModel.META) or {}
    if isinstance(meta, str):
        meta = {}
    if not isinstance(meta, dict):
        meta = {}
    if meta_patch:
        meta = {**meta, **meta_patch}
    supabase.table(Tables.SCHEDULING_APPOINTMENTS).update(
        {
            SchedulingAppointmentModel.PROFESSIONAL_ID: str(professional_id),
            SchedulingAppointmentModel.META: meta,
            SchedulingAppointmentModel.UPDATED_AT: _now_iso(),
        }
    ).eq(SchedulingAppointmentModel.ID, str(appointment_id)).eq(
        SchedulingAppointmentModel.CLIENTE_ID, str(cliente_id)
    ).execute()
    return True


def list_professionals(cliente_id: str, active_only: bool = True) -> list[dict[str, Any]]:
    if not supabase:
        return []
    q = (
        supabase.table(Tables.SCHEDULING_PROFESSIONALS)
        .select("*")
        .eq(SchedulingProfessionalModel.CLIENTE_ID, str(cliente_id))
        .order(SchedulingProfessionalModel.SORT_ORDER)
    )
    if active_only:
        q = q.eq(SchedulingProfessionalModel.ACTIVE, True)
    return q.execute().data or []


def list_services(cliente_id: str, active_only: bool = True) -> list[dict[str, Any]]:
    if not supabase:
        return []
    q = (
        supabase.table(Tables.SCHEDULING_SERVICES)
        .select("*")
        .eq(SchedulingServiceModel.CLIENTE_ID, str(cliente_id))
        .order(SchedulingServiceModel.SORT_ORDER)
    )
    if active_only:
        q = q.eq(SchedulingServiceModel.ACTIVE, True)
    return q.execute().data or []


def list_working_hours_all(cliente_id: str) -> list[dict[str, Any]]:
    if not supabase:
        return []
    return (
        supabase.table(Tables.SCHEDULING_WORKING_HOURS)
        .select("*")
        .eq(SchedulingWorkingHoursModel.CLIENTE_ID, str(cliente_id))
        .execute()
        .data
        or []
    )


def _parse_appointment_dt(value: Any) -> datetime | None:
    if value is None:
        return None
    try:
        dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def _normalize_booking_phone_key(phone: str | None) -> str:
    """Chave comparável para contact_phone / remote_id."""
    from services.contact_identity import normalize_whatsapp_phone

    raw = "".join(c for c in str(phone or "") if c.isdigit())
    if not raw:
        return ""
    norm = normalize_whatsapp_phone(raw) or normalize_whatsapp_phone(f"55{raw}")
    return norm or raw


def find_existing_booking_for_contact(
    cliente_id: str,
    service_id: str,
    starts_at_utc: datetime,
    *,
    contact_phone: str | None = None,
    remote_id: str | None = None,
) -> dict[str, Any] | None:
    """Marcação activa para o mesmo contacto, serviço e horário (idempotência)."""
    if not supabase:
        return None
    phone_key = _normalize_booking_phone_key(contact_phone) or _normalize_booking_phone_key(remote_id)
    if not phone_key:
        return None
    target = starts_at_utc.astimezone(timezone.utc)
    probe_end = target + timedelta(seconds=1)
    rows = (
        supabase.table(Tables.SCHEDULING_APPOINTMENTS)
        .select("*")
        .eq(SchedulingAppointmentModel.CLIENTE_ID, str(cliente_id))
        .eq(SchedulingAppointmentModel.SERVICE_ID, str(service_id))
        .lt(SchedulingAppointmentModel.STARTS_AT, probe_end.isoformat())
        .gt(SchedulingAppointmentModel.ENDS_AT, target.isoformat())
        .neq(SchedulingAppointmentModel.STATUS, "cancelled")
        .execute()
        .data
        or []
    )
    for row in rows:
        s = _parse_appointment_dt(row.get("starts_at"))
        if not s or abs((s.astimezone(timezone.utc) - target).total_seconds()) >= 1:
            continue
        row_key = _normalize_booking_phone_key(row.get("contact_phone")) or _normalize_booking_phone_key(
            row.get("remote_id")
        )
        if row_key and row_key == phone_key:
            return dict(row)
    return None


def find_appointment_at_exact_starts(
    cliente_id: str,
    professional_id: str,
    starts_at_utc: datetime,
    *,
    exclude_appointment_id: str | None = None,
) -> dict[str, Any] | None:
    """Marcação activa no profissional com starts_at exacto (UTC)."""
    target = starts_at_utc.astimezone(timezone.utc)
    end_probe = target + timedelta(seconds=1)
    rows = find_overlapping_appointments(
        cliente_id,
        professional_id,
        target,
        end_probe,
        exclude_appointment_id=exclude_appointment_id,
    )
    matches: list[dict[str, Any]] = []
    for row in rows:
        s = _parse_appointment_dt(row.get("starts_at"))
        if s and abs((s.astimezone(timezone.utc) - target).total_seconds()) < 1:
            matches.append(row)
    if len(matches) != 1:
        return None
    return matches[0]


def find_overlapping_appointments(
    cliente_id: str,
    professional_id: str,
    starts_at: datetime,
    ends_at: datetime,
    *,
    exclude_appointment_id: str | None = None,
) -> list[dict[str, Any]]:
    """Marcações activas com overlap no intervalo (profissional fixo)."""
    if not supabase:
        return []
    from_utc = starts_at.astimezone(timezone.utc)
    to_utc = ends_at.astimezone(timezone.utc)
    q = (
        supabase.table(Tables.SCHEDULING_APPOINTMENTS)
        .select("*")
        .eq(SchedulingAppointmentModel.CLIENTE_ID, str(cliente_id))
        .eq(SchedulingAppointmentModel.PROFESSIONAL_ID, str(professional_id))
        .lt(SchedulingAppointmentModel.STARTS_AT, to_utc.isoformat())
        .gt(SchedulingAppointmentModel.ENDS_AT, from_utc.isoformat())
        .neq(SchedulingAppointmentModel.STATUS, "cancelled")
    )
    if exclude_appointment_id:
        q = q.neq(SchedulingAppointmentModel.ID, str(exclude_appointment_id))
    return [dict(r) for r in (q.execute().data or [])]


def busy_intervals_utc(
    cliente_id: str,
    professional_id: str | None,
    from_utc: datetime,
    to_utc: datetime,
    exclude_appointment_id: str | None = None,
    exclude_appointment_ids: frozenset[str] | None = None,
) -> list[tuple[datetime, datetime]]:
    if not supabase:
        return []
    pid = str(professional_id) if professional_id else None

    ap_q = (
        supabase.table(Tables.SCHEDULING_APPOINTMENTS)
        .select(
            ",".join(
                [
                    SchedulingAppointmentModel.ID,
                    SchedulingAppointmentModel.STARTS_AT,
                    SchedulingAppointmentModel.ENDS_AT,
                    SchedulingAppointmentModel.STATUS,
                    SchedulingAppointmentModel.PROFESSIONAL_ID,
                ]
            )
        )
        .eq(SchedulingAppointmentModel.CLIENTE_ID, str(cliente_id))
        .lt(SchedulingAppointmentModel.STARTS_AT, to_utc.isoformat())
        .gt(SchedulingAppointmentModel.ENDS_AT, from_utc.isoformat())
        .neq(SchedulingAppointmentModel.STATUS, "cancelled")
    )
    excludes = set(exclude_appointment_ids or ())
    if exclude_appointment_id:
        excludes.add(str(exclude_appointment_id))
    for eid in excludes:
        ap_q = ap_q.neq(SchedulingAppointmentModel.ID, str(eid))
    if pid:
        ap_q = ap_q.eq(SchedulingAppointmentModel.PROFESSIONAL_ID, pid)
    aps = ap_q.execute().data or []

    bl_q = (
        supabase.table(Tables.SCHEDULING_BLOCKED_TIMES)
        .select(
            ",".join(
                [
                    SchedulingBlockedTimeModel.STARTS_AT,
                    SchedulingBlockedTimeModel.ENDS_AT,
                    SchedulingBlockedTimeModel.PROFESSIONAL_ID,
                ]
            )
        )
        .eq(SchedulingBlockedTimeModel.CLIENTE_ID, str(cliente_id))
        .lt(SchedulingBlockedTimeModel.STARTS_AT, to_utc.isoformat())
        .gt(SchedulingBlockedTimeModel.ENDS_AT, from_utc.isoformat())
    )
    blocks = bl_q.execute().data or []

    out: list[tuple[datetime, datetime]] = []
    for row in aps:
        try:
            s = datetime.fromisoformat(str(row.get("starts_at", "")).replace("Z", "+00:00"))
            e = datetime.fromisoformat(str(row.get("ends_at", "")).replace("Z", "+00:00"))
            if s.tzinfo is None:
                s = s.replace(tzinfo=timezone.utc)
            if e.tzinfo is None:
                e = e.replace(tzinfo=timezone.utc)
            if s < e:
                out.append((s, e))
        except Exception:
            continue

    for row in blocks:
        try:
            bid = row.get(SchedulingBlockedTimeModel.PROFESSIONAL_ID)
            if pid and bid not in (None, "") and str(bid) != str(pid):
                continue
            s = datetime.fromisoformat(str(row.get("starts_at", "")).replace("Z", "+00:00"))
            e = datetime.fromisoformat(str(row.get("ends_at", "")).replace("Z", "+00:00"))
            if s.tzinfo is None:
                s = s.replace(tzinfo=timezone.utc)
            if e.tzinfo is None:
                e = e.replace(tzinfo=timezone.utc)
            if s < e:
                out.append((s, e))
        except Exception:
            continue
    return out


def insert_appointment(
    *,
    cliente_id: str,
    service_id: str,
    professional_id: str | None,
    starts_at: datetime,
    ends_at: datetime,
    remote_id: str | None,
    status: str = "confirmed",
    contact_phone: str | None = None,
    notes: str | None = None,
    meta: dict[str, Any] | None = None,
    recurrence_series_id: str | None = None,
    series_occurrence_at: datetime | None = None,
    is_series_exception: bool = False,
) -> dict[str, Any] | None:
    if not supabase:
        return None
    row = {
        SchedulingAppointmentModel.CLIENTE_ID: str(cliente_id),
        SchedulingAppointmentModel.SERVICE_ID: str(service_id),
        SchedulingAppointmentModel.PROFESSIONAL_ID: str(professional_id) if professional_id else None,
        SchedulingAppointmentModel.STARTS_AT: starts_at.astimezone(timezone.utc).isoformat(),
        SchedulingAppointmentModel.ENDS_AT: ends_at.astimezone(timezone.utc).isoformat(),
        SchedulingAppointmentModel.STATUS: status,
        SchedulingAppointmentModel.REMOTE_ID: (remote_id or None),
        SchedulingAppointmentModel.CONTACT_PHONE: (contact_phone or None),
        SchedulingAppointmentModel.NOTES: (notes or None),
        SchedulingAppointmentModel.META: meta if isinstance(meta, dict) else {},
        SchedulingAppointmentModel.IS_SERIES_EXCEPTION: bool(is_series_exception),
        SchedulingAppointmentModel.UPDATED_AT: _now_iso(),
    }
    if recurrence_series_id:
        row[SchedulingAppointmentModel.RECURRENCE_SERIES_ID] = str(recurrence_series_id)
    if series_occurrence_at:
        row[SchedulingAppointmentModel.SERIES_OCCURRENCE_AT] = series_occurrence_at.astimezone(
            timezone.utc
        ).isoformat()
    r = supabase.table(Tables.SCHEDULING_APPOINTMENTS).insert(row).execute()
    rows = r.data or []
    return dict(rows[0]) if rows else None


def update_appointment_status(cliente_id: str, appointment_id: str, status: str) -> bool:
    if not supabase:
        return False
    supabase.table(Tables.SCHEDULING_APPOINTMENTS).update(
        {
            SchedulingAppointmentModel.STATUS: status,
            SchedulingAppointmentModel.UPDATED_AT: _now_iso(),
        }
    ).eq(SchedulingAppointmentModel.ID, str(appointment_id)).eq(
        SchedulingAppointmentModel.CLIENTE_ID, str(cliente_id)
    ).execute()
    return True


def list_upcoming_by_remote_id(
    cliente_id: str,
    remote_id: str,
    *,
    limit: int = 5,
) -> list[dict[str, Any]]:
    """Marcações futuras não canceladas para um contacto (WhatsApp remote_id)."""
    if not supabase:
        return []
    rid = (remote_id or "").strip()
    if not rid:
        return []
    now = datetime.now(timezone.utc).isoformat()
    return (
        supabase.table(Tables.SCHEDULING_APPOINTMENTS)
        .select("*")
        .eq(SchedulingAppointmentModel.CLIENTE_ID, str(cliente_id))
        .eq(SchedulingAppointmentModel.REMOTE_ID, rid)
        .gte(SchedulingAppointmentModel.STARTS_AT, now)
        .neq(SchedulingAppointmentModel.STATUS, "cancelled")
        .order(SchedulingAppointmentModel.STARTS_AT)
        .limit(max(1, int(limit)))
        .execute()
        .data
        or []
    )


def parse_row_datetime(value: Any) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        dt = value
    else:
        try:
            dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        except (TypeError, ValueError):
            return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def get_blocked_time(cliente_id: str, blocked_id: str) -> dict[str, Any] | None:
    if not supabase:
        return None
    r = (
        supabase.table(Tables.SCHEDULING_BLOCKED_TIMES)
        .select("*")
        .eq(SchedulingBlockedTimeModel.ID, str(blocked_id))
        .eq(SchedulingBlockedTimeModel.CLIENTE_ID, str(cliente_id))
        .limit(1)
        .execute()
    )
    rows = r.data or []
    return dict(rows[0]) if rows else None


def list_blocked_times_in_range(
    cliente_id: str,
    from_utc: datetime,
    to_utc: datetime,
    *,
    professional_id: str | None = None,
    limit: int = 500,
) -> list[dict[str, Any]]:
    """Bloqueios que intersectam [from_utc, to_utc]. Com professional_id: desse prof + globais."""
    if not supabase:
        return []
    q = (
        supabase.table(Tables.SCHEDULING_BLOCKED_TIMES)
        .select("*")
        .eq(SchedulingBlockedTimeModel.CLIENTE_ID, str(cliente_id))
        .lt(SchedulingBlockedTimeModel.STARTS_AT, to_utc.isoformat())
        .gt(SchedulingBlockedTimeModel.ENDS_AT, from_utc.isoformat())
        .order(SchedulingBlockedTimeModel.STARTS_AT)
        .limit(max(1, int(limit)))
    )
    rows = q.execute().data or []
    pid = (professional_id or "").strip()
    if not pid:
        return [dict(r) for r in rows]
    out: list[dict[str, Any]] = []
    for r in rows:
        bid = r.get(SchedulingBlockedTimeModel.PROFESSIONAL_ID)
        if bid in (None, "") or str(bid) == pid:
            out.append(dict(r))
    return out


def update_blocked_time(
    cliente_id: str,
    blocked_id: str,
    *,
    starts_at: datetime | None = None,
    ends_at: datetime | None = None,
    professional_id: Any = ...,
    reason: Any = ...,
) -> bool:
    if not supabase:
        return False
    payload: dict[str, Any] = {}
    if starts_at is not None:
        payload[SchedulingBlockedTimeModel.STARTS_AT] = starts_at.astimezone(timezone.utc).isoformat()
    if ends_at is not None:
        payload[SchedulingBlockedTimeModel.ENDS_AT] = ends_at.astimezone(timezone.utc).isoformat()
    if professional_id is not ...:
        pid = str(professional_id).strip() if professional_id else None
        payload[SchedulingBlockedTimeModel.PROFESSIONAL_ID] = pid or None
    if reason is not ...:
        payload[SchedulingBlockedTimeModel.REASON] = (str(reason).strip() if reason else None) or None
    if not payload:
        return True
    supabase.table(Tables.SCHEDULING_BLOCKED_TIMES).update(payload).eq(
        SchedulingBlockedTimeModel.ID, str(blocked_id)
    ).eq(SchedulingBlockedTimeModel.CLIENTE_ID, str(cliente_id)).execute()
    return True


def list_blocked_times(cliente_id: str, *, limit: int = 100) -> list[dict[str, Any]]:
    if not supabase:
        return []
    return (
        supabase.table(Tables.SCHEDULING_BLOCKED_TIMES)
        .select("*")
        .eq(SchedulingBlockedTimeModel.CLIENTE_ID, str(cliente_id))
        .order(SchedulingBlockedTimeModel.STARTS_AT, desc=True)
        .limit(max(1, int(limit)))
        .execute()
        .data
        or []
    )


def insert_blocked_time(
    *,
    cliente_id: str,
    starts_at: datetime,
    ends_at: datetime,
    professional_id: str | None = None,
    reason: str | None = None,
) -> dict[str, Any] | None:
    if not supabase:
        return None
    if starts_at >= ends_at:
        return None
    row = {
        SchedulingBlockedTimeModel.CLIENTE_ID: str(cliente_id),
        SchedulingBlockedTimeModel.PROFESSIONAL_ID: professional_id or None,
        SchedulingBlockedTimeModel.STARTS_AT: starts_at.astimezone(timezone.utc).isoformat(),
        SchedulingBlockedTimeModel.ENDS_AT: ends_at.astimezone(timezone.utc).isoformat(),
        SchedulingBlockedTimeModel.REASON: (reason or "").strip() or None,
    }
    r = supabase.table(Tables.SCHEDULING_BLOCKED_TIMES).insert(row).execute()
    data = r.data or []
    return dict(data[0]) if data else None


def delete_blocked_time(cliente_id: str, blocked_id: str) -> bool:
    if not supabase:
        return False
    supabase.table(Tables.SCHEDULING_BLOCKED_TIMES).delete().eq(
        SchedulingBlockedTimeModel.ID, str(blocked_id)
    ).eq(SchedulingBlockedTimeModel.CLIENTE_ID, str(cliente_id)).execute()
    return True


def get_appointment(cliente_id: str, appointment_id: str) -> dict[str, Any] | None:
    if not supabase:
        return None
    r = (
        supabase.table(Tables.SCHEDULING_APPOINTMENTS)
        .select("*")
        .eq(SchedulingAppointmentModel.ID, str(appointment_id))
        .eq(SchedulingAppointmentModel.CLIENTE_ID, str(cliente_id))
        .limit(1)
        .execute()
    )
    rows = r.data or []
    return dict(rows[0]) if rows else None


def merge_appointment_meta(cliente_id: str, appointment_id: str, patch: dict[str, Any]) -> bool:
    if not supabase or not patch:
        return False
    row = get_appointment(cliente_id, appointment_id)
    if not row:
        return False
    meta = row.get("meta") if isinstance(row.get("meta"), dict) else {}
    meta = dict(meta)
    for k, v in patch.items():
        if isinstance(v, dict) and isinstance(meta.get(k), dict):
            merged = dict(meta[k])
            merged.update(v)
            meta[k] = merged
        else:
            meta[k] = v
    supabase.table(Tables.SCHEDULING_APPOINTMENTS).update(
        {
            SchedulingAppointmentModel.META: meta,
            SchedulingAppointmentModel.UPDATED_AT: _now_iso(),
        }
    ).eq(SchedulingAppointmentModel.ID, str(appointment_id)).eq(
        SchedulingAppointmentModel.CLIENTE_ID, str(cliente_id)
    ).execute()
    return True


def set_appointment_external_id(
    cliente_id: str,
    appointment_id: str,
    external_agenda_appointment_id: str,
    *,
    meta_patch: dict[str, Any] | None = None,
) -> bool:
    if not supabase:
        return False
    patch: dict[str, Any] = {
        SchedulingAppointmentModel.EXTERNAL_AGENDA_APPOINTMENT_ID: str(external_agenda_appointment_id),
        SchedulingAppointmentModel.UPDATED_AT: _now_iso(),
    }
    if meta_patch:
        row = get_appointment(cliente_id, appointment_id)
        meta = dict(row.get("meta") or {}) if row else {}
        meta.update(meta_patch)
        patch[SchedulingAppointmentModel.META] = meta
    supabase.table(Tables.SCHEDULING_APPOINTMENTS).update(patch).eq(
        SchedulingAppointmentModel.ID, str(appointment_id)
    ).eq(SchedulingAppointmentModel.CLIENTE_ID, str(cliente_id)).execute()
    return True


def list_appointments_pending_motor_sync(
    cliente_id: str | None = None,
    *,
    limit: int = 100,
) -> list[dict[str, Any]]:
    if not supabase:
        return []
    q = supabase.table(Tables.SCHEDULING_APPOINTMENTS).select("*")
    if cliente_id:
        q = q.eq(SchedulingAppointmentModel.CLIENTE_ID, str(cliente_id))
    rows = q.limit(max(1, int(limit) * 3)).execute().data or []
    out = []
    for row in rows:
        meta = row.get("meta") if isinstance(row.get("meta"), dict) else {}
        if str(meta.get("motor_sync") or "") == "pending":
            out.append(dict(row))
        if len(out) >= limit:
            break
    return out


def list_series_appointments_from(
    cliente_id: str,
    series_id: str,
    from_starts_at_iso: str,
    *,
    include_cancelled: bool = False,
) -> list[dict[str, Any]]:
    if not supabase:
        return []
    q = (
        supabase.table(Tables.SCHEDULING_APPOINTMENTS)
        .select("*")
        .eq(SchedulingAppointmentModel.CLIENTE_ID, str(cliente_id))
        .eq(SchedulingAppointmentModel.RECURRENCE_SERIES_ID, str(series_id))
        .gte(SchedulingAppointmentModel.STARTS_AT, from_starts_at_iso)
    )
    if not include_cancelled:
        q = q.neq(SchedulingAppointmentModel.STATUS, "cancelled")
    return q.execute().data or []


def list_appointments_in_range(
    cliente_id: str,
    from_utc: datetime,
    to_utc: datetime,
    *,
    professional_id: str | None = None,
    status: str | None = None,
    search: str | None = None,
    limit: int = 500,
) -> list[dict[str, Any]]:
    if not supabase:
        return []
    q = (
        supabase.table(Tables.SCHEDULING_APPOINTMENTS)
        .select("*")
        .eq(SchedulingAppointmentModel.CLIENTE_ID, str(cliente_id))
        .gte(SchedulingAppointmentModel.STARTS_AT, from_utc.astimezone(timezone.utc).isoformat())
        .lt(SchedulingAppointmentModel.STARTS_AT, to_utc.astimezone(timezone.utc).isoformat())
        .order(SchedulingAppointmentModel.STARTS_AT)
        .limit(max(1, int(limit)))
    )
    if professional_id:
        q = q.eq(SchedulingAppointmentModel.PROFESSIONAL_ID, str(professional_id))
    if status and status.strip().lower() not in ("", "all"):
        q = q.eq(SchedulingAppointmentModel.STATUS, status.strip().lower())
    rows = q.execute().data or []
    term = (search or "").strip().lower()
    if not term:
        return rows
    out: list[dict[str, Any]] = []
    for row in rows:
        meta = row.get("meta") if isinstance(row.get("meta"), dict) else {}
        blob = " ".join(
            str(x or "")
            for x in (
                row.get("remote_id"),
                row.get("contact_phone"),
                row.get("notes"),
                meta.get("contact_name"),
                meta.get("contact_email"),
            )
        ).lower()
        if term in blob:
            out.append(row)
    return out


def list_upcoming_appointments(cliente_id: str, limit: int = 50) -> list[dict[str, Any]]:
    if not supabase:
        return []
    now = datetime.now(timezone.utc).isoformat()
    return (
        supabase.table(Tables.SCHEDULING_APPOINTMENTS)
        .select("*")
        .eq(SchedulingAppointmentModel.CLIENTE_ID, str(cliente_id))
        .gte(SchedulingAppointmentModel.STARTS_AT, now)
        .neq(SchedulingAppointmentModel.STATUS, "cancelled")
        .order(SchedulingAppointmentModel.STARTS_AT)
        .limit(limit)
        .execute()
        .data
        or []
    )


def get_service(cliente_id: str, service_id: str) -> dict[str, Any] | None:
    if not supabase:
        return None
    r = (
        supabase.table(Tables.SCHEDULING_SERVICES)
        .select("*")
        .eq(SchedulingServiceModel.CLIENTE_ID, str(cliente_id))
        .eq(SchedulingServiceModel.ID, str(service_id))
        .limit(1)
        .execute()
    )
    rows = r.data or []
    return dict(rows[0]) if rows else None


def get_appointment_by_external_agenda_id(
    cliente_id: str, external_agenda_appointment_id: str
) -> dict[str, Any] | None:
    """Uma linha por (cliente_id, external_agenda_appointment_id) após migração 026."""
    if not supabase:
        return None
    ext = (external_agenda_appointment_id or "").strip()
    if not ext:
        return None
    r = (
        supabase.table(Tables.SCHEDULING_APPOINTMENTS)
        .select("*")
        .eq(SchedulingAppointmentModel.CLIENTE_ID, str(cliente_id))
        .eq(SchedulingAppointmentModel.EXTERNAL_AGENDA_APPOINTMENT_ID, ext)
        .limit(1)
        .execute()
    )
    rows = r.data or []
    return dict(rows[0]) if rows else None


def get_professional(cliente_id: str, professional_id: str) -> dict[str, Any] | None:
    if not supabase:
        return None
    try:
        r = (
            supabase.table(Tables.SCHEDULING_PROFESSIONALS)
            .select("*")
            .eq(SchedulingProfessionalModel.CLIENTE_ID, str(cliente_id))
            .eq(SchedulingProfessionalModel.ID, str(professional_id))
            .limit(1)
            .execute()
        )
    except Exception:
        return None
    rows = r.data or []
    return dict(rows[0]) if rows else None


def get_settings_by_slug(slug: str) -> dict[str, Any] | None:
    if not supabase:
        return None
    s = (slug or "").strip().lower()
    if not s:
        return None
    r = (
        supabase.table(Tables.SCHEDULING_SETTINGS)
        .select("*")
        .eq(SchedulingSettingsModel.PUBLIC_SLUG, s)
        .limit(1)
        .execute()
    )
    rows = r.data or []
    return dict(rows[0]) if rows else None


def clear_clinica_config(cliente_id: str) -> None:
    """Remove nome, slug e horários gerais da clínica (mantém profissionais/serviços)."""
    if not supabase:
        return
    cid = str(cliente_id)
    supabase.table(Tables.SCHEDULING_SETTINGS).update(
        {
            SchedulingSettingsModel.PUBLIC_NAME: None,
            SchedulingSettingsModel.PUBLIC_SLUG: None,
            SchedulingSettingsModel.UPDATED_AT: _now_iso(),
        }
    ).eq(SchedulingSettingsModel.CLIENTE_ID, cid).execute()
    supabase.table(Tables.SCHEDULING_WORKING_HOURS).delete().eq(
        SchedulingWorkingHoursModel.CLIENTE_ID, cid
    ).is_(SchedulingWorkingHoursModel.PROFESSIONAL_ID, "null").execute()


def reset_agenda_catalog(cliente_id: str) -> str | None:
    """
    Apaga agendamentos, bloqueios, horários, serviços e profissionais do tenant.
    Devolve mensagem de erro ou None se OK.
    """
    if not supabase:
        return "supabase_indisponível"
    cid = str(cliente_id)
    try:
        supabase.table(Tables.SCHEDULING_APPOINTMENTS).delete().eq(
            SchedulingAppointmentModel.CLIENTE_ID, cid
        ).execute()
        supabase.table(Tables.SCHEDULING_BLOCKED_TIMES).delete().eq(
            SchedulingBlockedTimeModel.CLIENTE_ID, cid
        ).execute()
        supabase.table(Tables.SCHEDULING_WORKING_HOURS).delete().eq(
            SchedulingWorkingHoursModel.CLIENTE_ID, cid
        ).execute()
        supabase.table(Tables.SCHEDULING_SERVICES).delete().eq(
            SchedulingServiceModel.CLIENTE_ID, cid
        ).execute()
        supabase.table(Tables.SCHEDULING_PROFESSIONALS).delete().eq(
            SchedulingProfessionalModel.CLIENTE_ID, cid
        ).execute()
        clear_clinica_config(cid)
    except Exception as e:
        err = str(e).lower()
        if "restrict" in err or "23503" in err:
            return "existem_agendamentos_ou_referencias"
        return str(e)[:200]
    return None


def delete_appointment_row(cliente_id: str, appointment_id: str) -> bool:
    if not supabase:
        return False
    supabase.table(Tables.SCHEDULING_APPOINTMENTS).delete().eq(
        SchedulingAppointmentModel.ID, str(appointment_id)
    ).eq(SchedulingAppointmentModel.CLIENTE_ID, str(cliente_id)).execute()
    return True


def insert_recurrence_series(row: dict[str, Any]) -> dict[str, Any] | None:
    if not supabase:
        return None
    r = supabase.table(Tables.SCHEDULING_RECURRENCE_SERIES).insert(row).execute()
    rows = r.data or []
    return dict(rows[0]) if rows else None


def get_recurrence_series(cliente_id: str, series_id: str) -> dict[str, Any] | None:
    if not supabase:
        return None
    r = (
        supabase.table(Tables.SCHEDULING_RECURRENCE_SERIES)
        .select("*")
        .eq(SchedulingRecurrenceSeriesModel.ID, str(series_id))
        .eq(SchedulingRecurrenceSeriesModel.CLIENTE_ID, str(cliente_id))
        .limit(1)
        .execute()
    )
    rows = r.data or []
    return dict(rows[0]) if rows else None


def update_recurrence_series(cliente_id: str, series_id: str, patch: dict[str, Any]) -> bool:
    if not supabase:
        return False
    data = dict(patch)
    data[SchedulingRecurrenceSeriesModel.UPDATED_AT] = _now_iso()
    supabase.table(Tables.SCHEDULING_RECURRENCE_SERIES).update(data).eq(
        SchedulingRecurrenceSeriesModel.ID, str(series_id)
    ).eq(SchedulingRecurrenceSeriesModel.CLIENTE_ID, str(cliente_id)).execute()
    return True


def list_active_recurrence_series(*, limit: int = 500) -> list[dict[str, Any]]:
    if not supabase:
        return []
    return (
        supabase.table(Tables.SCHEDULING_RECURRENCE_SERIES)
        .select("*")
        .eq(SchedulingRecurrenceSeriesModel.STATUS, "active")
        .limit(max(1, int(limit)))
        .execute()
        .data
        or []
    )


def list_recurrence_skips(series_id: str) -> set[str]:
    if not supabase:
        return set()
    rows = (
        supabase.table(Tables.SCHEDULING_RECURRENCE_SKIPS)
        .select(SchedulingRecurrenceSkipModel.OCCURRENCE_DATE)
        .eq(SchedulingRecurrenceSkipModel.SERIES_ID, str(series_id))
        .execute()
        .data
        or []
    )
    return {str(r.get(SchedulingRecurrenceSkipModel.OCCURRENCE_DATE) or "")[:10] for r in rows}


def add_recurrence_skip(cliente_id: str, series_id: str, occurrence_date: str) -> bool:
    if not supabase:
        return False
    try:
        supabase.table(Tables.SCHEDULING_RECURRENCE_SKIPS).insert(
            {
                SchedulingRecurrenceSkipModel.CLIENTE_ID: str(cliente_id),
                SchedulingRecurrenceSkipModel.SERIES_ID: str(series_id),
                SchedulingRecurrenceSkipModel.OCCURRENCE_DATE: str(occurrence_date)[:10],
            }
        ).execute()
        return True
    except Exception:
        return False


def get_appointment_by_series_occurrence(
    series_id: str, series_occurrence_at: datetime
) -> dict[str, Any] | None:
    if not supabase:
        return None
    iso = series_occurrence_at.astimezone(timezone.utc).isoformat()
    r = (
        supabase.table(Tables.SCHEDULING_APPOINTMENTS)
        .select("*")
        .eq(SchedulingAppointmentModel.RECURRENCE_SERIES_ID, str(series_id))
        .eq(SchedulingAppointmentModel.SERIES_OCCURRENCE_AT, iso)
        .limit(1)
        .execute()
    )
    rows = r.data or []
    return dict(rows[0]) if rows else None


def list_series_appointments_from_date(
    cliente_id: str,
    series_id: str,
    from_date_iso: str,
    *,
    include_cancelled: bool = False,
) -> list[dict[str, Any]]:
    if not supabase:
        return []
    q = (
        supabase.table(Tables.SCHEDULING_APPOINTMENTS)
        .select("*")
        .eq(SchedulingAppointmentModel.CLIENTE_ID, str(cliente_id))
        .eq(SchedulingAppointmentModel.RECURRENCE_SERIES_ID, str(series_id))
        .gte(SchedulingAppointmentModel.STARTS_AT, f"{from_date_iso[:10]}T00:00:00+00:00")
        .order(SchedulingAppointmentModel.STARTS_AT)
    )
    if not include_cancelled:
        q = q.neq(SchedulingAppointmentModel.STATUS, "cancelled")
    return q.execute().data or []


def cancel_series_appointments_from(
    cliente_id: str,
    series_id: str,
    from_local_date: str,
    *,
    tz_name: str,
) -> int:
    """Cancela ocorrências futuras da série a partir de uma data local (inclusive)."""
    from services.scheduling.slot_engine import _get_tz
    from services.scheduling.timezones import normalize_timezone

    if not supabase:
        return 0
    tz = _get_tz(normalize_timezone(tz_name))
    try:
        anchor = date.fromisoformat(str(from_local_date)[:10])
    except ValueError:
        return 0
    from_local = datetime.combine(anchor, time.min, tzinfo=tz)
    from_utc = from_local.astimezone(timezone.utc).isoformat()
    rows = (
        supabase.table(Tables.SCHEDULING_APPOINTMENTS)
        .select(SchedulingAppointmentModel.ID)
        .eq(SchedulingAppointmentModel.CLIENTE_ID, str(cliente_id))
        .eq(SchedulingAppointmentModel.RECURRENCE_SERIES_ID, str(series_id))
        .gte(SchedulingAppointmentModel.STARTS_AT, from_utc)
        .neq(SchedulingAppointmentModel.STATUS, "cancelled")
        .execute()
        .data
        or []
    )
    n = 0
    for row in rows:
        aid = str(row.get(SchedulingAppointmentModel.ID) or "")
        if aid and update_appointment_status(cliente_id, aid, "cancelled"):
            n += 1
    return n


def delete_series_appointments_from(
    cliente_id: str,
    series_id: str,
    from_local_date: str,
    *,
    tz_name: str,
) -> int:
    """Exclui ocorrências da série a partir de uma data local (inclusive)."""
    from services.scheduling.slot_engine import _get_tz
    from services.scheduling.timezones import normalize_timezone

    if not supabase:
        return 0
    tz = _get_tz(normalize_timezone(tz_name))
    try:
        anchor = date.fromisoformat(str(from_local_date)[:10])
    except ValueError:
        return 0
    from_local = datetime.combine(anchor, time.min, tzinfo=tz)
    from_utc = from_local.astimezone(timezone.utc).isoformat()
    rows = list_series_appointments_from(cliente_id, series_id, from_utc, include_cancelled=True)
    n = 0
    for row in rows:
        aid = str(row.get(SchedulingAppointmentModel.ID) or "")
        if aid and delete_appointment_row(cliente_id, aid):
            n += 1
    return n


def delete_all_series_appointments(cliente_id: str, series_id: str) -> int:
    if not supabase:
        return 0
    rows = (
        supabase.table(Tables.SCHEDULING_APPOINTMENTS)
        .select(SchedulingAppointmentModel.ID)
        .eq(SchedulingAppointmentModel.CLIENTE_ID, str(cliente_id))
        .eq(SchedulingAppointmentModel.RECURRENCE_SERIES_ID, str(series_id))
        .execute()
        .data
        or []
    )
    n = 0
    for row in rows:
        aid = str(row.get(SchedulingAppointmentModel.ID) or "")
        if aid and delete_appointment_row(cliente_id, aid):
            n += 1
    return n
