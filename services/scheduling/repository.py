"""
Acesso Supabase ao domínio de agenda (service role).
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

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


def busy_intervals_utc(
    cliente_id: str,
    professional_id: str | None,
    from_utc: datetime,
    to_utc: datetime,
    exclude_appointment_id: str | None = None,
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
    if exclude_appointment_id:
        ap_q = ap_q.neq(SchedulingAppointmentModel.ID, str(exclude_appointment_id))
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
        SchedulingAppointmentModel.UPDATED_AT: _now_iso(),
    }
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
