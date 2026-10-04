from odoo import api, fields, models
from odoo.exceptions import ValidationError


class ClubMemberReactivationWizard(models.TransientModel):
    _name = "club.member.reactivation.wizard"
    _description = "Asistente de reactivación de Socio Pasivo"

    member_id = fields.Many2one(
        comodel_name="res.partner",
        string="Socio",
        required=True,
        readonly=True,
        ondelete="cascade",
        domain=[
            ("club_person_type", "=", "member"),
            ("club_member_state", "=", "inactive"),
        ],
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

    restore_member_state = fields.Selection(
        related="member_id.club_state_before_withdrawal",
        string="Estado que será restaurado",
        readonly=True,
    )

    last_withdrawal_date = fields.Date(
        related="member_id.club_last_withdrawal_date",
        string="Fecha efectiva del último retiro",
        readonly=True,
    )

    last_withdrawal_cause = fields.Selection(
        related="member_id.club_last_withdrawal_cause",
        string="Causa del último retiro",
        readonly=True,
    )

    certificate_id = fields.Many2one(
        comodel_name="club.certificate",
        string="Certificado Patrimonial",
        compute="_compute_reactivation_information",
        readonly=True,
    )

    certificate_state = fields.Selection(
        related="certificate_id.state",
        string="Estado del Certificado",
        readonly=True,
    )

    certificate_will_reactivate = fields.Boolean(
        string="El Certificado será reactivado",
        compute="_compute_reactivation_information",
        readonly=True,
    )

    eligible_beneficiary_count = fields.Integer(
        string="Beneficiarios que serán reactivados",
        compute="_compute_reactivation_information",
        readonly=True,
    )

    preserved_blocked_beneficiary_count = fields.Integer(
        string="Beneficiarios que permanecerán bloqueados",
        compute="_compute_reactivation_information",
        readonly=True,
    )

    effective_date = fields.Date(
        string="Fecha efectiva de la reactivación",
        required=True,
        default=fields.Date.context_today,
    )

    reason = fields.Text(
        string="Motivo de la reactivación",
        required=True,
    )

    @api.depends("member_id")
    def _compute_reactivation_information(self):
        for wizard in self:
            member = wizard.member_id

            if not member:
                wizard.certificate_id = False
                wizard.certificate_will_reactivate = False
                wizard.eligible_beneficiary_count = 0
                wizard.preserved_blocked_beneficiary_count = 0
                continue

            certificate = member.club_certificate_ids[:1]
            wizard.certificate_id = certificate

            wizard.certificate_will_reactivate = bool(
                certificate
                and certificate.state == "passive"
                and certificate.passive_by_member_withdrawal
            )

            blocked_beneficiaries = member.club_beneficiary_ids.filtered(
                lambda beneficiary: beneficiary.state == "blocked"
            )

            eligible_beneficiaries = blocked_beneficiaries.filtered(
                "blocked_by_member_withdrawal"
            )

            wizard.eligible_beneficiary_count = len(eligible_beneficiaries)

            wizard.preserved_blocked_beneficiary_count = len(
                blocked_beneficiaries - eligible_beneficiaries
            )

    def action_confirm(self):
        self.ensure_one()

        if not self.member_id:
            raise ValidationError(
                self.env._("No se encontró el Socio que debe reactivarse.")
            )

        normalized_reason = (self.reason or "").strip()

        if not normalized_reason:
            raise ValidationError(
                self.env._("Debe indicar el motivo de la reactivación del Socio.")
            )

        self.member_id.action_reactivate_club_member(
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
