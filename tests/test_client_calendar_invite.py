"""Testes — convite de calendário ao cliente via WhatsApp."""
from __future__ import annotations

import unittest
from datetime import datetime, timezone
from unittest.mock import patch

from services.scheduling.client_calendar_invite import (
    build_calendar_add_url,
    build_invite_message_parts,
    client_calendar_invites_enabled,
    maybe_send_client_calendar_invite,
)


class TestCalendarAddUrl(unittest.TestCase):
    def test_url_uses_clinic_timezone(self):
        row = {
            "starts_at": "2026-06-21T17:00:00+00:00",
            "ends_at": "2026-06-21T18:00:00+00:00",
            "notes": "",
        }
        ctx = {
            "tz": "America/Sao_Paulo",
            "clinic_name": "Clínica Teste",
            "service_name": "Consulta",
            "prof_name": "Dr. João",
            "contact_name": "Maria",
            "when": "21/06/2026 14:00",
        }
        url = build_calendar_add_url(row, ctx)
        self.assertIn("calendar.google.com/calendar/render", url)
        self.assertIn("action=TEMPLATE", url)
        self.assertIn("America%2FSao_Paulo", url)
        self.assertIn("20260621T140000", url)
        self.assertIn("20260621T150000", url)


class TestInviteCopy(unittest.TestCase):
    def test_confirmed_copy(self):
        intro, cta = build_invite_message_parts(
            {},
            {
                "contact_name": "Maria",
                "when": "21/06/2026 14:30",
                "service_name": "Consulta",
            },
            kind="confirmed",
        )
        self.assertIn("Maria", intro)
        self.assertIn("confirmado", intro)
        self.assertIn("Adicionar ao calendário", cta)
        self.assertNotIn("Google", intro + cta)

    def test_rescheduled_copy_differs(self):
        intro, cta = build_invite_message_parts(
            {},
            {"contact_name": "Maria", "when": "16/07/2026 10:00", "service_name": "Consulta"},
            kind="rescheduled",
        )
        self.assertIn("remarcado", intro)
        self.assertIn("Atualize sua agenda", cta)


class TestMaybeSendInvite(unittest.TestCase):
    @patch("services.scheduling.engine.scheduling_uses_internal_motor", return_value=True)
    @patch("services.scheduling.client_calendar_invite._send_invite_whatsapp")
    @patch("services.scheduling.client_calendar_invite.repository.merge_appointment_meta")
    @patch("services.scheduling.client_calendar_invite.repository.get_professional")
    @patch("services.scheduling.client_calendar_invite.repository.get_service")
    @patch("services.scheduling.client_calendar_invite.repository.get_settings")
    def test_sends_when_confirmed(
        self, mock_settings, mock_service, mock_prof, mock_merge, mock_send, _mock_motor
    ):
        mock_settings.return_value = {"timezone": "America/Sao_Paulo", "public_name": "Clínica"}
        mock_service.return_value = {"name": "Consulta"}
        mock_prof.return_value = {"name": "Dr."}
        mock_send.return_value = (True, None)
        row = {
            "id": "appt-1",
            "status": "confirmed",
            "contact_phone": "5511999999999",
            "starts_at": "2026-06-21T17:00:00+00:00",
            "ends_at": "2026-06-21T18:00:00+00:00",
            "service_id": "svc",
            "professional_id": "prof",
            "meta": {"contact_name": "Maria"},
        }
        ok, err = maybe_send_client_calendar_invite("cid", row)
        self.assertTrue(ok)
        self.assertIsNone(err)
        mock_send.assert_called_once()
        mock_merge.assert_called_once()

    @patch("services.scheduling.engine.scheduling_uses_internal_motor", return_value=True)
    @patch("services.scheduling.client_calendar_invite._send_invite_whatsapp")
    def test_skips_pending(self, mock_send, _mock_motor):
        row = {
            "id": "appt-1",
            "status": "pending",
            "contact_phone": "5511999999999",
            "starts_at": datetime.now(timezone.utc).isoformat(),
            "ends_at": datetime.now(timezone.utc).isoformat(),
            "meta": {},
        }
        ok, err = maybe_send_client_calendar_invite("cid", row)
        self.assertFalse(ok)
        self.assertEqual(err, "nao_confirmado")
        mock_send.assert_not_called()

    @patch("services.scheduling.engine.scheduling_uses_internal_motor", return_value=True)
    @patch("services.scheduling.client_calendar_invite._send_invite_whatsapp")
    def test_idempotent_for_same_starts_at(self, mock_send, _mock_motor):
        row = {
            "id": "appt-1",
            "status": "confirmed",
            "contact_phone": "5511999999999",
            "starts_at": "2026-06-21T17:00:00+00:00",
            "ends_at": "2026-06-21T18:00:00+00:00",
            "service_id": "svc",
            "professional_id": "prof",
            "meta": {
                "calendar_invite_for_starts_at": "2026-06-21T17:00:00+00:00",
                "calendar_invite_sent_at": "2026-06-20T10:00:00+00:00",
            },
        }
        ok, err = maybe_send_client_calendar_invite("cid", row)
        self.assertFalse(ok)
        self.assertEqual(err, "ja_enviado")
        mock_send.assert_not_called()

    def test_flag_default_enabled(self):
        self.assertTrue(client_calendar_invites_enabled())


