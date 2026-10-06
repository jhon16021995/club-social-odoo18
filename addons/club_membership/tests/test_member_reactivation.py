from dateutil.relativedelta import relativedelta
from odoo import fields
from odoo.exceptions import AccessError, ValidationError
from odoo.tests import tagged
from odoo.tests.common import TransactionCase, new_test_user


@tagged("post_install", "-at_install")
class TestMemberReactivation(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()

        cls.admin = cls.env.ref("base.user_admin")

        cls.Partner = cls.env["res.partner"].with_user(cls.admin)
        cls.Certificate = cls.env["club.certificate"].with_user(cls.admin)
        cls.Beneficiary = cls.env["club.beneficiary"].with_user(cls.admin)
        cls.Kardex = cls.env["club.kardex.event"].with_user(cls.admin)
        cls.Period = cls.env["club.membership.period"].with_user(cls.admin)
        cls.ReactivationWizard = cls.env["club.member.reactivation.wizard"].with_user(
            cls.admin
        )
        cls.WithdrawalWizard = cls.env["club.member.withdrawal.wizard"].with_user(
            cls.admin
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
        state="active",
        join_date=False,
    ):
        vals = {
            "name": name,
            "company_type": "person",
            "is_company": False,
            "club_person_type": "member",
            "club_id_number": cls._next_available_id_number(start_number),
            "club_birthdate": cls._birthdate_for_age(50),
            "club_member_state": state,
        }

        if join_date:
            vals["club_join_date"] = join_date

        return cls.Partner.create(vals)

    @classmethod
    def _create_person(cls, name, start_number):
        return cls.Partner.create(
            {
                "name": name,
                "company_type": "person",
                "is_company": False,
                "club_id_number": cls._next_available_id_number(start_number),
                "club_birthdate": cls._birthdate_for_age(30),
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

    @classmethod
    def _create_beneficiary(
        cls,
        member,
        person,
        *,
        relationship="spouse",
        start_date=False,
    ):
        vals = {
            "person_id": person.id,
            "member_id": member.id,
            "relationship": relationship,
            "special_condition": "none",
        }

        if start_date:
            vals["start_date"] = start_date

        return cls.Beneficiary.create(vals)

    def _assert_single_current_membership_period(self, member):
        periods = self.Period.search(
            [
                ("person_id", "=", member.id),
            ]
        )

        self.assertEqual(len(periods), 1)
        self.assertEqual(periods.state, "current")
        self.assertFalse(periods.end_date)

    def test_reactivation_restores_previous_state_and_related_records(self):
        today = fields.Date.context_today(self.Partner)

        member = self._create_member(
            "Socio REA restauración",
            99510000100,
            state="lifetime",
            join_date=today - relativedelta(years=10),
        )

        self._assert_single_current_membership_period(member)

        original_id_number = member.club_id_number
        original_member_code = member.club_member_code
        original_join_date = member.club_join_date

        certificate = self._create_certificate(member)

        eligible_beneficiary = self._create_beneficiary(
            member,
            self._create_person(
                "Beneficiario REA elegible",
                99510000200,
            ),
            start_date=today - relativedelta(years=1),
        )

        independent_blocked = self._create_beneficiary(
            member,
            self._create_person(
                "Beneficiario REA independiente",
                99510000300,
            ),
            relationship="parent",
            start_date=today - relativedelta(years=1),
        )

        independent_blocked.write(
            {
                "state": "blocked",
                "block_reason": "Bloqueo independiente",
            }
        )
        independent_reason = independent_blocked.block_reason

        member.action_withdraw_club_member(
            "Retiro previo a REA",
            effective_date=today,
        )

        self._assert_single_current_membership_period(member)

        member.invalidate_recordset()
        certificate.invalidate_recordset()
        eligible_beneficiary.invalidate_recordset()
        independent_blocked.invalidate_recordset()

        self.assertEqual(member.club_member_state, "inactive")
        self.assertEqual(
            member.club_state_before_withdrawal,
            "lifetime",
        )
        self.assertEqual(
            member.club_last_withdrawal_cause,
            "voluntary",
        )

        self.assertEqual(certificate.state, "passive")
        self.assertTrue(certificate.passive_by_member_withdrawal)

        self.assertEqual(eligible_beneficiary.state, "blocked")
        self.assertTrue(eligible_beneficiary.blocked_by_member_withdrawal)

        self.assertEqual(independent_blocked.state, "blocked")
        self.assertFalse(independent_blocked.blocked_by_member_withdrawal)

        member.action_reactivate_club_member(
            "Reactivación controlada",
            effective_date=today,
        )

        self._assert_single_current_membership_period(member)

        member.invalidate_recordset()
        certificate.invalidate_recordset()
        eligible_beneficiary.invalidate_recordset()
        independent_blocked.invalidate_recordset()

        self.assertEqual(member.club_member_state, "lifetime")
        self.assertFalse(member.club_state_before_withdrawal)
        self.assertEqual(
            member.club_last_reactivation_date,
            today,
        )

        self.assertEqual(
            member.club_id_number,
            original_id_number,
        )
        self.assertEqual(
            member.club_member_code,
            original_member_code,
        )
        self.assertEqual(
            member.club_join_date,
            original_join_date,
        )

        self.assertEqual(certificate.state, "active")
        self.assertFalse(certificate.passive_by_member_withdrawal)

        self.assertEqual(eligible_beneficiary.state, "active")
        self.assertFalse(eligible_beneficiary.blocked_by_member_withdrawal)

        self.assertEqual(independent_blocked.state, "blocked")
        self.assertEqual(
            independent_blocked.block_reason,
            independent_reason,
        )

    def test_death_withdrawal_can_be_corrected_by_reactivation(self):
        today = fields.Date.context_today(self.Partner)

        member = self._create_member(
            "Socio REA fallecimiento",
            99510000400,
            state="lifetime",
            join_date=today - relativedelta(years=12),
        )

        withdrawal_wizard = self.WithdrawalWizard.create(
            {
                "member_id": member.id,
                "withdrawal_cause": "death",
                "effective_date": today,
                "reason": "Registro de fallecimiento para prueba",
            }
        )

        withdrawal_wizard.action_confirm()

        member.invalidate_recordset()

        self.assertEqual(member.club_member_state, "inactive")
        self.assertEqual(
            member.club_state_before_withdrawal,
            "lifetime",
        )
        self.assertEqual(
            member.club_last_withdrawal_cause,
            "death",
        )

        withdrawal_event = self.Kardex.search(
            [
                ("member_id", "=", member.id),
                ("event_type", "=", "member_state_changed"),
            ],
            order="id desc",
            limit=1,
        )

        self.assertTrue(withdrawal_event)
        self.assertIn(
            "Fallecimiento",
            withdrawal_event.reason or "",
        )
        self.assertIn(
            "Registro de fallecimiento para prueba",
            withdrawal_event.reason or "",
        )

        reactivation_wizard = self.ReactivationWizard.create(
            {
                "member_id": member.id,
                "effective_date": today,
                "reason": ("Corrección de fallecimiento registrado por equivocación"),
            }
        )

        self.assertEqual(
            reactivation_wizard.last_withdrawal_cause,
            "death",
        )
        self.assertEqual(
            reactivation_wizard.restore_member_state,
            "lifetime",
        )

        reactivation_wizard.action_confirm()

        member.invalidate_recordset()

        self.assertEqual(member.club_member_state, "lifetime")
        self.assertFalse(member.club_state_before_withdrawal)

        reactivation_event = self.Kardex.search(
            [
                ("member_id", "=", member.id),
                ("event_type", "=", "member_state_changed"),
            ],
            order="id desc",
            limit=1,
        )

        self.assertIn(
            "Corrección de fallecimiento",
            reactivation_event.reason or "",
        )

    def test_reactivation_supports_multiple_cycles(self):
        today = fields.Date.context_today(self.Partner)
        first_withdrawal = today - relativedelta(days=3)
        first_reactivation = today - relativedelta(days=2)
        second_withdrawal = today - relativedelta(days=1)

        member = self._create_member(
            "Socio REA multiciclo",
            99510000500,
            state="temporary",
            join_date=today - relativedelta(years=4),
        )

        member.action_withdraw_club_member(
            "Primer retiro multiciclo",
            effective_date=first_withdrawal,
            withdrawal_cause="administrative",
        )

        member.invalidate_recordset()

        self.assertEqual(member.club_member_state, "inactive")
        self.assertEqual(
            member.club_state_before_withdrawal,
            "temporary",
        )
        self.assertEqual(
            member.club_last_withdrawal_cause,
            "administrative",
        )

        member.action_reactivate_club_member(
            "Primera reactivación multiciclo",
            effective_date=first_reactivation,
        )

        member.invalidate_recordset()

        self.assertEqual(member.club_member_state, "temporary")
        self.assertEqual(
            member.club_last_reactivation_date,
            first_reactivation,
        )

        member.action_withdraw_club_member(
            "Segundo retiro multiciclo",
            effective_date=second_withdrawal,
        )

        member.invalidate_recordset()

        self.assertEqual(member.club_member_state, "inactive")
        self.assertEqual(
            member.club_state_before_withdrawal,
            "temporary",
        )
        self.assertEqual(
            member.club_last_withdrawal_cause,
            "voluntary",
        )

        member.action_reactivate_club_member(
            "Segunda reactivación multiciclo",
            effective_date=today,
        )

        member.invalidate_recordset()

        self.assertEqual(member.club_member_state, "temporary")
        self.assertEqual(
            member.club_last_reactivation_date,
            today,
        )

    def test_withdrawal_cannot_predate_last_reactivation(self):
        today = fields.Date.context_today(self.Partner)
        withdrawal_date = today - relativedelta(days=2)
        reactivation_date = today - relativedelta(days=1)

        member = self._create_member(
            "Socio REA cronología",
            99510000600,
            join_date=today - relativedelta(years=2),
        )

        member.action_withdraw_club_member(
            "Retiro cronología",
            effective_date=withdrawal_date,
        )

        member.action_reactivate_club_member(
            "Reactivación cronología",
            effective_date=reactivation_date,
        )

        with self.assertRaises(ValidationError):
            member.action_withdraw_club_member(
                "Retiro anterior a última REA",
                effective_date=withdrawal_date,
            )

        member.invalidate_recordset()

        self.assertEqual(member.club_member_state, "active")

    def test_reactivation_requires_structured_withdrawal_history(self):
        member = self._create_member(
            "Socio Pasivo histórico sin RET",
            99510000700,
            state="inactive",
        )

        with self.assertRaises(ValidationError):
            member.action_reactivate_club_member(
                "Intento de reactivación sin historial estructurado"
            )

        member.invalidate_recordset()

        self.assertEqual(member.club_member_state, "inactive")

    def test_reactivation_requires_specific_permission(self):
        today = fields.Date.context_today(self.Partner)

        member = self._create_member(
            "Socio REA sin permiso",
            99510000800,
            join_date=today - relativedelta(years=3),
        )

        member.action_withdraw_club_member(
            "Retiro previo a prueba de permiso",
            effective_date=today,
        )

        operator = new_test_user(
            self.env,
            login="club_reactivation_without_permission",
            groups="base.group_user",
        )

        with self.assertRaises(AccessError):
            member.with_user(operator).action_reactivate_club_member(
                "Intento sin permiso",
                effective_date=today,
            )

        member.invalidate_recordset()

        self.assertEqual(member.club_member_state, "inactive")

    def test_reactivation_wizard_calculates_impact_and_executes(self):
        today = fields.Date.context_today(self.Partner)

        member = self._create_member(
            "Socio REA wizard",
            99510000900,
            state="lifetime",
            join_date=today - relativedelta(years=8),
        )

        certificate = self._create_certificate(member)

        eligible_beneficiary = self._create_beneficiary(
            member,
            self._create_person(
                "Beneficiario REA wizard elegible",
                99510001000,
            ),
            start_date=today - relativedelta(years=1),
        )

        independent_blocked = self._create_beneficiary(
            member,
            self._create_person(
                "Beneficiario REA wizard bloqueado",
                99510001100,
            ),
            relationship="parent",
            start_date=today - relativedelta(years=1),
        )

        independent_blocked.write(
            {
                "state": "blocked",
                "block_reason": "Bloqueo independiente wizard",
            }
        )

        member.action_withdraw_club_member(
            "Retiro previo a wizard REA",
            effective_date=today,
            withdrawal_cause="death",
        )

        wizard = self.ReactivationWizard.create(
            {
                "member_id": member.id,
                "effective_date": today,
                "reason": "Corrección mediante wizard REA",
            }
        )

        self.assertEqual(wizard.current_member_state, "inactive")
        self.assertEqual(wizard.restore_member_state, "lifetime")
        self.assertEqual(wizard.last_withdrawal_cause, "death")
        self.assertEqual(wizard.certificate_id, certificate)
        self.assertTrue(wizard.certificate_will_reactivate)
        self.assertEqual(wizard.eligible_beneficiary_count, 1)
        self.assertEqual(
            wizard.preserved_blocked_beneficiary_count,
            1,
        )

        action = wizard.action_confirm()

        member.invalidate_recordset()
        certificate.invalidate_recordset()
        eligible_beneficiary.invalidate_recordset()
        independent_blocked.invalidate_recordset()

        self.assertEqual(member.club_member_state, "lifetime")
        self.assertEqual(certificate.state, "active")
        self.assertEqual(eligible_beneficiary.state, "active")
        self.assertEqual(independent_blocked.state, "blocked")

        self.assertEqual(action["res_model"], "res.partner")
        self.assertEqual(action["res_id"], member.id)
        self.assertEqual(action["target"], "current")

    def test_withdrawal_cause_is_protected_and_validated(self):
        today = fields.Date.context_today(self.Partner)

        member = self._create_member(
            "Socio REA causa protegida",
            99510001200,
            join_date=today - relativedelta(years=2),
        )

        with self.assertRaises(ValidationError):
            member.action_withdraw_club_member(
                "   ",
                effective_date=today,
                withdrawal_cause="death",
            )

        with self.assertRaises(ValidationError):
            member.action_withdraw_club_member(
                "Causa inválida",
                effective_date=today,
                withdrawal_cause="invalid",
            )

        member.action_withdraw_club_member(
            "Retiro voluntario por defecto",
            effective_date=today,
        )

        member.invalidate_recordset()

        self.assertEqual(
            member.club_last_withdrawal_cause,
            "voluntary",
        )

        with self.assertRaises(AccessError):
            member.write(
                {
                    "club_last_withdrawal_cause": "death",
                }
            )

    def test_reassigned_beneficiary_is_not_restored_to_original_member(self):
        today = fields.Date.context_today(self.Partner)

        original_member = self._create_member(
            "Socio REA titular original",
            99510001300,
            state="lifetime",
            join_date=today - relativedelta(years=6),
        )

        new_member = self._create_member(
            "Socio REA nuevo titular",
            99510001400,
            join_date=today - relativedelta(years=3),
        )

        person = self._create_person(
            "Beneficiario REA reasignado",
            99510001500,
        )

        original_link = self._create_beneficiary(
            original_member,
            person,
            relationship="spouse",
            start_date=today - relativedelta(years=1),
        )

        original_member.action_withdraw_club_member(
            "Retiro previo a reasignación",
            effective_date=today,
        )

        original_link.invalidate_recordset()

        self.assertEqual(original_link.state, "blocked")
        self.assertTrue(original_link.blocked_by_member_withdrawal)

        new_link = original_link.reassign_link(
            {
                "new_member_id": new_member.id,
                "relationship": "partner",
                "special_condition": "none",
                "end_date": today,
                "start_date": today,
                "reason": ("Reasignación mientras el titular original está Pasivo"),
            }
        )

        original_link.invalidate_recordset()
        new_link.invalidate_recordset()

        self.assertEqual(original_link.state, "finalized")
        self.assertFalse(original_link.blocked_by_member_withdrawal)
        self.assertEqual(new_link.member_id, new_member)
        self.assertEqual(new_link.state, "active")
        self.assertFalse(new_link.blocked_by_member_withdrawal)

        original_member.action_reactivate_club_member(
            "Reactivación posterior a reasignación",
            effective_date=today,
        )

        original_member.invalidate_recordset()
        original_link.invalidate_recordset()
        new_link.invalidate_recordset()

        self.assertEqual(
            original_member.club_member_state,
            "lifetime",
        )
        self.assertEqual(original_link.state, "finalized")
        self.assertFalse(original_link.blocked_by_member_withdrawal)
        self.assertEqual(new_link.member_id, new_member)
        self.assertEqual(new_link.state, "active")

    def test_manual_block_reason_after_withdrawal_prevents_reactivation(self):
        today = fields.Date.context_today(self.Partner)

        member = self._create_member(
            "Socio REA bloqueo posterior",
            99510001600,
            join_date=today - relativedelta(years=5),
        )

        beneficiary = self._create_beneficiary(
            member,
            self._create_person(
                "Beneficiario REA bloqueo posterior",
                99510001700,
            ),
            relationship="parent",
            start_date=today - relativedelta(years=1),
        )

        member.action_withdraw_club_member(
            "Retiro previo a bloqueo independiente",
            effective_date=today,
        )

        beneficiary.invalidate_recordset()

        self.assertEqual(beneficiary.state, "blocked")
        self.assertTrue(beneficiary.blocked_by_member_withdrawal)

        independent_reason = (
            "Bloqueo administrativo independiente registrado después del retiro"
        )

        beneficiary.write(
            {
                "block_reason": independent_reason,
            }
        )

        beneficiary.invalidate_recordset()

        self.assertEqual(beneficiary.state, "blocked")
        self.assertFalse(beneficiary.blocked_by_member_withdrawal)
        self.assertEqual(
            beneficiary.block_reason,
            independent_reason,
        )

        member.action_reactivate_club_member(
            "Reactivación sin levantar bloqueo independiente",
            effective_date=today,
        )

        member.invalidate_recordset()
        beneficiary.invalidate_recordset()

        self.assertEqual(member.club_member_state, "active")
        self.assertEqual(beneficiary.state, "blocked")
        self.assertFalse(beneficiary.blocked_by_member_withdrawal)
        self.assertEqual(
            beneficiary.block_reason,
            independent_reason,
        )

    def test_certificate_passive_for_other_reason_is_not_reactivated(self):
        today = fields.Date.context_today(self.Partner)

        member = self._create_member(
            "Socio REA certificado Pasivo independiente",
            99510001800,
            join_date=today - relativedelta(years=4),
        )

        certificate = self._create_certificate(member)

        certificate.write(
            {
                "state": "passive",
            }
        )

        certificate.invalidate_recordset()

        self.assertEqual(certificate.state, "passive")
        self.assertFalse(certificate.passive_by_member_withdrawal)

        member.action_withdraw_club_member(
            "Retiro con certificado ya Pasivo",
            effective_date=today,
        )

        member.invalidate_recordset()
        certificate.invalidate_recordset()

        self.assertEqual(member.club_member_state, "inactive")
        self.assertEqual(certificate.state, "passive")
        self.assertFalse(certificate.passive_by_member_withdrawal)

        member.action_reactivate_club_member(
            "Reactivación que no debe tocar certificado independiente",
            effective_date=today,
        )

        member.invalidate_recordset()
        certificate.invalidate_recordset()

        self.assertEqual(member.club_member_state, "active")
        self.assertEqual(certificate.state, "passive")
        self.assertFalse(certificate.passive_by_member_withdrawal)

    def test_rpc_boolean_context_cannot_bypass_beneficiary_transition(self):
        today = fields.Date.context_today(self.Partner)

        member = self._create_member(
            "Socio REA protección RPC",
            99510001900,
            join_date=today - relativedelta(years=3),
        )

        beneficiary = self._create_beneficiary(
            member,
            self._create_person(
                "Beneficiario REA protección RPC",
                99510002000,
            ),
            start_date=today - relativedelta(years=1),
        )

        member.action_withdraw_club_member(
            "Retiro previo a prueba de protección RPC",
            effective_date=today,
        )

        beneficiary.invalidate_recordset()

        self.assertTrue(beneficiary.blocked_by_member_withdrawal)

        with self.assertRaises(AccessError):
            beneficiary.with_context(
                club_beneficiary_internal_transition_write=True,
            ).write(
                {
                    "blocked_by_member_withdrawal": False,
                }
            )

        beneficiary.invalidate_recordset()

        self.assertEqual(beneficiary.state, "blocked")
        self.assertTrue(beneficiary.blocked_by_member_withdrawal)

        second_member = self._create_member(
            "Socio REA protección finalización RPC",
            99510002100,
            join_date=today - relativedelta(years=2),
        )

        second_beneficiary = self._create_beneficiary(
            second_member,
            self._create_person(
                "Beneficiario REA finalización RPC",
                99510002200,
            ),
            start_date=today - relativedelta(years=1),
        )

        with self.assertRaises(ValidationError):
            second_beneficiary.with_context(
                club_beneficiary_internal_transition_write=True,
            ).write(
                {
                    "state": "finalized",
                }
            )

        second_beneficiary.invalidate_recordset()

        self.assertEqual(
            second_beneficiary.state,
            "active",
        )

    def test_reactivation_is_blocked_while_member_is_current_beneficiary(self):
        today = fields.Date.context_today(self.Partner)

        member = self._create_member(
            "Socio REA que luego será Beneficiario",
            99510002300,
            join_date=today - relativedelta(years=5),
        )

        certificate = self._create_certificate(member)

        own_beneficiary = self._create_beneficiary(
            member,
            self._create_person(
                "Beneficiario propio del Socio REA",
                99510002400,
            ),
            relationship="parent",
            start_date=today - relativedelta(years=1),
        )

        member.action_withdraw_club_member(
            "Retiro previo a vínculo como Beneficiario",
            effective_date=today,
        )

        member.invalidate_recordset()
        certificate.invalidate_recordset()
        own_beneficiary.invalidate_recordset()

        self.assertEqual(member.club_member_state, "inactive")
        self.assertEqual(certificate.state, "passive")
        self.assertTrue(certificate.passive_by_member_withdrawal)
        self.assertEqual(own_beneficiary.state, "blocked")
        self.assertTrue(own_beneficiary.blocked_by_member_withdrawal)

        titular = self._create_member(
            "Socio titular del vínculo vigente",
            99510002500,
            join_date=today - relativedelta(years=4),
        )

        current_link = self._create_beneficiary(
            titular,
            member,
            relationship="spouse",
            start_date=today,
        )

        self.assertEqual(current_link.state, "active")
        self.assertEqual(current_link.person_id, member)

        with self.assertRaisesRegex(
            ValidationError,
            "Finalice primero el vínculo",
        ):
            member.action_reactivate_club_member(
                "Intento de reactivación con vínculo vigente",
                effective_date=today,
            )

        member.invalidate_recordset()
        certificate.invalidate_recordset()
        own_beneficiary.invalidate_recordset()
        current_link.invalidate_recordset()

        self.assertEqual(member.club_member_state, "inactive")
        self.assertEqual(
            member.club_state_before_withdrawal,
            "active",
        )
        self.assertFalse(member.club_last_reactivation_date)

        self.assertEqual(certificate.state, "passive")
        self.assertTrue(certificate.passive_by_member_withdrawal)

        self.assertEqual(own_beneficiary.state, "blocked")
        self.assertTrue(own_beneficiary.blocked_by_member_withdrawal)

        self.assertEqual(current_link.state, "active")
        self.assertEqual(current_link.person_id, member)
