from odoo import api, fields, models
from odoo.exceptions import ValidationError
from odoo.tools import float_is_zero


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
        related="member_id.club_member_code",
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
        ],
        string="Estado",
        required=True,
        default="active",
        help=(
            "Activo: certificado vigente. "
            "Transferido: certificado transferido a un familiar. "
            "Pasivo: certificado inhabilitado."
        ),
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

        self._log_kardex_event(
            certificate,
            "certificate_state_changed",
            self.env._("Estado del Certificado Patrimonial actualizado."),
            old_value=old_state,
            new_value=new_state,
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

    def write(self, vals):
        vals = dict(vals)

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
