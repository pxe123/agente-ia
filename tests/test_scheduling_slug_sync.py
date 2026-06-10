"""Slug e provider_services no snapshot."""
from __future__ import annotations

import unittest

from services.agendamento_ia_sync import build_provider_services_links
from services.scheduling.slug import normalize_public_slug


class TestSchedulingSlugSync(unittest.TestCase):
    def test_normalize_slug(self):
        self.assertEqual(normalize_public_slug("  Clinica_Teste  "), "clinica-teste")
        self.assertEqual(normalize_public_slug("minha clínica"), "minha-cl-nica")

    def test_provider_services_one_prof(self):
        profs = [{"id": "p1", "name": "A", "active": True}]
        svcs = [
            {
                "id": "s1",
                "name": "Corte",
                "active": True,
                "professional_id": "p1",
            }
        ]
        links = build_provider_services_links(profs, svcs)
        self.assertEqual(links, [{"provider_id": "p1", "service_id": "s1"}])

    def test_provider_services_all_prof(self):
        profs = [
            {"id": "p1", "name": "A", "active": True},
            {"id": "p2", "name": "B", "active": True},
        ]
        svcs = [{"id": "s1", "name": "Corte", "active": True, "professional_id": None}]
        links = build_provider_services_links(profs, svcs)
        self.assertEqual(len(links), 2)

    def test_provider_services_inactive_prof_ignored(self):
        profs = [
            {"id": "p1", "name": "A", "active": False},
        ]
        svcs = [
            {
                "id": "s1",
                "name": "Corte",
                "active": True,
                "professional_id": "p1",
            }
        ]
        links = build_provider_services_links(profs, svcs)
        self.assertEqual(links, [])


if __name__ == "__main__":
    unittest.main()
