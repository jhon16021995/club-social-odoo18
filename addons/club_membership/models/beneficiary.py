from odoo import api, fields, models
from odoo.exceptions import ValidationError


class ClubBeneficiary(models.Model):
    _name = "club.beneficiary"
    _description = "Vínculo de Beneficiario del Club"
    _order = "member_id, person_id"

    _AGE_LIMITED_RELATIONSHIPS = {
        "child",
        "stepchild",
    }

    _AGE_EXEMPT_SPECIAL_CONDITIONS = {
        "legal_guardianship",
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
            ("sibling", "Hermano(a)"),
            ("worker", "Trabajador"),
            ("other", "Otro vínculo"),
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
                "legal_guardianship",
                "Bajo tutela legal del Socio",
            ),
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
    def _prepare_age_block_values(self, vals, beneficiary=None):
        prepared_vals = dict(vals)

        target_state = prepared_vals.get(
            "state",
            beneficiary.state if beneficiary else "active",
        )

        if target_state == "finalized":
            return prepared_vals

        age_limit_reached = self._is_age_limit_reached(
            prepared_vals,
            beneficiary=beneficiary,
        )

        if age_limit_reached:
            prepared_vals["state"] = "blocked"

            current_reason = beneficiary.block_reason if beneficiary else False

            if not prepared_vals.get("block_reason") and not current_reason:
                prepared_vals["block_reason"] = self.env._("Límite de edad alcanzado")

            return prepared_vals

        if (
            beneficiary
            and beneficiary.state == "blocked"
            and beneficiary.block_reason == self.env._("Límite de edad alcanzado")
        ):
            prepared_vals["state"] = "active"
            prepared_vals["block_reason"] = False
            return prepared_vals

        if prepared_vals.get("state") == "active":
            prepared_vals["block_reason"] = False

        return prepared_vals

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
                beneficiary.relationship == "other"
                and not beneficiary.relationship_detail
            ):
                raise ValidationError(
                    self.env._(
                        "Debe indicar el detalle cuando el vínculo "
                        "seleccionado sea Otro vínculo."
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

            if (
                person.club_person_type == "member"
                and person.club_member_state != "inactive"
            ):
                raise ValidationError(
                    self.env._(
                        "Un Socio vigente no puede ser Beneficiario. "
                        "Solo un Socio Pasivo puede tener un vínculo "
                        "vigente como Beneficiario."
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

            if beneficiary.state == "active" and self._is_age_limit_reached(
                {},
                beneficiary=beneficiary,
            ):
                raise ValidationError(
                    self.env._(
                        "Los hijos e hijastros de 25 años o más deben "
                        "estar bloqueados, salvo que tengan una condición "
                        "especial vigente."
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

    def _format_kardex_value(self, beneficiary, field_name):
        field = beneficiary._fields[field_name]
        value = beneficiary[field_name]

        if not value:
            return self.env._("Sin valor")

        if field.type == "many2one":
            return value.display_name

        if field.type == "selection":
            field_description = beneficiary.fields_get([field_name])[field_name]

            selection = dict(field_description.get("selection", []))

            return selection.get(value, value)

        if field.type == "date":
            return fields.Date.to_string(value)

        return str(value)

    def _get_kardex_snapshot(self, beneficiary):
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

        return "\n".join(old_lines), "\n".join(new_lines)

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

    def _log_beneficiary_created(self, beneficiary):
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
            tracked_fields.append("block_reason")

        tracked_fields.extend(
            [
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
            automatic_age_block = change_data["automatic_age_block"]

            event_type = (
                "beneficiary_age_blocked"
                if automatic_age_block
                else "beneficiary_blocked"
            )

            description = (
                self.env._(
                    "Beneficiario %(name)s bloqueado "
                    "automáticamente por límite de edad.",
                    name=beneficiary.name,
                )
                if automatic_age_block
                else self.env._(
                    "Beneficiario %(name)s bloqueado.",
                    name=beneficiary.name,
                )
            )

            self._log_kardex_event(
                beneficiary,
                event_type,
                description,
                old_value=before_values["state"],
                new_value=self._format_kardex_value(
                    beneficiary,
                    "state",
                ),
                reason=beneficiary.block_reason,
                origin=("automatic" if automatic_age_block else "manual"),
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
                origin=(
                    "automatic"
                    if change_data["automatic_age_reactivation"]
                    else "manual"
                ),
            )
            return

        if new_state == "finalized":
            self._log_kardex_event(
                beneficiary,
                "beneficiary_updated",
                self.env._(
                    "Vínculo del Beneficiario %(name)s finalizado.",
                    name=beneficiary.name,
                ),
                old_value=before_values["state"],
                new_value=self._format_kardex_value(
                    beneficiary,
                    "state",
                ),
                reason=beneficiary.end_reason,
                origin="manual",
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
        prepared_vals_list = [
            self._prepare_age_block_values(vals) for vals in vals_list
        ]

        beneficiaries = super().create(prepared_vals_list)

        for beneficiary in beneficiaries:
            self._log_beneficiary_created(beneficiary)

        return beneficiaries

    def write(self, vals):
        conversion_write = self.env.context.get("club_beneficiary_conversion_write")

        automatic_age_context = self.env.context.get(
            "club_beneficiary_automatic_age_block"
        )

        for beneficiary in self:
            if beneficiary.state == "finalized" and not conversion_write:
                raise ValidationError(
                    self.env._(
                        "Un vínculo de Beneficiario finalizado es "
                        "histórico y no puede modificarse."
                    )
                )

            if ("person_id" in vals or "member_id" in vals) and not conversion_write:
                raise ValidationError(
                    self.env._(
                        "La persona y el Socio titular no pueden "
                        "reemplazarse directamente. Debe finalizarse "
                        "el vínculo actual y crear uno nuevo."
                    )
                )

            before_values = self._get_kardex_snapshot(beneficiary)

            old_state = beneficiary.state
            old_reason = beneficiary.block_reason

            prepared_vals = self._prepare_age_block_values(
                vals,
                beneficiary=beneficiary,
            )

            automatic_age_block = bool(
                automatic_age_context
                or (
                    old_state != "blocked"
                    and prepared_vals.get(
                        "state",
                        old_state,
                    )
                    == "blocked"
                    and prepared_vals.get(
                        "block_reason",
                        old_reason,
                    )
                    == self.env._("Límite de edad alcanzado")
                )
            )

            automatic_age_reactivation = bool(
                old_state == "blocked"
                and old_reason == self.env._("Límite de edad alcanzado")
                and prepared_vals.get(
                    "state",
                    old_state,
                )
                == "active"
            )

            super(
                ClubBeneficiary,
                beneficiary,
            ).write(prepared_vals)

            if conversion_write:
                continue

            self._log_beneficiary_write_changes(
                beneficiary,
                before_values,
                {
                    "old_state": old_state,
                    "automatic_age_block": (automatic_age_block),
                    "automatic_age_reactivation": (automatic_age_reactivation),
                },
            )

        return True

    def action_convert_to_member(self):
        self.ensure_one()

        if self.state == "finalized":
            raise ValidationError(
                self.env._("Este vínculo de Beneficiario ya está finalizado.")
            )

        person = self.person_id

        if person.club_person_type == "client":
            raise ValidationError(
                self.env._(
                    "Esta persona todavía tiene la condición de Cliente. "
                    "Debe finalizar primero esa condición antes de "
                    "convertirse en Socio."
                )
            )

        if person.club_person_type == "member":
            raise ValidationError(
                self.env._(
                    "Esta persona ya posee historial como Socio. "
                    "La reactivación de un Socio Pasivo se realizará "
                    "mediante el proceso específico de reactivación."
                )
            )

        original_member = self.member_id

        person.with_context(club_conversion_beneficiary_id=self.id).write(
            {
                "club_person_type": "member",
            }
        )

        self.with_context(club_beneficiary_conversion_write=True).write(
            {
                "state": "finalized",
                "end_date": fields.Date.context_today(self),
                "end_reason": self.env._("Conversión a Socio"),
                "converted_member_id": person.id,
                "converted_at": fields.Datetime.now(),
            }
        )

        self._log_kardex_event(
            self,
            "beneficiary_converted",
            self.env._(
                "Beneficiario %(name)s convertido en Socio.",
                name=self.name,
            ),
            old_value=self.env._(
                "Beneficiario de %(member)s",
                member=original_member.display_name,
            ),
            new_value=self.env._(
                "Socio %(member)s · Código %(code)s",
                member=person.display_name,
                code=person.club_member_code,
            ),
            reason=self.env._("Conversión a Socio"),
            origin="manual",
        )

        return {
            "type": "ir.actions.act_window",
            "name": self.env._("Socio"),
            "res_model": "res.partner",
            "res_id": person.id,
            "view_mode": "form",
            "views": [
                (
                    self.env.ref(
                        "club_membership.view_partner_form_club_membership"
                    ).id,
                    "form",
                )
            ],
            "target": "current",
        }

    @api.model
    def _cron_block_age_limit_beneficiaries(self):
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
                    "=",
                    "active",
                ),
            ]
        )

        for beneficiary in beneficiaries:
            if self._is_age_limit_reached(
                {},
                beneficiary=beneficiary,
            ):
                beneficiary.with_context(
                    club_beneficiary_automatic_age_block=True
                ).write(
                    {
                        "state": "blocked",
                        "block_reason": self.env._("Límite de edad alcanzado"),
                    }
                )

    @api.ondelete(at_uninstall=False)
    def _unlink_except_module_uninstall(self):
        raise ValidationError(
            self.env._(
                "Los vínculos de Beneficiario son históricos y no pueden eliminarse."
            )
        )
