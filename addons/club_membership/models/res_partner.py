from odoo import api, fields, models
from odoo.exceptions import ValidationError


class ResPartner(models.Model):
    _inherit = "res.partner"

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

    club_origin_beneficiary_ids = fields.One2many(
        comodel_name="club.beneficiary",
        inverse_name="converted_member_id",
        string="Origen como beneficiario",
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

    @api.constrains(
        "club_person_type",
        "club_id_number",
        "club_id_extension",
        "club_birthdate",
        "is_company",
    )
    def _check_club_personal_data(self):
        Beneficiary = self.env["club.beneficiary"]
        today = fields.Date.context_today(self)

        conversion_beneficiary_id = self.env.context.get(
            "club_conversion_beneficiary_id"
        )

        for partner in self:
            if partner.club_person_type not in ("member", "client"):
                continue

            if not partner.club_id_number:
                raise ValidationError(
                    self.env._(
                        "El número de carnet es obligatorio para socios y clientes."
                    )
                )

            if not partner.club_id_number.isascii() or not (
                partner.club_id_number.isdigit()
            ):
                raise ValidationError(
                    self.env._("El número de carnet debe contener únicamente números.")
                )

            if not partner.is_company:
                if not partner.club_birthdate:
                    raise ValidationError(
                        self.env._(
                            "La fecha de nacimiento es obligatoria para socios "
                            "y clientes que sean personas individuales."
                        )
                    )

                if partner.club_birthdate > today:
                    raise ValidationError(
                        self.env._(
                            "La fecha de nacimiento no puede ser posterior "
                            "a la fecha actual."
                        )
                    )

            duplicate = self.search(
                [
                    ("id", "!=", partner.id),
                    ("club_person_type", "in", ("member", "client")),
                    ("club_id_number", "=", partner.club_id_number),
                    (
                        "club_id_extension",
                        "=",
                        partner.club_id_extension or False,
                    ),
                ],
                limit=1,
            )

            if duplicate:
                raise ValidationError(
                    self.env._("Ya existe una persona con el mismo carnet y extensión.")
                )

            duplicate_beneficiary = Beneficiary.search(
                [
                    (
                        "id_number",
                        "=",
                        partner.club_id_number,
                    ),
                    (
                        "id_extension",
                        "=",
                        partner.club_id_extension or False,
                    ),
                ],
                limit=1,
            )

            if (
                duplicate_beneficiary
                and duplicate_beneficiary.id != conversion_beneficiary_id
                and duplicate_beneficiary.converted_member_id != partner
            ):
                raise ValidationError(
                    self.env._(
                        "Ya existe un beneficiario con el mismo carnet y extensión."
                    )
                )

    def _build_club_member_code(
        self,
        id_number,
        id_extension,
        exclude_partner=None,
    ):
        if not id_number:
            return False

        domain = [
            ("club_person_type", "=", "member"),
            ("club_id_number", "=", id_number),
        ]

        if exclude_partner:
            domain.append(("id", "!=", exclude_partner.id))

        same_number_exists = bool(self.search(domain, limit=1))

        if same_number_exists:
            suffix = id_extension or "SINEXT"
            return f"{id_number}-{suffix}"

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
                    "No se puede usar el código de asociado %(code)s porque "
                    "ya pertenece a otro socio.",
                    code=member_code,
                )
            )

    def _apply_club_member_defaults(self, vals, partner=None):
        join_date = partner.club_join_date if partner else False
        member_state = partner.club_member_state if partner else False
        legal_state = partner.club_legal_state if partner else False

        if not vals.get("club_join_date") and not join_date:
            vals["club_join_date"] = fields.Date.context_today(self)

        if not vals.get("club_member_state") and not member_state:
            vals["club_member_state"] = "active"

        if not vals.get("club_legal_state") and not legal_state:
            vals["club_legal_state"] = "regular"

    def _get_club_member_code_for_write(
        self,
        partner,
        vals,
        new_id_number,
        new_id_extension,
    ):
        becoming_member = partner.club_person_type != "member"

        number_changed = (
            "club_id_number" in vals and new_id_number != partner.club_id_number
        )

        if becoming_member or number_changed:
            return self._build_club_member_code(
                new_id_number,
                new_id_extension,
                exclude_partner=partner,
            )

        extension_changed = (
            "club_id_extension" in vals
            and new_id_extension != partner.club_id_extension
        )

        if not extension_changed:
            return partner.club_member_code

        if partner.club_member_code == partner.club_id_number:
            return new_id_number

        suffix = new_id_extension or "SINEXT"
        return f"{new_id_number}-{suffix}"

    def _prepare_club_member_write_vals(self, partner, vals):
        partner_vals = dict(vals)

        new_person_type = partner_vals.get(
            "club_person_type",
            partner.club_person_type,
        )

        if partner.club_person_type == "member" and new_person_type != "member":
            raise ValidationError(
                self.env._(
                    "Un socio no puede convertirse en cliente ni dejar de ser "
                    "socio. Si deja de pertenecer al Club, debe cambiar su "
                    "estado del asociado a Pasivo."
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

        new_id_extension = partner_vals.get(
            "club_id_extension",
            partner.club_id_extension,
        )

        member_code = self._get_club_member_code_for_write(
            partner,
            partner_vals,
            new_id_number,
            new_id_extension,
        )

        self._check_club_member_code_available(
            member_code,
            exclude_partner=partner,
        )

        partner_vals["club_member_code"] = member_code

        return partner_vals

    @api.model_create_multi
    def create(self, vals_list):
        prepared_vals_list = []
        batch_member_numbers = set()
        batch_member_codes = set()

        for original_vals in vals_list:
            vals = dict(original_vals)

            if vals.get("club_person_type") != "member":
                vals["club_member_code"] = False
                prepared_vals_list.append(vals)
                continue

            self._apply_club_member_defaults(vals)

            id_number = vals.get("club_id_number")
            id_extension = vals.get("club_id_extension")

            if not id_number:
                prepared_vals_list.append(vals)
                continue

            existing_member = self.search(
                [
                    ("club_person_type", "=", "member"),
                    ("club_id_number", "=", id_number),
                ],
                limit=1,
            )

            same_number_exists = (
                bool(existing_member) or id_number in batch_member_numbers
            )

            if same_number_exists:
                suffix = id_extension or "SINEXT"
                member_code = f"{id_number}-{suffix}"
            else:
                member_code = id_number

            code_exists = self.search(
                [
                    ("club_member_code", "=", member_code),
                ],
                limit=1,
            )

            if code_exists or member_code in batch_member_codes:
                raise ValidationError(
                    self.env._(
                        "No se puede generar el código de asociado porque "
                        "ya existe otro socio con el código %(code)s.",
                        code=member_code,
                    )
                )

            vals["club_member_code"] = member_code

            batch_member_numbers.add(id_number)
            batch_member_codes.add(member_code)
            prepared_vals_list.append(vals)

        return super().create(prepared_vals_list)

    def write(self, vals):
        vals = dict(vals)
        vals.pop("club_member_code", None)

        if not vals:
            return True

        code_fields = {
            "club_person_type",
            "club_id_number",
            "club_id_extension",
        }

        if not code_fields.intersection(vals):
            return super().write(vals)

        for partner in self:
            partner_vals = self._prepare_club_member_write_vals(
                partner,
                vals,
            )

            super(ResPartner, partner).write(partner_vals)

        return True
