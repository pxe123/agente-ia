"""Testes das proteções de cadastro público."""
from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch

from base.signup_security import signup_rate_limit_exceeded
from services.signup_protection import (
    check_turnstile_for_signup,
    get_client_ip,
    honeypot_triggered,
    is_disposable_email,
    normalize_signup_email,
)
from billing.models import normalize_plan_key


class TestSignupProtection(unittest.TestCase):
    def test_normalize_email(self):
        self.assertEqual(normalize_signup_email("  Foo@Bar.COM "), "foo@bar.com")

    def test_disposable_domain(self):
        self.assertTrue(is_disposable_email("x@mailinator.com"))
        self.assertFalse(is_disposable_email("x@empresa.com.br"))

    def test_honeypot_empty_ok(self):
        form = {"website": "", "email": "a@b.com"}
        self.assertFalse(honeypot_triggered(form))

    def test_honeypot_filled(self):
        form = {"website": "http://spam.example", "email": "a@b.com"}
        self.assertTrue(honeypot_triggered(form))

    def test_client_ip_x_forwarded(self):
        req = MagicMock()
        req.headers = {"X-Forwarded-For": "203.0.113.1, 10.0.0.1"}
        req.remote_addr = "127.0.0.1"
        self.assertEqual(get_client_ip(req), "203.0.113.1")

    def test_rate_limit_blocks_after_threshold(self):
        ip = "test-rate-limit-ip-unique"
        self.assertFalse(signup_rate_limit_exceeded(ip))
        self.assertFalse(signup_rate_limit_exceeded(ip))
        self.assertFalse(signup_rate_limit_exceeded(ip))
        self.assertTrue(signup_rate_limit_exceeded(ip))

    @patch("services.signup_protection.is_production_environment", return_value=False)
    @patch("services.signup_protection.turnstile_configured", return_value=False)
    def test_turnstile_skipped_dev(self, _cfg, _prod):
        ok, reason = check_turnstile_for_signup("", "1.2.3.4")
        self.assertTrue(ok)
        self.assertIsNone(reason)

    @patch("services.signup_protection.is_production_environment", return_value=True)
    @patch("services.signup_protection.turnstile_configured", return_value=False)
    def test_turnstile_required_prod(self, _cfg, _prod):
        ok, reason = check_turnstile_for_signup("", "1.2.3.4")
        self.assertFalse(ok)
        self.assertEqual(reason, "turnstile_not_configured")

    @patch("services.signup_protection.turnstile_configured", return_value=True)
    @patch("services.signup_protection.verify_turnstile", return_value=True)
    def test_turnstile_ok(self, _verify, _cfg):
        ok, reason = check_turnstile_for_signup("token", "1.2.3.4")
        self.assertTrue(ok)
        self.assertIsNone(reason)

    def test_normalize_plan_key_legacy(self):
        self.assertEqual(normalize_plan_key("plan_test"), "starter")
        self.assertEqual(normalize_plan_key("plan_pro"), "pro")
        self.assertEqual(normalize_plan_key("plan_master"), "business")


if __name__ == "__main__":
    unittest.main()
