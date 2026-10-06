from dateutil.relativedelta import relativedelta
from odoo import fields
from odoo.exceptions import AccessError, ValidationError
from odoo.tests import tagged
from odoo.tests.common import TransactionCase, new_test_user


@tagged("post_install", "-at_install")
class TestClientToMemberConversion(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()

        cls.admin = cls.env.ref("base.user_admin")

        cls.Partner = cls.env["res.partner"].with_user(cls.admin)
        cls.Period = cls.env["club.membership.period"].with_user(cls.admin)
        cls.Kardex = cls.env["club.kardex.event"].with_user(cls.admin)

        cls.regular_user = new_test_user(
            cls.env,
            login="club_client_to_member_without_permission",
            groups="base.group_user",
            name="Usuario sin permiso Cliente a Socio",
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

    def test_direct_client_to_member_write_is_blocked(self):
        client = self._create_client(
            "Cliente protección conversión directa",
            99720000100,
        )

        self.assertEqual(client.club_person_type, "client")
        self.assertFalse(client.club_member_code)
        self.assertFalse(
            self.Period.search(
                [("person_id", "=", client.id)],
                limit=1,
            )
        )

        with self.assertRaises(ValidationError):
            client.write(
                {
                    "club_person_type": "member",
                }
            )

        client.invalidate_recordset()

        self.assertEqual(client.club_person_type, "client")
        self.assertFalse(client.club_member_code)
        self.assertFalse(
            self.Period.search(
                [("person_id", "=", client.id)],
                limit=1,
            )
        )

    def test_fake_client_to_member_context_token_cannot_bypass_write(self):
        client = self._create_client(
            "Cliente protección token falso",
            99720000125,
        )

        with self.assertRaises(ValidationError):
            client.with_context(
                club_client_to_member_internal_token=True,
            ).write(
                {
                    "club_person_type": "member",
                }
            )

        client.invalidate_recordset()

        self.assertEqual(client.club_person_type, "client")
        self.assertFalse(client.club_member_code)
        self.assertFalse(
            self.Period.search(
                [("person_id", "=", client.id)],
                limit=1,
            )
        )

    def test_open_conversion_wizard_requires_specific_permission(self):
        client = self._create_client(
            "Cliente wizard sin permiso",
            99720000175,
        )

        with self.assertRaisesRegex(
            AccessError,
            "No tiene permiso para convertir un Cliente en Socio.",
        ):
            client.with_user(
                self.regular_user
            ).action_open_club_client_to_member_wizard()

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

    def test_conversion_requires_specific_permission(self):
        client = self._create_client(
            "Cliente conversión sin permiso",
            99720000150,
        )

        with self.assertRaisesRegex(
            AccessError,
            "No tiene permiso para convertir un Cliente en Socio.",
        ):
            client.with_user(self.regular_user).action_convert_client_to_member()

        client.invalidate_recordset()

        self.assertEqual(client.club_person_type, "client")
        self.assertFalse(client.club_member_code)
        self.assertFalse(
            self.Period.search(
                [("person_id", "=", client.id)],
                limit=1,
            )
        )

    def test_first_time_client_converts_with_initial_period(self):
        client = self._create_client(
            "Cliente primera membresía controlada",
            99720000200,
        )

        client.action_convert_client_to_member()

        client.invalidate_recordset()

        periods = self.Period.search(
            [("person_id", "=", client.id)],
            order="id",
        )

        self.assertEqual(client.club_person_type, "member")
        self.assertEqual(client.club_member_code, client.club_id_number)
        self.assertEqual(client.club_member_state, "active")
        self.assertEqual(client.club_legal_state, "regular")

        self.assertEqual(len(periods), 1)
        self.assertEqual(periods.state, "current")
        self.assertEqual(periods.origin, "initial")
        self.assertEqual(periods.member_code, client.club_member_code)
        self.assertEqual(periods.start_date, client.club_join_date)

    def _prepare_historical_client(self, name, start_number):
        today = fields.Date.context_today(self.Partner)

        member = self.Partner.create(
            {
                "name": name,
                "company_type": "person",
                "is_company": False,
                "club_person_type": "member",
                "club_id_number": self._next_available_id_number(start_number),
                "club_birthdate": "1985-01-01",
                "club_join_date": today - relativedelta(years=5),
            }
        )

        member.action_end_club_membership(
            "Baja definitiva previa a conversión desde Cliente.",
            effective_date=today,
        )

        member.invalidate_recordset()

        member.write(
            {
                "club_person_type": "client",
            }
        )

        member.invalidate_recordset()

        return member, today

    def test_client_with_only_voided_history_converts_as_initial(self):
        today = fields.Date.context_today(self.Partner)

        client = self._create_client(
            "Cliente con historial solo anulado",
            99720000275,
        )

        # Helpers protegidos invocados intencionalmente para preparar
        # un historial técnico de alta errónea ya anulado.
        # pylint: disable=protected-access
        voided_period = self.Period._create_period_internal(
            {
                "person_id": client.id,
                "start_date": today - relativedelta(years=3),
                "origin": "initial",
                "member_code": client.club_id_number,
            }
        )
        voided_period._void_period_internal("Alta histórica registrada por error.")
        # pylint: enable=protected-access

        voided_period.invalidate_recordset()
        client.invalidate_recordset()

        self.assertEqual(client.club_person_type, "client")
        self.assertFalse(client.club_is_former_member)
        self.assertEqual(voided_period.state, "voided")

        self.assertFalse(
            self.Period.search(
                [
                    ("person_id", "=", client.id),
                    ("state", "=", "current"),
                ],
                limit=1,
            )
        )
        self.assertFalse(
            self.Period.search(
                [
                    ("person_id", "=", client.id),
                    ("state", "=", "finalized"),
                ],
                limit=1,
            )
        )

        client.action_convert_client_to_member()
        client.invalidate_recordset()
        voided_period.invalidate_recordset()

        periods = self.Period.search(
            [("person_id", "=", client.id)],
            order="id",
        )

        self.assertEqual(client.club_person_type, "member")
        self.assertEqual(len(periods), 2)

        self.assertEqual(periods[0].id, voided_period.id)
        self.assertEqual(periods[0].state, "voided")

        self.assertEqual(periods[1].state, "current")
        self.assertEqual(periods[1].origin, "initial")
        self.assertEqual(
            periods[1].member_code,
            client.club_member_code,
        )

    def test_client_with_current_membership_period_is_blocked(self):
        today = fields.Date.context_today(self.Partner)

        client = self._create_client(
            "Cliente inconsistente con período vigente",
            99720000280,
        )

        # Fixture técnico intencional para simular datos inconsistentes
        # heredados o cargados fuera del flujo normal.
        # pylint: disable=protected-access
        current_period = self.Period._create_period_internal(
            {
                "person_id": client.id,
                "start_date": today - relativedelta(years=1),
                "origin": "initial",
                "member_code": client.club_id_number,
            }
        )
        # pylint: enable=protected-access

        self.assertEqual(client.club_person_type, "client")
        self.assertEqual(current_period.state, "current")

        with self.assertRaisesRegex(
            ValidationError,
            "La Persona Cliente presenta un período de membresía "
            "vigente y no puede convertirse nuevamente en Socio.",
        ):
            client.action_convert_client_to_member()

        client.invalidate_recordset()
        current_period.invalidate_recordset()

        self.assertEqual(client.club_person_type, "client")
        self.assertEqual(current_period.state, "current")
        self.assertEqual(
            self.Period.search_count(
                [
                    ("person_id", "=", client.id),
                ]
            ),
            1,
        )

    def test_historical_client_reentry_before_last_end_is_blocked(self):
        client, today = self._prepare_historical_client(
            "Cliente histórico con fecha de Reingreso inválida",
            99720000290,
        )

        finalized_period = self.Period.search(
            [
                ("person_id", "=", client.id),
                ("state", "=", "finalized"),
            ],
            limit=1,
        )

        self.assertTrue(finalized_period)
        self.assertEqual(finalized_period.end_date, today)

        with self.assertRaisesRegex(
            ValidationError,
            "La fecha efectiva del Reingreso no puede ser anterior "
            "a la fecha de finalización de la última membresía.",
        ):
            client.action_convert_client_to_member(
                reason="Intento con cronología inválida.",
                effective_date=today - relativedelta(days=1),
            )

        client.invalidate_recordset()
        finalized_period.invalidate_recordset()

        self.assertEqual(client.club_person_type, "client")
        self.assertEqual(finalized_period.state, "finalized")
        self.assertFalse(
            self.Period.search(
                [
                    ("person_id", "=", client.id),
                    ("state", "=", "current"),
                ],
                limit=1,
            )
        )

    def test_historical_client_converts_with_reentry_period(self):
        client, today = self._prepare_historical_client(
            "Cliente con membresía histórica",
            99720000300,
        )

        person_id = client.id
        id_number = client.club_id_number

        periods_before = self.Period.search(
            [("person_id", "=", client.id)],
            order="id",
        )

        self.assertEqual(len(periods_before), 1)
        self.assertEqual(periods_before.state, "finalized")

        finalized_id = periods_before.id
        finalized_end_date = periods_before.end_date
        finalized_end_reason = periods_before.end_reason

        member_created_before = self.Kardex.search_count(
            [
                ("member_id", "=", client.id),
                ("event_type", "=", "member_created"),
            ]
        )

        client.action_convert_client_to_member(
            reason="Conversión controlada de Cliente histórico.",
            effective_date=today,
        )

        client.invalidate_recordset()

        periods = self.Period.search(
            [("person_id", "=", client.id)],
            order="id",
        )

        self.assertEqual(client.id, person_id)
        self.assertEqual(client.club_person_type, "member")
        self.assertEqual(client.club_id_number, id_number)
        self.assertEqual(client.club_member_code, id_number)
        self.assertEqual(client.club_member_state, "active")
        self.assertEqual(client.club_legal_state, "regular")

        self.assertEqual(len(periods), 2)

        finalized_period = periods[0]
        current_period = periods[1]

        self.assertEqual(finalized_period.id, finalized_id)
        self.assertEqual(finalized_period.state, "finalized")
        self.assertEqual(finalized_period.end_date, finalized_end_date)
        self.assertEqual(finalized_period.end_reason, finalized_end_reason)

        self.assertEqual(current_period.state, "current")
        self.assertEqual(current_period.origin, "reentry")
        self.assertEqual(current_period.start_date, today)
        self.assertEqual(current_period.member_code, id_number)

        member_created_after = self.Kardex.search_count(
            [
                ("member_id", "=", client.id),
                ("event_type", "=", "member_created"),
            ]
        )

        reentry_events = self.Kardex.search(
            [
                ("member_id", "=", client.id),
                ("event_type", "=", "membership_reentered"),
            ]
        )

        self.assertEqual(member_created_after, member_created_before)
        self.assertEqual(len(reentry_events), 1)
        self.assertIn(
            "Conversión controlada de Cliente histórico.",
            reentry_events.reason or "",
        )
