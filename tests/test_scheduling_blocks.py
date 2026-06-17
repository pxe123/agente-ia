"""Testes — bloqueios de horário."""
from __future__ import annotations

import unittest
from datetime import date, datetime, timezone
from unittest.mock import MagicMock, patch

from services.scheduling.blocks import (
    block_scope,
    resolve_day_block_bounds,
    validate_block_interval,
)
from services.scheduling.slot_engine import slot_starts_in_range


class TestBlocksHelpers(unittest.TestCase):
    def test_block_scope(self):
        self.assertEqual(block_scope(None), "clinic")
        self.assertEqual(block_scope(""), "clinic")
        self.assertEqual(block_scope("uuid-1"), "professional")

    def test_validate_interval(self):
        a = datetime(2026, 6, 15, 14, 0, tzinfo=timezone.utc)
        b = datetime(2026, 6, 15, 16, 0, tzinfo=timezone.utc)
        self.assertIsNone(validate_block_interval(a, b))
        self.assertEqual(validate_block_interval(b, a), "horario_invalido")

    def test_resolve_day_bounds_professional(self):
        rows = [
            {"day_of_week": 0, "start_time": "09:00", "end_time": "18:00", "professional_id": "p1"},
        ]
        d = date(2026, 6, 15)  # Monday
        self.assertEqual(d.weekday(), 0)
        st, et = resolve_day_block_bounds(
            local_date=d,
            tz_name="UTC",
            working_rows=rows,
            professional_id="p1",
        )
        self.assertEqual(st.hour, 9)
        self.assertEqual(et.hour, 18)

    def test_resolve_day_bounds_clinic_fallback(self):
        rows = [
            {"day_of_week": 0, "start_time": "08:00", "end_time": "17:00", "professional_id": None},
        ]
        d = date(2026, 6, 15)
        st, et = resolve_day_block_bounds(
            local_date=d,
            tz_name="UTC",
            working_rows=rows,
            professional_id=None,
        )
        self.assertEqual(st.hour, 8)
        self.assertEqual(et.hour, 17)

    def test_slots_exclude_block_interval(self):
        tz = "UTC"
        d = date(2026, 6, 15)
        rows = [{"day_of_week": 0, "start_time": "09:00", "end_time": "18:00", "professional_id": "p1"}]
        busy_start = datetime(2026, 6, 15, 15, 0, tzinfo=timezone.utc)
        busy_end = datetime(2026, 6, 15, 16, 0, tzinfo=timezone.utc)
        floor = datetime(2020, 1, 1, tzinfo=timezone.utc)
        with patch("services.scheduling.slot_engine._utc_now", return_value=floor):
            slots = slot_starts_in_range(
                tz_name=tz,
                start_day=d,
                num_days=1,
                duration_minutes=60,
                professional_id="p1",
                working_rows=rows,
                busy_intervals_utc=[(busy_start, busy_end)],
            )
        hours = {s.hour for s in slots}
        self.assertNotIn(15, hours)


class TestBlocksService(unittest.TestCase):
    @patch("services.scheduling.blocks.scheduling_uses_internal_motor", return_value=True)
    @patch("services.scheduling.blocks.repository.insert_blocked_time")
    def test_create_block_clinic(self, mock_insert, _motor):
        from services.scheduling.blocks import create_block

        mock_insert.return_value = {"id": "b1"}
        st = datetime(2026, 6, 15, 16, 0, tzinfo=timezone.utc)
        et = datetime(2026, 6, 15, 18, 0, tzinfo=timezone.utc)
        row, err = create_block(
            cliente_id="c1",
            starts_at=st,
            ends_at=et,
            professional_id=None,
        )
        self.assertIsNone(err)
        self.assertEqual(row["id"], "b1")
        mock_insert.assert_called_once()
        self.assertIsNone(mock_insert.call_args.kwargs.get("professional_id"))

    @patch("services.scheduling.blocks.scheduling_uses_internal_motor", return_value=False)
    def test_create_block_external_motor(self, _motor):
        from services.scheduling.blocks import create_block

        st = datetime(2026, 6, 15, 16, 0, tzinfo=timezone.utc)
        et = datetime(2026, 6, 15, 18, 0, tzinfo=timezone.utc)
        row, err = create_block(cliente_id="c1", starts_at=st, ends_at=et)
        self.assertIsNone(row)
        self.assertEqual(err, "motor_externo")


if __name__ == "__main__":
    unittest.main()
