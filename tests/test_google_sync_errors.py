"""Testes de mensagens de erro Google sync no painel."""
from __future__ import annotations

import unittest

from services.scheduling.google_sync_errors import format_agenda_operation_error


class TestGoogleSyncErrors(unittest.TestCase):
    def test_google_create_failed(self):
        msg = format_agenda_operation_error("GOOGLE_CREATE_FAILED")
        self.assertIn("Google Calendar", msg)
        self.assertIn("Reconecte", msg)

    def test_unknown_code_passthrough(self):
        self.assertEqual(format_agenda_operation_error("CUSTOM_CODE"), "CUSTOM_CODE")

    def test_empty(self):
        self.assertEqual(format_agenda_operation_error(None), "erro desconhecido")


if __name__ == "__main__":
    unittest.main()
