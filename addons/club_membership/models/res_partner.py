from odoo import api, fields, models
from odoo.exceptions import AccessError, ValidationError

_CLUB_MEMBER_STATE_INTERNAL_TOKEN = object()


class ResPartner(models.Model):
    # This extension intentionally remains separate from the member
    # registration correction process because that layer must load last.
    _inherit = "res.partner"  # pylint: disable=consider-merging-classes-inherited

    _sql_constraints = [
        (
            "club_id_number_unique",
            "unique(club_id_number)",
            "El número de carnet / identificación debe ser único en el Club.",
        ),
    ]

    _CLUB_KARDEX_PERSONAL_FIELDS = (
        "name",
        "company_type",
        "club_birthdate",
        "club_nationality_id",
        "club_marital_status",
        "club_occupation",
        "club_title",
        "phone",
        "mobile",
        "email",
        "street",
        "street2",
        "city",
        "state_id",
        "zip",
        "country_id",
    )

    _CLUB_KARDEX_IDENTITY_FIELDS = (
        "club_id_number",
        "club_id_extension",
    )

    club_person_type = fields.Selection(
        selection=[
            ("member", "Socio"),
            ("client", "Cliente"),
        ],
        string="Tipo de persona",
    )

    club_id_number = fields.Char(
        string="Número de carnet",
    )

    club_id_extension = fields.Char(
        string="Extensión del carnet",
    )

    club_birthdate = fields.Date(
        string="Fecha de nacimiento",
    )

    club_age = fields.Integer(
        string="Edad",
        compute="_compute_club_age",
    )

    club_nationality_id = fields.Many2one(
        comodel_name="res.country",
        string="Nacionalidad",
    )

    club_marital_status = fields.Selection(
        selection=[
            ("single", "Soltero/a"),
            ("married", "Casado/a"),
            ("divorced", "Divorciado/a"),
            ("widowed", "Viudo/a"),
            ("common_law", "Unión libre"),
        ],
        string="Estado civil",
    )

    club_occupation = fields.Char(
        string="Ocupación / Actividad",
    )

    club_title = fields.Char(
        string="Título profesional",
    )

    club_member_code = fields.Char(
        string="Código de asociado",
        copy=False,
    )

    club_join_date = fields.Date(
        string="Fecha de ingreso",
        copy=False,
    )

    club_seniority = fields.Integer(
        string="Antigüedad",
        compute="_compute_club_seniority",
    )

    club_member_state = fields.Selection(
        selection=[
            ("active", "Activo"),
            ("active_arrears", "Activo en mora"),
            ("lifetime", "Vitalicio"),
            ("absent", "Ausente"),
            ("temporary", "Transitorio"),
            ("inactive", "Pasivo"),
        ],
        string="Estado del asociado",
        copy=False,
    )

    club_legal_state = fields.Selection(
        selection=[
            ("regular", "Regular"),
            ("legal_process", "En proceso legal"),
            ("resolved", "Resuelto"),
        ],
        string="Estado legal",
        copy=False,
    )

    club_beneficiary_ids = fields.One2many(
        comodel_name="club.beneficiary",
        inverse_name="member_id",
        string="Beneficiarios",
        copy=False,
    )

    club_beneficiary_link_ids = fields.One2many(
        comodel_name="club.beneficiary",
        inverse_name="person_id",
        string="Historial como Beneficiario",
        copy=False,
    )

    club_origin_beneficiary_ids = fields.One2many(
        comodel_name="club.beneficiary",
        inverse_name="converted_member_id",
        string="Origen como beneficiario",
        copy=False,
    )

    club_certificate_ids = fields.One2many(
        comodel_name="club.certificate",
        inverse_name="member_id",
        string="Certificado Patrimonial",
        copy=False,
    )

    club_kardex_event_ids = fields.One2many(
        comodel_name="club.kardex.event",
        inverse_name="member_id",
        string="Kardex / Historial",
        copy=False,
    )

    @api.depends(
        "club_birthdate",
        "is_company",
    )
    def _compute_club_age(self):
        today = fields.Date.context_today(self)

        for partner in self:
            if partner.is_company or not partner.club_birthdate:
                partner.club_age = 0
                continue

            birthdate = partner.club_birthdate
            partner.club_age = (
                today.year
                - birthdate.year
                - ((today.month, today.day) < (birthdate.month, birthdate.day))
            )

    @api.depends("club_join_date")
    def _compute_club_seniority(self):
        today = fields.Date.context_today(self)

        for partner in self:
            if not partner.club_join_date:
                partner.club_seniority = 0
                continue

            join_date = partner.club_join_date
            partner.club_seniority = (
                today.year
                - join_date.year
                - ((today.month, today.day) < (join_date.month, join_date.day))
            )

    @api.model
    def check_club_id_number_format(self, id_number):
        if not id_number:
            return

        if not id_number.isascii() or not id_number.isdigit():
            raise ValidationError(
                self.env._("El número de carnet debe contener únicamente números.")
            )

        if id_number.startswith("0"):
            raise ValidationError(
                self.env._("El número de carnet no puede comenzar con cero.")
            )

    @api.constrains(
        "club_person_type",
        "club_id_number",
        "club_birthdate",
        "is_company",
    )
    def _check_club_personal_data(self):
        today = fields.Date.context_today(self)

        for partner in self:
            if partner.club_id_number:
                self.check_club_id_number_format(partner.club_id_number)

            if partner.club_person_type not in (
                "member",
                "client",
            ):
                continue

            if not partner.club_id_number:
                raise ValidationError(
                    self.env._(
                        "El número de carnet es obligatorio para socios y clientes."
                    )
                )

            if not partner.is_company:
                if not partner.club_birthdate:
                    raise ValidationError(
                        self.env._(
                            "La fecha de nacimiento es obligatoria "
                            "para socios y clientes que sean "
                            "personas individuales."
                        )
                    )

                if partner.club_birthdate > today:
                    raise ValidationError(
                        self.env._(
                            "La fecha de nacimiento no puede ser "
                            "posterior a la fecha actual."
                        )
                    )

    @api.constrains(
        "club_person_type",
        "club_member_state",
    )
    def _check_club_beneficiary_role_compatibility(self):
        conversion_beneficiary_id = self.env.context.get(
            "club_conversion_beneficiary_id"
        )

        for partner in self:
            domain = [
                ("person_id", "=", partner.id),
                ("state", "in", ("active", "blocked")),
            ]

            if conversion_beneficiary_id:
                domain.append(("id", "!=", conversion_beneficiary_id))

            current_link = self.env["club.beneficiary"].search(
                domain,
                limit=1,
            )

            if not current_link:
                continue

            if partner.club_person_type == "client":
                raise ValidationError(
                    self.env._(
                        "Una persona con un vínculo vigente como "
                        "Beneficiario no puede ser Cliente."
                    )
                )

            if (
                partner.club_person_type == "member"
                and partner.club_member_state != "inactive"
            ):
                raise ValidationError(
                    self.env._(
                        "Un Socio con un vínculo vigente como "
                        "Beneficiario debe permanecer Pasivo. "
                        "Finalice primero el vínculo de Beneficiario "
                        "antes de reactivar al Socio."
                    )
                )

    def _check_club_member_withdrawal_permission(self):
        if not self.env.user.has_group("club_membership.group_club_member_withdrawal"):
            raise AccessError(
                self.env._("No tiene permiso para retirar o dar de baja a un Socio.")
            )

    def _is_club_member_state_internal_write(self):
        return (
            self.env.context.get("club_member_state_internal_token")
            is _CLUB_MEMBER_STATE_INTERNAL_TOKEN
        )

    def _write_club_member_values_internal(
        self,
        vals,
        *,
        reason=False,
        origin="manual",
        effective_date=False,
    ):
        context_values = {
            "club_member_state_internal_token": (_CLUB_MEMBER_STATE_INTERNAL_TOKEN),
            "club_member_state_change_reason": reason or False,
            "club_member_state_change_origin": origin,
            "club_member_state_change_effective_date": (
                fields.Date.to_string(effective_date) if effective_date else False
            ),
        }

        return self.with_context(**context_values).write(vals)

    def _write_club_member_state_internal(
        self,
        new_state,
        *,
        reason=False,
        origin="manual",
        effective_date=False,
    ):
        self.ensure_one()

        return self._write_club_member_values_internal(
            {
                "club_member_state": new_state,
            },
            reason=reason,
            origin=origin,
            effective_date=effective_date,
        )

    def action_open_club_member_withdrawal_wizard(self):
        self.ensure_one()
        self._check_club_member_withdrawal_permission()

        if self.club_person_type != "member":
            raise ValidationError(
                self.env._("La acción de retiro solo puede aplicarse a un Socio.")
            )

        if self.club_member_state == "inactive":
            raise ValidationError(
                self.env._("El Socio ya se encuentra en estado Pasivo.")
            )

        return {
            "type": "ir.actions.act_window",
            "name": self.env._("Retirar / dar de baja Socio"),
            "res_model": "club.member.withdrawal.wizard",
            "view_mode": "form",
            "views": [
                (
                    self.env.ref(
                        "club_membership.view_club_member_withdrawal_wizard_form"
                    ).id,
                    "form",
                )
            ],
            "target": "new",
            "context": {
                "default_member_id": self.id,
            },
        }

    def action_withdraw_club_member(
        self,
        reason,
        effective_date=False,
    ):
        self.ensure_one()
        self._check_club_member_withdrawal_permission()

        if self.club_person_type != "member":
            raise ValidationError(
                self.env._("La acción de retiro solo puede aplicarse a un Socio.")
            )

        if self.club_member_state == "inactive":
            raise ValidationError(
                self.env._("El Socio ya se encuentra en estado Pasivo.")
            )

        normalized_reason = (reason or "").strip()
        if not normalized_reason:
            raise ValidationError(
                self.env._("Debe indicar el motivo del retiro del Socio.")
            )

        today = fields.Date.context_today(self)
        withdrawal_date = (
            fields.Date.to_date(effective_date) if effective_date else today
        )

        if withdrawal_date > today:
            raise ValidationError(
                self.env._("La fecha efectiva del retiro no puede ser futura.")
            )

        if self.club_join_date and withdrawal_date < self.club_join_date:
            raise ValidationError(
                self.env._(
                    "La fecha efectiva del retiro no puede ser "
                    "anterior a la fecha de ingreso del Socio."
                )
            )

        active_beneficiaries = self.club_beneficiary_ids.filtered(
            lambda beneficiary: beneficiary.state == "active"
        )

        if active_beneficiaries:
            active_beneficiaries._write_member_withdrawal_values_internal(  # pylint: disable=protected-access
                {
                    "state": "blocked",
                    "block_reason": self.env._(
                        "Socio titular retirado del Club con fecha "
                        "efectiva %(date)s. Motivo: %(reason)s",
                        date=fields.Date.to_string(withdrawal_date),
                        reason=normalized_reason,
                    ),
                    "blocked_by_member_withdrawal": True,
                }
            )

        certificate = self.club_certificate_ids[:1]

        if certificate and certificate.state == "active":
            certificate._write_member_withdrawal_values_internal(  # pylint: disable=protected-access
                {
                    "state": "passive",
                    "passive_by_member_withdrawal": True,
                },
                reason=self.env._(
                    "Retiro del Socio titular. Motivo: %(reason)s",
                    reason=normalized_reason,
                ),
            )

        kardex_reason = self.env._(
            "Fecha efectiva: %(date)s\nMotivo: %(reason)s",
            date=fields.Date.to_string(withdrawal_date),
            reason=normalized_reason,
        )

        self._write_club_member_values_internal(
            {
                "club_member_state": "inactive",
                "club_state_before_withdrawal": self.club_member_state,
                "club_last_withdrawal_date": withdrawal_date,
            },
            reason=kardex_reason,
            origin="manual",
            effective_date=withdrawal_date,
        )

        return True

    def _build_club_member_code(self, id_number):
        if not id_number:
            return False

        return id_number

    def _check_club_member_code_available(
        self,
        member_code,
        exclude_partner=None,
    ):
        if not member_code:
            return

        domain = [
            ("club_member_code", "=", member_code),
        ]

        if exclude_partner:
            domain.append(("id", "!=", exclude_partner.id))

        if self.search(domain, limit=1):
            raise ValidationError(
                self.env._(
                    "No se puede usar el código de asociado "
                    "%(code)s porque ya pertenece a otro socio.",
                    code=member_code,
                )
            )

    def _apply_club_member_defaults(
        self,
        vals,
        partner=None,
    ):
        join_date = partner.club_join_date if partner else False

        member_state = partner.club_member_state if partner else False

        legal_state = partner.club_legal_state if partner else False

        if not vals.get("club_join_date") and not join_date:
            vals["club_join_date"] = fields.Date.context_today(self)

        if not vals.get("club_member_state") and not member_state:
            vals["club_member_state"] = "active"

        if not vals.get("club_legal_state") and not legal_state:
            vals["club_legal_state"] = "regular"

    def _prepare_club_member_write_vals(
        self,
        partner,
        vals,
    ):
        partner_vals = dict(vals)

        new_person_type = partner_vals.get(
            "club_person_type",
            partner.club_person_type,
        )

        if partner.club_person_type == "member" and new_person_type != "member":
            raise ValidationError(
                self.env._(
                    "Un socio no puede convertirse en cliente "
                    "ni dejar de ser socio. Si deja de pertenecer "
                    "al Club, debe cambiar su estado del asociado "
                    "a Pasivo."
                )
            )

        if new_person_type != "member":
            partner_vals["club_member_code"] = False
            return partner_vals

        if partner.club_person_type != "member":
            self._apply_club_member_defaults(
                partner_vals,
                partner=partner,
            )

        new_id_number = partner_vals.get(
            "club_id_number",
            partner.club_id_number,
        )

        member_code = self._build_club_member_code(new_id_number)

        self._check_club_member_code_available(
            member_code,
            exclude_partner=partner,
        )

        partner_vals["club_member_code"] = member_code

        return partner_vals

    def _prepare_club_member_create_vals(
        self,
        original_vals,
        batch_member_codes,
    ):
        vals = dict(original_vals)

        person_type = vals.get("club_person_type") or self.env.context.get(
            "default_club_person_type"
        )

        if person_type:
            vals["club_person_type"] = person_type

        if person_type != "member":
            vals["club_member_code"] = False
            return vals

        self._apply_club_member_defaults(vals)

        id_number = vals.get("club_id_number")

        if not id_number:
            return vals

        member_code = self._build_club_member_code(id_number)

        code_exists = self.search(
            [
                (
                    "club_member_code",
                    "=",
                    member_code,
                ),
            ],
            limit=1,
        )

        if code_exists or member_code in batch_member_codes:
            raise ValidationError(
                self.env._(
                    "No se puede generar el código de asociado "
                    "porque ya existe otro socio con el código "
                    "%(code)s.",
                    code=member_code,
                )
            )

        vals["club_member_code"] = member_code
        batch_member_codes.add(member_code)

        return vals

    def _format_club_kardex_value(
        self,
        partner,
        field_name,
    ):
        field = partner._fields[field_name]
        value = partner[field_name]

        if not value:
            return self.env._("Sin valor")

        if field.type == "many2one":
            return value.display_name

        if field.type == "selection":
            field_description = partner.fields_get([field_name])[field_name]

            selection = dict(
                field_description.get(
                    "selection",
                    [],
                )
            )

            return selection.get(
                value,
                value,
            )

        if field.type == "date":
            return fields.Date.to_string(value)

        return str(value)

    def _get_club_kardex_snapshot(
        self,
        partner,
    ):
        field_names = (
            *self._CLUB_KARDEX_PERSONAL_FIELDS,
            *self._CLUB_KARDEX_IDENTITY_FIELDS,
            "club_member_code",
            "club_join_date",
            "club_member_state",
        )

        return {
            field_name: self._format_club_kardex_value(
                partner,
                field_name,
            )
            for field_name in field_names
        }

    def _build_club_kardex_change_values(
        self,
        partner,
        before_values,
        field_names,
    ):
        old_lines = []
        new_lines = []

        for field_name in field_names:
            old_value = before_values[field_name]

            new_value = self._format_club_kardex_value(
                partner,
                field_name,
            )

            if old_value == new_value:
                continue

            field_label = partner._fields[field_name].string

            old_lines.append(f"{field_label}: {old_value}")

            new_lines.append(f"{field_label}: {new_value}")

        return (
            "\n".join(old_lines),
            "\n".join(new_lines),
        )

    def _log_club_kardex_event(
        self,
        member,
        event_type,
        description,
        **event_data,
    ):
        Kardex = self.env["club.kardex.event"]

        return Kardex._log_event(  # pylint: disable=protected-access
            member,
            event_type,
            description,
            **event_data,
        )

    def _log_club_member_created(
        self,
        partner,
    ):
        conversion_beneficiary_id = self.env.context.get(
            "club_conversion_beneficiary_id"
        )

        if conversion_beneficiary_id:
            beneficiary = (
                self.env["club.beneficiary"].browse(conversion_beneficiary_id).exists()
            )

            if beneficiary:
                self._log_club_kardex_event(
                    partner,
                    "member_created_from_beneficiary",
                    self.env._(
                        "Alta como socio proveniente de beneficiario de %(member)s.",
                        member=(beneficiary.member_id.display_name),
                    ),
                    new_value=self.env._(
                        "Código de asociado: %(code)s",
                        code=partner.club_member_code,
                    ),
                    beneficiary=beneficiary,
                    origin="manual",
                )
                return

        self._log_club_kardex_event(
            partner,
            "member_created",
            self.env._("Socio registrado."),
            new_value=self.env._(
                "Código de asociado: %(code)s",
                code=partner.club_member_code,
            ),
            origin="manual",
        )

    def _log_club_member_write_changes(
        self,
        partner,
        before_values,
        was_member,
    ):
        if not was_member and partner.club_person_type == "member":
            self._log_club_member_created(partner)
            return

        if not was_member:
            return

        old_value, new_value = self._build_club_kardex_change_values(
            partner,
            before_values,
            self._CLUB_KARDEX_PERSONAL_FIELDS,
        )

        if old_value or new_value:
            self._log_club_kardex_event(
                partner,
                "member_personal_data_updated",
                self.env._("Datos personales del socio actualizados."),
                old_value=old_value,
                new_value=new_value,
                origin="manual",
            )

        old_value, new_value = self._build_club_kardex_change_values(
            partner,
            before_values,
            self._CLUB_KARDEX_IDENTITY_FIELDS,
        )

        if old_value or new_value:
            self._log_club_kardex_event(
                partner,
                "member_identity_updated",
                self.env._("Identificación del socio actualizada."),
                old_value=old_value,
                new_value=new_value,
                origin="manual",
            )

        old_code = before_values["club_member_code"]

        new_code = self._format_club_kardex_value(
            partner,
            "club_member_code",
        )

        if old_code != new_code:
            self._log_club_kardex_event(
                partner,
                "member_code_changed",
                self.env._("Código de asociado actualizado."),
                old_value=old_code,
                new_value=new_code,
                origin="automatic",
            )

        old_join_date = before_values["club_join_date"]

        new_join_date = self._format_club_kardex_value(
            partner,
            "club_join_date",
        )

        if old_join_date != new_join_date:
            self._log_club_kardex_event(
                partner,
                "member_join_date_changed",
                self.env._("Fecha de ingreso del socio actualizada."),
                old_value=old_join_date,
                new_value=new_join_date,
                origin="manual",
            )

        old_member_state = before_values["club_member_state"]

        new_member_state = self._format_club_kardex_value(
            partner,
            "club_member_state",
        )

        if old_member_state != new_member_state:
            effective_date = self.env.context.get(
                "club_member_state_change_effective_date"
            )

            description = self.env._("Estado del asociado actualizado.")

            if partner.club_member_state == "inactive" and effective_date:
                description = self.env._(
                    "Socio retirado del Club con fecha efectiva %(date)s.",
                    date=effective_date,
                )

            self._log_club_kardex_event(
                partner,
                "member_state_changed",
                description,
                old_value=old_member_state,
                new_value=new_member_state,
                reason=(
                    self.env.context.get("club_member_state_change_reason") or False
                ),
                origin=(
                    self.env.context.get("club_member_state_change_origin") or "manual"
                ),
            )

    @api.model_create_multi
    def create(self, vals_list):
        batch_member_codes = set()

        prepared_vals_list = [
            self._prepare_club_member_create_vals(
                original_vals,
                batch_member_codes,
            )
            for original_vals in vals_list
        ]

        partners = super().create(prepared_vals_list)

        for partner in partners:
            if partner.club_person_type == "member":
                self._log_club_member_created(partner)

        return partners

    def write(self, vals):
        vals = dict(vals)
        vals.pop(
            "club_member_code",
            None,
        )

        if not vals:
            return True

        internal_member_state_write = self._is_club_member_state_internal_write()

        if "club_member_state" in vals and not internal_member_state_write:
            requested_member_state = vals.get("club_member_state")

            for partner in self:
                if partner.club_person_type != "member":
                    continue

                if (
                    requested_member_state == "inactive"
                    and partner.club_member_state != "inactive"
                ):
                    raise ValidationError(
                        self.env._(
                            "Para pasar un Socio a Pasivo debe utilizar "
                            "la acción controlada Retirar / dar de baja Socio."
                        )
                    )

                if (
                    partner.club_member_state == "inactive"
                    and requested_member_state != "inactive"
                ):
                    raise ValidationError(
                        self.env._(
                            "Un Socio Pasivo no puede reactivarse "
                            "mediante edición directa. La reactivación "
                            "requiere un proceso controlado específico."
                        )
                    )

        code_fields = {
            "club_person_type",
            "club_id_number",
        }

        tracked_fields = {
            *self._CLUB_KARDEX_PERSONAL_FIELDS,
            *self._CLUB_KARDEX_IDENTITY_FIELDS,
            "club_person_type",
            "club_join_date",
            "club_member_state",
        }

        if not (code_fields | tracked_fields).intersection(vals):
            return super().write(vals)

        for partner in self:
            was_member = partner.club_person_type == "member"

            new_person_type = vals.get(
                "club_person_type",
                partner.club_person_type,
            )

            before_values = False

            if was_member or new_person_type == "member":
                before_values = self._get_club_kardex_snapshot(partner)

            partner_vals = dict(vals)

            if code_fields.intersection(vals):
                partner_vals = self._prepare_club_member_write_vals(
                    partner,
                    vals,
                )

            super(
                ResPartner,
                partner,
            ).write(partner_vals)

            if before_values:
                self._log_club_member_write_changes(
                    partner,
                    before_values,
                    was_member,
                )

        return True
