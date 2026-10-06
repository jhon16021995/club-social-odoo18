from dateutil.relativedelta import relativedelta
from odoo import fields
from odoo.exceptions import AccessError, ValidationError
from odoo.tests import tagged
from odoo.tests.common import TransactionCase, new_test_user


@tagged("post_install", "-at_install")
class TestMemberDefinitiveEnd(TransactionCase):  # pylint: disable=too-many-public-methods
    @classmethod
    def setUpClass(cls):
        super().setUpClass()

        cls.admin = cls.env.ref("base.user_admin")

        cls.Partner = cls.env["res.partner"].with_user(cls.admin)
        cls.Beneficiary = cls.env["club.beneficiary"].with_user(cls.admin)
        cls.Certificate = cls.env["club.certificate"].with_user(cls.admin)
        cls.Period = cls.env["club.membership.period"].with_user(cls.admin)
        cls.Kardex = cls.env["club.kardex.event"].with_user(cls.admin)

        cls.regular_user = new_test_user(
            cls.env,
            login="club_member_definitive_end_without_permission",
            groups="base.group_user",
            name="Usuario sin permiso de baja definitiva",
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
    def _birthdate_for_age(cls, age):
        today = fields.Date.context_today(cls.Partner)
        return fields.Date.to_string(today - relativedelta(years=age))

    @classmethod
    def _create_member(cls, name, start_number, join_date=False):
        vals = {
            "name": name,
            "company_type": "person",
            "is_company": False,
            "club_person_type": "member",
            "club_id_number": cls._next_available_id_number(start_number),
            "club_birthdate": cls._birthdate_for_age(50),
        }

        if join_date:
            vals["club_join_date"] = join_date

        return cls.Partner.create(vals)

    @classmethod
    def _create_person(cls, name, start_number):
        return cls.Partner.create(
            {
                "name": name,
                "company_type": "person",
                "is_company": False,
                "club_id_number": cls._next_available_id_number(start_number),
                "club_birthdate": cls._birthdate_for_age(30),
            }
        )

    @classmethod
    def _create_certificate(cls, member):
        return cls.Certificate.create(
            {
                "member_id": member.id,
                "registration_origin": "new",
                "total_value": 1000.0,
                "opening_balance": 1000.0,
            }
        )

    @classmethod
    def _create_beneficiary(cls, member, person):
        return cls.Beneficiary.create(
            {
                "person_id": person.id,
                "member_id": member.id,
                "relationship": "spouse",
                "special_condition": "none",
            }
        )

    def _get_single_period(self, member):
        periods = self.Period.search(
            [
                ("person_id", "=", member.id),
            ]
        )
        self.assertEqual(len(periods), 1)
        return periods

    def test_active_member_can_end_membership_definitively(self):
        today = fields.Date.context_today(self.Partner)
        reason = "Finalización definitiva solicitada por el Socio."

        member = self._create_member(
            "Socio baja definitiva activo",
            99600000100,
            join_date=today - relativedelta(years=8),
        )

        original_id_number = member.club_id_number
        period = self._get_single_period(member)

        self.assertEqual(period.state, "current")

        member.action_end_club_membership(
            reason,
            effective_date=today,
        )

        member.invalidate_recordset()
        period.invalidate_recordset()

        self.assertFalse(member.club_person_type)
        self.assertEqual(member.club_id_number, original_id_number)
        self.assertFalse(member.club_member_code)
        self.assertFalse(member.club_join_date)
        self.assertFalse(member.club_member_state)
        self.assertFalse(member.club_legal_state)

        self.assertEqual(period.state, "finalized")
        self.assertEqual(period.end_date, today)
        self.assertEqual(period.end_reason, reason)
        self.assertTrue(period.ended_at)
        self.assertEqual(period.end_user_id, self.admin)

        event = self.Kardex.search(
            [
                ("member_id", "=", member.id),
                ("event_type", "=", "membership_ended"),
            ],
            order="id desc",
            limit=1,
        )

        self.assertTrue(event)
        self.assertIn(reason, event.reason or "")

    def test_passive_member_can_end_membership_definitively(self):
        today = fields.Date.context_today(self.Partner)

        member = self._create_member(
            "Socio baja definitiva pasivo",
            99600000200,
            join_date=today - relativedelta(years=10),
        )

        member.action_withdraw_club_member(
            "Retiro previo a baja definitiva.",
            effective_date=today,
        )

        member.invalidate_recordset()

        self.assertEqual(member.club_member_state, "inactive")
        self.assertTrue(member.club_last_withdrawal_date)
        self.assertTrue(member.club_last_withdrawal_cause)

        member.action_end_club_membership(
            "Cierre definitivo posterior al retiro.",
            effective_date=today,
        )

        member.invalidate_recordset()
        period = self._get_single_period(member)

        self.assertFalse(member.club_person_type)
        self.assertFalse(member.club_member_code)
        self.assertFalse(member.club_join_date)
        self.assertFalse(member.club_member_state)
        self.assertFalse(member.club_legal_state)

        self.assertFalse(member.club_state_before_withdrawal)
        self.assertFalse(member.club_last_withdrawal_date)
        self.assertFalse(member.club_last_withdrawal_cause)
        self.assertFalse(member.club_last_reactivation_date)

        self.assertEqual(period.state, "finalized")
        self.assertEqual(period.end_date, today)

    def test_active_beneficiary_under_member_blocks_definitive_end(self):
        today = fields.Date.context_today(self.Partner)

        member = self._create_member(
            "Socio con beneficiario activo",
            99600000300,
            join_date=today - relativedelta(years=4),
        )

        self._create_beneficiary(
            member,
            self._create_person(
                "Beneficiario activo baja definitiva",
                99600000400,
            ),
        )

        with self.assertRaises(ValidationError):
            member.action_end_club_membership(
                "Intento con Beneficiario activo.",
                effective_date=today,
            )

        period = self._get_single_period(member)

        self.assertEqual(member.club_person_type, "member")
        self.assertEqual(period.state, "current")

    def test_blocked_beneficiary_under_member_blocks_definitive_end(self):
        today = fields.Date.context_today(self.Partner)

        member = self._create_member(
            "Socio con beneficiario bloqueado",
            99600000500,
            join_date=today - relativedelta(years=4),
        )

        beneficiary = self._create_beneficiary(
            member,
            self._create_person(
                "Beneficiario bloqueado baja definitiva",
                99600000600,
            ),
        )

        beneficiary.write(
            {
                "state": "blocked",
                "block_reason": "Bloqueo independiente previo.",
            }
        )

        with self.assertRaises(ValidationError):
            member.action_end_club_membership(
                "Intento con Beneficiario bloqueado.",
                effective_date=today,
            )

        period = self._get_single_period(member)

        self.assertEqual(member.club_person_type, "member")
        self.assertEqual(period.state, "current")

    def test_definitive_end_requires_reason(self):
        today = fields.Date.context_today(self.Partner)

        member = self._create_member(
            "Socio baja sin motivo",
            99600000700,
            join_date=today - relativedelta(years=3),
        )

        with self.assertRaises(ValidationError):
            member.action_end_club_membership(
                "   ",
                effective_date=today,
            )

    def test_definitive_end_rejects_future_date(self):
        today = fields.Date.context_today(self.Partner)

        member = self._create_member(
            "Socio baja fecha futura",
            99600000800,
            join_date=today - relativedelta(years=3),
        )

        with self.assertRaises(ValidationError):
            member.action_end_club_membership(
                "Intento con fecha futura.",
                effective_date=today + relativedelta(days=1),
            )

    def test_definitive_end_requires_specific_permission(self):
        today = fields.Date.context_today(self.Partner)

        member = self._create_member(
            "Socio baja sin permiso",
            99600000900,
            join_date=today - relativedelta(years=3),
        )

        with self.assertRaises(AccessError):
            member.with_user(self.regular_user).action_end_club_membership(
                "Intento sin permiso específico.",
                effective_date=today,
            )

    def test_active_certificate_becomes_passive_on_definitive_end(self):
        today = fields.Date.context_today(self.Partner)

        member = self._create_member(
            "Socio baja definitiva certificado activo",
            99600001000,
            join_date=today - relativedelta(years=5),
        )
        certificate = self._create_certificate(member)

        self.assertEqual(certificate.state, "active")
        self.assertFalse(certificate.passive_by_member_withdrawal)

        member.action_end_club_membership(
            "Baja definitiva con Certificado activo.",
            effective_date=today,
        )

        certificate.invalidate_recordset()

        self.assertEqual(certificate.state, "passive")
        self.assertFalse(certificate.passive_by_member_withdrawal)
        self.assertTrue(certificate.passive_by_membership_end)

    def test_withdrawal_certificate_is_absorbed_by_definitive_end(self):
        today = fields.Date.context_today(self.Partner)

        member = self._create_member(
            "Socio baja definitiva certificado RET",
            99600001100,
            join_date=today - relativedelta(years=6),
        )
        certificate = self._create_certificate(member)

        member.action_withdraw_club_member(
            "Retiro previo a baja definitiva.",
            effective_date=today,
        )

        certificate.invalidate_recordset()

        self.assertEqual(certificate.state, "passive")
        self.assertTrue(certificate.passive_by_member_withdrawal)

        member.action_end_club_membership(
            "Baja definitiva posterior al retiro.",
            effective_date=today,
        )

        certificate.invalidate_recordset()

        self.assertEqual(certificate.state, "passive")
        self.assertFalse(certificate.passive_by_member_withdrawal)
        self.assertTrue(certificate.passive_by_membership_end)

    def test_independently_passive_certificate_is_preserved(self):
        today = fields.Date.context_today(self.Partner)

        member = self._create_member(
            "Socio baja definitiva certificado Pasivo independiente",
            99600001200,
            join_date=today - relativedelta(years=5),
        )
        certificate = self._create_certificate(member)

        certificate.write(
            {
                "state": "passive",
            }
        )

        certificate.invalidate_recordset()

        self.assertEqual(certificate.state, "passive")
        self.assertFalse(certificate.passive_by_member_withdrawal)

        member.action_end_club_membership(
            "Baja definitiva con Certificado Pasivo independiente.",
            effective_date=today,
        )

        certificate.invalidate_recordset()

        self.assertEqual(certificate.state, "passive")
        self.assertFalse(certificate.passive_by_member_withdrawal)
        self.assertFalse(certificate.passive_by_membership_end)

    def test_transferred_certificate_is_preserved(self):
        today = fields.Date.context_today(self.Partner)

        member = self._create_member(
            "Socio baja definitiva certificado transferido",
            99600001300,
            join_date=today - relativedelta(years=5),
        )
        certificate = self._create_certificate(member)

        certificate.write(
            {
                "state": "transferred",
            }
        )

        certificate.invalidate_recordset()

        self.assertEqual(certificate.state, "transferred")

        member.action_end_club_membership(
            "Baja definitiva con Certificado transferido.",
            effective_date=today,
        )

        certificate.invalidate_recordset()

        self.assertEqual(certificate.state, "transferred")
        self.assertFalse(certificate.passive_by_member_withdrawal)
        self.assertFalse(certificate.passive_by_membership_end)

    def test_membership_end_marker_cannot_be_written_directly(self):
        member = self._create_member(
            "Socio protección marcador baja definitiva",
            99600001400,
        )
        certificate = self._create_certificate(member)

        with self.assertRaises(AccessError):
            certificate.write(
                {
                    "passive_by_membership_end": True,
                }
            )

        with self.assertRaises(AccessError):
            certificate.with_context(
                club_certificate_membership_end_internal_token=True,
            ).write(
                {
                    "passive_by_membership_end": True,
                }
            )

    def test_definitive_end_requires_effective_date(self):
        member = self._create_member(
            "Socio baja definitiva sin fecha",
            99600001500,
        )

        with self.assertRaises(ValidationError):
            member.action_end_club_membership(
                "Intento sin fecha efectiva.",
            )

    def test_definitive_end_before_period_start_has_no_side_effects(self):
        today = fields.Date.context_today(self.Partner)
        join_date = today - relativedelta(years=2)

        member = self._create_member(
            "Socio baja definitiva anterior al período",
            99600001600,
            join_date=join_date,
        )
        certificate = self._create_certificate(member)

        period = self.Period.search(
            [
                ("person_id", "=", member.id),
                ("state", "=", "current"),
            ],
            limit=1,
        )
        self.assertTrue(period)

        with self.assertRaises(ValidationError):
            member.action_end_club_membership(
                "Fecha anterior al inicio del período.",
                effective_date=join_date - relativedelta(days=1),
            )

        member.invalidate_recordset()
        certificate.invalidate_recordset()
        period.invalidate_recordset()

        self.assertEqual(member.club_person_type, "member")
        self.assertEqual(member.club_member_state, "active")
        self.assertEqual(period.state, "current")
        self.assertFalse(period.end_date)

        self.assertEqual(certificate.state, "active")
        self.assertFalse(certificate.passive_by_member_withdrawal)
        self.assertFalse(certificate.passive_by_membership_end)

    def test_passive_definitive_end_cannot_predate_withdrawal(self):
        today = fields.Date.context_today(self.Partner)

        member = self._create_member(
            "Socio baja definitiva anterior al RET",
            99600001700,
            join_date=today - relativedelta(years=5),
        )
        certificate = self._create_certificate(member)

        member.action_withdraw_club_member(
            "Retiro previo a prueba cronológica.",
            effective_date=today,
        )

        member.invalidate_recordset()
        certificate.invalidate_recordset()

        self.assertEqual(member.club_member_state, "inactive")
        self.assertEqual(member.club_last_withdrawal_date, today)
        self.assertEqual(certificate.state, "passive")
        self.assertTrue(certificate.passive_by_member_withdrawal)

        with self.assertRaises(ValidationError):
            member.action_end_club_membership(
                "Baja definitiva anterior al último retiro.",
                effective_date=today - relativedelta(days=1),
            )

        member.invalidate_recordset()
        certificate.invalidate_recordset()

        period = self.Period.search(
            [
                ("person_id", "=", member.id),
                ("state", "=", "current"),
            ],
            limit=1,
        )

        self.assertEqual(member.club_person_type, "member")
        self.assertEqual(member.club_member_state, "inactive")
        self.assertEqual(member.club_last_withdrawal_date, today)
        self.assertTrue(period)

        self.assertEqual(certificate.state, "passive")
        self.assertTrue(certificate.passive_by_member_withdrawal)
        self.assertFalse(certificate.passive_by_membership_end)

    def test_definitive_end_cannot_predate_last_reactivation(self):
        today = fields.Date.context_today(self.Partner)
        withdrawal_date = today - relativedelta(days=1)

        member = self._create_member(
            "Socio baja definitiva anterior a REA",
            99600001800,
            join_date=today - relativedelta(years=6),
        )
        certificate = self._create_certificate(member)

        member.action_withdraw_club_member(
            "Retiro previo a reactivación.",
            effective_date=withdrawal_date,
        )

        member.action_reactivate_club_member(
            "Reactivación previa a baja definitiva.",
            effective_date=today,
        )

        member.invalidate_recordset()
        certificate.invalidate_recordset()

        self.assertEqual(member.club_member_state, "active")
        self.assertEqual(member.club_last_reactivation_date, today)
        self.assertEqual(certificate.state, "active")
        self.assertFalse(certificate.passive_by_member_withdrawal)

        with self.assertRaises(ValidationError):
            member.action_end_club_membership(
                "Baja definitiva anterior a la última reactivación.",
                effective_date=withdrawal_date,
            )

        member.invalidate_recordset()
        certificate.invalidate_recordset()

        period = self.Period.search(
            [
                ("person_id", "=", member.id),
                ("state", "=", "current"),
            ],
            limit=1,
        )

        self.assertEqual(member.club_person_type, "member")
        self.assertEqual(member.club_member_state, "active")
        self.assertEqual(member.club_last_reactivation_date, today)
        self.assertTrue(period)

        self.assertEqual(certificate.state, "active")
        self.assertFalse(certificate.passive_by_member_withdrawal)
        self.assertFalse(certificate.passive_by_membership_end)

    def test_direct_member_role_clear_remains_blocked(self):
        member = self._create_member(
            "Socio protección salida directa",
            99600001900,
        )

        with self.assertRaises(ValidationError):
            member.write(
                {
                    "club_person_type": False,
                }
            )

        member.invalidate_recordset()

        self.assertEqual(member.club_person_type, "member")
        self.assertTrue(member.club_member_code)

    def test_fake_membership_end_context_token_cannot_clear_member_role(self):
        member = self._create_member(
            "Socio protección token falso baja definitiva",
            99600002000,
        )

        with self.assertRaises(ValidationError):
            member.with_context(
                club_membership_end_internal_token=True,
            ).write(
                {
                    "club_person_type": False,
                }
            )

        member.invalidate_recordset()

        self.assertEqual(member.club_person_type, "member")
        self.assertTrue(member.club_member_code)

    def test_definitive_end_rejects_non_member(self):
        today = fields.Date.context_today(self.Partner)

        person = self._create_person(
            "Persona no Socio para baja definitiva",
            99600002100,
        )

        self.assertNotEqual(person.club_person_type, "member")

        with self.assertRaises(ValidationError):
            person.action_end_club_membership(
                "Intento de baja definitiva sobre no Socio.",
                effective_date=today,
            )

    def test_definitive_end_rejects_member_without_current_period(self):
        today = fields.Date.context_today(self.Partner)

        member = self._create_member(
            "Socio sin período vigente para baja definitiva",
            99600002200,
            join_date=today - relativedelta(years=4),
        )

        period = self.Period.search(
            [
                ("person_id", "=", member.id),
                ("state", "=", "current"),
            ],
            limit=1,
        )
        self.assertTrue(period)

        period._finalize_period_internal(  # pylint: disable=protected-access
            today,
            "Preparación de inconsistencia controlada para prueba.",
        )

        member.invalidate_recordset()
        period.invalidate_recordset()

        self.assertEqual(member.club_person_type, "member")
        self.assertEqual(period.state, "finalized")
        self.assertFalse(
            self.Period.search(
                [
                    ("person_id", "=", member.id),
                    ("state", "=", "current"),
                ],
                limit=1,
            )
        )

        with self.assertRaises(ValidationError):
            member.action_end_club_membership(
                "Intento sin período vigente.",
                effective_date=today,
            )

        member.invalidate_recordset()

        self.assertEqual(member.club_person_type, "member")

    def test_passive_member_can_end_while_beneficiary_of_another_member(self):
        today = fields.Date.context_today(self.Partner)

        member = self._create_member(
            "Socio Pasivo que también es Beneficiario",
            99600002300,
            join_date=today - relativedelta(years=5),
        )

        member.action_withdraw_club_member(
            "Retiro previo a vínculo como Beneficiario.",
            effective_date=today,
        )

        member.invalidate_recordset()
        self.assertEqual(member.club_member_state, "inactive")

        titular = self._create_member(
            "Socio titular del Ex-Socio Beneficiario",
            99600002400,
            join_date=today - relativedelta(years=4),
        )

        current_link = self._create_beneficiary(
            titular,
            member,
        )

        self.assertEqual(current_link.state, "active")
        self.assertEqual(current_link.person_id, member)

        member.action_end_club_membership(
            "Baja definitiva manteniendo vínculo Beneficiario externo.",
            effective_date=today,
        )

        member.invalidate_recordset()
        current_link.invalidate_recordset()

        self.assertFalse(member.club_person_type)
        self.assertFalse(member.club_member_state)

        self.assertEqual(current_link.state, "active")
        self.assertEqual(current_link.person_id, member)
        self.assertEqual(current_link.member_id, titular)

        finalized_period = self.Period.search(
            [
                ("person_id", "=", member.id),
                ("state", "=", "finalized"),
            ],
            limit=1,
        )
        self.assertTrue(finalized_period)

    def test_definitive_end_creates_exactly_one_membership_ended_event(self):
        today = fields.Date.context_today(self.Partner)

        member = self._create_member(
            "Socio evento único baja definitiva",
            99600002500,
            join_date=today - relativedelta(years=3),
        )

        before_count = self.Kardex.search_count(
            [
                ("member_id", "=", member.id),
                ("event_type", "=", "membership_ended"),
            ]
        )

        member.action_end_club_membership(
            "Baja definitiva para validar evento único.",
            effective_date=today,
        )

        after_count = self.Kardex.search_count(
            [
                ("member_id", "=", member.id),
                ("event_type", "=", "membership_ended"),
            ]
        )

        self.assertEqual(after_count, before_count + 1)

    def test_membership_end_open_action_supports_active_and_passive_members(self):
        today = fields.Date.context_today(self.Partner)

        active_member = self._create_member(
            "Socio activo apertura baja definitiva",
            99600002600,
            join_date=today - relativedelta(years=3),
        )

        active_action = active_member.action_open_club_membership_end_wizard()

        self.assertEqual(
            active_action["res_model"],
            "club.membership.end.wizard",
        )
        self.assertEqual(active_action["target"], "new")
        self.assertEqual(
            active_action["context"]["default_member_id"],
            active_member.id,
        )
        self.assertNotIn(
            "default_effective_date",
            active_action["context"],
        )

        passive_member = self._create_member(
            "Socio Pasivo apertura baja definitiva",
            99600002700,
            join_date=today - relativedelta(years=4),
        )

        passive_member.action_withdraw_club_member(
            "Retiro previo a apertura de baja definitiva.",
            effective_date=today,
        )

        passive_member.invalidate_recordset()
        self.assertEqual(passive_member.club_member_state, "inactive")

        passive_action = passive_member.action_open_club_membership_end_wizard()

        self.assertEqual(
            passive_action["res_model"],
            "club.membership.end.wizard",
        )
        self.assertEqual(passive_action["target"], "new")
        self.assertEqual(
            passive_action["context"]["default_member_id"],
            passive_member.id,
        )
        self.assertNotIn(
            "default_effective_date",
            passive_action["context"],
        )

    def test_membership_end_open_action_requires_permission_and_member_role(self):
        member = self._create_member(
            "Socio apertura baja definitiva sin permiso",
            99600002800,
        )

        with self.assertRaises(AccessError):
            member.with_user(self.regular_user).action_open_club_membership_end_wizard()

        person = self._create_person(
            "Persona no Socio apertura baja definitiva",
            99600002900,
        )

        with self.assertRaises(ValidationError):
            person.action_open_club_membership_end_wizard()

    def test_membership_end_wizard_has_no_default_date_and_shows_impact(self):
        today = fields.Date.context_today(self.Partner)

        member = self._create_member(
            "Socio wizard baja definitiva impacto",
            99600003000,
            join_date=today - relativedelta(years=5),
        )
        certificate = self._create_certificate(member)

        active_beneficiary = self._create_beneficiary(
            member,
            self._create_person(
                "Beneficiario activo wizard baja definitiva",
                99600003100,
            ),
        )

        blocked_beneficiary = self._create_beneficiary(
            member,
            self._create_person(
                "Beneficiario bloqueado wizard baja definitiva",
                99600003200,
            ),
        )
        blocked_beneficiary.write(
            {
                "state": "blocked",
                "block_reason": "Bloqueo independiente para prueba del wizard.",
            }
        )

        Wizard = self.env["club.membership.end.wizard"].with_user(self.admin)

        defaults = Wizard.with_context(
            default_member_id=member.id,
        ).default_get(
            [
                "member_id",
                "effective_date",
            ]
        )

        self.assertEqual(defaults.get("member_id"), member.id)
        self.assertFalse(defaults.get("effective_date"))
        self.assertTrue(Wizard._fields["effective_date"].required)

        wizard = Wizard.create(
            {
                "member_id": member.id,
                "effective_date": today,
                "reason": "Inspección del impacto antes de confirmar.",
            }
        )

        self.assertEqual(wizard.current_member_state, "active")
        self.assertEqual(wizard.certificate_id, certificate)
        self.assertEqual(wizard.certificate_state, "active")
        self.assertEqual(wizard.active_beneficiary_count, 1)
        self.assertEqual(wizard.blocked_beneficiary_count, 1)

        self.assertEqual(active_beneficiary.state, "active")
        self.assertEqual(blocked_beneficiary.state, "blocked")

    def test_membership_end_wizard_rejects_blank_reason(self):
        today = fields.Date.context_today(self.Partner)

        member = self._create_member(
            "Socio wizard baja definitiva sin motivo",
            99600003300,
            join_date=today - relativedelta(years=2),
        )

        Wizard = self.env["club.membership.end.wizard"].with_user(self.admin)

        wizard = Wizard.create(
            {
                "member_id": member.id,
                "effective_date": today,
                "reason": "   ",
            }
        )

        with self.assertRaises(ValidationError):
            wizard.action_confirm()

        member.invalidate_recordset()
        self.assertEqual(member.club_person_type, "member")

    def test_membership_end_wizard_executes_controlled_process(self):
        today = fields.Date.context_today(self.Partner)

        member = self._create_member(
            "Socio wizard baja definitiva ejecución",
            99600003400,
            join_date=today - relativedelta(years=6),
        )

        Wizard = self.env["club.membership.end.wizard"].with_user(self.admin)

        wizard = Wizard.create(
            {
                "member_id": member.id,
                "effective_date": today,
                "reason": "Baja definitiva confirmada mediante wizard.",
            }
        )

        action = wizard.action_confirm()

        member.invalidate_recordset()

        self.assertFalse(member.club_person_type)
        self.assertFalse(member.club_member_state)

        finalized_period = self.Period.search(
            [
                ("person_id", "=", member.id),
                ("state", "=", "finalized"),
            ],
            limit=1,
        )
        self.assertTrue(finalized_period)
        self.assertEqual(finalized_period.end_date, today)

        self.assertEqual(action["res_model"], "res.partner")
        self.assertEqual(action["res_id"], member.id)
        self.assertEqual(action["target"], "current")
