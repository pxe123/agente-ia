"""Testes do rollout motor interno (flags por tenant + scheduling_engine BD)."""
from __future__ import annotations

import unittest
from unittest.mock import patch

from services.agendamento_ia_bridge import (
    agendamento_use_internal_scheduling,
    scheduling_uses_internal_motor,
)
from services.agendamento_ia_link import (
    build_zapaction_public_agenda_url,
    resolve_booking_url_for_contact,
)


class TestSchedulingUsesInternalMotor(unittest.TestCase):
    def test_force_agenda_overrides_allowlist(self):
        cid = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
        with patch("services.scheduling.engine.settings") as s:
            s.SCHEDULING_FORCE_AGENDA_CLIENTE_IDS = cid
            s.SCHEDULING_INTERNAL_CLIENTE_IDS = cid
            s.USE_INTERNAL_SCHEDULING = True
            with patch(
                "services.scheduling.engine._read_engine_from_db",
                return_value="zapaction_internal",
            ):
                self.assertFalse(scheduling_uses_internal_motor(cid))

    def test_allowlist_enables_internal_in_production(self):
        cid = "11111111-2222-3333-4444-555555555555"
        with patch("services.scheduling.engine.settings") as s:
            s.SCHEDULING_FORCE_AGENDA_CLIENTE_IDS = ""
            s.SCHEDULING_INTERNAL_CLIENTE_IDS = cid
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
                        self.assertTrue(scheduling_uses_internal_motor(cid))

    def test_production_without_allowlist_uses_external(self):
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
                            self.assertFalse(agendamento_use_internal_scheduling("any-client"))

    def test_global_flag_enables_internal(self):
        with patch("services.scheduling.engine.settings") as s:
            s.SCHEDULING_FORCE_AGENDA_CLIENTE_IDS = ""
            s.SCHEDULING_INTERNAL_CLIENTE_IDS = ""
            s.USE_INTERNAL_SCHEDULING = True
            with patch(
                "services.scheduling.engine._read_engine_from_db",
                return_value=None,
            ):
                self.assertTrue(scheduling_uses_internal_motor("client-x"))


class TestInternalAgendaUrl(unittest.TestCase):
    def test_build_zapaction_public_agenda_url(self):
        with patch(
            "base.domain_redirects.public_base_url",
            return_value="https://zapaction.com.br",
        ):
            url = build_zapaction_public_agenda_url("clinica", phone="5511", name="Ana")
        self.assertEqual(
            url,
            "https://zapaction.com.br/agenda/clinica?phone=5511&name=Ana",
        )

    def test_resolve_booking_prefers_internal_when_flagged(self):
        cid = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
        with patch(
            "services.agendamento_ia_bridge.scheduling_uses_internal_motor",
            return_value=True,
        ):
            with patch(
                "services.scheduling.repository.supabase_available",
                return_value=True,
            ):
                with patch(
                    "services.scheduling.repository.get_settings",
                    return_value={"public_slug": "minha-clinica"},
                ):
                    with patch(
                        "services.agendamento_ia_link.build_zapaction_public_agenda_url",
                        return_value="https://zapaction.com.br/agenda/minha-clinica?phone=55",
                    ):
                        url, src = resolve_booking_url_for_contact(
                            cliente_id=cid,
                            remote_id="5521999999999",
                        )
        self.assertEqual(src, "public_slug")
        self.assertIn("/agenda/minha-clinica", url)


if __name__ == "__main__":
    unittest.main()
