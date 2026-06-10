from __future__ import annotations

import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch


class TestLegacyMercadopagoGrace(unittest.TestCase):
    def test_legacy_mp_with_future_period_end_allowed(self):
        from services.billing.subscription_service import is_legacy_mercadopago_grace

        future = (datetime.now(timezone.utc) + timedelta(days=10)).isoformat()
        mock_supabase = MagicMock()

        def table_side_effect(name):
            t = MagicMock()
            if name == "clientes":
                t.select.return_value.eq.return_value.limit.return_value.execute.return_value = MagicMock(
                    data=[{"mp_preapproval_id": "mp-123", "billing_current_period_end": future}]
                )
            elif name == "subscriptions":
                t.select.return_value.eq.return_value.limit.return_value.execute.return_value = MagicMock(data=[])
            return t

        mock_supabase.table.side_effect = table_side_effect

        with patch("services.billing.subscription_service.supabase", mock_supabase):
            self.assertTrue(is_legacy_mercadopago_grace("cliente-1", "active"))

    def test_legacy_mp_expired_period_not_grace(self):
        from services.billing.subscription_service import is_legacy_mercadopago_grace

        past = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()
        mock_supabase = MagicMock()

        def table_side_effect(name):
            t = MagicMock()
            if name == "clientes":
                t.select.return_value.eq.return_value.limit.return_value.execute.return_value = MagicMock(
                    data=[{"mp_preapproval_id": "mp-123", "billing_current_period_end": past}]
                )
            elif name == "subscriptions":
                t.select.return_value.eq.return_value.limit.return_value.execute.return_value = MagicMock(data=[])
            return t

        mock_supabase.table.side_effect = table_side_effect

        with patch("services.billing.subscription_service.supabase", mock_supabase):
            self.assertFalse(is_legacy_mercadopago_grace("cliente-1", "active"))

    def test_stripe_active_with_subscription_id_allowed(self):
        from services.entitlements import can_use_product

        mock_supabase = MagicMock()

        def table_side_effect(name):
            t = MagicMock()
            if name == "subscriptions":
                t.select.return_value.eq.return_value.limit.return_value.execute.return_value = MagicMock(
                    data=[{"status": "active", "current_period_end": None, "trial_ends_at": None, "plan_key": "pro"}]
                )
            elif name == "clientes":
                chain = t.select.return_value.eq.return_value.limit.return_value
                chain.execute.return_value = MagicMock(
                    data=[
                        {
                            "billing_status": "active",
                            "billing_current_period_end": None,
                            "trial_ends_at": None,
                            "billing_plan_key": "pro",
                            "billing_cancel_at_period_end": False,
                            "mp_preapproval_id": None,
                            "stripe_subscription_id": "sub_stripe123",
                        }
                    ]
                )
            return t

        mock_supabase.table.side_effect = table_side_effect

        with patch("services.entitlements.supabase", mock_supabase):
            with patch("services.billing.subscription_service.supabase", mock_supabase):
                with patch("services.entitlements.settings") as mock_settings:
                    mock_settings.ENVIRONMENT = "production"
                    mock_settings.SUPER_ADMIN_TENANT_IDS = []
                    result = can_use_product("cliente-stripe")
        self.assertTrue(result.allowed)

    def test_legacy_mp_expired_without_stripe_blocked_in_production(self):
        from services.entitlements import can_use_product

        past = (datetime.now(timezone.utc) - timedelta(days=2)).isoformat()
        mock_supabase = MagicMock()

        def table_side_effect(name):
            t = MagicMock()
            if name == "subscriptions":
                t.select.return_value.eq.return_value.limit.return_value.execute.return_value = MagicMock(
                    data=[
                        {
                            "status": "active",
                            "current_period_end": past,
                            "trial_ends_at": None,
                            "plan_key": "pro",
                            "provider": "mercadopago",
                        }
                    ]
                )
            elif name == "clientes":
                chain = t.select.return_value.eq.return_value.limit.return_value
                chain.execute.return_value = MagicMock(
                    data=[
                        {
                            "billing_status": "active",
                            "billing_current_period_end": past,
                            "trial_ends_at": None,
                            "billing_plan_key": "pro",
                            "billing_cancel_at_period_end": False,
                            "mp_preapproval_id": "mp-old",
                            "stripe_subscription_id": None,
                        }
                    ]
                )
            return t

        mock_supabase.table.side_effect = table_side_effect

        with patch("services.entitlements.supabase", mock_supabase):
            with patch("services.billing.subscription_service.supabase", mock_supabase):
                with patch("services.entitlements.settings") as mock_settings:
                    mock_settings.ENVIRONMENT = "production"
                    mock_settings.SUPER_ADMIN_TENANT_IDS = []
                    result = can_use_product("cliente-mp-expired")
        self.assertFalse(result.allowed)


if __name__ == "__main__":
    unittest.main()
