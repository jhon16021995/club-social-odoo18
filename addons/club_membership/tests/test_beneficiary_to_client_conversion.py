from unittest.mock import patch

from dateutil.relativedelta import relativedelta
from odoo import fields
from odoo.exceptions import AccessError, ValidationError
from odoo.tests import tagged
from odoo.tests.common import TransactionCase, new_test_user


@tagged("post_install", "-at_install")
class TestBeneficiaryToClientConversion(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()

        cls.admin = cls.env.ref("base.user_admin")
        cls.Partner = cls.env["res.partner"].with_user(cls.admin)
        cls.Beneficiary = cls.env["club.beneficiary"].with_user(cls.admin)
        cls.Period = cls.env["club.membership.period"].with_user(cls.admin)

        cls.regular_user = new_test_user(
            cls.env,
            login="club_beneficiary_to_client_without_permission",
            groups="base.group_user",
            name="Usuario sin permiso Beneficiario a Cliente",
        )

        cls.member = cls._create_member(
            "Socio titular Beneficiario a Cliente",
            99740000100,
        )

        cls.other_member = cls._create_member(
            "Segundo Socio titular Beneficiario a Cliente",
            99740000150,
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
    def _create_person(cls, name, start_number):
        return cls.Partner.create(
            {
                "name": name,
                "company_type": "person",
                "is_company": False,
                "club_id_number": cls._next_available_id_number(start_number),
                "club_birthdate": "1990-01-01",
            }
        )

    @classmethod
    def _create_beneficiary(
        cls,
        name,
        start_number,
        *,
        member=None,
        relationship="spouse",
    ):
        person = cls._create_person(name, start_number)

        beneficiary = cls.Beneficiary.create(
            {
                "person_id": person.id,
                "member_id": (member or cls.member).id,
                "relationship": relationship,
                "special_condition": "none",
                "start_date": fields.Date.context_today(person),
            }
        )

        return person, beneficiary

    def test_direct_beneficiary_history_to_client_is_blocked(self):
        person, beneficiary = self._create_beneficiary(
            "Beneficiario protección cambio directo Cliente",
            99740000200,
        )

        beneficiary.finalize_link(
            end_date=fields.Date.context_today(beneficiary),
            reason="Finalización histórica para prueba.",
        )

        with self.assertRaisesRegex(
            ValidationError,
            "historial de Beneficiario no puede convertirse en Cliente",
        ):
            person.write(
                {
                    "club_person_type": "client",
                }
            )

        person.invalidate_recordset()
        beneficiary.invalidate_recordset()

        self.assertFalse(person.club_person_type)
        self.assertEqual(beneficiary.state, "finalized")

    def test_fake_internal_token_and_conversion_context_cannot_bypass_protection(self):
        person, beneficiary = self._create_beneficiary(
            "Beneficiario protección token falso Cliente",
            99740000300,
        )

        with self.assertRaisesRegex(
            ValidationError,
            "historial de Beneficiario no puede convertirse en Cliente",
        ):
            person.with_context(
                club_beneficiary_to_client_internal_token=True,
                club_conversion_beneficiary_id=beneficiary.id,
            ).write(
                {
                    "club_person_type": "client",
                }
            )

        person.invalidate_recordset()
        beneficiary.invalidate_recordset()

        self.assertFalse(person.club_person_type)
        self.assertEqual(beneficiary.state, "active")

    def test_conversion_requires_specific_permission(self):
        person, beneficiary = self._create_beneficiary(
            "Beneficiario sin permiso conversión Cliente",
            99740000400,
        )

        today = fields.Date.context_today(beneficiary)

        with self.assertRaisesRegex(
            AccessError,
            "No tiene permiso para convertir un Beneficiario en Cliente.",
        ):
            beneficiary.with_user(
                self.regular_user
            ).action_convert_beneficiary_to_client(
                {
                    "end_date": today,
                    "reason": "Conversión administrativa.",
                }
            )

        person.invalidate_recordset()
        beneficiary.invalidate_recordset()

        self.assertFalse(person.club_person_type)
        self.assertEqual(beneficiary.state, "active")

    def test_active_beneficiary_converts_reusing_same_person(self):
        person, beneficiary = self._create_beneficiary(
            "Beneficiario activo convertido a Cliente",
            99740000500,
        )

        original_person_id = person.id
        original_id_number = person.club_id_number
        today = fields.Date.context_today(beneficiary)
        reason = "Conversión administrativa de Beneficiario a Cliente."

        person_id = beneficiary.action_convert_beneficiary_to_client(
            {
                "end_date": today,
                "reason": reason,
            }
        )

        person.invalidate_recordset()
        beneficiary.invalidate_recordset()

        self.assertEqual(person_id, original_person_id)
        self.assertEqual(person.id, original_person_id)
        self.assertEqual(person.club_id_number, original_id_number)
        self.assertEqual(person.club_person_type, "client")

        self.assertEqual(beneficiary.person_id, person)
        self.assertEqual(beneficiary.state, "finalized")
        self.assertEqual(beneficiary.end_date, today)
        self.assertEqual(beneficiary.end_reason, reason)
        self.assertFalse(beneficiary.block_reason)

        self.assertFalse(
            self.Period.search(
                [
                    ("person_id", "=", person.id),
                ],
                limit=1,
            )
        )

    def test_blocked_beneficiary_converts_and_clears_block_state(self):
        person, beneficiary = self._create_beneficiary(
            "Beneficiario bloqueado convertido a Cliente",
            99740000600,
        )

        beneficiary.write(
            {
                "state": "blocked",
                "block_reason": "Bloqueo administrativo previo.",
            }
        )

        today = fields.Date.context_today(beneficiary)

        beneficiary.action_convert_beneficiary_to_client(
            {
                "end_date": today,
                "reason": "Conversión de vínculo bloqueado a Cliente.",
            }
        )

        person.invalidate_recordset()
        beneficiary.invalidate_recordset()

        self.assertEqual(person.club_person_type, "client")
        self.assertEqual(beneficiary.state, "finalized")
        self.assertEqual(beneficiary.end_date, today)
        self.assertFalse(beneficiary.block_reason)
        self.assertFalse(beneficiary.blocked_by_member_withdrawal)

    def test_finalized_beneficiary_converts_preserving_history(self):
        person, beneficiary = self._create_beneficiary(
            "Beneficiario histórico convertido a Cliente",
            99740000700,
        )

        today = fields.Date.context_today(beneficiary)
        historical_date = today
        historical_reason = "Finalización histórica anterior."

        beneficiary.finalize_link(
            end_date=historical_date,
            reason=historical_reason,
        )

        beneficiary.invalidate_recordset()

        original_member = beneficiary.member_id
        original_relationship = beneficiary.relationship
        original_end_date = beneficiary.end_date
        original_end_reason = beneficiary.end_reason

        person_id = beneficiary.action_convert_beneficiary_to_client()

        person.invalidate_recordset()
        beneficiary.invalidate_recordset()

        self.assertEqual(person_id, person.id)
        self.assertEqual(person.club_person_type, "client")
        self.assertEqual(beneficiary.state, "finalized")
        self.assertEqual(beneficiary.member_id, original_member)
        self.assertEqual(beneficiary.relationship, original_relationship)
        self.assertEqual(beneficiary.end_date, original_end_date)
        self.assertEqual(beneficiary.end_reason, original_end_reason)

    def test_failed_client_write_rolls_back_beneficiary_finalization(self):
        person, beneficiary = self._create_beneficiary(
            "Beneficiario rollback conversión Cliente",
            99740000800,
        )

        today = fields.Date.context_today(beneficiary)

        original_write = type(person).write

        def failing_write(recordset, vals):
            if vals.get("club_person_type") == "client":
                raise ValidationError(
                    self.env._("Fallo controlado posterior a finalización.")
                )
            return original_write(recordset, vals)

        with patch.object(
            type(person),
            "write",
            new=failing_write,
        ):
            with self.assertRaisesRegex(
                ValidationError,
                "Fallo controlado posterior a finalización",
            ):
                beneficiary.action_convert_beneficiary_to_client(
                    {
                        "end_date": today,
                        "reason": "Prueba de rollback transaccional.",
                    }
                )

        person.invalidate_recordset()
        beneficiary.invalidate_recordset()

        self.assertFalse(person.club_person_type)
        self.assertEqual(beneficiary.state, "active")
        self.assertFalse(beneficiary.end_date)
        self.assertFalse(beneficiary.end_reason)

        self.assertFalse(
            self.env["club.kardex.event"].search(
                [
                    ("beneficiary_id", "=", beneficiary.id),
                    ("event_type", "=", "beneficiary_finalized"),
                    ("reason", "=", "Prueba de rollback transaccional."),
                ],
                limit=1,
            )
        )

    def test_future_end_date_is_blocked_without_partial_conversion(self):
        person, beneficiary = self._create_beneficiary(
            "Beneficiario fecha futura conversión Cliente",
            99740000900,
        )

        tomorrow = fields.Date.context_today(beneficiary) + relativedelta(days=1)

        with self.assertRaisesRegex(
            ValidationError,
            "fecha de finalización del vínculo no puede ser futura",
        ):
            beneficiary.action_convert_beneficiary_to_client(
                {
                    "end_date": tomorrow,
                    "reason": "Fecha futura no permitida.",
                }
            )

        person.invalidate_recordset()
        beneficiary.invalidate_recordset()

        self.assertFalse(person.club_person_type)
        self.assertEqual(beneficiary.state, "active")

    def test_current_membership_period_is_blocked(self):
        person, beneficiary = self._create_beneficiary(
            "Beneficiario con período vigente inconsistente",
            99740001000,
        )

        today = fields.Date.context_today(person)

        # Fixture técnico para representar datos heredados inconsistentes.
        # pylint: disable=protected-access
        period = self.Period._create_period_internal(
            {
                "person_id": person.id,
                "start_date": today - relativedelta(years=1),
                "origin": "initial",
                "member_code": person.club_id_number,
            }
        )
        # pylint: enable=protected-access

        with self.assertRaisesRegex(
            ValidationError,
            "período de membresía vigente",
        ):
            beneficiary.action_convert_beneficiary_to_client(
                {
                    "end_date": today,
                    "reason": "Conversión que debe bloquearse.",
                }
            )

        person.invalidate_recordset()
        beneficiary.invalidate_recordset()
        period.invalidate_recordset()

        self.assertFalse(person.club_person_type)
        self.assertEqual(beneficiary.state, "active")
        self.assertEqual(period.state, "current")

    def test_finalized_membership_history_is_blocked_as_former_member(self):
        person, beneficiary = self._create_beneficiary(
            "Beneficiario con historia real Ex-Socio",
            99740001100,
        )

        today = fields.Date.context_today(person)

        # Fixture técnico de membresía legítima histórica.
        # pylint: disable=protected-access
        period = self.Period._create_period_internal(
            {
                "person_id": person.id,
                "start_date": today - relativedelta(years=5),
                "origin": "initial",
                "member_code": person.club_id_number,
            }
        )
        period._finalize_period_internal(
            today - relativedelta(years=1),
            "Finalización histórica de prueba.",
        )
        # pylint: enable=protected-access

        person.invalidate_recordset()
        period.invalidate_recordset()

        self.assertTrue(person.club_is_former_member)
        self.assertEqual(period.state, "finalized")

        with self.assertRaisesRegex(
            ValidationError,
            "historia real como Ex-Socio",
        ):
            beneficiary.action_convert_beneficiary_to_client(
                {
                    "end_date": today,
                    "reason": "No debe absorber Ex-Socio a Cliente.",
                }
            )

        person.invalidate_recordset()
        beneficiary.invalidate_recordset()

        self.assertFalse(person.club_person_type)
        self.assertEqual(beneficiary.state, "active")

    def test_only_voided_membership_history_can_convert(self):
        person, beneficiary = self._create_beneficiary(
            "Beneficiario con membresía anulada a Cliente",
            99740001200,
        )

        today = fields.Date.context_today(person)

        # Fixture técnico de alta histórica errónea ya anulada.
        # pylint: disable=protected-access
        period = self.Period._create_period_internal(
            {
                "person_id": person.id,
                "start_date": today - relativedelta(years=3),
                "origin": "initial",
                "member_code": person.club_id_number,
            }
        )
        period._void_period_internal("Alta histórica errónea de prueba.")
        # pylint: enable=protected-access

        person.invalidate_recordset()
        period.invalidate_recordset()

        self.assertFalse(person.club_is_former_member)
        self.assertEqual(period.state, "voided")

        beneficiary.action_convert_beneficiary_to_client(
            {
                "end_date": today,
                "reason": "Conversión con historia únicamente anulada.",
            }
        )

        person.invalidate_recordset()
        beneficiary.invalidate_recordset()
        period.invalidate_recordset()

        self.assertEqual(person.club_person_type, "client")
        self.assertEqual(beneficiary.state, "finalized")
        self.assertEqual(period.state, "voided")

    def test_finalized_source_is_blocked_when_another_current_link_exists(self):
        person, historical_link = self._create_beneficiary(
            "Beneficiario histórico con otro vínculo vigente",
            99740001300,
        )

        today = fields.Date.context_today(historical_link)

        historical_link.finalize_link(
            end_date=today,
            reason="Cierre del vínculo histórico.",
        )

        current_link = self.Beneficiary.create(
            {
                "person_id": person.id,
                "member_id": self.other_member.id,
                "relationship": "parent",
                "special_condition": "none",
                "start_date": today,
            }
        )

        with self.assertRaisesRegex(
            ValidationError,
            "posee actualmente otro vínculo vigente",
        ):
            historical_link.action_convert_beneficiary_to_client()

        person.invalidate_recordset()
        historical_link.invalidate_recordset()
        current_link.invalidate_recordset()

        self.assertFalse(person.club_person_type)
        self.assertEqual(historical_link.state, "finalized")
        self.assertEqual(current_link.state, "active")
