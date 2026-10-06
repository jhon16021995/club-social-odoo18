from odoo import api, fields, models
from odoo.exceptions import ValidationError


class ClubClientToMemberWizard(models.TransientModel):
    _name = "club.client.to.member.wizard"
    _description = "Asistente de conversión de Cliente a Socio"

    person_id = fields.Many2one(
        comodel_name="res.partner",
        string="Cliente",
        required=True,
        readonly=True,
        ondelete="cascade",
        domain=[("club_person_type", "=", "client")],
    )

    is_reentry = fields.Boolean(
        string="Es Reingreso",
        compute="_compute_membership_history",
        readonly=True,
    )

    last_membership_end_date = fields.Date(
        string="Última finalización de membresía",
        compute="_compute_membership_history",
        readonly=True,
    )

    effective_date = fields.Date(
        string="Fecha efectiva del Reingreso",
    )

    reason = fields.Text(
        string="Motivo del Reingreso",
    )

    @api.depends("person_id")
    def _compute_membership_history(self):
        Period = self.env["club.membership.period"]

        for wizard in self:
            wizard.is_reentry = False
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

            if last_period:
                wizard.is_reentry = True
                wizard.last_membership_end_date = last_period.end_date

    def action_confirm(self):
        self.ensure_one()

        if not self.person_id:
            raise ValidationError(
                self.env._("No se encontró el Cliente que debe convertirse en Socio.")
            )

        finalized_period = self.env["club.membership.period"].search(
            [
                ("person_id", "=", self.person_id.id),
                ("state", "=", "finalized"),
            ],
            limit=1,
        )

        if finalized_period:
            normalized_reason = (self.reason or "").strip()

            if not normalized_reason:
                raise ValidationError(
                    self.env._("Debe indicar el motivo del Reingreso como Socio.")
                )

            if not self.effective_date:
                raise ValidationError(
                    self.env._(
                        "Debe indicar la fecha efectiva del Reingreso como Socio."
                    )
                )

            self.person_id.action_convert_client_to_member(
                normalized_reason,
                effective_date=self.effective_date,
            )
        else:
            self.person_id.action_convert_client_to_member()

        return {
            "type": "ir.actions.act_window",
            "name": self.env._("Socio"),
            "res_model": "res.partner",
            "res_id": self.person_id.id,
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
