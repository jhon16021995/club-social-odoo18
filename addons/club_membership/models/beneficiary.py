from odoo import api, fields, models
from odoo.exceptions import ValidationError


class ClubBeneficiary(models.Model):
    _name = "club.beneficiary"
    _description = "Beneficiario del Club"
    _order = "member_id, name"

    _AGE_LIMITED_RELATIONSHIPS = {
        "child",
        "stepchild",
    }

    _KARDEX_TRACKED_FIELDS = (
        "name",
        "relationship",
        "birthdate",
        "id_number",
        "id_extension",
    )

    member_id = fields.Many2one(
        comodel_name="res.partner",
        string="Socio titular",
        required=True,
        ondelete="restrict",
        index=True,
        domain=[("club_person_type", "=", "member")],
    )

    name = fields.Char(
        string="Nombre completo",
        required=True,
    )

    relationship = fields.Selection(
        selection=[
            ("spouse", "Esposo(a)"),
            ("partner", "Pareja de hecho"),
            ("child", "Hijo(a)"),
            ("stepchild", "Hijastro(a)"),
            ("parent", "Padre o madre"),
            ("legal_guardian", "Tutor legal"),
            (
                "health_dependent",
                "Dependiente por condición de salud",
            ),
            ("worker", "Trabajador"),
        ],
        string="Parentesco",
        required=True,
    )

    birthdate = fields.Date(
        string="Fecha de nacimiento",
        required=True,
    )

    age = fields.Integer(
        string="Edad",
        compute="_compute_age",
    )

    id_number = fields.Char(
        string="Número de carnet",
        required=True,
    )

    id_extension = fields.Char(
        string="Extensión del carnet",
    )

    state = fields.Selection(
        selection=[
            ("active", "Activo"),
            ("blocked", "Bloqueado"),
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

    @api.depends("birthdate")
    def _compute_age(self):
        today = fields.Date.context_today(self)

        for beneficiary in self:
            if not beneficiary.birthdate:
                beneficiary.age = 0
                continue

            birthdate = beneficiary.birthdate
            beneficiary.age = (
                today.year
                - birthdate.year
                - ((today.month, today.day) < (birthdate.month, birthdate.day))
            )

    @api.model
    def _get_age_from_birthdate(self, birthdate):
        birthdate = fields.Date.to_date(birthdate)

        if not birthdate:
            return 0

        today = fields.Date.context_today(self)

        return (
            today.year
            - birthdate.year
            - ((today.month, today.day) < (birthdate.month, birthdate.day))
        )

    @api.model
    def _is_age_limit_reached(self, vals, beneficiary=None):
        relationship = vals.get(
            "relationship",
            beneficiary.relationship if beneficiary else False,
        )

        birthdate = vals.get(
            "birthdate",
            beneficiary.birthdate if beneficiary else False,
        )

        return bool(
            relationship in self._AGE_LIMITED_RELATIONSHIPS
            and birthdate
            and self._get_age_from_birthdate(birthdate) >= 25
        )

    @api.model
    def _prepare_age_block_values(self, vals, beneficiary=None):
        prepared_vals = dict(vals)

        if self._is_age_limit_reached(
            prepared_vals,
            beneficiary=beneficiary,
        ):
            prepared_vals["state"] = "blocked"

            if not prepared_vals.get("block_reason"):
                prepared_vals["block_reason"] = self.env._("Límite de edad alcanzado")

        elif prepared_vals.get("state") == "active":
            prepared_vals["block_reason"] = False

        return prepared_vals

    @api.constrains(
        "member_id",
        "relationship",
    )
    def _check_member_and_relationship(self):
        for beneficiary in self:
            if beneficiary.member_id.club_person_type != "member":
                raise ValidationError(
                    self.env._("El titular de un beneficiario debe ser un socio.")
                )

            if (
                beneficiary.relationship == "worker"
                and not beneficiary.member_id.is_company
            ):
                raise ValidationError(
                    self.env._(
                        "El parentesco Trabajador solo puede utilizarse "
                        "cuando el socio titular es una empresa."
                    )
                )

    @api.constrains(
        "birthdate",
        "relationship",
        "state",
    )
    def _check_birthdate_and_age_limit(self):
        today = fields.Date.context_today(self)

        for beneficiary in self:
            if beneficiary.birthdate > today:
                raise ValidationError(
                    self.env._(
                        "La fecha de nacimiento no puede ser posterior "
                        "a la fecha actual."
                    )
                )

            if (
                beneficiary.relationship in self._AGE_LIMITED_RELATIONSHIPS
                and beneficiary.age >= 25
                and beneficiary.state != "blocked"
            ):
                raise ValidationError(
                    self.env._(
                        "Los hijos e hijastros de 25 años o más deben estar bloqueados."
                    )
                )

    @api.constrains(
        "id_number",
        "id_extension",
        "converted_member_id",
    )
    def _check_identity(self):
        Partner = self.env["res.partner"]

        for beneficiary in self:
            if not beneficiary.id_number.isascii() or not (
                beneficiary.id_number.isdigit()
            ):
                raise ValidationError(
                    self.env._("El número de carnet debe contener únicamente números.")
                )

            duplicate_beneficiary = self.search(
                [
                    ("id", "!=", beneficiary.id),
                    ("id_number", "=", beneficiary.id_number),
                    (
                        "id_extension",
                        "=",
                        beneficiary.id_extension or False,
                    ),
                ],
                limit=1,
            )

            if duplicate_beneficiary:
                raise ValidationError(
                    self.env._(
                        "Ya existe un beneficiario con el mismo carnet y extensión."
                    )
                )

            duplicate_partner = Partner.search(
                [
                    (
                        "club_person_type",
                        "in",
                        ("member", "client"),
                    ),
                    (
                        "club_id_number",
                        "=",
                        beneficiary.id_number,
                    ),
                    (
                        "club_id_extension",
                        "=",
                        beneficiary.id_extension or False,
                    ),
                ],
                limit=1,
            )

            if (
                duplicate_partner
                and duplicate_partner != beneficiary.converted_member_id
            ):
                raise ValidationError(
                    self.env._(
                        "Ya existe un socio o cliente con el mismo carnet y extensión."
                    )
                )

    @api.constrains(
        "state",
        "block_reason",
    )
    def _check_block_reason(self):
        for beneficiary in self:
            if beneficiary.state == "blocked" and not beneficiary.block_reason:
                raise ValidationError(
                    self.env._("Debe indicar el motivo de bloqueo del beneficiario.")
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
                    "Parentesco: %(value)s",
                    value=self._format_kardex_value(
                        beneficiary,
                        "relationship",
                    ),
                ),
                self.env._(
                    "Carnet: %(value)s",
                    value=beneficiary.id_number,
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
                "Datos del beneficiario %(name)s actualizados.",
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
            if beneficiary.converted_member_id and not conversion_write:
                raise ValidationError(
                    self.env._(
                        "Este beneficiario ya fue convertido en socio "
                        "y su registro histórico no puede modificarse."
                    )
                )

            if beneficiary.converted_member_id and vals.get("state") == "active":
                raise ValidationError(
                    self.env._(
                        "Un beneficiario convertido en socio no puede "
                        "reactivarse como beneficiario."
                    )
                )

            before_values = self._get_kardex_snapshot(beneficiary)

            old_state = beneficiary.state

            automatic_age_block = bool(
                automatic_age_context
                or (
                    old_state != "blocked"
                    and vals.get("state") != "blocked"
                    and self._is_age_limit_reached(
                        vals,
                        beneficiary=beneficiary,
                    )
                )
            )

            prepared_vals = self._prepare_age_block_values(
                vals,
                beneficiary=beneficiary,
            )

            super(ClubBeneficiary, beneficiary).write(prepared_vals)

            if conversion_write:
                continue

            self._log_beneficiary_write_changes(
                beneficiary,
                before_values,
                {
                    "old_state": old_state,
                    "automatic_age_block": automatic_age_block,
                },
            )

        return True

    def action_convert_to_member(self):
        self.ensure_one()

        if self.converted_member_id:
            raise ValidationError(
                self.env._("Este beneficiario ya fue convertido en socio.")
            )

        original_member = self.member_id

        member = (
            self.env["res.partner"]
            .with_context(club_conversion_beneficiary_id=self.id)
            .create(
                {
                    "name": self.name,
                    "club_person_type": "member",
                    "club_id_number": self.id_number,
                    "club_id_extension": self.id_extension,
                    "club_birthdate": self.birthdate,
                    "is_company": False,
                }
            )
        )

        self.with_context(club_beneficiary_conversion_write=True).write(
            {
                "state": "blocked",
                "block_reason": self.env._("Convertido en socio"),
                "converted_member_id": member.id,
                "converted_at": fields.Datetime.now(),
            }
        )

        self._log_kardex_event(
            self,
            "beneficiary_converted",
            self.env._(
                "Beneficiario %(name)s convertido en socio.",
                name=self.name,
            ),
            old_value=self.env._(
                "Beneficiario de %(member)s",
                member=original_member.display_name,
            ),
            new_value=self.env._(
                "Socio %(member)s · Código %(code)s",
                member=member.display_name,
                code=member.club_member_code,
            ),
            reason=self.env._("Convertido en socio"),
            origin="manual",
        )

        return {
            "type": "ir.actions.act_window",
            "name": self.env._("Socio"),
            "res_model": "res.partner",
            "res_id": member.id,
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
                ("birthdate", "!=", False),
                ("state", "=", "active"),
                ("converted_member_id", "=", False),
            ]
        )

        for beneficiary in beneficiaries:
            if beneficiary.age >= 25:
                beneficiary.with_context(
                    club_beneficiary_automatic_age_block=True
                ).write(
                    {
                        "state": "blocked",
                        "block_reason": self.env._("Límite de edad alcanzado"),
                    }
                )
