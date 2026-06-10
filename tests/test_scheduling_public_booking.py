"""Testes calendário página pública /agenda/<slug>."""
from __future__ import annotations

import unittest
from datetime import date, datetime, timezone

from services.scheduling.public_booking import (
    build_public_booking_calendar,
    format_selected_date_long,
    group_slot_isos_by_local_day,
    month_bounds,
    parse_month_anchor,
)


class TestPublicBooking(unittest.TestCase):
    def test_group_slots_by_day(self):
        iso_am = datetime(2026, 6, 10, 12, 0, tzinfo=timezone.utc).isoformat()
        iso_pm = datetime(2026, 6, 10, 15, 0, tzinfo=timezone.utc).isoformat()
        grouped = group_slot_isos_by_local_day([iso_pm, iso_am], "UTC")
        self.assertEqual(list(grouped.keys()), ["2026-06-10"])
        self.assertEqual(len(grouped["2026-06-10"]), 2)

    def test_month_bounds(self):
        start, end = month_bounds(date(2026, 6, 15))
        self.assertEqual(start, date(2026, 6, 1))
        self.assertEqual(end, date(2026, 6, 30))

    def test_calendar_marks_days_with_slots(self):
        cal = build_public_booking_calendar(
            month_anchor=date(2026, 6, 1),
            slots_by_day={"2026-06-10": ["x"]},
            tz_name="UTC",
            selected_date=date(2026, 6, 10),
        )
        self.assertEqual(cal["month_label"], "Junho 2026")
        flat = [c for week in cal["weeks"] for c in week]
        day10 = next(c for c in flat if c["date"] == "2026-06-10")
        self.assertTrue(day10["has_slots"])
        self.assertTrue(day10["is_selected"])
        self.assertTrue(day10["clickable"])
        outside = [c for c in flat if not c["in_month"]]
        self.assertGreater(len(outside), 0)

    def test_format_selected_date_long(self):
        self.assertIn("junho", format_selected_date_long(date(2026, 6, 10)).lower())

    def test_parse_month_anchor(self):
        self.assertEqual(parse_month_anchor("2026-07", "UTC"), date(2026, 7, 1))


if __name__ == "__main__":
    unittest.main()
