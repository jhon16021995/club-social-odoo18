from dateutil.relativedelta import relativedelta
from odoo import fields
from odoo.exceptions import AccessError
from odoo.tests import tagged
from odoo.tests.common import TransactionCase


@tagged("post_install", "-at_install")
class TestMemberReactivationHistory(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()

        admin = cls.env.ref("base.user_admin")

        cls.Partner = cls.env["res.partner"].with_user(admin)
        cls.Certificate = cls.env["club.certificate"].with_user(admin)
        cls.ReactivationWizard = cls.env["club.member.reactivation.wizard"].with_user(
            admin
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
    def _create_member(cls, name, start_number, *, join_date=False):
        today = fields.Date.context_today(cls.Partner)

        vals = {
            "name": name,
            "company_type": "person",
            "is_company": False,
            "club_person_type": "member",
            "club_id_number": cls._next_available_id_number(start_number),
            "club_birthdate": fields.Date.to_string(today - relativedelta(years=50)),
            "club_member_state": "active",
            "club_ordinary_contributions_historical_paid": 0,
        }

        if join_date:
            vals["club_join_date"] = join_date

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

    def test_reactivation_selects_withdrawal_certificate_among_historical(self):
        today = fields.Date.context_today(self.Partner)

        member = self._create_member(
            "Socio REA con certificados historicos",
            99510003000,
            join_date=today - relativedelta(years=5),
        )

        eligible_certificate = self._create_certificate(member)

        eligible_certificate.write(
            {
                "issue_date": today - relativedelta(years=2),
            }
        )

        member.action_withdraw_club_member(
            "Retiro previo al escenario de REA historico",
            effective_date=today,
        )

        eligible_certificate.invalidate_recordset()

        self.assertEqual(eligible_certificate.state, "passive")
        self.assertTrue(eligible_certificate.passive_by_member_withdrawal)

        historical_certificate = self.Certificate.create(
            {
                "member_id": member.id,
                "registration_origin": "new",
                "total_value": 1000.0,
                "opening_balance": 1000.0,
                "state": "transferred",
                "issue_date": today,
            }
        )

        member.invalidate_recordset(["club_certificate_ids"])

        self.assertEqual(
            len(member.club_certificate_ids),
            2,
        )

        self.assertEqual(
            member.club_certificate_ids[:1],
            historical_certificate,
            "El escenario no coloca primero al Certificado historico.",
        )

        wizard = self.ReactivationWizard.create(
            {
                "member_id": member.id,
                "effective_date": today,
                "reason": "REA con varios certificados historicos",
            }
        )

        self.assertEqual(
            wizard.certificate_id,
            eligible_certificate,
        )

        self.assertTrue(wizard.certificate_will_reactivate)

        member.action_reactivate_club_member(
            "REA con varios certificados historicos",
            effective_date=today,
        )

        member.invalidate_recordset()
        eligible_certificate.invalidate_recordset()
        historical_certificate.invalidate_recordset()

        self.assertEqual(member.club_member_state, "active")
        self.assertEqual(eligible_certificate.state, "active")
        self.assertFalse(eligible_certificate.passive_by_member_withdrawal)

        self.assertEqual(historical_certificate.state, "transferred")
        self.assertFalse(historical_certificate.passive_by_member_withdrawal)

    def test_reactivation_remains_valid_after_rejected_forged_marker(self):
        today = fields.Date.context_today(self.Partner)

        member = self._create_member(
            "Socio REA con intento de marca falsificada",
            99510003100,
            join_date=today - relativedelta(years=5),
        )

        original_certificate = self._create_certificate(member)

        member.action_withdraw_club_member(
            "Retiro previo a intento de marca falsificada",
            effective_date=today,
        )

        original_certificate.invalidate_recordset()

        self.assertEqual(member.club_member_state, "inactive")
        self.assertEqual(original_certificate.state, "passive")
        self.assertTrue(original_certificate.passive_by_member_withdrawal)

        with self.env.cr.savepoint(), self.assertRaises(AccessError):
            self.Certificate.create(
                {
                    "member_id": member.id,
                    "registration_origin": "new",
                    "total_value": 1000.0,
                    "opening_balance": 1000.0,
                    "state": "passive",
                    "passive_by_member_withdrawal": True,
                    "issue_date": today,
                }
            )

        member.invalidate_recordset(["club_certificate_ids"])

        self.assertEqual(
            len(member.club_certificate_ids),
            1,
        )

        self.assertEqual(
            member.club_certificate_ids,
            original_certificate,
        )

        wizard = self.ReactivationWizard.create(
            {
                "member_id": member.id,
                "effective_date": today,
                "reason": "REA tras intento de marca falsificada",
            }
        )

        self.assertEqual(
            wizard.certificate_id,
            original_certificate,
        )

        self.assertTrue(wizard.certificate_will_reactivate)

        member.action_reactivate_club_member(
            "REA tras intento de marca falsificada",
            effective_date=today,
        )

        member.invalidate_recordset()
        original_certificate.invalidate_recordset()

        self.assertEqual(member.club_member_state, "active")
        self.assertEqual(original_certificate.state, "active")
        self.assertFalse(original_certificate.passive_by_member_withdrawal)

        self.assertEqual(
            len(member.club_certificate_ids),
            1,
        )
