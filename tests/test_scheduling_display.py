import unittest
from datetime import datetime, timezone

from services.scheduling.display import (
    enrich_appointments_display,
    format_datetime_br,
    format_phone_br_display,
    parse_iso_datetime,
)


class TestSchedulingDisplay(unittest.TestCase):
    def test_format_sao_paulo_from_utc_iso(self):
        # 2026-05-21 17:30 UTC = 14:30 em America/Sao_Paulo (UTC-3)
        iso = "2026-05-21T17:30:00+00:00"
        self.assertEqual(
            format_datetime_br(iso, "America/Sao_Paulo"),
            "21/05/2026 14:30",
        )

    def test_format_utc_no_offset_change(self):
        self.assertEqual(
            format_datetime_br("2026-05-21T14:30:00+00:00", "UTC"),
            "21/05/2026 14:30",
        )

    def test_parse_z_suffix(self):
        dt = parse_iso_datetime("2026-05-21T17:30:00Z")
        self.assertIsNotNone(dt)
        self.assertEqual(dt.tzinfo, timezone.utc)

    def test_invalid_returns_dash(self):
        self.assertEqual(format_datetime_br("", "America/Sao_Paulo"), "—")

    def test_format_phone_br_display(self):
        self.assertEqual(format_phone_br_display("5514998757520"), "+55 (14) 99875-7520")
        self.assertEqual(format_phone_br_display("14998757520"), "(14) 99875-7520")

    def test_enrich_appointments_splits_name_and_phone(self):
        rows = enrich_appointments_display(
            [
                {
                    "starts_at": "2026-05-21T17:30:00+00:00",
                    "meta": {"contact_name": "Maria"},
                    "contact_phone": "5514998757520",
                }
            ],
            "America/Sao_Paulo",
        )
        self.assertEqual(rows[0]["contact_name_display"], "Maria")
        self.assertEqual(rows[0]["contact_phone_display"], "+55 (14) 99875-7520")


if __name__ == "__main__":
    unittest.main()
