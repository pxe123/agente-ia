from __future__ import annotations

import unittest
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

from billing.stripe_service import (
    StripeSubscriptionState,
    _coerce_status_after_paid_checkout,
    cliente_billing_patch,
    resolve_cliente_id_for_webhook,
)


def _st(**kwargs) -> StripeSubscriptionState:
    base = dict(
        stripe_customer_id=None,
        stripe_subscription_id=None,
        stripe_price_id=None,
        status=None,
        current_period_end=None,
        cancel_at_period_end=None,
        plan_key=None,
    )
    base.update(kwargs)
    return StripeSubscriptionState(**base)


class _ExecResult:
    def __init__(self, data=None):
        self.data = data or []


class TestResolveClienteId(unittest.TestCase):
    def test_metadata_cliente_id(self):
        st = _st(status="active")
        cid = resolve_cliente_id_for_webhook(
            event_type="invoice.paid",
            event_object={"metadata": {"cliente_id": "abc-123"}},
            st=st,
        )
        self.assertEqual(cid, "abc-123")

    def test_client_reference_id_on_checkout(self):
        st = _st(status="active")
        cid = resolve_cliente_id_for_webhook(
            event_type="checkout.session.completed",
            event_object={"client_reference_id": "ref-uuid"},
            st=st,
        )
        self.assertEqual(cid, "ref-uuid")

    def test_lookup_by_stripe_subscription_id(self):
        st = _st(stripe_subscription_id="sub_xxx", status="active")
        mock_sb = MagicMock()
        table = MagicMock()
        mock_sb.table.return_value = table
        chain = table.select.return_value.eq.return_value.limit.return_value
        chain.execute.return_value = _ExecResult([{"id": "db-cliente"}])

        with patch("database.supabase_sq.supabase", mock_sb):
            cid = resolve_cliente_id_for_webhook(
                event_type="customer.subscription.updated",
                event_object={"customer": "cus_yyy"},
                st=st,
            )
        self.assertEqual(cid, "db-cliente")

    def test_lookup_by_stripe_customer_id(self):
        st = _st(stripe_customer_id="cus_zzz", status="active")
        mock_sb = MagicMock()
        table = MagicMock()
        mock_sb.table.return_value = table
        chain = table.select.return_value.eq.return_value.limit.return_value
        chain.execute.return_value = _ExecResult([{"id": "cust-cliente"}])

        with patch("database.supabase_sq.supabase", mock_sb):
            cid = resolve_cliente_id_for_webhook(
                event_type="invoice.paid",
                event_object={},
                st=st,
            )
        self.assertEqual(cid, "cust-cliente")


class TestBillingPatchAndCoerce(unittest.TestCase):
    def test_cliente_billing_patch_omits_none(self):
        st = _st(status="active", stripe_subscription_id="sub_1")
        patch = cliente_billing_patch(st)
        self.assertEqual(patch.get("billing_status"), "active")
        self.assertEqual(patch.get("stripe_subscription_id"), "sub_1")
        self.assertNotIn("billing_plan_key", patch)
        self.assertNotIn("plano", patch)

    def test_coerce_pending_to_active_when_checkout_paid(self):
        st = _st(status="pending", stripe_subscription_id="sub_1")
        out = _coerce_status_after_paid_checkout(st, {"payment_status": "paid"})
        self.assertEqual(out.status, "active")

    def test_coerce_keeps_canceled(self):
        st = _st(status="canceled", stripe_subscription_id="sub_1")
        out = _coerce_status_after_paid_checkout(st, {"payment_status": "paid"})
        self.assertEqual(out.status, "canceled")


if __name__ == "__main__":
    unittest.main()
