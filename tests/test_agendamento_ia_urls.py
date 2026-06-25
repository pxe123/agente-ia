"""Testes de URLs e integração Agendamento IA."""
from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch

from services.agendamento_ia_appointment_webhook import (
    appointment_origin_label,
    normalize_webhook_event,
    panel_can_reassign_professional,
)
from services.agendamento_ia_bridge import agendamento_use_internal_scheduling
from services.agendamento_ia_urls import (
    build_public_book_page_url,
    resolved_agendamento_webhook_url,
    resolved_clinic_sync_url,
    resolved_link_generate_url,
)


class TestAgendamentoIaUrls(unittest.TestCase):
    def test_derive_urls_from_base(self):
        with patch("services.agendamento_ia_urls.settings") as s:
            s.AGENDAMENTO_IA_BASE_URL = "https://agenda.example.com"
            s.AGENDAMENTO_IA_WEBHOOK_URL = ""
            s.AGENDAMENTO_IA_CLINIC_SYNC_URL = ""
            s.AGENDAMENTO_IA_LINK_GENERATE_URL = ""
            self.assertEqual(
                resolved_agendamento_webhook_url(),
                "https://agenda.example.com/v1/agendamento",
            )
            self.assertEqual(
                resolved_link_generate_url(),
                "https://agenda.example.com/v1/link/generate",
            )
            self.assertEqual(
                resolved_clinic_sync_url(),
                "https://agenda.example.com/v1/integrations/zapaction/tenant-snapshot",
            )

    def test_normalize_webhook_event_alias(self):
        self.assertEqual(normalize_webhook_event("APPOINTMENT_CONFIRMED"), "appointment.created")
        self.assertEqual(normalize_webhook_event("appointment.created"), "appointment.created")

    def test_appointment_origin_label(self):
        self.assertEqual(
            appointment_origin_label({"external_agenda_appointment_id": "x"}),
            "agenda",
        )
        self.assertEqual(appointment_origin_label({"meta": {}}), "zapaction_local")

    def test_panel_can_reassign_professional(self):
        local = {"status": "confirmed", "meta": {}}
        agenda = {"status": "confirmed", "external_agenda_appointment_id": "ext-1"}
        self.assertTrue(panel_can_reassign_professional(local, auto_distribution=False))
        self.assertFalse(panel_can_reassign_professional(agenda, auto_distribution=False))
        self.assertTrue(panel_can_reassign_professional(agenda, auto_distribution=True))
        confirmed_agenda = {**agenda, "status": "confirmed"}
        self.assertTrue(panel_can_reassign_professional(confirmed_agenda, auto_distribution=True))
        self.assertFalse(
            panel_can_reassign_professional(
                {**agenda, "status": "cancelled"},
                auto_distribution=True,
            )
        )

    def test_build_public_book_page_url(self):
        with patch(
            "services.agendamento_ia_urls.agendamento_ia_public_base_url",
            return_value="https://agenda.example.com",
        ):
            url = build_public_book_page_url("clinica-a", phone="5511")
        self.assertEqual(
            url,
            "https://agenda.example.com/v1/book/clinica-a/page?phone=5511",
        )


class TestAgendamentoIaLink(unittest.TestCase):
    @patch("services.agendamento_ia_link.requests.post")
    def test_generate_appointment_link_ok(self, mock_post):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.text = '{"url":"https://agenda.example.com/v1/link/page?t=abc"}'
        mock_post.return_value = mock_resp

        with patch(
            "services.agendamento_ia_link.resolved_link_generate_url",
            return_value="https://agenda.example.com/v1/link/generate",
        ):
            from services.agendamento_ia_link import generate_appointment_link

            out = generate_appointment_link(
                cliente_id="c1",
                remote_id="5521999999999",
                canal="whatsapp",
                node_id="n1",
            )
        self.assertTrue(out["ok"])
        self.assertIn("/v1/link/page", out["url"])


class TestAgendamentoUseInternal(unittest.TestCase):
    def test_production_with_base_uses_external(self):
        with patch("services.scheduling.engine.settings") as s:
            s.SCHEDULING_FORCE_AGENDA_CLIENTE_IDS = ""
            s.SCHEDULING_INTERNAL_CLIENTE_IDS = ""
            s.USE_INTERNAL_SCHEDULING = False
            with patch(
                "services.scheduling.engine._read_engine_from_db",
                return_value=None,
            ):
                with patch(
                    "services.scheduling.engine.is_production_environment",
                    return_value=True,
                ):
                    with patch(
                        "services.scheduling.engine.agendamento_ia_base_url",
                        return_value="https://agenda.example.com",
                    ):
                        with patch(
                            "services.scheduling.engine.resolved_agendamento_webhook_url",
                            return_value="https://agenda.example.com/v1/agendamento",
                        ):
                            self.assertFalse(agendamento_use_internal_scheduling())


if __name__ == "__main__":
    unittest.main()
