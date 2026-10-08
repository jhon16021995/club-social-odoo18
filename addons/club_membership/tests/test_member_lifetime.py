from dateutil.relativedelta import relativedelta
from odoo import fields
from odoo.exceptions import ValidationError
from odoo.tests import TransactionCase, tagged


@tagged("post_install", "-at_install")
class TestMemberLifetime(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()

        cls.Partner = cls.env["res.partner"].with_user(cls.env.ref("base.user_admin"))

    @classmethod
    def _birthdate_for_age(cls, age):
        today = fields.Date.context_today(cls.Partner)
        return fields.Date.to_string(today - relativedelta(years=age))

    def _create_member(
        self,
        id_number,
        *,
        age=60,
        historical_paid=0,
        state="active",
    ):
        return self.Partner.create(
            {
                "name": f"Socio Vitalicio {id_number}",
                "company_type": "person",
                "is_company": False,
                "club_person_type": "member",
                "club_id_number": str(id_number),
                "club_birthdate": self._birthdate_for_age(age),
                "club_ordinary_contributions_historical_paid": historical_paid,
                "club_member_state": state,
            }
        )

    def test_historical_paid_contributions_feed_total(self):
        member = self._create_member(
            99400000101,
            historical_paid=287,
        )

        self.assertEqual(
            member.club_ordinary_contributions_historical_paid,
            287,
        )
        self.assertEqual(
            member.club_ordinary_contributions_paid_total,
            287,
        )

    def test_lifetime_requires_360_paid_contributions_and_age_60(self):
        eligible = self._create_member(
            99400000102,
            age=60,
            historical_paid=360,
        )
        missing_contributions = self._create_member(
            99400000103,
            age=65,
            historical_paid=359,
        )
        too_young = self._create_member(
            99400000104,
            age=59,
            historical_paid=360,
        )

        self.assertTrue(eligible.club_lifetime_eligible)
        self.assertFalse(missing_contributions.club_lifetime_eligible)
        self.assertFalse(too_young.club_lifetime_eligible)

    def test_negative_historical_paid_contributions_are_rejected(self):
        with self.assertRaises(ValidationError):
            self._create_member(
                99400000105,
                historical_paid=-1,
            )

    def test_lifetime_state_is_rejected_without_requirements(self):
        with self.assertRaises(ValidationError):
            self._create_member(
                99400000106,
                age=59,
                historical_paid=359,
                state="lifetime",
            )

    def test_lifetime_state_is_allowed_with_requirements(self):
        member = self._create_member(
            99400000107,
            age=60,
            historical_paid=360,
            state="lifetime",
        )

        self.assertEqual(member.club_member_state, "lifetime")
        self.assertTrue(member.club_lifetime_eligible)

    def test_member_creation_logs_historical_paid_contributions(self):
        member = self._create_member(
            99400000108,
            historical_paid=240,
        )

        event = self.env["club.kardex.event"].search(
            [
                ("member_id", "=", member.id),
                ("event_type", "=", "member_created"),
            ],
            limit=1,
        )

        self.assertTrue(event)
        self.assertIn(
            "Aportes Ordinarios Pagados históricos: 240",
            event.new_value,
        )

    def test_historical_paid_contributions_change_is_logged(self):
        member = self._create_member(
            99400000109,
            historical_paid=240,
        )

        member.write(
            {
                "club_ordinary_contributions_historical_paid": 252,
            }
        )

        event = self.env["club.kardex.event"].search(
            [
                ("member_id", "=", member.id),
                (
                    "event_type",
                    "=",
                    "member_historical_contributions_changed",
                ),
            ],
            order="id desc",
            limit=1,
        )

        self.assertTrue(event)
        self.assertEqual(event.old_value, "240")
        self.assertEqual(event.new_value, "252")
        self.assertEqual(event.origin, "manual")
