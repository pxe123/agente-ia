"""Testes P2: calendário, stats, lembretes."""
from __future__ import annotations

import unittest
from datetime import date, datetime, timezone
from unittest.mock import patch

from services.scheduling.calendar import (
    _calendar_hour_range,
    build_calendar_view,
    build_week_days,
    parse_anchor_date,
)
from services.scheduling.datetime_parse import parse_panel_datetime
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
        self.assertGreaterEqual(cal["events_count"], 1)
        self.assertIn(12, cal["hours"])

    def test_build_calendar_view_early_morning_event(self):
        appts = [
            {
                "id": "a2",
                "status": "confirmed",
                "starts_at": "2026-06-18T09:00:00+00:00",
                "ends_at": "2026-06-18T10:00:00+00:00",
                "professional_id": "p1",
                "service_id": "s1",
                "remote_id": "x",
                "meta": {},
            }
        ]
        cal = build_calendar_view(
            view="day",
            anchor=date(2026, 6, 18),
            appointments=appts,
            tz_name="America/Sao_Paulo",
            prof_names={"p1": "Ana"},
            service_names={"s1": "Consulta"},
        )
        self.assertIn(6, cal["hours"])
        evs = cal["events_by_day"].get("2026-06-18", [])
        self.assertEqual(len(evs), 1)
        self.assertAlmostEqual(evs[0]["start_hour"], 6.0)

    def test_calendar_event_status_tone_by_status_not_origin(self):
        """Agenda IA: cor por status (pendente/confirmado), não por origem externa."""
        base = {
            "id": "a1",
            "starts_at": "2026-06-18T15:00:00+00:00",
            "ends_at": "2026-06-18T15:30:00+00:00",
            "professional_id": "p1",
            "service_id": "s1",
            "remote_id": "5511999999999",
            "meta": {"source": "agendamento_ia"},
            "origin": "agenda",
        }
        for status, tone in (
            ("pending", "pending"),
            ("confirmed", "local"),
            ("cancelled", "cancelled"),
        ):
            with self.subTest(status=status):
                appt = {**base, "status": status}
                cal = build_calendar_view(
                    view="day",
                    anchor=date(2026, 6, 18),
                    appointments=[appt],
                    tz_name="America/Sao_Paulo",
                    prof_names={"p1": "Ana"},
                    service_names={"s1": "Consulta"},
                )
                ev = cal["events_by_day"]["2026-06-18"][0]
                self.assertEqual(ev["status_tone"], tone)
                if status != "cancelled":
                    self.assertIn(" - Consulta", ev["display_label"])

    def test_calendar_display_label_client_and_service(self):
        appt = {
            "id": "a1",
            "status": "confirmed",
            "starts_at": "2026-06-18T15:00:00+00:00",
            "ends_at": "2026-06-18T15:30:00+00:00",
            "professional_id": "p1",
            "service_id": "s1",
            "meta": {"contact_name": "Maria Silva"},
            "contact_name_display": "Maria Silva",
        }
        cal = build_calendar_view(
            view="day",
            anchor=date(2026, 6, 18),
            appointments=[appt],
            tz_name="America/Sao_Paulo",
            prof_names={"p1": "Ana"},
            service_names={"s1": "Consulta"},
        )
        ev = cal["events_by_day"]["2026-06-18"][0]
        self.assertEqual(ev["display_label"], "Maria Silva - Consulta")
        self.assertEqual(ev["time_short"], "12:00")

    def test_calendar_hour_range_from_working_hours(self):
        events = [{"start_hour": 14.5, "duration_hours": 1.0}]
        rows = [{"start_time": "08:00", "end_time": "18:00", "professional_id": None}]
        start, hours = _calendar_hour_range(events, rows)
        self.assertLessEqual(start, 8)
        self.assertIn(14, hours)
        self.assertIn(18, hours)

    def test_parse_panel_datetime_local_clinic_tz(self):
        dt = parse_panel_datetime("2026-06-15T14:00", "America/Sao_Paulo")
        self.assertIsNotNone(dt)
        utc = dt.astimezone(timezone.utc)
        self.assertEqual(utc.hour, 17)
        self.assertEqual(utc.day, 15)

    def test_parse_panel_datetime_iso_offset(self):
        dt = parse_panel_datetime("2026-06-15T17:00:00+00:00", "America/Sao_Paulo")
        self.assertIsNotNone(dt)
        self.assertEqual(dt.hour, 17)


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
