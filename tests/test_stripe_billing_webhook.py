from __future__ import annotations

import unittest
from unittest.mock import patch


class _DummyExecResult:
    def __init__(self, data=None):
        self.data = data or []


class _DummyTable:
    def __init__(self):
        self._data = []

    def select(self, _cols: str):
        return self

    def eq(self, _k: str, _v):
        return self

    def limit(self, _n: int):
        return self

    def execute(self):
        return _DummyExecResult(data=[])

    def upsert(self, _payload, on_conflict: str = ""):
        return self

    def update(self, _payload):
        return self


class _DummySupabase:
    def table(self, _name: str):
        return _DummyTable()


class TestStripeWebhookBasics(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # Import tardio para permitir patch do supabase no módulo
        from billing.routes import stripe_billing_bp
        from flask import Flask

        app = Flask(__name__)
        app.config["TESTING"] = True
        app.register_blueprint(stripe_billing_bp)
        cls.client = app.test_client()

    def test_webhook_requires_signature_header(self):
        with patch("billing.routes.supabase", _DummySupabase()):
            resp = self.client.post("/api/billing/stripe/webhook", data=b"{}")
        self.assertEqual(resp.status_code, 400)

    def test_webhook_rejects_invalid_signature(self):
        with patch("billing.routes.supabase", _DummySupabase()):
            resp = self.client.post(
                "/api/billing/stripe/webhook",
                data=b"{}",
                headers={"Stripe-Signature": "t=123,v1=deadbeef"},
            )
        self.assertEqual(resp.status_code, 400)


if __name__ == "__main__":
    unittest.main()

