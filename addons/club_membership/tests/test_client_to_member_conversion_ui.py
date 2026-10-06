from dateutil.relativedelta import relativedelta
from lxml import etree
from odoo import fields
from odoo.exceptions import ValidationError
from odoo.tests import tagged
from odoo.tests.common import TransactionCase


@tagged("post_install", "-at_install")
class TestClientToMemberConversionUI(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()

        cls.admin = cls.env.ref("base.user_admin")
        cls.Partner = cls.env["res.partner"].with_user(cls.admin)
        cls.Period = cls.env["club.membership.period"].with_user(cls.admin)

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
    def _create_client(cls, name, start_number):
        return cls.Partner.create(
            {
                "name": name,
                "company_type": "person",
                "is_company": False,
                "club_person_type": "client",
                "club_id_number": cls._next_available_id_number(start_number),
                "club_birthdate": "1990-01-01",
            }
        )

    def _prepare_historical_client(self):
        today = fields.Date.today()
        original_join_date = today - relativedelta(years=5)

        person = self.Partner.create(
            {
                "name": "Cliente histórico para conversión",
                "company_type": "person",
                "is_company": False,
                "club_person_type": "member",
                "club_id_number": self._next_available_id_number(99721000025),
                "club_birthdate": "1990-01-01",
                "club_join_date": original_join_date,
            }
        )

        person.action_end_club_membership(
            "Baja histórica previa a conversión",
            effective_date=today,
        )

        person.write(
            {
                "club_person_type": "client",
            }
        )

        return person, today

    def test_first_time_client_wizard_is_not_reentry(self):
        client = self._create_client(
            "Cliente modo primera alta",
            99721000010,
        )

        wizard = (
            self.env["club.client.to.member.wizard"]
            .with_user(self.admin)
            .create(
                {
                    "person_id": client.id,
                }
            )
        )

        self.assertFalse(wizard.is_reentry)
        self.assertFalse(wizard.last_membership_end_date)

    def test_historical_client_wizard_is_reentry(self):
        client, today = self._prepare_historical_client()

        wizard = (
            self.env["club.client.to.member.wizard"]
            .with_user(self.admin)
            .create(
                {
                    "person_id": client.id,
                }
            )
        )

        self.assertTrue(wizard.is_reentry)
        self.assertEqual(
            wizard.last_membership_end_date,
            today,
        )

    def test_first_time_client_wizard_confirms_initial_membership(self):
        client = self._create_client(
            "Cliente primera alta desde wizard",
            99721000050,
        )

        wizard = (
            self.env["club.client.to.member.wizard"]
            .with_user(self.admin)
            .create(
                {
                    "person_id": client.id,
                }
            )
        )

        action = wizard.action_confirm()

        client.invalidate_recordset()

        self.assertEqual(client.club_person_type, "member")
        self.assertEqual(client.club_member_code, client.club_id_number)

        periods = self.Period.search(
            [("person_id", "=", client.id)],
            order="id",
        )

        self.assertEqual(len(periods), 1)
        self.assertEqual(periods.state, "current")
        self.assertEqual(periods.origin, "initial")
        self.assertEqual(periods.start_date, client.club_join_date)

        self.assertEqual(action["type"], "ir.actions.act_window")
        self.assertEqual(action["res_model"], "res.partner")
        self.assertEqual(action["res_id"], client.id)
        self.assertEqual(action["view_mode"], "form")
        self.assertEqual(action["target"], "current")

    def test_historical_client_wizard_requires_reason(self):
        client, today = self._prepare_historical_client()

        wizard = (
            self.env["club.client.to.member.wizard"]
            .with_user(self.admin)
            .create(
                {
                    "person_id": client.id,
                    "effective_date": today,
                    "reason": "   ",
                }
            )
        )

        with self.assertRaisesRegex(
            ValidationError,
            "Debe indicar el motivo del Reingreso como Socio.",
        ):
            wizard.action_confirm()

        client.invalidate_recordset()

        self.assertEqual(client.club_person_type, "client")
        self.assertFalse(
            self.Period.search(
                [
                    ("person_id", "=", client.id),
                    ("state", "=", "current"),
                ],
                limit=1,
            )
        )

    def test_historical_client_wizard_requires_effective_date(self):
        client, _today = self._prepare_historical_client()

        wizard = (
            self.env["club.client.to.member.wizard"]
            .with_user(self.admin)
            .create(
                {
                    "person_id": client.id,
                    "reason": "Reingreso administrativo válido.",
                }
            )
        )

        with self.assertRaisesRegex(
            ValidationError,
            "Debe indicar la fecha efectiva del Reingreso como Socio.",
        ):
            wizard.action_confirm()

        client.invalidate_recordset()

        self.assertEqual(client.club_person_type, "client")
        self.assertFalse(
            self.Period.search(
                [
                    ("person_id", "=", client.id),
                    ("state", "=", "current"),
                ],
                limit=1,
            )
        )

    def test_historical_client_wizard_confirms_reentry(self):
        client, today = self._prepare_historical_client()

        historical_period = self.Period.search(
            [
                ("person_id", "=", client.id),
                ("state", "=", "finalized"),
            ],
            limit=1,
        )

        self.assertTrue(historical_period)

        original_period_id = historical_period.id
        original_end_date = historical_period.end_date
        original_end_reason = historical_period.end_reason

        wizard = (
            self.env["club.client.to.member.wizard"]
            .with_user(self.admin)
            .create(
                {
                    "person_id": client.id,
                    "effective_date": today,
                    "reason": "Conversión administrativa de Cliente histórico",
                }
            )
        )

        action = wizard.action_confirm()

        client.invalidate_recordset()

        self.assertEqual(client.club_person_type, "member")
        self.assertEqual(client.club_member_code, client.club_id_number)

        periods = self.Period.search(
            [("person_id", "=", client.id)],
            order="id",
        )

        self.assertEqual(len(periods), 2)

        self.assertEqual(periods[0].id, original_period_id)
        self.assertEqual(periods[0].state, "finalized")
        self.assertEqual(periods[0].end_date, original_end_date)
        self.assertEqual(periods[0].end_reason, original_end_reason)

        self.assertEqual(periods[1].state, "current")
        self.assertEqual(periods[1].origin, "reentry")
        self.assertEqual(periods[1].start_date, today)

        self.assertEqual(action["type"], "ir.actions.act_window")
        self.assertEqual(action["res_model"], "res.partner")
        self.assertEqual(action["res_id"], client.id)
        self.assertEqual(action["target"], "current")

    def test_client_to_member_wizard_view_contract(self):
        arch = self._view_arch("view_club_client_to_member_wizard_form")

        field_names = {field.get("name") for field in arch.xpath("//field")}

        self.assertIn("person_id", field_names)
        self.assertIn("is_reentry", field_names)
        self.assertIn(
            "last_membership_end_date",
            field_names,
        )
        self.assertIn("effective_date", field_names)
        self.assertIn("reason", field_names)

        is_reentry_field = arch.xpath("//field[@name='is_reentry']")
        self.assertEqual(len(is_reentry_field), 1)
        self.assertEqual(
            is_reentry_field[0].get("invisible"),
            "1",
        )

        last_end_date = arch.xpath("//field[@name='last_membership_end_date']")[0]
        self.assertEqual(
            last_end_date.get("invisible"),
            "not is_reentry",
        )

        effective_date = arch.xpath("//field[@name='effective_date']")[0]
        self.assertEqual(
            effective_date.get("invisible"),
            "not is_reentry",
        )
        self.assertEqual(
            effective_date.get("required"),
            "is_reentry",
        )

        reason = arch.xpath("//field[@name='reason']")[0]
        self.assertEqual(
            reason.get("invisible"),
            "not is_reentry",
        )
        self.assertEqual(
            reason.get("required"),
            "is_reentry",
        )

        confirm_buttons = arch.xpath("//footer/button[@name='action_confirm']")
        self.assertEqual(len(confirm_buttons), 1)
        self.assertEqual(
            confirm_buttons[0].get("type"),
            "object",
        )
        self.assertEqual(
            confirm_buttons[0].get("string"),
            "Confirmar conversión",
        )

    def test_shared_form_protects_existing_person_role(self):
        arch = self._view_arch("view_partner_form_club_membership")

        person_type_fields = arch.xpath("//field[@name='club_person_type']")

        self.assertEqual(len(person_type_fields), 1)

        readonly_expression = " ".join(
            (person_type_fields[0].get("readonly") or "").split()
        )

        self.assertEqual(
            readonly_expression,
            "club_person_type or club_is_former_member",
        )

    def test_shared_form_exposes_controlled_client_to_member_button(self):
        arch = self._view_arch("view_partner_form_club_membership")

        buttons = arch.xpath(
            "//header/button[@name='action_open_club_client_to_member_wizard']"
        )

        self.assertEqual(len(buttons), 1)

        button = buttons[0]

        self.assertEqual(
            button.get("string"),
            "Convertir Cliente en Socio",
        )
        self.assertEqual(
            button.get("type"),
            "object",
        )
        self.assertEqual(
            button.get("groups"),
            "club_membership.group_club_client_to_member",
        )

        invisible_expression = " ".join((button.get("invisible") or "").split())

        self.assertEqual(
            invisible_expression,
            "club_person_type != 'client'",
        )

    def test_client_can_open_conversion_wizard(self):
        client = self._create_client(
            "Cliente apertura wizard conversión",
            99721000100,
        )

        action = client.action_open_club_client_to_member_wizard()

        self.assertEqual(action["type"], "ir.actions.act_window")
        self.assertEqual(
            action["res_model"],
            "club.client.to.member.wizard",
        )
        self.assertEqual(action["view_mode"], "form")
        self.assertEqual(action["target"], "new")
        self.assertEqual(
            action["context"]["default_person_id"],
            client.id,
        )

        expected_view = self._ref("view_club_client_to_member_wizard_form")

        self.assertEqual(
            action.get("views"),
            [(expected_view.id, "form")],
        )
