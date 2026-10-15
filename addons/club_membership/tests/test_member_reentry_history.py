from dateutil.relativedelta import relativedelta
from odoo import fields
from odoo.exceptions import AccessError
from odoo.tests import tagged
from odoo.tests.common import TransactionCase


@tagged("post_install", "-at_install")
class TestMemberReentryHistory(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()

        admin = cls.env.ref("base.user_admin")

        cls.Partner = cls.env["res.partner"].with_user(admin)
        cls.Certificate = cls.env["club.certificate"].with_user(admin)
        cls.ReentryWizard = cls.env["club.member.reentry.wizard"].with_user(admin)

    def _prepare_former_member_with_history(self):
        today = fields.Date.context_today(self.Partner)

        number = 99730006000

        while self.Partner.search(
            [("club_id_number", "=", str(number))],
            limit=1,
        ):
            number += 1

        member = self.Partner.create(
            {
                "name": "Ex-Socio reingreso con historial patrimonial",
                "company_type": "person",
                "is_company": False,
                "club_person_type": "member",
                "club_id_number": str(number),
                "club_birthdate": fields.Date.to_string(
                    today - relativedelta(years=50)
                ),
                "club_join_date": today - relativedelta(years=5),
            }
        )

        eligible_certificate = self.Certificate.create(
            {
                "member_id": member.id,
                "registration_origin": "new",
                "total_value": 1000.0,
                "opening_balance": 1000.0,
            }
        )

        eligible_certificate.write(
            {
                "issue_date": today - relativedelta(years=2),
            }
        )

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

        self.assertEqual(len(member.club_certificate_ids), 2)

        self.assertEqual(
            member.club_certificate_ids[:1],
            historical_certificate,
            "El escenario debe situar primero al Transferido historico.",
        )

        member.action_end_club_membership(
            "Baja definitiva previa al Reingreso historico.",
            effective_date=today,
        )

        member.invalidate_recordset()
        eligible_certificate.invalidate_recordset()
        historical_certificate.invalidate_recordset()

        self.assertFalse(member.club_person_type)
        self.assertTrue(member.club_is_former_member)

        self.assertEqual(eligible_certificate.state, "passive")
        self.assertTrue(eligible_certificate.passive_by_membership_end)
        self.assertFalse(eligible_certificate.passive_by_member_withdrawal)

        self.assertEqual(historical_certificate.state, "transferred")
        self.assertFalse(historical_certificate.passive_by_membership_end)

        member.invalidate_recordset(["club_certificate_ids"])

        self.assertEqual(
            member.club_certificate_ids[:1],
            historical_certificate,
        )

        return (
            member,
            eligible_certificate,
            historical_certificate,
            today,
        )

    def test_reentry_wizard_selects_membership_end_certificate_among_history(
        self,
    ):
        member, eligible, historical, today = self._prepare_former_member_with_history()

        wizard = self.ReentryWizard.create(
            {
                "person_id": member.id,
                "effective_date": today,
                "reason": "Inspeccion de Reingreso con historial.",
            }
        )

        self.assertEqual(wizard.certificate_id, eligible)
        self.assertTrue(wizard.certificate_will_reactivate)

        self.assertEqual(eligible.state, "passive")
        self.assertTrue(eligible.passive_by_membership_end)
        self.assertEqual(historical.state, "transferred")

    def test_reentry_backend_restores_membership_end_certificate_among_history(
        self,
    ):
        member, eligible, historical, today = self._prepare_former_member_with_history()

        member.action_reenter_club_member(
            "Reingreso recuperando el Certificado causal.",
            effective_date=today,
        )

        member.invalidate_recordset()
        eligible.invalidate_recordset()
        historical.invalidate_recordset()

        self.assertEqual(member.club_person_type, "member")
        self.assertEqual(member.club_member_state, "active")

        self.assertEqual(eligible.state, "active")
        self.assertFalse(eligible.passive_by_membership_end)
        self.assertFalse(eligible.passive_by_member_withdrawal)

        self.assertEqual(historical.state, "transferred")
        self.assertFalse(historical.passive_by_membership_end)
        self.assertFalse(historical.passive_by_member_withdrawal)

    def test_reentry_remains_valid_after_rejected_forged_marker(self):
        member, eligible, historical, today = self._prepare_former_member_with_history()

        original_certificate_ids = set(member.club_certificate_ids.ids)

        # No se permite fabricar otra marca causal durante create().
        with self.env.cr.savepoint(), self.assertRaises(AccessError):
            self.Certificate.create(
                {
                    "member_id": member.id,
                    "registration_origin": "new",
                    "total_value": 1000.0,
                    "opening_balance": 1000.0,
                    "state": "passive",
                    "passive_by_membership_end": True,
                }
            )

        # Tampoco se permite marcar un historico por write().
        with self.env.cr.savepoint(), self.assertRaises(AccessError):
            historical.write(
                {
                    "passive_by_membership_end": True,
                }
            )

        member.invalidate_recordset(["club_certificate_ids"])
        eligible.invalidate_recordset()
        historical.invalidate_recordset()

        self.assertEqual(
            set(member.club_certificate_ids.ids),
            original_certificate_ids,
        )

        self.assertEqual(eligible.state, "passive")
        self.assertTrue(eligible.passive_by_membership_end)

        self.assertEqual(historical.state, "transferred")
        self.assertFalse(historical.passive_by_membership_end)

        # Los intentos rechazados no deben impedir el Reingreso legitimo.
        member.action_reenter_club_member(
            "Reingreso despues de intentos de falsificacion rechazados.",
            effective_date=today,
        )

        member.invalidate_recordset()
        eligible.invalidate_recordset()
        historical.invalidate_recordset()

        self.assertEqual(member.club_person_type, "member")
        self.assertEqual(member.club_member_state, "active")

        self.assertEqual(eligible.state, "active")
        self.assertFalse(eligible.passive_by_membership_end)

        self.assertEqual(historical.state, "transferred")
        self.assertFalse(historical.passive_by_membership_end)

        member.invalidate_recordset(["club_certificate_ids"])

        self.assertEqual(
            set(member.club_certificate_ids.ids),
            original_certificate_ids,
        )
