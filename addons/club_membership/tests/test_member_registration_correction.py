from dateutil.relativedelta import relativedelta
from odoo import Command, fields
from odoo.exceptions import AccessError, ValidationError
from odoo.tests import tagged
from odoo.tests.common import TransactionCase


@tagged("post_install", "-at_install")
class TestMemberRegistrationCorrection(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()

        cls.admin = cls.env.ref("base.user_admin")
        cls.internal_group = cls.env.ref("base.group_user")

        cls.Partner = cls.env["res.partner"].with_user(cls.admin)
        cls.Beneficiary = cls.env["club.beneficiary"].with_user(cls.admin)
        cls.Certificate = cls.env["club.certificate"].with_user(cls.admin)
        cls.Kardex = cls.env["club.kardex.event"].with_user(cls.admin)
        cls.Period = cls.env["club.membership.period"].with_user(cls.admin)
        cls.Correction = cls.env["club.member.registration.correction"].with_user(
            cls.admin
        )

        cls.target_member = cls._create_member(
            name="Socio titular correcto prueba",
            start_number=99300000100,
        )

        cls.regular_user = cls.env["res.users"].create(
            {
                "name": "Usuario prueba sin corrección de alta errónea",
                "login": "club_member_registration_regular_test",
                "groups_id": [
                    Command.set(
                        [
                            cls.internal_group.id,
                        ]
                    )
                ],
            }
        )

        if cls.regular_user.has_group(
            "club_membership.group_club_member_registration_correction"
        ):
            raise AssertionError(
                "El usuario regular de prueba no debe tener permiso "
                "de corrección de alta errónea de Socio."
            )

    @classmethod
    def _next_available_id_number(cls, start):
        number = start

        while cls.Partner.search(
            [
                ("club_id_number", "=", str(number)),
            ],
            limit=1,
        ):
            number += 1

        return str(number)

    @classmethod
    def _birthdate_for_age(cls, age):
        today = fields.Date.context_today(cls.Partner)

        return fields.Date.to_string(today - relativedelta(years=age))

    @classmethod
    def _create_member(
        cls,
        name,
        start_number,
        state="active",
    ):
        return cls.Partner.create(
            {
                "name": name,
                "company_type": "person",
                "is_company": False,
                "club_person_type": "member",
                "club_id_number": (cls._next_available_id_number(start_number)),
                "club_birthdate": cls._birthdate_for_age(40),
                "club_member_state": state,
            }
        )

    @classmethod
    def _create_person(
        cls,
        name,
        start_number,
        age=30,
    ):
        return cls.Partner.create(
            {
                "name": name,
                "company_type": "person",
                "is_company": False,
                "club_id_number": (cls._next_available_id_number(start_number)),
                "club_birthdate": cls._birthdate_for_age(age),
            }
        )

    def _create_certificate(self, member):
        return self.Certificate.create(
            {
                "member_id": member.id,
                "registration_origin": "new",
                "total_value": 1000.0,
                "opening_balance": 1000.0,
            }
        )

    def _correct_member(
        self,
        member,
        relationship="spouse",
        reason="Alta registrada erróneamente como Socio",
    ):
        return member.correct_member_registration_error_to_beneficiary(
            self.target_member,
            {
                "relationship": relationship,
                "relationship_detail": False,
                "special_condition": "none",
                "start_date": fields.Date.context_today(member),
                "reason": reason,
            },
        )

    def test_user_without_permission_cannot_correct_member_registration(self):
        member = self._create_member(
            name="Socio corrección no autorizada",
            start_number=99300000150,
        )

        with self.assertRaises(AccessError):
            member.with_user(
                self.regular_user
            ).correct_member_registration_error_to_beneficiary(
                self.target_member.with_user(self.regular_user),
                {
                    "relationship": "spouse",
                    "relationship_detail": False,
                    "special_condition": "none",
                    "start_date": fields.Date.context_today(member),
                    "reason": "Intento de prueba sin permiso.",
                },
            )

        member.invalidate_recordset()

        self.assertEqual(
            member.club_person_type,
            "member",
        )
        self.assertEqual(
            member.club_member_state,
            "active",
        )

    def test_normal_member_removal_remains_blocked(self):
        member = self._create_member(
            name="Socio protección cambio directo",
            start_number=99300000200,
        )

        with self.assertRaises(ValidationError):
            member.write(
                {
                    "club_person_type": False,
                }
            )

        member.invalidate_recordset()

        self.assertEqual(
            member.club_person_type,
            "member",
        )
        self.assertEqual(
            member.club_member_state,
            "active",
        )

    def test_correction_reuses_same_person_and_carnet(self):
        member = self._create_member(
            name="Socio alta errónea sin certificado",
            start_number=99300000300,
        )

        original_partner_id = member.id
        original_carnet = member.club_id_number
        original_member_code = member.club_member_code

        beneficiary, correction = self._correct_member(member)

        member.invalidate_recordset()
        beneficiary.invalidate_recordset()
        correction.invalidate_recordset()

        self.assertEqual(
            member.id,
            original_partner_id,
        )
        self.assertEqual(
            member.club_id_number,
            original_carnet,
        )
        self.assertFalse(member.club_person_type)
        self.assertFalse(member.club_member_code)
        self.assertFalse(member.club_member_state)

        self.assertEqual(
            beneficiary.person_id,
            member,
        )
        self.assertEqual(
            beneficiary.member_id,
            self.target_member,
        )
        self.assertEqual(
            beneficiary.state,
            "active",
        )

        self.assertEqual(
            self.Partner.search_count(
                [
                    (
                        "club_id_number",
                        "=",
                        original_carnet,
                    ),
                ]
            ),
            1,
        )

        self.assertEqual(
            correction.person_id,
            member,
        )
        self.assertEqual(
            correction.target_member_id,
            self.target_member,
        )
        self.assertEqual(
            correction.beneficiary_id,
            beneficiary,
        )
        self.assertEqual(
            correction.old_member_code,
            original_member_code,
        )
        self.assertEqual(
            correction.id_number,
            original_carnet,
        )
        self.assertEqual(
            correction.user_id,
            self.admin,
        )
        self.assertTrue(correction.event_datetime)

        event = self.Kardex.search(
            [
                ("member_id", "=", member.id),
                (
                    "event_type",
                    "=",
                    "member_registration_error_corrected",
                ),
            ],
            order="id desc",
            limit=1,
        )

        self.assertTrue(event)
        self.assertEqual(
            event.beneficiary_id,
            beneficiary,
        )

    def test_certificate_is_voided_and_preserved(self):
        member = self._create_member(
            name="Socio alta errónea con certificado",
            start_number=99300000400,
        )

        original_carnet = member.club_id_number

        certificate = self._create_certificate(member)

        beneficiary, correction = self._correct_member(
            member,
            reason="Registro administrativo incorrecto",
        )

        member.invalidate_recordset()
        certificate.invalidate_recordset()
        beneficiary.invalidate_recordset()
        correction.invalidate_recordset()

        self.assertEqual(
            certificate.member_id,
            member,
        )
        self.assertEqual(
            certificate.certificate_number,
            original_carnet,
        )
        self.assertEqual(
            certificate.state,
            "registration_error_void",
        )
        self.assertEqual(
            certificate.registration_error_reason,
            "Registro administrativo incorrecto",
        )
        self.assertEqual(
            certificate.registration_error_user_id,
            self.admin,
        )
        self.assertTrue(certificate.registration_error_at)

        self.assertEqual(
            correction.certificate_id,
            certificate,
        )
        self.assertEqual(
            correction.certificate_number,
            original_carnet,
        )

        with self.assertRaises(ValidationError):
            certificate.write(
                {
                    "observations": ("Intento de modificar certificado anulado"),
                }
            )

    def test_current_beneficiary_blocks_correction_until_finalized(
        self,
    ):
        member = self._create_member(
            name="Socio erróneo con Beneficiario vigente",
            start_number=99300000500,
        )

        certificate = self._create_certificate(member)

        dependent_person = self._create_person(
            name="Beneficiario vigente del Socio erróneo",
            start_number=99300000600,
        )

        current_beneficiary = self.Beneficiary.create(
            {
                "person_id": dependent_person.id,
                "member_id": member.id,
                "relationship": "spouse",
                "special_condition": "none",
            }
        )

        self.assertEqual(
            len(
                self.Beneficiary.search(
                    [
                        ("member_id", "=", member.id),
                        ("state", "in", ("active", "blocked")),
                    ]
                )
            ),
            1,
        )

        with self.assertRaises(ValidationError):
            self._correct_member(member)

        member.invalidate_recordset()
        certificate.invalidate_recordset()

        self.assertEqual(
            member.club_person_type,
            "member",
        )
        self.assertEqual(
            member.club_member_state,
            "active",
        )
        self.assertEqual(
            certificate.state,
            "active",
        )

        self.assertFalse(
            self.Correction.search(
                [
                    ("person_id", "=", member.id),
                ],
                limit=1,
            )
        )

        current_beneficiary.finalize_link(
            end_date=fields.Date.context_today(current_beneficiary),
            reason=("Vínculo finalizado manualmente antes de corregir el alta"),
        )

        current_beneficiary.invalidate_recordset()
        member.invalidate_recordset()

        self.assertEqual(
            current_beneficiary.state,
            "finalized",
        )
        self.assertFalse(
            self.Beneficiary.search(
                [
                    ("member_id", "=", member.id),
                    ("state", "in", ("active", "blocked")),
                ]
            )
        )

        beneficiary, correction = self._correct_member(member)

        member.invalidate_recordset()
        certificate.invalidate_recordset()

        self.assertEqual(
            certificate.state,
            "registration_error_void",
        )
        self.assertFalse(member.club_person_type)
        self.assertEqual(
            beneficiary.person_id,
            member,
        )
        self.assertEqual(
            correction.person_id,
            member,
        )

    def test_blocked_beneficiary_also_blocks_correction(self):
        member = self._create_member(
            name="Socio erróneo con Beneficiario bloqueado",
            start_number=99300000700,
        )

        dependent_person = self._create_person(
            name="Beneficiario bloqueado del Socio",
            start_number=99300000800,
        )

        beneficiary = self.Beneficiary.create(
            {
                "person_id": dependent_person.id,
                "member_id": member.id,
                "relationship": "partner",
                "special_condition": "none",
            }
        )

        beneficiary.write(
            {
                "state": "blocked",
                "block_reason": "Bloqueo administrativo de prueba",
            }
        )

        beneficiary.invalidate_recordset()

        self.assertEqual(
            beneficiary.state,
            "blocked",
        )

        with self.assertRaises(ValidationError):
            self._correct_member(member)

        member.invalidate_recordset()

        self.assertEqual(
            member.club_person_type,
            "member",
        )
        self.assertEqual(
            member.club_member_state,
            "active",
        )

    def test_relationship_labels_match_approved_catalog(self):
        selection = dict(self.Beneficiary._fields["relationship"].selection)

        self.assertEqual(
            selection["spouse"],
            "Esposo(a)",
        )
        self.assertEqual(
            selection["partner"],
            "Pareja de hecho",
        )

    def test_correction_voids_membership_period(self):
        member = self._create_member(
            name="Socio período alta errónea",
            start_number=99300009900,
        )

        period = self.Period.search(
            [
                ("person_id", "=", member.id),
                ("state", "=", "current"),
            ],
            limit=1,
        )

        self.assertTrue(period)

        reason = "Alta administrativa registrada por error"

        self._correct_member(
            member,
            reason=reason,
        )

        member.invalidate_recordset()
        period.invalidate_recordset()

        self.assertEqual(period.state, "voided")
        self.assertFalse(period.end_date)
        self.assertEqual(period.void_reason, reason)
        self.assertTrue(period.voided_at)
        self.assertEqual(period.void_user_id, self.admin)

        self.assertFalse(
            self.Period.search(
                [
                    ("person_id", "=", member.id),
                    ("state", "=", "current"),
                ],
                limit=1,
            )
        )

        self.assertFalse(
            self.Period.search(
                [
                    ("person_id", "=", member.id),
                    ("state", "=", "finalized"),
                ],
                limit=1,
            )
        )

    def _prepare_multiple_certificates_for_correction(self):
        member = self._create_member(
            name="Socio alta erronea con historial patrimonial",
            start_number=99300009500,
        )

        today = fields.Date.context_today(member)

        active = self.Certificate.create(
            {
                "member_id": member.id,
                "registration_origin": "new",
                "total_value": 1000.0,
                "opening_balance": 1000.0,
                "issue_date": fields.Date.to_string(today - relativedelta(years=2)),
            }
        )

        historical = self.Certificate.create(
            {
                "member_id": member.id,
                "registration_origin": "new",
                "total_value": 1000.0,
                "opening_balance": 1000.0,
                "issue_date": fields.Date.to_string(today),
                "state": "transferred",
            }
        )

        member.invalidate_recordset(["club_certificate_ids"])

        self.assertEqual(len(member.club_certificate_ids), 2)
        self.assertEqual(active.state, "active")
        self.assertEqual(historical.state, "transferred")

        return member, active, historical

    def test_multiple_certificates_backend_rejects_without_side_effects(self):
        member, active, historical = (
            self._prepare_multiple_certificates_for_correction()
        )

        original_code = member.club_member_code
        original_carnet = member.club_id_number

        period = self.Period.search(
            [
                ("person_id", "=", member.id),
                ("state", "=", "current"),
            ],
            limit=1,
        )

        self.assertTrue(period)

        with (
            self.env.cr.savepoint(),
            self.assertRaisesRegex(
                ValidationError,
                "más de un Certificado",
            ),
        ):
            self._correct_member(member)

        member.invalidate_recordset()
        active.invalidate_recordset()
        historical.invalidate_recordset()
        period.invalidate_recordset()

        self.assertEqual(member.club_person_type, "member")
        self.assertEqual(member.club_member_state, "active")
        self.assertEqual(member.club_member_code, original_code)
        self.assertEqual(member.club_id_number, original_carnet)

        self.assertEqual(active.state, "active")
        self.assertEqual(historical.state, "transferred")
        self.assertFalse(active.registration_error_at)
        self.assertFalse(historical.registration_error_at)

        self.assertEqual(period.state, "current")

        self.assertFalse(
            self.Beneficiary.search(
                [
                    ("person_id", "=", member.id),
                    ("state", "in", ("active", "blocked")),
                ]
            )
        )

    def test_multiple_certificates_wizard_rejects_ambiguous_selection(self):
        member, active, historical = (
            self._prepare_multiple_certificates_for_correction()
        )

        Wizard = self.env["club.member.registration.correction.wizard"].with_user(
            self.admin
        )

        with (
            self.env.cr.savepoint(),
            self.assertRaisesRegex(
                ValidationError,
                "más de un Certificado",
            ),
        ):
            wizard = Wizard.create(
                {
                    "member_id": member.id,
                    "target_member_id": self.target_member.id,
                    "relationship": "spouse",
                    "special_condition": "none",
                    "start_date": fields.Date.context_today(member),
                    "reason": "Alta erronea con historial patrimonial.",
                }
            )
            self.assertTrue(wizard.certificate_id)

        member.invalidate_recordset()
        active.invalidate_recordset()
        historical.invalidate_recordset()

        self.assertEqual(member.club_person_type, "member")
        self.assertEqual(member.club_member_state, "active")
        self.assertEqual(active.state, "active")
        self.assertEqual(historical.state, "transferred")

    def test_cau06_single_transferred_history_blocks_erroneous_registration_correction(
        self,
    ):
        member = self._create_member(
            name="Socio con certificado historico transferido",
            start_number=99300009670,
        )
        historical = self.Certificate.create(
            {
                "member_id": member.id,
                "registration_origin": "new",
                "total_value": 1000.0,
                "opening_balance": 1000.0,
                "state": "transferred",
            }
        )

        original_code = member.club_member_code
        original_carnet = member.club_id_number

        period = self.Period.search(
            [
                ("person_id", "=", member.id),
                ("state", "=", "current"),
            ],
            limit=1,
        )
        self.assertTrue(period)

        with (
            self.env.cr.savepoint(),
            self.assertRaisesRegex(
                ValidationError,
                "[Cc]ertificado|hist[oó]ric|[Tt]ransferid",
            ),
        ):
            self._correct_member(
                member,
                reason="Intento de corregir alta con patrimonio historico",
            )

        member.invalidate_recordset()
        historical.invalidate_recordset()
        period.invalidate_recordset()

        self.assertEqual(member.club_person_type, "member")
        self.assertEqual(member.club_member_code, original_code)
        self.assertEqual(member.club_id_number, original_carnet)
        self.assertEqual(historical.state, "transferred")
        self.assertFalse(historical.registration_error_at)
        self.assertEqual(period.state, "current")

        self.assertFalse(
            self.Beneficiary.search(
                [
                    ("person_id", "=", member.id),
                    ("state", "in", ("active", "blocked")),
                ]
            )
        )

    def test_cau07_single_passive_withdrawal_blocks_backend(self):
        member = self._create_member(
            name="Caso defensivo certificado pasivo por retiro",
            start_number=99300009671,
        )
        certificate = self.Certificate.create(
            {
                "member_id": member.id,
                "registration_origin": "new",
                "total_value": 1000.0,
                "opening_balance": 1000.0,
                "state": "active",
            }
        )

        member.action_withdraw_club_member(
            "Retiro controlado de prueba CAU-07.",
            effective_date=fields.Date.context_today(member),
        )

        member.invalidate_recordset(["club_certificate_ids"])
        self.assertEqual(len(member.club_certificate_ids), 1)

        with (
            self.env.cr.savepoint(),
            self.assertRaises(ValidationError),
        ):
            self._correct_member(member)

        member.invalidate_recordset()
        certificate.invalidate_recordset()
        self.assertEqual(member.club_person_type, "member")
        self.assertEqual(certificate.state, "passive")
        self.assertTrue(certificate.passive_by_member_withdrawal)
        self.assertFalse(certificate.registration_error_at)

    def test_cau07_single_passive_membership_end_blocks_backend(self):
        member = self._create_member(
            name="Caso defensivo certificado pasivo fin membresia",
            start_number=99300009672,
        )
        certificate = self.Certificate.create(
            {
                "member_id": member.id,
                "registration_origin": "new",
                "total_value": 1000.0,
                "opening_balance": 1000.0,
                "state": "active",
            }
        )

        member.action_end_club_membership(
            "Baja definitiva controlada de prueba CAU-07.",
            effective_date=fields.Date.context_today(member),
        )

        member.invalidate_recordset(["club_certificate_ids"])
        self.assertEqual(len(member.club_certificate_ids), 1)

        with (
            self.env.cr.savepoint(),
            self.assertRaises(ValidationError),
        ):
            self._correct_member(member)

        member.invalidate_recordset()
        certificate.invalidate_recordset()
        self.assertNotEqual(member.club_person_type, "member")
        self.assertEqual(certificate.state, "passive")
        self.assertTrue(certificate.passive_by_membership_end)
        self.assertFalse(certificate.registration_error_at)

    def test_cau07_single_transferred_history_blocks_wizard(self):
        member = self._create_member(
            name="Caso defensivo asistente historico transferido",
            start_number=99300009673,
        )
        certificate = self.Certificate.create(
            {
                "member_id": member.id,
                "registration_origin": "new",
                "total_value": 1000.0,
                "opening_balance": 1000.0,
                "state": "transferred",
            }
        )
        member.invalidate_recordset(["club_certificate_ids"])
        self.assertEqual(len(member.club_certificate_ids), 1)

        Wizard = self.env["club.member.registration.correction.wizard"].with_user(
            self.admin
        )

        with (
            self.env.cr.savepoint(),
            self.assertRaisesRegex(ValidationError, "[Cc]ertificado|[Aa]ctivo"),
        ):
            wizard = Wizard.create(
                {
                    "member_id": member.id,
                    "target_member_id": self.target_member.id,
                    "relationship": "spouse",
                    "special_condition": "none",
                    "start_date": fields.Date.context_today(member),
                    "reason": "Intento de anular patrimonio historico.",
                }
            )
            self.assertTrue(wizard.certificate_id)

        member.invalidate_recordset()
        certificate.invalidate_recordset()
        self.assertEqual(member.club_person_type, "member")
        self.assertEqual(certificate.state, "transferred")
        self.assertFalse(certificate.registration_error_at)

    def test_cau07_internal_void_rejects_transferred(self):
        member = self._create_member(
            name="Caso defensivo anulacion interna transferido",
            start_number=99300009674,
        )
        certificate = self.Certificate.create(
            {
                "member_id": member.id,
                "registration_origin": "new",
                "total_value": 1000.0,
                "opening_balance": 1000.0,
                "state": "transferred",
            }
        )

        with (
            self.env.cr.savepoint(),
            self.assertRaisesRegex(ValidationError, "Solo un Certificado Activo"),
        ):
            certificate.with_user(self.admin)._action_void_registration_error(
                "Intento de anular certificado transferido."
            )

        certificate.invalidate_recordset()
        self.assertEqual(certificate.state, "transferred")
        self.assertFalse(certificate.registration_error_at)

    def test_cau07_internal_void_rejects_passive(self):
        member = self._create_member(
            name="Caso defensivo anulacion interna pasivo",
            start_number=99300009675,
        )
        certificate = self.Certificate.create(
            {
                "member_id": member.id,
                "registration_origin": "new",
                "total_value": 1000.0,
                "opening_balance": 1000.0,
                "state": "active",
            }
        )

        member.action_withdraw_club_member(
            "Retiro controlado para probar anulacion interna.",
            effective_date=fields.Date.context_today(member),
        )

        with (
            self.env.cr.savepoint(),
            self.assertRaisesRegex(ValidationError, "Solo un Certificado Activo"),
        ):
            certificate.with_user(self.admin)._action_void_registration_error(
                "Intento de anular certificado pasivo."
            )

        certificate.invalidate_recordset()
        self.assertEqual(certificate.state, "passive")
        self.assertTrue(certificate.passive_by_member_withdrawal)
        self.assertFalse(certificate.registration_error_at)

    def test_cau08_legitimate_reentry_blocks_erroneous_correction_without_side_effects(
        self,
    ):
        """Un reingreso legitimo no anula su historia por correccion de alta."""
        today = fields.Date.context_today(self.Partner)

        member = self._create_member(
            name="Socio CAU08 con reingreso legitimo",
            start_number=99300808000,
        )
        certificate = self._create_certificate(member)

        initial_period = self.Period.search(
            [
                ("person_id", "=", member.id),
                ("state", "=", "current"),
            ],
            limit=1,
        )
        self.assertTrue(initial_period)
        self.assertEqual(initial_period.origin, "initial")
        self.assertEqual(certificate.state, "active")

        member.action_end_club_membership(
            "Baja definitiva legitima previa a CAU08.",
            effective_date=today,
        )
        member.invalidate_recordset()
        certificate.invalidate_recordset()
        initial_period.invalidate_recordset()

        self.assertEqual(initial_period.state, "finalized")
        self.assertEqual(certificate.state, "passive")
        self.assertTrue(certificate.passive_by_membership_end)

        member.action_reenter_club_member(
            "Reingreso legitimo con historia conservada.",
            effective_date=today,
        )
        member.invalidate_recordset()
        certificate.invalidate_recordset()

        current_period = self.Period.search(
            [
                ("person_id", "=", member.id),
                ("state", "=", "current"),
            ],
            limit=1,
        )

        self.assertTrue(current_period)
        self.assertEqual(current_period.origin, "reentry")
        self.assertNotEqual(initial_period.id, current_period.id)
        self.assertEqual(certificate.state, "active")
        self.assertFalse(certificate.passive_by_membership_end)
        self.assertEqual(member.club_person_type, "member")

        before_corrections = self.Correction.search_count(
            [("person_id", "=", member.id)]
        )
        before_beneficiaries = self.Beneficiary.search_count(
            [("person_id", "=", member.id)]
        )
        historical_end_date = initial_period.end_date

        # La correccion actual aun no distingue este reingreso.
        # En TDD se espera un rechazo causal por Reingreso.
        # El savepoint evita persistencia de efectos si la
        # asercion falla durante el primer ensayo.
        with self.env.cr.savepoint():
            with self.assertRaisesRegex(
                ValidationError,
                "[Rr]eingreso",
            ):
                self._correct_member(
                    member,
                    reason=(
                        "Intento de corregir un reingreso "
                        "con membresia legitima previa."
                    ),
                )

        member.invalidate_recordset()
        certificate.invalidate_recordset()
        initial_period.invalidate_recordset()
        current_period.invalidate_recordset()

        self.assertEqual(member.club_person_type, "member")
        self.assertEqual(certificate.state, "active")
        self.assertEqual(initial_period.state, "finalized")
        self.assertEqual(initial_period.end_date, historical_end_date)
        self.assertEqual(current_period.state, "current")
        self.assertEqual(current_period.origin, "reentry")
        self.assertEqual(
            self.Correction.search_count([("person_id", "=", member.id)]),
            before_corrections,
        )
        self.assertEqual(
            self.Beneficiary.search_count([("person_id", "=", member.id)]),
            before_beneficiaries,
        )
