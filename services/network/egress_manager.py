from __future__ import annotations

import os
import time
from dataclasses import dataclass
from typing import Any, Dict, Optional, Tuple

from database.supabase_sq import supabase
from database.models import Tables, EgressProfileModel, EgressAssignmentModel
from services.network.egress_observability import emit


@dataclass(frozen=True)
class EgressProfile:
    id: str
    name: str
    host: str
    port: int
    username: str | None
    password: str | None
    type: str | None  # metadata only
    country: str | None
    is_active: bool
    max_clients: int
    last_test_ip: str | None
    last_test_latency: int | None
    last_test_at: str | None

    def proxy_server(self) -> str:
        return f"{self.host}:{int(self.port)}"


# Cache leve (process-local) para reduzir query por envio.
_CACHE_TTL_SEC = 30
_cache_profile_by_cliente: dict[str, tuple[float, Optional[EgressProfile]]] = {}


def _now() -> float:
    return time.time()


def _cache_get(cliente_id: str) -> Optional[EgressProfile] | None:
    k = str(cliente_id or "").strip()
    if not k:
        return None
    hit = _cache_profile_by_cliente.get(k)
    if not hit:
        return None
    ts, prof = hit
    if _now() - ts > _CACHE_TTL_SEC:
        _cache_profile_by_cliente.pop(k, None)
        return None
    return prof


def _cache_set(cliente_id: str, prof: Optional[EgressProfile]) -> None:
    k = str(cliente_id or "").strip()
    if not k:
        return
    _cache_profile_by_cliente[k] = (_now(), prof)


def _cache_invalidate(cliente_id: str) -> None:
    k = str(cliente_id or "").strip()
    if not k:
        return
    _cache_profile_by_cliente.pop(k, None)


def enforce_on_waha_sessions() -> bool:
    return (os.getenv("EGRESS_ENFORCE_ON_WAHA_SESSIONS") or "").strip().lower() in (
        "1",
        "true",
        "yes",
        "on",
    )


def _row_to_profile(row: dict[str, Any]) -> EgressProfile:
    return EgressProfile(
        id=str(row.get(EgressProfileModel.ID)),
        name=str(row.get(EgressProfileModel.NAME) or "").strip(),
        host=str(row.get(EgressProfileModel.HOST) or "").strip(),
        port=int(row.get(EgressProfileModel.PORT) or 0),
        username=(str(row.get(EgressProfileModel.USERNAME)).strip() if row.get(EgressProfileModel.USERNAME) is not None else None),
        password=(str(row.get(EgressProfileModel.PASSWORD)).strip() if row.get(EgressProfileModel.PASSWORD) is not None else None),
        type=(str(row.get(EgressProfileModel.TYPE)).strip() if row.get(EgressProfileModel.TYPE) is not None else None),
        country=(str(row.get(EgressProfileModel.COUNTRY)).strip() if row.get(EgressProfileModel.COUNTRY) is not None else None),
        is_active=bool(row.get(EgressProfileModel.IS_ACTIVE, True)),
        max_clients=int(row.get(EgressProfileModel.MAX_CLIENTS) or 2),
        last_test_ip=(str(row.get(EgressProfileModel.LAST_TEST_IP)).strip() if row.get(EgressProfileModel.LAST_TEST_IP) is not None else None),
        last_test_latency=(int(row.get(EgressProfileModel.LAST_TEST_LATENCY)) if row.get(EgressProfileModel.LAST_TEST_LATENCY) is not None else None),
        last_test_at=(str(row.get(EgressProfileModel.LAST_TEST_AT)).strip() if row.get(EgressProfileModel.LAST_TEST_AT) is not None else None),
    )


def get_profile(cliente_id: str) -> Optional[EgressProfile]:
    """
    Retorna o profile do tenant (ou None).
    Cache TTL 30s para reduzir custo em envios.
    """
    cid = str(cliente_id or "").strip()
    if not cid or not supabase:
        return None

    cached = _cache_get(cid)
    if cached is not None or (cid in _cache_profile_by_cliente):
        # cached pode ser None (sem perfil) mas armazenamos como hit também
        return cached

    try:
        a = (
            supabase.table(Tables.EGRESS_ASSIGNMENTS)
            .select(EgressAssignmentModel.EGRESS_PROFILE_ID)
            .eq(EgressAssignmentModel.CLIENTE_ID, cid)
            .limit(1)
            .execute()
        )
        if not a.data:
            _cache_set(cid, None)
            return None
        profile_id = str(a.data[0].get(EgressAssignmentModel.EGRESS_PROFILE_ID) or "").strip()
        if not profile_id:
            _cache_set(cid, None)
            return None
        p = (
            supabase.table(Tables.EGRESS_PROFILES)
            .select("*")
            .eq(EgressProfileModel.ID, profile_id)
            .limit(1)
            .execute()
        )
        if not p.data:
            _cache_set(cid, None)
            return None
        prof = _row_to_profile(p.data[0])
        _cache_set(cid, prof)
        return prof
    except Exception:
        return None


