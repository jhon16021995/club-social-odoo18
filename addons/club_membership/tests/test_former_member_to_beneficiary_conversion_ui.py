from dateutil.relativedelta import relativedelta
from lxml import etree
from odoo import fields
from odoo.exceptions import AccessError, ValidationError
from odoo.tests import tagged
from odoo.tests.common import TransactionCase, new_test_user


@tagged("post_install", "-at_install")
class TestFormerMemberToBeneficiaryConversionUI(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()

        cls.admin = cls.env.ref("base.user_admin")
        cls.Partner = cls.env["res.partner"].with_user(cls.admin)
        cls.Beneficiary = cls.env["club.beneficiary"].with_user(cls.admin)
        cls.Period = cls.env["club.membership.period"].with_user(cls.admin)

        cls.regular_user = new_test_user(
            cls.env,
            login="club_former_member_to_beneficiary_ui_without_permission",
            groups="base.group_user",
            name="Usuario UI sin permiso Ex-Socio a Beneficiario",
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
                "club_join_date": today - relativedelta(years=6),
            }
        )

    def _prepare_former_member(self, name, start_number):
        today = fields.Date.context_today(self.Partner)

        member = self._create_member(name, start_number)

        member.action_end_club_membership(
            "Baja definitiva previa a prueba UI Ex-Socio a Beneficiario.",
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

    def test_wizard_model_contract(self):
        self.assertIn(
            "club.former.member.to.beneficiary.wizard",
            self.env.registry.models,
        )

        Wizard = self.env["club.former.member.to.beneficiary.wizard"]

        self.assertTrue(Wizard._fields["person_id"].required)
        self.assertTrue(Wizard._fields["person_id"].readonly)
        self.assertTrue(Wizard._fields["member_id"].required)
        self.assertTrue(Wizard._fields["relationship"].required)
        self.assertTrue(Wizard._fields["start_date"].required)

        self.assertIn("id_number", Wizard._fields)
        self.assertIn("last_membership_end_date", Wizard._fields)
        self.assertIn("special_condition", Wizard._fields)
        self.assertIn("observations", Wizard._fields)
        self.assertNotIn("reason", Wizard._fields)

    def test_former_member_can_open_conversion_wizard(self):
        former, _today = self._prepare_former_member(
            "Ex-Socio abrir wizard Beneficiario",
            99830000100,
        )

        action = former.action_open_club_former_member_to_beneficiary_wizard()

        self.assertEqual(action["type"], "ir.actions.act_window")
        self.assertEqual(
            action["res_model"],
            "club.former.member.to.beneficiary.wizard",
        )
        self.assertEqual(action["view_mode"], "form")
        self.assertEqual(action["target"], "new")
        self.assertEqual(
            action["context"]["default_person_id"],
            former.id,
        )

        view = self.env.ref(
            "club_membership.view_club_former_member_to_beneficiary_wizard_form"
        )

        self.assertEqual(action["views"], [(view.id, "form")])

    def test_open_wizard_requires_specific_permission(self):
        former, _today = self._prepare_former_member(
            "Ex-Socio wizard Beneficiario sin permiso",
            99830000200,
        )

        with self.assertRaisesRegex(
            AccessError,
            "No tiene permiso para convertir un Ex-Socio en Beneficiario",
        ):
            former.with_user(
                self.regular_user
            ).action_open_club_former_member_to_beneficiary_wizard()

    def test_open_wizard_rejects_person_without_finalized_history(self):
        person = self.Partner.create(
            {
                "name": "Persona sin historia para wizard",
                "company_type": "person",
                "is_company": False,
                "club_id_number": self._next_available_id_number(99830000300),
                "club_birthdate": self._birthdate_for_age(40),
            }
        )

        with self.assertRaisesRegex(
            ValidationError,
            "no cumple la condición de Ex-Socio",
        ):
            person.action_open_club_former_member_to_beneficiary_wizard()

    def test_wizard_executes_conversion_and_opens_beneficiary(self):
        former, today = self._prepare_former_member(
            "Ex-Socio ejecución wizard Beneficiario",
            99830000400,
        )

        holder = self._create_member(
            "Titular wizard Ex-Socio Beneficiario",
            99830000500,
        )

        original_id = former.id
        original_id_number = former.club_id_number

        periods_before = self.Period.search(
            [("person_id", "=", former.id)],
            order="id",
        )

        wizard = (
            self.env["club.former.member.to.beneficiary.wizard"]
            .with_user(self.admin)
            .create(
                {
                    "person_id": former.id,
                    "member_id": holder.id,
                    "relationship": "partner",
                    "special_condition": "none",
                    "start_date": today,
                    "observations": (
                        "Conversión Ex-Socio a Beneficiario desde wizard."
                    ),
                }
            )
        )

        self.assertEqual(wizard.person_id, former)
        self.assertEqual(wizard.id_number, former.club_id_number)
        self.assertEqual(
            wizard.last_membership_end_date,
            today,
        )

        action = wizard.action_confirm()

        former.invalidate_recordset()

        beneficiary = self.Beneficiary.browse(action["res_id"])
        beneficiary.invalidate_recordset()

        periods_after = self.Period.search(
            [("person_id", "=", former.id)],
            order="id",
        )

        self.assertEqual(former.id, original_id)
        self.assertEqual(former.club_id_number, original_id_number)
        self.assertFalse(former.club_person_type)
        self.assertTrue(former.club_is_former_member)

        self.assertEqual(periods_after.ids, periods_before.ids)
        self.assertEqual(periods_after.state, "finalized")

        self.assertEqual(beneficiary.person_id, former)
        self.assertEqual(beneficiary.member_id, holder)
        self.assertEqual(beneficiary.relationship, "partner")
        self.assertEqual(beneficiary.start_date, today)
        self.assertEqual(beneficiary.state, "active")

        self.assertEqual(action["type"], "ir.actions.act_window")
        self.assertEqual(action["res_model"], "club.beneficiary")
        self.assertEqual(action["res_id"], beneficiary.id)
        self.assertEqual(action["target"], "current")

    def test_wizard_rejects_date_before_membership_end(self):
        former, today = self._prepare_former_member(
            "Ex-Socio wizard cronología",
            99830000600,
        )

        holder = self._create_member(
            "Titular wizard cronología",
            99830000700,
        )

        wizard = (
            self.env["club.former.member.to.beneficiary.wizard"]
            .with_user(self.admin)
            .create(
                {
                    "person_id": former.id,
                    "member_id": holder.id,
                    "relationship": "spouse",
                    "special_condition": "none",
                    "start_date": today - relativedelta(days=1),
                }
            )
        )

        with self.assertRaisesRegex(
            ValidationError,
            "no puede ser anterior",
        ):
            wizard.action_confirm()

        self.assertFalse(
            self.Beneficiary.search(
                [
                    ("person_id", "=", former.id),
                    ("state", "in", ("active", "blocked")),
                ],
                limit=1,
            )
        )

    def test_family_dependent_requires_detail(self):
        former, today = self._prepare_former_member(
            "Ex-Socio familiar dependiente",
            99830000800,
        )

        holder = self._create_member(
            "Titular familiar dependiente",
            99830000900,
        )

        wizard = (
            self.env["club.former.member.to.beneficiary.wizard"]
            .with_user(self.admin)
            .create(
                {
                    "person_id": former.id,
                    "member_id": holder.id,
                    "relationship": "family_dependent",
                    "relationship_detail": False,
                    "special_condition": "health_dependent",
                    "start_date": today,
                }
            )
        )

        with self.assertRaisesRegex(
            ValidationError,
            "Debe indicar el detalle",
        ):
            wizard.action_confirm()

    def test_wizard_view_contract(self):
        arch = self._view_arch("view_club_former_member_to_beneficiary_wizard_form")

        field_names = {field.get("name") for field in arch.xpath("//field")}

        for name in (
            "person_id",
            "id_number",
            "last_membership_end_date",
            "member_id",
            "relationship",
            "relationship_detail",
            "special_condition",
            "start_date",
            "observations",
        ):
            self.assertIn(name, field_names)

        self.assertNotIn("reason", field_names)

        relationship_detail = arch.xpath("//field[@name='relationship_detail']")

        self.assertEqual(len(relationship_detail), 1)

        invisible = " ".join((relationship_detail[0].get("invisible") or "").split())
        required = " ".join((relationship_detail[0].get("required") or "").split())

        self.assertEqual(
            invisible,
            "relationship != 'family_dependent'",
        )
        self.assertEqual(
            required,
            "relationship == 'family_dependent'",
        )

        text = " ".join("".join(arch.itertext()).split())

        self.assertIn("misma Persona", text)
        self.assertIn("períodos históricos", text)
        self.assertIn("Certificado Patrimonial", text)

        buttons = arch.xpath("//footer/button[@name='action_confirm']")

        self.assertEqual(len(buttons), 1)
        self.assertEqual(buttons[0].get("type"), "object")
        self.assertEqual(
            buttons[0].get("string"),
            "Confirmar conversión",
        )

    def test_shared_form_exposes_controlled_conversion_button(self):
        arch = self._view_arch("view_partner_form_club_membership")

        buttons = arch.xpath(
            "//header/button["
            "@name='action_open_club_former_member_to_beneficiary_wizard'"
            "]"
        )

        self.assertEqual(len(buttons), 1)

        button = buttons[0]

        self.assertEqual(
            button.get("string"),
            "Convertir Ex-Socio en Beneficiario",
        )
        self.assertEqual(
            button.get("groups"),
            "club_membership.group_club_former_member_to_beneficiary",
        )

        invisible = " ".join((button.get("invisible") or "").split())

        self.assertIn("not club_is_former_member", invisible)
        self.assertIn("club_person_type", invisible)
        self.assertIn(
            "club_has_current_beneficiary_link",
            invisible,
        )

    def test_current_beneficiary_hides_conversion_condition(self):
        former, today = self._prepare_former_member(
            "Ex-Socio visibilidad Beneficiario vigente",
            99830001000,
        )

        holder = self._create_member(
            "Titular visibilidad Beneficiario",
            99830001100,
        )

        self.assertFalse(former.club_has_current_beneficiary_link)

        former.action_convert_former_member_to_beneficiary(
            {
                "member_id": holder.id,
                "relationship": "spouse",
                "special_condition": "none",
                "start_date": today,
            }
        )

        former.invalidate_recordset()

        self.assertTrue(former.club_is_former_member)
        self.assertTrue(former.club_has_current_beneficiary_link)

    def test_wizard_acl_uses_specific_group(self):
        model = self.env["ir.model"].search(
            [
                (
                    "model",
                    "=",
                    "club.former.member.to.beneficiary.wizard",
                )
            ],
            limit=1,
        )

        self.assertTrue(model)

        group = self.env.ref("club_membership.group_club_former_member_to_beneficiary")

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
