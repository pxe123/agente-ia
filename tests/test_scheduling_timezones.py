import unittest

from services.scheduling.timezones import (
    DEFAULT_TIMEZONE,
    normalize_timezone,
    timezone_label,
)


class TestSchedulingTimezones(unittest.TestCase):
    def test_default_sao_paulo(self):
        self.assertEqual(normalize_timezone(None), DEFAULT_TIMEZONE)
        self.assertEqual(normalize_timezone(""), DEFAULT_TIMEZONE)

    def test_rejects_unknown(self):
        self.assertEqual(normalize_timezone("Invalid/Zone"), DEFAULT_TIMEZONE)

    def test_accepts_listed(self):
        self.assertEqual(normalize_timezone("America/Manaus"), "America/Manaus")

    def test_label_contains_city(self):
        self.assertIn("São Paulo", timezone_label(DEFAULT_TIMEZONE))


if __name__ == "__main__":
    unittest.main()