def validate_capacity(profile_id: str) -> Tuple[bool, Optional[str], Optional[dict]]:
    """
    Valida capacidade (sem lock). Para validação final use assign_profile (RPC com lock).
    Retorna (ok, erro, info).
    """
    pid = str(profile_id or "").strip()
    if not pid or not supabase:
        return False, "Perfil inválido.", None
    try:
        p = supabase.table(Tables.EGRESS_PROFILES).select("*").eq(EgressProfileModel.ID, pid).limit(1).execute()
        if not p.data:
            return False, "Perfil não encontrado.", None
        row = p.data[0]
        if not bool(row.get(EgressProfileModel.IS_ACTIVE, True)):
            return False, "Perfil inativo.", None
        max_clients = int(row.get(EgressProfileModel.MAX_CLIENTS) or 2)
        c = (
            supabase.table(Tables.EGRESS_ASSIGNMENTS)
            .select(EgressAssignmentModel.ID, count="exact")
            .eq(EgressAssignmentModel.EGRESS_PROFILE_ID, pid)
            .execute()
        )
        used = int(getattr(c, "count", None) or len(c.data or []))
        if used >= max_clients:
            return False, f"Sem capacidade (usando {used}/{max_clients}).", {"used": used, "max": max_clients}
        return True, None, {"used": used, "max": max_clients}
    except Exception as e:
        return False, str(e), None


def assign_profile(cliente_id: str, profile_id: str) -> None:
    """
    Vincula tenant ao profile usando RPC com lock (assign_egress_profile).
    Lança RuntimeError com mensagem clara em falha.
    """
    cid = str(cliente_id or "").strip()
    pid = str(profile_id or "").strip()
    if not cid or not pid:
        raise RuntimeError("cliente_id/profile_id inválidos.")
    if not supabase:
        raise RuntimeError("Supabase indisponível.")
    try:
        # A RPC implementa lock e valida capacidade/is_active.
        supabase.rpc("assign_egress_profile", {"p_cliente_id": cid, "p_profile_id": pid}).execute()
        emit("proxy_change_event", cliente_id=cid, profile_id=pid, data={"action": "assign"})
    except Exception as e:
        msg = str(e)
        # Normaliza mensagens comuns do Postgres.
        if "inativo" in msg.lower():
            raise RuntimeError("Egress profile inativo.") from e
        if "capacidade" in msg.lower() or "max_clients" in msg.lower():
            raise RuntimeError("Egress profile sem capacidade (max_clients excedido).") from e
        if "não encontrado" in msg.lower() or "not found" in msg.lower():
            raise RuntimeError("Egress profile não encontrado.") from e
        raise RuntimeError(msg) from e
    finally:
        _cache_invalidate(cid)


def release_profile(cliente_id: str) -> None:
    """
    Remove o vínculo tenant->profile.
    """
    cid = str(cliente_id or "").strip()
    if not cid:
        raise RuntimeError("cliente_id inválido.")
    if not supabase:
        raise RuntimeError("Supabase indisponível.")
    try:
        supabase.table(Tables.EGRESS_ASSIGNMENTS).delete().eq(EgressAssignmentModel.CLIENTE_ID, cid).execute()
        emit("proxy_change_event", cliente_id=cid, data={"action": "release"})
    except Exception as e:
        raise RuntimeError(str(e)) from e
    finally:
        _cache_invalidate(cid)


def get_proxy_config_for_waha(cliente_id: str) -> Optional[Dict[str, str]]:
    """
    Retorna dict para WAHA config.proxy, ou None se sem assignment.
    Nunca retorna 'type' (metadata) e não formata schema.
    """
    prof = get_profile(cliente_id)
    if not prof:
        return None
    if not prof.is_active:
        raise RuntimeError("Egress profile inativo.")
    server = prof.proxy_server()
    cfg: Dict[str, str] = {"server": server}
    if prof.username:
        cfg["username"] = prof.username
    if prof.password:
        cfg["password"] = prof.password
    return cfg

