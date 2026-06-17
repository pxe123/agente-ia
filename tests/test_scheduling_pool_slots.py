"""Pooling de slots para distribuição automática."""
from __future__ import annotations

import unittest
from datetime import date, datetime, timezone
from unittest.mock import patch

from services.scheduling.eligible import eligible_professionals
from services.scheduling.pool_slots import merge_slots_for_display


class TestEligibleProfessionals(unittest.TestCase):
    def test_service_fixed_professional(self):
        services = [{"id": "s1", "professional_id": "p2"}]
        profs = [
            {"id": "p1", "name": "A", "active": True},
            {"id": "p2", "name": "B", "active": True},
        ]
        out = eligible_professionals(services, profs, "s1")
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0]["id"], "p2")

    def test_service_any_professional(self):
        services = [{"id": "s1", "professional_id": None}]
        profs = [
            {"id": "p1", "name": "A", "active": True},
            {"id": "p2", "name": "B", "active": True},
        ]
        out = eligible_professionals(services, profs, "s1")
        self.assertEqual(len(out), 2)


class TestMergeSlotsForDisplay(unittest.TestCase):
    def test_merge_unique_times_with_candidates(self):
        t = datetime(2026, 6, 15, 14, 0, tzinfo=timezone.utc)
        iso = t.isoformat()
        entries = [
            {"iso": iso, "professional_id": "p1", "starts_at_utc": t},
            {"iso": iso, "professional_id": "p2", "starts_at_utc": t},
        ]
        slots, cmap = merge_slots_for_display(entries, "America/Sao_Paulo")
        self.assertEqual(len(slots), 1)
        self.assertEqual(set(cmap[iso]), {"p1", "p2"})

    def test_merge_preserves_order(self):
        t1 = datetime(2026, 6, 15, 14, 0, tzinfo=timezone.utc)
        t2 = datetime(2026, 6, 15, 15, 0, tzinfo=timezone.utc)
        entries = [
            {"iso": t1.isoformat(), "professional_id": "p1", "starts_at_utc": t1},
            {"iso": t2.isoformat(), "professional_id": "p1", "starts_at_utc": t2},
        ]
        slots, _ = merge_slots_for_display(entries, "America/Sao_Paulo")
        self.assertEqual(len(slots), 2)


class TestCandidatesAtInstant(unittest.TestCase):
    def test_professional_ids_free_at_slot_empty_when_busy(self):
        from services.scheduling.pool_slots import professional_ids_free_at_slot

        starts = datetime(2026, 6, 15, 17, 0, tzinfo=timezone.utc)
        busy_start = starts
        busy_end = starts.replace(hour=18)
        with patch(
            "services.scheduling.pool_slots.scheduling_repository.busy_intervals_utc",
            return_value=[(busy_start, busy_end)],
        ):
            with patch(
                "services.scheduling.pool_slots.slot_starts_in_range",
                return_value=[],
            ):
                out = professional_ids_free_at_slot(
                    cliente_id="c1",
                    service_id="s1",
                    starts_at=starts,
                    duration_minutes=30,
                    tz_name="America/Sao_Paulo",
                    working_rows=[],
                    professionals=[{"id": "p1", "active": True}],
                    services=[{"id": "s1", "professional_id": None}],
                )
        self.assertEqual(out, [])


if __name__ == "__main__":
    unittest.main()
