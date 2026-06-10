import unittest

from services.agendamento_ia_bridge import build_request_body
from services.agendamento_ia_contact import (
    booking_phone_for_public_url,
    enrich_collected_from_lead,
    lead_row_to_collected,
    normalize_collected_for_agendamento,
    prepare_agendamento_context,
)


class TestAgendamentoIaContact(unittest.TestCase):
    def test_normalize_aliases(self):
        cd = normalize_collected_for_agendamento(
            {
                "name": " Ana ",
                "e-mail": "a@b.com",
                "phone": "11999",
                "__pending_keys": ["nome"],
            }
        )
        self.assertEqual(cd["nome"], "Ana")
        self.assertEqual(cd["email"], "a@b.com")
        self.assertEqual(cd["telefone"], "11999")
        self.assertNotIn("__pending_keys", cd)

    def test_enrich_from_lead_row(self):
        collected = enrich_collected_from_lead(
            {"nome": "João"},
            {
                "nome": "João Silva",
                "email": "j@x.com",
                "telefone": "5511999",
                "dados": {"empresa": "ACME"},
            },
        )
        self.assertEqual(collected["nome"], "João")
        self.assertEqual(collected["email"], "j@x.com")
        self.assertEqual(collected["telefone"], "5511999")
        self.assertEqual(collected["empresa"], "ACME")

    def test_lead_row_to_collected(self):
        cd = lead_row_to_collected(
            {"nome": "Maria", "email": "", "telefone": "21", "dados": {"email": "m@z.com"}}
        )
        self.assertEqual(cd["nome"], "Maria")
        self.assertEqual(cd["email"], "m@z.com")
        self.assertEqual(cd["telefone"], "21")

    def test_booking_phone_rejects_lid(self):
        self.assertEqual(
            booking_phone_for_public_url(remote_id="91302582575248@lid"),
            "",
        )

    def test_booking_phone_from_cus_jid(self):
        self.assertEqual(
            booking_phone_for_public_url(remote_id="5514998575752@c.us"),
            "5514998575752",
        )

    def test_booking_phone_prefers_lead_telefone(self):
        self.assertEqual(
            booking_phone_for_public_url(
                remote_id="91302582575248@lid",
                contact_phone="14998575752",
            ),
            "5514998575752",
        )

    def test_prepare_context_and_build_body(self):
        ctx = prepare_agendamento_context(
            {
                "cliente_id": "c1",
                "collected_data": {"nome": "Ricardo", "email": "r@e.com", "telefone": "1499"},
            }
        )
        self.assertEqual(ctx["contact_name"], "Ricardo")
        self.assertEqual(ctx["contact_email"], "r@e.com")
        self.assertEqual(ctx["contact_phone"], "1499")
        body = build_request_body(
            user_message="",
            context=ctx,
            session=None,
            zapaction_turn_id="t1",
            inbound_user_message_id=None,
        )
        inner = body["context"]["collected_data"]
        self.assertEqual(inner["nome"], "Ricardo")
        self.assertEqual(body["context"]["contact_email"], "r@e.com")


if __name__ == "__main__":
    unittest.main()
