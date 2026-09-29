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
    def _prepare_age_block_values(self, vals, beneficiary=None):
        prepared_vals = dict(vals)

        relationship = prepared_vals.get(
            "relationship",
            beneficiary.relationship if beneficiary else False,
        )

        birthdate = prepared_vals.get(
            "birthdate",
            beneficiary.birthdate if beneficiary else False,
        )

        if (
            relationship in self._AGE_LIMITED_RELATIONSHIPS
            and birthdate
            and self._get_age_from_birthdate(birthdate) >= 25
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

    @api.model_create_multi
    def create(self, vals_list):
        prepared_vals_list = [
            self._prepare_age_block_values(vals) for vals in vals_list
        ]

        return super().create(prepared_vals_list)

    def write(self, vals):
        for beneficiary in self:
            if beneficiary.converted_member_id and vals.get("state") == "active":
                raise ValidationError(
                    self.env._(
                        "Un beneficiario convertido en socio no puede "
                        "reactivarse como beneficiario."
                    )
                )

            prepared_vals = self._prepare_age_block_values(
                vals,
                beneficiary=beneficiary,
            )

            super(ClubBeneficiary, beneficiary).write(prepared_vals)

        return True

    def action_convert_to_member(self):
        self.ensure_one()

        if self.converted_member_id:
            raise ValidationError(
                self.env._("Este beneficiario ya fue convertido en socio.")
            )

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

        self.write(
            {
                "state": "blocked",
                "block_reason": self.env._("Convertido en socio"),
                "converted_member_id": member.id,
                "converted_at": fields.Datetime.now(),
            }
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
                beneficiary.write(
                    {
                        "state": "blocked",
                        "block_reason": self.env._("Límite de edad alcanzado"),
                    }
                )
