import unittest
from datetime import date, datetime, timezone
from unittest.mock import patch

from services.scheduling.slot_engine import effective_working_rows_for_professional, slot_starts_in_range


class TestSlotEngine(unittest.TestCase):
    def test_effective_hours_prefers_professional_over_generic(self):
        rows = [
            {"day_of_week": 0, "start_time": "09:00", "end_time": "12:00", "professional_id": None},
            {"day_of_week": 0, "start_time": "14:00", "end_time": "18:00", "professional_id": "p1"},
        ]
        eff = effective_working_rows_for_professional(rows, "p1")
        dows = {r["day_of_week"] for r in eff}
        self.assertEqual(dows, {0})
        self.assertTrue(any(r.get("professional_id") == "p1" for r in eff))

    def test_slots_no_busy(self):
        tz = "UTC"
        d = date(2026, 1, 5)  # Monday
        rows = [{"day_of_week": 0, "start_time": "10:00", "end_time": "11:30", "professional_id": "p1"}]
        floor = datetime(2020, 1, 1, tzinfo=timezone.utc)
        with patch("services.scheduling.slot_engine._utc_now", return_value=floor):
            slots = slot_starts_in_range(
                tz_name=tz,
                start_day=d,
                num_days=1,
                duration_minutes=30,
                professional_id="p1",
                working_rows=rows,
                busy_intervals_utc=[],
            )
        self.assertEqual(len(slots), 3)
        self.assertEqual(slots[0].hour, 10)
        self.assertEqual(slots[0].minute, 0)

    def test_slots_excludes_past_on_today(self):
        tz = "UTC"
        d = date(2026, 6, 10)
        rows = [{"day_of_week": d.weekday(), "start_time": "09:00", "end_time": "18:00", "professional_id": "p1"}]
        now = datetime(2026, 6, 10, 11, 56, tzinfo=timezone.utc)
        with patch("services.scheduling.slot_engine._utc_now", return_value=now):
            slots = slot_starts_in_range(
                tz_name=tz,
                start_day=d,
                num_days=1,
                duration_minutes=30,
                professional_id="p1",
                working_rows=rows,
                busy_intervals_utc=[],
            )
        times = [s.astimezone(timezone.utc).strftime("%H:%M") for s in slots]
        self.assertNotIn("09:00", times)
        self.assertNotIn("11:30", times)
        self.assertIn("12:00", times)

    def test_slots_respects_busy(self):
        tz = "UTC"
        d = date(2026, 1, 5)
        rows = [{"day_of_week": 0, "start_time": "10:00", "end_time": "12:00", "professional_id": "p1"}]
        busy_start = datetime(2026, 1, 5, 10, 30, tzinfo=timezone.utc)
        busy_end = datetime(2026, 1, 5, 11, 30, tzinfo=timezone.utc)
        floor = datetime(2020, 1, 1, tzinfo=timezone.utc)
        with patch("services.scheduling.slot_engine._utc_now", return_value=floor):
            slots = slot_starts_in_range(
                tz_name=tz,
                start_day=d,
                num_days=1,
                duration_minutes=30,
                professional_id="p1",
                working_rows=rows,
                busy_intervals_utc=[(busy_start, busy_end)],
            )
        starts = [s.astimezone(timezone.utc).strftime("%H:%M") for s in slots]
        self.assertIn("10:00", starts)
        self.assertNotIn("10:30", starts)


if __name__ == "__main__":
    unittest.main()
