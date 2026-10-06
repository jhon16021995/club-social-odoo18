from lxml import etree
from odoo.tests import TransactionCase, tagged


@tagged("post_install", "-at_install")
class TestFormerMemberUI(TransactionCase):
    def _ref(self, xmlid):
        return self.env.ref(
            f"club_membership.{xmlid}",
            raise_if_not_found=False,
        )

    def _view_arch(self, xmlid):
        view = self._ref(xmlid)
        self.assertTrue(view, f"Debe existir la vista {xmlid}.")
        return etree.fromstring(view.arch_db.encode())

    def test_former_member_action_exists_with_read_only_scope(self):
        action = self._ref("action_club_former_members")

        self.assertTrue(action)
        self.assertEqual(action.res_model, "res.partner")
        self.assertEqual(action.view_mode, "list,form")
        self.assertIn(
            "('club_is_former_member', '=', True)",
            action.domain,
        )
        self.assertIn("'create': False", action.context)

    def test_former_member_action_uses_specific_list_search_and_shared_form(self):
        action = self._ref("action_club_former_members")
        list_view = self._ref("view_club_former_member_list")
        search_view = self._ref("view_club_former_member_search")
        shared_form = self._ref("view_partner_form_club_membership")

        self.assertTrue(action)
        self.assertTrue(list_view)
        self.assertTrue(search_view)
        self.assertTrue(shared_form)

        self.assertEqual(action.search_view_id, search_view)

        mappings = self.env["ir.actions.act_window.view"].search(
            [
                ("act_window_id", "=", action.id),
            ],
            order="sequence, id",
        )

        mapping_by_mode = {mapping.view_mode: mapping.view_id for mapping in mappings}

        self.assertEqual(mapping_by_mode.get("list"), list_view)
        self.assertEqual(mapping_by_mode.get("form"), shared_form)

    def test_former_member_menu_exists_and_points_to_action(self):
        menu = self._ref("menu_club_former_members")
        action = self._ref("action_club_former_members")

        self.assertTrue(menu)
        self.assertTrue(action)
        self.assertEqual(menu.name, "Ex-Socios")
        self.assertEqual(menu.action, action)

    def test_former_member_list_exposes_identity_and_current_role(self):
        arch = self._view_arch("view_club_former_member_list")

        field_names = {field.get("name") for field in arch.xpath("//field")}

        self.assertIn("name", field_names)
        self.assertIn("club_id_number", field_names)
        self.assertIn("club_id_extension", field_names)
        self.assertIn("club_person_type", field_names)
        self.assertIn("club_is_former_member", field_names)

    def test_former_member_search_exposes_identity_fields(self):
        arch = self._view_arch("view_club_former_member_search")

        field_names = {field.get("name") for field in arch.xpath("//search/field")}

        self.assertIn("name", field_names)
        self.assertIn("club_id_number", field_names)
        self.assertIn("phone", field_names)
        self.assertIn("mobile", field_names)
        self.assertIn("email", field_names)

    def test_shared_form_displays_former_member_condition(self):
        arch = self._view_arch("view_partner_form_club_membership")

        former_field = arch.xpath("//field[@name='club_is_former_member']")
        self.assertTrue(former_field)

        condition = arch.xpath("//*[@name='club_former_member_condition']")
        self.assertEqual(len(condition), 1)

        condition_text = " ".join("".join(condition[0].itertext()).split())
        self.assertIn("Condición institucional", condition_text)
        self.assertIn("Ex-Socio", condition_text)
        self.assertEqual(
            condition[0].get("invisible"),
            "not club_is_former_member",
        )

    def test_person_type_is_protected_for_former_member(self):
        arch = self._view_arch("view_partner_form_club_membership")

        person_type_fields = arch.xpath("//field[@name='club_person_type']")
        self.assertEqual(len(person_type_fields), 1)

        person_type = person_type_fields[0]

        self.assertEqual(
            person_type.get("required"),
            "not club_is_former_member",
        )
        readonly_expression = " ".join((person_type.get("readonly") or "").split())

        self.assertEqual(
            readonly_expression,
            "club_person_type == 'member' or club_is_former_member",
        )
