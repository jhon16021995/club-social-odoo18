from odoo import api, fields, models
from odoo.exceptions import AccessError, ValidationError
from odoo.tools import float_is_zero

_REGISTRATION_ERROR_VOID_TOKEN = object()
_CERTIFICATE_MEMBER_WITHDRAWAL_INTERNAL_TOKEN = object()


class ClubCertificate(models.Model):
    _name = "club.certificate"
    _description = "Certificado Patrimonial"
    _order = "issue_date desc, id desc"
    _rec_name = "certificate_number"

    _KARDEX_TRACKED_FIELDS = (
        "total_value",
        "opening_balance",
        "opening_paid_amount",
        "certificate_type",
        "issue_date",
        "observations",
    )

    member_id = fields.Many2one(
        comodel_name="res.partner",
        string="Socio titular",
        required=True,
        index=True,
        ondelete="restrict",
        domain=[("club_person_type", "=", "member")],
    )

    certificate_number = fields.Char(
        string="Número de certificado",
        related="member_id.club_id_number",
        store=True,
        readonly=True,
    )

    registration_origin = fields.Selection(
        selection=[
            ("new", "Nuevo"),
            ("migrated", "Migrado"),
        ],
        string="Origen del registro",
        required=True,
        default="new",
        copy=False,
        help=(
            "Nuevo: certificado emitido dentro del nuevo sistema. "
            "Migrado: certificado que ya existía antes de la puesta "
            "en marcha del sistema."
        ),
    )

    total_value = fields.Float(
        string="Valor total (Bs)",
        required=True,
        digits=(16, 2),
    )

    opening_balance = fields.Float(
        string="Saldo inicial (Bs)",
        required=True,
        digits=(16, 2),
        help=(
            "Saldo con el que el certificado inicia en este sistema. "
            "Para certificados nuevos coincide con el valor total. "
            "Para certificados migrados corresponde a la deuda "
            "pendiente al momento de la migración."
        ),
    )

    opening_paid_amount = fields.Float(
        string="Pagado antes del sistema (Bs)",
        compute="_compute_opening_paid_amount",
        store=True,
        readonly=True,
        digits=(16, 2),
    )

    certificate_type = fields.Selection(
        selection=[
            ("subscribed", "Suscrito"),
            ("paid", "Pagado"),
        ],
        string="Tipo",
        compute="_compute_certificate_type",
        store=True,
        readonly=True,
    )

    state = fields.Selection(
        selection=[
            ("active", "Activo"),
            ("transferred", "Transferido"),
            ("passive", "Pasivo"),
            (
                "registration_error_void",
                "Anulado por alta errónea",
            ),
        ],
        string="Estado",
        required=True,
        default="active",
        help=(
            "Activo: certificado vigente. "
            "Transferido: certificado transferido a un familiar. "
            "Pasivo: certificado inhabilitado. "
            "Anulado por alta errónea: certificado conservado "
            "históricamente porque la Persona fue registrada "
            "incorrectamente como Socio."
        ),
    )

    passive_by_member_withdrawal = fields.Boolean(
        string="Pasivo por retiro del Socio titular",
        readonly=True,
        copy=False,
        index=True,
    )

    registration_error_reason = fields.Text(
        string="Motivo de anulación por alta errónea",
        readonly=True,
        copy=False,
    )

    registration_error_at = fields.Datetime(
        string="Fecha de anulación por alta errónea",
        readonly=True,
        copy=False,
    )

    registration_error_user_id = fields.Many2one(
        comodel_name="res.users",
        string="Usuario que anuló por alta errónea",
        readonly=True,
        copy=False,
        ondelete="restrict",
    )

    issue_date = fields.Date(
        string="Fecha de emisión",
        required=True,
        default=fields.Date.context_today,
    )

    observations = fields.Text(
        string="Observaciones",
    )

    _sql_constraints = [
        (
            "club_certificate_member_unique",
            "unique(member_id)",
            "Cada socio puede tener un solo Certificado Patrimonial.",
        ),
    ]

    @api.onchange("registration_origin", "total_value")
    def _onchange_registration_origin_total_value(self):
        for certificate in self:
            if certificate.registration_origin == "new":
                certificate.opening_balance = certificate.total_value

    @api.depends("total_value", "opening_balance")
    def _compute_opening_paid_amount(self):
        for certificate in self:
            certificate.opening_paid_amount = max(
                certificate.total_value - certificate.opening_balance,
                0.0,
            )

    @api.depends("opening_balance")
    def _compute_certificate_type(self):
        for certificate in self:
            if float_is_zero(
                certificate.opening_balance,
                precision_digits=2,
            ):
                certificate.certificate_type = "paid"
            else:
                certificate.certificate_type = "subscribed"

    def _format_kardex_value(self, certificate, field_name):
        field = certificate._fields[field_name]
        value = certificate[field_name]

        if field.type == "float":
            return f"{value:.2f}"

        if not value:
            return self.env._("Sin valor")

        if field.type == "many2one":
            return value.display_name

        if field.type == "selection":
            field_description = certificate.fields_get([field_name])[field_name]

            selection = dict(field_description.get("selection", []))

            return selection.get(value, value)

        if field.type == "date":
            return fields.Date.to_string(value)

        return str(value)

    def _get_kardex_snapshot(self, certificate):
        field_names = (
            *self._KARDEX_TRACKED_FIELDS,
            "state",
        )

        return {
            field_name: self._format_kardex_value(
                certificate,
                field_name,
            )
            for field_name in field_names
        }

    def _build_kardex_change_values(
        self,
        certificate,
        before_values,
        field_names,
    ):
        old_lines = []
        new_lines = []

        for field_name in field_names:
            old_value = before_values[field_name]
            new_value = self._format_kardex_value(
                certificate,
                field_name,
            )

            if old_value == new_value:
                continue

            field_label = certificate._fields[field_name].string

            old_lines.append(f"{field_label}: {old_value}")
            new_lines.append(f"{field_label}: {new_value}")

        return "\n".join(old_lines), "\n".join(new_lines)

    def _log_kardex_event(
        self,
        certificate,
        event_type,
        description,
        **event_data,
    ):
        Kardex = self.env["club.kardex.event"]

        return Kardex._log_event(  # pylint: disable=protected-access
            certificate.member_id,
            event_type,
            description,
            certificate=certificate,
            **event_data,
        )

    def _log_certificate_created(self, certificate):
        description = (
            self.env._("Certificado Patrimonial migrado registrado.")
            if certificate.registration_origin == "migrated"
            else self.env._("Certificado Patrimonial registrado.")
        )

        new_value = "\n".join(
            [
                self.env._(
                    "Número: %(value)s",
                    value=certificate.certificate_number,
                ),
                self.env._(
                    "Origen: %(value)s",
                    value=self._format_kardex_value(
                        certificate,
                        "registration_origin",
                    ),
                ),
                self.env._(
                    "Tipo: %(value)s",
                    value=self._format_kardex_value(
                        certificate,
                        "certificate_type",
                    ),
                ),
                self.env._(
                    "Estado: %(value)s",
                    value=self._format_kardex_value(
                        certificate,
                        "state",
                    ),
                ),
                self.env._(
                    "Valor total (Bs): %(value)s",
                    value=self._format_kardex_value(
                        certificate,
                        "total_value",
                    ),
                ),
                self.env._(
                    "Saldo inicial (Bs): %(value)s",
                    value=self._format_kardex_value(
                        certificate,
                        "opening_balance",
                    ),
                ),
                self.env._(
                    "Pagado antes del sistema (Bs): %(value)s",
                    value=self._format_kardex_value(
                        certificate,
                        "opening_paid_amount",
                    ),
                ),
                self.env._(
                    "Fecha de emisión: %(value)s",
                    value=self._format_kardex_value(
                        certificate,
                        "issue_date",
                    ),
                ),
            ]
        )

        self._log_kardex_event(
            certificate,
            "certificate_created",
            description,
            new_value=new_value,
            origin="manual",
        )

    def _log_certificate_updated(
        self,
        certificate,
        before_values,
    ):
        old_value, new_value = self._build_kardex_change_values(
            certificate,
            before_values,
            self._KARDEX_TRACKED_FIELDS,
        )

        if not old_value and not new_value:
            return

        self._log_kardex_event(
            certificate,
            "certificate_updated",
            self.env._("Certificado Patrimonial actualizado."),
            old_value=old_value,
            new_value=new_value,
            origin="manual",
        )

    def _log_certificate_state_change(
        self,
        certificate,
        before_values,
    ):
        old_state = before_values["state"]
        new_state = self._format_kardex_value(
            certificate,
            "state",
        )

        if old_state == new_state:
            return

        registration_error_void = certificate.state == "registration_error_void"

        state_change_reason = self.env.context.get(
            "club_certificate_state_change_reason"
        )

        description = (
            self.env._("Certificado Patrimonial anulado por alta errónea.")
            if registration_error_void
            else self.env._("Estado del Certificado Patrimonial actualizado.")
        )

        self._log_kardex_event(
            certificate,
            "certificate_state_changed",
            description,
            old_value=old_state,
            new_value=new_state,
            reason=(
                certificate.registration_error_reason
                if registration_error_void
                else (state_change_reason or False)
            ),
            origin="manual",
        )

    @api.model_create_multi
    def create(self, vals_list):
        prepared_vals_list = []

        for original_vals in vals_list:
            vals = dict(original_vals)

            if vals.get("registration_origin", "new") == "new":
                vals["opening_balance"] = vals.get(
                    "total_value",
                    0.0,
                )

            prepared_vals_list.append(vals)

        certificates = super().create(prepared_vals_list)

        for certificate in certificates:
            self._log_certificate_created(certificate)

        return certificates

    def _action_void_registration_error(self, reason):
        self.ensure_one()

        if not self.env.user.has_group(
            "club_membership.group_club_member_registration_correction"
        ):
            raise AccessError(
                self.env._(
                    "No tiene permiso para anular un Certificado "
                    "por alta errónea de Socio."
                )
            )

        normalized_reason = (reason or "").strip()

        if not normalized_reason:
            raise ValidationError(
                self.env._("Debe indicar el motivo de la anulación por alta errónea.")
            )

        if self.state == "registration_error_void":
            raise ValidationError(
                self.env._("Este Certificado ya fue anulado por alta errónea.")
            )

        if self.member_id.club_person_type != "member":
            raise ValidationError(
                self.env._(
                    "La anulación por alta errónea debe realizarse "
                    "mientras la Persona todavía conserva "
                    "la condición de Socio."
                )
            )

        self.with_context(
            club_certificate_registration_error_void_token=(
                _REGISTRATION_ERROR_VOID_TOKEN
            )
        ).write(
            {
                "state": "registration_error_void",
                "registration_error_reason": normalized_reason,
                "registration_error_at": fields.Datetime.now(),
                "registration_error_user_id": self.env.user.id,
            }
        )

        return True

    def _write_member_withdrawal_values_internal(
        self,
        vals,
        *,
        reason=False,
    ):
        return self.with_context(
            club_certificate_member_withdrawal_internal_token=(
                _CERTIFICATE_MEMBER_WITHDRAWAL_INTERNAL_TOKEN
            ),
            club_certificate_state_change_reason=reason or False,
        ).write(vals)

    def _check_member_withdrawal_write(
        self,
        vals,
        *,
        internal_member_withdrawal_write,
        internal_registration_error_void,
    ):
        if (
            "passive_by_member_withdrawal" in vals
            and not internal_member_withdrawal_write
        ):
            raise AccessError(
                self.env._(
                    "La marca técnica de Certificado Pasivo por retiro "
                    "solo puede modificarse mediante un proceso "
                    "controlado del sistema."
                )
            )

        protected_state_change = (
            "state" in vals
            and vals.get("state") != "passive"
            and not internal_member_withdrawal_write
            and not internal_registration_error_void
        )

        if protected_state_change and self.filtered("passive_by_member_withdrawal"):
            raise ValidationError(
                self.env._(
                    "Un Certificado que quedó Pasivo por retiro del Socio "
                    "no puede reactivarse o cambiar de estado directamente. "
                    "Debe utilizarse el proceso controlado de reactivación "
                    "del Socio."
                )
            )

    def write(self, vals):
        vals = dict(vals)

        internal_member_withdrawal_write = (
            self.env.context.get("club_certificate_member_withdrawal_internal_token")
            is _CERTIFICATE_MEMBER_WITHDRAWAL_INTERNAL_TOKEN
        )

        internal_registration_error_void = (
            self.env.context.get("club_certificate_registration_error_void_token")
            is _REGISTRATION_ERROR_VOID_TOKEN
        )

        protected_registration_error_fields = {
            "registration_error_reason",
            "registration_error_at",
            "registration_error_user_id",
        }

        self._check_member_withdrawal_write(
            vals,
            internal_member_withdrawal_write=internal_member_withdrawal_write,
            internal_registration_error_void=internal_registration_error_void,
        )

        if (
            protected_registration_error_fields.intersection(vals)
            and not internal_registration_error_void
        ):
            raise AccessError(
                self.env._(
                    "Los datos de anulación por alta errónea "
                    "solo pueden ser modificados por el proceso "
                    "autorizado del sistema."
                )
            )

        if (
            vals.get("state") == "registration_error_void"
            and not internal_registration_error_void
        ):
            raise AccessError(
                self.env._(
                    "El estado Anulado por alta errónea "
                    "solo puede establecerse mediante "
                    "el proceso de corrección autorizado."
                )
            )

        for certificate in self:
            if certificate.state == "registration_error_void":
                raise ValidationError(
                    self.env._(
                        "Un Certificado anulado por alta errónea "
                        "es histórico y no puede modificarse."
                    )
                )

        if "member_id" in vals:
            for certificate in self:
                if vals["member_id"] != certificate.member_id.id:
                    raise ValidationError(
                        self.env._(
                            "El socio titular del Certificado Patrimonial "
                            "no puede modificarse después de registrarlo."
                        )
                    )

        if "registration_origin" in vals:
            for certificate in self:
                if (
                    certificate.registration_origin
                    and vals["registration_origin"] != certificate.registration_origin
                ):
                    raise ValidationError(
                        self.env._(
                            "El origen del Certificado Patrimonial "
                            "no puede cambiarse después de registrarlo."
                        )
                    )

        for certificate in self:
            before_values = self._get_kardex_snapshot(certificate)

            certificate_vals = dict(vals)

            if (
                certificate.registration_origin == "new"
                and "total_value" in certificate_vals
            ):
                certificate_vals["opening_balance"] = certificate_vals["total_value"]

            super(ClubCertificate, certificate).write(certificate_vals)

            self._log_certificate_updated(
                certificate,
                before_values,
            )

            self._log_certificate_state_change(
                certificate,
                before_values,
            )

        return True

    @api.constrains("member_id")
    def _check_member(self):
        for certificate in self:
            if certificate.member_id.club_person_type != "member":
                raise ValidationError(
                    self.env._(
                        "El Certificado Patrimonial solo puede pertenecer a un socio."
                    )
                )

            if not certificate.member_id.club_member_code:
                raise ValidationError(
                    self.env._(
                        "El socio debe tener un código de asociado antes "
                        "de registrar su Certificado Patrimonial."
                    )
                )

    @api.constrains("total_value")
    def _check_total_value(self):
        for certificate in self:
            if certificate.total_value <= 0:
                raise ValidationError(
                    self.env._(
                        "El valor total del Certificado Patrimonial "
                        "debe ser mayor que cero."
                    )
                )

    @api.constrains(
        "registration_origin",
        "total_value",
        "opening_balance",
    )
    def _check_opening_balance(self):
        for certificate in self:
            if certificate.opening_balance < 0:
                raise ValidationError(
                    self.env._(
                        "El saldo inicial del Certificado Patrimonial "
                        "no puede ser negativo."
                    )
                )

            if certificate.opening_balance > certificate.total_value:
                raise ValidationError(
                    self.env._(
                        "El saldo inicial no puede ser mayor que "
                        "el valor total del Certificado Patrimonial."
                    )
                )

            if certificate.registration_origin == "new" and not float_is_zero(
                certificate.opening_balance - certificate.total_value,
                precision_digits=2,
            ):
                raise ValidationError(
                    self.env._(
                        "Un Certificado Patrimonial nuevo debe iniciar "
                        "con un saldo igual a su valor total."
                    )
                )

    @api.ondelete(at_uninstall=False)
    def _unlink_except_module_uninstall(self):
        raise ValidationError(
            self.env._(
                "El Certificado Patrimonial es un registro histórico "
                "y no puede eliminarse."
            )
        )
