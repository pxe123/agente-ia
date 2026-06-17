"""Bloqueios de horário — indisponibilidade para novos agendamentos."""
from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone
from typing import Any

from services.agendamento_ia_bridge import scheduling_uses_internal_motor
from services.scheduling import repository
from services.scheduling.slot_engine import _get_tz, effective_working_rows_for_professional
from services.scheduling.timezones import normalize_timezone

_SENTINEL = object()


def block_scope(professional_id: str | None) -> str:
    return "clinic" if not (professional_id or "").strip() else "professional"


def block_scope_label(professional_id: str | None, prof_name: str | None = None) -> str:
    if block_scope(professional_id) == "clinic":
        return "Clínica"
    return (prof_name or "").strip() or "Profissional"


def validate_block_interval(starts_at: datetime, ends_at: datetime) -> str | None:
    if not starts_at or not ends_at:
        return "horario_invalido"
    if starts_at >= ends_at:
        return "horario_invalido"
    return None


def _parse_time_hms(v: Any) -> time:
    if isinstance(v, time):
        return v
    s = str(v or "").strip()
    if not s:
        return time(0, 0)
    parts = s.replace("T", " ").split()
    if len(parts) >= 2 and ":" in parts[-1]:
        s = parts[-1]
    seg = s.split(":")
    h = int(seg[0]) if seg else 0
    m = int(seg[1]) if len(seg) > 1 else 0
    sec = int(seg[2]) if len(seg) > 2 else 0
    return time(h, m, sec)


def resolve_day_block_bounds(
    *,
    local_date: date,
    tz_name: str,
    working_rows: list[dict[str, Any]],
    professional_id: str | None,
) -> tuple[datetime, datetime] | None:
    """Início/fim do dia inteiro no fuso da clínica (horários prof → clínica → 00:00–23:59)."""
    tz = _get_tz(normalize_timezone(tz_name))
    weekday = local_date.weekday()
    pid = (professional_id or "").strip() or None

    if pid:
        rows = effective_working_rows_for_professional(working_rows, pid)
        day_rows = [r for r in rows if int(r.get("day_of_week", -1)) == weekday]
    else:
        day_rows = [
            r
            for r in working_rows
            if int(r.get("day_of_week", -1)) == weekday
            and r.get("professional_id") in (None, "")
        ]

    if not day_rows and pid:
        day_rows = [
            r
            for r in working_rows
            if int(r.get("day_of_week", -1)) == weekday
            and r.get("professional_id") in (None, "")
        ]

    if day_rows:
        starts = [_parse_time_hms(r.get("start_time")) for r in day_rows]
        ends = [_parse_time_hms(r.get("end_time")) for r in day_rows]
        st = min(starts)
        et = max(ends)
    else:
        st = time(0, 0)
        et = time(23, 59, 59)

    start_local = datetime.combine(local_date, st, tzinfo=tz)
    end_local = datetime.combine(local_date, et, tzinfo=tz)
    if end_local <= start_local:
        end_local = start_local + timedelta(hours=1)
    return start_local, end_local


def _guard_internal_motor(cliente_id: str) -> str | None:
    if not scheduling_uses_internal_motor(cliente_id):
        return "motor_externo"
    return None


def _normalize_professional_id(raw: Any) -> str | None:
    if raw is None:
        return None
    s = str(raw).strip()
    if not s or s.lower() in ("null", "none", "clinic", "clinica"):
        return None
    return s


def create_block(
    *,
    cliente_id: str,
    starts_at: datetime,
    ends_at: datetime,
    professional_id: str | None = None,
    reason: str | None = None,
    all_day: bool = False,
    local_date: date | None = None,
    tz_name: str = "America/Sao_Paulo",
    working_rows: list[dict[str, Any]] | None = None,
) -> tuple[dict[str, Any] | None, str | None]:
    err = _guard_internal_motor(cliente_id)
    if err:
        return None, err
    pid = _normalize_professional_id(professional_id)
    if all_day and local_date:
        bounds = resolve_day_block_bounds(
            local_date=local_date,
            tz_name=tz_name,
            working_rows=working_rows or [],
            professional_id=pid,
        )
        if not bounds:
            return None, "horario_invalido"
        starts_at, ends_at = bounds
    interval_err = validate_block_interval(starts_at, ends_at)
    if interval_err:
        return None, interval_err
    row = repository.insert_blocked_time(
        cliente_id=cliente_id,
        starts_at=starts_at,
        ends_at=ends_at,
        professional_id=pid,
        reason=reason,
    )
    if not row:
        return None, "insert_falhou"
    return row, None


def update_block(
    *,
    cliente_id: str,
    blocked_id: str,
    starts_at: datetime | None = None,
    ends_at: datetime | None = None,
    professional_id: str | None | object = _SENTINEL,
    reason: str | None | object = _SENTINEL,
    all_day: bool = False,
    local_date: date | None = None,
    tz_name: str = "America/Sao_Paulo",
    working_rows: list[dict[str, Any]] | None = None,
) -> tuple[dict[str, Any] | None, str | None]:
    err = _guard_internal_motor(cliente_id)
    if err:
        return None, err
    existing = repository.get_blocked_time(cliente_id, blocked_id)
    if not existing:
        return None, "nao_encontrado"

    if professional_id is _SENTINEL:
        pid: str | None = existing.get("professional_id")
        if pid is not None:
            pid = str(pid).strip() or None
    else:
        pid = _normalize_professional_id(professional_id)  # type: ignore[arg-type]

    st = starts_at
    et = ends_at
    if all_day and local_date:
        bounds = resolve_day_block_bounds(
            local_date=local_date,
            tz_name=tz_name,
            working_rows=working_rows or [],
            professional_id=str(pid) if pid else None,
        )
        if not bounds:
            return None, "horario_invalido"
        st, et = bounds
    else:
        if st is None:
            st = repository.parse_row_datetime(existing.get("starts_at"))
        if et is None:
            et = repository.parse_row_datetime(existing.get("ends_at"))
    if not st or not et:
        return None, "horario_invalido"
    interval_err = validate_block_interval(st, et)
    if interval_err:
        return None, interval_err

    kwargs: dict[str, Any] = {"starts_at": st, "ends_at": et}
    if professional_id is not _SENTINEL:
        kwargs["professional_id"] = pid
    if reason is not _SENTINEL:
        kwargs["reason"] = (str(reason).strip() if reason else None) or None  # type: ignore[arg-type]

    ok = repository.update_blocked_time(cliente_id, blocked_id, **kwargs)
    if not ok:
        return None, "update_falhou"
    return repository.get_blocked_time(cliente_id, blocked_id), None


def delete_block(cliente_id: str, blocked_id: str) -> tuple[bool, str | None]:
    err = _guard_internal_motor(cliente_id)
    if err:
        return False, err
    if not repository.get_blocked_time(cliente_id, blocked_id):
        return False, "nao_encontrado"
    ok = repository.delete_blocked_time(cliente_id, blocked_id)
    return (ok, None if ok else "delete_falhou")
