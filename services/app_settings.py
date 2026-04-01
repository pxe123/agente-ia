"""
Leitura da tabela singleton app_settings (flags globais do SaaS).
Fallback seguro: se a tabela não existir ou houver erro, assume todos os canais habilitados.
"""
from __future__ import annotations

import time
from typing import Any, Dict

from database.supabase_sq import supabase
from database.models import AppSettingsModel, Tables

_CACHE_TTL_SEC = 30.0
_cache_at: float = 0.0
_cache_value: Dict[str, Any] = {
    "instagram_enabled": True,
    "messenger_enabled": True,
    "whatsapp_enabled": True,
}


def get_global_settings() -> Dict[str, Any]:
    """
    Consulta app_settings (id=1) no Supabase.
    Retorno inclui instagram_enabled, messenger_enabled, whatsapp_enabled (defaults True).
    Cache em memória com TTL de 30s para reduzir leituras repetidas.
    Em falha de rede/schema, retorna fallback com os três canais True.
    """
    global _cache_at, _cache_value
    now = time.monotonic()
    if now - _cache_at < _CACHE_TTL_SEC:
        return dict(_cache_value)

    default = {
        "instagram_enabled": True,
        "messenger_enabled": True,
        "whatsapp_enabled": True,
    }
    if not supabase:
        _cache_value = default
        _cache_at = now
        return dict(_cache_value)

    try:
        r = (
            supabase.table(Tables.APP_SETTINGS)
            .select(
                ",".join(
                    [
                        AppSettingsModel.INSTAGRAM_ENABLED,
                        AppSettingsModel.MESSENGER_ENABLED,
                        AppSettingsModel.WHATSAPP_ENABLED,
                    ]
                )
            )
            .eq(AppSettingsModel.ID, 1)
            .limit(1)
            .execute()
        )
        row = (r.data or [{}])[0] if r.data else {}
        _cache_value = {
            "instagram_enabled": bool(row.get(AppSettingsModel.INSTAGRAM_ENABLED, True)),
            "messenger_enabled": bool(row.get(AppSettingsModel.MESSENGER_ENABLED, True)),
            "whatsapp_enabled": bool(row.get(AppSettingsModel.WHATSAPP_ENABLED, True)),
        }
    except Exception:
        _cache_value = default

    _cache_at = now
    return dict(_cache_value)


def get_global_channel_flags() -> Dict[str, bool]:
    """
    Compatibilidade: só as três flags de canal, a partir do cache de get_global_settings().
    """
    s = get_global_settings()
    return {
        "instagram_enabled": bool(s.get("instagram_enabled", True)),
        "messenger_enabled": bool(s.get("messenger_enabled", True)),
        "whatsapp_enabled": bool(s.get("whatsapp_enabled", True)),
    }


def invalidate_global_channel_flags_cache() -> None:
    """Chamar após PATCH admin para refletir imediatamente neste worker."""
    global _cache_at
    _cache_at = 0.0


def invalidate_global_settings_cache() -> None:
    """Alias explícito para invalidar o cache de get_global_settings()."""
    invalidate_global_channel_flags_cache()
