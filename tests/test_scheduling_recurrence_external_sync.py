"""Testes de retry sync motor externo."""
from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import patch

from services.scheduling.recurrence import retry_pending_motor_sync


class TestRecurrenceExternalSync:
    @patch("services.agendamento_ia_book.create_appointment_in_agendamento_ia")
    @patch("services.scheduling.recurrence.repository")
    @patch("services.scheduling.engine.scheduling_uses_internal_motor", return_value=False)
    def test_retry_syncs_pending(self, _int, mock_repo, mock_create):
        starts = datetime(2026, 6, 16, 10, 0, tzinfo=timezone.utc)
        mock_repo.list_appointments_pending_motor_sync.return_value = [
            {
                "id": "a1",
                "cliente_id": "c1",
                "service_id": "s1",
                "professional_id": "p1",
                "starts_at": starts.isoformat(),
                "ends_at": starts.isoformat(),
                "status": "confirmed",
                "meta": {"zapaction_appointment_id": "a1", "contact_name": "Maria"},
            }
        ]
        mock_repo.parse_row_datetime.side_effect = lambda v: starts if v else None
        mock_create.return_value = ("ext-99", None)

        stats = retry_pending_motor_sync("c1", limit=10)
        assert stats["synced"] == 1
        mock_repo.set_appointment_external_id.assert_called_once()
