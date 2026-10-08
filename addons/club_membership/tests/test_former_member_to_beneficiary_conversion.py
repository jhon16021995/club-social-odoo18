from dateutil.relativedelta import relativedelta
from odoo import fields
from odoo.exceptions import AccessError, ValidationError
from odoo.tests import tagged
from odoo.tests.common import TransactionCase, new_test_user


@tagged("post_install", "-at_install")
class TestFormerMemberToBeneficiaryConversion(TransactionCase):
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
            login="club_former_member_to_beneficiary_without_permission",
            groups="base.group_user",
            name="Usuario sin permiso Ex-Socio a Beneficiario",
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
    def _birthdate_for_age(cls, age):
        today = fields.Date.context_today(cls.Partner)
        return fields.Date.to_string(today - relativedelta(years=age))

    @classmethod
    def _create_member(
        cls,
        name,
        start_number,
        *,
        join_date=False,
        is_company=False,
    ):
        vals = {
            "name": name,
            "company_type": "company" if is_company else "person",
            "is_company": is_company,
            "club_person_type": "member",
            "club_id_number": cls._next_available_id_number(start_number),
        }

        if join_date:
            vals["club_join_date"] = join_date

        if not is_company:
            vals["club_birthdate"] = cls._birthdate_for_age(40)

        return cls.Partner.create(vals)

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
        is_company=False,
    ):
        today = fields.Date.context_today(self.Partner)

        member = self._create_member(
            name,
            start_number,
            join_date=today - relativedelta(years=5),
            is_company=is_company,
        )

        certificate = (
            self._create_certificate(member) if with_certificate else self.Certificate
        )

        member.action_end_club_membership(
            "Baja definitiva previa a conversión Ex-Socio a Beneficiario.",
            effective_date=today,
        )

        member.invalidate_recordset()

        if certificate:
            certificate.invalidate_recordset()

        self.assertFalse(member.club_person_type)
        self.assertTrue(member.club_is_former_member)

        return member, certificate, today

    def _conversion_values(self, holder, start_date, **overrides):
        values = {
            "member_id": holder.id,
            "relationship": "spouse",
            "special_condition": "none",
            "start_date": start_date,
        }

        values.update(overrides)

        return values

    def test_direct_beneficiary_create_for_former_member_is_blocked(self):
        former, _certificate, today = self._prepare_former_member(
            "Ex-Socio create directo Beneficiario",
            99820000100,
        )

        holder = self._create_member(
            "Titular create directo Ex-Socio",
            99820000200,
            join_date=today - relativedelta(years=8),
        )

        with self.assertRaisesRegex(
            ValidationError,
            "Convertir Ex-Socio en Beneficiario",
        ):
            self.Beneficiary.create(
                {
                    "person_id": former.id,
                    "member_id": holder.id,
                    "relationship": "spouse",
                    "special_condition": "none",
                    "start_date": today,
                }
            )

        self.assertFalse(
            self.Beneficiary.search(
                [
                    ("person_id", "=", former.id),
                    ("state", "in", ("active", "blocked")),
                ],
                limit=1,
            )
        )

    def test_fake_internal_token_cannot_bypass_direct_create(self):
        former, _certificate, today = self._prepare_former_member(
            "Ex-Socio token falso Beneficiario",
            99820000300,
        )

        holder = self._create_member(
            "Titular token falso Ex-Socio",
            99820000400,
            join_date=today - relativedelta(years=8),
        )

        with self.assertRaisesRegex(
            ValidationError,
            "Convertir Ex-Socio en Beneficiario",
        ):
            self.Beneficiary.with_context(
                club_former_member_to_beneficiary_internal_token=True,
            ).create(
                {
                    "person_id": former.id,
                    "member_id": holder.id,
                    "relationship": "spouse",
                    "special_condition": "none",
                    "start_date": today,
                }
            )

    def test_conversion_requires_specific_permission(self):
        former, _certificate, today = self._prepare_former_member(
            "Ex-Socio sin permiso Beneficiario",
            99820000500,
        )

        holder = self._create_member(
            "Titular permiso Ex-Socio",
            99820000600,
            join_date=today - relativedelta(years=8),
        )

        with self.assertRaisesRegex(
            AccessError,
            "No tiene permiso para convertir un Ex-Socio en Beneficiario",
        ):
            former.with_user(
                self.regular_user
            ).action_convert_former_member_to_beneficiary(
                self._conversion_values(holder, today)
            )

    def test_voided_only_history_does_not_qualify_as_former_member(self):
        today = fields.Date.context_today(self.Partner)

        person = self.Partner.create(
            {
                "name": "Persona solo historial voided",
                "company_type": "person",
                "is_company": False,
                "club_id_number": self._next_available_id_number(99820000700),
                "club_birthdate": self._birthdate_for_age(40),
            }
        )

        # Fixture técnico para comprobar que voided no equivale a Ex-Socio.
        # pylint: disable=protected-access
        period = self.Period._create_period_internal(
            {
                "person_id": person.id,
                "start_date": today - relativedelta(years=2),
                "origin": "initial",
                "member_code": person.club_id_number,
            }
        )
        period._void_period_internal("Alta errónea de prueba.")
        # pylint: enable=protected-access

        person.invalidate_recordset()

        self.assertFalse(person.club_is_former_member)

        holder = self._create_member(
            "Titular historial voided",
            99820000800,
            join_date=today - relativedelta(years=8),
        )

        with self.assertRaisesRegex(
            ValidationError,
            "no cumple la condición de Ex-Socio",
        ):
            person.action_convert_former_member_to_beneficiary(
                self._conversion_values(holder, today)
            )

    def test_company_former_member_cannot_convert(self):
        former, _certificate, today = self._prepare_former_member(
            "Empresa Ex-Socio a Beneficiario",
            99820000900,
            is_company=True,
        )

        holder = self._create_member(
            "Titular empresa Ex-Socio",
            99820001000,
            join_date=today - relativedelta(years=8),
        )

        with self.assertRaisesRegex(
            ValidationError,
            "persona individual",
        ):
            former.action_convert_former_member_to_beneficiary(
                self._conversion_values(holder, today)
            )

    def test_current_membership_period_blocks_conversion(self):
        former, _certificate, today = self._prepare_former_member(
            "Ex-Socio inconsistente current",
            99820001100,
        )

        # Fixture técnico de datos heredados inconsistentes:
        # finalized histórico + current sin rol member.
        # pylint: disable=protected-access
        self.Period._create_period_internal(
            {
                "person_id": former.id,
                "start_date": today,
                "origin": "reentry",
                "member_code": former.club_id_number,
            }
        )
        # pylint: enable=protected-access

        former.invalidate_recordset()

        holder = self._create_member(
            "Titular current inconsistente",
            99820001200,
            join_date=today - relativedelta(years=8),
        )

        with self.assertRaisesRegex(
            ValidationError,
            "período de membresía vigente",
        ):
            former.action_convert_former_member_to_beneficiary(
                self._conversion_values(holder, today)
            )

    def test_start_date_before_last_membership_end_is_blocked(self):
        former, _certificate, today = self._prepare_former_member(
            "Ex-Socio cronología Beneficiario",
            99820001300,
        )

        holder = self._create_member(
            "Titular cronología Ex-Socio",
            99820001400,
            join_date=today - relativedelta(years=8),
        )

        with self.assertRaisesRegex(
            ValidationError,
            "no puede ser anterior",
        ):
            former.action_convert_former_member_to_beneficiary(
                self._conversion_values(
                    holder,
                    today - relativedelta(days=1),
                )
            )

    def test_conversion_reuses_person_and_preserves_history(self):
        former, certificate, today = self._prepare_former_member(
            "Ex-Socio conversión correcta Beneficiario",
            99820001500,
            with_certificate=True,
        )

        holder = self._create_member(
            "Titular conversión correcta Ex-Socio",
            99820001600,
            join_date=today - relativedelta(years=8),
        )

        original_person_id = former.id
        original_id_number = former.club_id_number

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

        beneficiary_id = former.action_convert_former_member_to_beneficiary(
            self._conversion_values(
                holder,
                today,
                relationship="parent",
                observations="Conversión controlada de Ex-Socio.",
            )
        )

        former.invalidate_recordset()
        certificate.invalidate_recordset()

        beneficiary = self.Beneficiary.browse(beneficiary_id)
        beneficiary.invalidate_recordset()

        self.assertEqual(former.id, original_person_id)
        self.assertEqual(former.club_id_number, original_id_number)
        self.assertFalse(former.club_person_type)
        self.assertTrue(former.club_is_former_member)

        self.assertEqual(beneficiary.person_id, former)
        self.assertEqual(beneficiary.member_id, holder)
        self.assertEqual(beneficiary.relationship, "parent")
        self.assertEqual(beneficiary.start_date, today)
        self.assertEqual(beneficiary.state, "active")
        self.assertEqual(
            beneficiary.observations,
            "Conversión controlada de Ex-Socio.",
        )

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

        event = self.Kardex.search(
            [
                ("member_id", "=", holder.id),
                ("beneficiary_id", "=", beneficiary.id),
                ("event_type", "=", "beneficiary_created"),
            ],
            limit=1,
        )

        self.assertTrue(event)

    def test_current_beneficiary_link_blocks_second_conversion(self):
        former, _certificate, today = self._prepare_former_member(
            "Ex-Socio doble Beneficiario",
            99820001700,
        )

        first_holder = self._create_member(
            "Primer titular Ex-Socio",
            99820001800,
            join_date=today - relativedelta(years=8),
        )

        second_holder = self._create_member(
            "Segundo titular Ex-Socio",
            99820001900,
            join_date=today - relativedelta(years=8),
        )

        first_id = former.action_convert_former_member_to_beneficiary(
            self._conversion_values(first_holder, today)
        )

        with self.assertRaisesRegex(
            ValidationError,
            "ya posee un vínculo vigente",
        ):
            former.action_convert_former_member_to_beneficiary(
                self._conversion_values(second_holder, today)
            )

        current_links = self.Beneficiary.search(
            [
                ("person_id", "=", former.id),
                ("state", "in", ("active", "blocked")),
            ]
        )

        self.assertEqual(len(current_links), 1)
        self.assertEqual(current_links.id, first_id)

    def test_finalized_beneficiary_history_allows_new_conversion(self):
        former, _certificate, today = self._prepare_former_member(
            "Ex-Socio Beneficiario histórico",
            99820002000,
        )

        first_holder = self._create_member(
            "Titular histórico Ex-Socio",
            99820002100,
            join_date=today - relativedelta(years=8),
        )

        second_holder = self._create_member(
            "Nuevo titular Ex-Socio",
            99820002200,
            join_date=today - relativedelta(years=8),
        )

        first_id = former.action_convert_former_member_to_beneficiary(
            self._conversion_values(first_holder, today)
        )

        first_link = self.Beneficiary.browse(first_id)

        first_link.finalize_link(
            end_date=today,
            reason="Finalización del vínculo histórico de prueba.",
        )

        first_link.invalidate_recordset()

        historical_snapshot = (
            first_link.member_id.id,
            first_link.relationship,
            first_link.start_date,
            first_link.end_date,
            first_link.end_reason,
        )

        second_id = former.action_convert_former_member_to_beneficiary(
            self._conversion_values(
                second_holder,
                today,
                relationship="partner",
            )
        )

        first_link.invalidate_recordset()
        second_link = self.Beneficiary.browse(second_id)

        self.assertEqual(first_link.state, "finalized")
        self.assertEqual(
            (
                first_link.member_id.id,
                first_link.relationship,
                first_link.start_date,
                first_link.end_date,
                first_link.end_reason,
            ),
            historical_snapshot,
        )

        self.assertEqual(second_link.state, "active")
        self.assertEqual(second_link.person_id, former)
        self.assertEqual(second_link.member_id, second_holder)

    def test_failed_beneficiary_creation_leaves_no_partial_link(self):
        former, _certificate, today = self._prepare_former_member(
            "Ex-Socio rollback Beneficiario",
            99820002300,
        )

        individual_holder = self._create_member(
            "Titular individual para worker inválido",
            99820002400,
            join_date=today - relativedelta(years=8),
        )

        with self.assertRaisesRegex(
            ValidationError,
            "Trabajador",
        ):
            former.action_convert_former_member_to_beneficiary(
                self._conversion_values(
                    individual_holder,
                    today,
                    relationship="worker",
                )
            )

        former.invalidate_recordset()

        self.assertFalse(former.club_person_type)
        self.assertTrue(former.club_is_former_member)

        self.assertFalse(
            self.Beneficiary.search(
                [
                    ("person_id", "=", former.id),
                    ("state", "in", ("active", "blocked")),
                ],
                limit=1,
            )
        )
