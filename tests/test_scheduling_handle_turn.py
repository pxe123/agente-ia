import unittest

from services.scheduling.service import handle_turn


class TestSchedulingHandleTurn(unittest.TestCase):
    def test_missing_cliente_id(self):
        out = handle_turn(
            {
                "user_message": "oi",
                "context": {},
                "session": {},
            }
        )
        self.assertEqual(out.get("api_status"), "error")
        self.assertFalse(out.get("done"))


if __name__ == "__main__":
    unittest.main()
