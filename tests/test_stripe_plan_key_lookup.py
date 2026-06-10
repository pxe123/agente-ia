from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch

from billing.stripe_service import finalize_subscription_state, StripeSubscriptionState


class TestStripePlanKeyFromPrice(unittest.TestCase):
    @patch("billing.stripe_service.plan_key_from_stripe_price_id")
    def test_finalize_resolves_plan_key(self, mock_lookup):
        mock_lookup.return_value = "profissional"
        st = StripeSubscriptionState(
            stripe_customer_id="cus_1",
            stripe_subscription_id="sub_1",
            stripe_price_id="price_xyz",
            status="active",
            current_period_end=None,
            cancel_at_period_end=None,
            plan_key=None,
        )
        out = finalize_subscription_state(st)
        self.assertEqual(out.plan_key, "profissional")


if __name__ == "__main__":
    unittest.main()
