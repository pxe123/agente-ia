"""Testes P2: calendário, stats, lembretes."""
from __future__ import annotations

import unittest
from datetime import date, datetime, timezone
from unittest.mock import patch

from services.scheduling.calendar import build_calendar_view, build_week_days, parse_anchor_date
from services.scheduling.reminders import _reminder_hours, run_appointment_reminders
from services.scheduling.stats import compute_dashboard_stats


class TestCalendar(unittest.TestCase):
    def test_parse_anchor_date(self):
        d = parse_anchor_date("2026-06-15", "America/Sao_Paulo")
        self.assertEqual(d, date(2026, 6, 15))

    def test_build_week_days(self):
        days = build_week_days(date(2026, 6, 18))  # quinta
        self.assertEqual(len(days), 7)
        self.assertEqual(days[0].weekday(), 0)

    def test_build_calendar_view_week(self):
        appts = [
            {
                "id": "a1",
                "status": "confirmed",
                "starts_at": "2026-06-18T15:00:00+00:00",
                "ends_at": "2026-06-18T15:30:00+00:00",
                "professional_id": "p1",
                "service_id": "s1",
                "remote_id": "5511999999999",
                "meta": {},
            }
        ]
        cal = build_calendar_view(
            view="week",
            anchor=date(2026, 6, 18),
            appointments=appts,
            tz_name="America/Sao_Paulo",
            prof_names={"p1": "Ana"},
            service_names={"s1": "Consulta"},
        )
        self.assertEqual(cal["view"], "week")
        self.assertEqual(len(cal["days"]), 7)


class TestStats(unittest.TestCase):
    def test_compute_dashboard_stats(self):
        now = datetime.now(timezone.utc)
        appts = [
            {"status": "confirmed", "starts_at": now.isoformat()},
            {"status": "cancelled", "starts_at": now.isoformat()},
        ]
        stats = compute_dashboard_stats(appts, tz_name="America/Sao_Paulo")
        self.assertIn("today", stats)
        self.assertGreaterEqual(stats["cancelled_month"], 1)


class TestReminders(unittest.TestCase):
    def test_reminder_hours_parse(self):
        with patch("services.scheduling.reminders.settings") as s:
            s.SCHEDULING_REMINDER_HOURS_BEFORE = "24, 1"
            self.assertEqual(_reminder_hours(), [24, 1])

    def test_reminders_disabled(self):
        with patch("services.scheduling.reminders.reminders_enabled", return_value=False):
            out = run_appointment_reminders()
        self.assertTrue(out.get("skipped"))


if __name__ == "__main__":
    unittest.main()
