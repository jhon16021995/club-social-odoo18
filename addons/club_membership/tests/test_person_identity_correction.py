from odoo import Command
from odoo.exceptions import AccessError, ValidationError
from odoo.tests import tagged
from odoo.tests.common import TransactionCase


@tagged("post_install", "-at_install")
class TestPersonIdentityCorrection(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()

        cls.admin = cls.env.ref("base.user_admin")
        cls.internal_group = cls.env.ref("base.group_user")

        cls.Partner = cls.env["res.partner"].with_user(cls.admin)
        cls.Audit = cls.env["club.person.audit.event"].with_user(cls.admin)
        cls.Kardex = cls.env["club.kardex.event"].with_user(cls.admin)

        cls.regular_user = cls.env["res.users"].create(
            {
                "name": "Usuario prueba sin corrección",
                "login": "club_identity_regular_test",
                "groups_id": [
                    Command.set(
                        [
                            cls.internal_group.id,
                        ]
                    )
                ],
            }
        )

        if cls.regular_user.has_group("club_membership.group_club_identity_correction"):
            raise AssertionError(
                "El usuario regular de prueba no debe tener "
                "permiso de corrección de identidad."
            )

    def _next_available_id_number(self, start):
        number = start

        while self.Partner.search(
            [
                ("club_id_number", "=", str(number)),
            ],
            limit=1,
        ):
            number += 1

        return str(number)

    def _create_client(self, name="Cliente prueba auditoría"):
        return self.Partner.create(
            {
                "name": name,
                "company_type": "person",
                "club_person_type": "client",
                "club_id_number": self._next_available_id_number(99100000100),
                "club_id_extension": "LP",
                "club_birthdate": "1990-01-01",
            }
        )

    def _create_member(self):
        return self.Partner.create(
            {
                "name": "Socio prueba auditoría",
                "company_type": "person",
                "club_person_type": "member",
                "club_id_number": self._next_available_id_number(99100000200),
                "club_id_extension": "LP",
                "club_birthdate": "1985-06-15",
            }
        )

    def test_direct_sensitive_write_is_blocked(self):
        client = self._create_client()

        with self.assertRaises(ValidationError):
            client.write(
                {
                    "name": "Cambio directo no autorizado",
                }
            )

        client.invalidate_recordset()

        self.assertEqual(
            client.name,
            "Cliente prueba auditoría",
        )

    def test_normal_data_remains_editable(self):
        client = self._create_client()

        client.write(
            {
                "phone": "22123456",
                "email": "prueba@example.com",
            }
        )

        client.invalidate_recordset()

        self.assertEqual(
            client.phone,
            "22123456",
        )
        self.assertEqual(
            client.email,
            "prueba@example.com",
        )

    def test_user_without_permission_cannot_correct_identity(self):
        client = self._create_client()

        with self.assertRaises(AccessError):
            client.with_user(self.regular_user).correct_sensitive_identity(
                "name",
                "Cambio no autorizado",
                "Intento de prueba sin permiso.",
            )

    def test_client_correction_creates_audit_without_kardex(self):
        client = self._create_client()

        reason = "Corrección automática de prueba."

        client.correct_sensitive_identity(
            "name",
            "Cliente prueba corregido",
            reason,
        )

        client.invalidate_recordset()

        self.assertEqual(
            client.name,
            "Cliente prueba corregido",
        )

        audits = self.Audit.search(
            [
                ("person_id", "=", client.id),
            ]
        )

        self.assertEqual(
            len(audits),
            1,
        )
        self.assertEqual(
            audits.field_name,
            "name",
        )
        self.assertEqual(
            audits.old_value,
            "Cliente prueba auditoría",
        )
        self.assertEqual(
            audits.new_value,
            "Cliente prueba corregido",
        )
        self.assertEqual(
            audits.reason,
            reason,
        )
        self.assertEqual(
            audits.user_id,
            self.admin,
        )

        self.assertFalse(
            self.Kardex.search(
                [
                    ("member_id", "=", client.id),
                ]
            )
        )

    def test_same_value_is_rejected(self):
        client = self._create_client()

        with self.assertRaises(ValidationError):
            client.correct_sensitive_identity(
                "name",
                client.name,
                "Prueba de valor idéntico.",
            )

        self.assertFalse(
            self.Audit.search(
                [
                    ("person_id", "=", client.id),
                ]
            )
        )

    def test_extension_can_be_cleared(self):
        client = self._create_client()

        client.correct_sensitive_identity(
            "club_id_extension",
            False,
            "Corrección de extensión para prueba.",
        )

        client.invalidate_recordset()

        self.assertFalse(client.club_id_extension)

        audit = self.Audit.search(
            [
                ("person_id", "=", client.id),
                ("field_name", "=", "club_id_extension"),
            ]
        )

        self.assertEqual(
            len(audit),
            1,
        )
        self.assertEqual(
            audit.old_value,
            "LP",
        )
        self.assertEqual(
            audit.new_value,
            "Sin valor",
        )

    def test_duplicate_id_number_is_rejected(self):
        first_client = self._create_client(name="Primer cliente prueba")
        second_client = self._create_client(name="Segundo cliente prueba")

        with self.assertRaises(ValidationError):
            first_client.correct_sensitive_identity(
                "club_id_number",
                second_client.club_id_number,
                "Prueba de carnet duplicado.",
            )

        first_client.invalidate_recordset()

        self.assertNotEqual(
            first_client.club_id_number,
            second_client.club_id_number,
        )

        self.assertFalse(
            self.Audit.search(
                [
                    ("person_id", "=", first_client.id),
                ]
            )
        )

    def test_member_id_correction_updates_code_and_kardex_once(self):
        member = self._create_member()

        old_id_number = member.club_id_number
        new_id_number = self._next_available_id_number(99100000300)

        generic_event_types = [
            "member_identity_updated",
            "member_code_changed",
        ]

        generic_before = self.Kardex.search_count(
            [
                ("member_id", "=", member.id),
                ("event_type", "in", generic_event_types),
            ]
        )

        reason = "Corrección de carnet para prueba automática."

        member.correct_sensitive_identity(
            "club_id_number",
            new_id_number,
            reason,
        )

        member.invalidate_recordset()

        self.assertEqual(
            member.club_id_number,
            new_id_number,
        )
        self.assertEqual(
            member.club_member_code,
            new_id_number,
        )

        audits = self.Audit.search(
            [
                ("person_id", "=", member.id),
            ]
        )

        self.assertEqual(
            len(audits),
            1,
        )
        self.assertEqual(
            audits.field_name,
            "club_id_number",
        )
        self.assertEqual(
            audits.old_value,
            old_id_number,
        )
        self.assertEqual(
            audits.new_value,
            new_id_number,
        )
        self.assertEqual(
            audits.reason,
            reason,
        )

        correction_events = self.Kardex.search(
            [
                ("member_id", "=", member.id),
                (
                    "event_type",
                    "=",
                    "member_identity_corrected",
                ),
            ]
        )

        self.assertEqual(
            len(correction_events),
            1,
        )
        self.assertEqual(
            correction_events.person_audit_event_id,
            audits,
        )
        self.assertEqual(
            correction_events.reason,
            reason,
        )

        generic_after = self.Kardex.search_count(
            [
                ("member_id", "=", member.id),
                ("event_type", "in", generic_event_types),
            ]
        )

        self.assertEqual(
            generic_before,
            generic_after,
        )
