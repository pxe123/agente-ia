"""Testes — tokens e resolução de propostas."""
from __future__ import annotations

import hashlib
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

from services.scheduling.confirmation_tokens import resolve_token


class TestConfirmationTokens(unittest.TestCase):
    @patch("services.scheduling.confirmation_tokens.repository.get_confirmation_token_by_hash")
    def test_resolve_valid_token(self, mock_get):
        exp = (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()
        mock_get.return_value = {
            "id": "t1",
            "action": "accept_proposal",
            "expires_at": exp,
            "used_at": None,
        }
        row, err = resolve_token("abc" * 8)
        self.assertIsNone(err)
        self.assertIsNotNone(row)
        expected_hash = hashlib.sha256(("abc" * 8).encode("utf-8")).hexdigest()
        mock_get.assert_called_once_with(expected_hash)

    @patch("services.scheduling.confirmation_tokens.repository.get_confirmation_token_by_hash")
    def test_resolve_expired_token(self, mock_get):
        exp = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
        mock_get.return_value = {
            "id": "t1",
            "action": "accept_proposal",
            "expires_at": exp,
            "used_at": None,
        }
        row, err = resolve_token("x" * 20)
        self.assertIsNone(row)
        self.assertEqual(err, "token_expirado")

    def test_resolve_short_token(self):
        row, err = resolve_token("short")
        self.assertIsNone(row)
        self.assertEqual(err, "token_invalido")


if __name__ == "__main__":
    unittest.main()
