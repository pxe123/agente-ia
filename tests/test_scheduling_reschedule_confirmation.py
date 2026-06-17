"""Testes — remarcação de confirmado com confirmação do cliente."""
from __future__ import annotations

import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

from services.scheduling.confirmation_actions import (
    _execute_decline_proposal,
    client_choose_alternative_slot,
    propose_reschedule_confirmed,
)


class TestProposeRescheduleConfirmed(unittest.TestCase):
    @patch("services.scheduling.confirmation_notify.notify_client_proposal")
    @patch("services.scheduling.confirmation_actions.create_proposal_token")
    @patch("services.scheduling.confirmation_actions.repository.insert_proposal")
    @patch("services.scheduling.confirmation_actions.repository.supersede_open_proposals")
    @patch("services.scheduling.confirmation_actions.repository.merge_appointment_meta")
    @patch("services.scheduling.confirmation_actions.repository.update_appointment_status")
    @patch("services.scheduling.bookings.check_reschedule_slot")
    @patch("services.scheduling.confirmation_actions.repository.get_appointment")
    def test_confirmed_goes_pending_and_notifies(
        self,
        mock_get,
        mock_check,
        mock_status,
        mock_meta,
        mock_supersede,
        mock_insert,
        mock_token,
        mock_notify,
    ):
        starts = datetime(2026, 5, 28, 14, 0, tzinfo=timezone.utc)
        mock_get.return_value = {
            "id": "appt-1",
            "status": "confirmed",
            "contact_phone": "5511999999999",
            "professional_id": "prof-1",
            "service_id": "svc-1",
            "starts_at": starts.isoformat(),
            "ends_at": (starts + timedelta(minutes=30)).isoformat(),
            "meta": {},
        }
        mock_check.return_value = (True, None, None)
        mock_status.return_value = True
        mock_insert.return_value = {"id": "prop-1"}
        mock_token.return_value = "https://app.example.com/confirmacao/tok"

        prop, err, offer = propose_reschedule_confirmed(
            "cid",
            "appt-1",
            proposed_starts_at=starts + timedelta(days=1),
            duration_minutes=30,
            professional_id="prof-1",
            proposed_by="panel_user:1",
        )

        self.assertIsNotNone(prop)
        self.assertIsNone(err)
        self.assertIsNone(offer)
        mock_status.assert_called_with("cid", "appt-1", "pending")
        mock_notify.assert_called_once()
        self.assertTrue(mock_notify.call_args.kwargs.get("is_reschedule"))

    @patch("services.scheduling.confirmation_actions.repository.get_appointment")
    def test_rejects_without_phone(self, mock_get):
        mock_get.return_value = {
            "id": "appt-1",
            "status": "confirmed",
            "contact_phone": "",
            "remote_id": "",
            "professional_id": "prof-1",
        }
        prop, err, offer = propose_reschedule_confirmed(
            "cid",
            "appt-1",
            proposed_starts_at=datetime.now(timezone.utc),
            duration_minutes=30,
            professional_id="prof-1",
            proposed_by="panel",
        )
        self.assertIsNone(prop)
        self.assertEqual(err, "sem_telefone_cliente")


class TestDeclineProposalKeepsPending(unittest.TestCase):
    @patch("services.scheduling.confirmation_actions.repository.merge_appointment_meta")
    @patch("services.scheduling.confirmation_actions.repository.update_proposal_status")
    @patch("services.scheduling.confirmation_actions.repository.get_appointment")
    def test_decline_stays_pending_for_slot_choice(
        self,
        mock_get,
        mock_prop_status,
        mock_meta,
    ):
        mock_get.return_value = {
            "id": "appt-1",
            "status": "pending",
            "meta": {"reschedule_from_confirmed": True},
        }
        ok, err = _execute_decline_proposal(
            {
                "id": "tok-1",
                "cliente_id": "cid",
                "appointment_id": "appt-1",
                "proposal_id": "prop-1",
            }
        )
        self.assertTrue(ok)
        self.assertIsNone(err)
        mock_meta.assert_called_once()
        patch = mock_meta.call_args[0][2]
        self.assertTrue(patch.get("awaiting_client_slot"))


class TestClientChooseAlternativeSlot(unittest.TestCase):
    @patch("services.scheduling.confirmation_notify.notify_client_slot_submitted")
    @patch("services.scheduling.confirmation_notify.notify_pending_booking")
    @patch("services.scheduling.confirmation_actions.repository.mark_confirmation_token_used")
    @patch("services.scheduling.confirmation_actions.repository.merge_appointment_meta")
    @patch("services.scheduling.bookings.reschedule_appointment")
    @patch("services.scheduling.bookings.check_reschedule_slot")
    @patch("services.scheduling.confirmation_actions.repository.get_service")
    @patch("services.scheduling.confirmation_actions.repository.get_appointment")
    @patch("services.scheduling.confirmation_actions.resolve_token")
    def test_submits_slot_and_notifies(
        self,
        mock_resolve,
        mock_get_appt,
        mock_svc,
        mock_check,
        mock_resched,
        mock_meta,
        mock_mark,
        mock_notify_clinic,
        mock_notify_client,
    ):
        starts = datetime(2026, 6, 1, 10, 0, tzinfo=timezone.utc)
        mock_resolve.return_value = (
            {"id": "tok-1", "cliente_id": "cid", "appointment_id": "appt-1"},
            None,
        )
        mock_get_appt.return_value = {
            "id": "appt-1",
            "status": "pending",
            "service_id": "svc-1",
            "professional_id": "prof-1",
        }
        mock_svc.return_value = {"duration_minutes": 30}
        mock_check.return_value = (True, None, None)
        mock_resched.return_value = (True, None, None)

        ok, err = client_choose_alternative_slot("raw-token", starts.isoformat())
        self.assertTrue(ok)
        self.assertIsNone(err)
        mock_mark.assert_called_once()
        mock_notify_clinic.assert_called_once()
        mock_notify_client.assert_called_once()


if __name__ == "__main__":
    unittest.main()
