"""Testes idempotência de reserva (evitar duplo agendamento)."""
from __future__ import annotations

import unittest
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

from services.scheduling.bookings import book_appointment


class TestBookAppointmentIdempotency(unittest.TestCase):
    @patch("services.scheduling.confirmation_notify.notify_pending_booking")
    @patch("services.scheduling.bookings.repository.find_overlapping_appointments", return_value=[])
    @patch("services.scheduling.bookings.repository.insert_appointment")
    @patch("services.scheduling.bookings.repository.busy_intervals_utc", return_value=[])
    @patch("services.scheduling.bookings.repository.find_existing_booking_for_contact")
    @patch("services.scheduling.confirmation_policy.build_booking_meta_patch", return_value={})
    @patch("services.scheduling.confirmation_policy.resolve_initial_appointment_status", return_value="pending")
    def test_returns_existing_without_insert_or_notify(
        self,
        _status,
        _meta,
        mock_find,
        _busy,
        mock_insert,
        _overlap,
        mock_notify,
    ):
        existing = {
            "id": "apt-existing",
            "status": "pending",
            "starts_at": "2026-06-10T15:00:00+00:00",
        }
        mock_find.return_value = existing
        starts = datetime(2026, 6, 10, 15, 0, tzinfo=timezone.utc)

        row, err = book_appointment(
            cliente_id="c1",
            service_id="s1",
            professional_id="p1",
            starts_at=starts,
            duration_minutes=30,
            remote_id="5511999999999",
            contact_phone="5511999999999",
        )

        self.assertIsNone(err)
        self.assertEqual(row, existing)
        mock_insert.assert_not_called()
        mock_notify.assert_not_called()

    @patch("services.scheduling.confirmation_notify.notify_pending_booking")
    @patch("services.scheduling.bookings.repository.find_overlapping_appointments", return_value=[])
    @patch("services.scheduling.bookings.repository.insert_appointment")
    @patch("services.scheduling.bookings.repository.busy_intervals_utc", return_value=[])
    @patch("services.scheduling.bookings.repository.find_existing_booking_for_contact", return_value=None)
    @patch("services.scheduling.confirmation_policy.build_booking_meta_patch", return_value={})
    @patch("services.scheduling.confirmation_policy.resolve_initial_appointment_status", return_value="pending")
    def test_inserts_when_no_existing(
        self,
        _status,
        _meta,
        _find,
        _busy,
        mock_insert,
        _overlap,
        mock_notify,
    ):
        created = {"id": "apt-new", "status": "pending"}
        mock_insert.return_value = created
        starts = datetime(2026, 6, 10, 15, 0, tzinfo=timezone.utc)

        row, err = book_appointment(
            cliente_id="c1",
            service_id="s1",
            professional_id="p1",
            starts_at=starts,
            duration_minutes=30,
            remote_id="5511999999999",
            contact_phone="5511999999999",
        )

        self.assertIsNone(err)
        self.assertEqual(row, created)
        mock_insert.assert_called_once()
        mock_notify.assert_called_once_with("c1", created)

    @patch("services.scheduling.confirmation_notify.notify_pending_booking")
    @patch("services.scheduling.bookings.repository.delete_appointment_row")
    @patch("services.scheduling.bookings.repository.find_overlapping_appointments")
    @patch("services.scheduling.bookings.repository.insert_appointment")
    @patch("services.scheduling.bookings.repository.busy_intervals_utc", return_value=[])
    @patch("services.scheduling.bookings.repository.find_existing_booking_for_contact", return_value=None)
    @patch("services.scheduling.confirmation_policy.build_booking_meta_patch", return_value={})
    @patch("services.scheduling.confirmation_policy.resolve_initial_appointment_status", return_value="confirmed")
    def test_post_insert_keeps_row_when_no_other_appointment(
        self,
        _status,
        _meta,
        _find,
        _busy,
        mock_insert,
        mock_overlap,
        mock_delete,
        mock_notify,
    ):
        created = {"id": "apt-new", "status": "confirmed"}
        mock_insert.return_value = created
        mock_overlap.return_value = []
        starts = datetime(2026, 6, 10, 15, 0, tzinfo=timezone.utc)

        row, err = book_appointment(
            cliente_id="c1",
            service_id="s1",
            professional_id="p1",
            starts_at=starts,
            duration_minutes=30,
            remote_id="5511999999999",
            contact_phone="5511999999999",
        )

        self.assertIsNone(err)
        self.assertEqual(row, created)
        mock_delete.assert_not_called()
        mock_notify.assert_not_called()

    @patch("services.scheduling.confirmation_notify.notify_pending_booking")
    @patch("services.scheduling.bookings.repository.delete_appointment_row")
    @patch("services.scheduling.bookings.repository.find_overlapping_appointments")
    @patch("services.scheduling.bookings.repository.insert_appointment")
    @patch("services.scheduling.bookings.repository.busy_intervals_utc", return_value=[])
    @patch("services.scheduling.bookings.repository.find_existing_booking_for_contact", return_value=None)
    @patch("services.scheduling.confirmation_policy.build_booking_meta_patch", return_value={})
    @patch("services.scheduling.confirmation_policy.resolve_initial_appointment_status", return_value="pending")
    def test_post_insert_deletes_and_skips_notify_on_race(
        self,
        _status,
        _meta,
        _find,
        _busy,
        mock_insert,
        mock_overlap,
        mock_delete,
        mock_notify,
    ):
        created = {"id": "apt-new", "status": "pending"}
        mock_insert.return_value = created
        mock_overlap.return_value = [{"id": "other"}]
        starts = datetime(2026, 6, 10, 15, 0, tzinfo=timezone.utc)

        row, err = book_appointment(
            cliente_id="c1",
            service_id="s1",
            professional_id="p1",
            starts_at=starts,
            duration_minutes=30,
            remote_id="5511999999999",
            contact_phone="5511999999999",
        )

        self.assertIsNone(row)
        self.assertEqual(err, "slot_ocupado")
        mock_delete.assert_called_once_with("c1", "apt-new")
        mock_notify.assert_not_called()


