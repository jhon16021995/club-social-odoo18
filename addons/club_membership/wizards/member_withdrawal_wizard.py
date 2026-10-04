from odoo import api, fields, models
from odoo.exceptions import ValidationError


class ClubMemberWithdrawalWizard(models.TransientModel):
    _name = "club.member.withdrawal.wizard"
    _description = "Asistente de retiro o baja voluntaria de Socio"

    member_id = fields.Many2one(
        comodel_name="res.partner",
        string="Socio",
        required=True,
        readonly=True,
        ondelete="cascade",
        domain=[("club_person_type", "=", "member")],
    )

    member_code = fields.Char(
        related="member_id.club_member_code",
        string="Código de asociado",
        readonly=True,
    )

    current_member_state = fields.Selection(
        related="member_id.club_member_state",
        string="Estado actual",
        readonly=True,
    )

    certificate_id = fields.Many2one(
        comodel_name="club.certificate",
        string="Certificado Patrimonial",
        compute="_compute_withdrawal_information",
        readonly=True,
    )

    certificate_state = fields.Selection(
        related="certificate_id.state",
        string="Estado del Certificado",
        readonly=True,
    )

    active_beneficiary_count = fields.Integer(
        string="Beneficiarios activos que serán bloqueados",
        compute="_compute_withdrawal_information",
        readonly=True,
    )

    blocked_beneficiary_count = fields.Integer(
        string="Beneficiarios ya bloqueados",
        compute="_compute_withdrawal_information",
        readonly=True,
    )

    effective_date = fields.Date(
        string="Fecha efectiva del retiro",
        required=True,
        default=fields.Date.context_today,
    )

    reason = fields.Text(
        string="Motivo del retiro",
        required=True,
    )

    @api.depends("member_id")
    def _compute_withdrawal_information(self):
        for wizard in self:
            member = wizard.member_id

            if not member:
                wizard.certificate_id = False
                wizard.active_beneficiary_count = 0
                wizard.blocked_beneficiary_count = 0
                continue

            wizard.certificate_id = member.club_certificate_ids[:1]

            wizard.active_beneficiary_count = len(
                member.club_beneficiary_ids.filtered(
                    lambda beneficiary: beneficiary.state == "active"
                )
            )

            wizard.blocked_beneficiary_count = len(
                member.club_beneficiary_ids.filtered(
                    lambda beneficiary: beneficiary.state == "blocked"
                )
            )

    def action_confirm(self):
        self.ensure_one()

        if not self.member_id:
            raise ValidationError(
                self.env._("No se encontró el Socio que debe retirarse.")
            )

        normalized_reason = (self.reason or "").strip()

        if not normalized_reason:
            raise ValidationError(
                self.env._("Debe indicar el motivo del retiro del Socio.")
            )

        self.member_id.action_withdraw_club_member(
            normalized_reason,
            effective_date=self.effective_date,
        )

        return {
            "type": "ir.actions.act_window",
            "name": self.env._("Socio"),
            "res_model": "res.partner",
            "res_id": self.member_id.id,
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
