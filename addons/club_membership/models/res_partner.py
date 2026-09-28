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

    club_occupation = fields.Char(
        string="Ocupación",
    )

    club_title = fields.Char(
        string="Título",
    )

    club_member_code = fields.Char(
        string="Código de asociado",
        copy=False,
    )

    club_join_date = fields.Date(
        string="Fecha de ingreso",
        copy=False,
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

    @api.depends("club_birthdate")
    def _compute_club_age(self):
        today = fields.Date.context_today(self)

        for partner in self:
            if not partner.club_birthdate:
                partner.club_age = 0
                continue

            birthdate = partner.club_birthdate
            partner.club_age = (
                today.year
                - birthdate.year
                - ((today.month, today.day) < (birthdate.month, birthdate.day))
            )

    @api.constrains(
        "club_person_type",
        "club_id_number",
        "club_id_extension",
        "club_birthdate",
    )
    def _check_club_personal_data(self):
        today = fields.Date.context_today(self)

        for partner in self:
            if partner.club_person_type not in ("member", "client"):
                continue

            if not partner.club_id_number:
                raise ValidationError(
                    self.env._(
                        "El número de carnet es obligatorio para socios y clientes."
                    )
                )

            if not partner.club_birthdate:
                raise ValidationError(
                    self.env._(
                        "La fecha de nacimiento es obligatoria para socios y clientes."
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
                    ("club_id_extension", "=", partner.club_id_extension or False),
                ],
                limit=1,
            )

            if duplicate:
                raise ValidationError(
                    self.env._("Ya existe una persona con el mismo carnet y extensión.")
                )
