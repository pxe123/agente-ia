import os
from typing import Optional

from base.config import settings


def get_redis_url() -> str:
    url = (getattr(settings, "REDIS_URL", None) or "").strip()
    if url:
        return url
    # Compat: alguns ambientes usam REDIS_TLS_URL/REDISGREEN_URL
    for k in ("REDIS_TLS_URL", "REDISGREEN_URL"):
        v = (os.getenv(k) or "").strip()
        if v:
            return v
    return ""


def get_default_queue():
    """
    Retorna uma fila RQ se Redis estiver configurado; senão, None.
    Mantém o app funcional localmente sem Redis.
    """
    redis_url = get_redis_url()
    if not redis_url:
        return None
    try:
        from redis import Redis  # type: ignore
        from rq import Queue  # type: ignore
    except Exception:
        return None
    try:
        conn = Redis.from_url(redis_url)
        return Queue("default", connection=conn)
    except Exception:
        return None


def enqueue(func_path: str, *args, **kwargs) -> Optional[str]:
    """
    Enfileira um job em RQ. func_path é 'modulo.funcao'.
    Retorna job_id ou None (se não há fila).
    """
    q = get_default_queue()
    if q is None:
        return None
    job = q.enqueue(func_path, *args, **kwargs)
    return getattr(job, "id", None)

