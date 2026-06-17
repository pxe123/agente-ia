"""Testes — rotinas de horário."""
from __future__ import annotations

import unittest

from services.scheduling.working_hour_routines import (
    expand_config_to_rows,
    infer_config_from_clinic_hours,
    normalize_config,
    routine_to_intervals,
    validate_config,
)


class TestWorkingHourRoutines(unittest.TestCase):
    def test_routine_with_lunch_splits_intervals(self):
        r = {
            "open": "08:00",
            "close": "18:00",
            "lunch_enabled": True,
            "lunch_start": "12:00",
            "lunch_end": "13:00",
        }
        self.assertEqual(routine_to_intervals(r), [("08:00", "12:00"), ("13:00", "18:00")])

    def test_multiple_routines_expand(self):
        cfg = normalize_config(
            {
                "routines": [
                    {
                        "id": "a",
                        "name": "Semana",
                        "days": [0, 1, 2, 3, 4],
                        "open": "08:00",
                        "close": "18:00",
                        "lunch_enabled": True,
                        "lunch_start": "12:00",
                        "lunch_end": "13:00",
                    },
                    {
                        "id": "b",
                        "name": "Sábado",
                        "days": [5],
                        "open": "09:00",
                        "close": "13:00",
                        "lunch_enabled": False,
                        "lunch_start": "12:00",
                        "lunch_end": "13:00",
                    },
                ],
                "day_overrides": {},
            }
        )
        rows = expand_config_to_rows(cfg)
        self.assertIn(0, rows)
        self.assertIn(5, rows)
        self.assertEqual(rows[5], [("09:00", "13:00")])

    def test_day_override_wins(self):
        cfg = normalize_config(
            {
                "routines": [
                    {
                        "id": "a",
                        "name": "Semana",
                        "days": [0, 1, 2, 3, 4, 5],
                        "open": "08:00",
                        "close": "18:00",
                        "lunch_enabled": False,
                        "lunch_start": "12:00",
                        "lunch_end": "13:00",
                    }
                ],
                "day_overrides": {
                    "5": {
                        "custom": True,
                        "intervals": [{"start": "10:00", "end": "14:00"}],
                    }
                },
            }
        )
        self.assertIsNotNone(validate_config(cfg))
        cfg["routines"][0]["days"] = [0, 1, 2, 3, 4]
        self.assertIsNone(validate_config(cfg))
        rows = expand_config_to_rows(cfg)
        self.assertEqual(rows[5], [("10:00", "14:00")])

    def test_infer_from_clinic_hours(self):
        cfg = infer_config_from_clinic_hours(
            [
                {
                    "professional_id": None,
                    "day_of_week": 0,
                    "start_time": "08:00:00",
                    "end_time": "12:00:00",
                },
                {
                    "professional_id": None,
                    "day_of_week": 0,
                    "start_time": "13:00:00",
                    "end_time": "18:00:00",
                },
                {
                    "professional_id": None,
                    "day_of_week": 5,
                    "start_time": "09:00",
                    "end_time": "13:00",
                },
            ]
        )
        self.assertTrue(cfg.get("routines"))


if __name__ == "__main__":
    unittest.main()
