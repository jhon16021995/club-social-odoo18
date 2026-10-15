"""Contrato TDD del Socio Transitorio.

Escenarios iniciales. No representan aprobación
ni ejecución de tests hasta la corrida controlada.
"""

from dateutil.relativedelta import relativedelta
from odoo import fields
from odoo.exceptions import ValidationError
from odoo.tests.common import TransactionCase


class TestTemporaryMemberContract(TransactionCase):
    """Reglas institucionales para la modalidad Transitorio."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        admin = cls.env.ref("base.user_admin")
        cls.Partner = cls.env["res.partner"].with_user(admin)

    def _member_values(self, *, company=False, paid=0):
        today = fields.Date.context_today(self.Partner)
        number = 99720404001

        while self.Partner.search(
            [
                ("club_id_number", "=", str(number)),
            ],
            limit=1,
        ):
            number += 2

        return {
            "name": "Ensayo TR-04 Transitorio",
            "company_type": ("company" if company else "person"),
            "is_company": company,
            "club_person_type": "member",
            "club_member_state": "temporary",
            "club_id_number": str(number),
            "club_birthdate": (today - relativedelta(years=60)),
            "club_join_date": (today - relativedelta(months=3)),
            "club_ordinary_contributions_historical_paid": paid,
        }

    def _tr15_certificate_values(self, member, state=None):
        """Valores de prueba para Certificado Patrimonial."""
        values = {
            "member_id": member.id,
            "registration_origin": "new",
            "total_value": 1000.0,
            "opening_balance": 1000.0,
        }
        if state is not None:
            values["state"] = state
        return values

    def _tr21_check_roundtrip(self, *, company):
        """RET/REA Transitorio sin alterar identidad ni periodo."""
        today = fields.Date.context_today(self.Partner)
        values = self._member_values(company=company)

        if company:
            values.pop("club_birthdate", None)

        member = self.Partner.create(values)

        admin = self.env.ref("base.user_admin")
        Period = self.env["club.membership.period"].with_user(admin)

        def member_periods():
            return Period.search(
                [("person_id", "=", member.id)],
                order="id",
            )

        initial_periods = member_periods()
        self.assertEqual(len(initial_periods), 1)

        initial_period_ids = initial_periods.ids
        initial_join_date = member.club_join_date
        initial_member_code = member.club_member_code
        initial_id_number = member.club_id_number

        self.assertEqual(member.club_member_state, "temporary")
        self.assertFalse(
            member.club_certificate_ids.filtered(
                lambda certificate: certificate.state == "active"
            )
        )

        member.action_withdraw_club_member(
            "RET Transitorio de prueba",
            effective_date=today,
        )

        member.invalidate_recordset()

        self.assertEqual(member.club_member_state, "inactive")
        self.assertEqual(
            member.club_state_before_withdrawal,
            "temporary",
        )
        self.assertEqual(member.club_last_withdrawal_date, today)
        self.assertEqual(member_periods().ids, initial_period_ids)

        member.action_reactivate_club_member(
            "REA Transitorio de prueba",
            effective_date=today,
        )

        member.invalidate_recordset()

        self.assertEqual(member.club_member_state, "temporary")
        self.assertFalse(member.club_state_before_withdrawal)
        self.assertEqual(
            member.club_last_reactivation_date,
            today,
        )
        self.assertEqual(member.club_join_date, initial_join_date)
        self.assertEqual(member.club_member_code, initial_member_code)
        self.assertEqual(member.club_id_number, initial_id_number)
        self.assertEqual(member.is_company, company)
        self.assertEqual(member_periods().ids, initial_period_ids)

        self.assertFalse(
            member.club_certificate_ids.filtered(
                lambda certificate: certificate.state == "active"
            )
        )

    def _tr24_create_company(self):
        values = self._member_values(company=True)
        values.pop("club_birthdate", None)
        return self.Partner.create(values)

    def _tr24_create_worker(self, company):
        today = fields.Date.context_today(self.Partner)
        number = 99720408001

        while self.Partner.search(
            [
                ("club_id_number", "=", str(number)),
            ],
            limit=1,
        ):
            number += 2

        worker = self.Partner.create(
            {
                "name": "Trabajador Empresa Transitoria TR-24",
                "company_type": "person",
                "is_company": False,
                "club_id_number": str(number),
                "club_birthdate": today - relativedelta(years=35),
            }
        )

        beneficiary = (
            self.env["club.beneficiary"]
            .with_user(self.env.ref("base.user_admin"))
            .create(
                {
                    "person_id": worker.id,
                    "member_id": company.id,
                    "relationship": "worker",
                    "special_condition": "none",
                }
            )
        )

        return worker, beneficiary

    def _tr28_check_rea_rejects_corrupt_legacy_certificate(self, *, company):
        """Simular certificado pasivo con marca RET incoherente, SOLO EN TEST.

        El SQL manipula un certificado sintético en la transacción de pruebas
        de una BASE TEMPORAL CLONADA; jamás toca el histórico original.
        """
        today = fields.Date.context_today(self.Partner)
        vals = self._member_values(company=company)
        if company:
            vals.pop("club_birthdate", None)
        member = self.Partner.create(vals)

        Certificate = self.env["club.certificate"].with_user(
            self.env.ref("base.user_admin")
        )
        historical = Certificate.create(
            {
                "member_id": member.id,
                "registration_origin": "new",
                "total_value": 1000.0,
                "opening_balance": 1000.0,
                "state": "transferred",
            }
        )

        self.assertEqual(member.club_member_state, "temporary")
        self.assertEqual(historical.state, "transferred")

        member.action_withdraw_club_member(
            "RET antes de auditoría patrimonial TR-28",
            effective_date=today,
        )
        member.invalidate_recordset()
        historical.invalidate_recordset()

        self.assertEqual(member.club_member_state, "inactive")
        self.assertEqual(member.club_state_before_withdrawal, "temporary")
        self.assertEqual(historical.state, "transferred")

        # SOLO TEST: representa datos históricos cargados inconsistentemente.
        # No es un proceso funcional ni autoriza F-TR-05.
        self.env.cr.execute(
            "UPDATE club_certificate "
            "SET state = %s, passive_by_member_withdrawal = %s "
            "WHERE id = %s",
            ["passive", True, historical.id],
        )
        historical.invalidate_recordset()
        member.invalidate_recordset(["club_certificate_ids"])

        self.assertEqual(historical.state, "passive")
        self.assertTrue(historical.passive_by_member_withdrawal)
        self.assertFalse(
            member.club_certificate_ids.filtered(lambda cert: cert.state == "active")
        )

        # Contrato esperado: REA debe detectar la incoherencia y NEGARSE.
        # La savepoint revierte cualquier intento de restauración parcial.
        with (
            self.env.cr.savepoint(),
            self.assertRaisesRegex(ValidationError, r"(?i)transitori"),
        ):
            member.action_reactivate_club_member(
                "REA TR-28 debe rechazar legado patrimonial incoherente",
                effective_date=today,
            )

        member.invalidate_recordset()
        historical.invalidate_recordset()
        self.assertEqual(member.club_member_state, "inactive")
        self.assertEqual(member.club_state_before_withdrawal, "temporary")
        self.assertEqual(historical.state, "passive")
        self.assertTrue(historical.passive_by_member_withdrawal)
        self.assertFalse(
            member.club_certificate_ids.filtered(lambda cert: cert.state == "active")
        )

    def test_temporary_person_rea_rejects_corrupt_legacy_passive_certificate(self):
        """Transitorio natural no recupera Certificado activo por REA."""
        self._tr28_check_rea_rejects_corrupt_legacy_certificate(company=False)

    def test_temporary_company_rea_rejects_corrupt_legacy_passive_certificate(self):
        """Empresa Transitoria tampoco recupera Certificado activo por REA."""
        self._tr28_check_rea_rejects_corrupt_legacy_certificate(company=True)

    def test_temporary_company_worker_ret_rea_roundtrip(self):
        """RET bloquea al Trabajador y REA lo restaura."""
        today = fields.Date.context_today(self.Partner)
        company = self._tr24_create_company()
        worker, beneficiary = self._tr24_create_worker(company)

        self.assertEqual(beneficiary.person_id, worker)
        self.assertEqual(beneficiary.member_id, company)
        self.assertEqual(beneficiary.relationship, "worker")
        self.assertEqual(beneficiary.state, "active")
        self.assertFalse(beneficiary.blocked_by_member_withdrawal)

        company.action_withdraw_club_member(
            "RET TR-24 de Empresa Transitoria",
            effective_date=today,
        )

        company.invalidate_recordset()
        beneficiary.invalidate_recordset()

        self.assertEqual(company.club_member_state, "inactive")
        self.assertEqual(
            company.club_state_before_withdrawal,
            "temporary",
        )
        self.assertEqual(beneficiary.state, "blocked")
        self.assertTrue(beneficiary.blocked_by_member_withdrawal)
        self.assertIn(
            "RET TR-24",
            beneficiary.block_reason or "",
        )

        company.action_reactivate_club_member(
            "REA TR-24 de Empresa Transitoria",
            effective_date=today,
        )

        company.invalidate_recordset()
        beneficiary.invalidate_recordset()

        self.assertEqual(company.club_member_state, "temporary")
        self.assertEqual(beneficiary.state, "active")
        self.assertFalse(beneficiary.blocked_by_member_withdrawal)
        self.assertEqual(beneficiary.person_id, worker)
        self.assertEqual(beneficiary.member_id, company)
        self.assertFalse(
            company.club_certificate_ids.filtered(
                lambda certificate: certificate.state == "active"
            )
        )

    def test_temporary_company_admin_blocked_worker_stays_blocked(self):
        """REA no debe desbloquear una sanción administrativa."""
        today = fields.Date.context_today(self.Partner)
        company = self._tr24_create_company()
        _worker, beneficiary = self._tr24_create_worker(company)

        reason = "Bloqueo administrativo independiente TR-24"
        beneficiary.write(
            {
                "state": "blocked",
                "block_reason": reason,
            }
        )

        beneficiary.invalidate_recordset()
        self.assertEqual(beneficiary.state, "blocked")
        self.assertFalse(beneficiary.blocked_by_member_withdrawal)

        company.action_withdraw_club_member(
            "RET TR-24 con bloqueo administrativo",
            effective_date=today,
        )

        beneficiary.invalidate_recordset()
        self.assertEqual(beneficiary.state, "blocked")
        self.assertFalse(beneficiary.blocked_by_member_withdrawal)
        self.assertEqual(beneficiary.block_reason, reason)

        company.action_reactivate_club_member(
            "REA TR-24 respeta bloqueo administrativo",
            effective_date=today,
        )

        company.invalidate_recordset()
        beneficiary.invalidate_recordset()

        self.assertEqual(company.club_member_state, "temporary")
        self.assertEqual(beneficiary.state, "blocked")
        self.assertFalse(beneficiary.blocked_by_member_withdrawal)
        self.assertEqual(beneficiary.block_reason, reason)

    def test_temporary_company_finalized_worker_stays_finalized(self):
        """REA no revive vínculos laborales finalizados."""
        today = fields.Date.context_today(self.Partner)
        company = self._tr24_create_company()
        _worker, beneficiary = self._tr24_create_worker(company)

        beneficiary.finalize_link(
            end_date=today,
            reason="Finalización laboral previa al retiro TR-24",
        )

        beneficiary.invalidate_recordset()
        self.assertEqual(beneficiary.state, "finalized")

        company.action_withdraw_club_member(
            "RET TR-24 con vínculo finalizado",
            effective_date=today,
        )

        beneficiary.invalidate_recordset()
        self.assertEqual(beneficiary.state, "finalized")
        self.assertFalse(beneficiary.blocked_by_member_withdrawal)

        company.action_reactivate_club_member(
            "REA TR-24 con vínculo finalizado",
            effective_date=today,
        )

        company.invalidate_recordset()
        beneficiary.invalidate_recordset()

        self.assertEqual(company.club_member_state, "temporary")
        self.assertEqual(beneficiary.state, "finalized")
        self.assertFalse(beneficiary.blocked_by_member_withdrawal)

    def test_temporary_company_worker_two_ret_rea_cycles(self):
        """El Trabajador resiste dos ciclos RET/REA sucesivos."""
        today = fields.Date.context_today(self.Partner)
        company = self._tr24_create_company()
        _worker, beneficiary = self._tr24_create_worker(company)

        Period = self.env["club.membership.period"].with_user(
            self.env.ref("base.user_admin")
        )

        def period_ids():
            return Period.search(
                [
                    ("person_id", "=", company.id),
                ],
                order="id",
            ).ids

        original_periods = period_ids()
        self.assertEqual(len(original_periods), 1)

        for cycle in (1, 2):
            company.action_withdraw_club_member(
                f"RET TR-24 ciclo {cycle}",
                effective_date=today,
            )

            company.invalidate_recordset()
            beneficiary.invalidate_recordset()

            self.assertEqual(company.club_member_state, "inactive")
            self.assertEqual(beneficiary.state, "blocked")
            self.assertTrue(beneficiary.blocked_by_member_withdrawal)

            company.action_reactivate_club_member(
                f"REA TR-24 ciclo {cycle}",
                effective_date=today,
            )

            company.invalidate_recordset()
            beneficiary.invalidate_recordset()

            self.assertEqual(company.club_member_state, "temporary")
            self.assertEqual(beneficiary.state, "active")
            self.assertFalse(beneficiary.blocked_by_member_withdrawal)
            self.assertEqual(period_ids(), original_periods)

        self.assertFalse(
            company.club_certificate_ids.filtered(
                lambda certificate: certificate.state == "active"
            )
        )

    def test_temporary_person_ret_rea_roundtrip(self):
        """Persona Transitoria retorna al mismo estado tras REA."""
        self._tr21_check_roundtrip(company=False)

    def test_temporary_company_ret_rea_roundtrip(self):
        """Empresa Transitoria retorna al mismo estado tras REA."""
        self._tr21_check_roundtrip(company=True)

    def test_temporary_second_withdrawal_rejected(self):
        """No se puede ejecutar dos veces el mismo RET."""
        today = fields.Date.context_today(self.Partner)
        member = self.Partner.create(self._member_values())

        member.action_withdraw_club_member(
            "Primer retiro de Transitorio",
            effective_date=today,
        )

        with (
            self.env.cr.savepoint(),
            self.assertRaisesRegex(ValidationError, r"(?i)pasivo"),
        ):
            member.action_withdraw_club_member(
                "Intento de segundo retiro",
                effective_date=today,
            )

        member.invalidate_recordset()
        self.assertEqual(member.club_member_state, "inactive")
        self.assertEqual(
            member.club_state_before_withdrawal,
            "temporary",
        )

    def test_temporary_rea_without_ret_rejected(self):
        """No se reactiva quien no se encuentra Pasivo."""
        member = self.Partner.create(self._member_values())

        with (
            self.env.cr.savepoint(),
            self.assertRaisesRegex(ValidationError, r"(?i)pasivo"),
        ):
            member.action_reactivate_club_member(
                "REA sin retiro previo",
            )

        member.invalidate_recordset()
        self.assertEqual(member.club_member_state, "temporary")

    def test_temporary_rea_before_withdrawal_rejected(self):
        """REA no puede anteceder al último RET."""
        today = fields.Date.context_today(self.Partner)
        member = self.Partner.create(self._member_values())

        member.action_withdraw_club_member(
            "Retiro para validar fecha",
            effective_date=today,
        )

        with (
            self.env.cr.savepoint(),
            self.assertRaisesRegex(ValidationError, r"(?i)anterior"),
        ):
            member.action_reactivate_club_member(
                "REA con fecha anterior",
                effective_date=today - relativedelta(days=1),
            )

        member.invalidate_recordset()
        self.assertEqual(member.club_member_state, "inactive")
        self.assertEqual(member.club_last_withdrawal_date, today)

    def test_temporary_rea_without_reason_rejected(self):
        """La reactivación exige un motivo documentado."""
        today = fields.Date.context_today(self.Partner)
        member = self.Partner.create(self._member_values())

        member.action_withdraw_club_member(
            "Retiro para validar motivo",
            effective_date=today,
        )

        with (
            self.env.cr.savepoint(),
            self.assertRaisesRegex(ValidationError, r"(?i)motivo"),
        ):
            member.action_reactivate_club_member(
                "   ",
                effective_date=today,
            )

        member.invalidate_recordset()
        self.assertEqual(member.club_member_state, "inactive")
        self.assertEqual(
            member.club_state_before_withdrawal,
            "temporary",
        )

    def test_temporary_person_orm_create_certificate_rejected(self):
        """La creación ORM debe rechazar Certificado activo."""
        member = self.Partner.create(self._member_values())
        Certificate = self.env["club.certificate"].with_user(
            self.env.ref("base.user_admin")
        )

        with (
            self.env.cr.savepoint(),
            self.assertRaisesRegex(ValidationError, r"(?i)transitori"),
        ):
            Certificate.create(self._tr15_certificate_values(member))

        member.invalidate_recordset(["club_certificate_ids"])
        self.assertFalse(
            member.club_certificate_ids.filtered(
                lambda certificate: certificate.state == "active"
            )
        )

    def test_temporary_company_orm_create_certificate_rejected(self):
        """También debe rechazarse para Empresa Transitoria."""
        values = self._member_values(company=True)
        values.pop("club_birthdate", None)
        member = self.Partner.create(values)
        Certificate = self.env["club.certificate"].with_user(
            self.env.ref("base.user_admin")
        )

        with (
            self.env.cr.savepoint(),
            self.assertRaisesRegex(ValidationError, r"(?i)transitori"),
        ):
            Certificate.create(self._tr15_certificate_values(member))

        member.invalidate_recordset(["club_certificate_ids"])
        self.assertFalse(
            member.club_certificate_ids.filtered(
                lambda certificate: certificate.state == "active"
            )
        )

    def test_temporary_person_orm_activate_certificate_rejected(self):
        """No se puede activar un Certificado histórico."""
        member = self.Partner.create(self._member_values())
        Certificate = self.env["club.certificate"].with_user(
            self.env.ref("base.user_admin")
        )
        historical = Certificate.create(
            self._tr15_certificate_values(member, state="transferred")
        )

        self.assertEqual(historical.state, "transferred")

        with (
            self.env.cr.savepoint(),
            self.assertRaisesRegex(ValidationError, r"(?i)transitori"),
        ):
            historical.write({"state": "active"})

        historical.invalidate_recordset()
        self.assertEqual(historical.state, "transferred")

    def test_temporary_company_orm_activate_certificate_rejected(self):
        """Empresa Transitoria tampoco puede reactivarlo."""
        values = self._member_values(company=True)
        values.pop("club_birthdate", None)
        member = self.Partner.create(values)
        Certificate = self.env["club.certificate"].with_user(
            self.env.ref("base.user_admin")
        )
        historical = Certificate.create(
            self._tr15_certificate_values(member, state="transferred")
        )

        self.assertEqual(historical.state, "transferred")

        with (
            self.env.cr.savepoint(),
            self.assertRaisesRegex(ValidationError, r"(?i)transitori"),
        ):
            historical.write({"state": "active"})

        historical.invalidate_recordset()
        self.assertEqual(historical.state, "transferred")

    def test_temporary_can_keep_historical_certificate(self):
        """La restricción no elimina el historial patrimonial."""
        member = self.Partner.create(self._member_values())
        Certificate = self.env["club.certificate"].with_user(
            self.env.ref("base.user_admin")
        )

        historical = Certificate.create(
            self._tr15_certificate_values(member, state="transferred")
        )

        self.assertEqual(historical.member_id, member)
        self.assertEqual(historical.state, "transferred")
        self.assertFalse(
            member.club_certificate_ids.filtered(
                lambda certificate: certificate.state == "active"
            )
        )

    def test_active_member_can_create_active_certificate(self):
        """La protección no debe bloquear al Socio Activo."""
        values = self._member_values()
        values["club_member_state"] = "active"
        member = self.Partner.create(values)
        Certificate = self.env["club.certificate"].with_user(
            self.env.ref("base.user_admin")
        )

        certificate = Certificate.create(self._tr15_certificate_values(member))

        self.assertEqual(member.club_member_state, "active")
        self.assertEqual(certificate.member_id, member)
        self.assertEqual(certificate.state, "active")

    def test_active_with_certificate_direct_temporary_rejected(self):
        """La edición directa no sustituye una conversión autorizada."""
        values = self._member_values()
        values["club_member_state"] = "active"
        member = self.Partner.create(values)
        Certificate = self.env["club.certificate"].with_user(
            self.env.ref("base.user_admin")
        )
        certificate = Certificate.create(self._tr15_certificate_values(member))

        with self.env.cr.savepoint(), self.assertRaises(ValidationError):
            member.write({"club_member_state": "temporary"})

        member.invalidate_recordset()
        certificate.invalidate_recordset()

        self.assertEqual(member.club_member_state, "active")
        self.assertEqual(certificate.state, "active")

    def test_temporary_person_rejects_active_certificate(self):
        """Un Transitorio natural no admite certificado activo."""
        member = self.Partner.create(self._member_values())

        self.assertFalse(
            member.club_certificate_ids.filtered(
                lambda certificate: certificate.state == "active"
            )
        )

        Certificate = self.env["club.certificate"].with_user(
            self.env.ref("base.user_admin")
        )

        with self.assertRaisesRegex(ValidationError, r"(?i)transitori"):
            Certificate._check_active_certificate_create_values(
                [{"member_id": member.id, "state": "active"}]
            )

    def test_temporary_company_rejects_active_certificate(self):
        """Una Empresa Transitoria tampoco admite certificado activo."""
        values = self._member_values(company=True)
        values.pop("club_birthdate", None)

        member = self.Partner.create(values)

        self.assertFalse(
            member.club_certificate_ids.filtered(
                lambda certificate: certificate.state == "active"
            )
        )

        Certificate = self.env["club.certificate"].with_user(
            self.env.ref("base.user_admin")
        )

        with self.assertRaisesRegex(ValidationError, r"(?i)transitori"):
            Certificate._check_active_certificate_create_values(
                [{"member_id": member.id, "state": "active"}]
            )

    def test_temporary_company_is_allowed(self):
        """Empresa puede ser Transitoria sin certificado."""
        values = self._member_values(company=True)
        values.pop("club_birthdate", None)

        company = self.Partner.create(values)

        self.assertTrue(company.is_company)
        self.assertEqual(company.company_type, "company")
        self.assertEqual(company.club_person_type, "member")
        self.assertEqual(company.club_member_state, "temporary")

        current = company.club_membership_period_ids.filtered(
            lambda period: period.state == "current"
        )

        self.assertEqual(len(current), 1)
        self.assertEqual(current.opening_member_state, "temporary")
        self.assertFalse(
            company.club_certificate_ids.filtered(
                lambda certificate: certificate.state == "active"
            )
        )

    def test_temporary_company_cannot_be_absent_or_lifetime(self):
        """Empresa Transitoria no admite Ausente ni Vitalicio."""
        values = self._member_values(company=True)
        values.pop("club_birthdate", None)

        company = self.Partner.create(values)

        with self.assertRaises(ValidationError):
            company.write({"club_member_state": "lifetime"})

        with self.assertRaises(ValidationError):
            company.write({"club_member_state": "absent"})

        today = fields.Date.context_today(company)

        with self.assertRaises(ValidationError):
            company.action_mark_club_member_absent(
                "Prueba empresa transitoria",
                effective_date=today,
            )

        self.assertEqual(company.club_member_state, "temporary")

    def test_temporary_cannot_be_absent_by_direct_write(self):
        """No permitir modificación directa a Ausente."""
        member = self.Partner.create(self._member_values())

        with self.assertRaises(ValidationError):
            member.write(
                {
                    "club_member_state": "absent",
                }
            )

        self.assertEqual(member.club_member_state, "temporary")

    def test_temporary_cannot_mark_absence(self):
        """Rechazar la operación institucional Ausente."""
        member = self.Partner.create(self._member_values())

        today = fields.Date.context_today(member)

        with self.assertRaises(ValidationError):
            member.action_mark_club_member_absent(
                "Prueba de prohibición Transitorio",
                effective_date=today,
            )

        self.assertEqual(member.club_member_state, "temporary")

    def test_temporary_cannot_be_lifetime_by_direct_write(self):
        """Ni edad ni aportes permiten cambio directo."""
        member = self.Partner.create(self._member_values(paid=360))

        with self.assertRaises(ValidationError):
            member.write(
                {
                    "club_member_state": "lifetime",
                }
            )

        self.assertEqual(member.club_member_state, "temporary")

    def test_temporary_preserves_initial_period(self):
        """El período empieza como Transitorio."""
        member = self.Partner.create(self._member_values())

        periods = member.club_membership_period_ids.filtered(
            lambda period: period.state == "current"
        )

        self.assertEqual(member.club_member_state, "temporary")
        self.assertEqual(len(periods), 1)
        self.assertEqual(
            periods.opening_member_state,
            "temporary",
        )
