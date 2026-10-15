from odoo import api, fields, models
from odoo.exceptions import AccessError, UserError, ValidationError

# Token privado: no puede falsificarse enviando True por RPC.
_TRANSFER_RECORD_INTERNAL_TOKEN = object()

_TRANSFER_CANCELLATION_AUDIT_INTERNAL_TOKEN = object()

_TRANSFER_PAYMENT_STATE_INTERNAL_TOKEN = object()
_TRANSFER_AUTHORIZATION_STATE_INTERNAL_TOKEN = object()


class ClubCertificateTransfer(models.Model):
    _name = "club.certificate.transfer"
    _description = "Transferencia Patrimonial de Certificado"
    _order = "id desc"

    def _check_recipient_has_registered_family_link(self):
        """Exige parentesco registrado con el titular cedente."""
        Beneficiary = self.env["club.beneficiary"].sudo()

        allowed_relationships = (
            "spouse",
            "partner",
            "child",
            "stepchild",
            "parent",
            "family_dependent",
        )

        for transfer in self:
            source = transfer.source_certificate_id
            recipient = transfer.recipient_person_id
            donor = source.member_id

            valid_link = (
                donor
                and recipient
                and Beneficiary.search(
                    [
                        ("member_id", "=", donor.id),
                        ("person_id", "=", recipient.id),
                        ("relationship", "in", allowed_relationships),
                        ("state", "in", ("active", "finalized")),
                    ],
                    limit=1,
                )
            )

            if not valid_link:
                raise ValidationError(
                    self.env._(
                        "El receptor debe acreditar un vínculo familiar "
                        "registrado con el Socio cedente para "
                        "recibir el Certificado por transferencia."
                    )
                )

        return True

    def _check_recipient_not_blocked_beneficiary(self):
        """No autorizar transferencias a personas con vinculo bloqueado."""
        Beneficiary = self.env["club.beneficiary"].sudo()
        for transfer in self:
            recipient = transfer.recipient_person_id
            if recipient and Beneficiary.search(
                [
                    ("person_id", "=", recipient.id),
                    ("state", "=", "blocked"),
                ],
                limit=1,
            ):
                raise ValidationError(
                    self.env._(
                        "Beneficiario bloqueado: debe regularizar su "
                        "situacion antes de recibir un Certificado "
                        "Patrimonial por transferencia."
                    )
                )
        return True

    def _check_recipient_not_current_member(self):
        """Un Socio vigente no puede recibir otra titularidad transferida."""
        for transfer in self:
            recipient = transfer.recipient_person_id
            if recipient and recipient.club_person_type == "member":
                raise ValidationError(
                    self.env._(
                        "El receptor ya es Socio vigente y no puede "
                        "recibir un Certificado por transferencia."
                    )
                )
        return True

    source_certificate_id = fields.Many2one(
        "club.certificate",
        string="Certificado original",
        required=True,
        ondelete="restrict",
        index=True,
        copy=False,
    )

    recipient_person_id = fields.Many2one(
        "res.partner",
        string="Persona receptora",
        required=True,
        ondelete="restrict",
        index=True,
        copy=False,
    )

    effective_date = fields.Date(
        string="Fecha efectiva",
        required=True,
        copy=False,
    )

    payment_evidence_reference = fields.Char(
        string="Referencia del respaldo de pago total",
        copy=False,
        readonly=True,
    )

    payment_verified_by_id = fields.Many2one(
        "res.users",
        string="Pago verificado por",
        ondelete="restrict",
        copy=False,
        readonly=True,
    )

    payment_verified_at = fields.Datetime(
        string="Fecha y hora de verificacion",
        copy=False,
        readonly=True,
    )

    cancellation_reason = fields.Text(
        string="Motivo institucional de cancelacion",
        copy=False,
        readonly=True,
        help=(
            "Justificacion registrada durante el "
            "procedimiento institucional de cancelacion."
        ),
    )

    cancelled_by_id = fields.Many2one(
        "res.users",
        string="Cancelado por",
        ondelete="restrict",
        copy=False,
        readonly=True,
    )

    cancelled_at = fields.Datetime(
        string="Fecha y hora de cancelacion",
        copy=False,
        readonly=True,
    )

    authorized_by_id = fields.Many2one(
        "res.users",
        string="Autorizado por",
        ondelete="restrict",
        copy=False,
        readonly=True,
    )

    authorized_at = fields.Datetime(
        string="Fecha y hora de autorizacion",
        copy=False,
        readonly=True,
    )

    executed_at = fields.Datetime(
        string="Fecha y hora de ejecucion",
        copy=False,
        readonly=True,
    )

    executed_by_id = fields.Many2one(
        "res.users",
        string="Ejecutado por",
        readonly=True,
        copy=False,
        index=True,
        ondelete="restrict",
        help=(
            "Funcionario responsable de la ejecución patrimonial. "
            "Se registra únicamente al ejecutar una cesión autorizada."
        ),
    )

    recipient_certificate_id = fields.Many2one(
        "club.certificate",
        string="Certificado del receptor",
        ondelete="restrict",
        copy=False,
        readonly=True,
    )

    state = fields.Selection(
        [
            ("draft", "Borrador"),
            ("payment_verified", "Pago verificado"),
            ("authorized", "Autorizado"),
            ("executed", "Ejecutado"),
            ("cancelled", "Cancelado"),
        ],
        string="Estado",
        default="draft",
        required=True,
        readonly=True,
        copy=False,
    )

    @api.model
    def _validate_payment_evidence(self, evidence):
        """Valida integridad de los datos documentales.

        No certifica el pago ni autoriza la transferencia.
        """
        if not isinstance(evidence, dict):
            raise ValidationError(
                self.env._("La evidencia documental debe contener datos estructurados.")
            )

        reference = evidence.get("payment_evidence_reference")

        if not isinstance(reference, str) or not reference.strip():
            raise ValidationError(
                self.env._(
                    "Debe registrarse una referencia documental "
                    "valida del pago total del Certificado."
                )
            )

        verifier_id = evidence.get("payment_verified_by_id")

        if (
            not isinstance(verifier_id, int)
            or isinstance(verifier_id, bool)
            or verifier_id <= 0
        ):
            raise ValidationError(
                self.env._("Debe identificarse al funcionario que verifico el pago.")
            )

        verified_at = evidence.get("payment_verified_at")

        if not verified_at:
            raise ValidationError(
                self.env._(
                    "Debe registrarse la fecha y hora de verificacion documental."
                )
            )

        try:
            normalized_date = fields.Datetime.to_datetime(verified_at)
        except (TypeError, ValueError, OverflowError):
            normalized_date = None

        if not normalized_date:
            raise ValidationError(
                self.env._("La fecha y hora de verificacion documental no son validas.")
            )

        return True

    @api.model
    def _check_payment_verifier_permission(self):
        """Exige permiso institucional al usuario autenticado."""
        group_xmlid = "club_membership.group_club_certificate_payment_verification"

        if not self.env.user.has_group(group_xmlid):
            raise AccessError(
                self.env._(
                    "El usuario actual no tiene autorizacion "
                    "institucional para verificar el pago "
                    "de Certificados Patrimoniales."
                )
            )

        return True

    @api.model
    def _prepare_payment_verification_values(self, evidence_reference):
        """Prepara evidencia con identidad autenticada.

        No verifica materialmente el pago.
        No autoriza ni ejecuta transferencias.
        """
        self._check_payment_verifier_permission()

        # Solo se admite una referencia documental.
        # Nunca se acepta un diccionario con identidad
        # o fecha declaradas por el solicitante.
        if not isinstance(evidence_reference, str):
            raise ValidationError(
                self.env._(
                    "Debe proporcionar exclusivamente "
                    "la referencia del respaldo documental. "
                    "La identidad y fecha del funcionario "
                    "son asignadas por el sistema."
                )
            )

        reference = evidence_reference.strip()

        values = {
            "payment_evidence_reference": reference,
            "payment_verified_by_id": self.env.user.id,
            "payment_verified_at": fields.Datetime.now(),
        }

        # Reutilizar las validaciones documentales.
        self._validate_payment_evidence(values)

        return values

    def action_register_payment_verification(
        self,
        evidence_reference,
        fully_paid_confirmed=False,
    ):
        """Registra la verificacion documental de pago total.

        No autoriza ni ejecuta la transferencia patrimonial.
        """
        self.ensure_one()

        # El permiso se comprueba ANTES de usar sudo.
        self._check_payment_verifier_permission()

        # Solo se acepta una confirmacion booleana expresa.
        if fully_paid_confirmed is not True:
            raise ValidationError(
                self.env._(
                    "El funcionario debe confirmar expresamente "
                    "que reviso el respaldo documental y "
                    "comprobo el pago total del Certificado."
                )
            )

        # La identidad y fecha se obtienen del usuario
        # autenticado y del servidor, nunca del solicitante.
        values = self._prepare_payment_verification_values(evidence_reference)

        # Bloquear la fila durante la operacion para impedir
        # verificaciones simultaneas sobre el mismo tramite.
        self.env.cr.execute(
            """
            SELECT id
              FROM club_certificate_transfer
             WHERE id = %s
             FOR UPDATE
            """,
            (self.id,),
        )

        if not self.env.cr.fetchone():
            raise UserError(self.env._("El tramite de transferencia no existe."))

        # El acceso elevado es exclusivamente interno,
        # despues de comprobar el permiso institucional.
        transfer = self.sudo()

        transfer.invalidate_recordset(
            [
                "state",
                "payment_evidence_reference",
                "payment_verified_by_id",
                "payment_verified_at",
            ]
        )

        if transfer.state != "draft":
            raise UserError(
                self.env._(
                    "Solo se puede verificar documentalmente "
                    "un tramite en estado Borrador."
                )
            )

        # BLOQUE 427: el Certificado original debe seguir
        # activo al momento de verificar documentalmente.
        source_certificate = transfer.source_certificate_id

        if not source_certificate:
            raise UserError(
                self.env._(
                    "El tramite no tiene un Certificado Patrimonial original valido."
                )
            )

        # Asegurar que cualquier cambio ORM pendiente
        # del estado llegue a PostgreSQL.
        source_certificate.flush_recordset(["state"])

        # Bloquear el Certificado original y consultar
        # su estado actualizado dentro de la transaccion.
        self.env.cr.execute(
            """
            SELECT state
              FROM club_certificate
             WHERE id = %s
             FOR UPDATE
            """,
            (source_certificate.id,),
        )

        source_state_row = self.env.cr.fetchone()

        if not source_state_row or source_state_row[0] != "active":
            raise UserError(
                self.env._(
                    "No puede verificarse una transferencia "
                    "si el Certificado Patrimonial original "
                    "no esta Activo."
                )
            )

        # BLOQUE 435: impedir verificaciones vigentes duplicadas.
        #
        # El Certificado original fue bloqueado arriba
        # mediante SELECT ... FOR UPDATE.
        # Esto serializa las verificaciones simultaneas
        # que intentan utilizar el mismo Certificado.

        # Asegurar que los cambios ORM pendientes sean
        # visibles para la consulta SQL.
        self.env["club.certificate.transfer"].flush_model(
            [
                "source_certificate_id",
                "state",
            ]
        )

        self.env.cr.execute(
            """
            SELECT id
              FROM club_certificate_transfer
             WHERE source_certificate_id = %s
               AND id != %s
               AND state IN (
                   'payment_verified',
                   'authorized',
                   'executed'
               )
             LIMIT 1
            """,
            (
                source_certificate.id,
                transfer.id,
            ),
        )

        if self.env.cr.fetchone():
            raise UserError(
                self.env._(
                    "Este Certificado Patrimonial ya tiene "
                    "otro tramite de transferencia con "
                    "pago verificado, autorizado o ejecutado. "
                    "No puede registrarse una segunda "
                    "verificacion vigente."
                )
            )

        # Rechazar un borrador que ya tenga datos de
        # verificacion, incluso si su estado es incorrecto.
        if (
            transfer.payment_evidence_reference
            or transfer.payment_verified_by_id
            or transfer.payment_verified_at
        ):
            raise UserError(
                self.env._(
                    "Este tramite ya contiene informacion de verificacion documental."
                )
            )

        # Escritura mediante el token privado del modelo.
        # No se conceden permisos CRUD generales.
        transfer.with_context(
            club_transfer_record_internal_token=(_TRANSFER_RECORD_INTERNAL_TOKEN)
        ).with_context(
            club_transfer_payment_state_internal_token=(
                _TRANSFER_PAYMENT_STATE_INTERNAL_TOKEN
            )
        )._write_payment_verification_with_unique_guard(values)

        return True

    def action_cancel_transfer(self, reason):
        """Cancela un tramite mediante autoridad institucional.

        Preserva las verificaciones documentales anteriores.
        No modifica el Certificado Patrimonial original.
        """
        self.ensure_one()

        # Comprobar el permiso ANTES de elevar privilegios.
        if not self.env.user.has_group(
            "club_membership.group_club_certificate_transfer_cancellation"
        ):
            raise AccessError(
                self.env._(
                    "No tiene autorizacion institucional "
                    "para cancelar transferencias patrimoniales."
                )
            )

        # Solo se recibe el motivo.
        # La identidad y fecha las determina el sistema.
        if not isinstance(reason, str) or not reason.strip():
            raise ValidationError(
                self.env._(
                    "Debe proporcionar un motivo institucional "
                    "obligatorio para cancelar la transferencia."
                )
            )

        clean_reason = reason.strip()

        # Acceso elevado exclusivamente para este
        # procedimiento despues de validar el permiso.
        transfer = self.sudo()

        # Sincronizar cualquier cambio ORM pendiente.
        transfer.flush_recordset(
            [
                "state",
                "cancellation_reason",
                "cancelled_by_id",
                "cancelled_at",
            ]
        )

        # Serializar cancelaciones simultaneas
        # sobre un mismo tramite.
        self.env.cr.execute(
            """
            SELECT id
              FROM club_certificate_transfer
             WHERE id = %s
             FOR UPDATE
            """,
            (self.id,),
        )

        if not self.env.cr.fetchone():
            raise UserError(self.env._("El tramite de transferencia no existe."))

        # Actualizar la cache despues de adquirir
        # el bloqueo transaccional.
        transfer.invalidate_recordset(
            [
                "state",
                "cancellation_reason",
                "cancelled_by_id",
                "cancelled_at",
            ]
        )

        if transfer.state not in (
            "draft",
            "payment_verified",
        ):
            raise UserError(
                self.env._(
                    "Solo pueden cancelarse transferencias "
                    "en Borrador o con Pago verificado. "
                    "Los tramites autorizados, ejecutados "
                    "o previamente cancelados no admiten "
                    "esta operacion."
                )
            )

        # No permitir sobrescribir una cancelacion
        # historica, aunque el estado fuese inconsistente.
        if (
            transfer.cancellation_reason
            or transfer.cancelled_by_id
            or transfer.cancelled_at
        ):
            raise UserError(
                self.env._(
                    "El tramite ya contiene informacion de cancelacion institucional."
                )
            )

        # Se usa el token privado ya existente.
        # No se conceden permisos CRUD generales.
        transfer.with_context(
            club_transfer_record_internal_token=(_TRANSFER_RECORD_INTERNAL_TOKEN)
        ).with_context(
            club_transfer_cancellation_audit_internal_token=(
                _TRANSFER_CANCELLATION_AUDIT_INTERNAL_TOKEN
            )
        ).write(
            {
                "cancellation_reason": clean_reason,
                "cancelled_by_id": self.env.user.id,
                "cancelled_at": fields.Datetime.now(),
                "state": "cancelled",
            }
        )

        # No se modifica:
        # - Certificado original
        # - Referencia documental del pago
        # - Funcionario o fecha de verificacion
        # - Certificado del receptor
        return True

    def init(self):
        """Garantiza unicidad patrimonial desde PostgreSQL.

        Solo una transferencia por Certificado puede estar
        en pago verificado, autorizada o ejecutada.

        Borradores y cancelaciones historicas no bloquean
        futuros tramites.
        """
        self.env.cr.execute(
            """
            CREATE UNIQUE INDEX IF NOT EXISTS
                club_certificate_transfer_live_source_uniq
            ON club_certificate_transfer (
                source_certificate_id
            )
            WHERE state IN (
                'payment_verified',
                'authorized',
                'executed'
            )
            """
        )

    def _write_payment_verification_with_unique_guard(self, values):
        """Escribe una verificacion protegiendo la unicidad SQL.

        Convierte exclusivamente la colision del indice
        patrimonial en un error institucional controlado.
        """
        from psycopg2.errors import UniqueViolation

        self.ensure_one()

        # No crear una ruta alternativa de escritura.
        # El token privado sigue siendo obligatorio.
        self._check_internal_transfer_access()

        required_keys = {
            "payment_evidence_reference",
            "payment_verified_by_id",
            "payment_verified_at",
        }

        if not isinstance(values, dict) or set(values) != required_keys:
            raise ValidationError(
                self.env._(
                    "Los datos de verificacion documental "
                    "no tienen la estructura requerida."
                )
            )

        if self.state != "draft":
            raise UserError(
                self.env._(
                    "Solo puede verificarse una transferencia "
                    "que permanezca en Borrador."
                )
            )

        try:
            # El savepoint permite revertir solo la
            # escritura fallida y conservar utilizable
            # la transaccion actual.
            with self.env.cr.savepoint():
                self.write(
                    {
                        **values,
                        "state": "payment_verified",
                    }
                )

                # Obligar a PostgreSQL a comprobar
                # el indice dentro del savepoint.
                self.flush_recordset(
                    [
                        "source_certificate_id",
                        "state",
                        "payment_evidence_reference",
                        "payment_verified_by_id",
                        "payment_verified_at",
                    ]
                )

        except UniqueViolation as error:
            constraint_name = getattr(
                getattr(error, "diag", None),
                "constraint_name",
                None,
            )

            # No ocultar errores de otras restricciones.
            if constraint_name != ("club_certificate_transfer_live_source_uniq"):
                raise

            raise UserError(
                self.env._(
                    "Este Certificado Patrimonial ya tiene "
                    "otra transferencia vigente con pago "
                    "verificado, autorizada o ejecutada. "
                    "No puede registrarse una segunda "
                    "verificacion para el mismo Certificado."
                )
            ) from error

        return True

    def _check_transfer_authorizer_permission(self):
        """Comprueba el permiso antes de elevar privilegios."""
        from odoo.exceptions import AccessError

        group_xmlid = "club_membership.group_club_certificate_transfer_authorization"

        if not self.env.user.has_group(group_xmlid):
            raise AccessError(
                self.env._(
                    "No tiene permiso institucional para "
                    "autorizar transferencias patrimoniales."
                )
            )

        return True

    def action_authorize_transfer(self):
        """Autoriza sin ejecutar el cambio de titularidad.

        Exige un actor distinto al funcionario que
        verifico documentalmente el pago.
        """
        from odoo.exceptions import UserError

        self.ensure_one()

        # Identidad y permiso del usuario autenticado.
        # Comprobar ANTES de cualquier sudo().
        self._check_transfer_authorizer_permission()

        actor_id = self.env.user.id

        transfer = self.sudo()

        # Asegurar que la consulta SQL observe los
        # cambios ORM pendientes de esta transaccion.
        transfer.flush_recordset(
            [
                "state",
                "source_certificate_id",
                "recipient_person_id",
                "payment_evidence_reference",
                "payment_verified_by_id",
                "payment_verified_at",
                "authorized_by_id",
                "authorized_at",
                "executed_at",
                "recipient_certificate_id",
                "cancellation_reason",
                "cancelled_by_id",
                "cancelled_at",
            ]
        )

        # Primer bloqueo: tramite de transferencia.
        # Respeta el orden utilizado por la verificacion.
        self.env.cr.execute(
            """
            SELECT
                state,
                source_certificate_id,
                recipient_person_id,
                payment_evidence_reference,
                payment_verified_by_id,
                payment_verified_at,
                authorized_by_id,
                authorized_at,
                executed_at,
                recipient_certificate_id,
                cancellation_reason,
                cancelled_by_id,
                cancelled_at
            FROM club_certificate_transfer
            WHERE id = %s
            FOR UPDATE
            """,
            (transfer.id,),
        )

        row = self.env.cr.fetchone()

        if not row:
            raise UserError(self.env._("No existe el tramite de transferencia."))

        (
            state,
            source_id,
            recipient_id,
            evidence_reference,
            verifier_id,
            verified_at,
            authorized_by_id,
            authorized_at,
            executed_at,
            recipient_certificate_id,
            cancellation_reason,
            cancelled_by_id,
            cancelled_at,
        ) = row

        if state != "payment_verified":
            raise UserError(
                self.env._(
                    "Solo puede autorizarse una transferencia "
                    "que tenga el pago documental verificado."
                )
            )

        if (
            not isinstance(evidence_reference, str)
            or not evidence_reference.strip()
            or not verifier_id
            or not verified_at
        ):
            raise UserError(
                self.env._(
                    "El tramite no contiene una verificacion "
                    "documental de pago completa."
                )
            )

        # Separacion de funciones incluso cuando
        # el usuario tiene ambos grupos.
        if verifier_id == actor_id:
            raise UserError(
                self.env._(
                    "El funcionario que verifico el pago "
                    "no puede autorizar esa misma "
                    "transferencia patrimonial."
                )
            )

        if (
            authorized_by_id
            or authorized_at
            or executed_at
            or recipient_certificate_id
            or cancellation_reason
            or cancelled_by_id
            or cancelled_at
        ):
            raise UserError(
                self.env._(
                    "El tramite ya tiene informacion de "
                    "autorizacion, cancelacion o ejecucion."
                )
            )

        if not source_id or not recipient_id:
            raise UserError(
                self.env._(
                    "La transferencia requiere Certificado "
                    "original y persona receptora."
                )
            )

        source = self.env["club.certificate"].sudo().browse(source_id)

        source.flush_recordset(["state"])

        # Segundo bloqueo: Certificado original.
        # La autorizacion exige que continue activo.
        self.env.cr.execute(
            """
            SELECT state
            FROM club_certificate
            WHERE id = %s
            FOR UPDATE
            """,
            (source_id,),
        )

        source_row = self.env.cr.fetchone()

        if not source_row or source_row[0] != "active":
            raise UserError(
                self.env._(
                    "El Certificado Patrimonial original "
                    "debe permanecer activo para autorizar "
                    "la transferencia."
                )
            )

        # Evitar autorizar una cesion a otro Socio.
        transfer._check_recipient_not_current_member()
        transfer._check_recipient_not_blocked_beneficiary()
        transfer._check_recipient_has_registered_family_link()

        # Escritura exclusivamente mediante el token
        # interno existente. No se abre acceso CRUD.
        transfer.with_context(
            club_transfer_record_internal_token=(_TRANSFER_RECORD_INTERNAL_TOKEN)
        ).with_context(
            club_transfer_authorization_state_internal_token=(
                _TRANSFER_AUTHORIZATION_STATE_INTERNAL_TOKEN
            )
        ).write(
            {
                "authorized_by_id": actor_id,
                "authorized_at": fields.Datetime.now(),
                "state": "authorized",
            }
        )

        return True

    def _check_internal_transfer_access(self):
        token = self.env.context.get("club_transfer_record_internal_token")
        if token is not _TRANSFER_RECORD_INTERNAL_TOKEN:
            raise AccessError(
                self.env._(
                    "La transferencia patrimonial solo puede "
                    "gestionarse mediante el procedimiento "
                    "institucional autorizado."
                )
            )

    @api.model_create_multi
    def create(self, vals_list):
        self._check_internal_transfer_access()
        if any("executed_by_id" in values for values in vals_list):
            from odoo.exceptions import AccessError

            raise AccessError(
                self.env._(
                    "No se puede registrar manualmente "
                    "la identidad del funcionario ejecutor. "
                    "Se requiere el proceso institucional "
                    "de ejecución patrimonial."
                )
            )

        # Los datos de auditoria del pago se registran
        # exclusivamente mediante la verificacion institucional.
        # El token general no autoriza su preasignacion en create.
        if any(
            field in values
            for values in vals_list
            for field in (
                "payment_evidence_reference",
                "payment_verified_by_id",
                "payment_verified_at",
            )
        ):
            from odoo.exceptions import AccessError

            raise AccessError(
                self.env._(
                    "No pueden preasignarse datos de auditoria "
                    "de verificacion del pago al crear una "
                    "transferencia patrimonial. Utilice el "
                    "procedimiento institucional de verificacion."
                )
            )

        # Una transferencia se crea exclusivamente en draft.
        # La autorizacion y cancelacion se registran solo
        # mediante sus procedimientos institucionales.
        # El token interno general no exime este control.
        if any(
            ("state" in values and values["state"] != "draft")
            or any(
                field in values
                for field in (
                    "authorized_by_id",
                    "authorized_at",
                    "cancelled_by_id",
                    "cancelled_at",
                )
            )
            for values in vals_list
        ):
            from odoo.exceptions import AccessError

            raise AccessError(
                self.env._(
                    "No se puede crear una transferencia "
                    "en un estado distinto de borrador "
                    "ni preasignar los datos de autorizacion "
                    "o cancelacion. Utilice los procedimientos "
                    "institucionales correspondientes."
                )
            )

        return super().create(vals_list)

    def write(self, vals):
        self._check_internal_transfer_access()
        if "executed_by_id" in vals:
            from odoo.exceptions import AccessError

            raise AccessError(
                self.env._(
                    "La identidad del funcionario ejecutor "
                    "está protegida. No puede modificarse "
                    "mediante escritura general del trámite."
                )
            )

        # No permitir sustituir al receptor de una
        # transferencia que ya tiene autorizacion.
        # Bloquear las filas evita carreras con la
        # autorizacion institucional concurrente.
        if "recipient_person_id" in vals and self:
            self.flush_recordset(["state"])
            self.env.cr.execute(
                """
                SELECT state
                  FROM club_certificate_transfer
                 WHERE id = ANY(%s)
                 ORDER BY id
                 FOR UPDATE
                """,
                (list(self.ids),),
            )
            if any(row[0] == "authorized" for row in self.env.cr.fetchall()):
                from odoo.exceptions import AccessError

                raise AccessError(
                    self.env._(
                        "No puede sustituirse el receptor "
                        "de una transferencia autorizada."
                    )
                )

        # El Certificado de origen autorizado no puede
        # sustituirse mediante una escritura general,
        # incluso cuando se utiliza el token interno.
        if "source_certificate_id" in vals and self:
            self.flush_recordset(["state"])
            self.env.cr.execute(
                """
                SELECT state
                  FROM club_certificate_transfer
                 WHERE id = ANY(%s)
                 ORDER BY id
                 FOR UPDATE
                """,
                (list(self.ids),),
            )
            if any(row[0] == "authorized" for row in self.env.cr.fetchall()):
                from odoo.exceptions import AccessError

                raise AccessError(
                    self.env._(
                        "No puede sustituirse el Certificado "
                        "de origen de una transferencia autorizada."
                    )
                )

        # Una autorizacion institucional fija su fecha
        # efectiva. El token interno general no puede
        # utilizarse para modificarla posteriormente.
        if "effective_date" in vals and self:
            self.flush_recordset(["state"])
            self.env.cr.execute(
                """
                SELECT state
                  FROM club_certificate_transfer
                 WHERE id = ANY(%s)
                 ORDER BY id
                 FOR UPDATE
                """,
                (list(self.ids),),
            )
            if any(row[0] == "authorized" for row in self.env.cr.fetchall()):
                from odoo.exceptions import AccessError

                raise AccessError(
                    self.env._(
                        "No puede modificarse la fecha efectiva "
                        "de una transferencia autorizada."
                    )
                )

        # Proteger la identidad historica del autorizador.
        # El token interno general no autoriza alterarla
        # despues de la autorizacion institucional.
        if "authorized_by_id" in vals and self:
            self.flush_recordset(["state"])
            self.env.cr.execute(
                """
                SELECT state
                  FROM club_certificate_transfer
                 WHERE id = ANY(%s)
                 ORDER BY id
                 FOR UPDATE
                """,
                (list(self.ids),),
            )
            if any(row[0] == "authorized" for row in self.env.cr.fetchall()):
                from odoo.exceptions import AccessError

                raise AccessError(
                    self.env._(
                        "No puede modificarse la identidad del "
                        "funcionario que autorizo esta transferencia."
                    )
                )

        # La fecha y hora de autorizacion constituye
        # evidencia historica institucional.
        # El token interno general no permite cambiarla
        # cuando la transferencia ya esta autorizada.
        if "authorized_at" in vals and self:
            self.flush_recordset(["state"])
            self.env.cr.execute(
                """
                SELECT state
                  FROM club_certificate_transfer
                 WHERE id = ANY(%s)
                 ORDER BY id
                 FOR UPDATE
                """,
                (list(self.ids),),
            )
            if any(row[0] == "authorized" for row in self.env.cr.fetchall()):
                from odoo.exceptions import AccessError

                raise AccessError(
                    self.env._(
                        "No puede modificarse la fecha y hora "
                        "de una transferencia autorizada."
                    )
                )

        # El respaldo de pago se registra al verificar desde draft.
        # Despues, la referencia documental es historica e inmutable.
        if "payment_evidence_reference" in vals and self:
            self.flush_recordset(["state"])
            self.env.cr.execute(
                """
                SELECT state
                  FROM club_certificate_transfer
                 WHERE id = ANY(%s)
                 ORDER BY id
                 FOR UPDATE
                """,
                (list(self.ids),),
            )
            if any(row[0] != "draft" for row in self.env.cr.fetchall()):
                from odoo.exceptions import AccessError

                raise AccessError(
                    self.env._(
                        "No puede modificarse la referencia documental "
                        "despues de verificar el pago de la transferencia."
                    )
                )

        # La identidad del verificador se fija al registrar el pago.
        # No se permite modificarla despues de salir de draft.
        if "payment_verified_by_id" in vals and self:
            self.flush_recordset(["state"])
            self.env.cr.execute(
                """
                SELECT state
                  FROM club_certificate_transfer
                 WHERE id = ANY(%s)
                 ORDER BY id
                 FOR UPDATE
                """,
                (list(self.ids),),
            )
            if any(row[0] != "draft" for row in self.env.cr.fetchall()):
                from odoo.exceptions import AccessError

                raise AccessError(
                    self.env._(
                        "No puede modificarse la identidad del "
                        "funcionario que verifico el pago "
                        "despues de registrar su verificacion."
                    )
                )

        # La fecha se fija al registrar la verificacion del pago.
        # No puede alterarse despues de salir de draft.
        if "payment_verified_at" in vals and self:
            self.flush_recordset(["state"])
            self.env.cr.execute(
                """
                SELECT state
                  FROM club_certificate_transfer
                 WHERE id = ANY(%s)
                 ORDER BY id
                 FOR UPDATE
                """,
                (list(self.ids),),
            )
            if any(row[0] != "draft" for row in self.env.cr.fetchall()):
                from odoo.exceptions import AccessError

                raise AccessError(
                    self.env._(
                        "No puede modificarse la fecha y hora "
                        "de verificacion del pago despues "
                        "de registrar su verificacion."
                    )
                )

        # Solo action_cancel_transfer() recibe la capacidad
        # privada para registrar la auditoria de cancelacion.
        # El token interno general no es suficiente.
        if any(field in vals for field in ("cancelled_by_id", "cancelled_at")):
            if (
                self.env.context.get("club_transfer_cancellation_audit_internal_token")
                is not _TRANSFER_CANCELLATION_AUDIT_INTERNAL_TOKEN
            ):
                from odoo.exceptions import AccessError

                raise AccessError(
                    self.env._(
                        "La auditoria de cancelacion solo puede "
                        "registrarse mediante el procedimiento "
                        "institucional de cancelacion."
                    )
                )

        # Cada transicion requiere la capacidad
        # propia de su procedimiento institucional.
        # El token interno general no autoriza state.
        if "state" in vals:
            requested_state = vals["state"]

            if requested_state == "payment_verified":
                allowed_state = (
                    self.env.context.get("club_transfer_payment_state_internal_token")
                    is _TRANSFER_PAYMENT_STATE_INTERNAL_TOKEN
                )

            elif requested_state == "authorized":
                allowed_state = (
                    self.env.context.get(
                        "club_transfer_authorization_state_internal_token"
                    )
                    is _TRANSFER_AUTHORIZATION_STATE_INTERNAL_TOKEN
                )

            elif requested_state == "cancelled":
                allowed_state = (
                    self.env.context.get(
                        "club_transfer_cancellation_audit_internal_token"
                    )
                    is _TRANSFER_CANCELLATION_AUDIT_INTERNAL_TOKEN
                )

            else:
                allowed_state = False

            if not allowed_state:
                from odoo.exceptions import AccessError

                raise AccessError(
                    self.env._(
                        "El estado de la transferencia solo "
                        "puede modificarse mediante su "
                        "procedimiento institucional autorizado."
                    )
                )

        return super().write(vals)

    def unlink(self):
        self._check_internal_transfer_access()
        return super().unlink()
