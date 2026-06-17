"""Distribuição automática: round-robin e modo por tenant."""
from __future__ import annotations

import unittest
from unittest.mock import patch

from services.scheduling.assignment import (
    order_candidates_for_assignment,
    pick_professional_round_robin,
    uses_auto_distribution,
)


class TestSchedulingAssignment(unittest.TestCase):
    def test_uses_auto_distribution_requires_internal_motor(self):
        cid = "11111111-2222-3333-4444-555555555555"
        with patch(
            "services.scheduling.assignment.scheduling_uses_internal_motor",
            return_value=False,
        ):
            with patch(
                "services.scheduling.assignment.scheduling_repository.get_assignment_mode",
                return_value="auto_distribution",
            ):
                self.assertFalse(uses_auto_distribution(cid))

    def test_uses_auto_distribution_when_internal_and_mode(self):
        cid = "11111111-2222-3333-4444-555555555555"
        with patch(
            "services.scheduling.assignment.scheduling_uses_internal_motor",
            return_value=True,
        ):
            with patch(
                "services.scheduling.assignment.scheduling_repository.get_assignment_mode",
                return_value="auto_distribution",
            ):
                self.assertTrue(uses_auto_distribution(cid))

    def test_manual_mode_default(self):
        cid = "11111111-2222-3333-4444-555555555555"
        with patch(
            "services.scheduling.assignment.scheduling_uses_internal_motor",
            return_value=True,
        ):
            with patch(
                "services.scheduling.assignment.scheduling_repository.get_assignment_mode",
                return_value="manual",
            ):
                self.assertFalse(uses_auto_distribution(cid))

    def test_round_robin_alternates(self):
        cid = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
        profs = [
            {"id": "p1", "name": "Ana", "sort_order": 0},
            {"id": "p2", "name": "Bruno", "sort_order": 1},
        ]
        candidates = ["p1", "p2"]
        with patch(
            "services.scheduling.assignment.scheduling_repository.get_distribution_cursor",
            return_value=None,
        ):
            first = pick_professional_round_robin(
                cid, candidates, professionals=profs
            )
            self.assertEqual(first, "p1")
        with patch(
            "services.scheduling.assignment.scheduling_repository.get_distribution_cursor",
            return_value="p1",
        ):
            second = pick_professional_round_robin(
                cid, candidates, professionals=profs
            )
            self.assertEqual(second, "p2")
        with patch(
            "services.scheduling.assignment.scheduling_repository.get_distribution_cursor",
            return_value="p2",
        ):
            third = pick_professional_round_robin(
                cid, candidates, professionals=profs
            )
            self.assertEqual(third, "p1")

    def test_single_candidate_skips_round_robin(self):
        cid = "bbbbbbbb-cccc-dddd-eeee-ffffffffffff"
        profs = [{"id": "p1", "name": "Ana", "sort_order": 0}]
        with patch(
            "services.scheduling.assignment.scheduling_repository.get_distribution_cursor",
            return_value="p9",
        ):
            picked = pick_professional_round_robin(
                cid, ["p1"], professionals=profs
            )
            self.assertEqual(picked, "p1")

    def test_order_candidates_puts_round_robin_first(self):
        cid = "cccccccc-dddd-eeee-ffff-000000000000"
        profs = [
            {"id": "p1", "name": "Ana", "sort_order": 0},
            {"id": "p2", "name": "Bruno", "sort_order": 1},
        ]
        with patch(
            "services.scheduling.assignment.scheduling_repository.get_distribution_strategy",
            return_value="round_robin",
        ):
            with patch(
                "services.scheduling.assignment.scheduling_repository.get_distribution_cursor",
                return_value="p1",
            ):
                ordered = order_candidates_for_assignment(
                    cid, ["p1", "p2"], professionals=profs
                )
        self.assertEqual(ordered[0], "p2")
        self.assertEqual(set(ordered), {"p1", "p2"})


if __name__ == "__main__":
    unittest.main()