class TestAgendaPublicaPrg(unittest.TestCase):
    @patch("services.scheduling.bookings.book_appointment")
    @patch("services.scheduling.slots_public.eligible_professionals")
    @patch("services.scheduling.public_booking.parse_month_anchor")
    @patch("services.scheduling.public_booking.parse_selected_date", return_value=None)
    @patch("services.scheduling.assignment.uses_auto_distribution", return_value=False)
    @patch("services.agendamento_ia_bridge.scheduling_uses_internal_motor", return_value=True)
    @patch("services.agendamento_ia_urls.agendamento_ia_configured", return_value=False)
    @patch("services.scheduling.repository.list_working_hours_all", return_value=[])
    @patch("services.scheduling.repository.get_service")
    @patch("services.scheduling.repository.list_services")
    @patch("services.scheduling.repository.list_professionals")
    @patch("services.scheduling.repository.get_settings_by_slug")
    @patch("database.supabase_sq.supabase", MagicMock())
    def test_redirect_after_successful_post(
        self,
        mock_get_settings,
        mock_list_profs,
        mock_list_services,
        mock_get_service,
        _wh,
        _ai_cfg,
        _internal,
        _auto,
        _parse_date,
        _parse_month,
        mock_eligible,
        mock_book,
    ):
        from app import app

        mock_get_settings.return_value = {
            "cliente_id": "c1",
            "timezone": "America/Sao_Paulo",
            "public_name": "Clínica",
        }
        mock_list_profs.return_value = [{"id": "p1", "name": "Dr"}]
        mock_list_services.return_value = [{"id": "s1", "name": "Consulta", "duration_minutes": 30}]
        mock_eligible.return_value = [{"id": "p1", "name": "Dr"}]
        mock_get_service.return_value = {"id": "s1", "duration_minutes": 30}
        mock_book.return_value = ({"id": "a1", "status": "pending"}, None)

        client = app.test_client()
        resp = client.post(
            "/agenda/clinica-teste",
            data={
                "slot_iso": "2026-06-10T15:00:00+00:00",
                "service_id": "s1",
                "professional_id": "p1",
                "name": "Ana",
                "phone": "(11) 99999-9999",
            },
            follow_redirects=False,
        )

        self.assertEqual(resp.status_code, 302)
        self.assertIn("/agenda/clinica-teste", resp.location or "")
        self.assertIn("booked=1", resp.location or "")
        self.assertIn("pending=1", resp.location or "")
        self.assertIn("date=2026-06-10", resp.location or "")


if __name__ == "__main__":
    unittest.main()
