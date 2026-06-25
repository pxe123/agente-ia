"""Rotinas de horário da clínica: múltiplas rotinas + personalização por dia."""
from __future__ import annotations

import uuid
from typing import Any

from database.models import SchedulingWorkingHoursModel, Tables
from database.supabase_sq import supabase


def _norm_time(value: Any) -> str:
    raw = str(value or "").strip()
    if len(raw) >= 5:
        return raw[:5]
    return "08:00"


def default_routine() -> dict[str, Any]:
    return {
        "id": str(uuid.uuid4()),
        "name": "Rotina principal",
        "days": [0, 1, 2, 3, 4],
        "open": "08:00",
        "close": "18:00",
        "lunch_enabled": True,
        "lunch_start": "12:00",
        "lunch_end": "13:00",
    }


def normalize_config(raw: dict[str, Any] | None) -> dict[str, Any]:
    data = raw if isinstance(raw, dict) else {}
    routines = data.get("routines")
    if not isinstance(routines, list) or not routines:
        routines = [default_routine()]
    cleaned_routines: list[dict[str, Any]] = []
    for r in routines:
        if not isinstance(r, dict):
            continue
        days_raw = r.get("days") or []
        days = sorted({int(d) for d in days_raw if str(d).isdigit() and 0 <= int(d) <= 6})
        cleaned_routines.append(
            {
                "id": str(r.get("id") or uuid.uuid4()),
                "name": str(r.get("name") or "Rotina").strip() or "Rotina",
                "days": days,
                "open": _norm_time(r.get("open")),
                "close": _norm_time(r.get("close")),
                "lunch_enabled": bool(r.get("lunch_enabled")),
                "lunch_start": _norm_time(r.get("lunch_start")),
                "lunch_end": _norm_time(r.get("lunch_end")),
            }
        )
    if not cleaned_routines:
        cleaned_routines = [default_routine()]

    overrides_in = data.get("day_overrides") if isinstance(data.get("day_overrides"), dict) else {}
    day_overrides: dict[str, Any] = {}
    for key, val in overrides_in.items():
        if not isinstance(val, dict) or not val.get("custom"):
            continue
        try:
            dow = int(key)
        except (TypeError, ValueError):
            continue
        if dow < 0 or dow > 6:
            continue
        intervals: list[dict[str, str]] = []
        for iv in val.get("intervals") or []:
            if not isinstance(iv, dict):
                continue
            start = _norm_time(iv.get("start"))
            end = _norm_time(iv.get("end"))
            if start < end:
                intervals.append({"start": start, "end": end})
        if intervals:
            day_overrides[str(dow)] = {"custom": True, "intervals": intervals}

    return {"routines": cleaned_routines, "day_overrides": day_overrides}


def routine_to_intervals(routine: dict[str, Any]) -> list[tuple[str, str]]:
    open_t = _norm_time(routine.get("open"))
    close_t = _norm_time(routine.get("close"))
    if routine.get("lunch_enabled"):
        ls = _norm_time(routine.get("lunch_start"))
        le = _norm_time(routine.get("lunch_end"))
        if open_t < ls and le < close_t:
            return [(open_t, ls), (le, close_t)]
    if open_t < close_t:
        return [(open_t, close_t)]
    return []


def resolve_day_intervals(day: int, config: dict[str, Any]) -> list[tuple[str, str]]:
    overrides = config.get("day_overrides") or {}
    od = overrides.get(str(day))
    if isinstance(od, dict) and od.get("custom"):
        out: list[tuple[str, str]] = []
        for iv in od.get("intervals") or []:
            if not isinstance(iv, dict):
                continue
            start = _norm_time(iv.get("start"))
            end = _norm_time(iv.get("end"))
            if start < end:
                out.append((start, end))
        if out:
            return out

    for routine in config.get("routines") or []:
        days = routine.get("days") or []
        if day in days:
            return routine_to_intervals(routine)
    return []


def expand_config_to_rows(config: dict[str, Any]) -> dict[int, list[tuple[str, str]]]:
    cfg = normalize_config(config)
    out: dict[int, list[tuple[str, str]]] = {}
    for dow in range(7):
        intervals = resolve_day_intervals(dow, cfg)
        if intervals:
            out[dow] = intervals
    return out


def validate_config(config: dict[str, Any]) -> str | None:
    cfg = normalize_config(config)
    seen_days: set[int] = set()
    override_days = {int(k) for k in (cfg.get("day_overrides") or {}).keys() if str(k).isdigit()}
    for routine in cfg["routines"]:
        for d in routine.get("days") or []:
            if d in override_days:
                return (
                    "Um dia com personalização ativa também está numa rotina. "
                    "Desmarque o dia na rotina ou desative a personalização."
                )
            if d in seen_days:
                return "O mesmo dia está em mais de uma rotina. Ajuste as rotinas."
            seen_days.add(d)
        if not routine.get("days"):
            continue
        if not routine_to_intervals(routine):
            return f"Rotina «{routine.get('name')}» tem horários inválidos."
    return None


