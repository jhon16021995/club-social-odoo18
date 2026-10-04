from odoo import api, fields, models
from odoo.exceptions import ValidationError


class ClubMemberRegistrationCorrectionWizard(models.TransientModel):
    _name = "club.member.registration.correction.wizard"
    _description = "Asistente de corrección de alta errónea de Socio"

    member_id = fields.Many2one(
        comodel_name="res.partner",
        string="Persona registrada erróneamente como Socio",
        required=True,
        readonly=True,
        ondelete="cascade",
    )

    id_number = fields.Char(
        related="member_id.club_id_number",
        string="Carnet",
        readonly=True,
    )

    member_code = fields.Char(
        related="member_id.club_member_code",
        string="Código de asociado",
        readonly=True,
    )

    current_member_state = fields.Selection(
        related="member_id.club_member_state",
        string="Estado actual del asociado",
        readonly=True,
    )

    certificate_id = fields.Many2one(
        comodel_name="club.certificate",
        string="Certificado Patrimonial",
        compute="_compute_certificate_id",
        readonly=True,
    )

    current_beneficiary_count = fields.Integer(
        string="Beneficiarios vigentes a cargo",
        compute="_compute_current_beneficiary_count",
        readonly=True,
    )

    target_member_id = fields.Many2one(
        comodel_name="res.partner",
        string="Socio titular correcto",
        required=True,
        domain=[("club_person_type", "=", "member")],
    )

    relationship = fields.Selection(
        selection=[
            ("spouse", "Esposo(a)"),
            ("partner", "Pareja de hecho"),
            ("child", "Hijo(a)"),
            ("stepchild", "Hijastro(a)"),
            ("parent", "Padre o madre"),
            ("worker", "Trabajador"),
            (
                "family_dependent",
                "Familiar dependiente",
            ),
        ],
        string="Vínculo con el Socio",
        required=True,
    )

    relationship_detail = fields.Char(
        string="Detalle del vínculo",
    )

    special_condition = fields.Selection(
        selection=[
            ("none", "Ninguna"),
            (
                "health_dependent",
                "Dependiente por condición de salud",
            ),
        ],
        string="Condición especial",
        required=True,
        default="none",
    )

    start_date = fields.Date(
        string="Fecha de inicio del vínculo",
        required=True,
        default=fields.Date.context_today,
    )

    reason = fields.Text(
        string="Motivo de la corrección",
        required=True,
    )

    @api.depends("member_id")
    def _compute_certificate_id(self):
        for wizard in self:
            wizard.certificate_id = wizard.member_id.club_certificate_ids[:1]

    @api.depends("member_id")
    def _compute_current_beneficiary_count(self):
        beneficiary_model = self.env["club.beneficiary"]

        for wizard in self:
            if not wizard.member_id:
                wizard.current_beneficiary_count = 0
                continue

            wizard.current_beneficiary_count = beneficiary_model.search_count(
                [
                    (
                        "member_id",
                        "=",
                        wizard.member_id.id,
                    ),
                    (
                        "state",
                        "in",
                        ("active", "blocked"),
                    ),
                ]
            )

    @api.onchange("relationship")
    def _onchange_relationship(self):
        if self.relationship != "family_dependent":
            self.relationship_detail = False

    def action_confirm(self):
        self.ensure_one()

        if not self.member_id:
            raise ValidationError(
                self.env._("No se encontró la Persona que debe corregirse.")
            )

        if self.current_beneficiary_count:
            raise ValidationError(
                self.env._(
                    "No se puede continuar porque este Socio "
                    "tiene %(count)s Beneficiario(s) vigente(s) "
                    "a su cargo. Debe finalizarlos manualmente "
                    "antes de realizar la corrección.",
                    count=self.current_beneficiary_count,
                )
            )

        if not self.target_member_id:
            raise ValidationError(
                self.env._("Debe seleccionar el Socio titular correcto.")
            )

        if not self.relationship:
            raise ValidationError(
                self.env._("Debe seleccionar el vínculo del Beneficiario.")
            )

        relationship_detail = (self.relationship_detail or "").strip()

        if self.relationship == "family_dependent" and not relationship_detail:
            raise ValidationError(
                self.env._(
                    "Debe indicar el detalle cuando el vínculo "
                    "sea Familiar dependiente."
                )
            )

        reason = (self.reason or "").strip()

        if not reason:
            raise ValidationError(
                self.env._("Debe indicar el motivo de la corrección.")
            )

        beneficiary, _correction = (
            self.member_id.correct_member_registration_error_to_beneficiary(
                self.target_member_id,
                {
                    "relationship": self.relationship,
                    "relationship_detail": relationship_detail,
                    "special_condition": (self.special_condition or "none"),
                    "start_date": self.start_date,
                    "reason": reason,
                },
            )
        )

        return {
            "type": "ir.actions.act_window",
            "name": self.env._("Beneficiario"),
            "res_model": "club.beneficiary",
            "res_id": beneficiary.id,
            "view_mode": "form",
            "views": [
                (
                    self.env.ref("club_membership.view_club_beneficiary_form").id,
                    "form",
                )
            ],
            "target": "current",
        }
