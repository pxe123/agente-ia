"""Testes de URL pública /v1/book e resolução de link de agendamento."""
from __future__ import annotations

import unittest
from unittest.mock import patch

from services.agendamento_ia_urls import build_public_book_page_url


class TestBuildPublicBookPageUrl(unittest.TestCase):
    def test_slug_and_query(self):
        with patch(
            "services.agendamento_ia_urls.agendamento_ia_public_base_url",
            return_value="https://agenda.example.com",
        ):
            url = build_public_book_page_url(
                "Minha-Clinica",
                phone="5511999999999",
                name="Maria",
            )
        self.assertIn("https://agenda.example.com/v1/book/minha-clinica/page", url)
        self.assertIn("phone=5511999999999", url)
        self.assertIn("name=Maria", url)

    def test_empty_slug(self):
        self.assertEqual(build_public_book_page_url(""), "")


if __name__ == "__main__":
    unittest.main()