def infer_config_from_clinic_hours(clinic_hours: list[dict[str, Any]]) -> dict[str, Any]:
    """Reconstrói rotinas a partir dos intervalos guardados (retrocompatível)."""
    by_day: dict[int, list[tuple[str, str]]] = {d: [] for d in range(7)}
    for row in clinic_hours or []:
        if row.get("professional_id") not in (None, ""):
            continue
        try:
            dow = int(row.get("day_of_week"))
        except (TypeError, ValueError):
            continue
        if dow < 0 or dow > 6:
            continue
        start = _norm_time(row.get("start_time"))
        end = _norm_time(row.get("end_time"))
        if start < end:
            by_day[dow].append((start, end))

    signature_to_days: dict[tuple[tuple[str, str], ...], list[int]] = {}
    day_overrides: dict[str, Any] = {}
    for dow, intervals in by_day.items():
        if not intervals:
            continue
        sig = tuple(sorted(intervals))
        if len(sig) == 1 or len(sig) == 2:
            signature_to_days.setdefault(sig, []).append(dow)
        else:
            day_overrides[str(dow)] = {
                "custom": True,
                "intervals": [{"start": a, "end": b} for a, b in sig],
            }

    routines: list[dict[str, Any]] = []
    for i, (sig, days) in enumerate(signature_to_days.items()):
        base = default_routine()
        base["id"] = str(uuid.uuid4())
        base["days"] = sorted(days)
        base["name"] = "Rotina principal" if i == 0 else f"Rotina {i + 1}"
        if len(sig) == 1:
            base["open"] = sig[0][0]
            base["close"] = sig[0][1]
            base["lunch_enabled"] = False
        elif len(sig) == 2:
            base["open"] = sig[0][0]
            base["lunch_start"] = sig[0][1]
            base["lunch_end"] = sig[1][0]
            base["close"] = sig[1][1]
            base["lunch_enabled"] = True
        routines.append(base)

    if not routines and not day_overrides:
        return normalize_config({})
    return normalize_config({"routines": routines or [default_routine()], "day_overrides": day_overrides})


def load_working_hour_config(
    settings: dict[str, Any] | None,
    clinic_hours: list[dict[str, Any]],
) -> dict[str, Any]:
    raw = (settings or {}).get("working_hour_config")
    if isinstance(raw, dict) and raw.get("routines"):
        return normalize_config(raw)
    if clinic_hours:
        return infer_config_from_clinic_hours(clinic_hours)
    return normalize_config({})


def sync_clinic_working_hours(cliente_id: str, config: dict[str, Any]) -> bool:
    if not supabase:
        return False
    cfg = normalize_config(config)
    expanded = expand_config_to_rows(cfg)
    supabase.table(Tables.SCHEDULING_WORKING_HOURS).delete().eq(
        SchedulingWorkingHoursModel.CLIENTE_ID, str(cliente_id)
    ).is_(SchedulingWorkingHoursModel.PROFESSIONAL_ID, "null").execute()
    rows: list[dict[str, Any]] = []
    for dow, intervals in expanded.items():
        for start, end in intervals:
            rows.append(
                {
                    SchedulingWorkingHoursModel.CLIENTE_ID: str(cliente_id),
                    SchedulingWorkingHoursModel.PROFESSIONAL_ID: None,
                    SchedulingWorkingHoursModel.DAY_OF_WEEK: int(dow),
                    SchedulingWorkingHoursModel.START_TIME: start,
                    SchedulingWorkingHoursModel.END_TIME: end,
                }
            )
    if rows:
        supabase.table(Tables.SCHEDULING_WORKING_HOURS).insert(rows).execute()
    return True


def save_working_hour_config(cliente_id: str, config: dict[str, Any]) -> str | None:
    err = validate_config(config)
    if err:
        return err
    if not supabase:
        return "sem_db"
    cfg = normalize_config(config)
    # Intervalos expandidos são a fonte de verdade para agenda e página pública.
    if not sync_clinic_working_hours(cliente_id, cfg):
        return "sem_db"
    from datetime import datetime, timezone

    from database.models import SchedulingSettingsModel

    payload = {
        SchedulingSettingsModel.WORKING_HOUR_CONFIG: cfg,
        SchedulingSettingsModel.UPDATED_AT: datetime.now(timezone.utc).isoformat(),
    }
    try:
        supabase.table(Tables.SCHEDULING_SETTINGS).update(payload).eq(
            SchedulingSettingsModel.CLIENTE_ID, str(cliente_id)
        ).execute()
    except Exception as exc:
        # Migração 032 ainda não aplicada: horários já foram gravados em working_hours.
        if "working_hour_config" not in str(exc).lower():
            return str(exc)[:200]
    return None
