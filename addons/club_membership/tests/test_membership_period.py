from odoo.exceptions import AccessError, ValidationError
from odoo.tests import TransactionCase, tagged


@tagged("post_install", "-at_install")
class TestMembershipPeriod(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()

        cls.Period = cls.env["club.membership.period"]

        cls.person = cls.env["res.partner"].create(
            {
                "name": "Persona prueba período de membresía",
                "company_type": "person",
                "is_company": False,
            }
        )

    def _create_period(self, **values):
        vals = {
            "person_id": self.person.id,
            "start_date": "2020-01-01",
            "origin": "initial",
            "member_code": "1234567",
        }
        vals.update(values)

        # Este helper protegido se invoca intencionalmente para probar
        # la API interna del proceso controlado de membresía.
        # pylint: disable=protected-access
        period = self.Period._create_period_internal(vals)
        # pylint: enable=protected-access
        return period

    def test_direct_creation_is_blocked(self):
        with self.assertRaises(AccessError):
            self.Period.create(
                {
                    "person_id": self.person.id,
                    "start_date": "2020-01-01",
                }
            )

    def test_fake_context_token_does_not_bypass_creation(self):
        with self.assertRaises(AccessError):
            self.Period.with_context(club_membership_period_internal_token=True).create(
                {
                    "person_id": self.person.id,
                    "start_date": "2020-01-01",
                }
            )

    def test_internal_creation_builds_current_period(self):
        period = self._create_period()

        self.assertEqual(period.person_id, self.person)
        self.assertEqual(period.state, "current")
        self.assertFalse(period.end_date)
        self.assertEqual(period.member_code, "1234567")

    def test_end_date_before_start_date_is_rejected(self):
        with self.assertRaises(ValidationError):
            self._create_period(
                start_date="2020-01-10",
                end_date="2020-01-09",
            )

    def test_only_one_current_period_per_person(self):
        self._create_period()

        with self.assertRaises(ValidationError):
            self._create_period(
                start_date="2022-01-01",
                origin="reentry",
            )

    def test_finalized_period_allows_new_current_period(self):
        old_period = self._create_period()

        # Este helper protegido se invoca intencionalmente para probar
        # la modificación interna controlada del período.
        # pylint: disable=protected-access
        old_period._write_period_internal(
            {
                "end_date": "2021-12-31",
                "end_reason": "Finalización histórica de prueba",
            }
        )
        # pylint: enable=protected-access

        new_period = self._create_period(
            start_date="2022-01-01",
            origin="reentry",
        )

        self.assertEqual(old_period.state, "finalized")
        self.assertEqual(new_period.state, "current")

    def test_direct_write_is_blocked(self):
        period = self._create_period()

        with self.assertRaises(AccessError):
            period.write(
                {
                    "end_date": "2021-12-31",
                }
            )

    def _void_period(self, period, reason="Alta errónea de prueba"):
        # Este helper protegido se invoca intencionalmente para probar
        # el proceso interno controlado de anulación del período.
        # pylint: disable=protected-access
        result = period._void_period_internal(reason)
        # pylint: enable=protected-access
        return result

    def test_voided_period_is_distinct_from_finalized(self):
        period = self._create_period()

        self._void_period(
            period,
            reason="Registro de Socio creado por error",
        )

        period.invalidate_recordset()

        self.assertEqual(period.state, "voided")
        self.assertFalse(period.end_date)
        self.assertEqual(
            period.void_reason,
            "Registro de Socio creado por error",
        )
        self.assertTrue(period.voided_at)
        self.assertEqual(period.void_user_id, self.env.user)

    def test_voided_period_allows_new_initial_period(self):
        old_period = self._create_period()

        self._void_period(old_period)

        new_period = self._create_period(
            start_date="2022-01-01",
            origin="initial",
        )

        old_period.invalidate_recordset()
        new_period.invalidate_recordset()

        self.assertEqual(old_period.state, "voided")
        self.assertEqual(new_period.state, "current")
        self.assertEqual(new_period.origin, "initial")

    def test_void_period_requires_reason(self):
        period = self._create_period()

        with self.assertRaises(ValidationError):
            self._void_period(period, reason="   ")

        period.invalidate_recordset()

        self.assertEqual(period.state, "current")
        self.assertFalse(period.voided_at)

    def test_finalized_period_cannot_be_voided(self):
        period = self._create_period()

        # Este helper protegido se invoca intencionalmente para preparar
        # un período histórico finalizado.
        # pylint: disable=protected-access
        period._write_period_internal(
            {
                "end_date": "2021-12-31",
                "end_reason": "Finalización histórica de prueba",
            }
        )
        # pylint: enable=protected-access

        with self.assertRaises(ValidationError):
            self._void_period(
                period,
                reason="Intento inválido de anulación",
            )

        period.invalidate_recordset()

        self.assertEqual(period.state, "finalized")
        self.assertFalse(period.voided_at)

    def test_fake_context_token_does_not_bypass_write(self):
        period = self._create_period()

        with self.assertRaises(AccessError):
            period.with_context(club_membership_period_internal_token=True).write(
                {
                    "end_date": "2021-12-31",
                }
            )

    def test_new_member_creation_builds_initial_current_period(self):
        member = self.env["res.partner"].create(
            {
                "name": "Socio integración período inicial",
                "company_type": "person",
                "is_company": False,
                "club_person_type": "member",
                "club_id_number": "99890000101",
                "club_birthdate": "1985-01-15",
                "club_join_date": "2024-02-01",
            }
        )

        periods = self.Period.search(
            [
                ("person_id", "=", member.id),
            ]
        )

        self.assertEqual(len(periods), 1)
        self.assertEqual(periods.state, "current")
        self.assertEqual(periods.origin, "initial")
        self.assertEqual(periods.start_date, member.club_join_date)
        self.assertEqual(periods.member_code, member.club_member_code)

    def test_beneficiary_conversion_builds_initial_current_period(self):
        admin = self.env.ref("base.user_admin")
        Partner = self.env["res.partner"].with_user(admin)
        Beneficiary = self.env["club.beneficiary"].with_user(admin)

        holder = Partner.create(
            {
                "name": "Socio titular conversión período",
                "company_type": "person",
                "is_company": False,
                "club_person_type": "member",
                "club_id_number": "99890000201",
                "club_birthdate": "1980-01-15",
            }
        )

        person = Partner.create(
            {
                "name": "Beneficiario conversión período",
                "company_type": "person",
                "is_company": False,
                "club_id_number": "99890000202",
                "club_birthdate": "1990-01-15",
            }
        )

        beneficiary = Beneficiary.create(
            {
                "person_id": person.id,
                "member_id": holder.id,
                "relationship": "spouse",
                "special_condition": "none",
            }
        )

        beneficiary.action_convert_to_member()

        person.invalidate_recordset()

        periods = self.Period.search(
            [
                ("person_id", "=", person.id),
            ]
        )

        self.assertEqual(len(periods), 1)
        self.assertEqual(periods.state, "current")
        self.assertEqual(periods.origin, "initial")
        self.assertEqual(periods.start_date, person.club_join_date)
        self.assertEqual(periods.member_code, person.club_member_code)
