"""
Proteções do cadastro público: Turnstile, honeypot, e-mails descartáveis, logging.
"""
from __future__ import annotations

import logging
from typing import Any

import requests
from flask import Request

from base.config import settings

logger = logging.getLogger(__name__)

_TURNSTILE_VERIFY_URL = "https://challenges.cloudflare.com/turnstile/v0/siteverify"

# Domínios descartáveis comuns (lista curta; expandir conforme necessário).
_DISPOSABLE_DOMAINS: frozenset[str] = frozenset(
    {
        "mailinator.com",
        "guerrillamail.com",
        "guerrillamail.net",
        "guerrillamail.org",
        "sharklasers.com",
        "grr.la",
        "yopmail.com",
        "tempmail.com",
        "temp-mail.org",
        "10minutemail.com",
        "trashmail.com",
        "getnada.com",
        "maildrop.cc",
        "dispostable.com",
        "fakeinbox.com",
        "throwaway.email",
        "mailnesia.com",
        "mintemail.com",
        "spamgourmet.com",
        "mytemp.email",
    }
)


def is_production_environment() -> bool:
    env = (getattr(settings, "ENVIRONMENT", None) or "").strip().lower()
    if env in ("production", "prod"):
        return True
    return (getattr(settings, "FLASK_ENV", None) or "").strip().lower() == "production"


def get_client_ip(req: Request) -> str:
    xff = (req.headers.get("X-Forwarded-For") or "").strip()
    if xff:
        first = xff.split(",")[0].strip()
        if first:
            return first
    return (req.remote_addr or "unknown").strip() or "unknown"


def normalize_signup_email(raw: str) -> str:
    return (raw or "").strip().lower()


def honeypot_triggered(form: Any) -> bool:
    return bool((form.get("website") or "").strip())


def is_disposable_email(email: str) -> bool:
    normalized = normalize_signup_email(email)
    if "@" not in normalized:
        return False
    domain = normalized.rsplit("@", 1)[-1]
    return domain in _DISPOSABLE_DOMAINS


def turnstile_configured() -> bool:
    site = (getattr(settings, "TURNSTILE_SITE_KEY", None) or "").strip()
    secret = (getattr(settings, "TURNSTILE_SECRET_KEY", None) or "").strip()
    return bool(site and secret)


def verify_turnstile(token: str, remote_ip: str | None) -> bool:
    secret = (getattr(settings, "TURNSTILE_SECRET_KEY", None) or "").strip()
    if not secret or not (token or "").strip():
        return False
    payload: dict[str, str] = {"secret": secret, "response": token.strip()}
    if remote_ip and remote_ip != "unknown":
        payload["remoteip"] = remote_ip
    try:
        r = requests.post(_TURNSTILE_VERIFY_URL, data=payload, timeout=10)
        r.raise_for_status()
        data = r.json()
        return bool(data.get("success"))
    except Exception as e:
        logger.warning("turnstile_verify_failed: %s", e)
        return False


def check_turnstile_for_signup(token: str, remote_ip: str) -> tuple[bool, str | None]:
    """
    Retorna (ok, reason). reason usado em logs (turnstile_missing, turnstile_failed, …).
    """
    if not turnstile_configured():
        if is_production_environment():
            logger.error("turnstile_not_configured_in_production")
            return False, "turnstile_not_configured"
        logger.warning("turnstile_skipped_dev: chaves TURNSTILE_* ausentes")
        return True, None
    if not (token or "").strip():
        return False, "turnstile_missing"
    if not verify_turnstile(token, remote_ip):
        return False, "turnstile_failed"
    return True, None


def log_signup_event(
    event: str,
    *,
    ip: str,
    reason: str | None = None,
    email: str | None = None,
) -> None:
    """Log estruturado sem senha."""
    parts = [f"event={event}", f"ip={ip}"]
    if reason:
        parts.append(f"reason={reason}")
    if email:
        parts.append(f"email={normalize_signup_email(email)}")
    logger.info("signup_security %s", " ".join(parts))
