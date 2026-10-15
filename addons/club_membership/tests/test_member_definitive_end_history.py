from dateutil.relativedelta import relativedelta
from odoo import fields
from odoo.exceptions import ValidationError
from odoo.tests import tagged
from odoo.tests.common import TransactionCase


@tagged("post_install", "-at_install")
class TestMemberDefinitiveEndHistory(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()

        admin = cls.env.ref("base.user_admin")

        cls.Partner = cls.env["res.partner"].with_user(admin)
        cls.Certificate = cls.env["club.certificate"].with_user(admin)
        cls.EndWizard = cls.env["club.membership.end.wizard"].with_user(admin)

    @classmethod
    def _next_available_id_number(cls, start):
        number = start

        while cls.Partner.search(
            [("club_id_number", "=", str(number))],
            limit=1,
        ):
            number += 1

        return str(number)

    def _prepare_history(self, *, withdrawn):
        today = fields.Date.context_today(self.Partner)

        member = self.Partner.create(
            {
                "name": (
                    "Socio baja historica RET"
                    if withdrawn
                    else "Socio baja historica activo"
                ),
                "company_type": "person",
                "is_company": False,
                "club_person_type": "member",
                "club_id_number": self._next_available_id_number(
                    99730005000 if withdrawn else 99730005100
                ),
                "club_birthdate": fields.Date.to_string(
                    today - relativedelta(years=50)
                ),
                "club_join_date": today - relativedelta(years=5),
                "club_member_state": "active",
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

        if withdrawn:
            member.action_withdraw_club_member(
                "Retiro previo a baja definitiva historica",
                effective_date=today,
            )

            eligible_certificate.invalidate_recordset()

            self.assertEqual(eligible_certificate.state, "passive")
            self.assertTrue(eligible_certificate.passive_by_member_withdrawal)
        else:
            self.assertEqual(eligible_certificate.state, "active")

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
            "El escenario debe colocar primero al Transferido historico.",
        )

        return (
            member,
            eligible_certificate,
            historical_certificate,
            today,
        )

    def test_active_history_wizard_selects_active_certificate(self):
        member, eligible, historical, today = self._prepare_history(
            withdrawn=False,
        )

        wizard = self.EndWizard.create(
            {
                "member_id": member.id,
                "effective_date": today,
                "reason": "Inspeccion de baja definitiva historica",
            }
        )

        self.assertEqual(wizard.certificate_id, eligible)
        self.assertEqual(wizard.certificate_state, "active")
        self.assertEqual(historical.state, "transferred")

    def test_active_history_backend_passivizes_active_certificate(self):
        member, eligible, historical, today = self._prepare_history(
            withdrawn=False,
        )

        member.action_end_club_membership(
            "Baja definitiva con Certificado activo historico",
            effective_date=today,
        )

        member.invalidate_recordset()
        eligible.invalidate_recordset()
        historical.invalidate_recordset()

        self.assertFalse(member.club_person_type)
        self.assertFalse(member.club_member_state)

        self.assertEqual(eligible.state, "passive")
        self.assertFalse(eligible.passive_by_member_withdrawal)
        self.assertTrue(eligible.passive_by_membership_end)

        self.assertEqual(historical.state, "transferred")
        self.assertFalse(historical.passive_by_member_withdrawal)
        self.assertFalse(historical.passive_by_membership_end)

    def test_withdrawal_history_wizard_selects_ret_certificate(self):
        member, eligible, historical, today = self._prepare_history(
            withdrawn=True,
        )

        wizard = self.EndWizard.create(
            {
                "member_id": member.id,
                "effective_date": today,
                "reason": "Inspeccion de baja definitiva posterior a RET",
            }
        )

        self.assertEqual(wizard.certificate_id, eligible)
        self.assertEqual(wizard.certificate_state, "passive")
        self.assertEqual(historical.state, "transferred")

    def test_withdrawal_history_backend_absorbs_ret_certificate(self):
        member, eligible, historical, today = self._prepare_history(
            withdrawn=True,
        )

        member.action_end_club_membership(
            "Baja definitiva posterior a RET con historial",
            effective_date=today,
        )

        member.invalidate_recordset()
        eligible.invalidate_recordset()
        historical.invalidate_recordset()

        self.assertFalse(member.club_person_type)
        self.assertFalse(member.club_member_state)

        self.assertEqual(eligible.state, "passive")
        self.assertFalse(eligible.passive_by_member_withdrawal)
        self.assertTrue(eligible.passive_by_membership_end)

        self.assertEqual(historical.state, "transferred")
        self.assertFalse(historical.passive_by_member_withdrawal)
        self.assertFalse(historical.passive_by_membership_end)

    def _prepare_ambiguous_candidates(self):
        member, ret_certificate, historical, today = self._prepare_history(
            withdrawn=True
        )

        active_certificate = self.Certificate.create(
            {
                "member_id": member.id,
                "registration_origin": "new",
                "total_value": 1000.0,
                "opening_balance": 1000.0,
                "state": "active",
                "issue_date": today,
            }
        )

        member.invalidate_recordset(["club_certificate_ids"])

        candidates = member.club_certificate_ids.filtered(
            lambda cert: (
                cert.state == "active"
                or (cert.state == "passive" and cert.passive_by_member_withdrawal)
            )
        )

        self.assertEqual(len(member.club_certificate_ids), 3)
        self.assertEqual(len(candidates), 2)
        self.assertEqual(
            set(candidates.ids),
            {ret_certificate.id, active_certificate.id},
        )

        self.assertEqual(member.club_member_state, "inactive")
        self.assertEqual(historical.state, "transferred")

        return member, ret_certificate, historical, active_certificate, today

    def test_ambiguous_candidates_wizard_rejects(self):
        member, ret_certificate, historical, active, today = (
            self._prepare_ambiguous_candidates()
        )

        with (
            self.env.cr.savepoint(),
            self.assertRaisesRegex(
                ValidationError,
                "Existen varios Certificados Patrimoniales elegibles",
            ),
        ):
            wizard = self.EndWizard.create(
                {
                    "member_id": member.id,
                    "effective_date": today,
                    "reason": "Prueba de ambiguedad del wizard",
                }
            )
            _ = wizard.certificate_id

        member.invalidate_recordset()
        ret_certificate.invalidate_recordset()
        historical.invalidate_recordset()
        active.invalidate_recordset()

        self.assertEqual(member.club_person_type, "member")
        self.assertEqual(member.club_member_state, "inactive")
        self.assertEqual(ret_certificate.state, "passive")
        self.assertTrue(ret_certificate.passive_by_member_withdrawal)
        self.assertFalse(ret_certificate.passive_by_membership_end)
        self.assertEqual(active.state, "active")
        self.assertEqual(historical.state, "transferred")

    def test_ambiguous_candidates_backend_rejects(self):
        member, ret_certificate, historical, active, today = (
            self._prepare_ambiguous_candidates()
        )

        with (
            self.env.cr.savepoint(),
            self.assertRaisesRegex(
                ValidationError,
                "Existen varios Certificados Patrimoniales elegibles",
            ),
        ):
            member.action_end_club_membership(
                "Baja definitiva con historial ambiguo",
                effective_date=today,
            )

        member.invalidate_recordset()
        ret_certificate.invalidate_recordset()
        historical.invalidate_recordset()
        active.invalidate_recordset()

        self.assertEqual(member.club_person_type, "member")
        self.assertEqual(member.club_member_state, "inactive")
        self.assertEqual(ret_certificate.state, "passive")
        self.assertTrue(ret_certificate.passive_by_member_withdrawal)
        self.assertFalse(ret_certificate.passive_by_membership_end)
        self.assertEqual(active.state, "active")
        self.assertEqual(historical.state, "transferred")

        current_periods = self.env["club.membership.period"].search(
            [
                ("person_id", "=", member.id),
                ("state", "=", "current"),
            ]
        )
        self.assertEqual(len(current_periods), 1)

    def test_cau05_ambiguous_active_and_residual_withdrawal_certificate_blocks_end(
        self,
    ):
        """CAU-05: dos certificados elegibles no deben causar una baja parcial.

        El segundo certificado pasivo con marca RET es un dato legado
        deliberadamente contradictorio. La marca se crea SOLO como fixture
        SQL dentro de esta prueba, nunca como procedimiento institucional.
        """
        from odoo.exceptions import ValidationError

        member, active, historical, today = self._prepare_history(
            withdrawn=False,
        )
        self.assertEqual(active.state, "active")
        self.assertEqual(historical.state, "transferred")

        residual = self.Certificate.create(
            {
                "member_id": member.id,
                "registration_origin": "new",
                "total_value": 1000.0,
                "opening_balance": 1000.0,
                "state": "passive",
                "issue_date": today,
            }
        )
        self.assertEqual(residual.state, "passive")
        self.assertFalse(residual.passive_by_member_withdrawal)

        # Solo preparar dato legado para la prueba, SIN abrir write publico.
        self.env.cr.execute(
            "UPDATE club_certificate "
            "SET passive_by_member_withdrawal = %s WHERE id = %s",
            (True, residual.id),
        )
        residual.invalidate_recordset(["passive_by_member_withdrawal"])
        self.assertTrue(residual.passive_by_member_withdrawal)

        periods = self.env["club.membership.period"].search(
            [
                ("person_id", "=", member.id),
            ],
            order="id",
        )
        original_periods = [(p.id, p.state, p.start_date, p.end_date) for p in periods]
        self.assertEqual(
            sum(p.state == "current" for p in periods),
            1,
        )
        member.invalidate_recordset(["club_certificate_ids"])
        original_certificate_ids = set(member.club_certificate_ids.ids)
        self.assertEqual(len(original_certificate_ids), 3)

        # El backend ya tiene una guarda len(eligible_certificates) > 1.
        with (
            self.env.cr.savepoint(),
            self.assertRaisesRegex(
                ValidationError,
                "varios Certificados Patrimoniales elegibles",
            ),
        ):
            member.action_end_club_membership(
                "Intento CAU-05 con marcador RET residual",
                effective_date=today,
            )

        member.invalidate_recordset()
        active.invalidate_recordset()
        residual.invalidate_recordset()
        historical.invalidate_recordset()
        periods.invalidate_recordset()

        self.assertEqual(member.club_person_type, "member")
        self.assertEqual(member.club_member_state, "active")
        self.assertEqual(active.state, "active")
        self.assertFalse(active.passive_by_membership_end)
        self.assertEqual(residual.state, "passive")
        self.assertTrue(residual.passive_by_member_withdrawal)
        self.assertFalse(residual.passive_by_membership_end)
        self.assertEqual(historical.state, "transferred")
        self.assertFalse(historical.passive_by_membership_end)
        self.assertEqual(
            [(p.id, p.state, p.start_date, p.end_date) for p in periods],
            original_periods,
        )
        member.invalidate_recordset(["club_certificate_ids"])
        self.assertEqual(
            set(member.club_certificate_ids.ids),
            original_certificate_ids,
        )
