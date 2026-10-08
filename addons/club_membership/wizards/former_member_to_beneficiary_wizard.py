from odoo import api, fields, models
from odoo.exceptions import ValidationError


class ClubFormerMemberToBeneficiaryWizard(models.TransientModel):
    _name = "club.former.member.to.beneficiary.wizard"
    _description = "Asistente de conversión de Ex-Socio a Beneficiario"

    person_id = fields.Many2one(
        comodel_name="res.partner",
        string="Ex-Socio",
        required=True,
        readonly=True,
        ondelete="cascade",
        domain=[
            ("club_is_former_member", "=", True),
            ("club_person_type", "=", False),
        ],
    )

    id_number = fields.Char(
        related="person_id.club_id_number",
        string="Carnet / Identificación",
        readonly=True,
    )

    last_membership_end_date = fields.Date(
        string="Última finalización de membresía",
        compute="_compute_last_membership_end_date",
        readonly=True,
    )

    member_id = fields.Many2one(
        comodel_name="res.partner",
        string="Socio titular",
        required=True,
        domain=[("club_person_type", "=", "member")],
    )

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
    )

    observations = fields.Text(
        string="Observaciones",
    )

    @api.depends("person_id")
    def _compute_last_membership_end_date(self):
        Period = self.env["club.membership.period"]

        for wizard in self:
            wizard.last_membership_end_date = False

            if not wizard.person_id:
                continue

            period = Period.search(
                [
                    ("person_id", "=", wizard.person_id.id),
                    ("state", "=", "finalized"),
                ],
                order="end_date desc, id desc",
                limit=1,
            )

            wizard.last_membership_end_date = period.end_date

    def action_confirm(self):
        self.ensure_one()

        if not self.person_id:
            raise ValidationError(
                self.env._(
                    "No se encontró el Ex-Socio que debe convertirse en Beneficiario."
                )
            )

        beneficiary_id = self.person_id.action_convert_former_member_to_beneficiary(
            {
                "member_id": self.member_id.id,
                "relationship": self.relationship,
                "relationship_detail": self.relationship_detail,
                "special_condition": self.special_condition,
                "start_date": self.start_date,
                "observations": self.observations,
            }
        )

        return {
            "type": "ir.actions.act_window",
            "name": self.env._("Beneficiario"),
            "res_model": "club.beneficiary",
            "res_id": beneficiary_id,
            "view_mode": "form",
            "views": [
                (
                    self.env.ref("club_membership.view_club_beneficiary_form").id,
                    "form",
                )
            ],
            "target": "current",
        }
