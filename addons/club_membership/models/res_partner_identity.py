from odoo import fields, models
from odoo.exceptions import AccessError, ValidationError


class ResPartnerIdentityCorrection(models.Model):
    _inherit = "res.partner"

    _CLUB_SENSITIVE_IDENTITY_FIELDS = (
        "name",
        "club_id_number",
        "club_id_extension",
        "club_birthdate",
    )

    club_person_audit_event_ids = fields.One2many(
        comodel_name="club.person.audit.event",
        inverse_name="person_id",
        string="Historial de identidad",
        copy=False,
    )

    def _club_identity_is_managed(self):
        self.ensure_one()

        return bool(
            self.club_person_type
            or self.club_id_number
            or self.club_beneficiary_link_ids
        )

    def _prepare_club_sensitive_identity_value(
        self,
        field_name,
        value,
    ):
        self.ensure_one()

        if field_name == "name":
            prepared_value = str(value or "").strip()

            if not prepared_value:
                raise ValidationError(
                    self.env._("El nombre o razón social no puede quedar vacío.")
                )

            return prepared_value

        if field_name == "club_id_number":
            prepared_value = str(value or "")

            if not prepared_value:
                raise ValidationError(
                    self.env._("El número de carnet no puede quedar vacío.")
                )

            self.check_club_id_number_format(prepared_value)

            return prepared_value

        if field_name == "club_id_extension":
            if value is False or value is None:
                return False

            prepared_value = str(value).strip()

            return prepared_value or False

        if field_name == "club_birthdate":
            if self.is_company:
                raise ValidationError(
                    self.env._("La fecha de nacimiento no corresponde a una empresa.")
                )

            if not value:
                raise ValidationError(
                    self.env._("La fecha de nacimiento no puede quedar vacía.")
                )

            try:
                prepared_value = fields.Date.to_date(value)
            except (TypeError, ValueError) as error:
                raise ValidationError(
                    self.env._("La fecha de nacimiento indicada no es válida.")
                ) from error

            if prepared_value > fields.Date.context_today(self):
                raise ValidationError(
                    self.env._(
                        "La fecha de nacimiento no puede ser posterior "
                        "a la fecha actual."
                    )
                )

            return prepared_value

        raise ValidationError(
            self.env._(
                "El dato seleccionado no forma parte de la identidad sensible del Club."
            )
        )

    def _prepare_club_sensitive_identity_vals(self, vals):
        self.ensure_one()

        prepared_vals = dict(vals)
        changed_fields = []

        sensitive_fields = set(vals).intersection(self._CLUB_SENSITIVE_IDENTITY_FIELDS)

        for field_name in sensitive_fields:
            prepared_value = self._prepare_club_sensitive_identity_value(
                field_name,
                vals[field_name],
            )

            prepared_vals[field_name] = prepared_value

            if self[field_name] != prepared_value:
                changed_fields.append(field_name)

        return prepared_vals, changed_fields

    def _check_club_identity_number_available(self, id_number):
        self.ensure_one()

        duplicate = self.search(
            [
                ("club_id_number", "=", id_number),
                ("id", "!=", self.id),
            ],
            limit=1,
        )

        if duplicate:
            raise ValidationError(
                self.env._(
                    "No se puede usar el número de carnet %(number)s "
                    "porque ya pertenece a otra Persona del Club.",
                    number=id_number,
                )
            )

    def _get_club_identity_correction_reason(self):
        return (self.env.context.get("club_identity_correction_reason") or "").strip()

    def _check_club_identity_correction_permission(self):
        if not self.env.user.has_group(
            "club_membership.group_club_identity_correction"
        ):
            raise AccessError(
                self.env._(
                    "No tiene permiso para corregir datos sensibles de identidad."
                )
            )

    def _log_club_identity_correction(
        self,
        field_name,
        old_value,
        reason,
    ):
        self.ensure_one()

        new_value = self[field_name]
        audit_model = self.env["club.person.audit.event"]

        audit_event = audit_model._log_event(  # pylint: disable=protected-access
            self,
            field_name,
            old_value,
            new_value,
            reason,
        )

        if self.club_person_type != "member":
            return audit_event

        field_label = self._fields[field_name].string

        description = self.env._(
            "Corrección de identidad del socio: %(field)s.",
            field=field_label,
        )

        if field_name == "club_id_number":
            description = self.env._(
                "Corrección del número de carnet del socio; "
                "el Código de asociado se actualizó automáticamente."
            )

        self._log_club_kardex_event(
            self,
            "member_identity_corrected",
            description,
            old_value=self.env._(
                "%(field)s: %(value)s",
                field=field_label,
                value=audit_event.old_value,
            ),
            new_value=self.env._(
                "%(field)s: %(value)s",
                field=field_label,
                value=audit_event.new_value,
            ),
            reason=reason,
            person_audit_event=audit_event,
            origin="manual",
        )

        return audit_event

    def _log_club_member_write_changes(
        self,
        partner,
        before_values,
        was_member,
    ):
        if self.env.context.get("club_identity_correction_field"):
            return

        super()._log_club_member_write_changes(
            partner,
            before_values,
            was_member,
        )

    def correct_sensitive_identity(
        self,
        field_name,
        new_value,
        reason,
    ):
        self.ensure_one()

        if not self._club_identity_is_managed():
            raise ValidationError(
                self.env._(
                    "La corrección sensible solo corresponde a una "
                    "Persona ya incorporada al Club."
                )
            )

        if field_name not in self._CLUB_SENSITIVE_IDENTITY_FIELDS:
            raise ValidationError(
                self.env._("El dato seleccionado no admite este proceso de corrección.")
            )

        reason = (reason or "").strip()

        if not reason:
            raise ValidationError(
                self.env._("Debe indicar el motivo de la corrección.")
            )

        return self.with_context(
            club_identity_correction_reason=reason,
        ).write(
            {
                field_name: new_value,
            }
        )

    def write(self, vals):
        vals = dict(vals)

        sensitive_fields = set(vals).intersection(self._CLUB_SENSITIVE_IDENTITY_FIELDS)

        if not sensitive_fields:
            return super().write(vals)

        if len(self) != 1:
            managed_records = self.filtered(
                lambda partner: bool(
                    partner.club_person_type
                    or partner.club_id_number
                    or partner.club_beneficiary_link_ids
                )
            )

            if managed_records:
                raise ValidationError(
                    self.env._(
                        "Las correcciones de identidad deben realizarse "
                        "sobre una Persona a la vez."
                    )
                )

            return super().write(vals)

        if not self._club_identity_is_managed():
            return super().write(vals)

        vals, changed_fields = self._prepare_club_sensitive_identity_vals(vals)

        if not changed_fields:
            if self._get_club_identity_correction_reason():
                raise ValidationError(
                    self.env._("El nuevo valor debe ser diferente del valor actual.")
                )

            return super().write(vals)

        if len(changed_fields) != 1:
            raise ValidationError(
                self.env._("Corrija un solo dato sensible por operación.")
            )

        field_name = changed_fields[0]

        if set(vals) != {field_name}:
            raise ValidationError(
                self.env._(
                    "La corrección de identidad debe realizarse como "
                    "una operación independiente. Guarde primero los "
                    "demás cambios."
                )
            )

        reason = self._get_club_identity_correction_reason()

        if not reason:
            raise ValidationError(
                self.env._(
                    "Los datos sensibles de una Persona del Club no "
                    "pueden modificarse directamente. Use la acción "
                    "Corregir identidad e indique el motivo."
                )
            )

        self._check_club_identity_correction_permission()

        if field_name == "club_id_number":
            self._check_club_identity_number_available(vals[field_name])

        old_value = self[field_name]

        partner_with_context = self.with_context(
            club_identity_correction_field=field_name,
        )

        result = super(
            ResPartnerIdentityCorrection,
            partner_with_context,
        ).write(vals)

        self._log_club_identity_correction(
            field_name,
            old_value,
            reason,
        )

        return result
