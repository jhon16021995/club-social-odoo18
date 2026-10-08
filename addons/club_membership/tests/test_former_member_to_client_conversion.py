from unittest.mock import patch

from dateutil.relativedelta import relativedelta
from odoo import fields
from odoo.exceptions import AccessError, ValidationError
from odoo.tests import tagged
from odoo.tests.common import TransactionCase, new_test_user


@tagged("post_install", "-at_install")
class TestFormerMemberToClientConversion(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()

        cls.admin = cls.env.ref("base.user_admin")
        cls.Partner = cls.env["res.partner"].with_user(cls.admin)
        cls.Beneficiary = cls.env["club.beneficiary"].with_user(cls.admin)
        cls.Certificate = cls.env["club.certificate"].with_user(cls.admin)
        cls.Period = cls.env["club.membership.period"].with_user(cls.admin)
        cls.Kardex = cls.env["club.kardex.event"].with_user(cls.admin)

        cls.regular_user = new_test_user(
            cls.env,
            login="club_former_member_to_client_without_permission",
            groups="base.group_user",
            name="Usuario sin permiso Ex-Socio a Cliente",
        )

    @classmethod
    def _birthdate_for_age(cls, age):
        today = fields.Date.context_today(cls.Partner)
        return fields.Date.to_string(today - relativedelta(years=age))

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
    def _create_member(cls, name, start_number, join_date):
        return cls.Partner.create(
            {
                "name": name,
                "company_type": "person",
                "is_company": False,
                "club_person_type": "member",
                "club_id_number": cls._next_available_id_number(start_number),
                "club_birthdate": cls._birthdate_for_age(40),
                "club_join_date": join_date,
            }
        )

    @classmethod
    def _create_certificate(cls, member):
        return cls.Certificate.create(
            {
                "member_id": member.id,
                "registration_origin": "new",
                "total_value": 1000.0,
                "opening_balance": 1000.0,
            }
        )

    def _prepare_former_member(
        self,
        name,
        start_number,
        *,
        with_certificate=False,
    ):
        today = fields.Date.context_today(self.Partner)

        member = self._create_member(
            name,
            start_number,
            join_date=today - relativedelta(years=5),
        )

        certificate = (
            self._create_certificate(member) if with_certificate else self.Certificate
        )

        member.action_end_club_membership(
            "Baja definitiva previa a conversión Ex-Socio a Cliente.",
            effective_date=today,
        )

        member.invalidate_recordset()

        if certificate:
            certificate.invalidate_recordset()

        self.assertFalse(member.club_person_type)
        self.assertTrue(member.club_is_former_member)

        return member, certificate, today

    def _create_current_beneficiary(self, person, today):
        titular = self._create_member(
            "Socio titular prueba Ex-Socio a Cliente",
            99810009000,
            join_date=today - relativedelta(years=8),
        )

        beneficiary_id = person.action_convert_former_member_to_beneficiary(
            {
                "member_id": titular.id,
                "relationship": "parent",
                "special_condition": "none",
                "start_date": today,
            }
        )

        return self.Beneficiary.browse(beneficiary_id)

    def test_direct_former_member_to_client_write_is_blocked(self):
        former, _certificate, _today = self._prepare_former_member(
            "Ex-Socio protección write directo a Cliente",
            99810000100,
        )

        with self.assertRaisesRegex(
            ValidationError,
            "Convertir Ex-Socio en Cliente",
        ):
            former.write(
                {
                    "club_person_type": "client",
                }
            )

        former.invalidate_recordset()

        self.assertFalse(former.club_person_type)
        self.assertTrue(former.club_is_former_member)

    def test_fake_internal_token_cannot_bypass_direct_write(self):
        former, _certificate, _today = self._prepare_former_member(
            "Ex-Socio token falso a Cliente",
            99810000200,
        )

        with self.assertRaises(ValidationError):
            former.with_context(
                club_former_member_to_client_internal_token=True,
            ).write(
                {
                    "club_person_type": "client",
                }
            )

        former.invalidate_recordset()

        self.assertFalse(former.club_person_type)
        self.assertTrue(former.club_is_former_member)

    def test_conversion_requires_specific_permission(self):
        former, _certificate, _today = self._prepare_former_member(
            "Ex-Socio sin permiso a Cliente",
            99810000300,
        )

        with self.assertRaises(AccessError):
            former.with_user(self.regular_user).action_convert_former_member_to_client(
                "No debe ejecutarse sin permiso."
            )

        former.invalidate_recordset()

        self.assertFalse(former.club_person_type)

    def test_conversion_requires_reason(self):
        former, _certificate, _today = self._prepare_former_member(
            "Ex-Socio sin motivo a Cliente",
            99810000400,
        )

        with self.assertRaises(ValidationError):
            former.action_convert_former_member_to_client("   ")

        former.invalidate_recordset()

        self.assertFalse(former.club_person_type)
        self.assertTrue(former.club_is_former_member)

    def test_former_member_converts_preserving_history_and_certificate(self):
        former, certificate, _today = self._prepare_former_member(
            "Ex-Socio conversión correcta a Cliente",
            99810000500,
            with_certificate=True,
        )

        id_number = former.club_id_number

        periods_before = self.Period.search(
            [("person_id", "=", former.id)],
            order="id",
        )

        period_snapshot = [
            (
                period.id,
                period.state,
                period.origin,
                period.start_date,
                period.end_date,
                period.end_reason,
                period.member_code,
            )
            for period in periods_before
        ]

        certificate_snapshot = (
            certificate.state,
            certificate.passive_by_member_withdrawal,
            certificate.passive_by_membership_end,
        )

        event_before = self.Kardex.search_count(
            [
                ("member_id", "=", former.id),
                (
                    "event_type",
                    "=",
                    "former_member_converted_to_client",
                ),
            ]
        )

        reason = "Conversión administrativa aprobada de Ex-Socio a Cliente."

        result = former.action_convert_former_member_to_client(reason)

        former.invalidate_recordset()
        certificate.invalidate_recordset()

        self.assertEqual(result, former.id)
        self.assertEqual(former.club_person_type, "client")
        self.assertEqual(former.club_id_number, id_number)
        self.assertTrue(former.club_is_former_member)

        periods_after = self.Period.search(
            [("person_id", "=", former.id)],
            order="id",
        )

        self.assertEqual(
            [
                (
                    period.id,
                    period.state,
                    period.origin,
                    period.start_date,
                    period.end_date,
                    period.end_reason,
                    period.member_code,
                )
                for period in periods_after
            ],
            period_snapshot,
        )

        self.assertEqual(
            (
                certificate.state,
                certificate.passive_by_member_withdrawal,
                certificate.passive_by_membership_end,
            ),
            certificate_snapshot,
        )

        events = self.Kardex.search(
            [
                ("member_id", "=", former.id),
                (
                    "event_type",
                    "=",
                    "former_member_converted_to_client",
                ),
            ],
            order="id",
        )

        self.assertEqual(len(events), event_before + 1)

        event = events[-1]

        self.assertEqual(event.member_id, former)
        self.assertEqual(
            event.old_value,
            "Condición institucional: Ex-Socio",
        )
        self.assertEqual(event.new_value, "Cliente")
        self.assertEqual(event.reason, reason)
        self.assertEqual(event.user_id, self.admin)
        self.assertEqual(event.origin, "manual")

    def test_current_beneficiary_link_blocks_conversion(self):
        former, _certificate, today = self._prepare_former_member(
            "Ex-Socio Beneficiario vigente bloquea Cliente",
            99810000600,
        )

        beneficiary = self._create_current_beneficiary(
            former,
            today,
        )

        with self.assertRaisesRegex(
            ValidationError,
            "vínculo vigente como Beneficiario",
        ):
            former.action_convert_former_member_to_client(
                "No debe convertir mientras exista Beneficiario vigente."
            )

        former.invalidate_recordset()
        beneficiary.invalidate_recordset()

        self.assertFalse(former.club_person_type)
        self.assertEqual(beneficiary.state, "active")

    def test_finalized_beneficiary_history_does_not_block_conversion(self):
        former, _certificate, today = self._prepare_former_member(
            "Ex-Socio con Beneficiario histórico a Cliente",
            99810000700,
        )

        beneficiary = self._create_current_beneficiary(
            former,
            today,
        )

        beneficiary.finalize_link(
            end_date=today,
            reason="Cierre histórico previo a conversión a Cliente.",
        )

        beneficiary.invalidate_recordset()

        historical_snapshot = (
            beneficiary.state,
            beneficiary.member_id.id,
            beneficiary.relationship,
            beneficiary.start_date,
            beneficiary.end_date,
            beneficiary.end_reason,
        )

        former.action_convert_former_member_to_client(
            "Conversión con historia de Beneficiario ya finalizada."
        )

        former.invalidate_recordset()
        beneficiary.invalidate_recordset()

        self.assertEqual(former.club_person_type, "client")

        self.assertEqual(
            (
                beneficiary.state,
                beneficiary.member_id.id,
                beneficiary.relationship,
                beneficiary.start_date,
                beneficiary.end_date,
                beneficiary.end_reason,
            ),
            historical_snapshot,
        )

    def test_kardex_failure_rolls_back_client_role(self):
        former, _certificate, _today = self._prepare_former_member(
            "Ex-Socio rollback Kardex a Cliente",
            99810000800,
        )

        before_count = self.Kardex.search_count(
            [
                ("member_id", "=", former.id),
                (
                    "event_type",
                    "=",
                    "former_member_converted_to_client",
                ),
            ]
        )

        kardex_model_class = type(self.Kardex)

        with patch.object(
            kardex_model_class,
            "_log_former_member_to_client_event",
            autospec=True,
            side_effect=ValidationError("Fallo controlado posterior a cambio de rol."),
        ):
            with self.assertRaisesRegex(
                ValidationError,
                "Fallo controlado posterior",
            ):
                former.action_convert_former_member_to_client(
                    "Debe revertirse completamente."
                )

        former.invalidate_recordset()

        self.assertFalse(former.club_person_type)
        self.assertTrue(former.club_is_former_member)

        after_count = self.Kardex.search_count(
            [
                ("member_id", "=", former.id),
                (
                    "event_type",
                    "=",
                    "former_member_converted_to_client",
                ),
            ]
        )

        self.assertEqual(after_count, before_count)

    def test_converted_client_returns_to_member_as_reentry(self):
        former, _certificate, today = self._prepare_former_member(
            "Ex-Socio Cliente luego Reingreso",
            99810000900,
        )

        old_periods = self.Period.search(
            [("person_id", "=", former.id)],
            order="id",
        )

        self.assertEqual(len(old_periods), 1)
        self.assertEqual(old_periods.state, "finalized")

        former.action_convert_former_member_to_client(
            "Primero pasa de Ex-Socio a Cliente."
        )

        former.invalidate_recordset()

        self.assertEqual(former.club_person_type, "client")

        former.action_convert_client_to_member(
            reason="Retorno posterior desde Cliente como Reingreso.",
            effective_date=today,
        )

        former.invalidate_recordset()

        periods = self.Period.search(
            [("person_id", "=", former.id)],
            order="id",
        )

        self.assertEqual(len(periods), 2)
        self.assertEqual(periods[0].state, "finalized")
        self.assertEqual(periods[1].state, "current")
        self.assertEqual(periods[1].origin, "reentry")
        self.assertEqual(former.club_person_type, "member")
