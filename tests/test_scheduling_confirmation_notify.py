"""Testes — notificações WhatsApp e token único de proposta."""
from __future__ import annotations

import unittest
from datetime import datetime, timezone
from unittest.mock import patch

from services.scheduling.confirmation_actions import resolve_proposal_choice
from services.scheduling.confirmation_notify import (
    notify_client_cancelled,
    notify_pending_booking,
)
from services.scheduling.confirmation_tokens import create_proposal_token


class TestNormalizeDestPhone(unittest.TestCase):
    def test_adds_brazil_country_code(self):
        from services.scheduling.confirmation_notify import _normalize_dest_phone

        self.assertEqual(_normalize_dest_phone("(14) 99999-9999"), "5514999999999")
        self.assertEqual(_normalize_dest_phone("5514999999999"), "5514999999999")
        self.assertEqual(_normalize_dest_phone("invalid"), "")


class TestNotifyPendingBooking(unittest.TestCase):
    @patch("services.scheduling.confirmation_notify._send_whatsapp")
    @patch("services.scheduling.confirmation_notify._clinic_notify_phone")
    @patch("services.scheduling.confirmation_notify._appointment_context")
    def test_sends_to_clinic_when_notify_whatsapp_set(
        self, mock_ctx, mock_clinic_phone, mock_send
    ):
        mock_ctx.return_value = {
            "row": {"professional_id": "prof-1"},
            "service_name": "Corte",
            "prof_name": "Ricardo",
            "when": "28/05 14:00",
            "contact_name": "Maria",
            "contact_phone": "5511999999999",
        }
        mock_clinic_phone.return_value = "5511888888888"
        mock_send.return_value = (True, None)

        ok = notify_pending_booking("cid", {"id": "appt-1"})
        self.assertTrue(ok)
        mock_send.assert_called_once()
        args = mock_send.call_args[0]
        self.assertEqual(args[1], "5511888888888")
        self.assertIn("pendente", args[2].lower())

    @patch("services.scheduling.confirmation_notify._send_whatsapp")
    @patch("services.scheduling.confirmation_notify.repository.get_professional")
    @patch("services.scheduling.confirmation_notify._clinic_notify_phone")
    @patch("services.scheduling.confirmation_notify._appointment_context")
    def test_fallback_professional_without_clinic_phone(
        self, mock_ctx, mock_clinic_phone, mock_get_prof, mock_send
    ):
        mock_ctx.return_value = {
            "row": {"professional_id": "prof-1"},
            "service_name": "Corte",
            "prof_name": "Ricardo",
            "when": "28/05 14:00",
            "contact_name": "Maria",
            "contact_phone": "5511999999999",
        }
        mock_clinic_phone.return_value = ""
        mock_get_prof.return_value = {"whatsapp_notify_phone": "5511777777777"}
        mock_send.return_value = (True, None)

        ok = notify_pending_booking("cid", {"id": "appt-1"})
        self.assertTrue(ok)
        mock_send.assert_called_once_with(
            "cid", "5511777777777", unittest.mock.ANY
        )


class TestNotifyClientCancelled(unittest.TestCase):
    @patch("services.scheduling.confirmation_notify._send_whatsapp")
    @patch("services.scheduling.confirmation_notify._clinic_whatsapp_link")
    @patch("services.scheduling.confirmation_notify._appointment_context")
    def test_sends_cancel_message(self, mock_ctx, mock_link, mock_send):
        mock_ctx.return_value = {
            "service_name": "Consulta",
            "when": "18/06 10:00",
            "phone": "5514999999999",
        }
        mock_link.return_value = "https://wa.me/5511888888888"
        mock_send.return_value = (True, None)

        ok = notify_client_cancelled("cid", "appt-1")
        self.assertTrue(ok)
        mock_send.assert_called_once()
        text = mock_send.call_args[0][2]
        self.assertIn("cancelado", text.lower())
        self.assertIn("Consulta", text)


class TestCancelAppointmentNotify(unittest.TestCase):
    @patch("services.scheduling.confirmation_notify.notify_client_cancelled")
    @patch("services.scheduling.bookings.repository.update_appointment_status", return_value=True)
    @patch("services.scheduling.bookings.repository.get_appointment")
    def test_notify_when_clinic_cancels_confirmed(
        self, mock_get, mock_update, mock_notify
    ):
        from services.scheduling.bookings import cancel_appointment

        mock_get.return_value = {"status": "confirmed"}
        ok = cancel_appointment("cid", "appt-1", notify_client=True)
        self.assertTrue(ok)
        mock_notify.assert_called_once_with("cid", "appt-1")

    @patch("services.scheduling.confirmation_notify.notify_client_cancelled")
    @patch("services.scheduling.bookings.repository.update_appointment_status", return_value=True)
    @patch("services.scheduling.bookings.repository.get_appointment")
    def test_no_notify_when_client_self_cancel(self, mock_get, mock_update, mock_notify):
        from services.scheduling.bookings import cancel_appointment

        mock_get.return_value = {"status": "confirmed"}
        ok = cancel_appointment("cid", "appt-1")
        self.assertTrue(ok)
        mock_notify.assert_not_called()


class TestCreateProposalToken(unittest.TestCase):
    @patch("services.scheduling.confirmation_tokens.public_base_url")
    @patch("services.scheduling.confirmation_tokens.repository.insert_confirmation_token")
    def test_single_url_with_resolve_proposal(self, mock_insert, mock_base):
        mock_base.return_value = "https://app.example.com"
        url = create_proposal_token(
            cliente_id="cid",
            appointment_id="appt-1",
            proposal_id="prop-1",
        )
        self.assertIn("https://app.example.com/confirmacao/", url)
        mock_insert.assert_called_once()
        kwargs = mock_insert.call_args.kwargs
        self.assertEqual(kwargs["action"], "resolve_proposal")
        self.assertEqual(kwargs["proposal_id"], "prop-1")


class TestResolveProposalChoice(unittest.TestCase):
    @patch("services.scheduling.confirmation_actions._execute_decline_proposal")
    @patch("services.scheduling.confirmation_actions.resolve_token")
    def test_resolve_proposal_decline(self, mock_resolve, mock_decline):
        mock_resolve.return_value = (
            {"id": "t1", "action": "resolve_proposal", "cliente_id": "c", "appointment_id": "a"},
            None,
        )
        mock_decline.return_value = (True, None)

        ok, err, appt = resolve_proposal_choice("token-raw", "decline")
        self.assertTrue(ok)
        self.assertIsNone(err)
        self.assertIsNone(appt)
        mock_decline.assert_called_once()

    @patch("services.scheduling.confirmation_actions._execute_accept_proposal")
    @patch("services.scheduling.confirmation_actions.resolve_token")
    def test_resolve_proposal_accept(self, mock_resolve, mock_accept):
        mock_resolve.return_value = (
            {"id": "t1", "action": "resolve_proposal"},
            None,
        )
        mock_accept.return_value = (True, None, {"id": "appt"})

        ok, err, appt = resolve_proposal_choice("token-raw", "accept")
        self.assertTrue(ok)
        self.assertIsNone(err)
        self.assertEqual(appt, {"id": "appt"})


if __name__ == "__main__":
    unittest.main()
