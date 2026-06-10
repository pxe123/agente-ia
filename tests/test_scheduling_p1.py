"""Testes P1: slots públicos, bloqueios, remarcação."""
from __future__ import annotations

import unittest
from datetime import datetime, timezone
from unittest.mock import patch

from services.scheduling.bookings import reschedule_appointment
from services.scheduling.slots_public import eligible_professionals


class TestEligibleProfessionals(unittest.TestCase):
    def test_service_bound_to_one_prof(self):
        services = [{"id": "s1", "professional_id": "p2"}]
        profs = [{"id": "p1", "name": "A"}, {"id": "p2", "name": "B"}]
        out = eligible_professionals(services, profs, "s1")
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0]["id"], "p2")

    def test_service_all_profs(self):
        services = [{"id": "s1", "professional_id": None}]
        profs = [{"id": "p1"}, {"id": "p2"}]
        self.assertEqual(len(eligible_professionals(services, profs, "s1")), 2)


class TestRescheduleAppointment(unittest.TestCase):
    @patch("database.supabase_sq.supabase")
    @patch("services.scheduling.bookings.repository.busy_intervals_utc", return_value=[])
    def test_reschedule_ok(self, _busy, mock_supabase):
        mock_supabase.table.return_value.update.return_value.eq.return_value.eq.return_value.execute.return_value = None
        new_start = datetime(2026, 6, 10, 14, 0, tzinfo=timezone.utc)
        ok, err = reschedule_appointment(
            cliente_id="c1",
            appointment_id="a1",
            new_starts_at=new_start,
            duration_minutes=30,
            professional_id="p1",
        )
        self.assertTrue(ok)
        self.assertIsNone(err)

    @patch("services.scheduling.bookings.repository.busy_intervals_utc")
    def test_reschedule_conflict(self, mock_busy):
        new_start = datetime(2026, 6, 10, 14, 0, tzinfo=timezone.utc)
        end = datetime(2026, 6, 10, 14, 30, tzinfo=timezone.utc)
        mock_busy.return_value = [(new_start, end)]
        ok, err = reschedule_appointment(
            cliente_id="c1",
            appointment_id="a1",
            new_starts_at=new_start,
            duration_minutes=30,
            professional_id="p1",
        )
        self.assertFalse(ok)
        self.assertEqual(err, "slot_ocupado")


if __name__ == "__main__":
    unittest.main()
