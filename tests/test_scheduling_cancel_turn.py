"""Testes de cancelamento no motor interno (handle_turn operation=cancel)."""
from __future__ import annotations

import unittest
from unittest.mock import patch

from services.scheduling.service import handle_turn


class TestSchedulingCancelTurn(unittest.TestCase):
    @patch("services.scheduling.bookings.cancel_appointment", return_value=True)
    @patch("services.scheduling.service.scheduling_repository.supabase_available", return_value=True)
    @patch("services.scheduling.service.scheduling_repository.get_appointment")
    def test_cancel_by_appointment_id(self, mock_get, _supa, mock_cancel_fn):
        mock_get.return_value = {
            "id": "appt-1",
            "remote_id": "5521999999999",
            "starts_at": "2026-06-01T10:00:00+00:00",
        }
        out = handle_turn(
            {
                "operation": "cancel",
                "user_message": "",
                "context": {
                    "cliente_id": "client-1",
                    "remote_id": "5521999999999",
                },
                "booking": {"appointment_id": "appt-1"},
                "session": {},
            }
        )
        mock_cancel_fn.assert_called_once_with("client-1", "appt-1")
        self.assertEqual(out.get("api_status"), "ok")
        self.assertTrue(out.get("done"))
        self.assertEqual(out.get("data", {}).get("cancelled_appointment_id"), "appt-1")

    @patch("services.scheduling.service.scheduling_repository.supabase_available", return_value=True)
    @patch("services.scheduling.service.scheduling_repository.list_upcoming_by_remote_id")
    def test_cancel_no_upcoming(self, mock_list, _supa):
        mock_list.return_value = []
        out = handle_turn(
            {
                "operation": "cancel",
                "user_message": "",
                "context": {"cliente_id": "client-1", "remote_id": "5521999999999"},
                "session": {},
            }
        )
        self.assertEqual(out.get("api_status"), "error")
        self.assertEqual(out.get("error", {}).get("code"), "no_upcoming")

    @patch("services.scheduling.service.scheduling_repository.supabase_available", return_value=True)
    @patch("services.scheduling.service.scheduling_repository.ensure_settings")
    @patch("services.scheduling.service.scheduling_repository.list_professionals")
    @patch("services.scheduling.service.scheduling_repository.list_services")
    @patch("services.scheduling.service.scheduling_repository.list_working_hours_all")
    def test_missing_cliente_id(self, _wh, _svc, _prof, _settings, _supa):
        out = handle_turn({"user_message": "oi", "context": {}, "session": {}})
        self.assertEqual(out.get("api_status"), "error")
        self.assertEqual(out.get("error", {}).get("code"), "missing_cliente_id")


if __name__ == "__main__":
    unittest.main()
