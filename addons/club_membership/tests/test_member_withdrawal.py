from dateutil.relativedelta import relativedelta
from odoo import fields
from odoo.exceptions import AccessError, ValidationError
from odoo.tests import tagged
from odoo.tests.common import TransactionCase, new_test_user


@tagged("post_install", "-at_install")
class TestMemberWithdrawal(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()

        cls.admin = cls.env.ref("base.user_admin")

        cls.Partner = cls.env["res.partner"].with_user(cls.admin)
        cls.Certificate = cls.env["club.certificate"].with_user(cls.admin)
        cls.Beneficiary = cls.env["club.beneficiary"].with_user(cls.admin)
        cls.Kardex = cls.env["club.kardex.event"].with_user(cls.admin)
        cls.Period = cls.env["club.membership.period"].with_user(cls.admin)
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
        state="active",
        join_date=False,
    ):
        vals = {
            "name": name,
            "company_type": "person",
            "is_company": False,
            "club_person_type": "member",
            "club_id_number": cls._next_available_id_number(start_number),
            "club_birthdate": cls._birthdate_for_age(40),
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
        relationship="spouse",
    ):
        return cls.Beneficiary.create(
            {
                "person_id": person.id,
                "member_id": member.id,
                "relationship": relationship,
                "special_condition": "none",
            }
        )

    def _assert_single_current_membership_period(self, member):
        periods = self.Period.search(
            [
                ("person_id", "=", member.id),
            ]
        )

        self.assertEqual(len(periods), 1)
        self.assertEqual(periods.state, "current")
        self.assertFalse(periods.end_date)

    def test_withdrawal_updates_history_and_related_records(self):
        today, reason = (
            fields.Date.context_today(self.Partner),
            "Retiro voluntario para prueba automática",
        )

        member = self._create_member(
            name="Socio retiro automático",
            start_number=99500000100,
            join_date=today - relativedelta(years=5),
        )

        self._assert_single_current_membership_period(member)
        original_id_number = member.club_id_number
        original_member_code = member.club_member_code
        original_join_date = member.club_join_date

        certificate = self._create_certificate(member)

        active_beneficiary = self._create_beneficiary(
            member,
            self._create_person(
                "Beneficiario activo retiro",
                99500000200,
            ),
            relationship="spouse",
        )
        blocked_beneficiary = self._create_beneficiary(
            member,
            self._create_person(
                "Beneficiario bloqueado retiro",
                99500000300,
            ),
            relationship="parent",
        )
        finalized_beneficiary = self._create_beneficiary(
            member,
            self._create_person(
                "Beneficiario finalizado retiro",
                99500000400,
            ),
            relationship="partner",
        )

        blocked_beneficiary.write(
            {
                "state": "blocked",
                "block_reason": "Bloqueo previo independiente",
            }
        )
        previous_block_reason = blocked_beneficiary.block_reason

        finalized_beneficiary.finalize_link(
            end_date=today,
            reason="Vínculo finalizado antes del retiro",
        )

        member.action_withdraw_club_member(
            reason,
            effective_date=today,
        )

        self._assert_single_current_membership_period(member)

        member.invalidate_recordset()
        certificate.invalidate_recordset()
        active_beneficiary.invalidate_recordset()
        blocked_beneficiary.invalidate_recordset()
        finalized_beneficiary.invalidate_recordset()

        self.assertEqual(member.club_person_type, "member")
        self.assertEqual(member.club_member_state, "inactive")
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
        self.assertEqual(
            member.club_state_before_withdrawal,
            "active",
        )
        self.assertEqual(
            member.club_last_withdrawal_date,
            today,
        )
        self.assertEqual(
            member.club_last_withdrawal_cause,
            "voluntary",
        )

        self.assertEqual(certificate.state, "passive")
        self.assertTrue(certificate.passive_by_member_withdrawal)

        self.assertEqual(active_beneficiary.state, "blocked")
        self.assertTrue(active_beneficiary.blocked_by_member_withdrawal)
        self.assertIn(
            reason,
            active_beneficiary.block_reason,
        )

        self.assertEqual(blocked_beneficiary.state, "blocked")
        self.assertFalse(blocked_beneficiary.blocked_by_member_withdrawal)
        self.assertEqual(
            blocked_beneficiary.block_reason,
            previous_block_reason,
        )

        self.assertEqual(
            finalized_beneficiary.state,
            "finalized",
        )
        self.assertFalse(finalized_beneficiary.blocked_by_member_withdrawal)

        member_event = self.Kardex.search(
            [
                ("member_id", "=", member.id),
                ("event_type", "=", "member_state_changed"),
            ],
            order="id desc",
            limit=1,
        )

        certificate_event = self.Kardex.search(
            [
                ("member_id", "=", member.id),
                ("event_type", "=", "certificate_state_changed"),
                ("certificate_id", "=", certificate.id),
            ],
            order="id desc",
            limit=1,
        )

        beneficiary_event = self.Kardex.search(
            [
                ("member_id", "=", member.id),
                ("event_type", "=", "beneficiary_blocked"),
                (
                    "beneficiary_id",
                    "=",
                    active_beneficiary.id,
                ),
            ],
            order="id desc",
            limit=1,
        )

        self.assertTrue(member_event)
        self.assertEqual(member_event.origin, "manual")
        self.assertEqual(member_event.user_id, self.admin)
        self.assertIn(reason, member_event.reason or "")

        self.assertTrue(certificate_event)
        self.assertIn(
            reason,
            certificate_event.reason or "",
        )

        self.assertTrue(beneficiary_event)
        self.assertIn(
            reason,
            beneficiary_event.reason or "",
        )

    def test_withdrawal_validations(self):
        today = fields.Date.context_today(self.Partner)

        member = self._create_member(
            name="Socio validaciones retiro",
            start_number=99500000500,
            join_date=today,
        )

        with self.assertRaises(ValidationError):
            member.action_withdraw_club_member(
                "   ",
                effective_date=today,
            )

        with self.assertRaises(ValidationError):
            member.action_withdraw_club_member(
                "Fecha futura",
                effective_date=today + relativedelta(days=1),
            )

        with self.assertRaises(ValidationError):
            member.action_withdraw_club_member(
                "Fecha anterior al ingreso",
                effective_date=today - relativedelta(days=1),
            )

        non_member = self._create_person(
            "Persona no Socio retiro",
            99500000600,
        )

        with self.assertRaises(ValidationError):
            non_member.action_withdraw_club_member(
                "No corresponde",
                effective_date=today,
            )

        passive_member = self._create_member(
            name="Socio ya Pasivo",
            start_number=99500000700,
            state="inactive",
        )

        with self.assertRaises(ValidationError):
            passive_member.action_withdraw_club_member(
                "Segundo retiro inválido",
                effective_date=today,
            )

    def test_direct_passive_state_transitions_are_blocked(self):
        active_member = self._create_member(
            name="Socio paso directo a Pasivo",
            start_number=99500000800,
            state="active",
        )

        with self.assertRaises(ValidationError):
            active_member.write(
                {
                    "club_member_state": "inactive",
                }
            )

        passive_member = self._create_member(
            name="Socio reactivación directa",
            start_number=99500000900,
            state="inactive",
        )

        with self.assertRaises(ValidationError):
            passive_member.write(
                {
                    "club_member_state": "active",
                }
            )

    def test_withdrawal_requires_specific_permission(self):
        today = fields.Date.context_today(self.Partner)

        member = self._create_member(
            name="Socio retiro sin permiso",
            start_number=99500001000,
        )

        operator = new_test_user(
            self.env,
            login="club_withdrawal_without_permission",
            groups="base.group_user",
        )

        with self.assertRaises(AccessError):
            member.with_user(operator).action_withdraw_club_member(
                "Intento sin permiso",
                effective_date=today,
            )

        member.invalidate_recordset()
        self.assertEqual(member.club_member_state, "active")

    def test_withdrawal_wizard_executes_controlled_process(self):
        today = fields.Date.context_today(self.Partner)

        member = self._create_member(
            name="Socio retiro mediante wizard",
            start_number=99500001100,
        )

        wizard = self.WithdrawalWizard.create(
            {
                "member_id": member.id,
                "effective_date": today,
                "reason": "Retiro confirmado mediante wizard",
            }
        )

        action = wizard.action_confirm()

        member.invalidate_recordset()

        self.assertEqual(member.club_member_state, "inactive")
        self.assertEqual(
            member.club_state_before_withdrawal,
            "active",
        )
        self.assertEqual(
            member.club_last_withdrawal_date,
            today,
        )
        self.assertEqual(
            member.club_last_withdrawal_cause,
            "voluntary",
        )
        self.assertEqual(action["res_model"], "res.partner")
        self.assertEqual(action["res_id"], member.id)
        self.assertEqual(action["target"], "current")
