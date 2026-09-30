from odoo import fields, models
from odoo.exceptions import ValidationError


class ClubBeneficiaryTransitionWizard(models.TransientModel):
    _name = "club.beneficiary.transition.wizard"
    _description = "Asistente de transición de Beneficiario"

    beneficiary_id = fields.Many2one(
        comodel_name="club.beneficiary",
        string="Registro de Beneficiario",
        required=True,
        readonly=True,
        ondelete="cascade",
    )

    operation = fields.Selection(
        selection=[
            ("finalize", "Finalizar vínculo"),
            ("reassign", "Reasignar / cambiar vínculo"),
        ],
        string="Operación",
        required=True,
        readonly=True,
    )

    person_id = fields.Many2one(
        related="beneficiary_id.person_id",
        string="Persona beneficiaria",
        readonly=True,
    )

    current_member_id = fields.Many2one(
        related="beneficiary_id.member_id",
        string="Socio titular actual",
        readonly=True,
    )

    current_relationship = fields.Selection(
        related="beneficiary_id.relationship",
        string="Vínculo actual",
        readonly=True,
    )

    end_date = fields.Date(
        string="Fecha de finalización",
        required=True,
        default=fields.Date.context_today,
    )

    reason = fields.Text(
        string="Motivo",
        required=True,
    )

    new_member_id = fields.Many2one(
        comodel_name="res.partner",
        string="Nuevo Socio titular",
        domain=[("club_person_type", "=", "member")],
    )

    relationship = fields.Selection(
        selection=[
            ("spouse", "Esposo(a)"),
            ("partner", "Pareja de hecho"),
            ("child", "Hijo(a)"),
            ("stepchild", "Hijastro(a)"),
            ("parent", "Padre o madre"),
            ("sibling", "Hermano(a)"),
            ("worker", "Trabajador"),
            ("other", "Otro vínculo"),
        ],
        string="Nuevo vínculo",
    )

    relationship_detail = fields.Char(
        string="Detalle del nuevo vínculo",
    )

    special_condition = fields.Selection(
        selection=[
            ("none", "Ninguna"),
            (
                "legal_guardianship",
                "Bajo tutela legal del Socio",
            ),
            (
                "health_dependent",
                "Dependiente por condición de salud",
            ),
        ],
        string="Condición especial",
        default="none",
    )

    start_date = fields.Date(
        string="Fecha de inicio del nuevo vínculo",
        default=fields.Date.context_today,
    )

    def action_confirm(self):
        self.ensure_one()

        if not self.beneficiary_id:
            raise ValidationError(
                self.env._("No se encontró el vínculo de Beneficiario.")
            )

        if self.operation == "finalize":
            self.beneficiary_id.finalize_link(
                end_date=self.end_date,
                reason=self.reason,
            )

            return {
                "type": "ir.actions.client",
                "tag": "reload",
            }

        if self.operation != "reassign":
            raise ValidationError(self.env._("La operación solicitada no es válida."))

        if not self.new_member_id:
            raise ValidationError(
                self.env._("Debe seleccionar el nuevo Socio titular.")
            )

        if not self.relationship:
            raise ValidationError(self.env._("Debe seleccionar el nuevo vínculo."))

        if not self.start_date:
            raise ValidationError(
                self.env._("Debe indicar la fecha de inicio del nuevo vínculo.")
            )

        new_link = self.beneficiary_id.reassign_link(
            {
                "new_member_id": self.new_member_id.id,
                "relationship": self.relationship,
                "relationship_detail": self.relationship_detail,
                "special_condition": (self.special_condition or "none"),
                "end_date": self.end_date,
                "start_date": self.start_date,
                "reason": self.reason,
            }
        )

        return {
            "type": "ir.actions.act_window",
            "name": self.env._("Beneficiario"),
            "res_model": "club.beneficiary",
            "res_id": new_link.id,
            "view_mode": "form",
            "views": [
                (
                    self.env.ref("club_membership.view_club_beneficiary_form").id,
                    "form",
                )
            ],
            "target": "current",
        }
