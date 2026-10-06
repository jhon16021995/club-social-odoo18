from dateutil.relativedelta import relativedelta
from odoo import fields
from odoo.exceptions import AccessError, ValidationError
from odoo.tests import tagged
from odoo.tests.common import TransactionCase, new_test_user


@tagged("post_install", "-at_install")
class TestClientToBeneficiaryConversion(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()

        cls.admin = cls.env.ref("base.user_admin")

        cls.Partner = cls.env["res.partner"].with_user(cls.admin)
        cls.Beneficiary = cls.env["club.beneficiary"].with_user(cls.admin)
        cls.Period = cls.env["club.membership.period"].with_user(cls.admin)

        cls.regular_user = new_test_user(
            cls.env,
            login="club_client_to_beneficiary_without_permission",
            groups="base.group_user",
            name="Usuario sin permiso Cliente a Beneficiario",
        )

        cls.member = cls._create_member(
            "Socio titular Cliente a Beneficiario",
            99730000100,
        )

    @classmethod
    def _next_available_id_number(cls, start):
        number = start

        while cls.Partner.search(
            [("club_id_number", "=", str(number))],
            limit=1,
        ):
            number += 1

        return str(number)

    @classmethod
    def _create_member(cls, name, start_number):
        return cls.Partner.create(
            {
                "name": name,
                "company_type": "person",
                "is_company": False,
                "club_person_type": "member",
                "club_id_number": cls._next_available_id_number(start_number),
                "club_birthdate": "1980-01-01",
            }
        )

    @classmethod
    def _create_client(
        cls,
        name,
        start_number,
        *,
        is_company=False,
    ):
        vals = {
            "name": name,
            "company_type": "company" if is_company else "person",
            "is_company": is_company,
            "club_person_type": "client",
            "club_id_number": cls._next_available_id_number(start_number),
        }

        if not is_company:
            vals["club_birthdate"] = "1990-01-01"

        return cls.Partner.create(vals)

    def _conversion_values(
        self,
        **overrides,
    ):
        values = {
            "member_id": self.member.id,
            "relationship": "spouse",
            "special_condition": "none",
            "start_date": fields.Date.context_today(self.Partner),
        }

        values.update(overrides)

        return values

    def test_direct_client_role_removal_is_blocked(self):
        client = self._create_client(
            "Cliente protección salida directa",
            99730000200,
        )

        with self.assertRaisesRegex(
            ValidationError,
            "Un Cliente no puede abandonar su condición",
        ):
            client.write(
                {
                    "club_person_type": False,
                }
            )

        client.invalidate_recordset()

        self.assertEqual(
            client.club_person_type,
            "client",
        )

    def test_fake_internal_context_token_cannot_bypass_role_protection(self):
        client = self._create_client(
            "Cliente protección token falso",
            99730000300,
        )

        with self.assertRaisesRegex(
            ValidationError,
            "Un Cliente no puede abandonar su condición",
        ):
            client.with_context(
                club_client_to_beneficiary_internal_token=True,
            ).write(
                {
                    "club_person_type": False,
                }
            )

        client.invalidate_recordset()

        self.assertEqual(
            client.club_person_type,
            "client",
        )

    def test_direct_beneficiary_create_with_client_is_blocked(self):
        client = self._create_client(
            "Cliente protección create directo Beneficiario",
            99730000350,
        )

        with self.assertRaisesRegex(
            ValidationError,
            "Un Cliente no puede ser Beneficiario al mismo tiempo",
        ):
            with self.env.cr.savepoint():
                self.Beneficiary.create(
                    {
                        "person_id": client.id,
                        "member_id": self.member.id,
                        "relationship": "spouse",
                        "special_condition": "none",
                        "start_date": fields.Date.context_today(client),
                    }
                )

        client.invalidate_recordset()

        self.assertEqual(
            client.club_person_type,
            "client",
        )

        self.assertFalse(
            self.Beneficiary.search(
                [
                    ("person_id", "=", client.id),
                    ("state", "in", ("active", "blocked")),
                ],
                limit=1,
            )
        )

    def test_conversion_requires_specific_permission(self):
        client = self._create_client(
            "Cliente sin permiso conversión Beneficiario",
            99730000400,
        )

        with self.assertRaisesRegex(
            AccessError,
            "No tiene permiso para convertir un Cliente en Beneficiario.",
        ):
            client.with_user(self.regular_user).action_convert_client_to_beneficiary(
                self._conversion_values()
            )

        client.invalidate_recordset()

        self.assertEqual(
            client.club_person_type,
            "client",
        )

        self.assertFalse(
            self.Beneficiary.search(
                [
                    ("person_id", "=", client.id),
                    ("state", "in", ("active", "blocked")),
                ],
                limit=1,
            )
        )

    def test_first_time_client_converts_reusing_same_person(self):
        client = self._create_client(
            "Cliente convertido a Beneficiario",
            99730000500,
        )

        original_person_id = client.id
        original_id_number = client.club_id_number
        today = fields.Date.context_today(client)

        beneficiary_id = client.action_convert_client_to_beneficiary(
            self._conversion_values(
                relationship="partner",
                start_date=today,
                observations="Conversión controlada de prueba.",
            )
        )

        client.invalidate_recordset()

        beneficiary = self.Beneficiary.browse(beneficiary_id)
        beneficiary.invalidate_recordset()

        self.assertEqual(
            client.id,
            original_person_id,
        )
        self.assertEqual(
            client.club_id_number,
            original_id_number,
        )
        self.assertFalse(
            client.club_person_type,
        )

        self.assertEqual(
            beneficiary.person_id,
            client,
        )
        self.assertEqual(
            beneficiary.member_id,
            self.member,
        )
        self.assertEqual(
            beneficiary.relationship,
            "partner",
        )
        self.assertEqual(
            beneficiary.start_date,
            today,
        )
        self.assertEqual(
            beneficiary.state,
            "active",
        )
        self.assertEqual(
            beneficiary.observations,
            "Conversión controlada de prueba.",
        )

        self.assertFalse(
            self.Period.search(
                [
                    ("person_id", "=", client.id),
                ],
                limit=1,
            )
        )

    def test_failed_beneficiary_creation_rolls_back_client_role_removal(self):
        client = self._create_client(
            "Cliente rollback conversión",
            99730000600,
        )

        with self.assertRaises(ValidationError):
            client.action_convert_client_to_beneficiary(
                self._conversion_values(
                    relationship="worker",
                )
            )

        client.invalidate_recordset()

        self.assertEqual(
            client.club_person_type,
            "client",
        )

        self.assertFalse(
            self.Beneficiary.search(
                [
                    ("person_id", "=", client.id),
                    ("state", "in", ("active", "blocked")),
                ],
                limit=1,
            )
        )

    def test_client_with_current_membership_period_is_blocked(self):
        client = self._create_client(
            "Cliente inconsistente período vigente Beneficiario",
            99730000700,
        )

        today = fields.Date.context_today(client)

        # Fixture técnico para simular datos heredados inconsistentes.
        # pylint: disable=protected-access
        current_period = self.Period._create_period_internal(
            {
                "person_id": client.id,
                "start_date": today - relativedelta(years=1),
                "origin": "initial",
                "member_code": client.club_id_number,
            }
        )
        # pylint: enable=protected-access

        with self.assertRaisesRegex(
            ValidationError,
            "período de membresía vigente inconsistente",
        ):
            client.action_convert_client_to_beneficiary(self._conversion_values())

        client.invalidate_recordset()
        current_period.invalidate_recordset()

        self.assertEqual(
            client.club_person_type,
            "client",
        )
        self.assertEqual(
            current_period.state,
            "current",
        )

    def test_client_with_finalized_membership_history_is_blocked(self):
        client = self._create_client(
            "Cliente con historia real Ex-Socio",
            99730000800,
        )

        today = fields.Date.context_today(client)

        # Fixture técnico para representar una membresía legítima histórica.
        # pylint: disable=protected-access
        period = self.Period._create_period_internal(
            {
                "person_id": client.id,
                "start_date": today - relativedelta(years=5),
                "origin": "initial",
                "member_code": client.club_id_number,
            }
        )
        period._finalize_period_internal(
            today - relativedelta(years=1),
            "Finalización histórica de prueba.",
        )
        # pylint: enable=protected-access

        client.invalidate_recordset()
        period.invalidate_recordset()

        self.assertTrue(
            client.club_is_former_member,
        )
        self.assertEqual(
            period.state,
            "finalized",
        )

        with self.assertRaisesRegex(
            ValidationError,
            "posee historia real como Ex-Socio",
        ):
            client.action_convert_client_to_beneficiary(self._conversion_values())

        client.invalidate_recordset()

        self.assertEqual(
            client.club_person_type,
            "client",
        )

    def test_client_with_only_voided_membership_history_can_convert(self):
        client = self._create_client(
            "Cliente con historia anulada a Beneficiario",
            99730000900,
        )

        today = fields.Date.context_today(client)

        # Fixture técnico de alta histórica errónea ya anulada.
        # pylint: disable=protected-access
        period = self.Period._create_period_internal(
            {
                "person_id": client.id,
                "start_date": today - relativedelta(years=3),
                "origin": "initial",
                "member_code": client.club_id_number,
            }
        )
        period._void_period_internal("Alta histórica errónea de prueba.")
        # pylint: enable=protected-access

        client.invalidate_recordset()
        period.invalidate_recordset()

        self.assertFalse(
            client.club_is_former_member,
        )
        self.assertEqual(
            period.state,
            "voided",
        )

        beneficiary_id = client.action_convert_client_to_beneficiary(
            self._conversion_values()
        )

        client.invalidate_recordset()
        period.invalidate_recordset()

        beneficiary = self.Beneficiary.browse(beneficiary_id)
        beneficiary.invalidate_recordset()

        self.assertFalse(
            client.club_person_type,
        )
        self.assertEqual(
            beneficiary.state,
            "active",
        )
        self.assertEqual(
            period.state,
            "voided",
        )

    def test_boolean_member_id_is_rejected_without_partial_conversion(self):
        client = self._create_client(
            "Cliente member id booleano",
            99730001000,
        )

        with self.assertRaisesRegex(
            ValidationError,
            "Debe seleccionar un Socio titular válido.",
        ):
            client.action_convert_client_to_beneficiary(
                self._conversion_values(
                    member_id=True,
                )
            )

        client.invalidate_recordset()

        self.assertEqual(
            client.club_person_type,
            "client",
        )

    def test_company_client_cannot_convert_to_beneficiary(self):
        client = self._create_client(
            "Empresa Cliente no Beneficiaria",
            99730001100,
            is_company=True,
        )

        with self.assertRaisesRegex(
            ValidationError,
            "Una empresa Cliente no puede convertirse en Beneficiario",
        ):
            client.action_convert_client_to_beneficiary(self._conversion_values())

        client.invalidate_recordset()

        self.assertEqual(
            client.club_person_type,
            "client",
        )
