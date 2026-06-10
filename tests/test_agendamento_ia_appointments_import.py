import unittest
from unittest.mock import patch

from services.agendamento_ia_appointments_import import _item_to_webhook_payload


class TestAppointmentsImport(unittest.TestCase):
    def test_payload_maps_contact(self):
        p = _item_to_webhook_payload(
            "cid-1",
            {
                "appointment_id": "ap-1",
                "status": "confirmed",
                "starts_at": "2026-05-22T14:30:00Z",
                "ends_at": "2026-05-22T15:00:00Z",
                "contact": {"name": "Ricardo", "phone": "5514"},
            },
        )
        self.assertEqual(p["cliente_id"], "cid-1")
        self.assertEqual(p["appointment_id"], "ap-1")
        self.assertEqual(p["contact"]["name"], "Ricardo")
        self.assertEqual(p["event"], "appointment.created")


if __name__ == "__main__":
    unittest.main()
