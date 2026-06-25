"""Webhook Agenda IA dispara WhatsApp ao cliente na criação pending."""
from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch

from services.agendamento_ia_appointment_webhook import (
    _dispatch_webhook_notifications,
    _normalize_webhook_phone,
)


class TestNormalizeWebhookPhone(unittest.TestCase):
    def test_normalizes_masked_br_phone(self):
        phone, remote = _normalize_webhook_phone("(14) 99675-5366", "")
        self.assertEqual(phone, "5514996755366")
        self.assertEqual(remote, "5514996755366")

    def test_keeps_e164(self):
        phone, remote = _normalize_webhook_phone("5514996755366", "5514996755366")
        self.assertEqual(phone, "5514996755366")
        self.assertEqual(remote, "5514996755366")


class TestDispatchWebhookNotifications(unittest.TestCase):
    @patch("services.agendamento_ia_appointment_webhook.sched_repo.get_appointment_by_external_agenda_id")
    @patch("services.scheduling.confirmation_notify.notify_client_booking_received")
    @patch("services.scheduling.confirmation_notify.notify_pending_booking")
    def test_pending_insert_notifies_client_and_clinic(
        self, mock_clinic, mock_client, mock_get
    ):
        mock_get.return_value = {
            "id": "za-appt-1",
            "status": "pending",
            "contact_phone": "5514996755366",
        }
        mock_clinic.return_value = True
        mock_client.return_value = True

        _dispatch_webhook_notifications(
            cliente_id="cid",
            agenda_appointment_id="agenda-appt-1",
            event="appointment.created",
            status="pending",
            is_new=True,
        )

        mock_clinic.assert_called_once()
        mock_client.assert_called_once_with("cid", "za-appt-1")

    @patch("services.agendamento_ia_appointment_webhook.sched_repo.get_appointment_by_external_agenda_id")
    @patch("services.scheduling.confirmation_notify.notify_client_booking_received")
    def test_skips_when_not_new(self, mock_client, mock_get):
        _dispatch_webhook_notifications(
            cliente_id="cid",
            agenda_appointment_id="agenda-appt-1",
            event="appointment.created",
            status="pending",
            is_new=False,
        )
        mock_get.assert_not_called()
        mock_client.assert_not_called()


if __name__ == "__main__":
    unittest.main()
