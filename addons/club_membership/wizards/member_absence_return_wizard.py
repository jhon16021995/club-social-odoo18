from odoo import fields, models
from odoo.exceptions import ValidationError


class ClubMemberAbsenceReturnWizard(models.TransientModel):
    _name = "club.member.absence.return.wizard"
    _description = "Asistente para registrar retorno de Socio Ausente"

    member_id = fields.Many2one(
        comodel_name="res.partner",
        string="Socio",
        required=True,
        readonly=True,
        ondelete="cascade",
        domain=[
            ("club_person_type", "=", "member"),
            ("club_member_state", "=", "absent"),
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

    expected_return_date = fields.Date(
        related="member_id.club_absence_expected_return_date",
        string="Retorno previsto anteriormente",
        readonly=True,
    )

    effective_date = fields.Date(
        string="Fecha efectiva de retorno",
        required=True,
        default=fields.Date.context_today,
    )

    reason = fields.Text(
        string="Motivo del retorno",
        required=True,
    )

    def action_confirm(self):
        self.ensure_one()

        if not self.member_id:
            raise ValidationError(self.env._("Debe identificar al Socio."))

        self.member_id.action_return_club_member_from_absence(
            self.reason,
            effective_date=self.effective_date,
        )

        return {"type": "ir.actions.act_window_close"}
