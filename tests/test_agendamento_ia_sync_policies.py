"""Snapshot tenant — políticas de assignment e confirmação."""
from __future__ import annotations

import unittest
from unittest.mock import patch

from services.agendamento_ia_sync import build_tenant_snapshot_payload


class TestAgendamentoIaSyncPolicies(unittest.TestCase):
    @patch("services.agendamento_ia_sync.sched_repo.list_services", return_value=[])
    @patch("services.agendamento_ia_sync.sched_repo.list_professionals", return_value=[])
    @patch("services.agendamento_ia_sync.sched_repo.list_working_hours_all", return_value=[])
    @patch("services.agendamento_ia_sync.sched_repo.get_assignment_mode", return_value="auto_distribution")
    @patch("services.agendamento_ia_sync.sched_repo.get_settings")
    @patch("services.agendamento_ia_sync.sched_repo.supabase_available", return_value=True)
    def test_snapshot_includes_policies(
        self,
        _sb,
        mock_settings,
        _mode,
        _wh,
        _profs,
        _svcs,
    ):
        mock_settings.return_value = {
            "public_name": "Clínica",
            "public_slug": "clinica-teste",
            "timezone": "America/Sao_Paulo",
            "professional_assignment_mode": "auto_distribution",
            "confirmation_policy": "professional",
            "confirmation_pending_ttl_hours": 72,
        }
        payload = build_tenant_snapshot_payload("cid-1")
        self.assertIsNotNone(payload)
        clinic = payload["clinic"]
        self.assertEqual(clinic["professional_assignment_mode"], "auto_distribution")
        self.assertEqual(clinic["confirmation_policy"], "professional")
        self.assertEqual(clinic["confirmation_pending_ttl_hours"], 72)


if __name__ == "__main__":
    unittest.main()
