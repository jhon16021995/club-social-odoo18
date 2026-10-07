from lxml import etree
from odoo import fields
from odoo.exceptions import AccessError, ValidationError
from odoo.tests import tagged
from odoo.tests.common import TransactionCase, new_test_user


@tagged("post_install", "-at_install")
class TestBeneficiaryToClientConversionUI(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()

        cls.admin = cls.env.ref("base.user_admin")

        cls.Partner = cls.env["res.partner"].with_user(cls.admin)
        cls.Beneficiary = cls.env["club.beneficiary"].with_user(cls.admin)
        cls.Wizard = cls.env["club.beneficiary.to.client.wizard"].with_user(cls.admin)

        cls.regular_user = new_test_user(
            cls.env,
            login="club_beneficiary_to_client_ui_without_permission",
            groups="base.group_user",
            name="Usuario UI sin permiso Beneficiario a Cliente",
        )

        cls.member = cls._create_member(
            "Socio titular UI Beneficiario a Cliente",
            99750000100,
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
    def _create_beneficiary(cls, name, start_number):
        person = cls.Partner.create(
            {
                "name": name,
                "company_type": "person",
                "is_company": False,
                "club_id_number": cls._next_available_id_number(start_number),
                "club_birthdate": "1990-01-01",
            }
        )

        beneficiary = cls.Beneficiary.create(
            {
                "person_id": person.id,
                "member_id": cls.member.id,
                "relationship": "spouse",
                "special_condition": "none",
                "start_date": fields.Date.context_today(person),
            }
        )

        return person, beneficiary

    def test_active_beneficiary_can_open_conversion_wizard(self):
        person, beneficiary = self._create_beneficiary(
            "Beneficiario UI abre conversión Cliente",
            99750000200,
        )

        action = beneficiary.action_open_club_beneficiary_to_client_wizard()

        self.assertEqual(
            action["res_model"],
            "club.beneficiary.to.client.wizard",
        )
        self.assertEqual(action["view_mode"], "form")
        self.assertEqual(action["target"], "new")
        self.assertEqual(
            action["context"]["default_beneficiary_id"],
            beneficiary.id,
        )
        self.assertEqual(
            action["views"][0][0],
            self.env.ref(
                "club_membership.view_club_beneficiary_to_client_wizard_form"
            ).id,
        )

        person.invalidate_recordset()
        beneficiary.invalidate_recordset()

        self.assertFalse(person.club_person_type)
        self.assertEqual(beneficiary.state, "active")

    def test_open_conversion_wizard_requires_specific_permission(self):
        person, beneficiary = self._create_beneficiary(
            "Beneficiario UI sin permiso conversión Cliente",
            99750000300,
        )

        with self.assertRaisesRegex(
            AccessError,
            "No tiene permiso para convertir un Beneficiario en Cliente.",
        ):
            beneficiary.with_user(
                self.regular_user
            ).action_open_club_beneficiary_to_client_wizard()

        person.invalidate_recordset()
        beneficiary.invalidate_recordset()

        self.assertFalse(person.club_person_type)
        self.assertEqual(beneficiary.state, "active")

    def test_wizard_acl_requires_specific_group(self):
        _person, beneficiary = self._create_beneficiary(
            "Beneficiario UI ACL wizard Cliente",
            99750000400,
        )

        with self.assertRaises(AccessError):
            self.env["club.beneficiary.to.client.wizard"].with_user(
                self.regular_user
            ).create(
                {
                    "beneficiary_id": beneficiary.id,
                }
            )

    def test_active_wizard_confirms_conversion_and_opens_client(self):
        person, beneficiary = self._create_beneficiary(
            "Beneficiario UI convertido a Cliente",
            99750000500,
        )

        original_person_id = person.id
        original_id_number = person.club_id_number
        today = fields.Date.context_today(beneficiary)
        reason = "Conversión UI controlada a Cliente."

        wizard = self.Wizard.create(
            {
                "beneficiary_id": beneficiary.id,
                "end_date": today,
                "reason": reason,
            }
        )

        action = wizard.action_confirm()

        person.invalidate_recordset()
        beneficiary.invalidate_recordset()

        self.assertEqual(action["res_model"], "res.partner")
        self.assertEqual(action["res_id"], original_person_id)
        self.assertEqual(action["view_mode"], "form")
        self.assertEqual(action["target"], "current")
        self.assertEqual(
            action["views"][0][0],
            self.env.ref("club_membership.view_partner_form_club_membership").id,
        )

        self.assertEqual(person.id, original_person_id)
        self.assertEqual(person.club_id_number, original_id_number)
        self.assertEqual(person.club_person_type, "client")

        self.assertEqual(beneficiary.person_id, person)
        self.assertEqual(beneficiary.state, "finalized")
        self.assertEqual(beneficiary.end_date, today)
        self.assertEqual(beneficiary.end_reason, reason)

    def test_finalized_wizard_preserves_history_and_opens_client(self):
        person, beneficiary = self._create_beneficiary(
            "Beneficiario UI histórico convertido a Cliente",
            99750000600,
        )

        today = fields.Date.context_today(beneficiary)
        historical_reason = "Finalización histórica previa UI."

        beneficiary.finalize_link(
            end_date=today,
            reason=historical_reason,
        )

        beneficiary.invalidate_recordset()

        original_member = beneficiary.member_id
        original_relationship = beneficiary.relationship
        original_start_date = beneficiary.start_date
        original_end_date = beneficiary.end_date
        original_end_reason = beneficiary.end_reason

        wizard = self.Wizard.create(
            {
                "beneficiary_id": beneficiary.id,
            }
        )

        action = wizard.action_confirm()

        person.invalidate_recordset()
        beneficiary.invalidate_recordset()

        self.assertEqual(action["res_model"], "res.partner")
        self.assertEqual(action["res_id"], person.id)
        self.assertEqual(person.club_person_type, "client")

        self.assertEqual(beneficiary.state, "finalized")
        self.assertEqual(beneficiary.member_id, original_member)
        self.assertEqual(
            beneficiary.relationship,
            original_relationship,
        )
        self.assertEqual(beneficiary.start_date, original_start_date)
        self.assertEqual(beneficiary.end_date, original_end_date)
        self.assertEqual(beneficiary.end_reason, original_end_reason)

    def test_current_wizard_requires_end_date_without_partial_conversion(self):
        person, beneficiary = self._create_beneficiary(
            "Beneficiario UI sin fecha conversión Cliente",
            99750000700,
        )

        wizard = self.Wizard.create(
            {
                "beneficiary_id": beneficiary.id,
                "end_date": False,
                "reason": "Motivo presente.",
            }
        )

        with self.assertRaisesRegex(
            ValidationError,
            "Debe indicar la fecha de finalización del vínculo.",
        ):
            wizard.action_confirm()

        person.invalidate_recordset()
        beneficiary.invalidate_recordset()

        self.assertFalse(person.club_person_type)
        self.assertEqual(beneficiary.state, "active")
        self.assertFalse(beneficiary.end_date)
        self.assertFalse(beneficiary.end_reason)

    def test_current_wizard_requires_reason_without_partial_conversion(self):
        person, beneficiary = self._create_beneficiary(
            "Beneficiario UI sin motivo conversión Cliente",
            99750000800,
        )

        wizard = self.Wizard.create(
            {
                "beneficiary_id": beneficiary.id,
                "end_date": fields.Date.context_today(beneficiary),
                "reason": "   ",
            }
        )

        with self.assertRaises(ValidationError):
            wizard.action_confirm()

        person.invalidate_recordset()
        beneficiary.invalidate_recordset()

        self.assertFalse(person.club_person_type)
        self.assertEqual(beneficiary.state, "active")
        self.assertFalse(beneficiary.end_date)
        self.assertFalse(beneficiary.end_reason)

    def test_wizard_view_contract(self):
        view = self.env.ref(
            "club_membership.view_club_beneficiary_to_client_wizard_form"
        )

        root = etree.fromstring(view.arch_db.encode())

        self.assertEqual(
            len(root.xpath(".//field[@name='beneficiary_id']")),
            1,
        )
        self.assertEqual(
            len(root.xpath(".//field[@name='person_id']")),
            1,
        )
        self.assertEqual(
            len(root.xpath(".//field[@name='member_id']")),
            1,
        )
        self.assertEqual(
            len(root.xpath(".//field[@name='relationship']")),
            1,
        )
        self.assertEqual(
            len(root.xpath(".//field[@name='beneficiary_state']")),
            1,
        )

        end_date = root.xpath(".//field[@name='end_date']")
        reason = root.xpath(".//field[@name='reason']")

        self.assertEqual(len(end_date), 1)
        self.assertEqual(len(reason), 1)

        self.assertEqual(
            end_date[0].get("required"),
            "beneficiary_state != 'finalized'",
        )
        self.assertEqual(
            reason[0].get("required"),
            "beneficiary_state != 'finalized'",
        )

        finalization_groups = root.xpath(".//group[@string='Finalización del vínculo']")

        self.assertEqual(len(finalization_groups), 1)
        self.assertEqual(
            finalization_groups[0].get("invisible"),
            "beneficiary_state == 'finalized'",
        )

        alerts = root.xpath(
            ".//div[contains(concat(' ', normalize-space(@class), ' '), ' alert ')]"
        )

        self.assertEqual(len(alerts), 2)
        self.assertTrue(all(alert.get("role") == "status" for alert in alerts))

        confirm_buttons = root.xpath(".//button[@name='action_confirm']")

        self.assertEqual(len(confirm_buttons), 1)
        self.assertEqual(
            confirm_buttons[0].get("string"),
            "Confirmar conversión",
        )

    def test_beneficiary_forms_expose_controlled_conversion_button(self):
        expected_group = "club_membership.group_club_beneficiary_to_client"

        view_contracts = (
            (
                "club_membership.view_club_beneficiary_form_beneficiary_to_client",
                "club_membership.view_club_beneficiary_form_transition_actions",
            ),
            (
                "club_membership.view_partner_form_beneficiary_to_client",
                "club_membership.view_partner_form_club_beneficiary_transition_actions",
            ),
        )

        for view_xmlid, parent_xmlid in view_contracts:
            view = self.env.ref(view_xmlid)
            parent = self.env.ref(parent_xmlid)

            self.assertEqual(view.inherit_id, parent)

            root = etree.fromstring(view.arch_db.encode())

            buttons = root.xpath(
                ".//button[@name='action_open_club_beneficiary_to_client_wizard']"
            )

            self.assertEqual(
                len(buttons),
                1,
                msg=f"Botón inesperado en {view_xmlid}.",
            )

            self.assertEqual(
                buttons[0].get("groups"),
                expected_group,
            )
            self.assertEqual(
                buttons[0].get("invisible"),
                "converted_member_id",
            )
            self.assertEqual(
                buttons[0].get("string"),
                "Convertir en Cliente",
            )
