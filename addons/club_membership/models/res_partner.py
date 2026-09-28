from odoo import api, fields, models


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
