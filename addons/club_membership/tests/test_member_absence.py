from dateutil.relativedelta import relativedelta
from odoo import fields
from odoo.exceptions import AccessError, ValidationError
from odoo.tests import tagged
from odoo.tests.common import TransactionCase, new_test_user


@tagged("post_install", "-at_install")
class TestMemberAbsence(TransactionCase):
    def test_mark_absent_preserves_period_and_certificate(self):
        Partner = self.env["res.partner"].with_user(self.env.ref("base.user_admin"))
        today = fields.Date.context_today(Partner)
        id_number = 99533500001

        while Partner.search([("club_id_number", "=", str(id_number))], limit=1):
            id_number += 1

        member = Partner.create(
            {
                "name": "Socio prueba ausencia controlada",
                "company_type": "person",
                "is_company": False,
                "club_person_type": "member",
                "club_id_number": str(id_number),
                "club_birthdate": today - relativedelta(years=40),
                "club_join_date": today - relativedelta(years=3),
                "club_member_state": "active",
            }
        )

        certificate = (
            self.env["club.certificate"]
            .with_user(self.env.ref("base.user_admin"))
            .create(
                {
                    "member_id": member.id,
                    "registration_origin": "new",
                    "total_value": 1000,
                    "opening_balance": 1000,
                }
            )
        )

        periods_before = member.club_membership_period_ids.ids
        expected_return = today + relativedelta(months=3)

        member.action_mark_club_member_absent(
            "Ausencia temporal de prueba",
            effective_date=today,
            expected_return_date=expected_return,
        )

        member.invalidate_recordset()
        certificate.invalidate_recordset()

        self.assertEqual(member.club_member_state, "absent")
        self.assertEqual(
            member.club_absence_expected_return_date,
            expected_return,
        )
        self.assertEqual(
            member.club_membership_period_ids.ids,
            periods_before,
        )
        self.assertEqual(
            member.club_membership_period_ids.state,
            "current",
        )
        self.assertEqual(certificate.state, "active")

    def test_return_from_absence_preserves_history(self):
        Partner = self.env["res.partner"].with_user(self.env.ref("base.user_admin"))
        today = fields.Date.context_today(Partner)
        absence_date = today - relativedelta(days=2)

        id_number = 99534200001

        while Partner.search(
            [("club_id_number", "=", str(id_number))],
            limit=1,
        ):
            id_number += 1

        member = Partner.create(
            {
                "name": "Socio prueba retorno de ausencia",
                "company_type": "person",
                "is_company": False,
                "club_person_type": "member",
                "club_id_number": str(id_number),
                "club_birthdate": today - relativedelta(years=40),
                "club_join_date": today - relativedelta(years=3),
                "club_member_state": "active",
            }
        )

        certificate = (
            self.env["club.certificate"]
            .with_user(self.env.ref("base.user_admin"))
            .create(
                {
                    "member_id": member.id,
                    "registration_origin": "new",
                    "total_value": 1000,
                    "opening_balance": 1000,
                }
            )
        )

        original_periods = member.club_membership_period_ids.ids

        member.action_mark_club_member_absent(
            "Ausencia temporal para probar retorno",
            effective_date=absence_date,
            expected_return_date=today + relativedelta(months=2),
        )

        self.assertEqual(member.club_member_state, "absent")

        member.action_return_club_member_from_absence(
            "Retorno presencial del Socio",
            effective_date=today,
        )

        member.invalidate_recordset()
        certificate.invalidate_recordset()

        self.assertEqual(member.club_member_state, "active")
        self.assertFalse(member.club_absence_expected_return_date)
        self.assertEqual(
            member.club_membership_period_ids.ids,
            original_periods,
        )
        self.assertEqual(
            member.club_membership_period_ids.state,
            "current",
        )
        self.assertEqual(certificate.state, "active")

        events = self.env["club.kardex.event"].search(
            [
                ("member_id", "=", member.id),
                ("event_type", "=", "member_state_changed"),
                ("member_state_to", "in", ["absent", "active"]),
            ],
            order="id asc",
        )

        self.assertEqual(len(events), 2)
        self.assertEqual(
            events.mapped("member_state_to"),
            ["absent", "active"],
        )
        self.assertEqual(
            events.mapped("effective_date"),
            [absence_date, today],
        )

    def _create_validation_member(self):
        Partner = self.env["res.partner"].with_user(self.env.ref("base.user_admin"))
        today = fields.Date.context_today(Partner)
        number = 99534300001

        while Partner.search(
            [("club_id_number", "=", str(number))],
            limit=1,
        ):
            number += 1

        member = Partner.create(
            {
                "name": "Socio validación ausencia",
                "company_type": "person",
                "is_company": False,
                "club_person_type": "member",
                "club_id_number": str(number),
                "club_birthdate": today - relativedelta(years=40),
                "club_join_date": today - relativedelta(years=3),
                "club_member_state": "active",
            }
        )
        return member, today

    def test_absence_rejects_invalid_inputs(self):
        member, today = self._create_validation_member()

        with self.assertRaises(ValidationError):
            member.action_mark_club_member_absent("   ", effective_date=today)

        with self.assertRaises(ValidationError):
            member.action_mark_club_member_absent(
                "Viaje",
                effective_date=today + relativedelta(days=1),
            )

        with self.assertRaises(ValidationError):
            member.action_mark_club_member_absent(
                "Viaje",
                effective_date=today,
                expected_return_date=today - relativedelta(days=1),
            )

        self.assertEqual(member.club_member_state, "active")
        self.assertFalse(member.club_absence_expected_return_date)

    def test_return_rejects_invalid_inputs(self):
        member, today = self._create_validation_member()
        absence_date = today - relativedelta(days=3)

        member.action_mark_club_member_absent(
            "Viaje temporal",
            effective_date=absence_date,
            expected_return_date=today + relativedelta(months=2),
        )

        with self.assertRaises(ValidationError):
            member.action_return_club_member_from_absence("   ", effective_date=today)

        with self.assertRaises(ValidationError):
            member.action_return_club_member_from_absence(
                "Retorno",
                effective_date=absence_date - relativedelta(days=1),
            )

        with self.assertRaises(ValidationError):
            member.action_return_club_member_from_absence(
                "Retorno",
                effective_date=today + relativedelta(days=1),
            )

        self.assertEqual(member.club_member_state, "absent")
        self.assertEqual(
            member.club_absence_expected_return_date,
            today + relativedelta(months=2),
        )

    def test_direct_writes_remain_blocked(self):
        member, today = self._create_validation_member()

        with self.assertRaises(ValidationError):
            member.write({"club_member_state": "absent"})

        with self.assertRaises(ValidationError):
            member.write(
                {
                    "club_absence_expected_return_date": today,
                }
            )

        member.action_mark_club_member_absent(
            "Ausencia controlada",
            effective_date=today,
        )

        with self.assertRaises(ValidationError):
            member.write({"club_member_state": "active"})

        self.assertEqual(member.club_member_state, "absent")

    def test_unauthorized_user_cannot_change_absence(self):
        member, today = self._create_validation_member()
        unauthorized = self.env.ref("base.public_user")

        with self.assertRaises(AccessError):
            member.with_user(unauthorized).action_mark_club_member_absent(
                "Intento sin permiso",
                effective_date=today,
            )

        self.assertEqual(member.club_member_state, "active")

        member.action_mark_club_member_absent(
            "Ausencia autorizada",
            effective_date=today,
        )

        with self.assertRaises(AccessError):
            member.with_user(unauthorized).action_return_club_member_from_absence(
                "Intento de retorno",
                effective_date=today,
            )

        self.assertEqual(member.club_member_state, "absent")

    def test_absence_operator_with_permission(self):
        member, today = self._create_validation_member()

        operator = new_test_user(
            self.env,
            login="club_absence_operator_345",
            groups=("base.group_user,club_membership.group_club_member_absence"),
        )

        expected_return = today + relativedelta(days=30)

        member.with_user(operator).action_mark_club_member_absent(
            "Ausencia autorizada por funcionario",
            effective_date=today,
            expected_return_date=expected_return,
        )

        member.invalidate_recordset()

        self.assertEqual(member.club_member_state, "absent")
        self.assertEqual(
            member.club_absence_expected_return_date,
            expected_return,
        )

        member.with_user(operator).action_return_club_member_from_absence(
            "Retorno autorizado por funcionario",
            effective_date=today,
        )

        member.invalidate_recordset()

        self.assertEqual(member.club_member_state, "active")
        self.assertFalse(member.club_absence_expected_return_date)

        events = (
            self.env["club.kardex.event"]
            .sudo()
            .search(
                [
                    ("member_id", "=", member.id),
                    ("event_type", "=", "member_state_changed"),
                    ("member_state_to", "in", ["absent", "active"]),
                ],
                order="id asc",
            )
        )

        self.assertEqual(
            events.mapped("member_state_to"),
            ["absent", "active"],
        )
        self.assertEqual(
            [event.user_id.id for event in events],
            [operator.id, operator.id],
        )

        with self.assertRaises(ValidationError):
            member.with_user(operator).write(
                {
                    "name": "Cambio de nombre no permitido",
                }
            )

    def test_absence_operator_without_permission(self):
        member, today = self._create_validation_member()

        operator = new_test_user(
            self.env,
            login="club_absence_without_permission_345",
            groups="base.group_user",
        )

        with self.assertRaises(AccessError):
            member.with_user(operator).action_mark_club_member_absent(
                "Intento de ausencia sin permiso",
                effective_date=today,
            )

        self.assertEqual(member.club_member_state, "active")

        member.action_mark_club_member_absent(
            "Ausencia registrada por administrador",
            effective_date=today,
        )

        with self.assertRaises(AccessError):
            member.with_user(operator).action_return_club_member_from_absence(
                "Intento de retorno sin permiso",
                effective_date=today,
            )

        self.assertEqual(member.club_member_state, "absent")

    def test_absence_wizards_authorized_operator(self):
        member, today = self._create_validation_member()

        operator = new_test_user(
            self.env,
            login="club_absence_wizard_operator_355",
            groups=("base.group_user,club_membership.group_club_member_absence"),
        )

        self.assertFalse(operator.has_group("base.group_system"))

        action = member.with_user(operator).action_open_club_member_absence_wizard()

        self.assertEqual(
            action["res_model"],
            "club.member.absence.wizard",
        )
        self.assertEqual(action["target"], "new")
        self.assertEqual(
            action["context"]["default_member_id"],
            member.id,
        )

        expected_return = today + relativedelta(days=30)

        wizard = (
            self.env["club.member.absence.wizard"]
            .with_user(operator)
            .with_context(**action["context"])
            .create(
                {
                    "effective_date": today,
                    "expected_return_date": expected_return,
                    "reason": "Ausencia mediante asistente",
                }
            )
        )

        self.assertEqual(wizard.member_id.id, member.id)

        result = wizard.action_confirm()

        self.assertEqual(
            result["type"],
            "ir.actions.act_window_close",
        )

        member.invalidate_recordset()

        self.assertEqual(member.club_member_state, "absent")
        self.assertEqual(
            member.club_absence_expected_return_date,
            expected_return,
        )

        with self.assertRaises(ValidationError):
            member.with_user(operator).action_open_club_member_absence_wizard()

        return_action = member.with_user(
            operator
        ).action_open_club_member_absence_return_wizard()

        self.assertEqual(
            return_action["res_model"],
            "club.member.absence.return.wizard",
        )
        self.assertEqual(return_action["target"], "new")

        return_wizard = (
            self.env["club.member.absence.return.wizard"]
            .with_user(operator)
            .with_context(**return_action["context"])
            .create(
                {
                    "effective_date": today,
                    "reason": "Retorno mediante asistente",
                }
            )
        )

        self.assertEqual(
            return_wizard.member_id.id,
            member.id,
        )

        return_result = return_wizard.action_confirm()

        self.assertEqual(
            return_result["type"],
            "ir.actions.act_window_close",
        )

        member.invalidate_recordset()

        self.assertEqual(member.club_member_state, "active")
        self.assertFalse(member.club_absence_expected_return_date)

        with self.assertRaises(ValidationError):
            member.with_user(operator).action_open_club_member_absence_return_wizard()

    def test_absence_wizards_unauthorized_operator(self):
        member, today = self._create_validation_member()

        operator = new_test_user(
            self.env,
            login="club_absence_wizard_denied_355",
            groups="base.group_user",
        )

        with self.assertRaises(AccessError):
            member.with_user(operator).action_open_club_member_absence_wizard()

        with self.assertRaises(AccessError):
            self.env["club.member.absence.wizard"].with_user(operator).create(
                {
                    "member_id": member.id,
                    "effective_date": today,
                    "reason": "Intento sin autorización",
                }
            )

        member.action_mark_club_member_absent(
            "Ausencia autorizada por administrador",
            effective_date=today,
        )

        with self.assertRaises(AccessError):
            member.with_user(operator).action_open_club_member_absence_return_wizard()

        with self.assertRaises(AccessError):
            self.env["club.member.absence.return.wizard"].with_user(operator).create(
                {
                    "member_id": member.id,
                    "effective_date": today,
                    "reason": "Intento de retorno sin autorización",
                }
            )

        self.assertEqual(member.club_member_state, "absent")

    def test_absence_derived_entry_suspension(self):
        member, today = self._create_validation_member()

        Beneficiary = self.env["club.beneficiary"]

        self.assertFalse(member.club_entry_suspended_by_absence)

        active_link = Beneficiary.new(
            {
                "member_id": member.id,
                "state": "active",
            }
        )

        self.assertFalse(active_link.club_entry_suspended_by_absence)

        member.action_mark_club_member_absent(
            "Ausencia para verificar ingreso",
            effective_date=today,
        )

        member.invalidate_recordset()

        self.assertTrue(member.club_entry_suspended_by_absence)

        active_link = Beneficiary.new(
            {
                "member_id": member.id,
                "state": "active",
            }
        )

        self.assertTrue(active_link.club_entry_suspended_by_absence)
        self.assertEqual(active_link.state, "active")

        blocked_link = Beneficiary.new(
            {
                "member_id": member.id,
                "state": "blocked",
            }
        )

        self.assertFalse(blocked_link.club_entry_suspended_by_absence)
        self.assertEqual(blocked_link.state, "blocked")

        member.action_return_club_member_from_absence(
            "Retorno para verificar ingreso",
            effective_date=today,
        )

        member.invalidate_recordset()

        self.assertFalse(member.club_entry_suspended_by_absence)

        active_link = Beneficiary.new(
            {
                "member_id": member.id,
                "state": "active",
            }
        )

        self.assertFalse(active_link.club_entry_suspended_by_absence)

    def test_absence_real_beneficiary_preserves_link(self):
        member, today = self._create_validation_member()

        admin = self.env.ref("base.user_admin")
        Partner = self.env["res.partner"].with_user(admin)
        Beneficiary = self.env["club.beneficiary"].with_user(admin)

        number = 99536000001

        while Partner.search(
            [("club_id_number", "=", str(number))],
            limit=1,
        ):
            number += 1

        person = Partner.create(
            {
                "name": "Beneficiario real prueba de ausencia",
                "company_type": "person",
                "is_company": False,
                "club_id_number": str(number),
                "club_birthdate": today - relativedelta(years=32),
            }
        )

        link = Beneficiary.create(
            {
                "person_id": person.id,
                "member_id": member.id,
                "relationship": "spouse",
                "special_condition": "none",
                "start_date": today,
            }
        )

        original_link_id = link.id
        original_member_id = link.member_id.id

        self.assertEqual(link.state, "active")
        self.assertFalse(link.end_date)
        self.assertFalse(member.club_entry_suspended_by_absence)
        self.assertFalse(link.club_entry_suspended_by_absence)
        self.assertFalse(person.club_entry_suspended_by_absence)

        member.action_mark_club_member_absent(
            "Ausencia temporal con beneficiario real",
            effective_date=today,
            expected_return_date=today + relativedelta(days=30),
        )

        member.invalidate_recordset()
        link.invalidate_recordset()
        person.invalidate_recordset()

        self.assertEqual(member.club_member_state, "absent")
        self.assertTrue(member.club_entry_suspended_by_absence)
        self.assertTrue(link.club_entry_suspended_by_absence)
        self.assertTrue(person.club_entry_suspended_by_absence)

        self.assertEqual(link.id, original_link_id)
        self.assertEqual(link.member_id.id, original_member_id)
        self.assertEqual(link.person_id.id, person.id)
        self.assertEqual(link.state, "active")
        self.assertFalse(link.end_date)

        member.action_return_club_member_from_absence(
            "Retorno de Socio con beneficiario real",
            effective_date=today,
        )

        member.invalidate_recordset()
        link.invalidate_recordset()
        person.invalidate_recordset()

        self.assertEqual(member.club_member_state, "active")
        self.assertFalse(member.club_entry_suspended_by_absence)
        self.assertFalse(link.club_entry_suspended_by_absence)
        self.assertFalse(person.club_entry_suspended_by_absence)

        self.assertEqual(link.id, original_link_id)
        self.assertEqual(link.member_id.id, original_member_id)
        self.assertEqual(link.person_id.id, person.id)
        self.assertEqual(link.state, "active")
        self.assertFalse(link.end_date)

    def test_absence_entry_gate_with_real_beneficiary(self):
        member, today = self._create_validation_member()

        admin = self.env.ref("base.user_admin")
        Partner = self.env["res.partner"].with_user(admin)

        number = 99536300001

        while Partner.search(
            [("club_id_number", "=", str(number))],
            limit=1,
        ):
            number += 1

        person = Partner.create(
            {
                "name": "Beneficiario prueba control de ingreso",
                "company_type": "person",
                "is_company": False,
                "club_id_number": str(number),
                "club_birthdate": today - relativedelta(years=30),
            }
        )

        link = (
            self.env["club.beneficiary"]
            .with_user(admin)
            .create(
                {
                    "person_id": person.id,
                    "member_id": member.id,
                    "relationship": "spouse",
                    "special_condition": "none",
                    "start_date": today,
                }
            )
        )

        self.assertTrue(member.check_club_entry_absence_restriction())
        self.assertTrue(person.check_club_entry_absence_restriction())
        self.assertTrue(link.check_club_entry_absence_restriction())

        member.action_mark_club_member_absent(
            "Ausencia para control de ingreso",
            effective_date=today,
        )

        member.invalidate_recordset()
        person.invalidate_recordset()
        link.invalidate_recordset()

        for record in (member, person, link):
            with self.assertRaisesRegex(
                ValidationError,
                "Ingreso suspendido",
            ):
                record.check_club_entry_absence_restriction()

        self.assertEqual(link.state, "active")
        self.assertEqual(link.member_id.id, member.id)

        member.action_return_club_member_from_absence(
            "Retorno para control de ingreso",
            effective_date=today,
        )

        member.invalidate_recordset()
        person.invalidate_recordset()
        link.invalidate_recordset()

        self.assertTrue(member.check_club_entry_absence_restriction())
        self.assertTrue(person.check_club_entry_absence_restriction())
        self.assertTrue(link.check_club_entry_absence_restriction())

        self.assertEqual(link.state, "active")
        self.assertEqual(link.member_id.id, member.id)