class TestRecurrenceSummaryCalendar(unittest.TestCase):
    @patch("services.scheduling.recurrence.repository.merge_appointment_meta")
    @patch("services.scheduling.recurrence.repository.list_series_appointments_from_date")
    @patch("services.scheduling.confirmation_notify.send_scheduling_whatsapp_text")
    @patch("services.scheduling.recurrence.repository.get_settings")
    def test_summary_includes_first_occurrence_link(
        self, mock_settings, mock_send, mock_list, mock_merge
    ):
        from database.models import SchedulingRecurrenceSeriesModel
        from services.scheduling.recurrence import notify_recurrence_series_summary

        mock_settings.return_value = {"timezone": "America/Sao_Paulo"}
        mock_send.return_value = (True, None)
        mock_list.return_value = [
            {
                "id": "occ-1",
                "status": "confirmed",
                "starts_at": "2026-06-21T17:00:00+00:00",
                "ends_at": "2026-06-21T18:00:00+00:00",
                "service_id": "svc",
                "professional_id": "prof",
                "contact_phone": "5511999999999",
                "meta": {"contact_name": "Maria"},
            }
        ]
        series = {
            SchedulingRecurrenceSeriesModel.ID: "series-1",
            SchedulingRecurrenceSeriesModel.CONTACT_PHONE: "5511999999999",
            SchedulingRecurrenceSeriesModel.CONTACT_NAME: "Maria",
            SchedulingRecurrenceSeriesModel.FREQUENCY: "weekly",
            SchedulingRecurrenceSeriesModel.RULE: {"days_of_week": [0]},
            SchedulingRecurrenceSeriesModel.TIME_LOCAL: "10:00:00",
            SchedulingRecurrenceSeriesModel.STARTS_ON: "2026-06-01",
        }
        with patch("services.scheduling.recurrence.repository.get_service", return_value={"name": "Consulta"}):
            with patch("services.scheduling.recurrence.repository.get_professional", return_value={"name": "Dr."}):
                with patch(
                    "services.scheduling.recurrence.repository.get_settings",
                    return_value={"timezone": "America/Sao_Paulo", "public_name": "Clínica"},
                ):
                    ok, err = notify_recurrence_series_summary("cid", series)
        self.assertTrue(ok)
        self.assertIsNone(err)
        sent_text = mock_send.call_args[0][2]
        self.assertIn("Adicionar ao calendário", sent_text)
        self.assertIn("calendar.google.com", sent_text)
        mock_merge.assert_called_once()


if __name__ == "__main__":
    unittest.main()
