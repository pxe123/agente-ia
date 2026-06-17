"""Testes nome/telefone página pública."""
from __future__ import annotations

import unittest

from services.scheduling.public_contact import (
    format_br_phone_input,
    normalize_scheduling_contact_phone,
    parse_panel_contact_phone,
    validate_public_contact,
)


class TestPublicContact(unittest.TestCase):
    def test_format_mask_mobile(self):
        self.assertEqual(format_br_phone_input("11999887766"), "(11) 99988-7766")

    def test_format_strips_country_code(self):
        self.assertEqual(format_br_phone_input("5511999887766"), "(11) 99988-7766")

    def test_format_with_country(self):
        self.assertEqual(
            format_br_phone_input("11999887766", with_country=True),
            "+55 (11) 99988-7766",
        )

    def test_normalize_scheduling_contact_phone(self):
        self.assertEqual(normalize_scheduling_contact_phone("(11) 99988-7766"), "5511999887766")
        self.assertEqual(normalize_scheduling_contact_phone("5511999887766"), "5511999887766")
        self.assertIsNone(normalize_scheduling_contact_phone("123"))

    def test_parse_panel_contact_phone(self):
        phone, err = parse_panel_contact_phone("(14) 99999-9999")
        self.assertIsNone(err)
        self.assertEqual(phone, "5514999999999")
        phone, err = parse_panel_contact_phone("")
        self.assertIsNone(err)
        self.assertIsNone(phone)

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
