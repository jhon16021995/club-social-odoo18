from odoo import fields
from odoo.exceptions import ValidationError
from odoo.tests.common import TransactionCase, tagged


@tagged("post_install", "-at_install")
class TestMembershipPeriodFinalization(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.Member = cls.env["res.partner"]
        cls.Period = cls.env["club.membership.period"]

    def _create_member(self, suffix, join_date="2026-01-01"):
        return self.Member.create(
            {
                "name": f"Socio cierre definitivo {suffix}",
                "club_person_type": "member",
                "club_id_number": f"99000013{suffix}",
                "club_birthdate": "1980-01-01",
                "club_join_date": join_date,
            }
        )

    def _get_current_period(self, member):
        period = self.Period.search(
            [
                ("person_id", "=", member.id),
                ("state", "=", "current"),
            ],
            limit=1,
        )
        self.assertTrue(period)
        return period

    def test_finalize_current_period_sets_terminal_metadata(self):
        member = self._create_member("001")
        period = self._get_current_period(member)
        end_date = fields.Date.to_date("2026-10-05")

        period._finalize_period_internal(  # pylint: disable=protected-access
            end_date,
            "Baja definitiva solicitada por el Socio.",
        )

        self.assertEqual(period.state, "finalized")
        self.assertEqual(period.end_date, end_date)
        self.assertEqual(
            period.end_reason,
            "Baja definitiva solicitada por el Socio.",
        )
        self.assertTrue(period.ended_at)
        self.assertEqual(period.end_user_id, self.env.user)
        self.assertFalse(period.voided_at)
        self.assertFalse(period.void_reason)
        self.assertFalse(period.void_user_id)

    def test_finalize_current_period_requires_reason(self):
        member = self._create_member("002")
        period = self._get_current_period(member)

        with self.assertRaises(ValidationError):
            period._finalize_period_internal(  # pylint: disable=protected-access
                fields.Date.to_date("2026-10-05"),
                "   ",
            )

    def test_voided_period_cannot_be_finalized(self):
        member = self._create_member("003")
        period = self._get_current_period(member)

        period._void_period_internal(  # pylint: disable=protected-access
            "Alta errónea."
        )

        with self.assertRaises(ValidationError):
            period._finalize_period_internal(  # pylint: disable=protected-access
                fields.Date.to_date("2026-10-05"),
                "Intento de baja definitiva.",
            )

    def test_finalization_cannot_predate_period_start(self):
        member = self._create_member(
            "004",
            join_date="2026-10-05",
        )
        period = self._get_current_period(member)

        with self.assertRaises(ValidationError):
            period._finalize_period_internal(  # pylint: disable=protected-access
                fields.Date.to_date("2026-10-04"),
                "Fecha inválida.",
            )
