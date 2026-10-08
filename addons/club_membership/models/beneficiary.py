from odoo import api, fields, models
from odoo.exceptions import AccessError, ValidationError

_CLUB_BENEFICIARY_WITHDRAWAL_INTERNAL_TOKEN = object()
_CLUB_BENEFICIARY_TRANSITION_INTERNAL_TOKEN = object()


class ClubBeneficiary(models.Model):
    _name = "club.beneficiary"
    _description = "Vínculo de Beneficiario del Club"
    _order = "member_id, person_id"

    _AGE_LIMITED_RELATIONSHIPS = {
        "child",
        "stepchild",
        "family_dependent",
    }

    _AGE_EXEMPT_SPECIAL_CONDITIONS = {
        "health_dependent",
    }

    _KARDEX_TRACKED_FIELDS = (
        "relationship",
        "relationship_detail",
        "special_condition",
        "start_date",
        "observations",
    )

    person_id = fields.Many2one(
        comodel_name="res.partner",
        string="Persona beneficiaria",
        required=True,
        ondelete="restrict",
        index=True,
        domain=[("is_company", "=", False)],
    )

    member_id = fields.Many2one(
        comodel_name="res.partner",
        string="Socio titular",
        required=True,
        ondelete="restrict",
        index=True,
        domain=[("club_person_type", "=", "member")],
    )

    # -------------------------------------------------------------------------
    # Datos de la persona.
    #
    # Se conservan estos nombres de campo para mantener compatibilidad con
    # vistas y búsquedas mientras la persona real vive únicamente en
    # res.partner.
    # -------------------------------------------------------------------------

    name = fields.Char(
        related="person_id.name",
        string="Nombre completo",
        store=True,
        readonly=True,
    )

    birthdate = fields.Date(
        related="person_id.club_birthdate",
        string="Fecha de nacimiento",
        store=True,
        readonly=True,
    )

    age = fields.Integer(
        related="person_id.club_age",
        string="Edad",
        readonly=True,
    )

    id_number = fields.Char(
        related="person_id.club_id_number",
        string="Número de carnet",
        store=True,
        readonly=True,
    )

    id_extension = fields.Char(
        related="person_id.club_id_extension",
        string="Extensión del carnet",
        store=True,
        readonly=True,
    )

    # -------------------------------------------------------------------------
    # Datos propios del vínculo.
    # -------------------------------------------------------------------------

    relationship = fields.Selection(
        selection=[
            ("spouse", "Esposo(a)"),
            ("partner", "Pareja de hecho"),
            ("child", "Hijo(a)"),
            ("stepchild", "Hijastro(a)"),
            ("parent", "Padre o madre"),
            ("worker", "Trabajador"),
            ("family_dependent", "Familiar dependiente"),
        ],
        string="Vínculo con el Socio",
        required=True,
    )

    relationship_detail = fields.Char(
        string="Detalle del vínculo",
    )

    special_condition = fields.Selection(
        selection=[
            ("none", "Ninguna"),
            (
                "health_dependent",
                "Dependiente por condición de salud",
            ),
        ],
        string="Condición especial",
        required=True,
        default="none",
    )

    start_date = fields.Date(
        string="Fecha de inicio",
        required=True,
        default=fields.Date.context_today,
        copy=False,
    )

    end_date = fields.Date(
        string="Fecha de finalización",
        copy=False,
    )

    state = fields.Selection(
        selection=[
            ("active", "Activo"),
            ("blocked", "Bloqueado"),
            ("finalized", "Finalizado"),
        ],
        string="Estado",
        required=True,
        default="active",
        copy=False,
    )

    block_reason = fields.Char(
        string="Motivo de bloqueo",
        copy=False,
    )

    blocked_by_member_withdrawal = fields.Boolean(
        string="Bloqueado por retiro del Socio titular",
        readonly=True,
        copy=False,
        index=True,
    )

    end_reason = fields.Char(
        string="Motivo de finalización",
        copy=False,
    )

    observations = fields.Text(
        string="Observaciones",
    )

    converted_member_id = fields.Many2one(
        comodel_name="res.partner",
        string="Socio convertido",
        copy=False,
        readonly=True,
        ondelete="restrict",
        domain=[("club_person_type", "=", "member")],
    )

    converted_at = fields.Datetime(
        string="Fecha de conversión a socio",
        copy=False,
        readonly=True,
    )

    @api.model
    def _get_person_from_values(self, vals, beneficiary=None):
        person_id = vals.get("person_id")
        if person_id:
            return self.env["res.partner"].browse(person_id)
        if beneficiary:
            return beneficiary.person_id
        return self.env["res.partner"]

    @api.model
    def _is_age_limit_reached(self, vals, beneficiary=None):
        state = vals.get(
            "state",
            beneficiary.state if beneficiary else "active",
        )
        if state == "finalized":
            return False
        relationship = vals.get(
            "relationship",
            beneficiary.relationship if beneficiary else False,
        )
        special_condition = vals.get(
            "special_condition",
            beneficiary.special_condition if beneficiary else "none",
        )
        if relationship not in self._AGE_LIMITED_RELATIONSHIPS:
            return False
        if special_condition in self._AGE_EXEMPT_SPECIAL_CONDITIONS:
            return False
        person = self._get_person_from_values(
            vals,
            beneficiary=beneficiary,
        )
        if not person or not person.club_birthdate:
            return False
        return person.club_age >= 25

    @api.model
    def _prepare_relationship_values(self, vals):
        prepared_vals = dict(vals)
        if prepared_vals.get("relationship") == "family_dependent":
            detail = (prepared_vals.get("relationship_detail") or "").strip()
            prepared_vals["relationship_detail"] = detail or False
        elif "relationship" in prepared_vals:
            prepared_vals["relationship_detail"] = False
        return prepared_vals

    @api.model
    def _age_limit_reason(self, beneficiary, vals):
        old_special_condition = beneficiary.special_condition
        new_special_condition = vals.get(
            "special_condition",
            old_special_condition,
        )
        if (
            old_special_condition == "health_dependent"
            and new_special_condition != "health_dependent"
        ):
            return self.env._("Fin de condición especial con límite de edad cumplido")
        return self.env._("Límite de edad alcanzado")

    @api.constrains(
        "person_id",
        "member_id",
        "relationship",
        "relationship_detail",
        "state",
    )
    def _check_person_member_and_relationship(self):
        for beneficiary in self:
            person = beneficiary.person_id
            member = beneficiary.member_id
            if not person:
                continue
            if person.is_company:
                raise ValidationError(
                    self.env._(
                        "La persona beneficiaria debe ser una persona individual."
                    )
                )
            if member.club_person_type != "member":
                raise ValidationError(
                    self.env._("El titular de un beneficiario debe ser un socio.")
                )
            if person == member:
                raise ValidationError(
                    self.env._("Una persona no puede ser beneficiaria de sí misma.")
                )
            if beneficiary.relationship == "worker" and not member.is_company:
                raise ValidationError(
                    self.env._(
                        "El vínculo Trabajador solo puede utilizarse "
                        "cuando el Socio titular es una empresa."
                    )
                )
            if (
                beneficiary.relationship == "family_dependent"
                and not (beneficiary.relationship_detail or "").strip()
            ):
                raise ValidationError(
                    self.env._(
                        "Debe indicar el detalle cuando el vínculo "
                        "seleccionado sea Familiar dependiente."
                    )
                )
            if (
                beneficiary.relationship != "family_dependent"
                and beneficiary.relationship_detail
            ):
                raise ValidationError(
                    self.env._(
                        "El detalle del vínculo solo corresponde a "
                        "Familiar dependiente."
                    )
                )
            if beneficiary.state not in ("active", "blocked"):
                continue

            if person.club_person_type == "client":
                raise ValidationError(
                    self.env._(
                        "Un Cliente no puede ser Beneficiario al mismo tiempo. "
                        "Primero debe dejar de tener la condición de Cliente."
                    )
                )

            if person.club_person_type == "member":
                raise ValidationError(
                    self.env._(
                        "Un Socio no puede tener un vínculo vigente como "
                        "Beneficiario, incluso si se encuentra Pasivo. "
                        "Debe finalizar primero su membresía y utilizar "
                        "el proceso correspondiente para Ex-Socios."
                    )
                )

    @api.constrains(
        "person_id",
        "state",
    )
    def _check_single_current_link(self):
        for beneficiary in self:
            if beneficiary.state not in ("active", "blocked"):
                continue

            duplicate = self.search(
                [
                    ("id", "!=", beneficiary.id),
                    ("person_id", "=", beneficiary.person_id.id),
                    ("state", "in", ("active", "blocked")),
                ],
                limit=1,
            )

            if duplicate:
                raise ValidationError(
                    self.env._(
                        "Esta persona ya tiene un vínculo vigente "
                        "como Beneficiario con otro Socio."
                    )
                )

    @api.constrains(
        "person_id",
        "state",
        "relationship",
        "special_condition",
    )
    def _check_personal_data_and_age(self):
        today = fields.Date.context_today(self)

        for beneficiary in self:
            person = beneficiary.person_id

            if not person:
                continue

            if not person.club_id_number:
                raise ValidationError(
                    self.env._(
                        "La persona beneficiaria debe tener un número de carnet."
                    )
                )

            person.check_club_id_number_format(person.club_id_number)

            if not person.club_birthdate:
                raise ValidationError(
                    self.env._(
                        "La fecha de nacimiento es obligatoria "
                        "para una persona beneficiaria."
                    )
                )

            if person.club_birthdate > today:
                raise ValidationError(
                    self.env._(
                        "La fecha de nacimiento no puede ser posterior "
                        "a la fecha actual."
                    )
                )

            if beneficiary.state in (
                "active",
                "blocked",
            ) and self._is_age_limit_reached(
                {},
                beneficiary=beneficiary,
            ):
                raise ValidationError(
                    self.env._(
                        "Hijo(a), Hijastro(a) y Familiar dependiente "
                        "no pueden mantener un vínculo vigente desde "
                        "los 25 años, salvo que tengan la condición "
                        "Dependiente por condición de salud."
                    )
                )

    @api.constrains(
        "start_date",
        "end_date",
        "state",
        "block_reason",
        "end_reason",
    )
    def _check_dates_and_reasons(self):
        for beneficiary in self:
            if (
                beneficiary.start_date
                and beneficiary.end_date
                and beneficiary.end_date < beneficiary.start_date
            ):
                raise ValidationError(
                    self.env._(
                        "La fecha de finalización no puede ser anterior "
                        "a la fecha de inicio."
                    )
                )

            if beneficiary.state == "blocked" and not beneficiary.block_reason:
                raise ValidationError(
                    self.env._("Debe indicar el motivo de bloqueo del Beneficiario.")
                )

            if beneficiary.state == "finalized":
                if not beneficiary.end_date:
                    raise ValidationError(
                        self.env._(
                            "Un vínculo finalizado debe tener fecha de finalización."
                        )
                    )

                if not beneficiary.end_reason:
                    raise ValidationError(
                        self.env._(
                            "Un vínculo finalizado debe tener motivo de finalización."
                        )
                    )

            elif beneficiary.end_date or beneficiary.end_reason:
                raise ValidationError(
                    self.env._(
                        "La fecha y el motivo de finalización solo pueden "
                        "informarse cuando el vínculo esté Finalizado."
                    )
                )

    def _format_kardex_value(
        self,
        beneficiary,
        field_name,
    ):
        field = beneficiary._fields[field_name]
        value = beneficiary[field_name]

        if not value:
            return self.env._("Sin valor")

        if field.type == "many2one":
            return value.display_name

        if field.type == "selection":
            field_description = beneficiary.fields_get([field_name])[field_name]

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

    def _get_kardex_snapshot(
        self,
        beneficiary,
    ):
        field_names = (
            *self._KARDEX_TRACKED_FIELDS,
            "state",
            "block_reason",
            "end_date",
            "end_reason",
        )

        return {
            field_name: self._format_kardex_value(
                beneficiary,
                field_name,
            )
            for field_name in field_names
        }

    def _build_kardex_change_values(
        self,
        beneficiary,
        before_values,
        field_names,
    ):
        old_lines = []
        new_lines = []

        for field_name in field_names:
            old_value = before_values[field_name]

            new_value = self._format_kardex_value(
                beneficiary,
                field_name,
            )

            if old_value == new_value:
                continue

            field_label = beneficiary._fields[field_name].string

            old_lines.append(f"{field_label}: {old_value}")

            new_lines.append(f"{field_label}: {new_value}")

        return (
            "\n".join(old_lines),
            "\n".join(new_lines),
        )

    def _log_kardex_event(
        self,
        beneficiary,
        event_type,
        description,
        **event_data,
    ):
        Kardex = self.env["club.kardex.event"]

        return Kardex._log_event(  # pylint: disable=protected-access
            beneficiary.member_id,
            event_type,
            description,
            beneficiary=beneficiary,
            **event_data,
        )

    def _log_beneficiary_created(
        self,
        beneficiary,
    ):
        new_value = "\n".join(
            [
                self.env._(
                    "Persona: %(value)s",
                    value=beneficiary.person_id.display_name,
                ),
                self.env._(
                    "Carnet: %(value)s",
                    value=beneficiary.id_number,
                ),
                self.env._(
                    "Vínculo: %(value)s",
                    value=self._format_kardex_value(
                        beneficiary,
                        "relationship",
                    ),
                ),
                self.env._(
                    "Condición especial: %(value)s",
                    value=self._format_kardex_value(
                        beneficiary,
                        "special_condition",
                    ),
                ),
                self.env._(
                    "Estado: %(value)s",
                    value=self._format_kardex_value(
                        beneficiary,
                        "state",
                    ),
                ),
            ]
        )

        self._log_kardex_event(
            beneficiary,
            "beneficiary_created",
            self.env._(
                "Beneficiario %(name)s registrado.",
                name=beneficiary.name,
            ),
            new_value=new_value,
            origin="manual",
        )

    def _log_beneficiary_update(
        self,
        beneficiary,
        before_values,
        state_changed,
    ):
        tracked_fields = list(self._KARDEX_TRACKED_FIELDS)

        if not state_changed:
            tracked_fields.extend(
                [
                    "block_reason",
                    "end_date",
                    "end_reason",
                ]
            )

        old_value, new_value = self._build_kardex_change_values(
            beneficiary,
            before_values,
            tracked_fields,
        )

        if not old_value and not new_value:
            return

        self._log_kardex_event(
            beneficiary,
            "beneficiary_updated",
            self.env._(
                "Datos del vínculo del Beneficiario %(name)s actualizados.",
                name=beneficiary.name,
            ),
            old_value=old_value,
            new_value=new_value,
            origin="manual",
        )

    def _log_beneficiary_state_change(
        self,
        beneficiary,
        before_values,
        change_data,
    ):
        old_state = change_data["old_state"]
        new_state = beneficiary.state

        if old_state == new_state:
            return

        if new_state == "blocked":
            self._log_kardex_event(
                beneficiary,
                "beneficiary_blocked",
                self.env._(
                    "Beneficiario %(name)s bloqueado.",
                    name=beneficiary.name,
                ),
                old_value=before_values["state"],
                new_value=self._format_kardex_value(
                    beneficiary,
                    "state",
                ),
                reason=beneficiary.block_reason,
                origin="manual",
            )
            return

        if new_state == "active":
            previous_reason = before_values["block_reason"]

            self._log_kardex_event(
                beneficiary,
                "beneficiary_reactivated",
                self.env._(
                    "Beneficiario %(name)s reactivado.",
                    name=beneficiary.name,
                ),
                old_value=before_values["state"],
                new_value=self._format_kardex_value(
                    beneficiary,
                    "state",
                ),
                reason=(
                    self.env._(
                        "Bloqueo anterior: %(reason)s",
                        reason=previous_reason,
                    )
                    if previous_reason != self.env._("Sin valor")
                    else False
                ),
                origin="manual",
            )
            return

        if new_state == "finalized":
            automatic_age_finalization = change_data.get(
                "automatic_age_finalization",
                False,
            )

            description = (
                self.env._(
                    "Vínculo del Beneficiario %(name)s "
                    "finalizado automáticamente por "
                    "regla de edad.",
                    name=beneficiary.name,
                )
                if automatic_age_finalization
                else self.env._(
                    "Vínculo del Beneficiario %(name)s finalizado.",
                    name=beneficiary.name,
                )
            )

            self._log_kardex_event(
                beneficiary,
                "beneficiary_finalized",
                description,
                old_value=before_values["state"],
                new_value=self._format_kardex_value(
                    beneficiary,
                    "state",
                ),
                reason=beneficiary.end_reason,
                origin=("automatic" if automatic_age_finalization else "manual"),
            )

    def _log_beneficiary_write_changes(
        self,
        beneficiary,
        before_values,
        change_data,
    ):
        state_changed = change_data["old_state"] != beneficiary.state

        self._log_beneficiary_update(
            beneficiary,
            before_values,
            state_changed,
        )

        self._log_beneficiary_state_change(
            beneficiary,
            before_values,
            change_data,
        )

    @api.model_create_multi
    def create(self, vals_list):
        prepared_vals_list = []

        for original_vals in vals_list:
            vals = self._prepare_relationship_values(original_vals)

            if self._is_age_limit_reached(vals):
                raise ValidationError(
                    self.env._(
                        "No puede registrarse un Hijo(a), "
                        "Hijastro(a) o Familiar dependiente "
                        "de 25 años o más como Beneficiario "
                        "vigente, salvo que tenga la condición "
                        "Dependiente por condición de salud."
                    )
                )

            prepared_vals_list.append(vals)

        beneficiaries = super().create(prepared_vals_list)

        for beneficiary in beneficiaries:
            self._log_beneficiary_created(beneficiary)

        return beneficiaries

    def _write_member_withdrawal_values_internal(self, vals):
        return self.with_context(
            club_beneficiary_withdrawal_internal_token=(
                _CLUB_BENEFICIARY_WITHDRAWAL_INTERNAL_TOKEN
            )
        ).write(vals)

    def write(self, vals):
        vals = dict(vals)

        internal_withdrawal_write = (
            self.env.context.get("club_beneficiary_withdrawal_internal_token")
            is _CLUB_BENEFICIARY_WITHDRAWAL_INTERNAL_TOKEN
        )

        internal_transition_write = (
            self.env.context.get("club_beneficiary_internal_transition_token")
            is _CLUB_BENEFICIARY_TRANSITION_INTERNAL_TOKEN
        )

        if (
            "blocked_by_member_withdrawal" in vals
            and not internal_withdrawal_write
            and not internal_transition_write
        ):
            raise AccessError(
                self.env._(
                    "La marca técnica de bloqueo por retiro del Socio "
                    "solo puede modificarse mediante un proceso "
                    "controlado del sistema."
                )
            )

        if (
            "state" in vals
            and vals.get("state") != "blocked"
            and not internal_withdrawal_write
            and not internal_transition_write
            and self.filtered("blocked_by_member_withdrawal")
        ):
            raise ValidationError(
                self.env._(
                    "Un Beneficiario bloqueado por retiro del Socio titular "
                    "no puede reactivarse directamente. Debe utilizarse el "
                    "proceso controlado de reactivación del Socio."
                )
            )

        skip_change_logging = internal_transition_write and self.env.context.get(
            "club_beneficiary_skip_change_logging"
        )

        if internal_transition_write:
            return super().write(vals)

        for beneficiary in self:
            if beneficiary.state == "finalized":
                raise ValidationError(
                    self.env._(
                        "Un vínculo de Beneficiario finalizado "
                        "es histórico y no puede modificarse."
                    )
                )

            if "person_id" in vals or "member_id" in vals:
                raise ValidationError(
                    self.env._(
                        "La persona y el Socio titular no pueden "
                        "reemplazarse directamente. Debe finalizarse "
                        "el vínculo actual y crear uno nuevo."
                    )
                )

            before_values = self._get_kardex_snapshot(beneficiary)

            old_state = beneficiary.state

            prepared_vals = dict(vals)

            if (
                beneficiary.blocked_by_member_withdrawal
                and "block_reason" in prepared_vals
                and not internal_withdrawal_write
                and not internal_transition_write
            ):
                prepared_vals["blocked_by_member_withdrawal"] = False

            if "relationship" in prepared_vals:
                prepared_vals = self._prepare_relationship_values(prepared_vals)

            automatic_age_finalization = self._is_age_limit_reached(
                prepared_vals,
                beneficiary=beneficiary,
            )

            if automatic_age_finalization:
                prepared_vals.update(
                    {
                        "state": "finalized",
                        "end_date": (fields.Date.context_today(beneficiary)),
                        "end_reason": (
                            self._age_limit_reason(
                                beneficiary,
                                prepared_vals,
                            )
                        ),
                        "block_reason": False,
                    }
                )

            elif prepared_vals.get("state") == "active":
                prepared_vals["block_reason"] = False

            super(
                ClubBeneficiary,
                beneficiary,
            ).write(prepared_vals)

            if skip_change_logging:
                continue

            self._log_beneficiary_write_changes(
                beneficiary,
                before_values,
                {
                    "old_state": old_state,
                    "automatic_age_finalization": (automatic_age_finalization),
                },
            )

        return True

    @api.model
    def _cron_finalize_age_limit_beneficiaries(
        self,
    ):
        beneficiaries = self.search(
            [
                (
                    "relationship",
                    "in",
                    tuple(self._AGE_LIMITED_RELATIONSHIPS),
                ),
                (
                    "special_condition",
                    "=",
                    "none",
                ),
                (
                    "person_id.club_birthdate",
                    "!=",
                    False,
                ),
                (
                    "state",
                    "in",
                    ("active", "blocked"),
                ),
            ]
        )

        for beneficiary in beneficiaries:
            if self._is_age_limit_reached(
                {},
                beneficiary=beneficiary,
            ):
                beneficiary.finalize_link(
                    end_date=(fields.Date.context_today(beneficiary)),
                    reason=self.env._("Límite de edad alcanzado"),
                    origin="automatic",
                )

    @api.model
    def _cron_block_age_limit_beneficiaries(
        self,
    ):
        """Compatibilidad con el cron ya instalado."""
        return self._cron_finalize_age_limit_beneficiaries()

    @api.ondelete(at_uninstall=False)
    def _unlink_except_module_uninstall(self):
        raise ValidationError(
            self.env._(
                "Los vínculos de Beneficiario son históricos y no pueden eliminarse."
            )
        )
