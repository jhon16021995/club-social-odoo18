from dateutil.relativedelta import relativedelta
from odoo import fields
from odoo.exceptions import AccessError
from odoo.tests import TransactionCase, tagged


@tagged("post_install", "-at_install")
class TestCertificateTransfer(TransactionCase):
    def test_transfer_rejects_recipient_who_is_already_member(self):
        """Un Socio vigente no puede recibir otro Certificado."""
        import uuid

        from odoo.exceptions import ValidationError

        admin = self.env.ref("base.user_admin")
        Partner = self.env["res.partner"].with_user(admin)
        Transfer = self.env["club.certificate.transfer"]

        today = fields.Date.context_today(Partner)
        suffix = uuid.uuid4().hex[:6]
        identity = 99800000000 + int(suffix, 16)

        existing_member = Partner.create(
            {
                "name": "F10-D Socio receptor " + suffix,
                "company_type": "person",
                "is_company": False,
                "club_person_type": "member",
                "club_id_number": str(identity),
                "club_birthdate": fields.Date.to_string(
                    today - relativedelta(years=40)
                ),
                "club_join_date": today,
            }
        )

        self.assertEqual(existing_member.club_person_type, "member")

        transfer = Transfer.new(
            {
                "recipient_person_id": existing_member.id,
            }
        )

        with self.assertRaisesRegex(
            ValidationError,
            "ya es Socio vigente",
        ):
            transfer._check_recipient_not_current_member()

    def test_certificate_transfer_registration_origin(self):
        """Existe un origen específico para certificados recibidos."""
        Certificate = self.env["club.certificate"]

        origin_field = Certificate._fields["registration_origin"]
        origins = dict(origin_field.selection)

        self.assertIn(
            "transfer_received",
            origins,
            "Falta el origen Recibido por transferencia.",
        )

    def test_certificate_transfer_source_relationship(self):
        """El certificado recibido conserva referencia al original."""
        Certificate = self.env["club.certificate"]

        self.assertIn(
            "transfer_source_certificate_id",
            Certificate._fields,
            "Falta la referencia al certificado del cedente.",
        )

        field = Certificate._fields["transfer_source_certificate_id"]

        self.assertEqual(
            field.comodel_name,
            "club.certificate",
        )

    def test_transfer_received_does_not_invent_historical_payment(self):
        """El valor recibido no equivale a efectivo pagado por el receptor."""
        Certificate = self.env["club.certificate"]

        certificate = Certificate.new(
            {
                "registration_origin": "transfer_received",
                "total_value": 5000.0,
                "opening_balance": 0.0,
            }
        )

        certificate._compute_opening_paid_amount()

        self.assertEqual(certificate.total_value, 5000.0)
        self.assertEqual(certificate.opening_balance, 0.0)

        self.assertEqual(
            certificate.opening_paid_amount,
            0.0,
            "El receptor no pagó Bs 5.000: recibió un derecho "
            "patrimonial por transferencia.",
        )

    def test_direct_creation_of_received_certificate_is_forbidden(self):
        """No se puede simular una transferencia mediante create directo."""
        admin = self.env.ref("base.user_admin")
        Partner = self.env["res.partner"].with_user(admin)
        Certificate = self.env["club.certificate"].with_user(admin)

        today = fields.Date.context_today(Partner)
        birthdate = today - relativedelta(years=40)

        number = 99720001000

        while Partner.search(
            [
                (
                    "club_id_number",
                    "in",
                    [str(number), str(number + 1)],
                )
            ],
            limit=1,
        ):
            number += 2

        def create_member(name, card_number):
            return Partner.create(
                {
                    "name": name,
                    "company_type": "person",
                    "is_company": False,
                    "club_person_type": "member",
                    "club_id_number": str(card_number),
                    "club_birthdate": fields.Date.to_string(birthdate),
                    "club_join_date": today,
                }
            )

        donor = create_member(
            "Socio cedente prueba seguridad",
            number,
        )

        receiver = create_member(
            "Socio receptor prueba seguridad",
            number + 1,
        )

        source = Certificate.create(
            {
                "member_id": donor.id,
                "registration_origin": "migrated",
                "total_value": 5000.0,
                "opening_balance": 0.0,
            }
        )

        self.assertEqual(source.certificate_type, "paid")

        with self.env.cr.savepoint(), self.assertRaises(AccessError):
            Certificate.create(
                {
                    "member_id": receiver.id,
                    "registration_origin": "transfer_received",
                    "transfer_source_certificate_id": source.id,
                    "total_value": 5000.0,
                    "opening_balance": 0.0,
                    "state": "active",
                }
            )

        self.assertFalse(
            Certificate.search(
                [
                    ("member_id", "=", receiver.id),
                    ("registration_origin", "=", "transfer_received"),
                ]
            )
        )

    def test_direct_write_of_transfer_source_is_forbidden(self):
        """No se permite simular una transferencia mediante write."""
        admin = self.env.ref("base.user_admin")
        Partner = self.env["res.partner"].with_user(admin)
        Certificate = self.env["club.certificate"].with_user(admin)

        today = fields.Date.context_today(Partner)
        birthdate = today - relativedelta(years=40)

        number = 99720002000

        while Partner.search(
            [
                (
                    "club_id_number",
                    "in",
                    [str(number), str(number + 1)],
                )
            ],
            limit=1,
        ):
            number += 2

        def create_member(name, card_number):
            return Partner.create(
                {
                    "name": name,
                    "company_type": "person",
                    "is_company": False,
                    "club_person_type": "member",
                    "club_id_number": str(card_number),
                    "club_birthdate": fields.Date.to_string(birthdate),
                    "club_join_date": today,
                }
            )

        donor = create_member(
            "Cedente para prueba write",
            number,
        )

        receiver = create_member(
            "Receptor para prueba write",
            number + 1,
        )

        source = Certificate.create(
            {
                "member_id": donor.id,
                "registration_origin": "migrated",
                "total_value": 5000.0,
                "opening_balance": 0.0,
            }
        )

        target = Certificate.create(
            {
                "member_id": receiver.id,
                "registration_origin": "new",
                "total_value": 5000.0,
            }
        )

        self.assertFalse(target.transfer_source_certificate_id)

        with self.env.cr.savepoint(), self.assertRaises(AccessError):
            target.write(
                {
                    "transfer_source_certificate_id": source.id,
                }
            )

        target.invalidate_recordset()

        self.assertFalse(
            target.transfer_source_certificate_id,
            "Una operación rechazada no debe dejar "
            "referencias de transferencia modificadas.",
        )

    def test_transfer_documentary_verification_structure(self):
        """Toda transferencia requiere evidencia auditable."""
        model_name = "club.certificate.transfer"

        self.assertIn(
            model_name,
            self.env.registry.models,
            "Falta el modelo de transferencia patrimonial.",
        )

        Transfer = self.env[model_name]

        required_fields = {
            "source_certificate_id",
            "recipient_person_id",
            "effective_date",
            "payment_evidence_reference",
            "payment_verified_by_id",
            "payment_verified_at",
        }

        missing_fields = required_fields - set(Transfer._fields)

        self.assertFalse(
            missing_fields,
            "Faltan campos de verificación documental: "
            + ", ".join(sorted(missing_fields)),
        )

    def test_transfer_acl_system_is_read_only(self):
        """El administrador tecnico solo puede consultar."""
        admin = self.env.ref("base.user_admin")

        self.assertTrue(admin.has_group("base.group_system"))

        Transfer = self.env["club.certificate.transfer"].with_user(admin)

        self.assertTrue(Transfer.has_access("read"))

        # Verificar una consulta ORM real.
        self.assertGreaterEqual(
            Transfer.search_count([]),
            0,
        )

        for operation in ("create", "write", "unlink"):
            self.assertFalse(
                Transfer.has_access(operation),
                "El administrador no debe tener permiso directo para: " + operation,
            )

            with self.assertRaises(AccessError):
                Transfer.check_access(operation)

    def test_transfer_acl_internal_user_has_no_access(self):
        """Un empleado sin grupo especial no puede acceder."""
        internal_group = self.env.ref("base.group_user")

        employee = (
            self.env["res.users"]
            .sudo()
            .with_context(no_reset_password=True)
            .create(
                {
                    "name": "Empleado prueba ACL transferencia",
                    "login": "club_transfer_acl_test_employee",
                    "groups_id": [
                        (6, 0, [internal_group.id]),
                    ],
                }
            )
        )

        self.assertTrue(employee.has_group("base.group_user"))
        self.assertFalse(employee.has_group("base.group_system"))

        Transfer = self.env["club.certificate.transfer"].with_user(employee)

        for operation in ("read", "create", "write", "unlink"):
            self.assertFalse(
                Transfer.has_access(operation),
                "Empleado no autorizado para: " + operation,
            )

            with self.assertRaises(AccessError):
                Transfer.check_access(operation)

        # Comprobar tambien el acceso mediante ORM.
        with self.assertRaises(AccessError):
            Transfer.search([])

    def test_payment_verification_requires_complete_evidence(self):
        """El pago total exige evidencia documental completa."""
        from odoo.exceptions import ValidationError

        Transfer = self.env["club.certificate.transfer"]

        validator = getattr(
            Transfer,
            "_validate_payment_evidence",
            None,
        )

        self.assertTrue(
            callable(validator),
            "Falta el validador de evidencia documental.",
        )

        valid_data = {
            "payment_evidence_reference": "ACTA-PAGO-001",
            "payment_verified_by_id": self.env.user.id,
            "payment_verified_at": fields.Datetime.now(),
        }

        # Ninguno de los tres datos puede faltar.
        for field_name in valid_data:
            incomplete_data = dict(valid_data)
            incomplete_data.pop(field_name)

            with self.subTest(missing_field=field_name):
                with self.assertRaises(ValidationError):
                    validator(incomplete_data)

        # Tampoco se aceptan valores vacios.
        invalid_values = {
            "payment_evidence_reference": "   ",
            "payment_verified_by_id": False,
            "payment_verified_at": False,
        }

        for field_name, invalid_value in invalid_values.items():
            incomplete_data = dict(valid_data)
            incomplete_data[field_name] = invalid_value

            with self.subTest(invalid_field=field_name):
                with self.assertRaises(ValidationError):
                    validator(incomplete_data)

        # La evidencia completa supera esta validacion inicial.
        self.assertTrue(validator(valid_data))

    def test_payment_verification_requires_authorized_operator(self):
        """Solo el funcionario habilitado verifica el pago."""
        role_xmlid = "club_membership.group_club_certificate_payment_verification"

        role = self.env.ref(
            role_xmlid,
            raise_if_not_found=False,
        )

        self.assertTrue(
            role,
            "Falta el grupo institucional de verificacion de pago patrimonial.",
        )

        Transfer = self.env["club.certificate.transfer"]

        validator = getattr(
            Transfer,
            "_check_payment_verifier_permission",
            None,
        )

        self.assertTrue(
            callable(validator),
            "Falta el control de permiso del funcionario verificador.",
        )

        Users = self.env["res.users"].sudo()
        internal_group = self.env.ref("base.group_user")

        ordinary_employee = Users.with_context(no_reset_password=True).create(
            {
                "name": "Empleado sin permiso de verificacion",
                "login": "club_transfer_payment_plain_test",
                "groups_id": [(6, 0, [internal_group.id])],
            }
        )

        authorized_employee = Users.with_context(no_reset_password=True).create(
            {
                "name": "Funcionario verificador de prueba",
                "login": "club_transfer_payment_verified_test",
                "groups_id": [(6, 0, [internal_group.id, role.id])],
            }
        )

        self.assertFalse(ordinary_employee.has_group(role_xmlid))

        self.assertTrue(authorized_employee.has_group(role_xmlid))

        # Un usuario sin autorizacion debe ser rechazado.
        with self.assertRaises(AccessError):
            Transfer.with_user(ordinary_employee)._check_payment_verifier_permission()

        # Un verificador habilitado supera esta comprobacion.
        self.assertTrue(
            Transfer.with_user(authorized_employee)._check_payment_verifier_permission()
        )

        # Ser verificador NO concede escritura directa.
        authorized_transfer = Transfer.with_user(authorized_employee)

        for operation in ("create", "write", "unlink"):
            self.assertFalse(
                authorized_transfer.has_access(operation),
                "El grupo verificador no debe conceder "
                "operaciones directas: " + operation,
            )

    def test_payment_verification_uses_authenticated_identity(self):
        """La identidad y fecha provienen del servidor."""
        from odoo.exceptions import ValidationError

        Transfer = self.env["club.certificate.transfer"]

        prepare = getattr(
            Transfer,
            "_prepare_payment_verification_values",
            None,
        )

        self.assertTrue(
            callable(prepare),
            "Falta la preparacion segura de la verificacion documental.",
        )

        role = self.env.ref(
            "club_membership.group_club_certificate_payment_verification"
        )

        internal_group = self.env.ref("base.group_user")

        Users = self.env["res.users"].sudo().with_context(no_reset_password=True)

        unauthorized = Users.create(
            {
                "name": "Operador sin permiso patrimonial",
                "login": "club_transfer_identity_plain_test",
                "groups_id": [(6, 0, [internal_group.id])],
            }
        )

        authorized = Users.create(
            {
                "name": "Verificador patrimonial autorizado",
                "login": "club_transfer_identity_authorized_test",
                "groups_id": [(6, 0, [internal_group.id, role.id])],
            }
        )

        # Un empleado comun no puede preparar la verificacion.
        with self.assertRaises(AccessError):
            Transfer.with_user(unauthorized)._prepare_payment_verification_values(
                "ACTA-PAGO-415"
            )

        # El funcionario autorizado utiliza su identidad real.
        values = Transfer.with_user(authorized)._prepare_payment_verification_values(
            "  ACTA-PAGO-415  "
        )

        self.assertEqual(
            set(values),
            {
                "payment_evidence_reference",
                "payment_verified_by_id",
                "payment_verified_at",
            },
        )

        self.assertEqual(
            values["payment_evidence_reference"],
            "ACTA-PAGO-415",
        )

        self.assertEqual(
            values["payment_verified_by_id"],
            authorized.id,
        )

        self.assertTrue(fields.Datetime.to_datetime(values["payment_verified_at"]))

        # Referencia vacia: rechazada.
        with self.assertRaises(ValidationError):
            Transfer.with_user(authorized)._prepare_payment_verification_values("   ")

        # No se aceptan datos enviados para falsificar
        # la identidad del funcionario verificador.
        with self.assertRaises(ValidationError):
            Transfer.with_user(authorized)._prepare_payment_verification_values(
                {
                    "payment_evidence_reference": "ACTA-FALSA",
                    "payment_verified_by_id": unauthorized.id,
                }
            )

    def test_register_payment_verification_changes_only_its_stage(self):
        """Verificar el pago no autoriza ni ejecuta transferencias."""
        from odoo.exceptions import UserError, ValidationError

        from ..models.certificate_transfer import (
            _TRANSFER_RECORD_INTERNAL_TOKEN,
        )

        Transfer = self.env["club.certificate.transfer"]

        action = getattr(
            Transfer,
            "action_register_payment_verification",
            None,
        )

        self.assertTrue(
            callable(action),
            "Falta el procedimiento controlado de registro de verificacion documental.",
        )

        admin = self.env.ref("base.user_admin")
        Partner = self.env["res.partner"].with_user(admin)
        Certificate = self.env["club.certificate"].with_user(admin)

        today = fields.Date.context_today(Partner)
        birthdate = today - relativedelta(years=40)

        number = 99720005000

        while Partner.search(
            [("club_id_number", "=", str(number))],
            limit=1,
        ):
            number += 1

        donor = Partner.create(
            {
                "name": "Cedente verificacion documental 420",
                "company_type": "person",
                "is_company": False,
                "club_person_type": "member",
                "club_id_number": str(number),
                "club_birthdate": fields.Date.to_string(birthdate),
                "club_join_date": today,
            }
        )

        receiver = Partner.create(
            {
                "name": "Receptor borrador documental 420",
                "company_type": "person",
                "is_company": False,
            }
        )

        source = Certificate.create(
            {
                "member_id": donor.id,
                "registration_origin": "migrated",
                "total_value": 5000.0,
                "opening_balance": 0.0,
            }
        )

        # Preparacion interna EXCLUSIVA del escenario de prueba.
        internal_transfer = Transfer.sudo().with_context(
            club_transfer_record_internal_token=(_TRANSFER_RECORD_INTERNAL_TOKEN)
        )

        draft = internal_transfer.create(
            {
                "source_certificate_id": source.id,
                "recipient_person_id": receiver.id,
                "effective_date": today,
            }
        )

        self.assertEqual(draft.state, "draft")

        role = self.env.ref(
            "club_membership.group_club_certificate_payment_verification"
        )
        internal_group = self.env.ref("base.group_user")

        Users = self.env["res.users"].sudo().with_context(no_reset_password=True)

        verifier = Users.create(
            {
                "name": "Verificador documental 420",
                "login": "club_transfer_verifier_420",
                "groups_id": [(6, 0, [internal_group.id, role.id])],
            }
        )

        ordinary_user = Users.create(
            {
                "name": "Empleado ordinario 420",
                "login": "club_transfer_ordinary_420",
                "groups_id": [(6, 0, [internal_group.id])],
            }
        )

        # Empleado sin autorizacion: rechazo.
        with self.assertRaises(AccessError):
            draft.with_user(ordinary_user).action_register_payment_verification(
                "ACTA-PAGO-420",
                fully_paid_confirmed=True,
            )

        self.assertEqual(draft.state, "draft")

        # No se admite verificar sin declaracion expresa.
        with self.assertRaises(ValidationError):
            draft.with_user(verifier).action_register_payment_verification(
                "ACTA-PAGO-420",
                fully_paid_confirmed=False,
            )

        self.assertEqual(draft.state, "draft")

        # Verificacion autorizada.
        draft.with_user(verifier).action_register_payment_verification(
            "  ACTA-PAGO-420  ",
            fully_paid_confirmed=True,
        )

        draft.invalidate_recordset()

        self.assertEqual(draft.state, "payment_verified")

        self.assertEqual(
            draft.payment_evidence_reference,
            "ACTA-PAGO-420",
        )

        self.assertEqual(
            draft.payment_verified_by_id.id,
            verifier.id,
        )

        self.assertTrue(draft.payment_verified_at)

        # La verificacion NO es autorizacion ni ejecucion.
        self.assertFalse(draft.authorized_by_id)
        self.assertFalse(draft.authorized_at)
        self.assertFalse(draft.executed_at)
        self.assertFalse(draft.recipient_certificate_id)

        source.invalidate_recordset()

        self.assertEqual(source.state, "active")

        self.assertFalse(Certificate.search([("member_id", "=", receiver.id)]))

        # No debe ser posible reemplazar silenciosamente
        # la primera verificacion documental.
        with self.assertRaises(UserError):
            draft.with_user(verifier).action_register_payment_verification(
                "OTRA-ACTA-420",
                fully_paid_confirmed=True,
            )

        draft.invalidate_recordset()

        self.assertEqual(
            draft.payment_evidence_reference,
            "ACTA-PAGO-420",
        )

    def test_payment_verification_rejects_transferred_source(self):
        """Un Certificado ya transferido no puede verificarse otra vez."""
        from odoo.exceptions import UserError

        from ..models.certificate_transfer import (
            _TRANSFER_RECORD_INTERNAL_TOKEN,
        )

        admin = self.env.ref("base.user_admin")

        Partner = self.env["res.partner"].with_user(admin)
        Certificate = self.env["club.certificate"].with_user(admin)
        Transfer = self.env["club.certificate.transfer"]

        today = fields.Date.context_today(Partner)
        birthdate = today - relativedelta(years=40)

        number = 99720006000

        while Partner.search([("club_id_number", "=", str(number))], limit=1):
            number += 1

        donor = Partner.create(
            {
                "name": "Cedente prueba certificado transferido 425",
                "company_type": "person",
                "is_company": False,
                "club_person_type": "member",
                "club_id_number": str(number),
                "club_birthdate": fields.Date.to_string(birthdate),
                "club_join_date": today,
            }
        )

        receiver = Partner.create(
            {
                "name": "Receptor prueba documental 425",
                "company_type": "person",
                "is_company": False,
            }
        )

        source = Certificate.create(
            {
                "member_id": donor.id,
                "registration_origin": "migrated",
                "total_value": 5000.0,
                "opening_balance": 0.0,
            }
        )

        self.assertEqual(source.state, "active")

        # Crear un borrador mediante el mecanismo interno
        # solo para preparar este escenario de prueba.
        draft = (
            Transfer.sudo()
            .with_context(
                club_transfer_record_internal_token=(_TRANSFER_RECORD_INTERNAL_TOKEN)
            )
            .create(
                {
                    "source_certificate_id": source.id,
                    "recipient_person_id": receiver.id,
                    "effective_date": today,
                }
            )
        )

        self.assertEqual(draft.state, "draft")

        # Simular que el Certificado original ya fue
        # transferido antes de verificar este borrador.
        source.write(
            {
                "state": "transferred",
            }
        )

        self.assertEqual(source.state, "transferred")

        role = self.env.ref(
            "club_membership.group_club_certificate_payment_verification"
        )
        internal_group = self.env.ref("base.group_user")

        verifier = (
            self.env["res.users"]
            .sudo()
            .with_context(no_reset_password=True)
            .create(
                {
                    "name": "Verificador prueba 425",
                    "login": "club_transfer_source_verifier_425",
                    "groups_id": [(6, 0, [internal_group.id, role.id])],
                }
            )
        )

        # Aunque tenga permiso y declare el pago total,
        # debe rechazarse la verificacion porque el
        # Certificado original ya fue transferido.
        with self.assertRaises(UserError):
            draft.with_user(verifier).action_register_payment_verification(
                "ACTA-PAGO-425",
                fully_paid_confirmed=True,
            )

        draft.invalidate_recordset()
        source.invalidate_recordset()

        # El rechazo no debe alterar el borrador.
        self.assertEqual(draft.state, "draft")
        self.assertFalse(draft.payment_verified_by_id)
        self.assertFalse(draft.payment_verified_at)
        self.assertFalse(draft.payment_evidence_reference)

        # El Certificado original conserva su historia.
        self.assertEqual(source.state, "transferred")

    def test_payment_verification_rejects_passive_and_void_sources(self):
        """No verificar certificados pasivos ni anulados."""
        from odoo.exceptions import UserError

        from ..models.certificate_transfer import (
            _TRANSFER_RECORD_INTERNAL_TOKEN,
        )

        admin = self.env.ref("base.user_admin")

        Partner = self.env["res.partner"].with_user(admin)
        Certificate = self.env["club.certificate"].with_user(admin)
        Transfer = self.env["club.certificate.transfer"]

        today = fields.Date.context_today(Partner)
        birthdate = today - relativedelta(years=40)

        number = 99720007000

        while Partner.search([("club_id_number", "=", str(number))], limit=1):
            number += 1

        donor = Partner.create(
            {
                "name": "Cedente prueba estados no activos 430",
                "company_type": "person",
                "is_company": False,
                "club_person_type": "member",
                "club_id_number": str(number),
                "club_birthdate": fields.Date.to_string(birthdate),
                "club_join_date": today,
            }
        )

        receiver = Partner.create(
            {
                "name": "Receptor prueba estados 430",
                "company_type": "person",
                "is_company": False,
            }
        )

        source = Certificate.create(
            {
                "member_id": donor.id,
                "registration_origin": "migrated",
                "total_value": 5000.0,
                "opening_balance": 0.0,
            }
        )

        self.assertEqual(source.state, "active")

        # Preparacion interna exclusiva de la prueba.
        draft = (
            Transfer.sudo()
            .with_context(
                club_transfer_record_internal_token=(_TRANSFER_RECORD_INTERNAL_TOKEN)
            )
            .create(
                {
                    "source_certificate_id": source.id,
                    "recipient_person_id": receiver.id,
                    "effective_date": today,
                }
            )
        )

        self.assertEqual(draft.state, "draft")

        role = self.env.ref(
            "club_membership.group_club_certificate_payment_verification"
        )

        internal_group = self.env.ref("base.group_user")

        verifier = (
            self.env["res.users"]
            .sudo()
            .with_context(no_reset_password=True)
            .create(
                {
                    "name": "Verificador estados no activos 430",
                    "login": "club_transfer_states_verifier_430",
                    "groups_id": [(6, 0, [internal_group.id, role.id])],
                }
            )
        )

        # Simulacion controlada SOLO dentro del test.
        # SQL prepara estados historicos sin invocar
        # artificialmente el procedimiento institucional
        # de anulacion por alta erronea.
        for invalid_state in (
            "passive",
            "registration_error_void",
        ):
            source.flush_recordset(["state"])

            self.env.cr.execute(
                """
                UPDATE club_certificate
                   SET state = %s
                 WHERE id = %s
                """,
                (invalid_state, source.id),
            )

            source.invalidate_recordset(["state"])

            self.assertEqual(
                source.state,
                invalid_state,
            )

            # Ambos estados deben impedir que el
            # funcionario verifique documentalmente.
            with self.assertRaises(UserError):
                draft.with_user(verifier).action_register_payment_verification(
                    "ACTA-PAGO-430",
                    fully_paid_confirmed=True,
                )

            draft.invalidate_recordset()

            # El rechazo conserva intacto el tramite.
            self.assertEqual(draft.state, "draft")
            self.assertFalse(draft.payment_verified_by_id)
            self.assertFalse(draft.payment_verified_at)
            self.assertFalse(draft.payment_evidence_reference)
            self.assertFalse(draft.authorized_by_id)
            self.assertFalse(draft.executed_at)
            self.assertFalse(draft.recipient_certificate_id)

            source.invalidate_recordset(["state"])

            self.assertEqual(
                source.state,
                invalid_state,
            )

    def test_documentary_payment_not_inferred_from_opening_balance(self):
        """El saldo migrado no sustituye la verificacion documental."""
        from odoo.exceptions import ValidationError

        from ..models.certificate_transfer import (
            _TRANSFER_RECORD_INTERNAL_TOKEN,
        )

        admin = self.env.ref("base.user_admin")

        Partner = self.env["res.partner"].with_user(admin)
        Certificate = self.env["club.certificate"].with_user(admin)
        Transfer = self.env["club.certificate.transfer"]

        today = fields.Date.context_today(Partner)
        birthdate = today - relativedelta(years=40)

        role = self.env.ref(
            "club_membership.group_club_certificate_payment_verification"
        )
        internal_group = self.env.ref("base.group_user")

        verifier = (
            self.env["res.users"]
            .sudo()
            .with_context(no_reset_password=True)
            .create(
                {
                    "name": "Verificador saldos historicos 432",
                    "login": "club_transfer_balance_verifier_432",
                    "groups_id": [(6, 0, [internal_group.id, role.id])],
                }
            )
        )

        for ordinal, historical_balance in enumerate((0.0, 1250.0)):
            number = 99720008000 + ordinal

            while Partner.search([("club_id_number", "=", str(number))], limit=1):
                number += 2

            donor = Partner.create(
                {
                    "name": ("Cedente saldo historico 432 " + str(ordinal)),
                    "company_type": "person",
                    "is_company": False,
                    "club_person_type": "member",
                    "club_id_number": str(number),
                    "club_birthdate": fields.Date.to_string(birthdate),
                    "club_join_date": today,
                }
            )

            receiver = Partner.create(
                {
                    "name": ("Receptor saldo historico 432 " + str(ordinal)),
                    "company_type": "person",
                    "is_company": False,
                }
            )

            source = Certificate.create(
                {
                    "member_id": donor.id,
                    "registration_origin": "migrated",
                    "total_value": 5000.0,
                    "opening_balance": historical_balance,
                }
            )

            self.assertEqual(source.state, "active")

            initial_paid = source.opening_paid_amount

            self.assertAlmostEqual(
                source.opening_balance,
                historical_balance,
                places=2,
            )

            draft = (
                Transfer.sudo()
                .with_context(
                    club_transfer_record_internal_token=(
                        _TRANSFER_RECORD_INTERNAL_TOKEN
                    )
                )
                .create(
                    {
                        "source_certificate_id": source.id,
                        "recipient_person_id": receiver.id,
                        "effective_date": today,
                    }
                )
            )

            reference = "ACTA-PAGO-432-" + str(ordinal)

            # Independientemente del saldo historico,
            # nadie puede omitir la confirmacion expresa.
            with self.assertRaises(ValidationError):
                draft.with_user(verifier).action_register_payment_verification(
                    reference,
                    fully_paid_confirmed=False,
                )

            draft.invalidate_recordset()

            self.assertEqual(draft.state, "draft")
            self.assertFalse(draft.payment_verified_by_id)
            self.assertFalse(draft.payment_verified_at)
            self.assertFalse(draft.payment_evidence_reference)

            if historical_balance > 0:
                # El saldo es una fotografia historica.
                # Puede existir documentacion posterior
                # que confirme el pago completo.
                draft.with_user(verifier).action_register_payment_verification(
                    reference,
                    fully_paid_confirmed=True,
                )

                draft.invalidate_recordset()

                self.assertEqual(
                    draft.state,
                    "payment_verified",
                )
                self.assertEqual(
                    draft.payment_evidence_reference,
                    reference,
                )
                self.assertEqual(
                    draft.payment_verified_by_id.id,
                    verifier.id,
                )
                self.assertTrue(draft.payment_verified_at)

            # No se crean pagos ni se modifica el
            # saldo historico del certificado original.
            source.invalidate_recordset()

            self.assertAlmostEqual(
                source.opening_balance,
                historical_balance,
                places=2,
            )
            self.assertAlmostEqual(
                source.opening_paid_amount,
                initial_paid,
                places=2,
            )
            self.assertEqual(source.state, "active")

            # Nunca se ejecuta una transferencia.
            self.assertFalse(draft.authorized_by_id)
            self.assertFalse(draft.authorized_at)
            self.assertFalse(draft.executed_at)
            self.assertFalse(draft.recipient_certificate_id)

            self.assertFalse(Certificate.search([("member_id", "=", receiver.id)]))

    def test_only_one_verified_transfer_per_source_certificate(self):
        """Un Certificado no admite dos verificaciones vigentes."""
        from odoo.exceptions import UserError

        from ..models.certificate_transfer import (
            _TRANSFER_RECORD_INTERNAL_TOKEN,
        )

        admin = self.env.ref("base.user_admin")

        Partner = self.env["res.partner"].with_user(admin)
        Certificate = self.env["club.certificate"].with_user(admin)
        Transfer = self.env["club.certificate.transfer"]

        today = fields.Date.context_today(Partner)
        birthdate = today - relativedelta(years=40)

        number = 99720009000

        while Partner.search([("club_id_number", "=", str(number))], limit=1):
            number += 1

        donor = Partner.create(
            {
                "name": "Cedente doble verificacion 433",
                "company_type": "person",
                "is_company": False,
                "club_person_type": "member",
                "club_id_number": str(number),
                "club_birthdate": fields.Date.to_string(birthdate),
                "club_join_date": today,
            }
        )

        receiver_a = Partner.create(
            {
                "name": "Receptor A documental 433",
                "company_type": "person",
                "is_company": False,
            }
        )

        receiver_b = Partner.create(
            {
                "name": "Receptor B documental 433",
                "company_type": "person",
                "is_company": False,
            }
        )

        source = Certificate.create(
            {
                "member_id": donor.id,
                "registration_origin": "migrated",
                "total_value": 5000.0,
                "opening_balance": 0.0,
            }
        )

        self.assertEqual(source.state, "active")

        # Dos borradores apuntan al mismo Certificado.
        # Se crean exclusivamente para este escenario TDD.
        internal_transfer = Transfer.sudo().with_context(
            club_transfer_record_internal_token=(_TRANSFER_RECORD_INTERNAL_TOKEN)
        )

        draft_a = internal_transfer.create(
            {
                "source_certificate_id": source.id,
                "recipient_person_id": receiver_a.id,
                "effective_date": today,
            }
        )

        draft_b = internal_transfer.create(
            {
                "source_certificate_id": source.id,
                "recipient_person_id": receiver_b.id,
                "effective_date": today,
            }
        )

        self.assertEqual(draft_a.state, "draft")
        self.assertEqual(draft_b.state, "draft")

        self.assertEqual(
            draft_a.source_certificate_id.id,
            draft_b.source_certificate_id.id,
        )

        role = self.env.ref(
            "club_membership.group_club_certificate_payment_verification"
        )

        internal_group = self.env.ref("base.group_user")

        verifier = (
            self.env["res.users"]
            .sudo()
            .with_context(no_reset_password=True)
            .create(
                {
                    "name": "Verificador doble tramite 433",
                    "login": "club_transfer_duplicate_verifier_433",
                    "groups_id": [(6, 0, [internal_group.id, role.id])],
                }
            )
        )

        # Primer tramite: debe avanzar normalmente.
        draft_a.with_user(verifier).action_register_payment_verification(
            "ACTA-PAGO-433-A",
            fully_paid_confirmed=True,
        )

        draft_a.invalidate_recordset()

        self.assertEqual(
            draft_a.state,
            "payment_verified",
        )
        self.assertEqual(
            draft_a.payment_evidence_reference,
            "ACTA-PAGO-433-A",
        )
        self.assertEqual(
            draft_a.payment_verified_by_id.id,
            verifier.id,
        )

        # Segundo tramite: debe rechazarse porque
        # ya existe una verificacion vigente del mismo
        # Certificado original.
        with self.assertRaises(UserError):
            draft_b.with_user(verifier).action_register_payment_verification(
                "ACTA-PAGO-433-B",
                fully_paid_confirmed=True,
            )

        draft_a.invalidate_recordset()
        draft_b.invalidate_recordset()
        source.invalidate_recordset()

        # El tramite original conserva su evidencia.
        self.assertEqual(
            draft_a.state,
            "payment_verified",
        )
        self.assertEqual(
            draft_a.payment_evidence_reference,
            "ACTA-PAGO-433-A",
        )

        # El segundo tramite no cambia de etapa.
        self.assertEqual(draft_b.state, "draft")
        self.assertFalse(draft_b.payment_evidence_reference)
        self.assertFalse(draft_b.payment_verified_by_id)
        self.assertFalse(draft_b.payment_verified_at)

        # Ninguno autoriza ni ejecuta el patrimonio.
        self.assertFalse(draft_a.authorized_by_id)
        self.assertFalse(draft_b.authorized_by_id)
        self.assertFalse(draft_a.executed_at)
        self.assertFalse(draft_b.executed_at)
        self.assertFalse(draft_a.recipient_certificate_id)
        self.assertFalse(draft_b.recipient_certificate_id)

        self.assertEqual(source.state, "active")
        self.assertEqual(source.member_id.id, donor.id)

        self.assertFalse(
            Certificate.search(
                [
                    (
                        "member_id",
                        "in",
                        [
                            receiver_a.id,
                            receiver_b.id,
                        ],
                    )
                ]
            )
        )

    def test_cancelled_verified_transfer_releases_source(self):
        """Cancelar un tramite libera el origen sin borrar historia."""
        from ..models.certificate_transfer import (
            _TRANSFER_RECORD_INTERNAL_TOKEN,
        )

        admin = self.env.ref("base.user_admin")

        Partner = self.env["res.partner"].with_user(admin)
        Certificate = self.env["club.certificate"].with_user(admin)
        Transfer = self.env["club.certificate.transfer"]

        today = fields.Date.context_today(Partner)
        birthdate = today - relativedelta(years=40)

        number = 99720010000

        while Partner.search([("club_id_number", "=", str(number))], limit=1):
            number += 1

        donor = Partner.create(
            {
                "name": "Cedente cancelacion documental 437",
                "company_type": "person",
                "is_company": False,
                "club_person_type": "member",
                "club_id_number": str(number),
                "club_birthdate": fields.Date.to_string(birthdate),
                "club_join_date": today,
            }
        )

        receiver_a = Partner.create(
            {
                "name": "Receptor A cancelacion 437",
                "company_type": "person",
                "is_company": False,
            }
        )

        receiver_b = Partner.create(
            {
                "name": "Receptor B cancelacion 437",
                "company_type": "person",
                "is_company": False,
            }
        )

        source = Certificate.create(
            {
                "member_id": donor.id,
                "registration_origin": "migrated",
                "total_value": 5000.0,
                "opening_balance": 0.0,
            }
        )

        self.assertEqual(source.state, "active")

        # Preparar dos borradores exclusivamente
        # dentro de esta prueba automatizada.
        internal_transfer = Transfer.sudo().with_context(
            club_transfer_record_internal_token=(_TRANSFER_RECORD_INTERNAL_TOKEN)
        )

        draft_a = internal_transfer.create(
            {
                "source_certificate_id": source.id,
                "recipient_person_id": receiver_a.id,
                "effective_date": today,
            }
        )

        draft_b = internal_transfer.create(
            {
                "source_certificate_id": source.id,
                "recipient_person_id": receiver_b.id,
                "effective_date": today,
            }
        )

        role = self.env.ref(
            "club_membership.group_club_certificate_payment_verification"
        )

        internal_group = self.env.ref("base.group_user")

        verifier = (
            self.env["res.users"]
            .sudo()
            .with_context(no_reset_password=True)
            .create(
                {
                    "name": "Verificador cancelacion 437",
                    "login": "club_transfer_cancel_verifier_437",
                    "groups_id": [(6, 0, [internal_group.id, role.id])],
                }
            )
        )

        # Primera verificacion documental autorizada.
        draft_a.with_user(verifier).action_register_payment_verification(
            "ACTA-PAGO-437-A",
            fully_paid_confirmed=True,
        )

        draft_a.invalidate_recordset()

        self.assertEqual(
            draft_a.state,
            "payment_verified",
        )

        original_verifier = draft_a.payment_verified_by_id.id
        original_date = draft_a.payment_verified_at

        self.assertTrue(original_date)

        # Simular cancelacion EXCLUSIVAMENTE en el test.
        # Todavia no existe un procedimiento
        # institucional de cancelacion implementado.
        self.env.cr.execute(
            "UPDATE club_certificate_transfer SET state = %s WHERE id = %s",
            (
                "cancelled",
                draft_a.id,
            ),
        )
        draft_a.invalidate_recordset(["state"])

        draft_a.invalidate_recordset()

        self.assertEqual(draft_a.state, "cancelled")

        # La cancelacion conserva la evidencia original.
        self.assertEqual(
            draft_a.payment_evidence_reference,
            "ACTA-PAGO-437-A",
        )
        self.assertEqual(
            draft_a.payment_verified_by_id.id,
            original_verifier,
        )
        self.assertEqual(
            draft_a.payment_verified_at,
            original_date,
        )

        # Una nueva solicitud puede verificarse porque
        # el tramite anterior ya esta cancelado.
        draft_b.with_user(verifier).action_register_payment_verification(
            "ACTA-PAGO-437-B",
            fully_paid_confirmed=True,
        )

        draft_a.invalidate_recordset()
        draft_b.invalidate_recordset()
        source.invalidate_recordset()

        self.assertEqual(draft_a.state, "cancelled")

        self.assertEqual(
            draft_b.state,
            "payment_verified",
        )

        self.assertEqual(
            draft_b.payment_evidence_reference,
            "ACTA-PAGO-437-B",
        )

        self.assertEqual(
            draft_b.payment_verified_by_id.id,
            verifier.id,
        )

        self.assertTrue(draft_b.payment_verified_at)

        # No existe autorizacion ni ejecucion.
        self.assertFalse(draft_a.authorized_by_id)
        self.assertFalse(draft_b.authorized_by_id)
        self.assertFalse(draft_a.executed_at)
        self.assertFalse(draft_b.executed_at)
        self.assertFalse(draft_a.recipient_certificate_id)
        self.assertFalse(draft_b.recipient_certificate_id)

        # El Certificado original permanece intacto.
        self.assertEqual(source.state, "active")
        self.assertEqual(source.member_id.id, donor.id)

        self.assertFalse(
            Certificate.search(
                [
                    (
                        "member_id",
                        "in",
                        [
                            receiver_a.id,
                            receiver_b.id,
                        ],
                    )
                ]
            )
        )

    def test_transfer_cancellation_requires_audit_and_separate_role(self):
        """Cancelar exige auditoria y rol institucional independiente."""
        Transfer = self.env["club.certificate.transfer"]

        required_fields = {
            "cancellation_reason": "text",
            "cancelled_by_id": "many2one",
            "cancelled_at": "datetime",
        }

        for field_name, field_type in required_fields.items():
            self.assertIn(
                field_name,
                Transfer._fields,
                "Falta el campo de auditoria: " + field_name,
            )

            self.assertEqual(
                Transfer._fields[field_name].type,
                field_type,
                "Tipo incorrecto para " + field_name,
            )

        self.assertEqual(
            Transfer._fields["cancelled_by_id"].comodel_name,
            "res.users",
        )

        # La cancelacion necesita un grupo propio.
        cancellation_group = self.env.ref(
            "club_membership.group_club_certificate_transfer_cancellation",
            raise_if_not_found=False,
        )

        self.assertTrue(
            cancellation_group,
            "Falta el grupo institucional de cancelacion de transferencias.",
        )

        payment_group = self.env.ref(
            "club_membership.group_club_certificate_payment_verification"
        )

        self.assertNotEqual(
            cancellation_group.id,
            payment_group.id,
            "La cancelacion debe utilizar un grupo diferente del verificador de pagos.",
        )

        # Debe existir un procedimiento controlado.
        action = getattr(
            Transfer,
            "action_cancel_transfer",
            None,
        )

        self.assertTrue(
            callable(action),
            "Falta el procedimiento institucional de cancelacion de transferencias.",
        )

    def test_cancel_verified_transfer_requires_permission_and_audit(self):
        """La cancelacion conserva el historial y exige autoridad."""
        from odoo.exceptions import (
            AccessError,
            UserError,
            ValidationError,
        )

        from ..models.certificate_transfer import (
            _TRANSFER_RECORD_INTERNAL_TOKEN,
        )

        admin = self.env.ref("base.user_admin")

        Partner = self.env["res.partner"].with_user(admin)
        Certificate = self.env["club.certificate"].with_user(admin)
        Transfer = self.env["club.certificate.transfer"]

        today = fields.Date.context_today(Partner)
        birthdate = today - relativedelta(years=40)

        number = 99720011000

        while Partner.search([("club_id_number", "=", str(number))], limit=1):
            number += 1

        donor = Partner.create(
            {
                "name": "Cedente cancelacion funcional 445",
                "company_type": "person",
                "is_company": False,
                "club_person_type": "member",
                "club_id_number": str(number),
                "club_birthdate": fields.Date.to_string(birthdate),
                "club_join_date": today,
            }
        )

        receiver = Partner.create(
            {
                "name": "Receptor cancelacion funcional 445",
                "company_type": "person",
                "is_company": False,
            }
        )

        source = Certificate.create(
            {
                "member_id": donor.id,
                "registration_origin": "migrated",
                "total_value": 5000.0,
                "opening_balance": 0.0,
            }
        )

        self.assertEqual(source.state, "active")

        # Preparar el tramite mediante el mecanismo
        # interno exclusivamente para esta prueba.
        draft = (
            Transfer.sudo()
            .with_context(
                club_transfer_record_internal_token=(_TRANSFER_RECORD_INTERNAL_TOKEN)
            )
            .create(
                {
                    "source_certificate_id": source.id,
                    "recipient_person_id": receiver.id,
                    "effective_date": today,
                }
            )
        )

        self.assertEqual(draft.state, "draft")

        payment_group = self.env.ref(
            "club_membership.group_club_certificate_payment_verification"
        )

        cancellation_group = self.env.ref(
            "club_membership.group_club_certificate_transfer_cancellation"
        )

        internal_group = self.env.ref("base.group_user")

        Users = self.env["res.users"].sudo().with_context(no_reset_password=True)

        verifier = Users.create(
            {
                "name": "Verificador documental 445",
                "login": "club_transfer_verifier_445",
                "groups_id": [
                    (
                        6,
                        0,
                        [
                            internal_group.id,
                            payment_group.id,
                        ],
                    )
                ],
            }
        )

        canceller = Users.create(
            {
                "name": "Responsable cancelacion 445",
                "login": "club_transfer_canceller_445",
                "groups_id": [
                    (
                        6,
                        0,
                        [
                            internal_group.id,
                            cancellation_group.id,
                        ],
                    )
                ],
            }
        )

        self.assertFalse(
            verifier.has_group(
                "club_membership.group_club_certificate_transfer_cancellation"
            )
        )

        # ETAPA 1: verificacion documental.
        draft.with_user(verifier).action_register_payment_verification(
            "ACTA-PAGO-445",
            fully_paid_confirmed=True,
        )

        draft.invalidate_recordset()

        self.assertEqual(
            draft.state,
            "payment_verified",
        )

        original_reference = draft.payment_evidence_reference
        original_verifier = draft.payment_verified_by_id.id
        original_date = draft.payment_verified_at

        self.assertTrue(original_date)

        # Un verificador no puede cancelar solamente
        # por tener permiso de verificar pagos.
        with self.assertRaises(AccessError):
            draft.with_user(verifier).action_cancel_transfer(
                "Intento sin permiso de cancelacion"
            )

        # El funcionario autorizado necesita
        # un motivo institucional obligatorio.
        with self.assertRaises(ValidationError):
            draft.with_user(canceller).action_cancel_transfer("   ")

        # No se admiten datos estructurados que
        # intenten declarar otra identidad.
        with self.assertRaises(ValidationError):
            draft.with_user(canceller).action_cancel_transfer(
                {
                    "reason": "Motivo falso",
                    "cancelled_by_id": verifier.id,
                }
            )

        draft.invalidate_recordset()

        self.assertEqual(
            draft.state,
            "payment_verified",
        )

        self.assertFalse(draft.cancelled_by_id)
        self.assertFalse(draft.cancelled_at)
        self.assertFalse(draft.cancellation_reason)

        # ETAPA 2: cancelacion institucional valida.
        draft.with_user(canceller).action_cancel_transfer(
            "  Solicitud desistida formalmente  "
        )

        draft.invalidate_recordset()

        self.assertEqual(draft.state, "cancelled")

        self.assertEqual(
            draft.cancellation_reason,
            "Solicitud desistida formalmente",
        )

        self.assertEqual(
            draft.cancelled_by_id.id,
            canceller.id,
        )

        self.assertTrue(draft.cancelled_at)

        # La cancelacion no borra ni altera
        # la evidencia documental del pago.
        self.assertEqual(
            draft.payment_evidence_reference,
            original_reference,
        )

        self.assertEqual(
            draft.payment_verified_by_id.id,
            original_verifier,
        )

        self.assertEqual(
            draft.payment_verified_at,
            original_date,
        )

        original_cancellation_date = draft.cancelled_at

        # Una cancelacion ya efectuada
        # no puede repetirse ni reemplazarse.
        with self.assertRaises(UserError):
            draft.with_user(canceller).action_cancel_transfer(
                "Intento de reemplazar el motivo"
            )

        draft.invalidate_recordset()
        source.invalidate_recordset()

        self.assertEqual(draft.state, "cancelled")

        self.assertEqual(
            draft.cancellation_reason,
            "Solicitud desistida formalmente",
        )

        self.assertEqual(
            draft.cancelled_by_id.id,
            canceller.id,
        )

        self.assertEqual(
            draft.cancelled_at,
            original_cancellation_date,
        )

        # La cancelacion nunca autoriza ni ejecuta
        # una transferencia patrimonial.
        self.assertFalse(draft.authorized_by_id)
        self.assertFalse(draft.authorized_at)
        self.assertFalse(draft.executed_at)
        self.assertFalse(draft.recipient_certificate_id)

        # El Certificado original sigue perteneciendo
        # al cedente y mantiene su estado.
        self.assertEqual(source.state, "active")

        self.assertEqual(
            source.member_id.id,
            donor.id,
        )

        # El receptor no recibe un Certificado.
        self.assertFalse(Certificate.search([("member_id", "=", receiver.id)]))

    def test_cancellation_rejects_authorized_and_executed_transfers(self):
        """No cancelar tramites autorizados ni ejecutados."""
        from odoo.exceptions import UserError

        from ..models.certificate_transfer import (
            _TRANSFER_RECORD_INTERNAL_TOKEN,
        )

        admin = self.env.ref("base.user_admin")

        Partner = self.env["res.partner"].with_user(admin)
        Certificate = self.env["club.certificate"].with_user(admin)
        Transfer = self.env["club.certificate.transfer"]

        today = fields.Date.context_today(Partner)
        birthdate = today - relativedelta(years=40)

        number = 99720012000

        while Partner.search([("club_id_number", "=", str(number))], limit=1):
            number += 1

        donor = Partner.create(
            {
                "name": "Cedente estados protegidos 447",
                "company_type": "person",
                "is_company": False,
                "club_person_type": "member",
                "club_id_number": str(number),
                "club_birthdate": fields.Date.to_string(birthdate),
                "club_join_date": today,
            }
        )

        receiver = Partner.create(
            {
                "name": "Receptor estados protegidos 447",
                "company_type": "person",
                "is_company": False,
            }
        )

        source = Certificate.create(
            {
                "member_id": donor.id,
                "registration_origin": "migrated",
                "total_value": 5000.0,
                "opening_balance": 0.0,
            }
        )

        self.assertEqual(source.state, "active")

        internal_transfer = Transfer.sudo().with_context(
            club_transfer_record_internal_token=(_TRANSFER_RECORD_INTERNAL_TOKEN)
        )

        draft = internal_transfer.create(
            {
                "source_certificate_id": source.id,
                "recipient_person_id": receiver.id,
                "effective_date": today,
            }
        )

        cancellation_group = self.env.ref(
            "club_membership.group_club_certificate_transfer_cancellation"
        )
        internal_group = self.env.ref("base.group_user")

        canceller = (
            self.env["res.users"]
            .sudo()
            .with_context(no_reset_password=True)
            .create(
                {
                    "name": "Responsable estados protegidos 447",
                    "login": "club_transfer_states_canceller_447",
                    "groups_id": [
                        (
                            6,
                            0,
                            [
                                internal_group.id,
                                cancellation_group.id,
                            ],
                        )
                    ],
                }
            )
        )

        self.assertTrue(
            canceller.has_group(
                "club_membership.group_club_certificate_transfer_cancellation"
            )
        )

        # Simular un tramite autorizado EXCLUSIVAMENTE
        # como preparacion del escenario de prueba.
        # No constituye una autorizacion institucional real.
        verified_at = fields.Datetime.now()
        authorized_at = fields.Datetime.now()

        self.env.cr.execute(
            "UPDATE club_certificate_transfer SET payment_evidence_reference = %s, payment_verified_by_id = %s, payment_verified_at = %s, authorized_by_id = %s, authorized_at = %s, state = %s WHERE id = %s",
            (
                "ACTA-PAGO-447",
                admin.id,
                verified_at,
                admin.id,
                authorized_at,
                "authorized",
                draft.id,
            ),
        )
        draft.invalidate_recordset(
            [
                "payment_evidence_reference",
                "payment_verified_by_id",
                "payment_verified_at",
                "authorized_by_id",
                "authorized_at",
                "state",
            ]
        )

        draft.invalidate_recordset()

        self.assertEqual(draft.state, "authorized")

        # El funcionario tiene permiso de cancelacion,
        # pero NO puede cancelar algo ya autorizado.
        with self.assertRaises(UserError):
            draft.with_user(canceller).action_cancel_transfer(
                "Intento de cancelar tramite autorizado"
            )

        draft.invalidate_recordset()

        self.assertEqual(draft.state, "authorized")
        self.assertFalse(draft.cancellation_reason)
        self.assertFalse(draft.cancelled_by_id)
        self.assertFalse(draft.cancelled_at)

        self.assertEqual(
            draft.payment_evidence_reference,
            "ACTA-PAGO-447",
        )
        self.assertEqual(
            draft.authorized_by_id.id,
            admin.id,
        )
        self.assertEqual(
            draft.authorized_at,
            authorized_at,
        )

        # Simular el estado Ejecutado SOLO dentro
        # del test. No se realiza ninguna transferencia
        # patrimonial real ni se crea otro Certificado.
        executed_at = fields.Datetime.now()

        self.env.cr.execute(
            "UPDATE club_certificate_transfer SET state = %s, executed_at = %s WHERE id = %s",
            (
                "executed",
                executed_at,
                draft.id,
            ),
        )
        draft.invalidate_recordset(["state", "executed_at"])

        draft.invalidate_recordset()

        self.assertEqual(draft.state, "executed")

        # Tampoco puede cancelar un tramite ejecutado.
        with self.assertRaises(UserError):
            draft.with_user(canceller).action_cancel_transfer(
                "Intento de cancelar tramite ejecutado"
            )

        draft.invalidate_recordset()
        source.invalidate_recordset()

        self.assertEqual(draft.state, "executed")
        self.assertEqual(draft.executed_at, executed_at)

        self.assertFalse(draft.cancellation_reason)
        self.assertFalse(draft.cancelled_by_id)
        self.assertFalse(draft.cancelled_at)

        # La auditoria previa debe conservarse.
        self.assertEqual(
            draft.payment_evidence_reference,
            "ACTA-PAGO-447",
        )
        self.assertEqual(
            draft.payment_verified_by_id.id,
            admin.id,
        )
        self.assertEqual(
            draft.payment_verified_at,
            verified_at,
        )
        self.assertEqual(
            draft.authorized_by_id.id,
            admin.id,
        )
        self.assertEqual(
            draft.authorized_at,
            authorized_at,
        )

        # La prueba no debe transferir patrimonio.
        self.assertEqual(source.state, "active")
        self.assertEqual(source.member_id.id, donor.id)

        self.assertFalse(draft.recipient_certificate_id)

        self.assertFalse(Certificate.search([("member_id", "=", receiver.id)]))

    def test_cancel_draft_protects_audit_from_direct_writes(self):
        """Cancelar un borrador no habilita escrituras directas."""

        from ..models.certificate_transfer import (
            _TRANSFER_RECORD_INTERNAL_TOKEN,
        )

        admin = self.env.ref("base.user_admin")

        Partner = self.env["res.partner"].with_user(admin)
        Certificate = self.env["club.certificate"].with_user(admin)
        Transfer = self.env["club.certificate.transfer"]

        today = fields.Date.context_today(Partner)
        birthdate = today - relativedelta(years=40)

        number = 99720013000

        while Partner.search([("club_id_number", "=", str(number))], limit=1):
            number += 1

        donor = Partner.create(
            {
                "name": "Cedente cancelacion borrador 448",
                "company_type": "person",
                "is_company": False,
                "club_person_type": "member",
                "club_id_number": str(number),
                "club_birthdate": fields.Date.to_string(birthdate),
                "club_join_date": today,
            }
        )

        receiver = Partner.create(
            {
                "name": "Receptor cancelacion borrador 448",
                "company_type": "person",
                "is_company": False,
            }
        )

        source = Certificate.create(
            {
                "member_id": donor.id,
                "registration_origin": "migrated",
                "total_value": 5000.0,
                "opening_balance": 0.0,
            }
        )

        draft = (
            Transfer.sudo()
            .with_context(
                club_transfer_record_internal_token=(_TRANSFER_RECORD_INTERNAL_TOKEN)
            )
            .create(
                {
                    "source_certificate_id": source.id,
                    "recipient_person_id": receiver.id,
                    "effective_date": today,
                }
            )
        )

        self.assertEqual(draft.state, "draft")

        cancellation_group = self.env.ref(
            "club_membership.group_club_certificate_transfer_cancellation"
        )

        internal_group = self.env.ref("base.group_user")

        canceller = (
            self.env["res.users"]
            .sudo()
            .with_context(no_reset_password=True)
            .create(
                {
                    "name": "Responsable cancelacion borrador 448",
                    "login": "club_transfer_draft_canceller_448",
                    "groups_id": [
                        (
                            6,
                            0,
                            [
                                internal_group.id,
                                cancellation_group.id,
                            ],
                        )
                    ],
                }
            )
        )

        # El permiso de cancelar NO autoriza
        # escrituras directas sobre el modelo.
        with self.assertRaises(AccessError):
            draft.with_user(canceller).write(
                {
                    "state": "cancelled",
                }
            )

        draft.invalidate_recordset()
        self.assertEqual(draft.state, "draft")

        # La cancelacion valida debe realizarse
        # exclusivamente por el procedimiento.
        draft.with_user(canceller).action_cancel_transfer(
            "  Solicitud retirada antes de verificar pago  "
        )

        draft.invalidate_recordset()

        self.assertEqual(draft.state, "cancelled")
        self.assertEqual(
            draft.cancellation_reason,
            "Solicitud retirada antes de verificar pago",
        )
        self.assertEqual(
            draft.cancelled_by_id.id,
            canceller.id,
        )
        self.assertTrue(draft.cancelled_at)

        cancellation_date = draft.cancelled_at

        # Un borrador cancelado no inventa
        # una verificacion documental de pago.
        self.assertFalse(draft.payment_evidence_reference)
        self.assertFalse(draft.payment_verified_by_id)
        self.assertFalse(draft.payment_verified_at)

        # El responsable tampoco puede alterar
        # directamente su propia auditoria.
        with self.assertRaises(AccessError):
            draft.with_user(canceller).write(
                {
                    "cancellation_reason": "Motivo sustituido",
                }
            )

        with self.assertRaises(AccessError):
            draft.with_user(canceller).write(
                {
                    "cancelled_by_id": admin.id,
                }
            )

        draft.invalidate_recordset()
        source.invalidate_recordset()

        self.assertEqual(draft.state, "cancelled")
        self.assertEqual(
            draft.cancellation_reason,
            "Solicitud retirada antes de verificar pago",
        )
        self.assertEqual(
            draft.cancelled_by_id.id,
            canceller.id,
        )
        self.assertEqual(
            draft.cancelled_at,
            cancellation_date,
        )

        # No se autoriza ni ejecuta patrimonio.
        self.assertFalse(draft.authorized_by_id)
        self.assertFalse(draft.authorized_at)
        self.assertFalse(draft.executed_at)
        self.assertFalse(draft.recipient_certificate_id)

        self.assertEqual(source.state, "active")
        self.assertEqual(source.member_id.id, donor.id)

        self.assertFalse(Certificate.search([("member_id", "=", receiver.id)]))

    def test_institutional_cancellation_releases_source_for_new_verification(self):
        """Cancelar A permite verificar B y conserva la auditoria de A."""
        from odoo.exceptions import UserError

        from ..models.certificate_transfer import (
            _TRANSFER_RECORD_INTERNAL_TOKEN,
        )

        admin = self.env.ref("base.user_admin")
        Partner = self.env["res.partner"].with_user(admin)
        Certificate = self.env["club.certificate"].with_user(admin)
        Transfer = self.env["club.certificate.transfer"]

        today = fields.Date.context_today(Partner)
        birthdate = today - relativedelta(years=40)

        number = 99720014000
        while Partner.search([("club_id_number", "=", str(number))], limit=1):
            number += 1

        donor = Partner.create(
            {
                "name": "Cedente integridad 451",
                "company_type": "person",
                "is_company": False,
                "club_person_type": "member",
                "club_id_number": str(number),
                "club_birthdate": fields.Date.to_string(birthdate),
                "club_join_date": today,
            }
        )

        receiver_a = Partner.create(
            {
                "name": "Receptor transferencia A 451",
                "company_type": "person",
                "is_company": False,
            }
        )

        receiver_b = Partner.create(
            {
                "name": "Receptor transferencia B 451",
                "company_type": "person",
                "is_company": False,
            }
        )

        source = Certificate.create(
            {
                "member_id": donor.id,
                "registration_origin": "migrated",
                "total_value": 5000.0,
                "opening_balance": 0.0,
            }
        )

        self.assertEqual(source.state, "active")

        internal_transfer = Transfer.sudo().with_context(
            club_transfer_record_internal_token=(_TRANSFER_RECORD_INTERNAL_TOKEN)
        )

        first = internal_transfer.create(
            {
                "source_certificate_id": source.id,
                "recipient_person_id": receiver_a.id,
                "effective_date": today,
            }
        )

        second = internal_transfer.create(
            {
                "source_certificate_id": source.id,
                "recipient_person_id": receiver_b.id,
                "effective_date": today,
            }
        )

        self.assertEqual(first.state, "draft")
        self.assertEqual(second.state, "draft")

        internal_group = self.env.ref("base.group_user")

        verification_group = self.env.ref(
            "club_membership.group_club_certificate_payment_verification"
        )

        cancellation_group = self.env.ref(
            "club_membership.group_club_certificate_transfer_cancellation"
        )

        Users = self.env["res.users"].sudo().with_context(no_reset_password=True)

        verifier = Users.create(
            {
                "name": "Verificador integridad 451",
                "login": "club_integrity_verifier_451",
                "groups_id": [
                    (
                        6,
                        0,
                        [
                            internal_group.id,
                            verification_group.id,
                        ],
                    )
                ],
            }
        )

        canceller = Users.create(
            {
                "name": "Cancelador integridad 451",
                "login": "club_integrity_canceller_451",
                "groups_id": [
                    (
                        6,
                        0,
                        [
                            internal_group.id,
                            cancellation_group.id,
                        ],
                    )
                ],
            }
        )

        self.assertFalse(
            verifier.has_group(
                "club_membership.group_club_certificate_transfer_cancellation"
            )
        )

        # ETAPA 1: la transferencia A queda verificada.
        first.with_user(verifier).action_register_payment_verification(
            "ACTA-PAGO-A-451",
            fully_paid_confirmed=True,
        )

        first.invalidate_recordset()

        self.assertEqual(first.state, "payment_verified")

        evidence_a = first.payment_evidence_reference
        verifier_a = first.payment_verified_by_id.id
        verification_date_a = first.payment_verified_at

        self.assertEqual(evidence_a, "ACTA-PAGO-A-451")
        self.assertEqual(verifier_a, verifier.id)
        self.assertTrue(verification_date_a)

        # ETAPA 2: B no puede verificar el mismo
        # Certificado mientras A permanece vigente.
        with self.assertRaises(UserError):
            second.with_user(verifier).action_register_payment_verification(
                "ACTA-PAGO-B-451",
                fully_paid_confirmed=True,
            )

        second.invalidate_recordset()

        self.assertEqual(second.state, "draft")
        self.assertFalse(second.payment_verified_at)

        # ETAPA 3: cancelacion mediante procedimiento
        # institucional, sin modificar estados manualmente.
        first.with_user(canceller).action_cancel_transfer(
            "Desistimiento institucional documentado 451"
        )

        first.invalidate_recordset()

        self.assertEqual(first.state, "cancelled")
        self.assertEqual(
            first.cancelled_by_id.id,
            canceller.id,
        )
        self.assertTrue(first.cancelled_at)

        # La cancelacion conserva los datos de pago.
        self.assertEqual(
            first.payment_evidence_reference,
            evidence_a,
        )
        self.assertEqual(
            first.payment_verified_by_id.id,
            verifier_a,
        )
        self.assertEqual(
            first.payment_verified_at,
            verification_date_a,
        )

        # ETAPA 4: ahora B puede verificarse porque
        # A ya no mantiene el estado payment_verified.
        second.with_user(verifier).action_register_payment_verification(
            "ACTA-PAGO-B-451",
            fully_paid_confirmed=True,
        )

        first.invalidate_recordset()
        second.invalidate_recordset()
        source.invalidate_recordset()

        self.assertEqual(first.state, "cancelled")
        self.assertEqual(second.state, "payment_verified")

        self.assertEqual(
            second.payment_evidence_reference,
            "ACTA-PAGO-B-451",
        )
        self.assertEqual(
            second.payment_verified_by_id.id,
            verifier.id,
        )
        self.assertTrue(second.payment_verified_at)

        # Solo puede existir una transferencia vigente
        # con pago verificado para el Certificado.
        active_count = Transfer.sudo().search_count(
            [
                ("source_certificate_id", "=", source.id),
                (
                    "state",
                    "in",
                    [
                        "payment_verified",
                        "authorized",
                        "executed",
                    ],
                ),
            ]
        )

        self.assertEqual(active_count, 1)

        # A mantiene intacta su auditoria historica.
        self.assertEqual(
            first.payment_evidence_reference,
            evidence_a,
        )
        self.assertEqual(
            first.payment_verified_by_id.id,
            verifier_a,
        )
        self.assertEqual(
            first.payment_verified_at,
            verification_date_a,
        )
        self.assertEqual(
            first.cancellation_reason,
            "Desistimiento institucional documentado 451",
        )

        # No se efectua una transferencia patrimonial.
        self.assertEqual(source.state, "active")
        self.assertEqual(source.member_id.id, donor.id)

        self.assertFalse(first.recipient_certificate_id)
        self.assertFalse(second.recipient_certificate_id)

        self.assertFalse(
            Certificate.search(
                [
                    (
                        "member_id",
                        "in",
                        [
                            receiver_a.id,
                            receiver_b.id,
                        ],
                    )
                ]
            )
        )

    def test_database_rejects_two_live_transfers_for_same_source(self):
        """PostgreSQL impide dos tramites vigentes por Certificado."""
        from psycopg2.errors import UniqueViolation

        from ..models.certificate_transfer import (
            _TRANSFER_RECORD_INTERNAL_TOKEN,
        )

        admin = self.env.ref("base.user_admin")
        Partner = self.env["res.partner"].with_user(admin)
        Certificate = self.env["club.certificate"].with_user(admin)

        today = fields.Date.context_today(Partner)
        birthdate = today - relativedelta(years=40)

        number = 99720018000

        while Partner.search([("club_id_number", "=", str(number))], limit=1):
            number += 1

        donor = Partner.create(
            {
                "name": "Cedente unicidad SQL 460",
                "company_type": "person",
                "is_company": False,
                "club_person_type": "member",
                "club_id_number": str(number),
                "club_birthdate": fields.Date.to_string(birthdate),
                "club_join_date": today,
            }
        )

        receiver_a = Partner.create(
            {
                "name": "Receptor unicidad A 460",
                "company_type": "person",
                "is_company": False,
            }
        )

        receiver_b = Partner.create(
            {
                "name": "Receptor unicidad B 460",
                "company_type": "person",
                "is_company": False,
            }
        )

        source = Certificate.create(
            {
                "member_id": donor.id,
                "registration_origin": "migrated",
                "total_value": 5000.0,
                "opening_balance": 0.0,
            }
        )

        self.assertEqual(source.state, "active")

        # Token privado exclusivamente en el ensayo.
        # Esta prueba comprueba la restriccion SQL,
        # no registra pagos ni autoriza transferencias.
        Transfer = (
            self.env["club.certificate.transfer"]
            .sudo()
            .with_context(
                club_transfer_record_internal_token=(_TRANSFER_RECORD_INTERNAL_TOKEN)
            )
        )

        first = Transfer.create(
            {
                "source_certificate_id": source.id,
                "recipient_person_id": receiver_a.id,
                "effective_date": today,
            }
        )

        second = Transfer.create(
            {
                "source_certificate_id": source.id,
                "recipient_person_id": receiver_b.id,
                "effective_date": today,
            }
        )

        self.assertEqual(first.state, "draft")
        self.assertEqual(second.state, "draft")

        # Simular una verificacion existente,
        # solo para preparar el escenario SQL.
        self.env.cr.execute(
            "UPDATE club_certificate_transfer SET payment_evidence_reference = %s, payment_verified_by_id = %s, payment_verified_at = %s, state = %s WHERE id = %s",
            (
                "ENSAYO-SQL-A-460",
                admin.id,
                fields.Datetime.now(),
                "payment_verified",
                first.id,
            ),
        )
        first.invalidate_recordset(
            [
                "payment_evidence_reference",
                "payment_verified_by_id",
                "payment_verified_at",
                "state",
            ]
        )

        first.flush_recordset(
            [
                "source_certificate_id",
                "state",
            ]
        )

        self.assertEqual(first.state, "payment_verified")

        # La segunda escritura DEBE provocar
        # UniqueViolation en PostgreSQL.
        #
        # Usamos savepoint para recuperar correctamente
        # la transaccion de prueba tras el rechazo.
        with self.assertRaises(UniqueViolation):
            with self.env.cr.savepoint():
                self.env.cr.execute(
                    "UPDATE club_certificate_transfer SET payment_evidence_reference = %s, payment_verified_by_id = %s, payment_verified_at = %s, state = %s WHERE id = %s",
                    (
                        "ENSAYO-SQL-B-460",
                        admin.id,
                        fields.Datetime.now(),
                        "payment_verified",
                        second.id,
                    ),
                )
                second.invalidate_recordset(
                    [
                        "payment_evidence_reference",
                        "payment_verified_by_id",
                        "payment_verified_at",
                        "state",
                    ]
                )

                second.flush_recordset(
                    [
                        "source_certificate_id",
                        "state",
                    ]
                )

        # La escritura rechazada no debe persistir.
        second.invalidate_recordset()

        self.assertEqual(second.state, "draft")
        self.assertFalse(second.payment_verified_at)

        source.invalidate_recordset()

        self.assertEqual(source.state, "active")
        self.assertEqual(source.member_id.id, donor.id)

    def test_unique_violation_returns_controlled_payment_error(self):
        """Una colision SQL genera UserError sin alterar auditorias."""
        from odoo.exceptions import UserError

        from ..models.certificate_transfer import (
            _TRANSFER_RECORD_INTERNAL_TOKEN,
        )

        admin = self.env.ref("base.user_admin")
        Partner = self.env["res.partner"].with_user(admin)
        Certificate = self.env["club.certificate"].with_user(admin)

        today = fields.Date.context_today(Partner)
        birthdate = today - relativedelta(years=40)

        number = 99720019000
        while Partner.search([("club_id_number", "=", str(number))], limit=1):
            number += 1

        donor = Partner.create(
            {
                "name": "Cedente conflicto SQL 462",
                "company_type": "person",
                "is_company": False,
                "club_person_type": "member",
                "club_id_number": str(number),
                "club_birthdate": fields.Date.to_string(birthdate),
                "club_join_date": today,
            }
        )

        receiver_a = Partner.create(
            {
                "name": "Receptor conflicto A 462",
                "company_type": "person",
                "is_company": False,
            }
        )

        receiver_b = Partner.create(
            {
                "name": "Receptor conflicto B 462",
                "company_type": "person",
                "is_company": False,
            }
        )

        source = Certificate.create(
            {
                "member_id": donor.id,
                "registration_origin": "migrated",
                "total_value": 5000.0,
                "opening_balance": 0.0,
            }
        )

        Transfer = (
            self.env["club.certificate.transfer"]
            .sudo()
            .with_context(
                club_transfer_record_internal_token=(_TRANSFER_RECORD_INTERNAL_TOKEN)
            )
        )

        first = Transfer.create(
            {
                "source_certificate_id": source.id,
                "recipient_person_id": receiver_a.id,
                "effective_date": today,
            }
        )

        second = Transfer.create(
            {
                "source_certificate_id": source.id,
                "recipient_person_id": receiver_b.id,
                "effective_date": today,
            }
        )

        # Preparacion EXCLUSIVA del escenario de prueba.
        # No representa un pago monetario real.
        self.env.cr.execute(
            "UPDATE club_certificate_transfer SET payment_evidence_reference = %s, payment_verified_by_id = %s, payment_verified_at = %s, state = %s WHERE id = %s",
            (
                "ENSAYO-SQL-A-462",
                admin.id,
                fields.Datetime.now(),
                "payment_verified",
                first.id,
            ),
        )
        first.invalidate_recordset(
            [
                "payment_evidence_reference",
                "payment_verified_by_id",
                "payment_verified_at",
                "state",
            ]
        )

        first.flush_recordset(
            [
                "source_certificate_id",
                "state",
            ]
        )

        self.assertEqual(first.state, "payment_verified")
        self.assertEqual(second.state, "draft")

        # Exigir que exista el procedimiento privado
        # encargado de manejar el conflicto SQL.
        # Capacidad privada inyectada solo en el test de colision SQL.
        from ..models.certificate_transfer import (
            _TRANSFER_PAYMENT_STATE_INTERNAL_TOKEN,
        )

        second_for_sql_test = second.with_context(
            club_transfer_payment_state_internal_token=(
                _TRANSFER_PAYMENT_STATE_INTERNAL_TOKEN
            )
        )

        handler = getattr(
            second_for_sql_test,
            "_write_payment_verification_with_unique_guard",
            None,
        )

        self.assertTrue(
            callable(handler),
            "Falta el tratamiento controlado de la colision de unicidad PostgreSQL.",
        )

        # Invocar directamente el tramo de escritura:
        # asi probamos la colision real del indice SQL
        # sin que la comprobacion preliminar del metodo
        # publico la rechace antes de escribir.
        with self.assertRaises(UserError) as captured:
            handler(
                {
                    "payment_evidence_reference": "ENSAYO-SQL-B-462",
                    "payment_verified_by_id": admin.id,
                    "payment_verified_at": fields.Datetime.now(),
                }
            )

        self.assertIn(
            "certificado",
            str(captured.exception).lower(),
        )

        self.assertIn(
            "transferencia",
            str(captured.exception).lower(),
        )

        # La transaccion debe seguir utilizable
        # despues del conflicto controlado.
        second.invalidate_recordset()
        first.invalidate_recordset()
        source.invalidate_recordset()

        self.assertEqual(second.state, "draft")
        self.assertFalse(second.payment_evidence_reference)
        self.assertFalse(second.payment_verified_by_id)
        self.assertFalse(second.payment_verified_at)

        self.assertEqual(first.state, "payment_verified")
        self.assertEqual(
            first.payment_evidence_reference,
            "ENSAYO-SQL-A-462",
        )

        self.assertEqual(source.state, "active")
        self.assertEqual(source.member_id.id, donor.id)

        self.assertFalse(first.recipient_certificate_id)
        self.assertFalse(second.recipient_certificate_id)

    def test_authorization_rejects_current_member_without_side_effects(self):
        """Autorizar requiere rol propio, pago verificado y otro actor."""
        import uuid

        from odoo.exceptions import UserError

        from ..models.certificate_transfer import (
            _TRANSFER_RECORD_INTERNAL_TOKEN,
        )

        # Primero comprobar el nuevo grupo institucional.
        authorization_xmlid = (
            "club_membership.group_club_certificate_transfer_authorization"
        )

        authorization_group = self.env.ref(
            authorization_xmlid,
            raise_if_not_found=False,
        )

        self.assertTrue(
            authorization_group,
            "Falta el grupo institucional de autorizacion "
            "de transferencias patrimoniales.",
        )

        Transfer = self.env["club.certificate.transfer"]

        self.assertTrue(
            callable(
                getattr(
                    Transfer,
                    "action_authorize_transfer",
                    None,
                )
            ),
            "Falta action_authorize_transfer().",
        )

        admin = self.env.ref("base.user_admin")
        Partner = self.env["res.partner"].with_user(admin)
        Certificate = self.env["club.certificate"].with_user(admin)

        payment_group = self.env.ref(
            "club_membership.group_club_certificate_payment_verification"
        )

        internal_group = self.env.ref("base.group_user")

        suffix = uuid.uuid4().hex[:12]

        Users = self.env["res.users"].sudo().with_context(no_reset_password=True)

        # El verificador pertenece deliberadamente a
        # ambos grupos. Aun asi, NO puede aprobar
        # una verificacion que el mismo realizo.
        verifier = Users.create(
            {
                "name": "Ensayo 471 - Verificador",
                "login": "club_auth_471_verify_" + suffix,
                "groups_id": [
                    (
                        6,
                        0,
                        [
                            internal_group.id,
                            payment_group.id,
                            authorization_group.id,
                        ],
                    )
                ],
            }
        )

        authorizer = Users.create(
            {
                "name": "Ensayo 471 - Autorizador",
                "login": "club_auth_471_authorize_" + suffix,
                "groups_id": [
                    (
                        6,
                        0,
                        [
                            internal_group.id,
                            authorization_group.id,
                        ],
                    )
                ],
            }
        )

        observer = Users.create(
            {
                "name": "Ensayo 471 - Sin autorizacion",
                "login": "club_auth_471_observer_" + suffix,
                "groups_id": [
                    (
                        6,
                        0,
                        [
                            internal_group.id,
                        ],
                    )
                ],
            }
        )

        self.assertTrue(
            verifier.has_group(
                "club_membership.group_club_certificate_payment_verification"
            )
        )

        self.assertTrue(verifier.has_group(authorization_xmlid))

        self.assertTrue(authorizer.has_group(authorization_xmlid))

        self.assertFalse(observer.has_group(authorization_xmlid))

        today = fields.Date.context_today(Partner)

        birthdate = today - relativedelta(years=40)
        number = 99720021000

        while Partner.search([("club_id_number", "=", str(number))], limit=1):
            number += 1

        donor = Partner.create(
            {
                "name": "Cedente autorizacion institucional 471",
                "company_type": "person",
                "is_company": False,
                "club_person_type": "member",
                "club_id_number": str(number),
                "club_birthdate": fields.Date.to_string(birthdate),
                "club_join_date": today,
            }
        )

        recipient = Partner.create(
            {
                "club_person_type": "member",
                "club_join_date": fields.Date.context_today(Partner),
                "club_id_number": str(99000000000 + int(suffix[:6], 16)),
                "club_birthdate": fields.Date.to_string(
                    fields.Date.context_today(Partner) - relativedelta(years=35)
                ),
                "name": "Receptor autorizacion institucional 471",
                "company_type": "person",
                "is_company": False,
            }
        )

        source = Certificate.create(
            {
                "member_id": donor.id,
                "registration_origin": "migrated",
                "total_value": 5000.0,
                "opening_balance": 0.0,
            }
        )

        self.assertEqual(source.state, "active")

        # El token privado solo se utiliza para
        # crear el registro dentro de esta prueba.
        internal_transfer = Transfer.sudo().with_context(
            club_transfer_record_internal_token=(_TRANSFER_RECORD_INTERNAL_TOKEN)
        )

        created = internal_transfer.create(
            {
                "source_certificate_id": source.id,
                "recipient_person_id": recipient.id,
                "effective_date": today,
            }
        )

        # Volver a obtener el tramite SIN token privado.
        transfer = Transfer.browse(created.id)

        _certificate_count = Certificate.sudo().search_count([])

        self.assertEqual(transfer.state, "draft")
        self.assertFalse(transfer.authorized_by_id)
        self.assertFalse(transfer.authorized_at)

        # 1. No se autoriza un Borrador.
        with self.assertRaises(UserError):
            transfer.with_user(authorizer).action_authorize_transfer()

        self.assertEqual(transfer.state, "draft")

        # 2. Verificacion documental real por
        # un funcionario identificado.
        transfer.with_user(verifier).action_register_payment_verification(
            "ACTA-PAGO-471",
            fully_paid_confirmed=True,
        )

        transfer.invalidate_recordset()

        self.assertEqual(
            transfer.state,
            "payment_verified",
        )

        self.assertEqual(
            transfer.payment_verified_by_id.id,
            verifier.id,
        )

        self.assertEqual(
            transfer.payment_evidence_reference,
            "ACTA-PAGO-471",
        )

        original_verified_at = transfer.payment_verified_at

        self.assertTrue(original_verified_at)

        # F10-I: el receptor del ensayo ya es Socio.
        self.assertEqual(recipient.club_person_type, "member")

        transfer.invalidate_recordset()
        source.invalidate_recordset()

        self.assertEqual(transfer.state, "payment_verified")
        self.assertEqual(
            transfer.recipient_person_id.id,
            recipient.id,
        )

        original_evidence = transfer.payment_evidence_reference
        original_verifier = transfer.payment_verified_by_id.id
        original_verified_at = transfer.payment_verified_at
        original_source_state = source.state
        original_source_owner = source.member_id.id
        original_certificate_count = Certificate.sudo().search_count([])

        from odoo.exceptions import ValidationError

        # Rechazo institucional, no solo validacion directa.
        with self.assertRaisesRegex(
            ValidationError,
            "ya es Socio vigente",
        ):
            transfer.with_user(authorizer).action_authorize_transfer()

        transfer.invalidate_recordset()
        source.invalidate_recordset()

        # El tramite debe permanecer sin autorizacion.
        self.assertEqual(transfer.state, "payment_verified")
        self.assertFalse(transfer.authorized_by_id)
        self.assertFalse(transfer.authorized_at)
        self.assertFalse(transfer.executed_by_id)
        self.assertFalse(transfer.executed_at)
        self.assertFalse(transfer.recipient_certificate_id)

        # La evidencia documental conserva su autoria.
        self.assertEqual(
            transfer.payment_evidence_reference,
            original_evidence,
        )
        self.assertEqual(
            transfer.payment_verified_by_id.id,
            original_verifier,
        )
        self.assertEqual(
            transfer.payment_verified_at,
            original_verified_at,
        )

        # El patrimonio original permanece intacto.
        self.assertEqual(source.state, original_source_state)
        self.assertEqual(source.member_id.id, original_source_owner)
        self.assertEqual(
            Certificate.sudo().search_count([]),
            original_certificate_count,
        )

    def test_authorization_rejects_blocked_family_beneficiary(self):
        """Autorizar requiere rol propio, pago verificado y otro actor."""
        import uuid

        from odoo.exceptions import UserError

        from ..models.certificate_transfer import (
            _TRANSFER_RECORD_INTERNAL_TOKEN,
        )

        # Primero comprobar el nuevo grupo institucional.
        authorization_xmlid = (
            "club_membership.group_club_certificate_transfer_authorization"
        )

        authorization_group = self.env.ref(
            authorization_xmlid,
            raise_if_not_found=False,
        )

        self.assertTrue(
            authorization_group,
            "Falta el grupo institucional de autorizacion "
            "de transferencias patrimoniales.",
        )

        Transfer = self.env["club.certificate.transfer"]

        self.assertTrue(
            callable(
                getattr(
                    Transfer,
                    "action_authorize_transfer",
                    None,
                )
            ),
            "Falta action_authorize_transfer().",
        )

        admin = self.env.ref("base.user_admin")
        Partner = self.env["res.partner"].with_user(admin)
        Certificate = self.env["club.certificate"].with_user(admin)

        payment_group = self.env.ref(
            "club_membership.group_club_certificate_payment_verification"
        )

        internal_group = self.env.ref("base.group_user")

        suffix = uuid.uuid4().hex[:12]

        Users = self.env["res.users"].sudo().with_context(no_reset_password=True)

        # El verificador pertenece deliberadamente a
        # ambos grupos. Aun asi, NO puede aprobar
        # una verificacion que el mismo realizo.
        verifier = Users.create(
            {
                "name": "Ensayo 471 - Verificador",
                "login": "club_auth_471_verify_" + suffix,
                "groups_id": [
                    (
                        6,
                        0,
                        [
                            internal_group.id,
                            payment_group.id,
                            authorization_group.id,
                        ],
                    )
                ],
            }
        )

        authorizer = Users.create(
            {
                "name": "Ensayo 471 - Autorizador",
                "login": "club_auth_471_authorize_" + suffix,
                "groups_id": [
                    (
                        6,
                        0,
                        [
                            internal_group.id,
                            authorization_group.id,
                        ],
                    )
                ],
            }
        )

        observer = Users.create(
            {
                "name": "Ensayo 471 - Sin autorizacion",
                "login": "club_auth_471_observer_" + suffix,
                "groups_id": [
                    (
                        6,
                        0,
                        [
                            internal_group.id,
                        ],
                    )
                ],
            }
        )

        self.assertTrue(
            verifier.has_group(
                "club_membership.group_club_certificate_payment_verification"
            )
        )

        self.assertTrue(verifier.has_group(authorization_xmlid))

        self.assertTrue(authorizer.has_group(authorization_xmlid))

        self.assertFalse(observer.has_group(authorization_xmlid))

        today = fields.Date.context_today(Partner)

        birthdate = today - relativedelta(years=40)
        number = 99720021000

        while Partner.search([("club_id_number", "=", str(number))], limit=1):
            number += 1

        donor = Partner.create(
            {
                "name": "Cedente autorizacion institucional 471",
                "company_type": "person",
                "is_company": False,
                "club_person_type": "member",
                "club_id_number": str(number),
                "club_birthdate": fields.Date.to_string(birthdate),
                "club_join_date": today,
            }
        )

        recipient = Partner.create(
            {
                "name": "Receptor autorizacion institucional 471",
                "company_type": "person",
                "is_company": False,
            }
        )

        source = Certificate.create(
            {
                "member_id": donor.id,
                "registration_origin": "migrated",
                "total_value": 5000.0,
                "opening_balance": 0.0,
            }
        )

        self.assertEqual(source.state, "active")

        # El token privado solo se utiliza para
        # crear el registro dentro de esta prueba.
        internal_transfer = Transfer.sudo().with_context(
            club_transfer_record_internal_token=(_TRANSFER_RECORD_INTERNAL_TOKEN)
        )

        created = internal_transfer.create(
            {
                "source_certificate_id": source.id,
                "recipient_person_id": recipient.id,
                "effective_date": today,
            }
        )

        # Volver a obtener el tramite SIN token privado.
        transfer = Transfer.browse(created.id)

        _certificate_count = Certificate.sudo().search_count([])

        self.assertEqual(transfer.state, "draft")
        self.assertFalse(transfer.authorized_by_id)
        self.assertFalse(transfer.authorized_at)

        # 1. No se autoriza un Borrador.
        with self.assertRaises(UserError):
            transfer.with_user(authorizer).action_authorize_transfer()

        self.assertEqual(transfer.state, "draft")

        # 2. Verificacion documental real por
        # un funcionario identificado.
        transfer.with_user(verifier).action_register_payment_verification(
            "ACTA-PAGO-471",
            fully_paid_confirmed=True,
        )

        transfer.invalidate_recordset()

        self.assertEqual(
            transfer.state,
            "payment_verified",
        )

        self.assertEqual(
            transfer.payment_verified_by_id.id,
            verifier.id,
        )

        self.assertEqual(
            transfer.payment_evidence_reference,
            "ACTA-PAGO-471",
        )

        original_verified_at = transfer.payment_verified_at

        self.assertTrue(original_verified_at)

        # Persona receptora: no es Socio y es familiar del cedente.
        recipient_number = number + 1
        while Partner.search([("club_id_number", "=", str(recipient_number))], limit=1):
            recipient_number += 1

        recipient.write(
            {
                "club_id_number": str(recipient_number),
                "club_birthdate": fields.Date.to_string(
                    today - relativedelta(years=30)
                ),
            }
        )

        self.assertNotEqual(recipient.club_person_type, "member")

        # Utilizar el parentesco existente, sin agregar categorias.
        beneficiary = (
            self.env["club.beneficiary"]
            .sudo()
            .create(
                {
                    "member_id": donor.id,
                    "person_id": recipient.id,
                    "relationship": "spouse",
                    "start_date": today,
                }
            )
        )

        self.assertEqual(beneficiary.state, "active")

        # Bloqueo administrativo valido, registrado antes del intento.
        beneficiary.write(
            {
                "state": "blocked",
                "block_reason": "Bloqueo administrativo F10-L",
            }
        )

        self.assertEqual(beneficiary.state, "blocked")
        self.assertEqual(transfer.state, "payment_verified")
        self.assertEqual(source.state, "active")

        original_evidence = transfer.payment_evidence_reference
        original_verified_by = transfer.payment_verified_by_id.id
        original_verified_at = transfer.payment_verified_at
        original_count = Certificate.sudo().search_count([])

        from odoo.exceptions import ValidationError

        # Este rechazo es el nuevo requisito funcional.
        with self.assertRaisesRegex(ValidationError, "Beneficiario bloqueado"):
            transfer.with_user(authorizer).action_authorize_transfer()

        transfer.invalidate_recordset()
        source.invalidate_recordset()
        beneficiary.invalidate_recordset()

        self.assertEqual(transfer.state, "payment_verified")
        self.assertFalse(transfer.authorized_by_id)
        self.assertFalse(transfer.authorized_at)
        self.assertFalse(transfer.executed_at)
        self.assertFalse(transfer.recipient_certificate_id)

        self.assertEqual(transfer.payment_evidence_reference, original_evidence)
        self.assertEqual(transfer.payment_verified_by_id.id, original_verified_by)
        self.assertEqual(transfer.payment_verified_at, original_verified_at)
        self.assertEqual(source.state, "active")
        self.assertEqual(source.member_id.id, donor.id)
        self.assertEqual(beneficiary.state, "blocked")
        self.assertEqual(Certificate.sudo().search_count([]), original_count)

    def test_authorization_rejects_recipient_without_family_link(self):
        """Autorizar requiere rol propio, pago verificado y otro actor."""
        import uuid

        from odoo.exceptions import AccessError, UserError

        from ..models.certificate_transfer import (
            _TRANSFER_RECORD_INTERNAL_TOKEN,
        )

        # Primero comprobar el nuevo grupo institucional.
        authorization_xmlid = (
            "club_membership.group_club_certificate_transfer_authorization"
        )

        authorization_group = self.env.ref(
            authorization_xmlid,
            raise_if_not_found=False,
        )

        self.assertTrue(
            authorization_group,
            "Falta el grupo institucional de autorizacion "
            "de transferencias patrimoniales.",
        )

        Transfer = self.env["club.certificate.transfer"]

        self.assertTrue(
            callable(
                getattr(
                    Transfer,
                    "action_authorize_transfer",
                    None,
                )
            ),
            "Falta action_authorize_transfer().",
        )

        admin = self.env.ref("base.user_admin")
        Partner = self.env["res.partner"].with_user(admin)
        Certificate = self.env["club.certificate"].with_user(admin)

        payment_group = self.env.ref(
            "club_membership.group_club_certificate_payment_verification"
        )

        internal_group = self.env.ref("base.group_user")

        suffix = uuid.uuid4().hex[:12]

        Users = self.env["res.users"].sudo().with_context(no_reset_password=True)

        # El verificador pertenece deliberadamente a
        # ambos grupos. Aun asi, NO puede aprobar
        # una verificacion que el mismo realizo.
        verifier = Users.create(
            {
                "name": "Ensayo 471 - Verificador",
                "login": "club_auth_471_verify_" + suffix,
                "groups_id": [
                    (
                        6,
                        0,
                        [
                            internal_group.id,
                            payment_group.id,
                            authorization_group.id,
                        ],
                    )
                ],
            }
        )

        authorizer = Users.create(
            {
                "name": "Ensayo 471 - Autorizador",
                "login": "club_auth_471_authorize_" + suffix,
                "groups_id": [
                    (
                        6,
                        0,
                        [
                            internal_group.id,
                            authorization_group.id,
                        ],
                    )
                ],
            }
        )

        observer = Users.create(
            {
                "name": "Ensayo 471 - Sin autorizacion",
                "login": "club_auth_471_observer_" + suffix,
                "groups_id": [
                    (
                        6,
                        0,
                        [
                            internal_group.id,
                        ],
                    )
                ],
            }
        )

        self.assertTrue(
            verifier.has_group(
                "club_membership.group_club_certificate_payment_verification"
            )
        )

        self.assertTrue(verifier.has_group(authorization_xmlid))

        self.assertTrue(authorizer.has_group(authorization_xmlid))

        self.assertFalse(observer.has_group(authorization_xmlid))

        today = fields.Date.context_today(Partner)

        birthdate = today - relativedelta(years=40)
        number = 99720021000

        while Partner.search([("club_id_number", "=", str(number))], limit=1):
            number += 1

        donor = Partner.create(
            {
                "name": "Cedente autorizacion institucional 471",
                "company_type": "person",
                "is_company": False,
                "club_person_type": "member",
                "club_id_number": str(number),
                "club_birthdate": fields.Date.to_string(birthdate),
                "club_join_date": today,
            }
        )

        recipient = Partner.create(
            {
                "name": "Receptor autorizacion institucional 471",
                "company_type": "person",
                "is_company": False,
            }
        )

        source = Certificate.create(
            {
                "member_id": donor.id,
                "registration_origin": "migrated",
                "total_value": 5000.0,
                "opening_balance": 0.0,
            }
        )

        self.assertEqual(source.state, "active")

        # El token privado solo se utiliza para
        # crear el registro dentro de esta prueba.
        internal_transfer = Transfer.sudo().with_context(
            club_transfer_record_internal_token=(_TRANSFER_RECORD_INTERNAL_TOKEN)
        )

        created = internal_transfer.create(
            {
                "source_certificate_id": source.id,
                "recipient_person_id": recipient.id,
                "effective_date": today,
            }
        )

        # Volver a obtener el tramite SIN token privado.
        transfer = Transfer.browse(created.id)

        _certificate_count = Certificate.sudo().search_count([])

        self.assertEqual(transfer.state, "draft")
        self.assertFalse(transfer.authorized_by_id)
        self.assertFalse(transfer.authorized_at)

        # 1. No se autoriza un Borrador.
        with self.assertRaises(UserError):
            transfer.with_user(authorizer).action_authorize_transfer()

        self.assertEqual(transfer.state, "draft")

        # 2. Verificacion documental real por
        # un funcionario identificado.
        transfer.with_user(verifier).action_register_payment_verification(
            "ACTA-PAGO-471",
            fully_paid_confirmed=True,
        )

        transfer.invalidate_recordset()

        self.assertEqual(
            transfer.state,
            "payment_verified",
        )

        self.assertEqual(
            transfer.payment_verified_by_id.id,
            verifier.id,
        )

        self.assertEqual(
            transfer.payment_evidence_reference,
            "ACTA-PAGO-471",
        )

        original_verified_at = transfer.payment_verified_at

        self.assertTrue(original_verified_at)

        # 3. Usuario sin rol no autoriza.
        with self.assertRaises(AccessError):
            transfer.with_user(observer).action_authorize_transfer()

        # 4. Quien verifico NO puede autorizar,
        # aunque tenga ambos grupos.
        with self.assertRaises(UserError):
            transfer.with_user(verifier).action_authorize_transfer()

        transfer.invalidate_recordset()

        self.assertEqual(
            transfer.state,
            "payment_verified",
        )

        self.assertFalse(transfer.authorized_by_id)
        self.assertFalse(transfer.authorized_at)

        # Receptor distinto del cedente, no Socio.
        self.assertNotEqual(recipient.id, donor.id)
        self.assertNotEqual(recipient.club_person_type, "member")

        # Ausencia de parentesco registrado con el cedente.
        self.assertFalse(
            self.env["club.beneficiary"]
            .sudo()
            .search(
                [
                    ("member_id", "=", donor.id),
                    ("person_id", "=", recipient.id),
                ],
                limit=1,
            )
        )

        transfer.invalidate_recordset()
        source.invalidate_recordset()

        self.assertEqual(transfer.state, "payment_verified")
        self.assertEqual(source.state, "active")

        original_evidence = transfer.payment_evidence_reference
        original_verifier = transfer.payment_verified_by_id.id
        original_verified_at = transfer.payment_verified_at
        original_count = Certificate.sudo().search_count([])

        from odoo.exceptions import ValidationError

        # TDD ROJO: aun falta exigir el vinculo familiar.
        with self.assertRaisesRegex(ValidationError, "vínculo familiar"):
            transfer.with_user(authorizer).action_authorize_transfer()

        transfer.invalidate_recordset()
        source.invalidate_recordset()

        self.assertEqual(transfer.state, "payment_verified")
        self.assertFalse(transfer.authorized_by_id)
        self.assertFalse(transfer.authorized_at)
        self.assertFalse(transfer.executed_at)
        self.assertFalse(transfer.recipient_certificate_id)
        self.assertEqual(transfer.payment_evidence_reference, original_evidence)
        self.assertEqual(transfer.payment_verified_by_id.id, original_verifier)
        self.assertEqual(transfer.payment_verified_at, original_verified_at)
        self.assertEqual(source.state, "active")
        self.assertEqual(source.member_id.id, donor.id)
        self.assertEqual(Certificate.sudo().search_count([]), original_count)

    def test_authorization_accepts_finalized_family_link_without_reactivation(self):
        """Autorizar requiere rol propio, pago verificado y otro actor."""
        import uuid

        from odoo.exceptions import AccessError, UserError

        from ..models.certificate_transfer import (
            _TRANSFER_RECORD_INTERNAL_TOKEN,
        )

        # Primero comprobar el nuevo grupo institucional.
        authorization_xmlid = (
            "club_membership.group_club_certificate_transfer_authorization"
        )

        authorization_group = self.env.ref(
            authorization_xmlid,
            raise_if_not_found=False,
        )

        self.assertTrue(
            authorization_group,
            "Falta el grupo institucional de autorizacion "
            "de transferencias patrimoniales.",
        )

        Transfer = self.env["club.certificate.transfer"]

        self.assertTrue(
            callable(
                getattr(
                    Transfer,
                    "action_authorize_transfer",
                    None,
                )
            ),
            "Falta action_authorize_transfer().",
        )

        admin = self.env.ref("base.user_admin")
        Partner = self.env["res.partner"].with_user(admin)
        Certificate = self.env["club.certificate"].with_user(admin)

        payment_group = self.env.ref(
            "club_membership.group_club_certificate_payment_verification"
        )

        internal_group = self.env.ref("base.group_user")

        suffix = uuid.uuid4().hex[:12]

        Users = self.env["res.users"].sudo().with_context(no_reset_password=True)

        # El verificador pertenece deliberadamente a
        # ambos grupos. Aun asi, NO puede aprobar
        # una verificacion que el mismo realizo.
        verifier = Users.create(
            {
                "name": "Ensayo 471 - Verificador",
                "login": "club_auth_471_verify_" + suffix,
                "groups_id": [
                    (
                        6,
                        0,
                        [
                            internal_group.id,
                            payment_group.id,
                            authorization_group.id,
                        ],
                    )
                ],
            }
        )

        authorizer = Users.create(
            {
                "name": "Ensayo 471 - Autorizador",
                "login": "club_auth_471_authorize_" + suffix,
                "groups_id": [
                    (
                        6,
                        0,
                        [
                            internal_group.id,
                            authorization_group.id,
                        ],
                    )
                ],
            }
        )

        observer = Users.create(
            {
                "name": "Ensayo 471 - Sin autorizacion",
                "login": "club_auth_471_observer_" + suffix,
                "groups_id": [
                    (
                        6,
                        0,
                        [
                            internal_group.id,
                        ],
                    )
                ],
            }
        )

        self.assertTrue(
            verifier.has_group(
                "club_membership.group_club_certificate_payment_verification"
            )
        )

        self.assertTrue(verifier.has_group(authorization_xmlid))

        self.assertTrue(authorizer.has_group(authorization_xmlid))

        self.assertFalse(observer.has_group(authorization_xmlid))

        today = fields.Date.context_today(Partner)

        birthdate = today - relativedelta(years=40)
        number = 99720021000

        while Partner.search([("club_id_number", "=", str(number))], limit=1):
            number += 1

        donor = Partner.create(
            {
                "name": "Cedente autorizacion institucional 471",
                "company_type": "person",
                "is_company": False,
                "club_person_type": "member",
                "club_id_number": str(number),
                "club_birthdate": fields.Date.to_string(birthdate),
                "club_join_date": today,
            }
        )

        recipient = Partner.create(
            {
                "name": "Receptor autorizacion institucional 471",
                "company_type": "person",
                "is_company": False,
            }
        )

        # F10-Q: parentesco sintetico para autorizacion positiva.
        # No modifica personas, parentescos ni certificados reales.
        self.assertNotEqual(recipient.club_person_type, "member")

        _f10q_values = {}

        if not recipient.club_id_number:
            _f10q_ci = 99500000000 + recipient.id
            while Partner.search([("club_id_number", "=", str(_f10q_ci))], limit=1):
                _f10q_ci += 1
            _f10q_values["club_id_number"] = str(_f10q_ci)

        if not recipient.club_birthdate:
            _f10q_values["club_birthdate"] = fields.Date.to_string(
                fields.Date.context_today(Partner) - relativedelta(years=35)
            )

        if _f10q_values:
            recipient.write(_f10q_values)

        _f10q_family_link = (
            self.env["club.beneficiary"]
            .sudo()
            .create(
                {
                    "member_id": donor.id,
                    "person_id": recipient.id,
                    "relationship": "spouse",
                    "start_date": fields.Date.context_today(Partner),
                }
            )
        )

        self.assertEqual(_f10q_family_link.state, "active")
        self.assertEqual(_f10q_family_link.member_id.id, donor.id)
        self.assertEqual(_f10q_family_link.person_id.id, recipient.id)

        # F10-R: terminar el vinculo con el procedimiento real.
        _f10q_family_link.finalize_link(
            end_date=fields.Date.context_today(Partner),
            reason="Finalizacion historica de ensayo F10-R",
        )
        _f10q_family_link.invalidate_recordset()
        self.assertEqual(_f10q_family_link.state, "finalized")
        _historical_end_date = _f10q_family_link.end_date
        _historical_end_reason = _f10q_family_link.end_reason
        self.assertTrue(_historical_end_date)
        self.assertTrue(_historical_end_reason)

        source = Certificate.create(
            {
                "member_id": donor.id,
                "registration_origin": "migrated",
                "total_value": 5000.0,
                "opening_balance": 0.0,
            }
        )

        self.assertEqual(source.state, "active")

        # El token privado solo se utiliza para
        # crear el registro dentro de esta prueba.
        internal_transfer = Transfer.sudo().with_context(
            club_transfer_record_internal_token=(_TRANSFER_RECORD_INTERNAL_TOKEN)
        )

        created = internal_transfer.create(
            {
                "source_certificate_id": source.id,
                "recipient_person_id": recipient.id,
                "effective_date": today,
            }
        )

        # Volver a obtener el tramite SIN token privado.
        transfer = Transfer.browse(created.id)

        certificate_count = Certificate.sudo().search_count([])

        self.assertEqual(transfer.state, "draft")
        self.assertFalse(transfer.authorized_by_id)
        self.assertFalse(transfer.authorized_at)

        # 1. No se autoriza un Borrador.
        with self.assertRaises(UserError):
            transfer.with_user(authorizer).action_authorize_transfer()

        self.assertEqual(transfer.state, "draft")

        # 2. Verificacion documental real por
        # un funcionario identificado.
        transfer.with_user(verifier).action_register_payment_verification(
            "ACTA-PAGO-471",
            fully_paid_confirmed=True,
        )

        transfer.invalidate_recordset()

        self.assertEqual(
            transfer.state,
            "payment_verified",
        )

        self.assertEqual(
            transfer.payment_verified_by_id.id,
            verifier.id,
        )

        self.assertEqual(
            transfer.payment_evidence_reference,
            "ACTA-PAGO-471",
        )

        original_verified_at = transfer.payment_verified_at

        self.assertTrue(original_verified_at)

        # 3. Usuario sin rol no autoriza.
        with self.assertRaises(AccessError):
            transfer.with_user(observer).action_authorize_transfer()

        # 4. Quien verifico NO puede autorizar,
        # aunque tenga ambos grupos.
        with self.assertRaises(UserError):
            transfer.with_user(verifier).action_authorize_transfer()

        transfer.invalidate_recordset()

        self.assertEqual(
            transfer.state,
            "payment_verified",
        )

        self.assertFalse(transfer.authorized_by_id)
        self.assertFalse(transfer.authorized_at)

        # 5. Funcionario independiente autoriza.
        result = transfer.with_user(authorizer).action_authorize_transfer()

        self.assertTrue(result)

        # Autorizar no reabre ni modifica el vínculo histórico.
        _f10q_family_link.invalidate_recordset()
        self.assertEqual(_f10q_family_link.state, "finalized")
        self.assertEqual(
            _f10q_family_link.end_date,
            _historical_end_date,
        )
        self.assertEqual(
            _f10q_family_link.end_reason,
            _historical_end_reason,
        )

        transfer.invalidate_recordset()
        source.invalidate_recordset()

        self.assertEqual(transfer.state, "authorized")

        self.assertEqual(
            transfer.authorized_by_id.id,
            authorizer.id,
        )

        self.assertTrue(transfer.authorized_at)

        # 6. La verificacion documental se conserva.
        self.assertEqual(
            transfer.payment_verified_by_id.id,
            verifier.id,
        )

        self.assertEqual(
            transfer.payment_evidence_reference,
            "ACTA-PAGO-471",
        )

        self.assertEqual(
            transfer.payment_verified_at,
            original_verified_at,
        )

        # 7. Autorizar NO ejecuta patrimonio.
        self.assertEqual(source.state, "active")
        self.assertEqual(source.member_id.id, donor.id)

        self.assertFalse(transfer.executed_at)
        self.assertFalse(transfer.recipient_certificate_id)

        self.assertEqual(
            Certificate.sudo().search_count([]),
            certificate_count,
        )

        # 8. No se autoriza dos veces.
        with self.assertRaises(UserError):
            transfer.with_user(authorizer).action_authorize_transfer()

        self.assertEqual(transfer.state, "authorized")
        self.assertEqual(
            transfer.authorized_by_id.id,
            authorizer.id,
        )

    def test_authorization_rejects_family_link_to_different_member(self):
        """Autorizar requiere rol propio, pago verificado y otro actor."""
        import uuid

        from odoo.exceptions import AccessError, UserError

        from ..models.certificate_transfer import (
            _TRANSFER_RECORD_INTERNAL_TOKEN,
        )

        # Primero comprobar el nuevo grupo institucional.
        authorization_xmlid = (
            "club_membership.group_club_certificate_transfer_authorization"
        )

        authorization_group = self.env.ref(
            authorization_xmlid,
            raise_if_not_found=False,
        )

        self.assertTrue(
            authorization_group,
            "Falta el grupo institucional de autorizacion "
            "de transferencias patrimoniales.",
        )

        Transfer = self.env["club.certificate.transfer"]

        self.assertTrue(
            callable(
                getattr(
                    Transfer,
                    "action_authorize_transfer",
                    None,
                )
            ),
            "Falta action_authorize_transfer().",
        )

        admin = self.env.ref("base.user_admin")
        Partner = self.env["res.partner"].with_user(admin)
        Certificate = self.env["club.certificate"].with_user(admin)

        payment_group = self.env.ref(
            "club_membership.group_club_certificate_payment_verification"
        )

        internal_group = self.env.ref("base.group_user")

        suffix = uuid.uuid4().hex[:12]

        Users = self.env["res.users"].sudo().with_context(no_reset_password=True)

        # El verificador pertenece deliberadamente a
        # ambos grupos. Aun asi, NO puede aprobar
        # una verificacion que el mismo realizo.
        verifier = Users.create(
            {
                "name": "Ensayo 471 - Verificador",
                "login": "club_auth_471_verify_" + suffix,
                "groups_id": [
                    (
                        6,
                        0,
                        [
                            internal_group.id,
                            payment_group.id,
                            authorization_group.id,
                        ],
                    )
                ],
            }
        )

        authorizer = Users.create(
            {
                "name": "Ensayo 471 - Autorizador",
                "login": "club_auth_471_authorize_" + suffix,
                "groups_id": [
                    (
                        6,
                        0,
                        [
                            internal_group.id,
                            authorization_group.id,
                        ],
                    )
                ],
            }
        )

        observer = Users.create(
            {
                "name": "Ensayo 471 - Sin autorizacion",
                "login": "club_auth_471_observer_" + suffix,
                "groups_id": [
                    (
                        6,
                        0,
                        [
                            internal_group.id,
                        ],
                    )
                ],
            }
        )

        self.assertTrue(
            verifier.has_group(
                "club_membership.group_club_certificate_payment_verification"
            )
        )

        self.assertTrue(verifier.has_group(authorization_xmlid))

        self.assertTrue(authorizer.has_group(authorization_xmlid))

        self.assertFalse(observer.has_group(authorization_xmlid))

        today = fields.Date.context_today(Partner)

        birthdate = today - relativedelta(years=40)
        number = 99720021000

        while Partner.search([("club_id_number", "=", str(number))], limit=1):
            number += 1

        donor = Partner.create(
            {
                "name": "Cedente autorizacion institucional 471",
                "company_type": "person",
                "is_company": False,
                "club_person_type": "member",
                "club_id_number": str(number),
                "club_birthdate": fields.Date.to_string(birthdate),
                "club_join_date": today,
            }
        )

        # F10-V: otra persona es Socio, pero no es el cedente.
        _f10v_number = number + 2000000
        while Partner.search([("club_id_number", "=", str(_f10v_number))], limit=1):
            _f10v_number += 1

        _f10v_other_member = Partner.create(
            {
                "name": "Socio familiar ajeno " + suffix,
                "company_type": "person",
                "is_company": False,
                "club_person_type": "member",
                "club_id_number": str(_f10v_number),
                "club_birthdate": fields.Date.to_string(
                    today - relativedelta(years=42)
                ),
                "club_join_date": today,
            }
        )
        self.assertNotEqual(_f10v_other_member.id, donor.id)

        recipient = Partner.create(
            {
                "name": "Receptor autorizacion institucional 471",
                "company_type": "person",
                "is_company": False,
            }
        )

        # F10-Q: parentesco sintetico para autorizacion positiva.
        # No modifica personas, parentescos ni certificados reales.
        self.assertNotEqual(recipient.club_person_type, "member")

        _f10q_values = {}

        if not recipient.club_id_number:
            _f10q_ci = 99500000000 + recipient.id
            while Partner.search([("club_id_number", "=", str(_f10q_ci))], limit=1):
                _f10q_ci += 1
            _f10q_values["club_id_number"] = str(_f10q_ci)

        if not recipient.club_birthdate:
            _f10q_values["club_birthdate"] = fields.Date.to_string(
                fields.Date.context_today(Partner) - relativedelta(years=35)
            )

        if _f10q_values:
            recipient.write(_f10q_values)

        _f10q_family_link = (
            self.env["club.beneficiary"]
            .sudo()
            .create(
                {
                    "member_id": _f10v_other_member.id,
                    "person_id": recipient.id,
                    "relationship": "spouse",
                    "start_date": fields.Date.context_today(Partner),
                }
            )
        )

        self.assertEqual(_f10q_family_link.state, "active")
        self.assertEqual(_f10q_family_link.member_id.id, _f10v_other_member.id)
        self.assertEqual(_f10q_family_link.person_id.id, recipient.id)

        source = Certificate.create(
            {
                "member_id": donor.id,
                "registration_origin": "migrated",
                "total_value": 5000.0,
                "opening_balance": 0.0,
            }
        )

        self.assertEqual(source.state, "active")

        # El token privado solo se utiliza para
        # crear el registro dentro de esta prueba.
        internal_transfer = Transfer.sudo().with_context(
            club_transfer_record_internal_token=(_TRANSFER_RECORD_INTERNAL_TOKEN)
        )

        created = internal_transfer.create(
            {
                "source_certificate_id": source.id,
                "recipient_person_id": recipient.id,
                "effective_date": today,
            }
        )

        # Volver a obtener el tramite SIN token privado.
        transfer = Transfer.browse(created.id)

        _certificate_count = Certificate.sudo().search_count([])

        self.assertEqual(transfer.state, "draft")
        self.assertFalse(transfer.authorized_by_id)
        self.assertFalse(transfer.authorized_at)

        # 1. No se autoriza un Borrador.
        with self.assertRaises(UserError):
            transfer.with_user(authorizer).action_authorize_transfer()

        self.assertEqual(transfer.state, "draft")

        # 2. Verificacion documental real por
        # un funcionario identificado.
        transfer.with_user(verifier).action_register_payment_verification(
            "ACTA-PAGO-471",
            fully_paid_confirmed=True,
        )

        transfer.invalidate_recordset()

        self.assertEqual(
            transfer.state,
            "payment_verified",
        )

        self.assertEqual(
            transfer.payment_verified_by_id.id,
            verifier.id,
        )

        self.assertEqual(
            transfer.payment_evidence_reference,
            "ACTA-PAGO-471",
        )

        original_verified_at = transfer.payment_verified_at

        self.assertTrue(original_verified_at)

        # 3. Usuario sin rol no autoriza.
        with self.assertRaises(AccessError):
            transfer.with_user(observer).action_authorize_transfer()

        # 4. Quien verifico NO puede autorizar,
        # aunque tenga ambos grupos.
        with self.assertRaises(UserError):
            transfer.with_user(verifier).action_authorize_transfer()

        transfer.invalidate_recordset()

        self.assertEqual(
            transfer.state,
            "payment_verified",
        )

        self.assertFalse(transfer.authorized_by_id)
        self.assertFalse(transfer.authorized_at)

        # El receptor si es Beneficiario, pero NO del cedente.
        _f10v_beneficiary = self.env["club.beneficiary"].sudo()
        self.assertEqual(_f10q_family_link.state, "active")
        self.assertEqual(_f10q_family_link.member_id.id, _f10v_other_member.id)
        self.assertFalse(
            _f10v_beneficiary.search(
                [
                    ("member_id", "=", donor.id),
                    ("person_id", "=", recipient.id),
                ],
                limit=1,
            )
        )

        transfer.invalidate_recordset()
        source.invalidate_recordset()
        self.assertEqual(transfer.state, "payment_verified")
        self.assertEqual(source.state, "active")

        _f10v_evidence = transfer.payment_evidence_reference
        _f10v_verifier = transfer.payment_verified_by_id.id
        _f10v_verified_at = transfer.payment_verified_at
        _f10v_count = Certificate.sudo().search_count([])

        from odoo.exceptions import ValidationError

        with self.assertRaisesRegex(ValidationError, "vínculo familiar"):
            transfer.with_user(authorizer).action_authorize_transfer()

        transfer.invalidate_recordset()
        source.invalidate_recordset()
        _f10q_family_link.invalidate_recordset()

        self.assertEqual(transfer.state, "payment_verified")
        self.assertFalse(transfer.authorized_by_id)
        self.assertFalse(transfer.authorized_at)
        self.assertFalse(transfer.executed_at)
        self.assertFalse(transfer.recipient_certificate_id)
        self.assertEqual(transfer.payment_evidence_reference, _f10v_evidence)
        self.assertEqual(transfer.payment_verified_by_id.id, _f10v_verifier)
        self.assertEqual(transfer.payment_verified_at, _f10v_verified_at)
        self.assertEqual(source.state, "active")
        self.assertEqual(source.member_id.id, donor.id)
        self.assertEqual(Certificate.sudo().search_count([]), _f10v_count)
        self.assertEqual(_f10q_family_link.state, "active")
        self.assertEqual(_f10q_family_link.member_id.id, _f10v_other_member.id)

    def test_institutional_authorization_requires_distinct_actor(self):
        """Autorizar requiere rol propio, pago verificado y otro actor."""
        import uuid

        from odoo.exceptions import AccessError, UserError

        from ..models.certificate_transfer import (
            _TRANSFER_RECORD_INTERNAL_TOKEN,
        )

        # Primero comprobar el nuevo grupo institucional.
        authorization_xmlid = (
            "club_membership.group_club_certificate_transfer_authorization"
        )

        authorization_group = self.env.ref(
            authorization_xmlid,
            raise_if_not_found=False,
        )

        self.assertTrue(
            authorization_group,
            "Falta el grupo institucional de autorizacion "
            "de transferencias patrimoniales.",
        )

        Transfer = self.env["club.certificate.transfer"]

        self.assertTrue(
            callable(
                getattr(
                    Transfer,
                    "action_authorize_transfer",
                    None,
                )
            ),
            "Falta action_authorize_transfer().",
        )

        admin = self.env.ref("base.user_admin")
        Partner = self.env["res.partner"].with_user(admin)
        Certificate = self.env["club.certificate"].with_user(admin)

        payment_group = self.env.ref(
            "club_membership.group_club_certificate_payment_verification"
        )

        internal_group = self.env.ref("base.group_user")

        suffix = uuid.uuid4().hex[:12]

        Users = self.env["res.users"].sudo().with_context(no_reset_password=True)

        # El verificador pertenece deliberadamente a
        # ambos grupos. Aun asi, NO puede aprobar
        # una verificacion que el mismo realizo.
        verifier = Users.create(
            {
                "name": "Ensayo 471 - Verificador",
                "login": "club_auth_471_verify_" + suffix,
                "groups_id": [
                    (
                        6,
                        0,
                        [
                            internal_group.id,
                            payment_group.id,
                            authorization_group.id,
                        ],
                    )
                ],
            }
        )

        authorizer = Users.create(
            {
                "name": "Ensayo 471 - Autorizador",
                "login": "club_auth_471_authorize_" + suffix,
                "groups_id": [
                    (
                        6,
                        0,
                        [
                            internal_group.id,
                            authorization_group.id,
                        ],
                    )
                ],
            }
        )

        observer = Users.create(
            {
                "name": "Ensayo 471 - Sin autorizacion",
                "login": "club_auth_471_observer_" + suffix,
                "groups_id": [
                    (
                        6,
                        0,
                        [
                            internal_group.id,
                        ],
                    )
                ],
            }
        )

        self.assertTrue(
            verifier.has_group(
                "club_membership.group_club_certificate_payment_verification"
            )
        )

        self.assertTrue(verifier.has_group(authorization_xmlid))

        self.assertTrue(authorizer.has_group(authorization_xmlid))

        self.assertFalse(observer.has_group(authorization_xmlid))

        today = fields.Date.context_today(Partner)

        birthdate = today - relativedelta(years=40)
        number = 99720021000

        while Partner.search([("club_id_number", "=", str(number))], limit=1):
            number += 1

        donor = Partner.create(
            {
                "name": "Cedente autorizacion institucional 471",
                "company_type": "person",
                "is_company": False,
                "club_person_type": "member",
                "club_id_number": str(number),
                "club_birthdate": fields.Date.to_string(birthdate),
                "club_join_date": today,
            }
        )

        recipient = Partner.create(
            {
                "name": "Receptor autorizacion institucional 471",
                "company_type": "person",
                "is_company": False,
            }
        )

        # F10-Q: parentesco sintetico para autorizacion positiva.
        # No modifica personas, parentescos ni certificados reales.
        self.assertNotEqual(recipient.club_person_type, "member")

        _f10q_values = {}

        if not recipient.club_id_number:
            _f10q_ci = 99500000000 + recipient.id
            while Partner.search([("club_id_number", "=", str(_f10q_ci))], limit=1):
                _f10q_ci += 1
            _f10q_values["club_id_number"] = str(_f10q_ci)

        if not recipient.club_birthdate:
            _f10q_values["club_birthdate"] = fields.Date.to_string(
                fields.Date.context_today(Partner) - relativedelta(years=35)
            )

        if _f10q_values:
            recipient.write(_f10q_values)

        _f10q_family_link = (
            self.env["club.beneficiary"]
            .sudo()
            .create(
                {
                    "member_id": donor.id,
                    "person_id": recipient.id,
                    "relationship": "spouse",
                    "start_date": fields.Date.context_today(Partner),
                }
            )
        )

        self.assertEqual(_f10q_family_link.state, "active")
        self.assertEqual(_f10q_family_link.member_id.id, donor.id)
        self.assertEqual(_f10q_family_link.person_id.id, recipient.id)

        source = Certificate.create(
            {
                "member_id": donor.id,
                "registration_origin": "migrated",
                "total_value": 5000.0,
                "opening_balance": 0.0,
            }
        )

        self.assertEqual(source.state, "active")

        # El token privado solo se utiliza para
        # crear el registro dentro de esta prueba.
        internal_transfer = Transfer.sudo().with_context(
            club_transfer_record_internal_token=(_TRANSFER_RECORD_INTERNAL_TOKEN)
        )

        created = internal_transfer.create(
            {
                "source_certificate_id": source.id,
                "recipient_person_id": recipient.id,
                "effective_date": today,
            }
        )

        # Volver a obtener el tramite SIN token privado.
        transfer = Transfer.browse(created.id)

        certificate_count = Certificate.sudo().search_count([])

        self.assertEqual(transfer.state, "draft")
        self.assertFalse(transfer.authorized_by_id)
        self.assertFalse(transfer.authorized_at)

        # 1. No se autoriza un Borrador.
        with self.assertRaises(UserError):
            transfer.with_user(authorizer).action_authorize_transfer()

        self.assertEqual(transfer.state, "draft")

        # 2. Verificacion documental real por
        # un funcionario identificado.
        transfer.with_user(verifier).action_register_payment_verification(
            "ACTA-PAGO-471",
            fully_paid_confirmed=True,
        )

        transfer.invalidate_recordset()

        self.assertEqual(
            transfer.state,
            "payment_verified",
        )

        self.assertEqual(
            transfer.payment_verified_by_id.id,
            verifier.id,
        )

        self.assertEqual(
            transfer.payment_evidence_reference,
            "ACTA-PAGO-471",
        )

        original_verified_at = transfer.payment_verified_at

        self.assertTrue(original_verified_at)

        # 3. Usuario sin rol no autoriza.
        with self.assertRaises(AccessError):
            transfer.with_user(observer).action_authorize_transfer()

        # 4. Quien verifico NO puede autorizar,
        # aunque tenga ambos grupos.
        with self.assertRaises(UserError):
            transfer.with_user(verifier).action_authorize_transfer()

        transfer.invalidate_recordset()

        self.assertEqual(
            transfer.state,
            "payment_verified",
        )

        self.assertFalse(transfer.authorized_by_id)
        self.assertFalse(transfer.authorized_at)

        # 5. Funcionario independiente autoriza.
        result = transfer.with_user(authorizer).action_authorize_transfer()

        self.assertTrue(result)

        transfer.invalidate_recordset()
        source.invalidate_recordset()

        self.assertEqual(transfer.state, "authorized")

        self.assertEqual(
            transfer.authorized_by_id.id,
            authorizer.id,
        )

        self.assertTrue(transfer.authorized_at)

        # 6. La verificacion documental se conserva.
        self.assertEqual(
            transfer.payment_verified_by_id.id,
            verifier.id,
        )

        self.assertEqual(
            transfer.payment_evidence_reference,
            "ACTA-PAGO-471",
        )

        self.assertEqual(
            transfer.payment_verified_at,
            original_verified_at,
        )

        # 7. Autorizar NO ejecuta patrimonio.
        self.assertEqual(source.state, "active")
        self.assertEqual(source.member_id.id, donor.id)

        self.assertFalse(transfer.executed_at)
        self.assertFalse(transfer.recipient_certificate_id)

        self.assertEqual(
            Certificate.sudo().search_count([]),
            certificate_count,
        )

        # 8. No se autoriza dos veces.
        with self.assertRaises(UserError):
            transfer.with_user(authorizer).action_authorize_transfer()

        self.assertEqual(transfer.state, "authorized")
        self.assertEqual(
            transfer.authorized_by_id.id,
            authorizer.id,
        )

    def test_authorization_rejects_incomplete_inactive_and_cancelled(self):
        """La autorizacion falla cerrada ante estados irregulares."""
        import uuid

        from odoo.exceptions import UserError

        from ..models.certificate_transfer import (
            _TRANSFER_RECORD_INTERNAL_TOKEN,
        )

        admin = self.env.ref("base.user_admin")
        Partner = self.env["res.partner"].with_user(admin)
        Certificate = self.env["club.certificate"].with_user(admin)

        internal_group = self.env.ref("base.group_user")
        payment_group = self.env.ref(
            "club_membership.group_club_certificate_payment_verification"
        )
        authorization_group = self.env.ref(
            "club_membership.group_club_certificate_transfer_authorization"
        )
        cancellation_group = self.env.ref(
            "club_membership.group_club_certificate_transfer_cancellation"
        )

        Users = self.env["res.users"].sudo().with_context(no_reset_password=True)

        suffix = uuid.uuid4().hex[:12]

        verifier = Users.create(
            {
                "name": "Ensayo 473 - Verificador",
                "login": "club_473_verify_" + suffix,
                "groups_id": [
                    (
                        6,
                        0,
                        [
                            internal_group.id,
                            payment_group.id,
                        ],
                    )
                ],
            }
        )

        authorizer = Users.create(
            {
                "name": "Ensayo 473 - Autorizador",
                "login": "club_473_authorize_" + suffix,
                "groups_id": [
                    (
                        6,
                        0,
                        [
                            internal_group.id,
                            authorization_group.id,
                        ],
                    )
                ],
            }
        )

        canceller = Users.create(
            {
                "name": "Ensayo 473 - Cancelador",
                "login": "club_473_cancel_" + suffix,
                "groups_id": [
                    (
                        6,
                        0,
                        [
                            internal_group.id,
                            cancellation_group.id,
                        ],
                    )
                ],
            }
        )

        today = fields.Date.context_today(Partner)
        birthdate = today - relativedelta(years=40)

        number = 99720022000
        while Partner.search([("club_id_number", "=", str(number))], limit=1):
            number += 1

        donor = Partner.create(
            {
                "name": "Cedente ensayo autorizacion 473",
                "company_type": "person",
                "is_company": False,
                "club_person_type": "member",
                "club_id_number": str(number),
                "club_birthdate": fields.Date.to_string(birthdate),
                "club_join_date": today,
            }
        )

        recipient = Partner.create(
            {
                "name": "Receptor ensayo autorizacion 473",
                "company_type": "person",
                "is_company": False,
            }
        )

        source = Certificate.create(
            {
                "member_id": donor.id,
                "registration_origin": "migrated",
                "total_value": 5000.0,
                "opening_balance": 0.0,
            }
        )

        Transfer = self.env["club.certificate.transfer"]

        internal = Transfer.sudo().with_context(
            club_transfer_record_internal_token=(_TRANSFER_RECORD_INTERNAL_TOKEN)
        )

        created = internal.create(
            {
                "source_certificate_id": source.id,
                "recipient_person_id": recipient.id,
                "effective_date": today,
            }
        )

        transfer = Transfer.browse(created.id)
        internal_record = internal.browse(created.id)

        certificate_count = Certificate.sudo().search_count([])

        self.assertEqual(source.state, "active")
        self.assertEqual(transfer.state, "draft")

        # CASO 1:
        # Estado payment_verified sin evidencia
        # documental. La autorizacion debe fallar.
        self.env.cr.execute(
            "UPDATE club_certificate_transfer SET state = %s WHERE id = %s",
            (
                "payment_verified",
                internal_record.id,
            ),
        )
        internal_record.invalidate_recordset(["state"])

        transfer.invalidate_recordset()

        with self.assertRaises(UserError):
            transfer.with_user(authorizer).action_authorize_transfer()

        transfer.invalidate_recordset()

        self.assertEqual(
            transfer.state,
            "payment_verified",
        )
        self.assertFalse(transfer.authorized_by_id)
        self.assertFalse(transfer.authorized_at)

        # Restaurar el borrador de ensayo para
        # registrar una verificacion completa.
        self.env.cr.execute(
            "UPDATE club_certificate_transfer SET state = %s WHERE id = %s",
            (
                "draft",
                internal_record.id,
            ),
        )
        internal_record.invalidate_recordset(["state"])

        transfer.invalidate_recordset()

        self.assertEqual(transfer.state, "draft")

        transfer.with_user(verifier).action_register_payment_verification(
            "ACTA-PAGO-473",
            fully_paid_confirmed=True,
        )

        transfer.invalidate_recordset()

        self.assertEqual(
            transfer.state,
            "payment_verified",
        )
        self.assertEqual(
            transfer.payment_verified_by_id.id,
            verifier.id,
        )

        verification_time = transfer.payment_verified_at

        # CASO 2:
        # Simular exclusivamente en la transaccion
        # de prueba que el Certificado dejo de estar
        # activo despues de verificar el pago.
        #
        # La sentencia SQL representa una alteracion
        # externa de estado para comprobar la defensa.
        # No se utiliza en el procedimiento de negocio.
        self.env.cr.execute(
            """
            UPDATE club_certificate
               SET state = %s
             WHERE id = %s
            """,
            ("transferred", source.id),
        )

        source.invalidate_recordset(["state"])

        self.assertEqual(source.state, "transferred")

        with self.assertRaises(UserError):
            transfer.with_user(authorizer).action_authorize_transfer()

        transfer.invalidate_recordset()

        self.assertEqual(
            transfer.state,
            "payment_verified",
        )
        self.assertFalse(transfer.authorized_by_id)
        self.assertFalse(transfer.authorized_at)

        # Restaurar el Certificado de ensayo.
        self.env.cr.execute(
            """
            UPDATE club_certificate
               SET state = %s
             WHERE id = %s
            """,
            ("active", source.id),
        )

        source.invalidate_recordset(["state"])

        self.assertEqual(source.state, "active")

        # CASO 3:
        # Cancelar institucionalmente el tramite
        # con otro funcionario y comprobar que
        # no puede autorizarse despues.
        transfer.with_user(canceller).action_cancel_transfer(
            "Cancelacion de ensayo institucional 473"
        )

        transfer.invalidate_recordset()

        self.assertEqual(transfer.state, "cancelled")
        self.assertEqual(
            transfer.cancelled_by_id.id,
            canceller.id,
        )
        self.assertTrue(transfer.cancelled_at)

        with self.assertRaises(UserError):
            transfer.with_user(authorizer).action_authorize_transfer()

        transfer.invalidate_recordset()
        source.invalidate_recordset()

        self.assertEqual(transfer.state, "cancelled")
        self.assertFalse(transfer.authorized_by_id)
        self.assertFalse(transfer.authorized_at)
        self.assertFalse(transfer.executed_at)
        self.assertFalse(transfer.recipient_certificate_id)

        # La evidencia documental y el historial
        # de cancelacion deben conservarse.
        self.assertEqual(
            transfer.payment_evidence_reference,
            "ACTA-PAGO-473",
        )
        self.assertEqual(
            transfer.payment_verified_by_id.id,
            verifier.id,
        )
        self.assertEqual(
            transfer.payment_verified_at,
            verification_time,
        )

        # Ninguna autorizacion fallida puede
        # producir efectos patrimoniales.
        self.assertEqual(source.state, "active")
        self.assertEqual(source.member_id.id, donor.id)
        self.assertEqual(
            Certificate.sudo().search_count([]),
            certificate_count,
        )

    def test_tr03a_finalized_beneficiary_recipient_requires_execution_contract(self):
        """TR-03-A: receptor de 30 anos con vinculo finalizado.

        TDD ROJO: preparar una autorizacion valida y exigir
        el procedimiento de ejecucion aun no implementado.
        """
        import uuid

        from ..models.certificate_transfer import (
            _TRANSFER_RECORD_INTERNAL_TOKEN,
        )

        admin = self.env.ref("base.user_admin")

        Partner = self.env["res.partner"].with_user(admin)
        Certificate = self.env["club.certificate"].with_user(admin)
        Beneficiary = self.env["club.beneficiary"]

        Transfer = self.env["club.certificate.transfer"]

        today = fields.Date.context_today(Partner)

        suffix = uuid.uuid4().hex[:10]

        id_base = 99800000000 + int(suffix[:6], 16)

        donor = Partner.create(
            {
                "name": "TR-03-A Cedente " + suffix,
                "company_type": "person",
                "is_company": False,
                "club_person_type": "member",
                "club_id_number": str(id_base),
                "club_birthdate": fields.Date.to_string(
                    today - relativedelta(years=45)
                ),
                "club_join_date": today,
            }
        )

        recipient = Partner.create(
            {
                "name": "TR-03-A Receptor " + suffix,
                "company_type": "person",
                "is_company": False,
                "club_id_number": str(id_base + 1),
                "club_birthdate": fields.Date.to_string(
                    today - relativedelta(years=30)
                ),
            }
        )

        self.assertEqual(recipient.club_age, 30)

        self.assertNotEqual(
            donor.id,
            recipient.id,
        )

        self.assertNotEqual(
            recipient.club_person_type,
            "member",
        )

        original_recipient_id = recipient.id
        original_recipient_number = recipient.club_id_number

        # El cedente es titular del vinculo historico.
        beneficiary = Beneficiary.create(
            {
                "member_id": donor.id,
                "person_id": recipient.id,
                "relationship": "spouse",
                "start_date": today,
            }
        )

        self.assertEqual(
            beneficiary.state,
            "active",
        )

        history_reason = "TR-03-A finalizacion historica previa"

        beneficiary.finalize_link(
            end_date=today,
            reason=history_reason,
        )

        beneficiary.invalidate_recordset()

        self.assertEqual(
            beneficiary.state,
            "finalized",
        )

        historical_date = beneficiary.end_date
        historical_reason = beneficiary.end_reason

        self.assertEqual(
            historical_date,
            today,
        )

        self.assertEqual(
            historical_reason,
            history_reason,
        )

        source = Certificate.create(
            {
                "member_id": donor.id,
                "registration_origin": "migrated",
                "total_value": 5000.0,
                "opening_balance": 0.0,
            }
        )

        self.assertEqual(
            source.state,
            "active",
        )

        self.assertEqual(
            source.member_id.id,
            donor.id,
        )

        self.assertEqual(
            Certificate.search_count(
                [
                    ("member_id", "=", recipient.id),
                    ("state", "=", "active"),
                ]
            ),
            0,
        )

        internal_group = self.env.ref("base.group_user")

        payment_group = self.env.ref(
            "club_membership.group_club_certificate_payment_verification"
        )

        authorization_group = self.env.ref(
            "club_membership.group_club_certificate_transfer_authorization"
        )

        Users = self.env["res.users"].sudo().with_context(no_reset_password=True)

        verifier = Users.create(
            {
                "name": "TR-03-A Verificador " + suffix,
                "login": "tr03a_verifier_" + suffix,
                "groups_id": [
                    (
                        6,
                        0,
                        [
                            internal_group.id,
                            payment_group.id,
                        ],
                    )
                ],
            }
        )

        authorizer = Users.create(
            {
                "name": "TR-03-A Autorizador " + suffix,
                "login": "tr03a_authorizer_" + suffix,
                "groups_id": [
                    (
                        6,
                        0,
                        [
                            internal_group.id,
                            authorization_group.id,
                        ],
                    )
                ],
            }
        )

        self.assertNotEqual(
            verifier.id,
            authorizer.id,
        )

        internal_transfer = Transfer.sudo().with_context(
            club_transfer_record_internal_token=(_TRANSFER_RECORD_INTERNAL_TOKEN)
        )

        transfer = internal_transfer.create(
            {
                "source_certificate_id": source.id,
                "recipient_person_id": recipient.id,
                "effective_date": today,
            }
        )

        evidence = "DOCUMENTO-TR03A-" + suffix

        transfer.with_user(verifier).action_register_payment_verification(
            evidence,
            fully_paid_confirmed=True,
        )

        transfer.invalidate_recordset()

        self.assertEqual(
            transfer.state,
            "payment_verified",
        )

        self.assertEqual(
            transfer.payment_verified_by_id.id,
            verifier.id,
        )

        transfer.with_user(authorizer).action_authorize_transfer()

        transfer.invalidate_recordset()

        self.assertEqual(
            transfer.state,
            "authorized",
        )

        self.assertEqual(
            transfer.authorized_by_id.id,
            authorizer.id,
        )

        self.assertEqual(
            transfer.payment_evidence_reference,
            evidence,
        )

        # Confirmar que la preparacion no ejecuto
        # ninguna operacion patrimonial.
        source.invalidate_recordset()

        self.assertEqual(
            source.state,
            "active",
        )

        self.assertEqual(
            source.member_id.id,
            donor.id,
        )

        recipient.invalidate_recordset()
        beneficiary.invalidate_recordset()

        self.assertEqual(
            recipient.id,
            original_recipient_id,
        )

        self.assertEqual(
            recipient.club_id_number,
            original_recipient_number,
        )

        self.assertEqual(
            beneficiary.state,
            "finalized",
        )

        self.assertEqual(
            beneficiary.end_date,
            historical_date,
        )

        self.assertEqual(
            beneficiary.end_reason,
            historical_reason,
        )

        self.assertFalse(
            transfer.recipient_certificate_id,
        )

        self.assertFalse(
            transfer.executed_at,
        )

        # PUNTO TDD ROJO:
        # La preparacion es valida y no debe
        # ejecutarse todavia ninguna transferencia.
        #
        # En la siguiente etapa se establecera
        # el grupo institucional ejecutor.
        self.assertTrue(
            callable(
                getattr(
                    transfer,
                    "action_execute_transfer",
                    None,
                )
            ),
            "TDD_ROJO_TR03A_FALTA_ACTION_EXECUTE_TRANSFER",
        )

    def test_execution_requires_responsible_user_audit_field(self):
        """Ejecucion patrimonial: registrar usuario responsable.

        Este test no habilita la ejecucion, no crea grupos
        ni presupone la separacion institucional de cargos.
        """
        Transfer = self.env["club.certificate.transfer"]

        self.assertIn(
            "payment_verified_by_id",
            Transfer._fields,
        )
        self.assertIn(
            "authorized_by_id",
            Transfer._fields,
        )
        self.assertIn(
            "executed_at",
            Transfer._fields,
        )
        self.assertIn(
            "recipient_certificate_id",
            Transfer._fields,
        )

        # TDD ROJO: falta identidad del ejecutor.
        self.assertIn(
            "executed_by_id",
            Transfer._fields,
            "TDD_ROJO_494_FALTA_EXECUTED_BY_ID",
        )

        actor_field = Transfer._fields["executed_by_id"]

        self.assertEqual(
            actor_field.type,
            "many2one",
        )
        self.assertEqual(
            actor_field.comodel_name,
            "res.users",
        )

    def test_execution_actor_cannot_be_assigned_with_general_internal_token(self):
        """El token general no debe permitir falsificar al ejecutor.

        La prueba no ejecuta la transferencia. Comprueba
        exclusivamente create() y write() del tramite.
        """
        import uuid

        from ..models.certificate_transfer import (
            _TRANSFER_RECORD_INTERNAL_TOKEN,
        )

        admin = self.env.ref("base.user_admin")

        Partner = self.env["res.partner"].with_user(admin)
        Certificate = self.env["club.certificate"].with_user(admin)

        Transfer = (
            self.env["club.certificate.transfer"]
            .sudo()
            .with_context(
                club_transfer_record_internal_token=(_TRANSFER_RECORD_INTERNAL_TOKEN)
            )
        )

        suffix = uuid.uuid4().hex[:10]
        number = 99850000000 + int(suffix[:6], 16)

        today = fields.Date.context_today(Partner)

        donor = Partner.create(
            {
                "name": "Ensayo 496 Cedente " + suffix,
                "company_type": "person",
                "is_company": False,
                "club_person_type": "member",
                "club_id_number": str(number),
                "club_birthdate": fields.Date.to_string(
                    today - relativedelta(years=45)
                ),
                "club_join_date": today,
            }
        )

        recipient = Partner.create(
            {
                "name": "Ensayo 496 Receptor " + suffix,
                "company_type": "person",
                "is_company": False,
                "club_id_number": str(number + 1),
                "club_birthdate": fields.Date.to_string(
                    today - relativedelta(years=30)
                ),
            }
        )

        source = Certificate.create(
            {
                "member_id": donor.id,
                "registration_origin": "migrated",
                "total_value": 5000.0,
                "opening_balance": 0.0,
            }
        )

        self.assertEqual(source.state, "active")

        values = {
            "source_certificate_id": source.id,
            "recipient_person_id": recipient.id,
            "effective_date": today,
        }

        breaches = []

        # 1. Un tramite en Borrador no puede
        # nacer con identidad de ejecutor
        # inyectada mediante el token general.
        try:
            transfer = Transfer.create(
                {
                    **values,
                    "executed_by_id": admin.id,
                }
            )
        except AccessError:
            transfer = Transfer.create(values)
        else:
            transfer.invalidate_recordset(
                [
                    "executed_by_id",
                ]
            )

            if transfer.executed_by_id.id == admin.id:
                breaches.append("CREATE")

        self.assertEqual(
            transfer.state,
            "draft",
        )

        # 2. El mismo token general tampoco
        # puede cambiar ejecutado_por mediante
        # una escritura aislada.
        try:
            transfer.write(
                {
                    "executed_by_id": admin.id,
                }
            )
        except AccessError:
            pass
        else:
            breaches.append("WRITE")

        # Comprobar que no hubo ejecución real.
        transfer.invalidate_recordset()
        source.invalidate_recordset()

        self.assertEqual(
            transfer.state,
            "draft",
        )

        self.assertFalse(
            transfer.executed_at,
        )

        self.assertFalse(
            transfer.recipient_certificate_id,
        )

        self.assertEqual(
            source.state,
            "active",
        )

        self.assertEqual(
            source.member_id.id,
            donor.id,
        )

        # TDD ROJO: actualmente el campo tiene
        # readonly=True, pero falta la guarda
        # backend contra el token interno general.
        self.assertFalse(
            breaches,
            (
                "TDD_ROJO_496_EJECUTOR_MODIFICABLE_"
                "CON_TOKEN_GENERAL: " + ", ".join(breaches)
            ),
        )

    def test_execution_actor_stays_empty_through_verification_and_authorization(self):
        """La verificacion y autorizacion no son ejecucion patrimonial."""
        import uuid

        from ..models.certificate_transfer import (
            _TRANSFER_RECORD_INTERNAL_TOKEN,
        )

        admin = self.env.ref("base.user_admin")

        Partner = self.env["res.partner"].with_user(admin)
        Certificate = self.env["club.certificate"].with_user(admin)

        Transfer = self.env["club.certificate.transfer"]

        today = fields.Date.context_today(Partner)
        suffix = uuid.uuid4().hex[:10]
        number = 99870000000 + int(suffix[:6], 16)

        donor = Partner.create(
            {
                "name": "Ensayo 499 Cedente " + suffix,
                "company_type": "person",
                "is_company": False,
                "club_person_type": "member",
                "club_id_number": str(number),
                "club_birthdate": fields.Date.to_string(
                    today - relativedelta(years=45)
                ),
                "club_join_date": today,
            }
        )

        recipient = Partner.create(
            {
                "name": "Ensayo 499 Receptor " + suffix,
                "company_type": "person",
                "is_company": False,
                "club_id_number": str(number + 1),
                "club_birthdate": fields.Date.to_string(
                    today - relativedelta(years=30)
                ),
            }
        )

        # F10-Q: parentesco sintetico para autorizacion positiva.
        # No modifica personas, parentescos ni certificados reales.
        self.assertNotEqual(recipient.club_person_type, "member")

        _f10q_values = {}

        if not recipient.club_id_number:
            _f10q_ci = 99500000000 + recipient.id
            while Partner.search([("club_id_number", "=", str(_f10q_ci))], limit=1):
                _f10q_ci += 1
            _f10q_values["club_id_number"] = str(_f10q_ci)

        if not recipient.club_birthdate:
            _f10q_values["club_birthdate"] = fields.Date.to_string(
                fields.Date.context_today(Partner) - relativedelta(years=35)
            )

        if _f10q_values:
            recipient.write(_f10q_values)

        _f10q_family_link = (
            self.env["club.beneficiary"]
            .sudo()
            .create(
                {
                    "member_id": donor.id,
                    "person_id": recipient.id,
                    "relationship": "spouse",
                    "start_date": fields.Date.context_today(Partner),
                }
            )
        )

        self.assertEqual(_f10q_family_link.state, "active")
        self.assertEqual(_f10q_family_link.member_id.id, donor.id)
        self.assertEqual(_f10q_family_link.person_id.id, recipient.id)

        source = Certificate.create(
            {
                "member_id": donor.id,
                "registration_origin": "migrated",
                "total_value": 5000.0,
                "opening_balance": 0.0,
            }
        )

        self.assertEqual(source.state, "active")
        self.assertEqual(source.member_id.id, donor.id)

        internal_group = self.env.ref("base.group_user")

        payment_group = self.env.ref(
            "club_membership.group_club_certificate_payment_verification"
        )

        authorization_group = self.env.ref(
            "club_membership.group_club_certificate_transfer_authorization"
        )

        Users = self.env["res.users"].sudo().with_context(no_reset_password=True)

        verifier = Users.create(
            {
                "name": "Ensayo 499 Verificador " + suffix,
                "login": "club_499_verify_" + suffix,
                "groups_id": [
                    (
                        6,
                        0,
                        [
                            internal_group.id,
                            payment_group.id,
                        ],
                    )
                ],
            }
        )

        authorizer = Users.create(
            {
                "name": "Ensayo 499 Autorizador " + suffix,
                "login": "club_499_auth_" + suffix,
                "groups_id": [
                    (
                        6,
                        0,
                        [
                            internal_group.id,
                            authorization_group.id,
                        ],
                    )
                ],
            }
        )

        self.assertNotEqual(
            verifier.id,
            authorizer.id,
        )

        internal_transfer = Transfer.sudo().with_context(
            club_transfer_record_internal_token=(_TRANSFER_RECORD_INTERNAL_TOKEN)
        )

        transfer = internal_transfer.create(
            {
                "source_certificate_id": source.id,
                "recipient_person_id": recipient.id,
                "effective_date": today,
            }
        )

        # ETAPA 1: BORRADOR.
        transfer.invalidate_recordset()

        self.assertEqual(transfer.state, "draft")
        self.assertFalse(transfer.executed_by_id)
        self.assertFalse(transfer.executed_at)
        self.assertFalse(transfer.recipient_certificate_id)
        self.assertFalse(transfer.payment_verified_by_id)
        self.assertFalse(transfer.authorized_by_id)

        evidence = "DOCUMENTO-499-" + suffix

        transfer.with_user(verifier).action_register_payment_verification(
            evidence,
            fully_paid_confirmed=True,
        )

        # ETAPA 2: PAGO DOCUMENTAL VERIFICADO.
        transfer.invalidate_recordset()

        self.assertEqual(
            transfer.state,
            "payment_verified",
        )
        self.assertEqual(
            transfer.payment_verified_by_id.id,
            verifier.id,
        )
        self.assertFalse(transfer.authorized_by_id)
        self.assertFalse(transfer.executed_by_id)
        self.assertFalse(transfer.executed_at)
        self.assertFalse(transfer.recipient_certificate_id)

        transfer.with_user(authorizer).action_authorize_transfer()

        # ETAPA 3: AUTORIZACION INSTITUCIONAL.
        transfer.invalidate_recordset()

        self.assertEqual(transfer.state, "authorized")
        self.assertEqual(
            transfer.payment_verified_by_id.id,
            verifier.id,
        )
        self.assertEqual(
            transfer.authorized_by_id.id,
            authorizer.id,
        )
        self.assertEqual(
            transfer.payment_evidence_reference,
            evidence,
        )

        self.assertFalse(
            transfer.executed_by_id,
            "La autorizacion no puede registrar ejecutor.",
        )
        self.assertFalse(
            transfer.executed_at,
            "La autorizacion no equivale a ejecucion.",
        )
        self.assertFalse(
            transfer.recipient_certificate_id,
            "Todavia no debe crearse certificado receptor.",
        )

        source.invalidate_recordset()
        recipient.invalidate_recordset()

        self.assertEqual(source.state, "active")
        self.assertEqual(source.member_id.id, donor.id)

        self.assertNotEqual(
            recipient.club_person_type,
            "member",
        )

        self.assertEqual(
            Certificate.search_count(
                [
                    ("member_id", "=", recipient.id),
                    ("state", "=", "active"),
                ]
            ),
            0,
        )

        self.assertFalse(
            callable(
                getattr(
                    transfer,
                    "action_execute_transfer",
                    None,
                )
            ),
            "La ejecucion patrimonial debe seguir pendiente.",
        )

    def test_cancel_verified_transfer_preserves_empty_execution_audit(self):
        """Cancelar pago verificado no ejecuta patrimonio."""
        import uuid

        from ..models.certificate_transfer import (
            _TRANSFER_RECORD_INTERNAL_TOKEN,
        )

        admin = self.env.ref("base.user_admin")

        Partner = self.env["res.partner"].with_user(admin)
        Certificate = self.env["club.certificate"].with_user(admin)
        Transfer = self.env["club.certificate.transfer"]

        today = fields.Date.context_today(Partner)
        suffix = uuid.uuid4().hex[:10]
        number = 99890000000 + int(suffix[:6], 16)

        donor = Partner.create(
            {
                "name": "Ensayo 501 Cedente " + suffix,
                "company_type": "person",
                "is_company": False,
                "club_person_type": "member",
                "club_id_number": str(number),
                "club_birthdate": fields.Date.to_string(
                    today - relativedelta(years=45)
                ),
                "club_join_date": today,
            }
        )

        recipient = Partner.create(
            {
                "name": "Ensayo 501 Receptor " + suffix,
                "company_type": "person",
                "is_company": False,
                "club_id_number": str(number + 1),
                "club_birthdate": fields.Date.to_string(
                    today - relativedelta(years=30)
                ),
            }
        )

        source = Certificate.create(
            {
                "member_id": donor.id,
                "registration_origin": "migrated",
                "total_value": 5000.0,
                "opening_balance": 0.0,
            }
        )

        self.assertEqual(source.state, "active")
        self.assertEqual(source.member_id.id, donor.id)

        internal_group = self.env.ref("base.group_user")

        payment_group = self.env.ref(
            "club_membership.group_club_certificate_payment_verification"
        )

        cancellation_group = self.env.ref(
            "club_membership.group_club_certificate_transfer_cancellation"
        )

        Users = self.env["res.users"].sudo().with_context(no_reset_password=True)

        verifier = Users.create(
            {
                "name": "Ensayo 501 Verificador " + suffix,
                "login": "club_501_verify_" + suffix,
                "groups_id": [
                    (
                        6,
                        0,
                        [
                            internal_group.id,
                            payment_group.id,
                        ],
                    )
                ],
            }
        )

        canceller = Users.create(
            {
                "name": "Ensayo 501 Cancelador " + suffix,
                "login": "club_501_cancel_" + suffix,
                "groups_id": [
                    (
                        6,
                        0,
                        [
                            internal_group.id,
                            cancellation_group.id,
                        ],
                    )
                ],
            }
        )

        self.assertNotEqual(
            verifier.id,
            canceller.id,
        )

        internal_transfer = Transfer.sudo().with_context(
            club_transfer_record_internal_token=(_TRANSFER_RECORD_INTERNAL_TOKEN)
        )

        transfer = internal_transfer.create(
            {
                "source_certificate_id": source.id,
                "recipient_person_id": recipient.id,
                "effective_date": today,
            }
        )

        # ETAPA 1: BORRADOR
        transfer.invalidate_recordset()

        self.assertEqual(transfer.state, "draft")
        self.assertFalse(transfer.executed_by_id)
        self.assertFalse(transfer.executed_at)
        self.assertFalse(transfer.recipient_certificate_id)

        evidence = "DOCUMENTO-501-" + suffix

        transfer.with_user(verifier).action_register_payment_verification(
            evidence,
            fully_paid_confirmed=True,
        )

        # ETAPA 2: PAGO DOCUMENTAL VERIFICADO
        transfer.invalidate_recordset()

        self.assertEqual(
            transfer.state,
            "payment_verified",
        )
        self.assertEqual(
            transfer.payment_verified_by_id.id,
            verifier.id,
        )
        self.assertTrue(transfer.payment_verified_at)
        self.assertFalse(transfer.executed_by_id)
        self.assertFalse(transfer.executed_at)
        self.assertFalse(transfer.recipient_certificate_id)

        original_verification_date = transfer.payment_verified_at

        original_evidence = transfer.payment_evidence_reference

        self.assertEqual(original_evidence, evidence)

        self.assertFalse(transfer.authorized_by_id)
        self.assertFalse(transfer.authorized_at)

        # ETAPA 3: CANCELACION INSTITUCIONAL
        transfer.with_user(canceller).action_cancel_transfer(
            "  Solicitud desistida en ensayo 501  "
        )

        transfer.invalidate_recordset()
        source.invalidate_recordset()
        recipient.invalidate_recordset()

        self.assertEqual(
            transfer.state,
            "cancelled",
        )

        self.assertEqual(
            transfer.cancellation_reason,
            "Solicitud desistida en ensayo 501",
        )

        self.assertEqual(
            transfer.cancelled_by_id.id,
            canceller.id,
        )

        self.assertTrue(transfer.cancelled_at)

        # La verificacion documental es historia:
        # cancelar no debe borrarla.
        self.assertEqual(
            transfer.payment_verified_by_id.id,
            verifier.id,
        )

        self.assertEqual(
            transfer.payment_verified_at,
            original_verification_date,
        )

        self.assertEqual(
            transfer.payment_evidence_reference,
            original_evidence,
        )

        # Cancelacion NO equivale a autorizacion
        # ni a ejecucion patrimonial.
        self.assertFalse(transfer.authorized_by_id)
        self.assertFalse(transfer.authorized_at)

        self.assertFalse(
            transfer.executed_by_id,
            "Cancelar no puede identificar a un ejecutor.",
        )

        self.assertFalse(
            transfer.executed_at,
            "Cancelar no puede registrar ejecucion.",
        )

        self.assertFalse(
            transfer.recipient_certificate_id,
            "Cancelar no puede crear certificado receptor.",
        )

        # El certificado cedente permanece intacto.
        self.assertEqual(source.state, "active")
        self.assertEqual(
            source.member_id.id,
            donor.id,
        )

        self.assertFalse(
            source.transfer_source_certificate_id,
        )

        # El receptor no fue convertido en socio.
        self.assertNotEqual(
            recipient.club_person_type,
            "member",
        )

        self.assertEqual(
            Certificate.search_count(
                [
                    ("member_id", "=", recipient.id),
                ]
            ),
            0,
        )

        # La ejecucion sigue sin implementarse.
        self.assertFalse(
            callable(
                getattr(
                    transfer,
                    "action_execute_transfer",
                    None,
                )
            ),
        )

    def test_authorized_transfer_recipient_cannot_change_with_general_token(self):
        """Una autorizacion no admite sustituir al receptor."""
        import uuid

        from ..models.certificate_transfer import (
            _TRANSFER_RECORD_INTERNAL_TOKEN,
        )

        admin = self.env.ref("base.user_admin")

        Partner = self.env["res.partner"].with_user(admin)
        Certificate = self.env["club.certificate"].with_user(admin)
        Transfer = self.env["club.certificate.transfer"]

        today = fields.Date.context_today(Partner)
        suffix = uuid.uuid4().hex[:10]
        number = 99892000000 + int(suffix[:6], 16)

        donor = Partner.create(
            {
                "name": "Ensayo 512 Cedente " + suffix,
                "company_type": "person",
                "is_company": False,
                "club_person_type": "member",
                "club_id_number": str(number),
                "club_birthdate": fields.Date.to_string(
                    today - relativedelta(years=45)
                ),
                "club_join_date": today,
            }
        )

        recipient = Partner.create(
            {
                "name": "Ensayo 512 Receptor autorizado " + suffix,
                "company_type": "person",
                "is_company": False,
                "club_id_number": str(number + 1),
                "club_birthdate": fields.Date.to_string(
                    today - relativedelta(years=30)
                ),
            }
        )

        # F10-Q: parentesco sintetico para autorizacion positiva.
        # No modifica personas, parentescos ni certificados reales.
        self.assertNotEqual(recipient.club_person_type, "member")

        _f10q_values = {}

        if not recipient.club_id_number:
            _f10q_ci = 99500000000 + recipient.id
            while Partner.search([("club_id_number", "=", str(_f10q_ci))], limit=1):
                _f10q_ci += 1
            _f10q_values["club_id_number"] = str(_f10q_ci)

        if not recipient.club_birthdate:
            _f10q_values["club_birthdate"] = fields.Date.to_string(
                fields.Date.context_today(Partner) - relativedelta(years=35)
            )

        if _f10q_values:
            recipient.write(_f10q_values)

        _f10q_family_link = (
            self.env["club.beneficiary"]
            .sudo()
            .create(
                {
                    "member_id": donor.id,
                    "person_id": recipient.id,
                    "relationship": "spouse",
                    "start_date": fields.Date.context_today(Partner),
                }
            )
        )

        self.assertEqual(_f10q_family_link.state, "active")
        self.assertEqual(_f10q_family_link.member_id.id, donor.id)
        self.assertEqual(_f10q_family_link.person_id.id, recipient.id)

        substitute = Partner.create(
            {
                "name": "Ensayo 512 Receptor sustituto " + suffix,
                "company_type": "person",
                "is_company": False,
                "club_id_number": str(number + 2),
                "club_birthdate": fields.Date.to_string(
                    today - relativedelta(years=35)
                ),
            }
        )

        source = Certificate.create(
            {
                "member_id": donor.id,
                "registration_origin": "migrated",
                "total_value": 5000.0,
                "opening_balance": 0.0,
            }
        )

        self.assertEqual(source.state, "active")
        self.assertEqual(source.member_id.id, donor.id)

        internal_group = self.env.ref("base.group_user")

        payment_group = self.env.ref(
            "club_membership.group_club_certificate_payment_verification"
        )

        authorization_group = self.env.ref(
            "club_membership.group_club_certificate_transfer_authorization"
        )

        Users = self.env["res.users"].sudo().with_context(no_reset_password=True)

        verifier = Users.create(
            {
                "name": "Ensayo 512 Verificador " + suffix,
                "login": "club_512_verify_" + suffix,
                "groups_id": [
                    (
                        6,
                        0,
                        [
                            internal_group.id,
                            payment_group.id,
                        ],
                    )
                ],
            }
        )

        authorizer = Users.create(
            {
                "name": "Ensayo 512 Autorizador " + suffix,
                "login": "club_512_auth_" + suffix,
                "groups_id": [
                    (
                        6,
                        0,
                        [
                            internal_group.id,
                            authorization_group.id,
                        ],
                    )
                ],
            }
        )

        self.assertNotEqual(verifier.id, authorizer.id)

        transfer = (
            Transfer.sudo()
            .with_context(
                club_transfer_record_internal_token=(_TRANSFER_RECORD_INTERNAL_TOKEN)
            )
            .create(
                {
                    "source_certificate_id": source.id,
                    "recipient_person_id": recipient.id,
                    "effective_date": today,
                }
            )
        )

        self.assertEqual(transfer.state, "draft")

        evidence = "PAGO-512-" + suffix

        transfer.with_user(verifier).action_register_payment_verification(
            evidence,
            fully_paid_confirmed=True,
        )

        transfer.invalidate_recordset()

        self.assertEqual(
            transfer.state,
            "payment_verified",
        )

        self.assertEqual(
            transfer.payment_verified_by_id.id,
            verifier.id,
        )

        transfer.with_user(authorizer).action_authorize_transfer()

        transfer.invalidate_recordset()

        # Contrato autorizado correctamente.
        self.assertEqual(transfer.state, "authorized")

        self.assertEqual(
            transfer.recipient_person_id.id,
            recipient.id,
        )

        self.assertEqual(
            transfer.source_certificate_id.id,
            source.id,
        )

        self.assertEqual(
            transfer.authorized_by_id.id,
            authorizer.id,
        )

        self.assertTrue(transfer.authorized_at)

        self.assertFalse(transfer.executed_by_id)
        self.assertFalse(transfer.executed_at)
        self.assertFalse(transfer.recipient_certificate_id)

        original_authorized_at = transfer.authorized_at
        original_payment_at = transfer.payment_verified_at

        # CONTROL 512:
        # El token general no debe permitir cambiar
        # a quien recibira un Certificado autorizado.
        #
        # El savepoint revierte la modificacion
        # si el sistema todavia la permite.
        with self.env.cr.savepoint():
            try:
                (
                    transfer.sudo()
                    .with_context(
                        club_transfer_record_internal_token=(
                            _TRANSFER_RECORD_INTERNAL_TOKEN
                        )
                    )
                    .write(
                        {
                            "recipient_person_id": substitute.id,
                        }
                    )
                )
            except AccessError:
                # Resultado esperado tras implementar
                # la proteccion backend.
                pass
            else:
                self.fail("TDD_ROJO_512_RECEPTOR_AUTORIZADO_MUTABLE_CON_TOKEN_GENERAL")

        transfer.invalidate_recordset()
        source.invalidate_recordset()

        self.assertEqual(transfer.state, "authorized")

        self.assertEqual(
            transfer.recipient_person_id.id,
            recipient.id,
        )

        self.assertEqual(
            transfer.source_certificate_id.id,
            source.id,
        )

        self.assertEqual(
            transfer.authorized_by_id.id,
            authorizer.id,
        )

        self.assertEqual(
            transfer.authorized_at,
            original_authorized_at,
        )

        self.assertEqual(
            transfer.payment_verified_by_id.id,
            verifier.id,
        )

        self.assertEqual(
            transfer.payment_verified_at,
            original_payment_at,
        )

        self.assertEqual(
            transfer.payment_evidence_reference,
            evidence,
        )

        self.assertFalse(transfer.executed_by_id)
        self.assertFalse(transfer.executed_at)
        self.assertFalse(transfer.recipient_certificate_id)

        self.assertEqual(source.state, "active")
        self.assertEqual(source.member_id.id, donor.id)

        self.assertEqual(
            Certificate.search_count(
                [
                    (
                        "member_id",
                        "in",
                        [
                            recipient.id,
                            substitute.id,
                        ],
                    ),
                ]
            ),
            0,
        )

    def test_authorized_transfer_source_cannot_change_with_general_token(self):
        """Una autorizacion no admite sustituir su Certificado de origen."""
        import uuid

        from ..models.certificate_transfer import (
            _TRANSFER_RECORD_INTERNAL_TOKEN,
        )

        admin = self.env.ref("base.user_admin")

        Partner = self.env["res.partner"].with_user(admin)
        Certificate = self.env["club.certificate"].with_user(admin)
        Transfer = self.env["club.certificate.transfer"]

        today = fields.Date.context_today(Partner)
        suffix = uuid.uuid4().hex[:10]
        number = 99892000000 + int(suffix[:6], 16)

        donor = Partner.create(
            {
                "name": "Ensayo 517 Cedente " + suffix,
                "company_type": "person",
                "is_company": False,
                "club_person_type": "member",
                "club_id_number": str(number),
                "club_birthdate": fields.Date.to_string(
                    today - relativedelta(years=45)
                ),
                "club_join_date": today,
            }
        )

        recipient = Partner.create(
            {
                "name": "Ensayo 517 Receptor autorizado " + suffix,
                "company_type": "person",
                "is_company": False,
                "club_id_number": str(number + 1),
                "club_birthdate": fields.Date.to_string(
                    today - relativedelta(years=30)
                ),
            }
        )

        # F10-Q: parentesco sintetico para autorizacion positiva.
        # No modifica personas, parentescos ni certificados reales.
        self.assertNotEqual(recipient.club_person_type, "member")

        _f10q_values = {}

        if not recipient.club_id_number:
            _f10q_ci = 99500000000 + recipient.id
            while Partner.search([("club_id_number", "=", str(_f10q_ci))], limit=1):
                _f10q_ci += 1
            _f10q_values["club_id_number"] = str(_f10q_ci)

        if not recipient.club_birthdate:
            _f10q_values["club_birthdate"] = fields.Date.to_string(
                fields.Date.context_today(Partner) - relativedelta(years=35)
            )

        if _f10q_values:
            recipient.write(_f10q_values)

        _f10q_family_link = (
            self.env["club.beneficiary"]
            .sudo()
            .create(
                {
                    "member_id": donor.id,
                    "person_id": recipient.id,
                    "relationship": "spouse",
                    "start_date": fields.Date.context_today(Partner),
                }
            )
        )

        self.assertEqual(_f10q_family_link.state, "active")
        self.assertEqual(_f10q_family_link.member_id.id, donor.id)
        self.assertEqual(_f10q_family_link.person_id.id, recipient.id)

        substitute = Partner.create(
            {
                "name": "Ensayo 517 Receptor sustituto " + suffix,
                "company_type": "person",
                "is_company": False,
                "club_id_number": str(number + 2),
                "club_birthdate": fields.Date.to_string(
                    today - relativedelta(years=35)
                ),
            }
        )

        source = Certificate.create(
            {
                "member_id": donor.id,
                "registration_origin": "migrated",
                "total_value": 5000.0,
                "opening_balance": 0.0,
            }
        )

        self.assertEqual(source.state, "active")
        self.assertEqual(source.member_id.id, donor.id)

        alternate_donor = Partner.create(
            {
                "name": "Ensayo 517 Cedente alternativo " + suffix,
                "company_type": "person",
                "is_company": False,
                "club_person_type": "member",
                "club_id_number": str(number + 3),
                "club_birthdate": fields.Date.to_string(
                    today - relativedelta(years=42)
                ),
                "club_join_date": today,
            }
        )

        alternate_source = Certificate.create(
            {
                "member_id": alternate_donor.id,
                "registration_origin": "migrated",
                "total_value": 5000.0,
                "opening_balance": 0.0,
            }
        )

        self.assertEqual(alternate_source.state, "active")
        self.assertEqual(
            alternate_source.member_id.id,
            alternate_donor.id,
        )
        self.assertNotEqual(source.id, alternate_source.id)

        internal_group = self.env.ref("base.group_user")

        payment_group = self.env.ref(
            "club_membership.group_club_certificate_payment_verification"
        )

        authorization_group = self.env.ref(
            "club_membership.group_club_certificate_transfer_authorization"
        )

        Users = self.env["res.users"].sudo().with_context(no_reset_password=True)

        verifier = Users.create(
            {
                "name": "Ensayo 517 Verificador " + suffix,
                "login": "club_517_verify_" + suffix,
                "groups_id": [
                    (
                        6,
                        0,
                        [
                            internal_group.id,
                            payment_group.id,
                        ],
                    )
                ],
            }
        )

        authorizer = Users.create(
            {
                "name": "Ensayo 517 Autorizador " + suffix,
                "login": "club_517_auth_" + suffix,
                "groups_id": [
                    (
                        6,
                        0,
                        [
                            internal_group.id,
                            authorization_group.id,
                        ],
                    )
                ],
            }
        )

        self.assertNotEqual(verifier.id, authorizer.id)

        transfer = (
            Transfer.sudo()
            .with_context(
                club_transfer_record_internal_token=(_TRANSFER_RECORD_INTERNAL_TOKEN)
            )
            .create(
                {
                    "source_certificate_id": source.id,
                    "recipient_person_id": recipient.id,
                    "effective_date": today,
                }
            )
        )

        self.assertEqual(transfer.state, "draft")

        evidence = "PAGO-517-" + suffix

        transfer.with_user(verifier).action_register_payment_verification(
            evidence,
            fully_paid_confirmed=True,
        )

        transfer.invalidate_recordset()

        self.assertEqual(
            transfer.state,
            "payment_verified",
        )

        self.assertEqual(
            transfer.payment_verified_by_id.id,
            verifier.id,
        )

        transfer.with_user(authorizer).action_authorize_transfer()

        transfer.invalidate_recordset()

        # Contrato autorizado correctamente.
        self.assertEqual(transfer.state, "authorized")

        self.assertEqual(
            transfer.recipient_person_id.id,
            recipient.id,
        )

        self.assertEqual(
            transfer.source_certificate_id.id,
            source.id,
        )

        self.assertEqual(
            transfer.authorized_by_id.id,
            authorizer.id,
        )

        self.assertTrue(transfer.authorized_at)

        self.assertFalse(transfer.executed_by_id)
        self.assertFalse(transfer.executed_at)
        self.assertFalse(transfer.recipient_certificate_id)

        original_authorized_at = transfer.authorized_at
        original_payment_at = transfer.payment_verified_at

        # CONTROL 517:
        # El token general no debe permitir cambiar
        # el Certificado original ya autorizado.
        #
        # El savepoint revierte la modificacion
        # si el sistema todavia la permite.
        with self.env.cr.savepoint():
            try:
                (
                    transfer.sudo()
                    .with_context(
                        club_transfer_record_internal_token=(
                            _TRANSFER_RECORD_INTERNAL_TOKEN
                        )
                    )
                    .write(
                        {
                            "source_certificate_id": alternate_source.id,
                        }
                    )
                )
            except AccessError:
                # Resultado esperado tras implementar
                # la proteccion backend.
                pass
            else:
                self.fail("TDD_ROJO_517_ORIGEN_AUTORIZADO_MUTABLE_CON_TOKEN_GENERAL")

        transfer.invalidate_recordset()
        source.invalidate_recordset()

        self.assertEqual(transfer.state, "authorized")

        self.assertEqual(
            transfer.recipient_person_id.id,
            recipient.id,
        )

        self.assertEqual(
            transfer.source_certificate_id.id,
            source.id,
        )

        self.assertEqual(
            transfer.authorized_by_id.id,
            authorizer.id,
        )

        self.assertEqual(
            transfer.authorized_at,
            original_authorized_at,
        )

        self.assertEqual(
            transfer.payment_verified_by_id.id,
            verifier.id,
        )

        self.assertEqual(
            transfer.payment_verified_at,
            original_payment_at,
        )

        self.assertEqual(
            transfer.payment_evidence_reference,
            evidence,
        )

        self.assertFalse(transfer.executed_by_id)
        self.assertFalse(transfer.executed_at)
        self.assertFalse(transfer.recipient_certificate_id)

        self.assertEqual(source.state, "active")
        self.assertEqual(source.member_id.id, donor.id)

        alternate_source.invalidate_recordset()
        self.assertEqual(alternate_source.state, "active")
        self.assertEqual(
            alternate_source.member_id.id,
            alternate_donor.id,
        )

        self.assertEqual(
            Certificate.search_count(
                [
                    (
                        "member_id",
                        "in",
                        [
                            recipient.id,
                            substitute.id,
                        ],
                    ),
                ]
            ),
            0,
        )

    def test_authorized_transfer_effective_date_cannot_change_with_general_token(self):
        """La fecha efectiva autorizada no puede modificarse."""
        import uuid

        from ..models.certificate_transfer import (
            _TRANSFER_RECORD_INTERNAL_TOKEN,
        )

        admin = self.env.ref("base.user_admin")

        Partner = self.env["res.partner"].with_user(admin)
        Certificate = self.env["club.certificate"].with_user(admin)
        Transfer = self.env["club.certificate.transfer"]

        today = fields.Date.context_today(Partner)
        suffix = uuid.uuid4().hex[:10]
        number = 99892000000 + int(suffix[:6], 16)

        donor = Partner.create(
            {
                "name": "Ensayo 522 Cedente " + suffix,
                "company_type": "person",
                "is_company": False,
                "club_person_type": "member",
                "club_id_number": str(number),
                "club_birthdate": fields.Date.to_string(
                    today - relativedelta(years=45)
                ),
                "club_join_date": today,
            }
        )

        recipient = Partner.create(
            {
                "name": "Ensayo 522 Receptor autorizado " + suffix,
                "company_type": "person",
                "is_company": False,
                "club_id_number": str(number + 1),
                "club_birthdate": fields.Date.to_string(
                    today - relativedelta(years=30)
                ),
            }
        )

        # F10-Q: parentesco sintetico para autorizacion positiva.
        # No modifica personas, parentescos ni certificados reales.
        self.assertNotEqual(recipient.club_person_type, "member")

        _f10q_values = {}

        if not recipient.club_id_number:
            _f10q_ci = 99500000000 + recipient.id
            while Partner.search([("club_id_number", "=", str(_f10q_ci))], limit=1):
                _f10q_ci += 1
            _f10q_values["club_id_number"] = str(_f10q_ci)

        if not recipient.club_birthdate:
            _f10q_values["club_birthdate"] = fields.Date.to_string(
                fields.Date.context_today(Partner) - relativedelta(years=35)
            )

        if _f10q_values:
            recipient.write(_f10q_values)

        _f10q_family_link = (
            self.env["club.beneficiary"]
            .sudo()
            .create(
                {
                    "member_id": donor.id,
                    "person_id": recipient.id,
                    "relationship": "spouse",
                    "start_date": fields.Date.context_today(Partner),
                }
            )
        )

        self.assertEqual(_f10q_family_link.state, "active")
        self.assertEqual(_f10q_family_link.member_id.id, donor.id)
        self.assertEqual(_f10q_family_link.person_id.id, recipient.id)

        substitute = Partner.create(
            {
                "name": "Ensayo 522 Receptor sustituto " + suffix,
                "company_type": "person",
                "is_company": False,
                "club_id_number": str(number + 2),
                "club_birthdate": fields.Date.to_string(
                    today - relativedelta(years=35)
                ),
            }
        )

        source = Certificate.create(
            {
                "member_id": donor.id,
                "registration_origin": "migrated",
                "total_value": 5000.0,
                "opening_balance": 0.0,
            }
        )

        self.assertEqual(source.state, "active")
        self.assertEqual(source.member_id.id, donor.id)

        internal_group = self.env.ref("base.group_user")

        payment_group = self.env.ref(
            "club_membership.group_club_certificate_payment_verification"
        )

        authorization_group = self.env.ref(
            "club_membership.group_club_certificate_transfer_authorization"
        )

        Users = self.env["res.users"].sudo().with_context(no_reset_password=True)

        verifier = Users.create(
            {
                "name": "Ensayo 522 Verificador " + suffix,
                "login": "club_522_verify_" + suffix,
                "groups_id": [
                    (
                        6,
                        0,
                        [
                            internal_group.id,
                            payment_group.id,
                        ],
                    )
                ],
            }
        )

        authorizer = Users.create(
            {
                "name": "Ensayo 522 Autorizador " + suffix,
                "login": "club_522_auth_" + suffix,
                "groups_id": [
                    (
                        6,
                        0,
                        [
                            internal_group.id,
                            authorization_group.id,
                        ],
                    )
                ],
            }
        )

        self.assertNotEqual(verifier.id, authorizer.id)

        transfer = (
            Transfer.sudo()
            .with_context(
                club_transfer_record_internal_token=(_TRANSFER_RECORD_INTERNAL_TOKEN)
            )
            .create(
                {
                    "source_certificate_id": source.id,
                    "recipient_person_id": recipient.id,
                    "effective_date": today,
                }
            )
        )

        self.assertEqual(transfer.state, "draft")

        evidence = "PAGO-522-" + suffix

        transfer.with_user(verifier).action_register_payment_verification(
            evidence,
            fully_paid_confirmed=True,
        )

        transfer.invalidate_recordset()

        self.assertEqual(
            transfer.state,
            "payment_verified",
        )

        self.assertEqual(
            transfer.payment_verified_by_id.id,
            verifier.id,
        )

        transfer.with_user(authorizer).action_authorize_transfer()

        transfer.invalidate_recordset()

        # Contrato autorizado correctamente.
        self.assertEqual(transfer.state, "authorized")

        self.assertEqual(
            transfer.recipient_person_id.id,
            recipient.id,
        )

        self.assertEqual(
            transfer.source_certificate_id.id,
            source.id,
        )

        self.assertEqual(
            transfer.authorized_by_id.id,
            authorizer.id,
        )

        self.assertTrue(transfer.authorized_at)

        self.assertFalse(transfer.executed_by_id)
        self.assertFalse(transfer.executed_at)
        self.assertFalse(transfer.recipient_certificate_id)

        original_authorized_at = transfer.authorized_at
        original_payment_at = transfer.payment_verified_at
        original_effective_date = transfer.effective_date
        alternative_effective_date = today - relativedelta(days=7)
        self.assertNotEqual(
            original_effective_date,
            alternative_effective_date,
        )

        # CONTROL 522:
        # El token general no debe permitir cambiar
        # la fecha efectiva de una autorizacion existente.
        #
        # El savepoint revierte la modificacion
        # si el sistema todavia la permite.
        with self.env.cr.savepoint():
            try:
                (
                    transfer.sudo()
                    .with_context(
                        club_transfer_record_internal_token=(
                            _TRANSFER_RECORD_INTERNAL_TOKEN
                        )
                    )
                    .write(
                        {
                            "effective_date": alternative_effective_date,
                        }
                    )
                )
            except AccessError:
                # Resultado esperado tras implementar
                # la proteccion backend.
                pass
            else:
                self.fail("TDD_ROJO_522_FECHA_AUTORIZADA_MUTABLE_CON_TOKEN_GENERAL")

        transfer.invalidate_recordset()
        source.invalidate_recordset()

        self.assertEqual(transfer.state, "authorized")
        self.assertEqual(
            transfer.effective_date,
            original_effective_date,
        )

        self.assertEqual(
            transfer.recipient_person_id.id,
            recipient.id,
        )

        self.assertEqual(
            transfer.source_certificate_id.id,
            source.id,
        )

        self.assertEqual(
            transfer.authorized_by_id.id,
            authorizer.id,
        )

        self.assertEqual(
            transfer.authorized_at,
            original_authorized_at,
        )

        self.assertEqual(
            transfer.payment_verified_by_id.id,
            verifier.id,
        )

        self.assertEqual(
            transfer.payment_verified_at,
            original_payment_at,
        )

        self.assertEqual(
            transfer.payment_evidence_reference,
            evidence,
        )

        self.assertFalse(transfer.executed_by_id)
        self.assertFalse(transfer.executed_at)
        self.assertFalse(transfer.recipient_certificate_id)

        self.assertEqual(source.state, "active")
        self.assertEqual(source.member_id.id, donor.id)

        self.assertEqual(
            Certificate.search_count(
                [
                    (
                        "member_id",
                        "in",
                        [
                            recipient.id,
                            substitute.id,
                        ],
                    ),
                ]
            ),
            0,
        )

    def test_authorized_transfer_authorizer_cannot_be_erased_with_general_token(self):
        """Una autorizacion no permite borrar a su responsable."""
        import uuid

        from ..models.certificate_transfer import (
            _TRANSFER_RECORD_INTERNAL_TOKEN,
        )

        admin = self.env.ref("base.user_admin")

        Partner = self.env["res.partner"].with_user(admin)
        Certificate = self.env["club.certificate"].with_user(admin)
        Transfer = self.env["club.certificate.transfer"]

        today = fields.Date.context_today(Partner)
        suffix = uuid.uuid4().hex[:10]
        number = 99892000000 + int(suffix[:6], 16)

        donor = Partner.create(
            {
                "name": "Ensayo 527 Cedente " + suffix,
                "company_type": "person",
                "is_company": False,
                "club_person_type": "member",
                "club_id_number": str(number),
                "club_birthdate": fields.Date.to_string(
                    today - relativedelta(years=45)
                ),
                "club_join_date": today,
            }
        )

        recipient = Partner.create(
            {
                "name": "Ensayo 527 Receptor autorizado " + suffix,
                "company_type": "person",
                "is_company": False,
                "club_id_number": str(number + 1),
                "club_birthdate": fields.Date.to_string(
                    today - relativedelta(years=30)
                ),
            }
        )

        # F10-Q: parentesco sintetico para autorizacion positiva.
        # No modifica personas, parentescos ni certificados reales.
        self.assertNotEqual(recipient.club_person_type, "member")

        _f10q_values = {}

        if not recipient.club_id_number:
            _f10q_ci = 99500000000 + recipient.id
            while Partner.search([("club_id_number", "=", str(_f10q_ci))], limit=1):
                _f10q_ci += 1
            _f10q_values["club_id_number"] = str(_f10q_ci)

        if not recipient.club_birthdate:
            _f10q_values["club_birthdate"] = fields.Date.to_string(
                fields.Date.context_today(Partner) - relativedelta(years=35)
            )

        if _f10q_values:
            recipient.write(_f10q_values)

        _f10q_family_link = (
            self.env["club.beneficiary"]
            .sudo()
            .create(
                {
                    "member_id": donor.id,
                    "person_id": recipient.id,
                    "relationship": "spouse",
                    "start_date": fields.Date.context_today(Partner),
                }
            )
        )

        self.assertEqual(_f10q_family_link.state, "active")
        self.assertEqual(_f10q_family_link.member_id.id, donor.id)
        self.assertEqual(_f10q_family_link.person_id.id, recipient.id)

        substitute = Partner.create(
            {
                "name": "Ensayo 527 Receptor sustituto " + suffix,
                "company_type": "person",
                "is_company": False,
                "club_id_number": str(number + 2),
                "club_birthdate": fields.Date.to_string(
                    today - relativedelta(years=35)
                ),
            }
        )

        source = Certificate.create(
            {
                "member_id": donor.id,
                "registration_origin": "migrated",
                "total_value": 5000.0,
                "opening_balance": 0.0,
            }
        )

        self.assertEqual(source.state, "active")
        self.assertEqual(source.member_id.id, donor.id)

        internal_group = self.env.ref("base.group_user")

        payment_group = self.env.ref(
            "club_membership.group_club_certificate_payment_verification"
        )

        authorization_group = self.env.ref(
            "club_membership.group_club_certificate_transfer_authorization"
        )

        Users = self.env["res.users"].sudo().with_context(no_reset_password=True)

        verifier = Users.create(
            {
                "name": "Ensayo 527 Verificador " + suffix,
                "login": "club_527_verify_" + suffix,
                "groups_id": [
                    (
                        6,
                        0,
                        [
                            internal_group.id,
                            payment_group.id,
                        ],
                    )
                ],
            }
        )

        authorizer = Users.create(
            {
                "name": "Ensayo 527 Autorizador " + suffix,
                "login": "club_527_auth_" + suffix,
                "groups_id": [
                    (
                        6,
                        0,
                        [
                            internal_group.id,
                            authorization_group.id,
                        ],
                    )
                ],
            }
        )

        self.assertNotEqual(verifier.id, authorizer.id)

        transfer = (
            Transfer.sudo()
            .with_context(
                club_transfer_record_internal_token=(_TRANSFER_RECORD_INTERNAL_TOKEN)
            )
            .create(
                {
                    "source_certificate_id": source.id,
                    "recipient_person_id": recipient.id,
                    "effective_date": today,
                }
            )
        )

        self.assertEqual(transfer.state, "draft")

        evidence = "PAGO-527-" + suffix

        transfer.with_user(verifier).action_register_payment_verification(
            evidence,
            fully_paid_confirmed=True,
        )

        transfer.invalidate_recordset()

        self.assertEqual(
            transfer.state,
            "payment_verified",
        )

        self.assertEqual(
            transfer.payment_verified_by_id.id,
            verifier.id,
        )

        transfer.with_user(authorizer).action_authorize_transfer()

        transfer.invalidate_recordset()

        # Contrato autorizado correctamente.
        self.assertEqual(transfer.state, "authorized")

        self.assertEqual(
            transfer.recipient_person_id.id,
            recipient.id,
        )

        self.assertEqual(
            transfer.source_certificate_id.id,
            source.id,
        )

        self.assertEqual(
            transfer.authorized_by_id.id,
            authorizer.id,
        )

        self.assertTrue(transfer.authorized_at)

        self.assertFalse(transfer.executed_by_id)
        self.assertFalse(transfer.executed_at)
        self.assertFalse(transfer.recipient_certificate_id)

        original_authorized_at = transfer.authorized_at
        original_authorizer_id = transfer.authorized_by_id.id
        self.assertTrue(original_authorizer_id)
        original_payment_at = transfer.payment_verified_at

        # CONTROL 527:
        # El token general no debe permitir cambiar
        # quien asumio formalmente la autorizacion.
        #
        # El savepoint revierte la modificacion
        # si el sistema todavia la permite.
        with self.env.cr.savepoint():
            try:
                (
                    transfer.sudo()
                    .with_context(
                        club_transfer_record_internal_token=(
                            _TRANSFER_RECORD_INTERNAL_TOKEN
                        )
                    )
                    .write(
                        {
                            "authorized_by_id": False,
                        }
                    )
                )
            except AccessError:
                # Resultado esperado tras implementar
                # la proteccion backend.
                pass
            else:
                self.fail("TDD_ROJO_527_AUTORIZADOR_MUTABLE_CON_TOKEN_GENERAL")

        transfer.invalidate_recordset()
        source.invalidate_recordset()

        self.assertEqual(transfer.state, "authorized")
        self.assertEqual(
            transfer.authorized_by_id.id,
            original_authorizer_id,
        )

        self.assertEqual(
            transfer.recipient_person_id.id,
            recipient.id,
        )

        self.assertEqual(
            transfer.source_certificate_id.id,
            source.id,
        )

        self.assertEqual(
            transfer.authorized_by_id.id,
            authorizer.id,
        )

        self.assertEqual(
            transfer.authorized_at,
            original_authorized_at,
        )

        self.assertEqual(
            transfer.payment_verified_by_id.id,
            verifier.id,
        )

        self.assertEqual(
            transfer.payment_verified_at,
            original_payment_at,
        )

        self.assertEqual(
            transfer.payment_evidence_reference,
            evidence,
        )

        self.assertFalse(transfer.executed_by_id)
        self.assertFalse(transfer.executed_at)
        self.assertFalse(transfer.recipient_certificate_id)

        self.assertEqual(source.state, "active")
        self.assertEqual(source.member_id.id, donor.id)

        self.assertEqual(
            Certificate.search_count(
                [
                    (
                        "member_id",
                        "in",
                        [
                            recipient.id,
                            substitute.id,
                        ],
                    ),
                ]
            ),
            0,
        )

    def test_authorized_transfer_authorized_at_cannot_change_with_general_token(self):
        """La fecha y hora de autorizacion deben conservarse."""
        import uuid

        from ..models.certificate_transfer import (
            _TRANSFER_RECORD_INTERNAL_TOKEN,
        )

        admin = self.env.ref("base.user_admin")

        Partner = self.env["res.partner"].with_user(admin)
        Certificate = self.env["club.certificate"].with_user(admin)
        Transfer = self.env["club.certificate.transfer"]

        today = fields.Date.context_today(Partner)
        suffix = uuid.uuid4().hex[:10]
        number = 99892000000 + int(suffix[:6], 16)

        donor = Partner.create(
            {
                "name": "Ensayo 532 Cedente " + suffix,
                "company_type": "person",
                "is_company": False,
                "club_person_type": "member",
                "club_id_number": str(number),
                "club_birthdate": fields.Date.to_string(
                    today - relativedelta(years=45)
                ),
                "club_join_date": today,
            }
        )

        recipient = Partner.create(
            {
                "name": "Ensayo 532 Receptor autorizado " + suffix,
                "company_type": "person",
                "is_company": False,
                "club_id_number": str(number + 1),
                "club_birthdate": fields.Date.to_string(
                    today - relativedelta(years=30)
                ),
            }
        )

        # F10-Q: parentesco sintetico para autorizacion positiva.
        # No modifica personas, parentescos ni certificados reales.
        self.assertNotEqual(recipient.club_person_type, "member")

        _f10q_values = {}

        if not recipient.club_id_number:
            _f10q_ci = 99500000000 + recipient.id
            while Partner.search([("club_id_number", "=", str(_f10q_ci))], limit=1):
                _f10q_ci += 1
            _f10q_values["club_id_number"] = str(_f10q_ci)

        if not recipient.club_birthdate:
            _f10q_values["club_birthdate"] = fields.Date.to_string(
                fields.Date.context_today(Partner) - relativedelta(years=35)
            )

        if _f10q_values:
            recipient.write(_f10q_values)

        _f10q_family_link = (
            self.env["club.beneficiary"]
            .sudo()
            .create(
                {
                    "member_id": donor.id,
                    "person_id": recipient.id,
                    "relationship": "spouse",
                    "start_date": fields.Date.context_today(Partner),
                }
            )
        )

        self.assertEqual(_f10q_family_link.state, "active")
        self.assertEqual(_f10q_family_link.member_id.id, donor.id)
        self.assertEqual(_f10q_family_link.person_id.id, recipient.id)

        substitute = Partner.create(
            {
                "name": "Ensayo 532 Receptor sustituto " + suffix,
                "company_type": "person",
                "is_company": False,
                "club_id_number": str(number + 2),
                "club_birthdate": fields.Date.to_string(
                    today - relativedelta(years=35)
                ),
            }
        )

        source = Certificate.create(
            {
                "member_id": donor.id,
                "registration_origin": "migrated",
                "total_value": 5000.0,
                "opening_balance": 0.0,
            }
        )

        self.assertEqual(source.state, "active")
        self.assertEqual(source.member_id.id, donor.id)

        internal_group = self.env.ref("base.group_user")

        payment_group = self.env.ref(
            "club_membership.group_club_certificate_payment_verification"
        )

        authorization_group = self.env.ref(
            "club_membership.group_club_certificate_transfer_authorization"
        )

        Users = self.env["res.users"].sudo().with_context(no_reset_password=True)

        verifier = Users.create(
            {
                "name": "Ensayo 532 Verificador " + suffix,
                "login": "club_532_verify_" + suffix,
                "groups_id": [
                    (
                        6,
                        0,
                        [
                            internal_group.id,
                            payment_group.id,
                        ],
                    )
                ],
            }
        )

        authorizer = Users.create(
            {
                "name": "Ensayo 532 Autorizador " + suffix,
                "login": "club_532_auth_" + suffix,
                "groups_id": [
                    (
                        6,
                        0,
                        [
                            internal_group.id,
                            authorization_group.id,
                        ],
                    )
                ],
            }
        )

        self.assertNotEqual(verifier.id, authorizer.id)

        transfer = (
            Transfer.sudo()
            .with_context(
                club_transfer_record_internal_token=(_TRANSFER_RECORD_INTERNAL_TOKEN)
            )
            .create(
                {
                    "source_certificate_id": source.id,
                    "recipient_person_id": recipient.id,
                    "effective_date": today,
                }
            )
        )

        self.assertEqual(transfer.state, "draft")

        evidence = "PAGO-532-" + suffix

        transfer.with_user(verifier).action_register_payment_verification(
            evidence,
            fully_paid_confirmed=True,
        )

        transfer.invalidate_recordset()

        self.assertEqual(
            transfer.state,
            "payment_verified",
        )

        self.assertEqual(
            transfer.payment_verified_by_id.id,
            verifier.id,
        )

        transfer.with_user(authorizer).action_authorize_transfer()

        transfer.invalidate_recordset()

        # Contrato autorizado correctamente.
        self.assertEqual(transfer.state, "authorized")

        self.assertEqual(
            transfer.recipient_person_id.id,
            recipient.id,
        )

        self.assertEqual(
            transfer.source_certificate_id.id,
            source.id,
        )

        self.assertEqual(
            transfer.authorized_by_id.id,
            authorizer.id,
        )

        self.assertTrue(transfer.authorized_at)

        self.assertFalse(transfer.executed_by_id)
        self.assertFalse(transfer.executed_at)
        self.assertFalse(transfer.recipient_certificate_id)

        original_authorized_at = transfer.authorized_at
        original_authorizer_id = transfer.authorized_by_id.id
        self.assertTrue(original_authorizer_id)
        original_payment_at = transfer.payment_verified_at

        # CONTROL 532:
        # El token general no debe permitir cambiar
        # cuando ocurrio la autorizacion institucional.
        #
        # El savepoint revierte la modificacion
        # si el sistema todavia la permite.
        with self.env.cr.savepoint():
            try:
                (
                    transfer.sudo()
                    .with_context(
                        club_transfer_record_internal_token=(
                            _TRANSFER_RECORD_INTERNAL_TOKEN
                        )
                    )
                    .write(
                        {
                            "authorized_at": False,
                        }
                    )
                )
            except AccessError:
                # Resultado esperado tras implementar
                # la proteccion backend.
                pass
            else:
                self.fail("TDD_ROJO_532_AUTHORIZED_AT_MUTABLE_CON_TOKEN_GENERAL")

        transfer.invalidate_recordset()
        source.invalidate_recordset()

        self.assertEqual(transfer.state, "authorized")
        self.assertEqual(
            transfer.authorized_by_id.id,
            original_authorizer_id,
        )

        self.assertEqual(
            transfer.recipient_person_id.id,
            recipient.id,
        )

        self.assertEqual(
            transfer.source_certificate_id.id,
            source.id,
        )

        self.assertEqual(
            transfer.authorized_by_id.id,
            authorizer.id,
        )

        self.assertEqual(
            transfer.authorized_at,
            original_authorized_at,
        )

        self.assertEqual(
            transfer.payment_verified_by_id.id,
            verifier.id,
        )

        self.assertEqual(
            transfer.payment_verified_at,
            original_payment_at,
        )

        self.assertEqual(
            transfer.payment_evidence_reference,
            evidence,
        )

        self.assertFalse(transfer.executed_by_id)
        self.assertFalse(transfer.executed_at)
        self.assertFalse(transfer.recipient_certificate_id)

        self.assertEqual(source.state, "active")
        self.assertEqual(source.member_id.id, donor.id)

        self.assertEqual(
            Certificate.search_count(
                [
                    (
                        "member_id",
                        "in",
                        [
                            recipient.id,
                            substitute.id,
                        ],
                    ),
                ]
            ),
            0,
        )

    def test_verified_and_authorized_transfer_payment_evidence_cannot_be_erased_with_general_token(
        self,
    ):
        """La fecha y hora de autorizacion deben conservarse."""
        import uuid

        from ..models.certificate_transfer import (
            _TRANSFER_RECORD_INTERNAL_TOKEN,
        )

        admin = self.env.ref("base.user_admin")

        Partner = self.env["res.partner"].with_user(admin)
        Certificate = self.env["club.certificate"].with_user(admin)
        Transfer = self.env["club.certificate.transfer"]

        today = fields.Date.context_today(Partner)
        suffix = uuid.uuid4().hex[:10]
        number = 99892000000 + int(suffix[:6], 16)

        donor = Partner.create(
            {
                "name": "Ensayo 539 Cedente " + suffix,
                "company_type": "person",
                "is_company": False,
                "club_person_type": "member",
                "club_id_number": str(number),
                "club_birthdate": fields.Date.to_string(
                    today - relativedelta(years=45)
                ),
                "club_join_date": today,
            }
        )

        recipient = Partner.create(
            {
                "name": "Ensayo 539 Receptor autorizado " + suffix,
                "company_type": "person",
                "is_company": False,
                "club_id_number": str(number + 1),
                "club_birthdate": fields.Date.to_string(
                    today - relativedelta(years=30)
                ),
            }
        )

        # F10-Q: parentesco sintetico para autorizacion positiva.
        # No modifica personas, parentescos ni certificados reales.
        self.assertNotEqual(recipient.club_person_type, "member")

        _f10q_values = {}

        if not recipient.club_id_number:
            _f10q_ci = 99500000000 + recipient.id
            while Partner.search([("club_id_number", "=", str(_f10q_ci))], limit=1):
                _f10q_ci += 1
            _f10q_values["club_id_number"] = str(_f10q_ci)

        if not recipient.club_birthdate:
            _f10q_values["club_birthdate"] = fields.Date.to_string(
                fields.Date.context_today(Partner) - relativedelta(years=35)
            )

        if _f10q_values:
            recipient.write(_f10q_values)

        _f10q_family_link = (
            self.env["club.beneficiary"]
            .sudo()
            .create(
                {
                    "member_id": donor.id,
                    "person_id": recipient.id,
                    "relationship": "spouse",
                    "start_date": fields.Date.context_today(Partner),
                }
            )
        )

        self.assertEqual(_f10q_family_link.state, "active")
        self.assertEqual(_f10q_family_link.member_id.id, donor.id)
        self.assertEqual(_f10q_family_link.person_id.id, recipient.id)

        substitute = Partner.create(
            {
                "name": "Ensayo 539 Receptor sustituto " + suffix,
                "company_type": "person",
                "is_company": False,
                "club_id_number": str(number + 2),
                "club_birthdate": fields.Date.to_string(
                    today - relativedelta(years=35)
                ),
            }
        )

        source = Certificate.create(
            {
                "member_id": donor.id,
                "registration_origin": "migrated",
                "total_value": 5000.0,
                "opening_balance": 0.0,
            }
        )

        self.assertEqual(source.state, "active")
        self.assertEqual(source.member_id.id, donor.id)

        internal_group = self.env.ref("base.group_user")

        payment_group = self.env.ref(
            "club_membership.group_club_certificate_payment_verification"
        )

        authorization_group = self.env.ref(
            "club_membership.group_club_certificate_transfer_authorization"
        )

        Users = self.env["res.users"].sudo().with_context(no_reset_password=True)

        verifier = Users.create(
            {
                "name": "Ensayo 539 Verificador " + suffix,
                "login": "club_539_verify_" + suffix,
                "groups_id": [
                    (
                        6,
                        0,
                        [
                            internal_group.id,
                            payment_group.id,
                        ],
                    )
                ],
            }
        )

        authorizer = Users.create(
            {
                "name": "Ensayo 539 Autorizador " + suffix,
                "login": "club_539_auth_" + suffix,
                "groups_id": [
                    (
                        6,
                        0,
                        [
                            internal_group.id,
                            authorization_group.id,
                        ],
                    )
                ],
            }
        )

        self.assertNotEqual(verifier.id, authorizer.id)

        transfer = (
            Transfer.sudo()
            .with_context(
                club_transfer_record_internal_token=(_TRANSFER_RECORD_INTERNAL_TOKEN)
            )
            .create(
                {
                    "source_certificate_id": source.id,
                    "recipient_person_id": recipient.id,
                    "effective_date": today,
                }
            )
        )

        self.assertEqual(transfer.state, "draft")

        evidence = "PAGO-539-" + suffix

        transfer.with_user(verifier).action_register_payment_verification(
            evidence,
            fully_paid_confirmed=True,
        )

        transfer.invalidate_recordset()

        self.assertEqual(
            transfer.state,
            "payment_verified",
        )

        self.assertEqual(
            transfer.payment_verified_by_id.id,
            verifier.id,
        )

        # TDD 539: evidencia del pago ya verificado.
        original_evidence_539 = transfer.payment_evidence_reference
        self.assertTrue(original_evidence_539)
        with self.env.cr.savepoint():
            try:
                (
                    transfer.sudo()
                    .with_context(
                        club_transfer_record_internal_token=(
                            _TRANSFER_RECORD_INTERNAL_TOKEN
                        )
                    )
                    .write(
                        {
                            "payment_evidence_reference": False,
                        }
                    )
                )
            except AccessError:
                # Resultado esperado tras implementar
                # la proteccion backend.
                pass
            else:
                self.fail("TDD_ROJO_539_EVIDENCIA_PAGO_MUTABLE_CON_TOKEN_GENERAL")

        transfer.invalidate_recordset(["payment_evidence_reference"])
        self.assertEqual(
            transfer.payment_evidence_reference,
            original_evidence_539,
        )

        transfer.with_user(authorizer).action_authorize_transfer()

        transfer.invalidate_recordset()

        # Contrato autorizado correctamente.
        self.assertEqual(transfer.state, "authorized")

        self.assertEqual(
            transfer.recipient_person_id.id,
            recipient.id,
        )

        self.assertEqual(
            transfer.source_certificate_id.id,
            source.id,
        )

        self.assertEqual(
            transfer.authorized_by_id.id,
            authorizer.id,
        )

        self.assertTrue(transfer.authorized_at)

        self.assertFalse(transfer.executed_by_id)
        self.assertFalse(transfer.executed_at)
        self.assertFalse(transfer.recipient_certificate_id)

        original_authorized_at = transfer.authorized_at
        original_authorizer_id = transfer.authorized_by_id.id
        self.assertTrue(original_authorizer_id)
        original_payment_at = transfer.payment_verified_at

        # CONTROL 539:
        # El token general no debe permitir cambiar
        # cuando ocurrio la autorizacion institucional.
        #
        # El savepoint revierte la modificacion
        # si el sistema todavia la permite.
        with self.env.cr.savepoint():
            try:
                (
                    transfer.sudo()
                    .with_context(
                        club_transfer_record_internal_token=(
                            _TRANSFER_RECORD_INTERNAL_TOKEN
                        )
                    )
                    .write(
                        {
                            "payment_evidence_reference": False,
                        }
                    )
                )
            except AccessError:
                # Resultado esperado tras implementar
                # la proteccion backend.
                pass
            else:
                self.fail("TDD_ROJO_539_EVIDENCIA_PAGO_MUTABLE_CON_TOKEN_GENERAL")

        transfer.invalidate_recordset()
        source.invalidate_recordset()

        self.assertEqual(transfer.state, "authorized")
        self.assertEqual(
            transfer.authorized_by_id.id,
            original_authorizer_id,
        )

        self.assertEqual(
            transfer.recipient_person_id.id,
            recipient.id,
        )

        self.assertEqual(
            transfer.source_certificate_id.id,
            source.id,
        )

        self.assertEqual(
            transfer.authorized_by_id.id,
            authorizer.id,
        )

        self.assertEqual(
            transfer.authorized_at,
            original_authorized_at,
        )

        self.assertEqual(
            transfer.payment_verified_by_id.id,
            verifier.id,
        )

        self.assertEqual(
            transfer.payment_verified_at,
            original_payment_at,
        )

        self.assertEqual(
            transfer.payment_evidence_reference,
            evidence,
        )

        self.assertFalse(transfer.executed_by_id)
        self.assertFalse(transfer.executed_at)
        self.assertFalse(transfer.recipient_certificate_id)

        self.assertEqual(source.state, "active")
        self.assertEqual(source.member_id.id, donor.id)

        self.assertEqual(
            Certificate.search_count(
                [
                    (
                        "member_id",
                        "in",
                        [
                            recipient.id,
                            substitute.id,
                        ],
                    ),
                ]
            ),
            0,
        )

        transfer.invalidate_recordset(["payment_evidence_reference"])
        self.assertEqual(
            transfer.payment_evidence_reference,
            original_evidence_539,
        )

    def test_verified_and_authorized_transfer_payment_verifier_cannot_be_erased_with_general_token(
        self,
    ):
        """La identidad del verificador del pago es inmutable."""
        import uuid

        from ..models.certificate_transfer import (
            _TRANSFER_RECORD_INTERNAL_TOKEN,
        )

        admin = self.env.ref("base.user_admin")

        Partner = self.env["res.partner"].with_user(admin)
        Certificate = self.env["club.certificate"].with_user(admin)
        Transfer = self.env["club.certificate.transfer"]

        today = fields.Date.context_today(Partner)
        suffix = uuid.uuid4().hex[:10]
        number = 99892000000 + int(suffix[:6], 16)

        donor = Partner.create(
            {
                "name": "Ensayo 539 Cedente " + suffix,
                "company_type": "person",
                "is_company": False,
                "club_person_type": "member",
                "club_id_number": str(number),
                "club_birthdate": fields.Date.to_string(
                    today - relativedelta(years=45)
                ),
                "club_join_date": today,
            }
        )

        recipient = Partner.create(
            {
                "name": "Ensayo 539 Receptor autorizado " + suffix,
                "company_type": "person",
                "is_company": False,
                "club_id_number": str(number + 1),
                "club_birthdate": fields.Date.to_string(
                    today - relativedelta(years=30)
                ),
            }
        )

        # F10-Q: parentesco sintetico para autorizacion positiva.
        # No modifica personas, parentescos ni certificados reales.
        self.assertNotEqual(recipient.club_person_type, "member")

        _f10q_values = {}

        if not recipient.club_id_number:
            _f10q_ci = 99500000000 + recipient.id
            while Partner.search([("club_id_number", "=", str(_f10q_ci))], limit=1):
                _f10q_ci += 1
            _f10q_values["club_id_number"] = str(_f10q_ci)

        if not recipient.club_birthdate:
            _f10q_values["club_birthdate"] = fields.Date.to_string(
                fields.Date.context_today(Partner) - relativedelta(years=35)
            )

        if _f10q_values:
            recipient.write(_f10q_values)

        _f10q_family_link = (
            self.env["club.beneficiary"]
            .sudo()
            .create(
                {
                    "member_id": donor.id,
                    "person_id": recipient.id,
                    "relationship": "spouse",
                    "start_date": fields.Date.context_today(Partner),
                }
            )
        )

        self.assertEqual(_f10q_family_link.state, "active")
        self.assertEqual(_f10q_family_link.member_id.id, donor.id)
        self.assertEqual(_f10q_family_link.person_id.id, recipient.id)

        substitute = Partner.create(
            {
                "name": "Ensayo 539 Receptor sustituto " + suffix,
                "company_type": "person",
                "is_company": False,
                "club_id_number": str(number + 2),
                "club_birthdate": fields.Date.to_string(
                    today - relativedelta(years=35)
                ),
            }
        )

        source = Certificate.create(
            {
                "member_id": donor.id,
                "registration_origin": "migrated",
                "total_value": 5000.0,
                "opening_balance": 0.0,
            }
        )

        self.assertEqual(source.state, "active")
        self.assertEqual(source.member_id.id, donor.id)

        internal_group = self.env.ref("base.group_user")

        payment_group = self.env.ref(
            "club_membership.group_club_certificate_payment_verification"
        )

        authorization_group = self.env.ref(
            "club_membership.group_club_certificate_transfer_authorization"
        )

        Users = self.env["res.users"].sudo().with_context(no_reset_password=True)

        verifier = Users.create(
            {
                "name": "Ensayo 539 Verificador " + suffix,
                "login": "club_539_verify_" + suffix,
                "groups_id": [
                    (
                        6,
                        0,
                        [
                            internal_group.id,
                            payment_group.id,
                        ],
                    )
                ],
            }
        )

        authorizer = Users.create(
            {
                "name": "Ensayo 539 Autorizador " + suffix,
                "login": "club_539_auth_" + suffix,
                "groups_id": [
                    (
                        6,
                        0,
                        [
                            internal_group.id,
                            authorization_group.id,
                        ],
                    )
                ],
            }
        )

        self.assertNotEqual(verifier.id, authorizer.id)

        transfer = (
            Transfer.sudo()
            .with_context(
                club_transfer_record_internal_token=(_TRANSFER_RECORD_INTERNAL_TOKEN)
            )
            .create(
                {
                    "source_certificate_id": source.id,
                    "recipient_person_id": recipient.id,
                    "effective_date": today,
                }
            )
        )

        self.assertEqual(transfer.state, "draft")

        evidence = "PAGO-539-" + suffix

        transfer.with_user(verifier).action_register_payment_verification(
            evidence,
            fully_paid_confirmed=True,
        )

        transfer.invalidate_recordset()

        self.assertEqual(
            transfer.state,
            "payment_verified",
        )

        self.assertEqual(
            transfer.payment_verified_by_id.id,
            verifier.id,
        )

        # TDD 544: evidencia del pago ya verificado.
        original_evidence_544 = transfer.payment_evidence_reference
        self.assertTrue(original_evidence_544)
        # Registrar identidad legitima antes de intentar alterarla.
        original_verifier_id_544 = transfer.payment_verified_by_id.id
        self.assertTrue(original_verifier_id_544)

        with self.env.cr.savepoint():
            try:
                (
                    transfer.sudo()
                    .with_context(
                        club_transfer_record_internal_token=(
                            _TRANSFER_RECORD_INTERNAL_TOKEN
                        )
                    )
                    .write(
                        {
                            "payment_verified_by_id": False,
                        }
                    )
                )
            except AccessError:
                # Resultado esperado tras implementar
                # la proteccion backend.
                pass
            else:
                self.fail("TDD_ROJO_544_VERIFICADOR_PAGO_MUTABLE_CON_TOKEN_GENERAL")

        transfer.invalidate_recordset(["payment_verified_by_id"])
        self.assertEqual(
            transfer.payment_verified_by_id.id,
            original_verifier_id_544,
        )

        transfer.invalidate_recordset(["payment_evidence_reference"])
        self.assertEqual(
            transfer.payment_evidence_reference,
            original_evidence_544,
        )

        transfer.with_user(authorizer).action_authorize_transfer()

        transfer.invalidate_recordset()

        # Contrato autorizado correctamente.
        self.assertEqual(transfer.state, "authorized")

        self.assertEqual(
            transfer.recipient_person_id.id,
            recipient.id,
        )

        self.assertEqual(
            transfer.source_certificate_id.id,
            source.id,
        )

        self.assertEqual(
            transfer.authorized_by_id.id,
            authorizer.id,
        )

        self.assertTrue(transfer.authorized_at)

        self.assertFalse(transfer.executed_by_id)
        self.assertFalse(transfer.executed_at)
        self.assertFalse(transfer.recipient_certificate_id)

        original_authorized_at = transfer.authorized_at
        original_authorizer_id = transfer.authorized_by_id.id
        self.assertTrue(original_authorizer_id)
        original_payment_at = transfer.payment_verified_at

        # CONTROL 539:
        # El token general no debe permitir cambiar
        # cuando ocurrio la autorizacion institucional.
        #
        # El savepoint revierte la modificacion
        # si el sistema todavia la permite.
        with self.env.cr.savepoint():
            try:
                (
                    transfer.sudo()
                    .with_context(
                        club_transfer_record_internal_token=(
                            _TRANSFER_RECORD_INTERNAL_TOKEN
                        )
                    )
                    .write(
                        {
                            "payment_verified_by_id": False,
                        }
                    )
                )
            except AccessError:
                # Resultado esperado tras implementar
                # la proteccion backend.
                pass
            else:
                self.fail("TDD_ROJO_544_VERIFICADOR_PAGO_MUTABLE_CON_TOKEN_GENERAL")

        transfer.invalidate_recordset(["payment_verified_by_id"])
        self.assertEqual(
            transfer.payment_verified_by_id.id,
            original_verifier_id_544,
        )

        transfer.invalidate_recordset()
        source.invalidate_recordset()

        self.assertEqual(transfer.state, "authorized")
        self.assertEqual(
            transfer.authorized_by_id.id,
            original_authorizer_id,
        )

        self.assertEqual(
            transfer.recipient_person_id.id,
            recipient.id,
        )

        self.assertEqual(
            transfer.source_certificate_id.id,
            source.id,
        )

        self.assertEqual(
            transfer.authorized_by_id.id,
            authorizer.id,
        )

        self.assertEqual(
            transfer.authorized_at,
            original_authorized_at,
        )

        self.assertEqual(
            transfer.payment_verified_by_id.id,
            verifier.id,
        )

        self.assertEqual(
            transfer.payment_verified_at,
            original_payment_at,
        )

        self.assertEqual(
            transfer.payment_evidence_reference,
            evidence,
        )

        self.assertFalse(transfer.executed_by_id)
        self.assertFalse(transfer.executed_at)
        self.assertFalse(transfer.recipient_certificate_id)

        self.assertEqual(source.state, "active")
        self.assertEqual(source.member_id.id, donor.id)

        self.assertEqual(
            Certificate.search_count(
                [
                    (
                        "member_id",
                        "in",
                        [
                            recipient.id,
                            substitute.id,
                        ],
                    ),
                ]
            ),
            0,
        )

        transfer.invalidate_recordset(["payment_evidence_reference"])
        self.assertEqual(
            transfer.payment_evidence_reference,
            original_evidence_544,
        )

    def test_verified_and_authorized_transfer_payment_verified_at_cannot_be_erased_with_general_token(
        self,
    ):
        """La fecha de verificacion del pago es inmutable."""
        import uuid

        from ..models.certificate_transfer import (
            _TRANSFER_RECORD_INTERNAL_TOKEN,
        )

        admin = self.env.ref("base.user_admin")

        Partner = self.env["res.partner"].with_user(admin)
        Certificate = self.env["club.certificate"].with_user(admin)
        Transfer = self.env["club.certificate.transfer"]

        today = fields.Date.context_today(Partner)
        suffix = uuid.uuid4().hex[:10]
        number = 99892000000 + int(suffix[:6], 16)

        donor = Partner.create(
            {
                "name": "Ensayo 539 Cedente " + suffix,
                "company_type": "person",
                "is_company": False,
                "club_person_type": "member",
                "club_id_number": str(number),
                "club_birthdate": fields.Date.to_string(
                    today - relativedelta(years=45)
                ),
                "club_join_date": today,
            }
        )

        recipient = Partner.create(
            {
                "name": "Ensayo 539 Receptor autorizado " + suffix,
                "company_type": "person",
                "is_company": False,
                "club_id_number": str(number + 1),
                "club_birthdate": fields.Date.to_string(
                    today - relativedelta(years=30)
                ),
            }
        )

        # F10-Q: parentesco sintetico para autorizacion positiva.
        # No modifica personas, parentescos ni certificados reales.
        self.assertNotEqual(recipient.club_person_type, "member")

        _f10q_values = {}

        if not recipient.club_id_number:
            _f10q_ci = 99500000000 + recipient.id
            while Partner.search([("club_id_number", "=", str(_f10q_ci))], limit=1):
                _f10q_ci += 1
            _f10q_values["club_id_number"] = str(_f10q_ci)

        if not recipient.club_birthdate:
            _f10q_values["club_birthdate"] = fields.Date.to_string(
                fields.Date.context_today(Partner) - relativedelta(years=35)
            )

        if _f10q_values:
            recipient.write(_f10q_values)

        _f10q_family_link = (
            self.env["club.beneficiary"]
            .sudo()
            .create(
                {
                    "member_id": donor.id,
                    "person_id": recipient.id,
                    "relationship": "spouse",
                    "start_date": fields.Date.context_today(Partner),
                }
            )
        )

        self.assertEqual(_f10q_family_link.state, "active")
        self.assertEqual(_f10q_family_link.member_id.id, donor.id)
        self.assertEqual(_f10q_family_link.person_id.id, recipient.id)

        substitute = Partner.create(
            {
                "name": "Ensayo 539 Receptor sustituto " + suffix,
                "company_type": "person",
                "is_company": False,
                "club_id_number": str(number + 2),
                "club_birthdate": fields.Date.to_string(
                    today - relativedelta(years=35)
                ),
            }
        )

        source = Certificate.create(
            {
                "member_id": donor.id,
                "registration_origin": "migrated",
                "total_value": 5000.0,
                "opening_balance": 0.0,
            }
        )

        self.assertEqual(source.state, "active")
        self.assertEqual(source.member_id.id, donor.id)

        internal_group = self.env.ref("base.group_user")

        payment_group = self.env.ref(
            "club_membership.group_club_certificate_payment_verification"
        )

        authorization_group = self.env.ref(
            "club_membership.group_club_certificate_transfer_authorization"
        )

        Users = self.env["res.users"].sudo().with_context(no_reset_password=True)

        verifier = Users.create(
            {
                "name": "Ensayo 539 Verificador " + suffix,
                "login": "club_539_verify_" + suffix,
                "groups_id": [
                    (
                        6,
                        0,
                        [
                            internal_group.id,
                            payment_group.id,
                        ],
                    )
                ],
            }
        )

        authorizer = Users.create(
            {
                "name": "Ensayo 539 Autorizador " + suffix,
                "login": "club_539_auth_" + suffix,
                "groups_id": [
                    (
                        6,
                        0,
                        [
                            internal_group.id,
                            authorization_group.id,
                        ],
                    )
                ],
            }
        )

        self.assertNotEqual(verifier.id, authorizer.id)

        transfer = (
            Transfer.sudo()
            .with_context(
                club_transfer_record_internal_token=(_TRANSFER_RECORD_INTERNAL_TOKEN)
            )
            .create(
                {
                    "source_certificate_id": source.id,
                    "recipient_person_id": recipient.id,
                    "effective_date": today,
                }
            )
        )

        self.assertEqual(transfer.state, "draft")

        evidence = "PAGO-539-" + suffix

        transfer.with_user(verifier).action_register_payment_verification(
            evidence,
            fully_paid_confirmed=True,
        )

        transfer.invalidate_recordset()

        self.assertEqual(
            transfer.state,
            "payment_verified",
        )

        self.assertEqual(
            transfer.payment_verified_by_id.id,
            verifier.id,
        )

        # TDD 548: evidencia del pago ya verificado.
        original_evidence_544 = transfer.payment_evidence_reference
        self.assertTrue(original_evidence_544)
        # Registrar identidad legitima antes de intentar alterarla.
        original_verifier_id_548 = transfer.payment_verified_by_id.id
        self.assertTrue(original_verifier_id_548)

        # Conservar la fecha de verificacion legitima.
        original_verified_at_548 = transfer.payment_verified_at
        self.assertTrue(original_verified_at_548)

        with self.env.cr.savepoint():
            try:
                (
                    transfer.sudo()
                    .with_context(
                        club_transfer_record_internal_token=(
                            _TRANSFER_RECORD_INTERNAL_TOKEN
                        )
                    )
                    .write(
                        {
                            "payment_verified_at": False,
                        }
                    )
                )
            except AccessError:
                # Resultado esperado tras implementar
                # la proteccion backend.
                pass
            else:
                self.fail("TDD_ROJO_548_FECHA_VERIFICACION_MUTABLE_CON_TOKEN_GENERAL")

        transfer.invalidate_recordset(["payment_verified_at"])
        self.assertEqual(
            transfer.payment_verified_at,
            original_verified_at_548,
        )

        transfer.invalidate_recordset(["payment_verified_by_id"])
        self.assertEqual(
            transfer.payment_verified_by_id.id,
            original_verifier_id_548,
        )

        transfer.invalidate_recordset(["payment_evidence_reference"])
        self.assertEqual(
            transfer.payment_evidence_reference,
            original_evidence_544,
        )

        transfer.with_user(authorizer).action_authorize_transfer()

        transfer.invalidate_recordset()

        # Contrato autorizado correctamente.
        self.assertEqual(transfer.state, "authorized")

        self.assertEqual(
            transfer.recipient_person_id.id,
            recipient.id,
        )

        self.assertEqual(
            transfer.source_certificate_id.id,
            source.id,
        )

        self.assertEqual(
            transfer.authorized_by_id.id,
            authorizer.id,
        )

        self.assertTrue(transfer.authorized_at)

        self.assertFalse(transfer.executed_by_id)
        self.assertFalse(transfer.executed_at)
        self.assertFalse(transfer.recipient_certificate_id)

        original_authorized_at = transfer.authorized_at
        original_authorizer_id = transfer.authorized_by_id.id
        self.assertTrue(original_authorizer_id)
        original_payment_at = transfer.payment_verified_at

        # CONTROL 539:
        # El token general no debe permitir cambiar
        # cuando ocurrio la autorizacion institucional.
        #
        # El savepoint revierte la modificacion
        # si el sistema todavia la permite.
        with self.env.cr.savepoint():
            try:
                (
                    transfer.sudo()
                    .with_context(
                        club_transfer_record_internal_token=(
                            _TRANSFER_RECORD_INTERNAL_TOKEN
                        )
                    )
                    .write(
                        {
                            "payment_verified_at": False,
                        }
                    )
                )
            except AccessError:
                # Resultado esperado tras implementar
                # la proteccion backend.
                pass
            else:
                self.fail("TDD_ROJO_548_FECHA_VERIFICACION_MUTABLE_CON_TOKEN_GENERAL")

        transfer.invalidate_recordset(["payment_verified_at"])
        self.assertEqual(
            transfer.payment_verified_at,
            original_verified_at_548,
        )

        transfer.invalidate_recordset(["payment_verified_by_id"])
        self.assertEqual(
            transfer.payment_verified_by_id.id,
            original_verifier_id_548,
        )

        transfer.invalidate_recordset()
        source.invalidate_recordset()

        self.assertEqual(transfer.state, "authorized")
        self.assertEqual(
            transfer.authorized_by_id.id,
            original_authorizer_id,
        )

        self.assertEqual(
            transfer.recipient_person_id.id,
            recipient.id,
        )

        self.assertEqual(
            transfer.source_certificate_id.id,
            source.id,
        )

        self.assertEqual(
            transfer.authorized_by_id.id,
            authorizer.id,
        )

        self.assertEqual(
            transfer.authorized_at,
            original_authorized_at,
        )

        self.assertEqual(
            transfer.payment_verified_by_id.id,
            verifier.id,
        )

        self.assertEqual(
            transfer.payment_verified_at,
            original_payment_at,
        )

        self.assertEqual(
            transfer.payment_evidence_reference,
            evidence,
        )

        self.assertFalse(transfer.executed_by_id)
        self.assertFalse(transfer.executed_at)
        self.assertFalse(transfer.recipient_certificate_id)

        self.assertEqual(source.state, "active")
        self.assertEqual(source.member_id.id, donor.id)

        self.assertEqual(
            Certificate.search_count(
                [
                    (
                        "member_id",
                        "in",
                        [
                            recipient.id,
                            substitute.id,
                        ],
                    ),
                ]
            ),
            0,
        )

        transfer.invalidate_recordset(["payment_evidence_reference"])
        self.assertEqual(
            transfer.payment_evidence_reference,
            original_evidence_544,
        )

    def test_create_rejects_preassigned_payment_audit_with_internal_token(self):
        """Cancelar pago verificado no ejecuta patrimonio."""
        import uuid

        from ..models.certificate_transfer import (
            _TRANSFER_RECORD_INTERNAL_TOKEN,
        )

        admin = self.env.ref("base.user_admin")

        Partner = self.env["res.partner"].with_user(admin)
        Certificate = self.env["club.certificate"].with_user(admin)
        Transfer = self.env["club.certificate.transfer"]

        today = fields.Date.context_today(Partner)
        suffix = uuid.uuid4().hex[:10]
        number = 99890000000 + int(suffix[:6], 16)

        donor = Partner.create(
            {
                "name": "Ensayo 501 Cedente " + suffix,
                "company_type": "person",
                "is_company": False,
                "club_person_type": "member",
                "club_id_number": str(number),
                "club_birthdate": fields.Date.to_string(
                    today - relativedelta(years=45)
                ),
                "club_join_date": today,
            }
        )

        recipient = Partner.create(
            {
                "name": "Ensayo 501 Receptor " + suffix,
                "company_type": "person",
                "is_company": False,
                "club_id_number": str(number + 1),
                "club_birthdate": fields.Date.to_string(
                    today - relativedelta(years=30)
                ),
            }
        )

        source = Certificate.create(
            {
                "member_id": donor.id,
                "registration_origin": "migrated",
                "total_value": 5000.0,
                "opening_balance": 0.0,
            }
        )

        self.assertEqual(source.state, "active")
        self.assertEqual(source.member_id.id, donor.id)

        internal_group = self.env.ref("base.group_user")

        payment_group = self.env.ref(
            "club_membership.group_club_certificate_payment_verification"
        )

        cancellation_group = self.env.ref(
            "club_membership.group_club_certificate_transfer_cancellation"
        )

        Users = self.env["res.users"].sudo().with_context(no_reset_password=True)

        verifier = Users.create(
            {
                "name": "Ensayo 501 Verificador " + suffix,
                "login": "club_501_verify_" + suffix,
                "groups_id": [
                    (
                        6,
                        0,
                        [
                            internal_group.id,
                            payment_group.id,
                        ],
                    )
                ],
            }
        )

        canceller = Users.create(
            {
                "name": "Ensayo 501 Cancelador " + suffix,
                "login": "club_501_cancel_" + suffix,
                "groups_id": [
                    (
                        6,
                        0,
                        [
                            internal_group.id,
                            cancellation_group.id,
                        ],
                    )
                ],
            }
        )

        self.assertNotEqual(
            verifier.id,
            canceller.id,
        )

        internal_transfer = Transfer.sudo().with_context(
            club_transfer_record_internal_token=(_TRANSFER_RECORD_INTERNAL_TOKEN)
        )

        # El token interno no autoriza falsificar
        # los datos de auditoria de verificacion.
        for audit_field, audit_value in (
            (
                "payment_evidence_reference",
                "TDD-557-DOCUMENTO",
            ),
            (
                "payment_verified_by_id",
                self.env.user.id,
            ),
            (
                "payment_verified_at",
                fields.Datetime.now(),
            ),
        ):
            vals = {
                "source_certificate_id": source.id,
                "recipient_person_id": recipient.id,
                "effective_date": today,
            }
            vals[audit_field] = audit_value

            try:
                with self.env.cr.savepoint():
                    internal_transfer.create(vals)
                    raise AssertionError(
                        "TDD_ROJO_557_CREATE_PREASIGNACION_" + audit_field
                    )
            except AccessError:
                pass

        transfer = internal_transfer.create(
            {
                "source_certificate_id": source.id,
                "recipient_person_id": recipient.id,
                "effective_date": today,
            }
        )

        # El alta institucional ordinaria debe funcionar.
        self.assertTrue(transfer.exists())
        self.assertEqual(transfer.state, "draft")
        self.assertFalse(transfer.payment_evidence_reference)
        self.assertFalse(transfer.payment_verified_by_id)
        self.assertFalse(transfer.payment_verified_at)

    def test_create_rejects_preassigned_authorization_and_cancellation_audit_with_internal_token(
        self,
    ):
        """Cancelar pago verificado no ejecuta patrimonio."""
        import uuid

        from ..models.certificate_transfer import (
            _TRANSFER_RECORD_INTERNAL_TOKEN,
        )

        admin = self.env.ref("base.user_admin")

        Partner = self.env["res.partner"].with_user(admin)
        Certificate = self.env["club.certificate"].with_user(admin)
        Transfer = self.env["club.certificate.transfer"]

        today = fields.Date.context_today(Partner)
        suffix = uuid.uuid4().hex[:10]
        number = 99890000000 + int(suffix[:6], 16)

        donor = Partner.create(
            {
                "name": "Ensayo 501 Cedente " + suffix,
                "company_type": "person",
                "is_company": False,
                "club_person_type": "member",
                "club_id_number": str(number),
                "club_birthdate": fields.Date.to_string(
                    today - relativedelta(years=45)
                ),
                "club_join_date": today,
            }
        )

        recipient = Partner.create(
            {
                "name": "Ensayo 501 Receptor " + suffix,
                "company_type": "person",
                "is_company": False,
                "club_id_number": str(number + 1),
                "club_birthdate": fields.Date.to_string(
                    today - relativedelta(years=30)
                ),
            }
        )

        source = Certificate.create(
            {
                "member_id": donor.id,
                "registration_origin": "migrated",
                "total_value": 5000.0,
                "opening_balance": 0.0,
            }
        )

        self.assertEqual(source.state, "active")
        self.assertEqual(source.member_id.id, donor.id)

        internal_group = self.env.ref("base.group_user")

        payment_group = self.env.ref(
            "club_membership.group_club_certificate_payment_verification"
        )

        cancellation_group = self.env.ref(
            "club_membership.group_club_certificate_transfer_cancellation"
        )

        Users = self.env["res.users"].sudo().with_context(no_reset_password=True)

        verifier = Users.create(
            {
                "name": "Ensayo 501 Verificador " + suffix,
                "login": "club_501_verify_" + suffix,
                "groups_id": [
                    (
                        6,
                        0,
                        [
                            internal_group.id,
                            payment_group.id,
                        ],
                    )
                ],
            }
        )

        canceller = Users.create(
            {
                "name": "Ensayo 501 Cancelador " + suffix,
                "login": "club_501_cancel_" + suffix,
                "groups_id": [
                    (
                        6,
                        0,
                        [
                            internal_group.id,
                            cancellation_group.id,
                        ],
                    )
                ],
            }
        )

        self.assertNotEqual(
            verifier.id,
            canceller.id,
        )

        internal_transfer = Transfer.sudo().with_context(
            club_transfer_record_internal_token=(_TRANSFER_RECORD_INTERNAL_TOKEN)
        )

        # El token interno no autoriza falsificar
        # los datos de auditoria de verificacion.

        # No preasignar estados ni auditorias de autorizacion
        # o cancelacion durante el alta de una transferencia.
        # Nunca se solicita el estado executed.
        for audit_field, audit_value in (
            (
                "state",
                "authorized",
            ),
            (
                "authorized_by_id",
                self.env.user.id,
            ),
            (
                "authorized_at",
                fields.Datetime.now(),
            ),
            (
                "cancelled_by_id",
                self.env.user.id,
            ),
            (
                "cancelled_at",
                fields.Datetime.now(),
            ),
        ):
            vals = {
                "source_certificate_id": source.id,
                "recipient_person_id": recipient.id,
                "effective_date": today,
            }
            vals[audit_field] = audit_value

            try:
                with self.env.cr.savepoint():
                    internal_transfer.create(vals)
                    raise AssertionError(
                        "TDD_ROJO_563_CREATE_PREASIGNACION_" + audit_field
                    )
            except AccessError:
                pass

        transfer = internal_transfer.create(
            {
                "source_certificate_id": source.id,
                "recipient_person_id": recipient.id,
                "effective_date": today,
            }
        )

        # El alta institucional ordinaria debe funcionar.
        self.assertTrue(transfer.exists())
        self.assertEqual(transfer.state, "draft")
        self.assertFalse(transfer.payment_evidence_reference)
        self.assertFalse(transfer.payment_verified_by_id)
        self.assertFalse(transfer.payment_verified_at)

    def test_write_rejects_direct_cancellation_audit_with_general_internal_token(self):
        """Cancelar pago verificado no ejecuta patrimonio."""
        import uuid

        from ..models.certificate_transfer import (
            _TRANSFER_RECORD_INTERNAL_TOKEN,
        )

        admin = self.env.ref("base.user_admin")

        Partner = self.env["res.partner"].with_user(admin)
        Certificate = self.env["club.certificate"].with_user(admin)
        Transfer = self.env["club.certificate.transfer"]

        today = fields.Date.context_today(Partner)
        suffix = uuid.uuid4().hex[:10]
        number = 99890000000 + int(suffix[:6], 16)

        donor = Partner.create(
            {
                "name": "Ensayo 501 Cedente " + suffix,
                "company_type": "person",
                "is_company": False,
                "club_person_type": "member",
                "club_id_number": str(number),
                "club_birthdate": fields.Date.to_string(
                    today - relativedelta(years=45)
                ),
                "club_join_date": today,
            }
        )

        recipient = Partner.create(
            {
                "name": "Ensayo 501 Receptor " + suffix,
                "company_type": "person",
                "is_company": False,
                "club_id_number": str(number + 1),
                "club_birthdate": fields.Date.to_string(
                    today - relativedelta(years=30)
                ),
            }
        )

        source = Certificate.create(
            {
                "member_id": donor.id,
                "registration_origin": "migrated",
                "total_value": 5000.0,
                "opening_balance": 0.0,
            }
        )

        self.assertEqual(source.state, "active")
        self.assertEqual(source.member_id.id, donor.id)

        internal_group = self.env.ref("base.group_user")

        payment_group = self.env.ref(
            "club_membership.group_club_certificate_payment_verification"
        )

        cancellation_group = self.env.ref(
            "club_membership.group_club_certificate_transfer_cancellation"
        )

        Users = self.env["res.users"].sudo().with_context(no_reset_password=True)

        verifier = Users.create(
            {
                "name": "Ensayo 501 Verificador " + suffix,
                "login": "club_501_verify_" + suffix,
                "groups_id": [
                    (
                        6,
                        0,
                        [
                            internal_group.id,
                            payment_group.id,
                        ],
                    )
                ],
            }
        )

        canceller = Users.create(
            {
                "name": "Ensayo 501 Cancelador " + suffix,
                "login": "club_501_cancel_" + suffix,
                "groups_id": [
                    (
                        6,
                        0,
                        [
                            internal_group.id,
                            cancellation_group.id,
                        ],
                    )
                ],
            }
        )

        self.assertNotEqual(
            verifier.id,
            canceller.id,
        )

        internal_transfer = Transfer.sudo().with_context(
            club_transfer_record_internal_token=(_TRANSFER_RECORD_INTERNAL_TOKEN)
        )

        # El token interno no autoriza falsificar
        # los datos de auditoria de verificacion.

        # No preasignar estados ni auditorias de autorizacion
        # o cancelacion durante el alta de una transferencia.
        # Nunca se solicita el estado executed.
        transfer = internal_transfer.create(
            {
                "source_certificate_id": source.id,
                "recipient_person_id": recipient.id,
                "effective_date": today,
            }
        )

        # El alta institucional ordinaria debe funcionar.
        self.assertTrue(transfer.exists())
        self.assertEqual(transfer.state, "draft")
        self.assertFalse(transfer.payment_evidence_reference)
        self.assertFalse(transfer.payment_verified_by_id)
        self.assertFalse(transfer.payment_verified_at)

        # El token interno general no debe permitir
        # falsificar la identidad o fecha de cancelacion.
        # No se solicita ningun cambio de estado.
        for audit_field, audit_value in (
            (
                "cancelled_by_id",
                self.env.user.id,
            ),
            (
                "cancelled_at",
                fields.Datetime.now(),
            ),
        ):
            try:
                with self.env.cr.savepoint():
                    internal_transfer.browse(transfer.id).write(
                        {
                            audit_field: audit_value,
                        }
                    )
                    raise AssertionError(
                        "TDD_ROJO_569_WRITE_CANCEL_AUDIT_" + audit_field
                    )
            except AccessError:
                pass

        transfer.invalidate_recordset(
            [
                "state",
                "cancelled_by_id",
                "cancelled_at",
            ]
        )
        self.assertEqual(transfer.state, "draft")
        self.assertFalse(transfer.cancelled_by_id)
        self.assertFalse(transfer.cancelled_at)

    def test_write_rejects_direct_payment_verified_state_with_general_internal_token(
        self,
    ):
        """Cancelar pago verificado no ejecuta patrimonio."""
        import uuid

        from ..models.certificate_transfer import (
            _TRANSFER_RECORD_INTERNAL_TOKEN,
        )

        admin = self.env.ref("base.user_admin")

        Partner = self.env["res.partner"].with_user(admin)
        Certificate = self.env["club.certificate"].with_user(admin)
        Transfer = self.env["club.certificate.transfer"]

        today = fields.Date.context_today(Partner)
        suffix = uuid.uuid4().hex[:10]
        number = 99890000000 + int(suffix[:6], 16)

        donor = Partner.create(
            {
                "name": "Ensayo 501 Cedente " + suffix,
                "company_type": "person",
                "is_company": False,
                "club_person_type": "member",
                "club_id_number": str(number),
                "club_birthdate": fields.Date.to_string(
                    today - relativedelta(years=45)
                ),
                "club_join_date": today,
            }
        )

        recipient = Partner.create(
            {
                "name": "Ensayo 501 Receptor " + suffix,
                "company_type": "person",
                "is_company": False,
                "club_id_number": str(number + 1),
                "club_birthdate": fields.Date.to_string(
                    today - relativedelta(years=30)
                ),
            }
        )

        source = Certificate.create(
            {
                "member_id": donor.id,
                "registration_origin": "migrated",
                "total_value": 5000.0,
                "opening_balance": 0.0,
            }
        )

        self.assertEqual(source.state, "active")
        self.assertEqual(source.member_id.id, donor.id)

        internal_group = self.env.ref("base.group_user")

        payment_group = self.env.ref(
            "club_membership.group_club_certificate_payment_verification"
        )

        cancellation_group = self.env.ref(
            "club_membership.group_club_certificate_transfer_cancellation"
        )

        Users = self.env["res.users"].sudo().with_context(no_reset_password=True)

        verifier = Users.create(
            {
                "name": "Ensayo 501 Verificador " + suffix,
                "login": "club_501_verify_" + suffix,
                "groups_id": [
                    (
                        6,
                        0,
                        [
                            internal_group.id,
                            payment_group.id,
                        ],
                    )
                ],
            }
        )

        canceller = Users.create(
            {
                "name": "Ensayo 501 Cancelador " + suffix,
                "login": "club_501_cancel_" + suffix,
                "groups_id": [
                    (
                        6,
                        0,
                        [
                            internal_group.id,
                            cancellation_group.id,
                        ],
                    )
                ],
            }
        )

        self.assertNotEqual(
            verifier.id,
            canceller.id,
        )

        internal_transfer = Transfer.sudo().with_context(
            club_transfer_record_internal_token=(_TRANSFER_RECORD_INTERNAL_TOKEN)
        )

        # El token interno no autoriza falsificar
        # los datos de auditoria de verificacion.

        # No preasignar estados ni auditorias de autorizacion
        # o cancelacion durante el alta de una transferencia.
        # Nunca se solicita el estado executed.
        transfer = internal_transfer.create(
            {
                "source_certificate_id": source.id,
                "recipient_person_id": recipient.id,
                "effective_date": today,
            }
        )

        # El alta institucional ordinaria debe funcionar.
        self.assertTrue(transfer.exists())
        self.assertEqual(transfer.state, "draft")
        self.assertFalse(transfer.payment_evidence_reference)
        self.assertFalse(transfer.payment_verified_by_id)
        self.assertFalse(transfer.payment_verified_at)

        # El token interno general no debe permitir
        # falsificar la identidad o fecha de cancelacion.
        # No se solicita ningun cambio de estado.

        # Un cambio directo de estado no sustituye
        # la verificacion institucional del pago.
        # No se solicita el estado executed.
        self.assertEqual(transfer.state, "draft")

        try:
            with self.env.cr.savepoint():
                internal_transfer.browse(transfer.id).write(
                    {
                        "state": "payment_verified",
                    }
                )
                raise AssertionError("TDD_ROJO_574_WRITE_STATE_payment_verified")
        except AccessError:
            pass

        transfer.invalidate_recordset(["state"])
        self.assertEqual(transfer.state, "draft")
