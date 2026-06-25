"""Testes de exclusão no painel e anti-reimportação."""
from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch

from services.agendamento_ia_appointment_webhook import process_appointment_webhook_payload
from services.scheduling.panel_purge import purge_appointment_from_panel


class TestPanelPurge(unittest.TestCase):
    @patch("services.scheduling.panel_purge.repository.delete_appointment_row", return_value=True)
    @patch("services.scheduling.panel_purge.repository.get_appointment")
    @patch("services.agendamento_ia_cancel.cancel_appointment_in_agendamento_ia")
    def test_purge_cancels_remote_before_delete(self, mock_cancel, mock_get, mock_delete):
        mock_get.return_value = {
            "id": "za-1",
            "external_agenda_appointment_id": "agenda-1",
            "remote_id": "5511999999999",
        }
        mock_cancel.return_value = (True, None)

        ok, err = purge_appointment_from_panel("cid", "za-1")

        self.assertTrue(ok)
        self.assertIsNone(err)
        mock_cancel.assert_called_once()
        mock_delete.assert_called_once_with("cid", "za-1")

    @patch("services.scheduling.panel_purge.repository.get_appointment")
    @patch("services.agendamento_ia_cancel.cancel_appointment_in_agendamento_ia")
    def test_purge_blocks_delete_when_remote_cancel_fails(self, mock_cancel, mock_get):
        mock_get.return_value = {
            "id": "za-1",
            "external_agenda_appointment_id": "agenda-1",
        }
        mock_cancel.return_value = (False, "timeout")

        ok, err = purge_appointment_from_panel("cid", "za-1")

        self.assertFalse(ok)
        self.assertEqual(err, "timeout")


class TestWebhookAntiResurrection(unittest.TestCase):
    @patch("services.agendamento_ia_appointment_webhook.supabase", new_callable=MagicMock)
    @patch("services.agendamento_ia_appointment_webhook.tenant_has_scheduling", return_value=True)
    @patch("services.agendamento_ia_appointment_webhook.sched_repo.get_appointment_by_external_agenda_id")
    @patch("services.agendamento_ia_appointment_webhook.sched_repo.get_service")
    @patch("services.agendamento_ia_appointment_webhook.sched_repo.list_services")
    def test_does_not_resurrect_cancelled_appointment(
        self,
        mock_list_services,
        mock_get_service,
        mock_get_ext,
        _tenant,
        _supabase,
    ):
        mock_get_ext.return_value = {
            "id": "za-1",
            "status": "cancelled",
            "meta": {},
        }
        mock_list_services.return_value = [{"id": "svc-1"}]
        mock_get_service.return_value = {"id": "svc-1"}

        payload = {
            "event": "appointment.created",
            "request_schema_version": 1,
            "event_id": "import-agenda-1",
            "cliente_id": "cid",
            "appointment_id": "agenda-1",
            "status": "confirmed",
            "starts_at": "2026-06-20T14:00:00+00:00",
            "ends_at": "2026-06-20T14:30:00+00:00",
            "service_id": "svc-1",
        }
        ok, err, code = process_appointment_webhook_payload(payload)

        self.assertTrue(ok)
        self.assertIsNone(err)
        self.assertEqual(code, 200)
        _supabase.table.return_value.update.assert_not_called()
        _supabase.table.return_value.insert.assert_not_called()


if __name__ == "__main__":
    unittest.main()
