from odoo import fields, models
from odoo.exceptions import ValidationError


class ClubClientToBeneficiaryWizard(models.TransientModel):
    _name = "club.client.to.beneficiary.wizard"
    _description = "Asistente de conversión de Cliente a Beneficiario"

    person_id = fields.Many2one(
        comodel_name="res.partner",
        string="Cliente",
        required=True,
        readonly=True,
        ondelete="cascade",
        domain=[("club_person_type", "=", "client")],
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

    def action_confirm(self):
        self.ensure_one()

        if not self.person_id:
            raise ValidationError(
                self.env._(
                    "No se encontró el Cliente que debe convertirse en Beneficiario."
                )
            )

        beneficiary_id = self.person_id.action_convert_client_to_beneficiary(
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
