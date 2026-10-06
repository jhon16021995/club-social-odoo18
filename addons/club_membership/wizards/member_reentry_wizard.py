from odoo import api, fields, models
from odoo.exceptions import ValidationError


class ClubMemberReentryWizard(models.TransientModel):
    _name = "club.member.reentry.wizard"
    _description = "Asistente de Reingreso de Ex-Socio como Socio"

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
        compute="_compute_reentry_information",
        readonly=True,
    )

    certificate_id = fields.Many2one(
        comodel_name="club.certificate",
        string="Certificado Patrimonial",
        compute="_compute_reentry_information",
        readonly=True,
    )

    certificate_state = fields.Selection(
        related="certificate_id.state",
        string="Estado del Certificado",
        readonly=True,
    )

    certificate_will_reactivate = fields.Boolean(
        string="El Certificado será reactivado",
        compute="_compute_reentry_information",
        readonly=True,
    )

    active_beneficiary_count = fields.Integer(
        string="Vínculos activos como Beneficiario",
        compute="_compute_reentry_information",
        readonly=True,
    )

    blocked_beneficiary_count = fields.Integer(
        string="Vínculos bloqueados como Beneficiario",
        compute="_compute_reentry_information",
        readonly=True,
    )

    effective_date = fields.Date(
        string="Fecha efectiva del Reingreso",
        required=True,
    )

    reason = fields.Text(
        string="Motivo del Reingreso",
        required=True,
    )

    @api.depends("person_id")
    def _compute_reentry_information(self):
        Period = self.env["club.membership.period"]
        Beneficiary = self.env["club.beneficiary"]

        for wizard in self:
            person = wizard.person_id

            wizard.last_membership_end_date = False
            wizard.certificate_id = False
            wizard.certificate_will_reactivate = False
            wizard.active_beneficiary_count = 0
            wizard.blocked_beneficiary_count = 0

            if not person:
                continue

            last_period = Period.search(
                [
                    ("person_id", "=", person.id),
                    ("state", "=", "finalized"),
                ],
                order="end_date desc, id desc",
                limit=1,
            )

            wizard.last_membership_end_date = last_period.end_date

            certificate = person.club_certificate_ids[:1]
            wizard.certificate_id = certificate
            wizard.certificate_will_reactivate = bool(
                certificate
                and certificate.state == "passive"
                and certificate.passive_by_membership_end
            )

            wizard.active_beneficiary_count = Beneficiary.search_count(
                [
                    ("person_id", "=", person.id),
                    ("state", "=", "active"),
                ]
            )

            wizard.blocked_beneficiary_count = Beneficiary.search_count(
                [
                    ("person_id", "=", person.id),
                    ("state", "=", "blocked"),
                ]
            )

    def action_confirm(self):
        self.ensure_one()

        if not self.person_id:
            raise ValidationError(
                self.env._("No se encontró el Ex-Socio que debe Reingresar como Socio.")
            )

        normalized_reason = (self.reason or "").strip()

        if not normalized_reason:
            raise ValidationError(
                self.env._("Debe indicar el motivo del Reingreso como Socio.")
            )

        if not self.effective_date:
            raise ValidationError(
                self.env._("Debe indicar la fecha efectiva del Reingreso como Socio.")
            )

        self.person_id.action_reenter_club_member(
            normalized_reason,
            effective_date=self.effective_date,
        )

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
