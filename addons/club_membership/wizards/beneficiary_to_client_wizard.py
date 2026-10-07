from odoo import fields, models
from odoo.exceptions import ValidationError


class ClubBeneficiaryToClientWizard(models.TransientModel):
    _name = "club.beneficiary.to.client.wizard"
    _description = "Asistente de conversión de Beneficiario a Cliente"

    beneficiary_id = fields.Many2one(
        comodel_name="club.beneficiary",
        string="Registro de Beneficiario",
        required=True,
        readonly=True,
        ondelete="cascade",
    )

    person_id = fields.Many2one(
        related="beneficiary_id.person_id",
        string="Persona",
        readonly=True,
    )

    member_id = fields.Many2one(
        related="beneficiary_id.member_id",
        string="Socio titular",
        readonly=True,
    )

    relationship = fields.Selection(
        related="beneficiary_id.relationship",
        string="Vínculo",
        readonly=True,
    )

    beneficiary_state = fields.Selection(
        related="beneficiary_id.state",
        string="Estado del vínculo",
        readonly=True,
    )

    end_date = fields.Date(
        string="Fecha de finalización",
        default=fields.Date.context_today,
    )

    reason = fields.Text(
        string="Motivo de conversión",
    )

    def action_confirm(self):
        self.ensure_one()

        if not self.beneficiary_id:
            raise ValidationError(
                self.env._(
                    "No se encontró el vínculo de Beneficiario "
                    "que debe convertirse en Cliente."
                )
            )

        conversion_vals = {}

        if self.beneficiary_id.state != "finalized":
            if not self.end_date:
                raise ValidationError(
                    self.env._("Debe indicar la fecha de finalización del vínculo.")
                )

            conversion_vals.update(
                {
                    "end_date": self.end_date,
                    "reason": self.reason,
                }
            )

        person_id = self.beneficiary_id.action_convert_beneficiary_to_client(
            conversion_vals
        )

        return {
            "type": "ir.actions.act_window",
            "name": self.env._("Cliente"),
            "res_model": "res.partner",
            "res_id": person_id,
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
