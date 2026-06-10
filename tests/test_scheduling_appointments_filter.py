"""Testes filtros aba Agendamentos."""
from __future__ import annotations

import unittest
from datetime import date

from services.scheduling.appointments_filter import (
    resolve_appointments_period,
    shift_view_date,
    view_date_for_period,
)


class TestAppointmentsFilter(unittest.TestCase):
    def test_default_today(self):
        _, _, key, label = resolve_appointments_period(period=None, anchor_date=None, tz_name="America/Sao_Paulo")
        self.assertEqual(key, "today")
        self.assertIn("Hoje", label)

    def test_tomorrow(self):
        _, _, key, _ = resolve_appointments_period(period="tomorrow", anchor_date=None, tz_name="America/Sao_Paulo")
        self.assertEqual(key, "tomorrow")

    def test_specific_date(self):
        d = date(2026, 6, 20)
        _, _, key, label = resolve_appointments_period(period=None, anchor_date=d, tz_name="America/Sao_Paulo")
        self.assertEqual(key, "day")
        self.assertIn("20/06/2026", label)

    def test_week_bounds(self):
        from_utc, to_utc, key, _ = resolve_appointments_period(
            period="week", anchor_date=None, tz_name="America/Sao_Paulo"
        )
        self.assertEqual(key, "week")
        self.assertLess(from_utc, to_utc)
        self.assertEqual((to_utc - from_utc).days, 7)

    def test_view_date_anchor(self):
        d = date(2026, 6, 15)
        got = view_date_for_period(period="week", anchor_date=d, tz_name="America/Sao_Paulo")
        self.assertEqual(got, d)

    def test_view_date_tomorrow(self):
        today = view_date_for_period(period="today", anchor_date=None, tz_name="America/Sao_Paulo")
        tomorrow = view_date_for_period(period="tomorrow", anchor_date=None, tz_name="America/Sao_Paulo")
        self.assertEqual(tomorrow, shift_view_date(today, 1))


if __name__ == "__main__":
    unittest.main()
