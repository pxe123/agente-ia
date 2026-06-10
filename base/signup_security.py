"""
Rate limit dedicado ao cadastro público (POST /cadastro).
Mais restrito que login (base/auth_login_security.py).
"""
import time
from typing import Final

_SIGNUP_HOURLY: dict[str, list[float]] = {}
_SIGNUP_DAILY: dict[str, list[float]] = {}

_HOUR_LIMIT: Final[int] = 3
_HOUR_WINDOW_SEC: Final[int] = 60 * 60
_DAY_LIMIT: Final[int] = 10
_DAY_WINDOW_SEC: Final[int] = 24 * 60 * 60


def _prune(bucket: list[float], now: float, window_sec: int) -> list[float]:
    return [t for t in bucket if now - t < window_sec]


def signup_rate_limit_exceeded(ip: str) -> bool:
    """True se o IP excedeu cadastros na janela horária ou diária."""
    key = (ip or "unknown").strip() or "unknown"
    now = time.time()

    hourly = _prune(_SIGNUP_HOURLY.get(key, []), now, _HOUR_WINDOW_SEC)
    daily = _prune(_SIGNUP_DAILY.get(key, []), now, _DAY_WINDOW_SEC)

    if len(hourly) >= _HOUR_LIMIT or len(daily) >= _DAY_LIMIT:
        _SIGNUP_HOURLY[key] = hourly
        _SIGNUP_DAILY[key] = daily
        return True

    hourly.append(now)
    daily.append(now)
    _SIGNUP_HOURLY[key] = hourly
    _SIGNUP_DAILY[key] = daily
    return False
