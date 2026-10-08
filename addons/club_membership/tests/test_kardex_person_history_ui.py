from lxml import etree
from odoo import fields
from odoo.tests import tagged
from odoo.tests.common import TransactionCase


@tagged("post_install", "-at_install")
class TestKardexPersonHistoryUI(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()

        cls.admin = cls.env.ref("base.user_admin")
        cls.Partner = cls.env["res.partner"].with_user(cls.admin)

    @classmethod
    def _next_available_id_number(cls, start):
        number = start

        while cls.Partner.search(
            [("club_id_number", "=", str(number))],
            limit=1,
        ):
            number += 1

        return str(number)

    def _prepare_former_member(self):
        today = fields.Date.context_today(self.Partner)

        member = self.Partner.create(
            {
                "name": "Ex-Socio historial Kardex visible",
                "company_type": "person",
                "is_company": False,
                "club_person_type": "member",
                "club_id_number": self._next_available_id_number(99830000100),
                "club_birthdate": "1985-01-01",
                "club_join_date": today,
            }
        )

        member.action_end_club_membership(
            "Baja definitiva para probar historial visible.",
            effective_date=today,
        )

        member.invalidate_recordset()

        self.assertTrue(member.club_is_former_member)
        self.assertFalse(member.club_person_type)

        return member

    def _kardex_inherited_arch(self):
        view = self.env.ref("club_membership.view_partner_form_club_kardex")

        return etree.fromstring(view.arch_db.encode())

    def test_kardex_view_expands_notebook_visibility_contract(self):
        arch = self._kardex_inherited_arch()

        notebook_attrs = arch.xpath(
            "//xpath[@expr='//notebook' and @position='attributes']"
            "/attribute[@name='invisible']"
        )

        self.assertEqual(len(notebook_attrs), 1)

        expression = " ".join("".join(notebook_attrs[0].itertext()).split())

        self.assertEqual(
            expression,
            "club_person_type != 'member' and not club_kardex_event_ids",
        )

    def test_member_only_pages_remain_hidden_for_non_members(self):
        arch = self._kardex_inherited_arch()

        expected_pages = (
            "club_beneficiaries",
            "club_beneficiary_person_history",
        )

        for page_name in expected_pages:
            modifiers = arch.xpath(
                "//xpath["
                f"@expr=\"//page[@name='{page_name}']\" "
                "and @position='attributes'"
                "]/attribute[@name='invisible']"
            )

            self.assertEqual(
                len(modifiers),
                1,
                f"Debe protegerse la pestaña {page_name}.",
            )

            expression = " ".join("".join(modifiers[0].itertext()).split())

            self.assertEqual(
                expression,
                "club_person_type != 'member'",
            )

    def test_kardex_page_remains_read_only(self):
        arch = self._kardex_inherited_arch()

        pages = arch.xpath("//page[@name='club_kardex']")

        self.assertEqual(len(pages), 1)

        lists = pages[0].xpath(".//field[@name='club_kardex_event_ids']/list")

        self.assertEqual(len(lists), 1)
        self.assertEqual(lists[0].get("create"), "false")
        self.assertEqual(lists[0].get("edit"), "false")
        self.assertEqual(lists[0].get("delete"), "false")

    def test_converted_former_member_keeps_accessible_kardex_events(self):
        former = self._prepare_former_member()

        events_before = former.club_kardex_event_ids
        self.assertTrue(events_before)

        former.action_convert_former_member_to_client(
            "Conversión para verificar historial de Kardex visible."
        )

        former.invalidate_recordset()

        self.assertEqual(former.club_person_type, "client")
        self.assertTrue(former.club_is_former_member)
        self.assertTrue(former.club_kardex_event_ids)

        conversion_events = former.club_kardex_event_ids.filtered(
            lambda event: event.event_type == "former_member_converted_to_client"
        )

        self.assertEqual(len(conversion_events), 1)
        self.assertEqual(
            conversion_events.reason,
            "Conversión para verificar historial de Kardex visible.",
        )
