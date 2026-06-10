"""Testes integração Google Calendar ↔ Agendamento IA."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

from services.agendamento_ia_google_status import (
    _normalize_provider_status,
    fetch_google_connect_authorize_url,
    fetch_google_status,
    fetch_google_status_by_providers,
    google_provider_ui_status,
    push_google_tokens_to_agendamento_ia,
)


@patch("services.agendamento_ia_google_status.requests.post")
@patch("services.agendamento_ia_google_status.agendamento_ia_base_url", return_value="https://agenda.example")
@patch("services.agendamento_ia_google_status.scheduling_integration_headers", return_value={})
def test_push_google_tokens(mock_headers, mock_base, mock_post):
    mock_post.return_value = MagicMock(status_code=200, json=lambda: {"ok": True})
    ok, err = push_google_tokens_to_agendamento_ia(
        "c1", provider_id="p1", refresh_token="rtok"
    )
    assert ok is True
    assert err is None
    assert mock_post.call_args.kwargs["json"]["refresh_token"] == "rtok"


@patch("services.agendamento_ia_google_status.requests.get")
@patch("services.agendamento_ia_google_status.agendamento_ia_base_url", return_value="https://agenda.example")
@patch("services.agendamento_ia_google_status.scheduling_integration_headers", return_value={"Authorization": "Bearer x"})
def test_fetch_google_status_provider(mock_headers, mock_base, mock_get):
    mock_get.return_value = MagicMock(
        status_code=200,
        json=lambda: {
            "provider_id": "p1",
            "refresh_token": True,
            "calendar_access": True,
            "freebusy_ok": True,
        },
    )
    out = fetch_google_status("c1", provider_id="p1")
    assert out is not None
    assert out.get("connected") is True
    mock_get.assert_called_once()
    assert mock_get.call_args.kwargs["params"]["provider_id"] == "p1"


@patch("services.agendamento_ia_google_status.requests.get")
@patch("services.agendamento_ia_google_status.agendamento_ia_base_url", return_value="https://agenda.example")
@patch("services.agendamento_ia_google_status.scheduling_integration_headers", return_value={})
def test_fetch_google_connect_authorize_url(mock_headers, mock_base, mock_get):
    mock_get.return_value = MagicMock(
        status_code=200,
        json=lambda: {"authorize_url": "https://accounts.google.com/o/oauth2/auth?x=1"},
    )
    url, err = fetch_google_connect_authorize_url(
        "c1",
        provider_id="p1",
        return_url="https://app.zapaction.com.br/painel/agenda?tab=profissionais",
    )
    assert err is None
    assert url and "accounts.google.com" in url


@patch("services.agendamento_ia_google_status.requests.get")
@patch("services.agendamento_ia_google_status.agendamento_ia_base_url", return_value="https://agenda.example")
@patch("services.agendamento_ia_google_status.scheduling_integration_headers", return_value={})
def test_fetch_google_connect_404_endpoint(mock_headers, mock_base, mock_get):
    mock_get.return_value = MagicMock(status_code=404, text="Not Found", json=lambda: {"detail": "not found"})
    url, err = fetch_google_connect_authorize_url("c1", provider_id="p1", return_url="https://app.zapaction.com.br/x")
    assert url is None
    assert err == "endpoint_connect_indisponivel"


@patch("services.agendamento_ia_google_status.fetch_google_status")
def test_fetch_google_status_by_providers(mock_fetch):
    mock_fetch.side_effect = lambda cid, provider_id=None, timeout_sec=15: {
        "provider_id": provider_id,
        "connected": provider_id == "a",
    }
    out = fetch_google_status_by_providers("c1", ["a", "b"])
    assert out["a"]["connected"] is True
    assert out["b"]["connected"] is False


def test_normalize_provider_status_adds_connected():
    data = {"refresh_token": True, "calendar_access": True, "freebusy_ok": True}
    out = _normalize_provider_status(data)
    assert out["connected"] is True


def test_google_provider_ui_status():
    assert google_provider_ui_status({"connected": True}) == "connected"
    assert google_provider_ui_status({"last_error": "x", "refresh_token": True}) == "needs_reconnect"
    assert google_provider_ui_status({"error": "http_500"}) == "error"
