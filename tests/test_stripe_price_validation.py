from __future__ import annotations

import unittest
from unittest.mock import patch

from billing.stripe_service import price_id_for_plan


class TestStripePriceValidation(unittest.TestCase):
    @patch("billing.stripe_service.ensure_stripe_price_for_plan")
    def test_delegates_to_plans_table(self, mock_ensure):
        mock_ensure.return_value = "price_from_plans"
        self.assertEqual(price_id_for_plan("social"), "price_from_plans")
        mock_ensure.assert_called_once_with("social")

    @patch("billing.stripe_service.ensure_stripe_price_for_plan")
    def test_propagates_value_error(self, mock_ensure):
        mock_ensure.side_effect = ValueError("stripe_price_invalid:prod_abc")
        with self.assertRaises(ValueError):
            price_id_for_plan("social")


if __name__ == "__main__":
    unittest.main()
