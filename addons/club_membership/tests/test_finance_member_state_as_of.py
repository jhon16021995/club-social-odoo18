"""TDD: consulta historica para Finanzas, sin movimientos contables."""

from dateutil.relativedelta import relativedelta
from odoo import fields
from odoo.tests import tagged
from odoo.tests.common import TransactionCase


@tagged("post_install", "-at_install")
class TestFinanceMembershipAsOf(TransactionCase):
    def test_month_start_uses_initial_membership_state(self):
        admin = self.env.ref("base.user_admin")
        Partner = self.env["res.partner"].with_user(admin)

        today = fields.Date.context_today(Partner)
        month_start = today.replace(day=1)
        joined = month_start - relativedelta(months=3)
        birthdate = month_start - relativedelta(years=40)

        number = 99720111001
        while Partner.search([("club_id_number", "=", str(number))], limit=1):
            number += 2

        member = Partner.create(
            {
                "name": "Ensayo F11-E consulta historica",
                "company_type": "person",
                "is_company": False,
                "club_person_type": "member",
                "club_id_number": str(number),
                "club_birthdate": fields.Date.to_string(birthdate),
                "club_join_date": joined,
            }
        )

        periods = member.club_membership_period_ids.filtered(
            lambda p: p.state == "current"
        )

        self.assertEqual(len(periods), 1)
        self.assertEqual(periods.start_date, joined)
        self.assertEqual(periods.opening_member_state, "active")

        # TDD RED intencional: la interfaz todavia no existe.
        result = member.get_club_member_state_as_of(month_start)

        self.assertEqual(result, "active")

    def _f11h_month_start(self):
        today = fields.Date.context_today(self.env["res.partner"])
        return today.replace(day=1) - relativedelta(months=1)

    def _f11h_create_member(self, label, cutoff):
        admin = self.env.ref("base.user_admin")
        Partner = self.env["res.partner"].with_user(admin)

        number = 99720118001
        while Partner.search([("club_id_number", "=", str(number))], limit=1):
            number += 2

        member = Partner.create(
            {
                "name": "Ensayo financiero F11-H " + label,
                "company_type": "person",
                "is_company": False,
                "club_person_type": "member",
                "club_member_state": "active",
                "club_id_number": str(number),
                "club_birthdate": fields.Date.to_string(
                    cutoff - relativedelta(years=40)
                ),
                "club_join_date": cutoff - relativedelta(months=3),
            }
        )

        periods = member.club_membership_period_ids.filtered(
            lambda period: period.state == "current"
        )
        self.assertEqual(len(periods), 1)
        self.assertEqual(periods.opening_member_state, "active")
        return member

    def test_absence_before_month_start_changes_historical_state(self):
        cutoff = self._f11h_month_start()
        absence_date = cutoff - relativedelta(days=2)
        member = self._f11h_create_member("ausencia previa", cutoff)

        member.action_mark_club_member_absent(
            "Ausencia efectiva antes del corte mensual",
            effective_date=absence_date,
        )

        member.invalidate_recordset()
        self.assertEqual(member.club_member_state, "absent")
        self.assertEqual(member.club_membership_period_ids.state, "current")

        events = (
            self.env["club.kardex.event"]
            .sudo()
            .search(
                [
                    ("member_id", "=", member.id),
                    ("event_type", "=", "member_state_changed"),
                    ("member_state_to", "=", "absent"),
                ]
            )
        )
        self.assertEqual(len(events), 1)
        self.assertEqual(events.effective_date, absence_date)
        self.assertEqual(events.member_state_from, "active")

        # TDD rojo: aún falta reconstruir el cambio anterior al corte.
        self.assertEqual(
            member.get_club_member_state_as_of(cutoff),
            "absent",
        )

    def test_absence_after_month_start_preserves_historical_state(self):
        cutoff = self._f11h_month_start()
        absence_date = cutoff + relativedelta(days=1)
        member = self._f11h_create_member("ausencia posterior", cutoff)

        member.action_mark_club_member_absent(
            "Ausencia efectiva despues del corte mensual",
            effective_date=absence_date,
        )

        member.invalidate_recordset()
        self.assertEqual(member.club_member_state, "absent")
        self.assertEqual(member.club_membership_period_ids.state, "current")

        events = (
            self.env["club.kardex.event"]
            .sudo()
            .search(
                [
                    ("member_id", "=", member.id),
                    ("event_type", "=", "member_state_changed"),
                    ("member_state_to", "=", "absent"),
                ]
            )
        )
        self.assertEqual(len(events), 1)
        self.assertEqual(events.effective_date, absence_date)

        # Verde esperado: el evento posterior no altera el día 1.
        self.assertEqual(
            member.get_club_member_state_as_of(cutoff),
            "active",
        )

    def test_return_before_month_start_restores_historical_state(self):
        cutoff = self._f11h_month_start()
        absence_date = cutoff - relativedelta(days=4)
        return_date = cutoff - relativedelta(days=1)
        member = self._f11h_create_member("retorno previo", cutoff)

        member.action_mark_club_member_absent(
            "Ausencia historica de ensayo",
            effective_date=absence_date,
        )
        member.action_return_club_member_from_absence(
            "Retorno historico de ensayo",
            effective_date=return_date,
        )

        member.invalidate_recordset()
        self.assertEqual(member.club_member_state, "active")
        self.assertEqual(member.club_membership_period_ids.state, "current")

        events = (
            self.env["club.kardex.event"]
            .sudo()
            .search(
                [
                    ("member_id", "=", member.id),
                    ("event_type", "=", "member_state_changed"),
                ],
                order="id asc",
            )
        )

        self.assertEqual(len(events), 2)
        self.assertEqual(
            events.mapped("member_state_from"),
            ["active", "absent"],
        )
        self.assertEqual(
            events.mapped("member_state_to"),
            ["absent", "active"],
        )
        self.assertEqual(
            events.mapped("effective_date"),
            [absence_date, return_date],
        )

        # TDD rojo: deben aplicarse ambas transiciones cronológicas.
        self.assertEqual(
            member.get_club_member_state_as_of(cutoff),
            "active",
        )

    def _f11k_create_member_with_certificate(self, label, cutoff):
        member = self._f11h_create_member(label, cutoff)
        admin = self.env.ref("base.user_admin")

        certificate = (
            self.env["club.certificate"]
            .with_user(admin)
            .create(
                {
                    "member_id": member.id,
                    "registration_origin": "new",
                    "total_value": 1000,
                    "opening_balance": 1000,
                }
            )
        )

        self.assertEqual(member.club_member_state, "active")
        self.assertEqual(certificate.state, "active")
        return member, certificate

    def test_withdrawal_before_month_start_is_inactive(self):
        cutoff = self._f11h_month_start()
        withdrawal_date = cutoff - relativedelta(days=3)

        member, certificate = self._f11k_create_member_with_certificate(
            "retiro anterior", cutoff
        )

        member.action_withdraw_club_member(
            "Retiro histórico anterior al corte",
            effective_date=withdrawal_date,
        )

        member.invalidate_recordset()
        certificate.invalidate_recordset()

        self.assertEqual(member.club_member_state, "inactive")
        self.assertEqual(certificate.state, "passive")

        events = (
            self.env["club.kardex.event"]
            .sudo()
            .search(
                [
                    ("member_id", "=", member.id),
                    ("event_type", "=", "member_state_changed"),
                ]
            )
        )

        self.assertEqual(len(events), 1)
        self.assertEqual(events.effective_date, withdrawal_date)
        self.assertEqual(events.member_state_from, "active")
        self.assertEqual(events.member_state_to, "inactive")

        # TDD rojo: active -> inactive aún no soportado.
        self.assertEqual(
            member.get_club_member_state_as_of(cutoff),
            "inactive",
        )

    def test_withdrawal_after_month_start_preserves_active(self):
        cutoff = self._f11h_month_start()
        withdrawal_date = cutoff + relativedelta(days=2)

        member, certificate = self._f11k_create_member_with_certificate(
            "retiro posterior", cutoff
        )

        member.action_withdraw_club_member(
            "Retiro posterior al corte",
            effective_date=withdrawal_date,
        )

        member.invalidate_recordset()
        certificate.invalidate_recordset()

        self.assertEqual(member.club_member_state, "inactive")
        self.assertEqual(certificate.state, "passive")

        events = (
            self.env["club.kardex.event"]
            .sudo()
            .search(
                [
                    ("member_id", "=", member.id),
                    ("event_type", "=", "member_state_changed"),
                ]
            )
        )

        self.assertEqual(len(events), 1)
        self.assertEqual(events.effective_date, withdrawal_date)

        # Verde: un retiro posterior no altera el día 1.
        self.assertEqual(
            member.get_club_member_state_as_of(cutoff),
            "active",
        )

    def test_reactivation_before_month_start_restores_active(self):
        cutoff = self._f11h_month_start()
        withdrawal_date = cutoff - relativedelta(days=5)
        reactivation_date = cutoff - relativedelta(days=2)

        member, certificate = self._f11k_create_member_with_certificate(
            "reactivación anterior", cutoff
        )

        member.action_withdraw_club_member(
            "Retiro previo a reactivación histórica",
            effective_date=withdrawal_date,
        )

        member.invalidate_recordset()
        self.assertEqual(member.club_member_state, "inactive")
        self.assertEqual(member.club_state_before_withdrawal, "active")

        member.action_reactivate_club_member(
            "Reactivación histórica antes del corte",
            effective_date=reactivation_date,
        )

        member.invalidate_recordset()
        certificate.invalidate_recordset()

        self.assertEqual(member.club_member_state, "active")
        self.assertEqual(certificate.state, "active")

        events = (
            self.env["club.kardex.event"]
            .sudo()
            .search(
                [
                    ("member_id", "=", member.id),
                    ("event_type", "=", "member_state_changed"),
                ],
                order="effective_date asc, id asc",
            )
        )

        self.assertEqual(len(events), 2)
        self.assertEqual(
            events.mapped("member_state_from"),
            ["active", "inactive"],
        )
        self.assertEqual(
            events.mapped("member_state_to"),
            ["inactive", "active"],
        )
        self.assertEqual(
            events.mapped("effective_date"),
            [withdrawal_date, reactivation_date],
        )

        # TDD rojo: ambas transiciones aún no soportadas.
        self.assertEqual(
            member.get_club_member_state_as_of(cutoff),
            "active",
        )

    def test_reactivation_after_month_start_retains_inactive(self):
        cutoff = self._f11h_month_start()
        withdrawal_date = cutoff - relativedelta(days=3)
        reactivation_date = cutoff + relativedelta(days=2)

        member, certificate = self._f11k_create_member_with_certificate(
            "reactivación posterior", cutoff
        )

        member.action_withdraw_club_member(
            "Retiro anterior al corte",
            effective_date=withdrawal_date,
        )

        member.action_reactivate_club_member(
            "Reactivación posterior al corte",
            effective_date=reactivation_date,
        )

        member.invalidate_recordset()
        certificate.invalidate_recordset()

        self.assertEqual(member.club_member_state, "active")
        self.assertEqual(certificate.state, "active")

        events = (
            self.env["club.kardex.event"]
            .sudo()
            .search(
                [
                    ("member_id", "=", member.id),
                    ("event_type", "=", "member_state_changed"),
                ],
                order="effective_date asc, id asc",
            )
        )

        self.assertEqual(len(events), 2)
        self.assertEqual(
            events.mapped("effective_date"),
            [withdrawal_date, reactivation_date],
        )

        # TDD rojo: al día 1 seguía Pasivo.
        self.assertEqual(
            member.get_club_member_state_as_of(cutoff),
            "inactive",
        )

    def _f11n_temporary_member(self, label, cutoff):
        admin = self.env.ref("base.user_admin")
        Partner = self.env["res.partner"].with_user(admin)
        number = 99720129001

        while Partner.search([("club_id_number", "=", str(number))], limit=1):
            number += 2

        member = Partner.create(
            {
                "name": "Ensayo F11-N " + label,
                "company_type": "person",
                "is_company": False,
                "club_person_type": "member",
                "club_member_state": "temporary",
                "club_id_number": str(number),
                "club_birthdate": fields.Date.to_string(
                    cutoff - relativedelta(years=50)
                ),
                "club_join_date": cutoff - relativedelta(months=3),
            }
        )

        periods = member.club_membership_period_ids.filtered(
            lambda period: period.state == "current"
        )

        self.assertEqual(len(periods), 1)
        self.assertEqual(periods.opening_member_state, "temporary")
        self.assertEqual(member.club_member_state, "temporary")
        return member

    def test_temporary_withdrawal_before_cutoff(self):
        cutoff = self._f11h_month_start()
        withdrawal = cutoff - relativedelta(days=5)
        member = self._f11n_temporary_member("Transitorio retiro", cutoff)

        member.action_withdraw_club_member(
            "Retiro histórico de Transitorio",
            effective_date=withdrawal,
        )
        member.invalidate_recordset()

        self.assertEqual(member.club_member_state, "inactive")
        self.assertEqual(member.club_state_before_withdrawal, "temporary")

        events = (
            self.env["club.kardex.event"]
            .sudo()
            .search(
                [
                    ("member_id", "=", member.id),
                    ("event_type", "=", "member_state_changed"),
                ]
            )
        )

        self.assertEqual(len(events), 1)
        self.assertEqual(events.member_state_from, "temporary")
        self.assertEqual(events.member_state_to, "inactive")
        self.assertEqual(events.effective_date, withdrawal)

        # TDD rojo: temporary -> inactive todavía no soportado.
        self.assertEqual(
            member.get_club_member_state_as_of(cutoff),
            "inactive",
        )

    def test_temporary_reactivation_before_cutoff(self):
        cutoff = self._f11h_month_start()
        withdrawal = cutoff - relativedelta(days=6)
        reactivation = cutoff - relativedelta(days=3)

        member = self._f11n_temporary_member("Transitorio reactivado", cutoff)

        member.action_withdraw_club_member(
            "Retiro previo de Transitorio",
            effective_date=withdrawal,
        )
        member.action_reactivate_club_member(
            "Reactivación de Transitorio",
            effective_date=reactivation,
        )
        member.invalidate_recordset()

        self.assertEqual(member.club_member_state, "temporary")

        events = (
            self.env["club.kardex.event"]
            .sudo()
            .search(
                [
                    ("member_id", "=", member.id),
                    ("event_type", "=", "member_state_changed"),
                ],
                order="effective_date asc, id asc",
            )
        )

        self.assertEqual(len(events), 2)
        self.assertEqual(
            events.mapped("member_state_from"),
            ["temporary", "inactive"],
        )
        self.assertEqual(
            events.mapped("member_state_to"),
            ["inactive", "temporary"],
        )
        self.assertEqual(
            events.mapped("effective_date"),
            [withdrawal, reactivation],
        )

        # TDD rojo: restauración al estado Transitorio.
        self.assertEqual(
            member.get_club_member_state_as_of(cutoff),
            "temporary",
        )

    def test_temporary_two_cycles_before_cutoff(self):
        cutoff = self._f11h_month_start()
        dates = [
            cutoff - relativedelta(days=10),
            cutoff - relativedelta(days=8),
            cutoff - relativedelta(days=6),
            cutoff - relativedelta(days=4),
        ]

        member = self._f11n_temporary_member("Transitorio multiciclo", cutoff)

        member.action_withdraw_club_member(
            "Primer retiro",
            effective_date=dates[0],
            withdrawal_cause="administrative",
        )
        member.action_reactivate_club_member(
            "Primera reactivación",
            effective_date=dates[1],
        )
        member.action_withdraw_club_member(
            "Segundo retiro",
            effective_date=dates[2],
        )
        member.action_reactivate_club_member(
            "Segunda reactivación",
            effective_date=dates[3],
        )

        member.invalidate_recordset()
        self.assertEqual(member.club_member_state, "temporary")

        events = (
            self.env["club.kardex.event"]
            .sudo()
            .search(
                [
                    ("member_id", "=", member.id),
                    ("event_type", "=", "member_state_changed"),
                ],
                order="effective_date asc, id asc",
            )
        )

        self.assertEqual(len(events), 4)
        self.assertEqual(
            events.mapped("member_state_from"),
            ["temporary", "inactive", "temporary", "inactive"],
        )
        self.assertEqual(
            events.mapped("member_state_to"),
            ["inactive", "temporary", "inactive", "temporary"],
        )
        self.assertEqual(events.mapped("effective_date"), dates)

        # TDD rojo: reconstruir los dos ciclos completos.
        self.assertEqual(
            member.get_club_member_state_as_of(cutoff),
            "temporary",
        )

    def test_withdrawal_exactly_on_month_start(self):
        cutoff = self._f11h_month_start()

        member, certificate = self._f11k_create_member_with_certificate(
            "retiro exactamente dia uno", cutoff
        )

        member.action_withdraw_club_member(
            "Retiro efectivo el primer día",
            effective_date=cutoff,
        )
        member.invalidate_recordset()
        certificate.invalidate_recordset()

        self.assertEqual(member.club_member_state, "inactive")
        self.assertEqual(certificate.state, "passive")
        self.assertEqual(
            member.get_club_member_state_as_of(cutoff),
            "inactive",
        )

    def test_absence_exactly_on_month_start(self):
        cutoff = self._f11h_month_start()
        member = self._f11h_create_member("ausencia exactamente dia uno", cutoff)

        member.action_mark_club_member_absent(
            "Ausencia efectiva el día uno",
            effective_date=cutoff,
        )

        member.invalidate_recordset()
        self.assertEqual(member.club_member_state, "absent")
        self.assertEqual(
            member.get_club_member_state_as_of(cutoff),
            "absent",
        )

    def test_same_day_absence_return_is_ambiguous(self):
        from odoo.exceptions import ValidationError

        cutoff = self._f11h_month_start()
        same_day = cutoff - relativedelta(days=2)
        member = self._f11h_create_member("ausencia y retorno mismo dia", cutoff)

        member.action_mark_club_member_absent(
            "Ausencia del mismo día",
            effective_date=same_day,
        )
        member.action_return_club_member_from_absence(
            "Retorno del mismo día",
            effective_date=same_day,
        )

        events = (
            self.env["club.kardex.event"]
            .sudo()
            .search(
                [
                    ("member_id", "=", member.id),
                    ("event_type", "=", "member_state_changed"),
                ],
                order="id asc",
            )
        )

        self.assertEqual(len(events), 2)
        self.assertEqual(
            events.mapped("effective_date"),
            [same_day, same_day],
        )

        # La fecha sola no resuelve el orden intradía.
        with self.assertRaisesRegex(ValidationError, "misma fecha efectiva"):
            member.get_club_member_state_as_of(cutoff)

    def test_date_before_initial_membership_has_no_state(self):
        cutoff = self._f11h_month_start()
        member = self._f11h_create_member("consulta previa al ingreso", cutoff)

        period = member.club_membership_period_ids.filtered(
            lambda item: item.state == "current"
        )
        self.assertEqual(len(period), 1)

        earlier = period.start_date - relativedelta(days=1)

        self.assertFalse(member.get_club_member_state_as_of(earlier))

    def _f11r_member_with_reentry(self, label, cutoff, end_date, reentry_date):
        member = self._f11h_create_member(label, cutoff)

        initial_periods = member.club_membership_period_ids.filtered(
            lambda period: period.state == "current"
        )
        self.assertEqual(len(initial_periods), 1)
        first_period_id = initial_periods.id
        first_start = initial_periods.start_date

        member.action_end_club_membership(
            "Baja definitiva histórica para Finanzas",
            effective_date=end_date,
        )
        member.invalidate_recordset()

        self.assertFalse(member.club_person_type)
        self.assertTrue(member.club_is_former_member)

        member.action_reenter_club_member(
            "Reingreso histórico para Finanzas",
            effective_date=reentry_date,
        )
        member.invalidate_recordset()

        periods = (
            self.env["club.membership.period"]
            .sudo()
            .search(
                [
                    ("person_id", "=", member.id),
                ],
                order="start_date asc, id asc",
            )
        )

        self.assertEqual(len(periods), 2)
        old_period, new_period = periods[0], periods[1]

        self.assertEqual(old_period.id, first_period_id)
        self.assertEqual(old_period.start_date, first_start)
        self.assertEqual(old_period.end_date, end_date)
        self.assertEqual(old_period.state, "finalized")
        self.assertEqual(old_period.opening_member_state, "active")

        self.assertEqual(new_period.origin, "reentry")
        self.assertEqual(new_period.start_date, reentry_date)
        self.assertEqual(new_period.state, "current")
        self.assertEqual(new_period.opening_member_state, "active")

        self.assertEqual(member.club_person_type, "member")
        self.assertEqual(member.club_member_state, "active")

        return member, old_period, new_period

    def test_former_member_old_period_remains_queryable(self):
        cutoff = self._f11h_month_start()
        end_date = cutoff - relativedelta(days=3)
        reentry_date = cutoff + relativedelta(days=3)

        member, old_period, new_period = self._f11r_member_with_reentry(
            "consulta de periodo anterior",
            cutoff,
            end_date,
            reentry_date,
        )

        before_end = end_date - relativedelta(days=1)
        self.assertTrue(old_period.start_date < before_end)
        self.assertTrue(before_end < old_period.end_date)
        self.assertTrue(new_period.start_date > before_end)

        self.assertEqual(
            member.get_club_member_state_as_of(before_end),
            "active",
        )

    def test_gap_between_end_and_reentry_has_no_membership(self):
        cutoff = self._f11h_month_start()
        end_date = cutoff - relativedelta(days=3)
        reentry_date = cutoff + relativedelta(days=3)

        member, old_period, new_period = self._f11r_member_with_reentry(
            "intervalo sin membresia",
            cutoff,
            end_date,
            reentry_date,
        )

        self.assertTrue(old_period.end_date < cutoff)
        self.assertTrue(cutoff < new_period.start_date)

        self.assertFalse(member.get_club_member_state_as_of(cutoff))

    def test_reentry_new_period_is_active_at_cutoff(self):
        cutoff = self._f11h_month_start()
        end_date = cutoff - relativedelta(days=10)
        reentry_date = cutoff - relativedelta(days=3)

        member, old_period, new_period = self._f11r_member_with_reentry(
            "periodo vigente posterior al reingreso",
            cutoff,
            end_date,
            reentry_date,
        )

        self.assertTrue(old_period.end_date < new_period.start_date)
        self.assertTrue(new_period.start_date < cutoff)

        self.assertEqual(
            member.get_club_member_state_as_of(cutoff),
            "active",
        )

    def test_same_day_end_and_reentry_remains_blocked(self):
        from odoo.exceptions import ValidationError

        cutoff = self._f11h_month_start()

        member, old_period, new_period = self._f11r_member_with_reentry(
            "baja y reingreso misma fecha",
            cutoff,
            cutoff,
            cutoff,
        )

        self.assertEqual(old_period.end_date, cutoff)
        self.assertEqual(new_period.start_date, cutoff)

        # No establecer todavía la regla financiera del mismo día.
        # La API debe conservar su rechazo conservador actual.
        with self.assertRaisesRegex(
            ValidationError,
            "coincide con una finalización",
        ):
            member.get_club_member_state_as_of(cutoff)

    def _f11t_inject_test_event(self, member, when, state_from, state_to, label):
        # Exclusivamente dentro del TransactionCase de Odoo.
        # Utiliza el helper institucional; no escribe SQL.
        return (
            self.env["club.kardex.event"]
            .sudo()
            ._log_event(
                member,
                "member_state_changed",
                "Fixture aislada F11-T: " + label,
                origin="manual",
                effective_date=when,
                member_state_from=state_from,
                member_state_to=state_to,
            )
        )

    def test_kardex_without_effective_date_is_rejected(self):
        from odoo.exceptions import ValidationError

        cutoff = self._f11h_month_start()
        member = self._f11h_create_member("Kardex sin fecha efectiva", cutoff)

        event = self._f11t_inject_test_event(
            member,
            False,
            "active",
            "absent",
            "fecha ausente",
        )

        self.assertFalse(event.effective_date)
        self.assertEqual(event.member_state_from, "active")
        self.assertEqual(event.member_state_to, "absent")

        with self.assertRaisesRegex(ValidationError, "sin fecha efectiva"):
            member.get_club_member_state_as_of(cutoff)

    def test_kardex_without_target_state_is_rejected(self):
        from odoo.exceptions import ValidationError

        cutoff = self._f11h_month_start()
        event_date = cutoff - relativedelta(days=2)
        member = self._f11h_create_member("Kardex sin estado de destino", cutoff)

        event = self._f11t_inject_test_event(
            member,
            event_date,
            "active",
            False,
            "destino ausente",
        )

        self.assertEqual(event.effective_date, event_date)
        self.assertEqual(event.member_state_from, "active")
        self.assertFalse(event.member_state_to)

        with self.assertRaisesRegex(
            ValidationError, "sin estados anterior y nuevo completos"
        ):
            member.get_club_member_state_as_of(cutoff)

    def test_kardex_contradictory_transition_is_rejected(self):
        from odoo.exceptions import ValidationError

        cutoff = self._f11h_month_start()
        absence_date = cutoff - relativedelta(days=4)
        contradiction_date = cutoff - relativedelta(days=2)

        member = self._f11h_create_member(
            "Kardex con transición contradictoria", cutoff
        )

        member.action_mark_club_member_absent(
            "Ausencia válida antes de contradicción",
            effective_date=absence_date,
        )

        member.invalidate_recordset()
        self.assertEqual(member.club_member_state, "absent")

        bad_event = self._f11t_inject_test_event(
            member,
            contradiction_date,
            "active",
            "inactive",
            "estado anterior contradictorio",
        )

        self.assertEqual(bad_event.effective_date, contradiction_date)
        self.assertEqual(bad_event.member_state_from, "active")
        self.assertEqual(bad_event.member_state_to, "inactive")

        events = (
            self.env["club.kardex.event"]
            .sudo()
            .search(
                [
                    ("member_id", "=", member.id),
                    ("event_type", "=", "member_state_changed"),
                ]
            )
        )

        self.assertEqual(len(events), 2)

        with self.assertRaisesRegex(
            ValidationError, "no coincide con el estado anterior"
        ):
            member.get_club_member_state_as_of(cutoff)

    def test_retroactive_contradictory_event_is_rejected(self):
        from odoo.exceptions import ValidationError

        cutoff = self._f11h_month_start()
        absence_date = cutoff - relativedelta(days=2)
        retroactive_date = cutoff - relativedelta(days=4)

        member = self._f11h_create_member("Kardex retroactivo contradictorio", cutoff)

        member.action_mark_club_member_absent(
            "Cambio válido de estado a Ausente",
            effective_date=absence_date,
        )

        original_events = (
            self.env["club.kardex.event"]
            .sudo()
            .search(
                [
                    ("member_id", "=", member.id),
                    ("event_type", "=", "member_state_changed"),
                ]
            )
        )

        self.assertEqual(len(original_events), 1)
        self.assertEqual(original_events.effective_date, absence_date)

        # Registrado después, pero con fecha efectiva anterior.
        retroactive_event = self._f11t_inject_test_event(
            member,
            retroactive_date,
            "active",
            "inactive",
            "corrección retroactiva contradictoria",
        )

        self.assertGreater(retroactive_event.id, original_events.id)
        self.assertLess(
            retroactive_event.effective_date,
            original_events.effective_date,
        )

        events = (
            self.env["club.kardex.event"]
            .sudo()
            .search(
                [
                    ("member_id", "=", member.id),
                    ("event_type", "=", "member_state_changed"),
                ],
                order="effective_date asc, id asc",
            )
        )

        self.assertEqual(len(events), 2)
        self.assertEqual(
            events.mapped("effective_date"),
            [retroactive_date, absence_date],
        )

        # Reconstruir por fecha efectiva debe revelar la
        # contradicción, no ocultarla con el orden de registro.
        with self.assertRaisesRegex(
            ValidationError, "no coincide con el estado anterior"
        ):
            member.get_club_member_state_as_of(cutoff)

    def _f12d_create_lifetime_member(self, label, cutoff):
        admin = self.env.ref("base.user_admin")
        Partner = self.env["res.partner"].with_user(admin)

        number = 99720130001
        while Partner.search(
            [
                ("club_id_number", "=", str(number)),
            ],
            limit=1,
        ):
            number += 2

        member = Partner.create(
            {
                "name": "Ensayo F12-D " + label,
                "company_type": "person",
                "is_company": False,
                "club_person_type": "member",
                "club_member_state": "lifetime",
                "club_id_number": str(number),
                "club_birthdate": fields.Date.to_string(
                    cutoff - relativedelta(years=65)
                ),
                "club_join_date": (cutoff - relativedelta(years=5)),
                "club_ordinary_contributions_historical_paid": 360,
            }
        )

        self.assertEqual(
            member.club_member_state,
            "lifetime",
        )
        self.assertEqual(
            member.club_ordinary_contributions_paid_total,
            360,
        )
        self.assertTrue(member.club_lifetime_eligible)

        periods = member.club_membership_period_ids.filtered(
            lambda period: period.state == "current"
        )

        self.assertEqual(len(periods), 1)
        self.assertEqual(
            periods.opening_member_state,
            "lifetime",
        )
        self.assertTrue(periods.start_date < cutoff)

        return member

    def test_lifetime_opening_state_at_cutoff(self):
        cutoff = self._f11h_month_start()

        member = self._f12d_create_lifetime_member(
            "Vitalicio desde apertura",
            cutoff,
        )

        self.assertEqual(
            member.get_club_member_state_as_of(cutoff),
            "lifetime",
        )

    def test_lifetime_withdrawal_before_cutoff(self):
        cutoff = self._f11h_month_start()
        withdrawal_date = cutoff - relativedelta(days=8)

        member = self._f12d_create_lifetime_member(
            "Vitalicio retirado",
            cutoff,
        )

        member.action_withdraw_club_member(
            "Retiro administrativo de Vitalicio para TDD",
            effective_date=withdrawal_date,
            withdrawal_cause="administrative",
        )

        member.invalidate_recordset()

        self.assertEqual(
            member.club_member_state,
            "inactive",
        )
        self.assertEqual(
            member.club_state_before_withdrawal,
            "lifetime",
        )

        # TDD rojo: falta reconstruir lifetime -> inactive.
        self.assertEqual(
            member.get_club_member_state_as_of(cutoff),
            "inactive",
        )

    def test_lifetime_reactivation_before_cutoff(self):
        cutoff = self._f11h_month_start()
        withdrawal_date = cutoff - relativedelta(days=10)
        reactivation_date = cutoff - relativedelta(days=5)

        member = self._f12d_create_lifetime_member(
            "Vitalicio retirado y reactivado",
            cutoff,
        )

        member.action_withdraw_club_member(
            "Primer cambio institucional del Vitalicio",
            effective_date=withdrawal_date,
            withdrawal_cause="administrative",
        )

        member.invalidate_recordset()

        self.assertEqual(
            member.club_member_state,
            "inactive",
        )
        self.assertEqual(
            member.club_state_before_withdrawal,
            "lifetime",
        )

        member.action_reactivate_club_member(
            "Restauración institucional del Vitalicio",
            effective_date=reactivation_date,
        )

        member.invalidate_recordset()

        self.assertEqual(
            member.club_member_state,
            "lifetime",
        )
        self.assertFalse(member.club_state_before_withdrawal)

        # TDD rojo: faltan las dos transiciones.
        self.assertEqual(
            member.get_club_member_state_as_of(cutoff),
            "lifetime",
        )
