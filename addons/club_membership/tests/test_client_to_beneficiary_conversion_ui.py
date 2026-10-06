from lxml import etree
from odoo import fields
from odoo.exceptions import AccessError, ValidationError
from odoo.tests import tagged
from odoo.tests.common import TransactionCase, new_test_user


@tagged("post_install", "-at_install")
class TestClientToBeneficiaryConversionUI(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()

        cls.admin = cls.env.ref("base.user_admin")

        cls.Partner = cls.env["res.partner"].with_user(cls.admin)
        cls.Beneficiary = cls.env["club.beneficiary"].with_user(cls.admin)

        cls.regular_user = new_test_user(
            cls.env,
            login="club_client_to_beneficiary_ui_without_permission",
            groups="base.group_user",
            name="Usuario UI sin permiso Cliente a Beneficiario",
        )

        cls.member = cls._create_member(
            "Socio titular UI Cliente a Beneficiario",
            99731000100,
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
        return cls.Partner.create(
            {
                "name": name,
                "company_type": "person",
                "is_company": False,
                "club_person_type": "member",
                "club_id_number": cls._next_available_id_number(start_number),
                "club_birthdate": "1980-01-01",
            }
        )

    @classmethod
    def _create_client(
        cls,
        name,
        start_number,
        *,
        is_company=False,
    ):
        vals = {
            "name": name,
            "company_type": "company" if is_company else "person",
            "is_company": is_company,
            "club_person_type": "client",
            "club_id_number": cls._next_available_id_number(start_number),
        }

        if not is_company:
            vals["club_birthdate"] = "1990-01-01"

        return cls.Partner.create(vals)

    def test_client_can_open_conversion_wizard(self):
        client = self._create_client(
            "Cliente apertura wizard Beneficiario",
            99731000200,
        )

        action = client.action_open_club_client_to_beneficiary_wizard()

        self.assertEqual(
            action["type"],
            "ir.actions.act_window",
        )
        self.assertEqual(
            action["res_model"],
            "club.client.to.beneficiary.wizard",
        )
        self.assertEqual(
            action["view_mode"],
            "form",
        )
        self.assertEqual(
            action["target"],
            "new",
        )
        self.assertEqual(
            action["context"]["default_person_id"],
            client.id,
        )

        expected_view = self._ref("view_club_client_to_beneficiary_wizard_form")

        self.assertEqual(
            action.get("views"),
            [(expected_view.id, "form")],
        )

    def test_open_conversion_wizard_requires_specific_permission(self):
        client = self._create_client(
            "Cliente apertura wizard sin permiso",
            99731000300,
        )

        with self.assertRaisesRegex(
            AccessError,
            "No tiene permiso para convertir un Cliente en Beneficiario.",
        ):
            client.with_user(
                self.regular_user
            ).action_open_club_client_to_beneficiary_wizard()

        client.invalidate_recordset()

        self.assertEqual(
            client.club_person_type,
            "client",
        )

    def test_company_client_cannot_open_conversion_wizard(self):
        client = self._create_client(
            "Empresa Cliente wizard Beneficiario",
            99731000400,
            is_company=True,
        )

        with self.assertRaisesRegex(
            ValidationError,
            "Una empresa Cliente no puede convertirse en Beneficiario",
        ):
            client.action_open_club_client_to_beneficiary_wizard()

        client.invalidate_recordset()

        self.assertEqual(
            client.club_person_type,
            "client",
        )

    def test_wizard_confirms_conversion_and_opens_beneficiary(self):
        client = self._create_client(
            "Cliente conversión desde wizard",
            99731000500,
        )

        original_person_id = client.id
        original_id_number = client.club_id_number
        today = fields.Date.context_today(client)

        wizard = (
            self.env["club.client.to.beneficiary.wizard"]
            .with_user(self.admin)
            .create(
                {
                    "person_id": client.id,
                    "member_id": self.member.id,
                    "relationship": "partner",
                    "special_condition": "none",
                    "start_date": today,
                    "observations": ("Conversión Cliente a Beneficiario desde wizard."),
                }
            )
        )

        action = wizard.action_confirm()

        client.invalidate_recordset()

        beneficiary = self.Beneficiary.browse(action["res_id"])
        beneficiary.invalidate_recordset()

        self.assertEqual(
            client.id,
            original_person_id,
        )
        self.assertEqual(
            client.club_id_number,
            original_id_number,
        )
        self.assertFalse(
            client.club_person_type,
        )

        self.assertEqual(
            beneficiary.person_id,
            client,
        )
        self.assertEqual(
            beneficiary.member_id,
            self.member,
        )
        self.assertEqual(
            beneficiary.relationship,
            "partner",
        )
        self.assertEqual(
            beneficiary.start_date,
            today,
        )
        self.assertEqual(
            beneficiary.state,
            "active",
        )

        self.assertEqual(
            action["type"],
            "ir.actions.act_window",
        )
        self.assertEqual(
            action["res_model"],
            "club.beneficiary",
        )
        self.assertEqual(
            action["res_id"],
            beneficiary.id,
        )
        self.assertEqual(
            action["view_mode"],
            "form",
        )
        self.assertEqual(
            action["target"],
            "current",
        )

        expected_view = self._ref("view_club_beneficiary_form")

        self.assertEqual(
            action.get("views"),
            [(expected_view.id, "form")],
        )

    def test_family_dependent_without_detail_rolls_back_conversion(self):
        client = self._create_client(
            "Cliente familiar sin detalle",
            99731000600,
        )

        wizard = (
            self.env["club.client.to.beneficiary.wizard"]
            .with_user(self.admin)
            .create(
                {
                    "person_id": client.id,
                    "member_id": self.member.id,
                    "relationship": "family_dependent",
                    "relationship_detail": False,
                    "special_condition": "health_dependent",
                    "start_date": fields.Date.context_today(client),
                }
            )
        )

        with self.assertRaisesRegex(
            ValidationError,
            "Debe indicar el detalle cuando el vínculo "
            "seleccionado sea Familiar dependiente.",
        ):
            wizard.action_confirm()

        client.invalidate_recordset()

        self.assertEqual(
            client.club_person_type,
            "client",
        )

        self.assertFalse(
            self.Beneficiary.search(
                [
                    ("person_id", "=", client.id),
                    ("state", "in", ("active", "blocked")),
                ],
                limit=1,
            )
        )

    def test_wizard_view_contract(self):
        arch = self._view_arch("view_club_client_to_beneficiary_wizard_form")

        field_names = {field.get("name") for field in arch.xpath("//field")}

        self.assertIn("person_id", field_names)
        self.assertIn("member_id", field_names)
        self.assertIn("relationship", field_names)
        self.assertIn("relationship_detail", field_names)
        self.assertIn("special_condition", field_names)
        self.assertIn("start_date", field_names)
        self.assertIn("observations", field_names)

        relationship_detail = arch.xpath("//field[@name='relationship_detail']")

        self.assertEqual(
            len(relationship_detail),
            1,
        )

        invisible_expression = " ".join(
            (relationship_detail[0].get("invisible") or "").split()
        )

        required_expression = " ".join(
            (relationship_detail[0].get("required") or "").split()
        )

        self.assertEqual(
            invisible_expression,
            "relationship != 'family_dependent'",
        )
        self.assertEqual(
            required_expression,
            "relationship == 'family_dependent'",
        )

        confirm_buttons = arch.xpath("//footer/button[@name='action_confirm']")

        self.assertEqual(
            len(confirm_buttons),
            1,
        )
        self.assertEqual(
            confirm_buttons[0].get("type"),
            "object",
        )
        self.assertEqual(
            confirm_buttons[0].get("string"),
            "Confirmar conversión",
        )

    def test_shared_form_exposes_controlled_conversion_button(self):
        arch = self._view_arch("view_partner_form_club_membership")

        buttons = arch.xpath(
            "//header/button[@name='action_open_club_client_to_beneficiary_wizard']"
        )

        self.assertEqual(
            len(buttons),
            1,
        )

        button = buttons[0]

        self.assertEqual(
            button.get("string"),
            "Convertir Cliente en Beneficiario",
        )
        self.assertEqual(
            button.get("type"),
            "object",
        )
        self.assertEqual(
            button.get("groups"),
            "club_membership.group_club_client_to_beneficiary",
        )

        invisible_expression = " ".join((button.get("invisible") or "").split())

        self.assertEqual(
            invisible_expression,
            "club_person_type != 'client'",
        )
