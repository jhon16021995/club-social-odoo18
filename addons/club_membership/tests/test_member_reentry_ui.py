from dateutil.relativedelta import relativedelta
from lxml import etree
from odoo import fields
from odoo.exceptions import AccessError, ValidationError
from odoo.tests import TransactionCase, tagged
from odoo.tests.common import new_test_user


@tagged("post_install", "-at_install")
class TestMemberReentryUI(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()

        cls.admin = cls.env.ref("base.user_admin")

        cls.Partner = cls.env["res.partner"].with_user(cls.admin)
        cls.Certificate = cls.env["club.certificate"].with_user(cls.admin)
        cls.Beneficiary = cls.env["club.beneficiary"].with_user(cls.admin)
        cls.Period = cls.env["club.membership.period"].with_user(cls.admin)

        cls.regular_user = new_test_user(
            cls.env,
            login="club_member_reentry_ui_without_permission",
            groups="base.group_user",
            name="Usuario sin permiso UI de Reingreso",
        )

    def _ref(self, xmlid):
        return self.env.ref(
            f"club_membership.{xmlid}",
            raise_if_not_found=False,
        )

    def _view_arch(self, xmlid):
        view = self._ref(xmlid)
        self.assertTrue(view, f"Debe existir la vista {xmlid}.")
        return etree.fromstring(view.arch_db.encode())

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
            "Baja definitiva previa a prueba UI de Reingreso.",
            effective_date=today,
        )

        member.invalidate_recordset()

        if certificate:
            certificate.invalidate_recordset()

        return member, certificate, today

    def test_reentry_wizard_model_contract_exists(self):
        self.assertIn(
            "club.member.reentry.wizard",
            self.env.registry.models,
        )

        Wizard = self.env["club.member.reentry.wizard"]

        self.assertTrue(Wizard._fields["person_id"].required)
        self.assertTrue(Wizard._fields["person_id"].readonly)
        self.assertTrue(Wizard._fields["effective_date"].required)
        self.assertTrue(Wizard._fields["reason"].required)

        self.assertIn("last_membership_end_date", Wizard._fields)
        self.assertIn("certificate_will_reactivate", Wizard._fields)
        self.assertIn("active_beneficiary_count", Wizard._fields)
        self.assertIn("blocked_beneficiary_count", Wizard._fields)

    def test_open_reentry_wizard_for_former_member(self):
        former, _certificate, _today = self._prepare_former_member(
            "Ex-Socio abrir wizard Reingreso",
            99710000100,
        )

        action = former.action_open_club_member_reentry_wizard()

        self.assertEqual(action["type"], "ir.actions.act_window")
        self.assertEqual(
            action["res_model"],
            "club.member.reentry.wizard",
        )
        self.assertEqual(action["view_mode"], "form")
        self.assertEqual(action["target"], "new")
        self.assertEqual(
            action["context"]["default_person_id"],
            former.id,
        )

        view = self._ref("view_club_member_reentry_wizard_form")

        self.assertTrue(view)
        self.assertEqual(
            action["views"],
            [(view.id, "form")],
        )

    def test_open_reentry_wizard_requires_specific_permission(self):
        former, _certificate, _today = self._prepare_former_member(
            "Ex-Socio wizard sin permiso",
            99710000200,
        )

        with self.assertRaises(AccessError):
            former.with_user(self.regular_user).action_open_club_member_reentry_wizard()

    def test_open_reentry_wizard_rejects_current_client_role(self):
        former, _certificate, _today = self._prepare_former_member(
            "Ex-Socio Cliente sin Reingreso directo UI",
            99710000300,
        )

        former.write(
            {
                "club_person_type": "client",
            }
        )

        former.invalidate_recordset()

        self.assertEqual(former.club_person_type, "client")
        self.assertTrue(former.club_is_former_member)

        with self.assertRaises(ValidationError):
            former.action_open_club_member_reentry_wizard()

    def test_reentry_wizard_calculates_impact(self):
        former, certificate, today = self._prepare_former_member(
            "Ex-Socio impacto wizard Reingreso",
            99710000400,
            with_certificate=True,
        )

        holder = self._create_member(
            "Socio titular para impacto Reingreso",
            99710000500,
            join_date=today - relativedelta(years=4),
        )

        self.Beneficiary.create(
            {
                "person_id": former.id,
                "member_id": holder.id,
                "relationship": "spouse",
                "special_condition": "none",
            }
        )

        self.assertIn(
            "club.member.reentry.wizard",
            self.env.registry.models,
        )

        wizard = (
            self.env["club.member.reentry.wizard"]
            .with_user(self.admin)
            .create(
                {
                    "person_id": former.id,
                    "effective_date": today,
                    "reason": "Inspección de impacto de Reingreso.",
                }
            )
        )

        self.assertEqual(wizard.person_id, former)
        self.assertEqual(
            wizard.id_number,
            former.club_id_number,
        )
        self.assertEqual(
            wizard.last_membership_end_date,
            today,
        )
        self.assertEqual(wizard.certificate_id, certificate)
        self.assertEqual(wizard.certificate_state, "passive")
        self.assertTrue(wizard.certificate_will_reactivate)
        self.assertEqual(wizard.active_beneficiary_count, 1)
        self.assertEqual(wizard.blocked_beneficiary_count, 0)

    def test_reentry_wizard_executes_same_day(self):
        former, certificate, today = self._prepare_former_member(
            "Ex-Socio ejecución wizard Reingreso",
            99710000600,
            with_certificate=True,
        )

        self.assertIn(
            "club.member.reentry.wizard",
            self.env.registry.models,
        )

        wizard = (
            self.env["club.member.reentry.wizard"]
            .with_user(self.admin)
            .create(
                {
                    "person_id": former.id,
                    "effective_date": today,
                    "reason": "Reingreso confirmado mediante wizard.",
                }
            )
        )

        action = wizard.action_confirm()

        former.invalidate_recordset()
        certificate.invalidate_recordset()

        self.assertEqual(former.club_person_type, "member")
        self.assertEqual(former.club_member_state, "active")
        self.assertFalse(former.club_is_former_member)

        self.assertEqual(certificate.state, "active")
        self.assertFalse(certificate.passive_by_membership_end)

        self.assertEqual(action["res_model"], "res.partner")
        self.assertEqual(action["res_id"], former.id)
        self.assertEqual(action["target"], "current")

    def test_reentry_wizard_preserves_historical_effective_date(self):
        today = fields.Date.context_today(self.Partner)
        effective_date = today - relativedelta(days=1)

        former = self._create_member(
            "Ex-Socio wizard fecha histórica",
            99710001000,
            join_date=today - relativedelta(years=4),
        )

        former.action_end_club_membership(
            "Baja definitiva histórica previa al Reingreso por wizard.",
            effective_date=effective_date,
        )

        former.invalidate_recordset()

        wizard = (
            self.env["club.member.reentry.wizard"]
            .with_user(self.admin)
            .create(
                {
                    "person_id": former.id,
                    "effective_date": effective_date,
                    "reason": "Reingreso histórico confirmado mediante wizard.",
                }
            )
        )

        wizard.action_confirm()

        former.invalidate_recordset()

        periods = self.Period.search(
            [
                ("person_id", "=", former.id),
            ],
            order="id",
        )

        self.assertEqual(len(periods), 2)
        self.assertEqual(periods[0].state, "finalized")
        self.assertEqual(periods[0].end_date, effective_date)
        self.assertEqual(periods[1].state, "current")
        self.assertEqual(periods[1].origin, "reentry")
        self.assertEqual(periods[1].start_date, effective_date)

        self.assertEqual(former.club_person_type, "member")
        self.assertEqual(former.club_join_date, effective_date)
        self.assertEqual(former.club_member_state, "active")
        self.assertEqual(former.club_legal_state, "regular")

    def test_reentry_wizard_view_contract(self):
        arch = self._view_arch("view_club_member_reentry_wizard_form")

        field_names = {field.get("name") for field in arch.xpath("//field")}

        self.assertIn("person_id", field_names)
        self.assertIn("id_number", field_names)
        self.assertIn("last_membership_end_date", field_names)
        self.assertIn("certificate_id", field_names)
        self.assertIn("certificate_state", field_names)
        self.assertIn("certificate_will_reactivate", field_names)
        self.assertIn("active_beneficiary_count", field_names)
        self.assertIn("blocked_beneficiary_count", field_names)
        self.assertIn("effective_date", field_names)
        self.assertIn("reason", field_names)

        text = " ".join("".join(arch.itertext()).split())

        self.assertIn("Reingreso", text)
        self.assertIn("nuevo período", text)
        self.assertIn("no es una REA", text)

        confirm_buttons = arch.xpath("//footer/button[@name='action_confirm']")

        self.assertEqual(len(confirm_buttons), 1)
        self.assertEqual(
            confirm_buttons[0].get("type"),
            "object",
        )

    def test_former_member_form_exposes_reentry_button(self):
        arch = self._view_arch("view_partner_form_club_membership")

        buttons = arch.xpath(
            "//header/button[@name='action_open_club_member_reentry_wizard']"
        )

        self.assertEqual(len(buttons), 1)

        button = buttons[0]

        self.assertEqual(
            button.get("string"),
            "Reingresar como Socio",
        )
        self.assertEqual(
            button.get("groups"),
            "club_membership.group_club_member_reentry",
        )

        invisible = " ".join((button.get("invisible") or "").split())

        self.assertIn(
            "not club_is_former_member",
            invisible,
        )
        self.assertIn(
            "club_person_type",
            invisible,
        )

    def test_reentry_wizard_acl_uses_specific_group(self):
        self.assertIn(
            "club.member.reentry.wizard",
            self.env.registry.models,
        )

        model = self.env["ir.model"].search(
            [
                ("model", "=", "club.member.reentry.wizard"),
            ],
            limit=1,
        )

        self.assertTrue(model)

        group = self.env.ref("club_membership.group_club_member_reentry")

        access = self.env["ir.model.access"].search(
            [
                ("model_id", "=", model.id),
                ("group_id", "=", group.id),
            ],
            limit=1,
        )

        self.assertTrue(access)
        self.assertTrue(access.perm_read)
        self.assertTrue(access.perm_write)
        self.assertTrue(access.perm_create)
        self.assertTrue(access.perm_unlink)
