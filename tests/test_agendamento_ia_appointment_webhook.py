"""Testes do webhook reverso Agendamento IA → ZapAction (assinatura + parsing)."""
from __future__ import annotations

import hashlib
import hmac
import time
import unittest

from services.agendamento_ia_appointment_webhook import (
    _resolve_professional_id,
    normalize_webhook_event,
    parse_json_body,
    verify_zapaction_webhook_signature,
)


def _sign(secret: str, ts: str, body: bytes) -> str:
    body_text = body.decode("utf-8")
    msg = f"{ts}.{body_text}".encode("utf-8")
    return hmac.new(secret.encode("utf-8"), msg, hashlib.sha256).hexdigest()


class TestAgendamentoIaAppointmentWebhook(unittest.TestCase):
    def test_verify_signature_ok(self):
        secret = "test-secret-32-chars-minimum-xx"
        body = b'{"event":"appointment.created","request_schema_version":1}'
        ts = str(int(time.time()))
        sig = f"sha256={_sign(secret, ts, body)}"
        ok, err = verify_zapaction_webhook_signature(
            secret=secret, raw_body=body, timestamp_header=ts, signature_header=sig
        )
        self.assertTrue(ok, err)
        self.assertIsNone(err)

    def test_verify_signature_rejects_bad_secret(self):
        body = b'{"a":1}'
        ts = str(int(time.time()))
        sig = f"sha256={_sign('good', ts, body)}"
        ok, err = verify_zapaction_webhook_signature(
            secret="wrong", raw_body=body, timestamp_header=ts, signature_header=sig
        )
        self.assertFalse(ok)
        self.assertEqual(err, "assinatura_invalida")

    def test_verify_signature_rejects_old_timestamp(self):
        secret = "test-secret-32-chars-minimum-xx"
        body = b"{}"
        ts = str(int(time.time()) - 99999)
        sig = f"sha256={_sign(secret, ts, body)}"
        ok, err = verify_zapaction_webhook_signature(
            secret=secret, raw_body=body, timestamp_header=ts, signature_header=sig
        )
        self.assertFalse(ok)
        self.assertEqual(err, "timestamp_fora_da_janela")

    def test_parse_json_body(self):
        d, err = parse_json_body(b'{"x":1}')
        self.assertIsNone(err)
        self.assertEqual(d, {"x": 1})
        d2, err2 = parse_json_body(b"not-json")
        self.assertIsNone(d2)
        self.assertEqual(err2, "json_invalido")

    def test_normalize_appointment_confirmed_alias(self):
        self.assertEqual(normalize_webhook_event("APPOINTMENT_CONFIRMED"), "appointment.created")

    def test_resolve_professional_any_is_none(self):
        self.assertIsNone(_resolve_professional_id("c1", "any"))
        self.assertIsNone(_resolve_professional_id("c1", "not-a-uuid"))


if __name__ == "__main__":
    unittest.main()
