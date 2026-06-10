"""Testes nome/telefone página pública."""
from __future__ import annotations

import unittest

from services.scheduling.public_contact import format_br_phone_input, validate_public_contact


class TestPublicContact(unittest.TestCase):
    def test_format_mask_mobile(self):
        self.assertEqual(format_br_phone_input("11999887766"), "(11) 99988-7766")

    def test_format_strips_country_code(self):
        self.assertEqual(format_br_phone_input("5511999887766"), "(11) 99988-7766")

    def test_validate_ok(self):
        nome, phone, err = validate_public_contact(name="Maria Silva", phone="(11) 99988-7766")
        self.assertIsNone(err)
        self.assertEqual(nome, "Maria Silva")
        self.assertEqual(phone, "5511999887766")

    def test_validate_name_required(self):
        _, _, err = validate_public_contact(name=" ", phone="(11) 99988-7766")
        self.assertIn("nome", err.lower())

    def test_validate_phone_invalid(self):
        _, _, err = validate_public_contact(name="João", phone="(11) 9999")
        self.assertIn("Telefone", err)


if __name__ == "__main__":
    unittest.main()
