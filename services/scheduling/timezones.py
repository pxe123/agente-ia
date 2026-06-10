"""
Fusos horários disponíveis na agenda (IANA + rótulos pt-BR).
"""
from __future__ import annotations

from datetime import timedelta, timezone

DEFAULT_TIMEZONE = "America/Sao_Paulo"

# (id IANA, rótulo para o utilizador) — ordem de exibição no select
TIMEZONE_CHOICE_GROUPS: list[tuple[str, list[tuple[str, str]]]] = [
    (
        "Brasil",
        [
            (DEFAULT_TIMEZONE, "São Paulo, Rio, Brasília, Curitiba, Belo Horizonte (UTC−3)"),
            ("America/Fortaleza", "Fortaleza, Recife, Salvador, Natal (UTC−3)"),
            ("America/Manaus", "Manaus, Porto Velho (horário do Amazonas, UTC−4)"),
            ("America/Cuiaba", "Cuiabá, Campo Grande (UTC−4)"),
            ("America/Rio_Branco", "Rio Branco, Acre (UTC−5)"),
            ("America/Noronha", "Fernando de Noronha (UTC−2)"),
        ],
    ),
    (
        "Portugal e PALOP",
        [
            ("Europe/Lisbon", "Portugal continental (Lisboa)"),
            ("Atlantic/Azores", "Açores"),
            ("Africa/Luanda", "Angola (Luanda)"),
            ("Africa/Maputo", "Moçambique (Maputo)"),
        ],
    ),
    (
        "Outros",
        [
            ("UTC", "UTC (coordenado universal)"),
            ("Europe/London", "Reino Unido (Londres)"),
            ("Europe/Paris", "França (Paris)"),
            ("Europe/Berlin", "Alemanha (Berlim)"),
            ("America/New_York", "EUA — Costa leste (Nova Iorque)"),
            ("America/Chicago", "EUA — Centro (Chicago)"),
            ("America/Denver", "EUA — Montanhas (Denver)"),
            ("America/Los_Angeles", "EUA — Costa oeste (Los Angeles)"),
            ("America/Argentina/Buenos_Aires", "Argentina (Buenos Aires)"),
            ("America/Santiago", "Chile (Santiago)"),
        ],
    ),
]

# Offsets fixos quando ZoneInfo/tzdata não está disponível (sem horário de verão histórico).
_FIXED_OFFSET_HOURS: dict[str, int] = {
    DEFAULT_TIMEZONE: -3,
    "America/Fortaleza": -3,
    "America/Belem": -3,
    "America/Recife": -3,
    "America/Maceio": -3,
    "America/Bahia": -3,
    "America/Manaus": -4,
    "America/Cuiaba": -4,
    "America/Campo_Grande": -4,
    "America/Porto_Velho": -4,
    "America/Boa_Vista": -4,
    "America/Rio_Branco": -5,
    "America/Noronha": -2,
    "Europe/Lisbon": 0,
    "Atlantic/Azores": -1,
    "Africa/Luanda": 1,
    "Africa/Maputo": 2,
    "UTC": 0,
    "Europe/London": 0,
    "Europe/Paris": 1,
    "Europe/Berlin": 1,
    "America/New_York": -5,
    "America/Chicago": -6,
    "America/Denver": -7,
    "America/Los_Angeles": -8,
    "America/Argentina/Buenos_Aires": -3,
    "America/Santiago": -4,
}


def _all_choice_ids() -> frozenset[str]:
    ids: list[str] = []
    for _, choices in TIMEZONE_CHOICE_GROUPS:
        ids.extend(k for k, _ in choices)
    return frozenset(ids)


ALLOWED_TIMEZONES = _all_choice_ids()


def normalize_timezone(value: str | None) -> str:
    """Devolve fuso da lista ou o padrão (São Paulo)."""
    v = (value or "").strip()
    if v in ALLOWED_TIMEZONES:
        return v
    return DEFAULT_TIMEZONE


def timezone_label(iana: str | None) -> str:
    v = (iana or "").strip() or DEFAULT_TIMEZONE
    for _, choices in TIMEZONE_CHOICE_GROUPS:
        for kid, lbl in choices:
            if kid == v:
                return lbl
    return v


def fixed_offset_tz_fallback(iana: str) -> timezone | None:
    """Timezone fixo para IANA conhecido; None se não houver fallback."""
    hours = _FIXED_OFFSET_HOURS.get((iana or "").strip())
    if hours is None:
        return None
    return timezone(timedelta(hours=hours))
