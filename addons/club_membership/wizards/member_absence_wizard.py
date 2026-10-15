from odoo import fields, models
from odoo.exceptions import ValidationError


class ClubMemberAbsenceWizard(models.TransientModel):
    _name = "club.member.absence.wizard"
    _description = "Asistente para registrar ausencia de Socio"

    member_id = fields.Many2one(
        comodel_name="res.partner",
        string="Socio",
        required=True,
        readonly=True,
        ondelete="cascade",
        domain=[
            ("club_person_type", "=", "member"),
            ("club_member_state", "=", "active"),
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

    effective_date = fields.Date(
        string="Fecha efectiva de ausencia",
        required=True,
        default=fields.Date.context_today,
    )

    expected_return_date = fields.Date(
        string="Fecha prevista de retorno",
        required=False,
    )

    reason = fields.Text(
        string="Motivo de la ausencia",
        required=True,
    )

    def action_confirm(self):
        self.ensure_one()

        if not self.member_id:
            raise ValidationError(self.env._("Debe identificar al Socio."))

        self.member_id.action_mark_club_member_absent(
            self.reason,
            effective_date=self.effective_date,
            expected_return_date=self.expected_return_date,
        )

        return {"type": "ir.actions.act_window_close"}
