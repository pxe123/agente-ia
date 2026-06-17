"""Testes do cliente HTTP de booking Agenda IA."""
from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

from services.agendamento_ia_book import (
    cancel_appointments_batch_in_agendamento_ia,
    create_appointment_in_agendamento_ia,
)


class TestAgendamentoIaBook:
    @patch("services.agendamento_ia_book.requests.post")
    @patch("services.agendamento_ia_book.agendamento_ia_configured", return_value=True)
    @patch("services.agendamento_ia_book.resolved_appointments_create_url", return_value="http://agenda/v1/integrations/zapaction/appointments")
    @patch("services.agendamento_ia_book.recurrence_external_sync_enabled", return_value=True)
    def test_create_success(self, _sync, _url, _cfg, mock_post):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.text = '{"appointment_id":"ext-123","status":"confirmed"}'
        mock_resp.json.return_value = {"appointment_id": "ext-123", "status": "confirmed"}
        mock_post.return_value = mock_resp

        starts = datetime(2026, 6, 16, 13, 0, tzinfo=timezone.utc)
        ends = datetime(2026, 6, 16, 13, 30, tzinfo=timezone.utc)
        ext, err = create_appointment_in_agendamento_ia(
            cliente_id="c1",
            zapaction_appointment_id="za-1",
            service_id="s1",
            provider_id="p1",
            starts_at=starts,
            ends_at=ends,
            contact_name="Maria",
            recurrence_series_id="series-1",
            series_occurrence_at=starts,
        )
        assert ext == "ext-123"
        assert err is None
        body = mock_post.call_args.kwargs["json"]
        assert body["recurrence"]["series_id"] == "series-1"

    @patch("services.agendamento_ia_book.requests.post")
    @patch("services.agendamento_ia_book.agendamento_ia_configured", return_value=True)
    @patch("services.agendamento_ia_book.resolved_appointments_create_url", return_value="http://agenda/v1/integrations/zapaction/appointments")
    @patch("services.agendamento_ia_book.recurrence_external_sync_enabled", return_value=True)
    def test_create_slot_ocupado(self, _sync, _url, _cfg, mock_post):
        mock_resp = MagicMock()
        mock_resp.status_code = 409
        mock_resp.text = '{"error":{"code":"slot_ocupado"}}'
        mock_resp.json.return_value = {"error": {"code": "slot_ocupado"}}
        mock_post.return_value = mock_resp

        starts = datetime(2026, 6, 16, 13, 0, tzinfo=timezone.utc)
        ext, err = create_appointment_in_agendamento_ia(
            cliente_id="c1",
            zapaction_appointment_id="za-1",
            service_id="s1",
            provider_id=None,
            starts_at=starts,
            ends_at=starts,
            contact_name="Maria",
        )
        assert ext is None
        assert err == "slot_ocupado"

    @patch("services.agendamento_ia_book.requests.post")
    @patch("services.agendamento_ia_book.agendamento_ia_configured", return_value=True)
    @patch("services.agendamento_ia_book.resolved_appointments_cancel_batch_url", return_value="http://agenda/v1/integrations/zapaction/appointments/cancel-batch")
    @patch("services.agendamento_ia_book.recurrence_external_sync_enabled", return_value=True)
    def test_cancel_batch(self, _sync, _url, _cfg, mock_post):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.text = '{"cancelled":2}'
        mock_resp.json.return_value = {"cancelled": 2}
        mock_post.return_value = mock_resp

        n, err = cancel_appointments_batch_in_agendamento_ia(
            cliente_id="c1",
            scope="following",
            series_id="series-1",
            from_starts_at=datetime(2026, 6, 16, tzinfo=timezone.utc),
        )
        assert n == 2
        assert err is None
