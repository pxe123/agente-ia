"""Testes OAuth Google no ZapAction."""
from __future__ import annotations

from unittest.mock import patch

from services.google_calendar_oauth import (
    sign_oauth_state,
    verify_oauth_state,
)


@patch("services.google_calendar_oauth.settings")
def test_sign_and_verify_oauth_state(mock_settings):
    mock_settings.SECRET_KEY = "test-secret-key"
    state = sign_oauth_state(cliente_id="cliente-uuid-1", provider_id="provider-uuid-2")
    parsed = verify_oauth_state(state)
    assert parsed == ("cliente-uuid-1", "provider-uuid-2")


@patch("services.google_calendar_oauth.settings")
def test_verify_oauth_state_rejects_tamper(mock_settings):
    mock_settings.SECRET_KEY = "test-secret-key"
    state = sign_oauth_state(cliente_id="c1", provider_id="p1")
    bad = state[:-1] + ("x" if state[-1] != "x" else "y")
    assert verify_oauth_state(bad) is None
