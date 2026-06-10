"""Resolução scheduling_engine por tenant (BD + fallback env)."""
from __future__ import annotations

import unittest
from unittest.mock import patch

from services.scheduling.engine import (
    ENGINE_AGENDAMENTO_IA,
    ENGINE_ZAPACTION_INTERNAL,
    get_scheduling_engine,
    scheduling_uses_internal_motor,
    set_scheduling_engine,
)


class TestSchedulingEngineResolver(unittest.TestCase):
    def test_db_internal_overrides_empty_env(self):
        cid = "11111111-2222-3333-4444-555555555555"
        with patch("services.scheduling.engine.settings") as s:
            s.SCHEDULING_FORCE_AGENDA_CLIENTE_IDS = ""
            s.SCHEDULING_INTERNAL_CLIENTE_IDS = ""
            s.USE_INTERNAL_SCHEDULING = False
            with patch(
                "services.scheduling.engine._read_engine_from_db",
                return_value=ENGINE_ZAPACTION_INTERNAL,
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

    def test_db_agenda_overrides_env_allowlist(self):
        cid = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
        with patch("services.scheduling.engine.settings") as s:
            s.SCHEDULING_FORCE_AGENDA_CLIENTE_IDS = ""
            s.SCHEDULING_INTERNAL_CLIENTE_IDS = cid
            s.USE_INTERNAL_SCHEDULING = False
            with patch(
                "services.scheduling.engine._read_engine_from_db",
                return_value=ENGINE_AGENDAMENTO_IA,
            ):
                with patch(
                    "services.scheduling.engine.is_production_environment",
                    return_value=True,
                ):
                    with patch(
                        "services.scheduling.engine.agendamento_ia_base_url",
                        return_value="https://agenda.example.com",
                    ):
                        self.assertFalse(scheduling_uses_internal_motor(cid))

    def test_env_allowlist_fallback_when_no_db_row(self):
        cid = "22222222-3333-4444-5555-666666666666"
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

    def test_force_agenda_env_blocks_all(self):
        cid = "33333333-4444-5555-6666-777777777777"
        with patch("services.scheduling.engine.settings") as s:
            s.SCHEDULING_FORCE_AGENDA_CLIENTE_IDS = cid
            s.SCHEDULING_INTERNAL_CLIENTE_IDS = cid
            s.USE_INTERNAL_SCHEDULING = True
            with patch(
                "services.scheduling.engine._read_engine_from_db",
                return_value=ENGINE_ZAPACTION_INTERNAL,
            ):
                self.assertFalse(scheduling_uses_internal_motor(cid))

    def test_get_scheduling_engine_from_db(self):
        with patch(
            "services.scheduling.engine._read_engine_from_db",
            return_value=ENGINE_ZAPACTION_INTERNAL,
        ):
            self.assertEqual(
                get_scheduling_engine("x"),
                ENGINE_ZAPACTION_INTERNAL,
            )

    def test_set_scheduling_engine_invalid(self):
        ok, err = set_scheduling_engine("x", "invalid")
        self.assertFalse(ok)
        self.assertEqual(err, "engine_invalido")


if __name__ == "__main__":
    unittest.main()
