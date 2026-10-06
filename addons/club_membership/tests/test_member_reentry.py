from dateutil.relativedelta import relativedelta
from odoo import fields
from odoo.exceptions import AccessError, ValidationError
from odoo.tests import tagged
from odoo.tests.common import TransactionCase, new_test_user


@tagged("post_install", "-at_install")
class TestMemberReentry(TransactionCase):
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
            login="club_member_reentry_without_permission",
            groups="base.group_user",
            name="Usuario sin permiso de Reingreso",
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
            "Baja definitiva previa al Reingreso.",
            effective_date=today,
        )

        member.invalidate_recordset()

        if certificate:
            certificate.invalidate_recordset()

        return member, certificate, today

    def test_former_member_can_reenter_on_same_day(self):
        member, _certificate, today = self._prepare_former_member(
            "Ex-Socio Reingreso mismo día",
            99700000100,
        )

        periods_before = self.Period.search(
            [("person_id", "=", member.id)],
            order="id",
        )

        self.assertEqual(len(periods_before), 1)
        self.assertEqual(periods_before.state, "finalized")
        self.assertTrue(member.club_is_former_member)

        member.action_reenter_club_member(
            "Reingreso autorizado el mismo día.",
            effective_date=today,
        )

        member.invalidate_recordset()

        periods = self.Period.search(
            [("person_id", "=", member.id)],
            order="id",
        )

        self.assertEqual(len(periods), 2)

        old_period = periods[0]
        new_period = periods[1]

        self.assertEqual(old_period.state, "finalized")
        self.assertEqual(old_period.end_date, today)

        self.assertEqual(new_period.state, "current")
        self.assertEqual(new_period.origin, "reentry")
        self.assertEqual(new_period.start_date, today)
        self.assertEqual(new_period.member_code, member.club_member_code)

        self.assertEqual(member.club_person_type, "member")
        self.assertEqual(member.club_member_code, member.club_id_number)
        self.assertEqual(member.club_join_date, today)
        self.assertEqual(member.club_member_state, "active")
        self.assertEqual(member.club_legal_state, "regular")
        self.assertFalse(member.club_is_former_member)

    def test_reentry_before_last_membership_end_is_rejected(self):
        member, _certificate, today = self._prepare_former_member(
            "Ex-Socio Reingreso fecha inválida",
            99700000200,
        )

        with self.assertRaises(ValidationError):
            member.action_reenter_club_member(
                "Intento anterior al último cierre.",
                effective_date=today - relativedelta(days=1),
            )

        member.invalidate_recordset()

        periods = self.Period.search(
            [("person_id", "=", member.id)],
        )

        self.assertEqual(len(periods), 1)
        self.assertEqual(periods.state, "finalized")
        self.assertFalse(member.club_person_type)
        self.assertTrue(member.club_is_former_member)

    def test_reentry_requires_specific_permission(self):
        member, _certificate, today = self._prepare_former_member(
            "Ex-Socio Reingreso sin permiso",
            99700000300,
        )

        with self.assertRaises(AccessError):
            member.with_user(self.regular_user).action_reenter_club_member(
                "Intento sin permiso específico.",
                effective_date=today,
            )

    def test_current_beneficiary_link_blocks_reentry(self):
        member, _certificate, today = self._prepare_former_member(
            "Ex-Socio Beneficiario vigente",
            99700000400,
        )

        holder = self._create_member(
            "Socio titular del Ex-Socio Beneficiario",
            99700000500,
            join_date=today - relativedelta(years=4),
        )

        self.Beneficiary.create(
            {
                "person_id": member.id,
                "member_id": holder.id,
                "relationship": "spouse",
                "special_condition": "none",
            }
        )

        with self.assertRaises(ValidationError):
            member.action_reenter_club_member(
                "Intento con vínculo vigente como Beneficiario.",
                effective_date=today,
            )

        member.invalidate_recordset()

        self.assertFalse(member.club_person_type)
        self.assertTrue(member.club_is_former_member)

    def test_membership_end_certificate_is_reactivated_by_reentry(self):
        member, certificate, today = self._prepare_former_member(
            "Ex-Socio Reingreso Certificado",
            99700000600,
            with_certificate=True,
        )

        self.assertEqual(certificate.state, "passive")
        self.assertTrue(certificate.passive_by_membership_end)

        member.action_reenter_club_member(
            "Reingreso con recuperación causal del Certificado.",
            effective_date=today,
        )

        certificate.invalidate_recordset()

        self.assertEqual(certificate.state, "active")
        self.assertFalse(certificate.passive_by_membership_end)

    def test_reentry_logs_specific_event_without_second_member_created(self):
        member, _certificate, today = self._prepare_former_member(
            "Ex-Socio Kardex de Reingreso",
            99700000700,
        )

        initial_created_count = self.Kardex.search_count(
            [
                ("member_id", "=", member.id),
                ("event_type", "=", "member_created"),
            ]
        )

        self.assertEqual(initial_created_count, 1)

        member.action_reenter_club_member(
            "Reingreso con Kardex específico.",
            effective_date=today,
        )

        created_count = self.Kardex.search_count(
            [
                ("member_id", "=", member.id),
                ("event_type", "=", "member_created"),
            ]
        )

        reentry_events = self.Kardex.search(
            [
                ("member_id", "=", member.id),
                ("event_type", "=", "membership_reentered"),
            ]
        )

        self.assertEqual(created_count, 1)
        self.assertEqual(len(reentry_events), 1)
        self.assertIn(
            "Reingreso con Kardex específico.",
            reentry_events.reason or "",
        )

    def test_direct_write_cannot_reenter_former_member(self):
        member, _certificate, _today = self._prepare_former_member(
            "Ex-Socio protección write directo",
            99700000800,
        )

        with self.assertRaises(ValidationError):
            member.write(
                {
                    "club_person_type": "member",
                }
            )

        member.invalidate_recordset()

        self.assertFalse(member.club_person_type)
        self.assertTrue(member.club_is_former_member)

    def test_reentry_requires_reason(self):
        member, _certificate, today = self._prepare_former_member(
            "Ex-Socio Reingreso sin motivo",
            99700000900,
        )

        with self.assertRaises(ValidationError):
            member.action_reenter_club_member(
                "   ",
                effective_date=today,
            )

        member.invalidate_recordset()

        self.assertFalse(member.club_person_type)
        self.assertTrue(member.club_is_former_member)

    def test_reentry_requires_effective_date(self):
        member, _certificate, _today = self._prepare_former_member(
            "Ex-Socio Reingreso sin fecha",
            99700001000,
        )

        with self.assertRaises(ValidationError):
            member.action_reenter_club_member(
                "Intento sin fecha efectiva.",
            )

        member.invalidate_recordset()

        self.assertFalse(member.club_person_type)
        self.assertTrue(member.club_is_former_member)

    def test_reentry_rejects_future_date(self):
        member, _certificate, today = self._prepare_former_member(
            "Ex-Socio Reingreso fecha futura",
            99700001100,
        )

        with self.assertRaises(ValidationError):
            member.action_reenter_club_member(
                "Intento con fecha futura.",
                effective_date=today + relativedelta(days=1),
            )

        member.invalidate_recordset()

        self.assertFalse(member.club_person_type)
        self.assertTrue(member.club_is_former_member)

    def test_former_member_with_current_client_role_cannot_use_reentry(self):
        member, _certificate, today = self._prepare_former_member(
            "Ex-Socio actualmente Cliente",
            99700001200,
        )

        member.write(
            {
                "club_person_type": "client",
            }
        )

        member.invalidate_recordset()

        self.assertEqual(member.club_person_type, "client")
        self.assertTrue(member.club_is_former_member)

        with self.assertRaises(ValidationError):
            member.action_reenter_club_member(
                "Intento de Reingreso desde rol Cliente.",
                effective_date=today,
            )

        member.invalidate_recordset()

        self.assertEqual(member.club_person_type, "client")
        self.assertTrue(member.club_is_former_member)

    def test_independently_passive_certificate_is_preserved_on_reentry(self):
        today = fields.Date.context_today(self.Partner)

        member = self._create_member(
            "Ex-Socio Certificado Pasivo independiente",
            99700001300,
            join_date=today - relativedelta(years=5),
        )

        certificate = self._create_certificate(member)

        certificate.write(
            {
                "state": "passive",
            }
        )

        member.action_end_club_membership(
            "Baja definitiva con Certificado Pasivo independiente.",
            effective_date=today,
        )

        member.invalidate_recordset()
        certificate.invalidate_recordset()

        self.assertEqual(certificate.state, "passive")
        self.assertFalse(certificate.passive_by_membership_end)

        member.action_reenter_club_member(
            "Reingreso preservando Certificado Pasivo independiente.",
            effective_date=today,
        )

        certificate.invalidate_recordset()

        self.assertEqual(certificate.state, "passive")
        self.assertFalse(certificate.passive_by_membership_end)

    def test_transferred_certificate_is_preserved_on_reentry(self):
        today = fields.Date.context_today(self.Partner)

        member = self._create_member(
            "Ex-Socio Certificado Transferido",
            99700001400,
            join_date=today - relativedelta(years=5),
        )

        certificate = self._create_certificate(member)

        certificate.write(
            {
                "state": "transferred",
            }
        )

        member.action_end_club_membership(
            "Baja definitiva con Certificado Transferido.",
            effective_date=today,
        )

        member.invalidate_recordset()
        certificate.invalidate_recordset()

        self.assertEqual(certificate.state, "transferred")
        self.assertFalse(certificate.passive_by_membership_end)

        member.action_reenter_club_member(
            "Reingreso preservando Certificado Transferido.",
            effective_date=today,
        )

        certificate.invalidate_recordset()

        self.assertEqual(certificate.state, "transferred")
        self.assertFalse(certificate.passive_by_membership_end)

    def test_fake_reentry_context_token_cannot_bypass_direct_write(self):
        member, _certificate, _today = self._prepare_former_member(
            "Ex-Socio token falso de Reingreso",
            99700001500,
        )

        with self.assertRaises(ValidationError):
            member.with_context(
                club_member_reentry_internal_token=True,
            ).write(
                {
                    "club_person_type": "member",
                }
            )

        member.invalidate_recordset()

        self.assertFalse(member.club_person_type)
        self.assertTrue(member.club_is_former_member)

    def test_reentry_historical_effective_date_is_preserved(self):
        today = fields.Date.context_today(self.Partner)
        effective_date = today - relativedelta(days=1)

        member = self._create_member(
            "Ex-Socio Reingreso fecha histórica",
            99700001600,
            join_date=today - relativedelta(years=5),
        )

        member.action_end_club_membership(
            "Baja definitiva histórica previa al Reingreso.",
            effective_date=effective_date,
        )

        member.invalidate_recordset()

        self.assertTrue(member.club_is_former_member)
        self.assertFalse(member.club_person_type)

        member.action_reenter_club_member(
            "Reingreso histórico el mismo día de la baja.",
            effective_date=effective_date,
        )

        member.invalidate_recordset()

        periods = self.Period.search(
            [
                ("person_id", "=", member.id),
            ],
            order="id",
        )

        self.assertEqual(len(periods), 2)

        old_period = periods[0]
        new_period = periods[1]

        self.assertEqual(old_period.state, "finalized")
        self.assertEqual(old_period.end_date, effective_date)

        self.assertEqual(new_period.state, "current")
        self.assertEqual(new_period.origin, "reentry")
        self.assertEqual(new_period.start_date, effective_date)

        self.assertEqual(member.club_person_type, "member")
        self.assertEqual(member.club_member_code, member.club_id_number)
        self.assertEqual(member.club_join_date, effective_date)
        self.assertEqual(member.club_member_state, "active")
        self.assertEqual(member.club_legal_state, "regular")

        reentry_event = self.Kardex.search(
            [
                ("member_id", "=", member.id),
                ("event_type", "=", "membership_reentered"),
            ],
            order="id desc",
            limit=1,
        )

        self.assertTrue(reentry_event)
        self.assertIn(
            fields.Date.to_string(effective_date),
            reentry_event.reason or "",
        )
