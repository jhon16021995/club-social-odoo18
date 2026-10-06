from odoo.tests import TransactionCase, tagged


@tagged("post_install", "-at_install")
class TestFormerMemberStatus(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()

        cls.admin = cls.env.ref("base.user_admin")
        cls.Partner = cls.env["res.partner"].with_user(cls.admin)
        cls.Period = cls.env["club.membership.period"].with_user(cls.admin)

    def _create_person(self, name, id_number):
        return self.Partner.create(
            {
                "name": name,
                "company_type": "person",
                "is_company": False,
                "club_id_number": str(id_number),
                "club_birthdate": "1985-01-15",
            }
        )

    def _create_member(self, name, id_number):
        return self.Partner.create(
            {
                "name": name,
                "company_type": "person",
                "is_company": False,
                "club_person_type": "member",
                "club_id_number": str(id_number),
                "club_birthdate": "1985-01-15",
                "club_join_date": "2024-01-01",
            }
        )

    def _create_period(
        self,
        person,
        *,
        start_date="2020-01-01",
        origin="initial",
        member_code="99880000001",
    ):
        return self.Period._create_period_internal(  # pylint: disable=protected-access
            {
                "person_id": person.id,
                "start_date": start_date,
                "origin": origin,
                "member_code": member_code,
            }
        )

    def _finalize_period(
        self,
        period,
        *,
        end_date="2021-12-31",
        reason="Finalización histórica de prueba",
    ):
        return period._finalize_period_internal(  # pylint: disable=protected-access
            end_date,
            reason,
        )

    def _void_period(
        self,
        period,
        reason="Alta errónea histórica de prueba",
    ):
        return period._void_period_internal(  # pylint: disable=protected-access
            reason
        )

    def test_person_without_membership_history_is_not_former_member(self):
        person = self._create_person(
            "Persona sin historia de membresía",
            99880000101,
        )

        self.assertFalse(person.club_is_former_member)

    def test_voided_period_does_not_create_former_member_condition(self):
        person = self._create_person(
            "Persona con período anulado",
            99880000201,
        )
        period = self._create_period(
            person,
            member_code="99880000201",
        )

        self._void_period(period)

        person.invalidate_recordset()
        period.invalidate_recordset()

        self.assertEqual(period.state, "voided")
        self.assertFalse(person.club_is_former_member)

    def test_finalized_period_without_current_membership_is_former_member(self):
        person = self._create_person(
            "Ex-Socio con período finalizado",
            99880000301,
        )
        period = self._create_period(
            person,
            member_code="99880000301",
        )

        self._finalize_period(period)

        person.invalidate_recordset()
        period.invalidate_recordset()

        self.assertEqual(period.state, "finalized")
        self.assertTrue(person.club_is_former_member)

    def test_current_member_role_is_never_shown_as_former_member(self):
        member = self._create_member(
            "Socio actual con período finalizado inconsistente",
            99880000401,
        )

        period = self.Period.search(
            [
                ("person_id", "=", member.id),
                ("state", "=", "current"),
            ],
            limit=1,
        )
        self.assertTrue(period)

        self._finalize_period(
            period,
            end_date="2024-12-31",
            reason="Finalización técnica sin retirar rol actual",
        )

        member.invalidate_recordset()
        period.invalidate_recordset()

        self.assertEqual(member.club_person_type, "member")
        self.assertEqual(period.state, "finalized")
        self.assertFalse(member.club_is_former_member)

    def test_new_current_period_suppresses_former_member_condition(self):
        person = self._create_person(
            "Persona con reingreso histórico",
            99880000501,
        )

        old_period = self._create_period(
            person,
            member_code="99880000501",
        )
        self._finalize_period(old_period)

        new_period = self._create_period(
            person,
            start_date="2022-01-01",
            origin="reentry",
            member_code="99880000501",
        )

        person.invalidate_recordset()
        old_period.invalidate_recordset()
        new_period.invalidate_recordset()

        self.assertEqual(old_period.state, "finalized")
        self.assertEqual(new_period.state, "current")
        self.assertFalse(person.club_is_former_member)

    def test_definitive_membership_end_sets_former_member_condition(self):
        member = self._create_member(
            "Socio para condición Ex-Socio",
            99880000601,
        )

        self.assertFalse(member.club_is_former_member)

        member.action_end_club_membership(
            "Baja definitiva para validar condición Ex-Socio.",
            effective_date="2025-01-01",
        )

        member.invalidate_recordset()

        self.assertFalse(member.club_person_type)
        self.assertTrue(member.club_is_former_member)
