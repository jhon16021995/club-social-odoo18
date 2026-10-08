from odoo import api, fields, models
from odoo.exceptions import ValidationError


class ClubFormerMemberToClientWizard(models.TransientModel):
    _name = "club.former.member.to.client.wizard"
    _description = "Asistente de conversión de Ex-Socio a Cliente"

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
        string="Fecha de finalización de la última membresía",
        compute="_compute_last_membership_end_date",
        readonly=True,
    )

    reason = fields.Text(
        string="Motivo de conversión",
        required=True,
    )

    @api.depends("person_id")
    def _compute_last_membership_end_date(self):
        Period = self.env["club.membership.period"]

        for wizard in self:
            wizard.last_membership_end_date = False

            if not wizard.person_id:
                continue

            last_period = Period.search(
                [
                    ("person_id", "=", wizard.person_id.id),
                    ("state", "=", "finalized"),
                ],
                order="end_date desc, id desc",
                limit=1,
            )

            wizard.last_membership_end_date = last_period.end_date

    def action_confirm(self):
        self.ensure_one()

        if not self.person_id:
            raise ValidationError(
                self.env._(
                    "No se encontró el Ex-Socio que debe convertirse en Cliente."
                )
            )

        normalized_reason = (self.reason or "").strip()

        if not normalized_reason:
            raise ValidationError(
                self.env._(
                    "Debe indicar el motivo de la conversión de Ex-Socio a Cliente."
                )
            )

        person_id = self.person_id.action_convert_former_member_to_client(
            normalized_reason
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
