"""Troca de clientes entre profissionais (swap)."""
from __future__ import annotations

import logging
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

from services.scheduling.swap import (
    SWAP_MODE_CROSS,
    SWAP_MODE_SAME_SLOT,
    can_professional_assume_appointment,
    cross_swap_valid,
    swap_appointments_between_professionals,
)


def _row(
    aid: str,
    pid: str,
    start_h: int,
    *,
    status: str = "confirmed",
    duration_min: int = 30,
) -> dict:
    start = datetime(2026, 6, 10, start_h, 0, tzinfo=timezone.utc)
    end = start + timedelta(minutes=duration_min)
    return {
        "id": aid,
        "cliente_id": "c1",
        "professional_id": pid,
        "starts_at": start.isoformat(),
        "ends_at": end.isoformat(),
        "status": status,
        "meta": {},
    }


class TestSchedulingSwap(unittest.TestCase):
    def test_same_slot_success(self):
        row_a = _row("a1", "p1", 14)
        row_b = _row("b1", "p2", 14)
        with patch(
            "services.scheduling.swap.scheduling_repository.get_appointment",
            side_effect=lambda _c, aid: row_a if aid == "a1" else row_b,
        ):
            with patch(
                "services.scheduling.swap.scheduling_repository.update_appointment_professional",
                return_value=True,
            ) as mock_upd:
                with self.assertLogs("services.scheduling.swap", level="INFO") as logs:
                    ok, err = swap_appointments_between_professionals(
                        "c1", "a1", "b1", "user1", swap_mode=SWAP_MODE_SAME_SLOT
                    )
        self.assertTrue(ok)
        self.assertIsNone(err)
        self.assertEqual(mock_upd.call_count, 2)
        self.assertTrue(any("appointment_swap" in m for m in logs.output))

    def test_cross_validated_different_times(self):
        row_a = _row("a1", "p1", 14)
        row_b = _row("b1", "p2", 15)
        with patch(
            "services.scheduling.swap.scheduling_repository.get_appointment",
            side_effect=lambda _c, aid: row_a if aid == "a1" else row_b,
        ):
            with patch("services.scheduling.swap.cross_swap_valid", return_value=True):
                with patch(
                    "services.scheduling.swap.scheduling_repository.update_appointment_professional",
                    return_value=True,
                ):
                    ok, err = swap_appointments_between_professionals(
                        "c1", "a1", "b1", "user1", swap_mode=SWAP_MODE_CROSS
                    )
        self.assertTrue(ok)
        self.assertIsNone(err)

    def test_same_professional_rejected(self):
        row_a = _row("a1", "p1", 14)
        row_b = _row("b1", "p1", 15)
        with patch(
            "services.scheduling.swap.scheduling_repository.get_appointment",
            side_effect=lambda _c, aid: row_a if aid == "a1" else row_b,
        ):
            ok, err = swap_appointments_between_professionals(
                "c1", "a1", "b1", "user1", swap_mode=SWAP_MODE_CROSS
            )
        self.assertFalse(ok)
        self.assertEqual(err, "mesmo_profissional")

    def test_cancelled_rejected(self):
        row_a = _row("a1", "p1", 14, status="cancelled")
        row_b = _row("b1", "p2", 14)
        with patch(
            "services.scheduling.swap.scheduling_repository.get_appointment",
            side_effect=lambda _c, aid: row_a if aid == "a1" else row_b,
        ):
            ok, err = swap_appointments_between_professionals(
                "c1", "a1", "b1", "user1", swap_mode=SWAP_MODE_SAME_SLOT
            )
        self.assertFalse(ok)
        self.assertEqual(err, "cancelado")

    def test_without_professional_rejected(self):
        row_a = _row("a1", "p1", 14)
        row_b = _row("b1", "p2", 14)
        row_b["professional_id"] = None
        with patch(
            "services.scheduling.swap.scheduling_repository.get_appointment",
            side_effect=lambda _c, aid: row_a if aid == "a1" else row_b,
        ):
            ok, err = swap_appointments_between_professionals(
                "c1", "a1", "b1", "user1", swap_mode=SWAP_MODE_SAME_SLOT
            )
        self.assertFalse(ok)
        self.assertEqual(err, "sem_profissional")

    def test_cross_conflict_when_busy(self):
        row_a = _row("a1", "p1", 14)
        row_b = _row("b1", "p2", 15)
        with patch(
            "services.scheduling.swap.scheduling_repository.get_appointment",
            side_effect=lambda _c, aid: row_a if aid == "a1" else row_b,
        ):
            with patch("services.scheduling.swap.cross_swap_valid", return_value=False):
                ok, err = swap_appointments_between_professionals(
                    "c1", "a1", "b1", "user1", swap_mode=SWAP_MODE_CROSS
                )
        self.assertFalse(ok)
        self.assertEqual(err, "conflito_cruzado")

    def test_meta_persisted_on_update(self):
        row_a = _row("a1", "p1", 14)
        row_b = _row("b1", "p2", 14)
        patches = []
        with patch(
            "services.scheduling.swap.scheduling_repository.get_appointment",
            side_effect=lambda _c, aid: row_a if aid == "a1" else row_b,
        ):
            with patch(
                "services.scheduling.swap.scheduling_repository.update_appointment_professional",
                return_value=True,
            ) as mock_upd:
                swap_appointments_between_professionals(
                    "c1", "a1", "b1", "panel_user", swap_mode=SWAP_MODE_SAME_SLOT
                )
                for call in mock_upd.call_args_list:
                    meta = call.kwargs.get("meta_patch") or call[1].get("meta_patch")
                    self.assertTrue(meta.get("swap_performed"))
                    self.assertEqual(meta.get("swapped_by"), "panel_user")
                    self.assertEqual(meta.get("swap_mode"), SWAP_MODE_SAME_SLOT)

    def test_can_professional_assume_free(self):
        row = _row("b1", "p2", 15)
        with patch(
            "services.scheduling.swap.scheduling_repository.busy_intervals_utc",
            return_value=[],
        ):
            self.assertTrue(
                can_professional_assume_appointment(
                    "c1", "p1", row, exclude_appointment_ids=frozenset({"a1", "b1"})
                )
            )

    def test_cross_swap_valid_both_directions(self):
        row_a = _row("a1", "p1", 14)
        row_b = _row("b1", "p2", 15)
        with patch(
            "services.scheduling.swap.can_professional_assume_appointment",
            return_value=True,
        ):
            self.assertTrue(cross_swap_valid(row_a, row_b, "c1"))


if __name__ == "__main__":
    unittest.main()
