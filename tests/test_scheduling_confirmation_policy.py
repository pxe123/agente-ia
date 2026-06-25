"""Testes — política de confirmação de agendamento."""
from __future__ import annotations

import unittest
from unittest.mock import patch

from services.scheduling.confirmation_policy import (
    build_booking_meta_patch,
    confirmation_policy_label,
    get_confirmation_policy,
    requires_professional_confirmation,
    resolve_initial_appointment_status,
)


class TestConfirmationPolicy(unittest.TestCase):
    @patch("services.scheduling.confirmation_policy.scheduling_repository.get_settings")
    def test_default_auto(self, mock_settings):
        mock_settings.return_value = {}
        self.assertEqual(get_confirmation_policy("cid"), "auto")
        self.assertFalse(requires_professional_confirmation("cid"))
        self.assertEqual(resolve_initial_appointment_status("cid"), "confirmed")
        self.assertEqual(build_booking_meta_patch("cid"), {})

    @patch("services.scheduling.confirmation_policy.scheduling_uses_internal_motor")
    @patch("services.scheduling.confirmation_policy.scheduling_repository.get_settings")
    def test_professional_internal(self, mock_settings, mock_internal):
        mock_settings.return_value = {"confirmation_policy": "professional"}
        mock_internal.return_value = True
        self.assertEqual(get_confirmation_policy("cid"), "professional")
        self.assertTrue(requires_professional_confirmation("cid"))
        self.assertEqual(resolve_initial_appointment_status("cid"), "pending")
        meta = build_booking_meta_patch("cid")
        self.assertEqual(meta.get("confirmation_policy"), "professional")
        self.assertIn("confirmation_requested_at", meta)

    @patch("services.agendamento_ia_urls.agendamento_ia_configured", return_value=False)
    @patch("services.scheduling.confirmation_policy.scheduling_uses_internal_motor")
    @patch("services.scheduling.confirmation_policy.scheduling_repository.get_settings")
    def test_professional_external_fallback_auto(self, mock_settings, mock_internal, _configured):
        mock_settings.return_value = {"confirmation_policy": "professional"}
        mock_internal.return_value = False
        self.assertEqual(get_confirmation_policy("cid"), "auto")
        self.assertEqual(resolve_initial_appointment_status("cid"), "confirmed")

    @patch("services.agendamento_ia_urls.agendamento_ia_configured", return_value=True)
    @patch("services.scheduling.confirmation_policy.scheduling_uses_internal_motor", return_value=False)
    @patch("services.scheduling.confirmation_policy.scheduling_repository.get_settings")
    def test_professional_agenda_ia(self, mock_settings, _internal, _configured):
        mock_settings.return_value = {"confirmation_policy": "professional"}
        self.assertEqual(get_confirmation_policy("cid"), "professional")
        self.assertEqual(resolve_initial_appointment_status("cid"), "pending")

    def test_labels(self):
        self.assertEqual(confirmation_policy_label("auto"), "Confirmação automática")
        self.assertEqual(confirmation_policy_label("professional"), "Confirmação pelo profissional")


if __name__ == "__main__":
    unittest.main()
