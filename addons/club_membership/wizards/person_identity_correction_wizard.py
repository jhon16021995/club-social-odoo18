from odoo import api, fields, models
from odoo.exceptions import ValidationError


class ClubPersonIdentityCorrectionWizard(models.TransientModel):
    _name = "club.person.identity.correction.wizard"
    _description = "Asistente de corrección de identidad de Persona"

    person_id = fields.Many2one(
        comodel_name="res.partner",
        string="Persona",
        required=True,
        readonly=True,
        ondelete="cascade",
    )

    field_name = fields.Selection(
        selection=[
            ("name", "Nombre / Razón social"),
            ("club_id_number", "Número de carnet"),
            ("club_id_extension", "Extensión del carnet"),
            ("club_birthdate", "Fecha de nacimiento"),
        ],
        string="Dato a corregir",
        required=True,
    )

    current_value = fields.Char(
        string="Valor actual",
        compute="_compute_current_value",
        readonly=True,
    )

    new_text_value = fields.Char(
        string="Nuevo valor de texto",
    )

    new_birthdate_value = fields.Date(
        string="Nueva fecha de nacimiento",
    )

    reason = fields.Text(
        string="Motivo de la corrección",
        required=True,
    )

    @api.depends(
        "person_id",
        "field_name",
    )
    def _compute_current_value(self):
        for wizard in self:
            wizard.current_value = False

            if not wizard.person_id or not wizard.field_name:
                continue

            value = wizard.person_id[wizard.field_name]

            if not value:
                wizard.current_value = self.env._("Sin valor")
                continue

            if wizard.field_name == "club_birthdate":
                wizard.current_value = fields.Date.to_string(value)
                continue

            wizard.current_value = str(value)

    def _get_new_value(self):
        self.ensure_one()

        if self.field_name == "club_birthdate":
            return self.new_birthdate_value

        return self.new_text_value

    def action_confirm(self):
        self.ensure_one()

        if not self.person_id:
            raise ValidationError(
                self.env._("No se encontró la Persona que debe corregirse.")
            )

        if not self.field_name:
            raise ValidationError(
                self.env._("Debe seleccionar el dato que desea corregir.")
            )

        reason = (self.reason or "").strip()

        if not reason:
            raise ValidationError(
                self.env._("Debe indicar el motivo de la corrección.")
            )

        self.person_id.correct_sensitive_identity(
            self.field_name,
            self._get_new_value(),
            reason,
        )

        return {
            "type": "ir.actions.client",
            "tag": "reload",
        }
