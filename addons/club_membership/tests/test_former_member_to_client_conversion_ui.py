from dateutil.relativedelta import relativedelta
from lxml import etree
from odoo import fields
from odoo.exceptions import AccessError, ValidationError
from odoo.tests import tagged
from odoo.tests.common import TransactionCase, new_test_user


@tagged("post_install", "-at_install")
class TestFormerMemberToClientConversionUI(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()

        cls.admin = cls.env.ref("base.user_admin")
        cls.Partner = cls.env["res.partner"].with_user(cls.admin)
        cls.Period = cls.env["club.membership.period"].with_user(cls.admin)

        cls.regular_user = new_test_user(
            cls.env,
            login="club_former_member_to_client_ui_without_permission",
            groups="base.group_user",
            name="Usuario sin permiso UI Ex-Socio a Cliente",
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
    def _create_member(cls, name, start_number):
        today = fields.Date.context_today(cls.Partner)

        return cls.Partner.create(
            {
                "name": name,
                "company_type": "person",
                "is_company": False,
                "club_person_type": "member",
                "club_id_number": cls._next_available_id_number(start_number),
                "club_birthdate": cls._birthdate_for_age(40),
                "club_join_date": today - relativedelta(years=5),
            }
        )

    def _prepare_former_member(self, name, start_number):
        today = fields.Date.context_today(self.Partner)

        member = self._create_member(
            name,
            start_number,
        )

        member.action_end_club_membership(
            "Baja definitiva previa a prueba UI Ex-Socio a Cliente.",
            effective_date=today,
        )

        member.invalidate_recordset()

        self.assertFalse(member.club_person_type)
        self.assertTrue(member.club_is_former_member)

        return member, today

    def _view_arch(self, xml_id):
        view = self.env.ref(
            f"club_membership.{xml_id}",
            raise_if_not_found=False,
        )

        self.assertTrue(view)

        arch_db = view.arch_db
        if isinstance(arch_db, str):
            arch_db = arch_db.encode("utf-8")

        return etree.fromstring(arch_db)

    def test_wizard_model_contract_exists(self):
        self.assertIn(
            "club.former.member.to.client.wizard",
            self.env.registry.models,
        )

        Wizard = self.env["club.former.member.to.client.wizard"]

        self.assertTrue(Wizard._fields["person_id"].required)
        self.assertTrue(Wizard._fields["person_id"].readonly)
        self.assertTrue(Wizard._fields["reason"].required)
        self.assertIn("id_number", Wizard._fields)
        self.assertIn("last_membership_end_date", Wizard._fields)
        self.assertNotIn("effective_date", Wizard._fields)

    def test_former_member_can_open_conversion_wizard(self):
        former, _today = self._prepare_former_member(
            "Ex-Socio abrir wizard Cliente",
            99820000100,
        )

        action = former.action_open_club_former_member_to_client_wizard()

        self.assertEqual(action["type"], "ir.actions.act_window")
        self.assertEqual(
            action["res_model"],
            "club.former.member.to.client.wizard",
        )
        self.assertEqual(action["view_mode"], "form")
        self.assertEqual(action["target"], "new")
        self.assertEqual(
            action["context"]["default_person_id"],
            former.id,
        )

        view = self.env.ref(
            "club_membership.view_club_former_member_to_client_wizard_form"
        )

        self.assertEqual(
            action["views"],
            [(view.id, "form")],
        )

    def test_open_wizard_requires_specific_permission(self):
        former, _today = self._prepare_former_member(
            "Ex-Socio wizard Cliente sin permiso",
            99820000200,
        )

        with self.assertRaises(AccessError):
            former.with_user(
                self.regular_user
            ).action_open_club_former_member_to_client_wizard()

    def test_open_wizard_rejects_current_client(self):
        former, _today = self._prepare_former_member(
            "Ex-Socio ya convertido en Cliente",
            99820000300,
        )

        former.action_convert_former_member_to_client(
            "Conversión previa para validar que el wizard ya no abra."
        )

        former.invalidate_recordset()

        self.assertEqual(former.club_person_type, "client")
        self.assertTrue(former.club_is_former_member)

        with self.assertRaises(ValidationError):
            former.action_open_club_former_member_to_client_wizard()

    def test_wizard_executes_conversion_and_returns_client_form(self):
        former, today = self._prepare_former_member(
            "Ex-Socio ejecución wizard Cliente",
            99820000400,
        )

        wizard = (
            self.env["club.former.member.to.client.wizard"]
            .with_user(self.admin)
            .create(
                {
                    "person_id": former.id,
                    "reason": "Conversión confirmada mediante wizard.",
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

        periods_before = self.Period.search(
            [("person_id", "=", former.id)],
            order="id",
        )

        self.assertEqual(len(periods_before), 1)
        self.assertEqual(periods_before.state, "finalized")

        action = wizard.action_confirm()

        former.invalidate_recordset()

        periods_after = self.Period.search(
            [("person_id", "=", former.id)],
            order="id",
        )

        self.assertEqual(former.club_person_type, "client")
        self.assertTrue(former.club_is_former_member)
        self.assertEqual(periods_after.ids, periods_before.ids)
        self.assertEqual(periods_after.state, "finalized")

        self.assertEqual(action["res_model"], "res.partner")
        self.assertEqual(action["res_id"], former.id)
        self.assertEqual(action["target"], "current")
        self.assertEqual(
            action["views"],
            [
                (
                    self.env.ref(
                        "club_membership.view_partner_form_club_membership"
                    ).id,
                    "form",
                )
            ],
        )

    def test_wizard_rejects_blank_reason(self):
        former, _today = self._prepare_former_member(
            "Ex-Socio wizard Cliente sin motivo",
            99820000500,
        )

        wizard = (
            self.env["club.former.member.to.client.wizard"]
            .with_user(self.admin)
            .create(
                {
                    "person_id": former.id,
                    "reason": "   ",
                }
            )
        )

        with self.assertRaises(ValidationError):
            wizard.action_confirm()

        former.invalidate_recordset()

        self.assertFalse(former.club_person_type)
        self.assertTrue(former.club_is_former_member)

    def test_wizard_view_contract(self):
        arch = self._view_arch("view_club_former_member_to_client_wizard_form")

        field_names = {field.get("name") for field in arch.xpath("//field")}

        self.assertIn("person_id", field_names)
        self.assertIn("id_number", field_names)
        self.assertIn("last_membership_end_date", field_names)
        self.assertIn("reason", field_names)
        self.assertNotIn("effective_date", field_names)

        text = " ".join("".join(arch.itertext()).split())

        self.assertIn("misma Persona", text)
        self.assertIn("No crea ni reabre períodos", text)
        self.assertIn("Certificado Patrimonial", text)
        self.assertIn("Reingreso", text)

        buttons = arch.xpath("//footer/button[@name='action_confirm']")

        self.assertEqual(len(buttons), 1)
        self.assertEqual(buttons[0].get("type"), "object")
        self.assertEqual(
            buttons[0].get("string"),
            "Confirmar conversión",
        )

    def test_form_exposes_former_member_to_client_button(self):
        arch = self._view_arch("view_partner_form_club_membership")

        buttons = arch.xpath(
            "//header/button[@name='action_open_club_former_member_to_client_wizard']"
        )

        self.assertEqual(len(buttons), 1)

        button = buttons[0]

        self.assertEqual(
            button.get("string"),
            "Convertir Ex-Socio en Cliente",
        )
        self.assertEqual(
            button.get("groups"),
            "club_membership.group_club_former_member_to_client",
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

    def test_wizard_acl_uses_specific_group(self):
        self.assertIn(
            "club.former.member.to.client.wizard",
            self.env.registry.models,
        )

        model = self.env["ir.model"].search(
            [
                (
                    "model",
                    "=",
                    "club.former.member.to.client.wizard",
                ),
            ],
            limit=1,
        )

        self.assertTrue(model)

        group = self.env.ref("club_membership.group_club_former_member_to_client")

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
