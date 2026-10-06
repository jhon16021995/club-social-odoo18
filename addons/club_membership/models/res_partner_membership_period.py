from odoo import api, fields, models
from odoo.exceptions import ValidationError


class ResPartnerMembershipPeriod(models.Model):
    # Esta extensión se mantiene separada intencionalmente de la capa
    # principal de res.partner y de la corrección de alta errónea.
    # La separación conserva responsabilidades y permite que la capa
    # de corrección controlada permanezca al final del orden de carga.
    _inherit = "res.partner"  # pylint: disable=consider-merging-classes-inherited

    club_membership_period_ids = fields.One2many(
        comodel_name="club.membership.period",
        inverse_name="person_id",
        string="Períodos de membresía",
        readonly=True,
    )

    club_is_former_member = fields.Boolean(
        string="Ex-Socio",
        compute="_compute_club_is_former_member",
        store=True,
        index=True,
        readonly=True,
    )

    @api.depends(
        "club_person_type",
        "club_membership_period_ids.state",
    )
    def _compute_club_is_former_member(self):
        for partner in self:
            period_states = set(partner.club_membership_period_ids.mapped("state"))

            partner.club_is_former_member = (
                partner.club_person_type != "member"
                and "current" not in period_states
                and "finalized" in period_states
            )

    def _create_initial_membership_period(self):
        self.ensure_one()

        if self.club_person_type != "member":
            return self.env["club.membership.period"]

        Period = self.env["club.membership.period"]

        real_history = Period.search(
            [
                ("person_id", "=", self.id),
                ("state", "in", ("current", "finalized")),
            ],
            limit=1,
        )

        if real_history:
            raise ValidationError(
                self.env._(
                    "No puede generarse un alta inicial de Socio "
                    "porque la Persona ya posee un período real "
                    "de membresía."
                )
            )

        return Period._create_period_internal(  # pylint: disable=protected-access
            {
                "person_id": self.id,
                "start_date": self.club_join_date,
                "origin": "initial",
                "member_code": self.club_member_code,
            }
        )

    @api.model_create_multi
    def create(self, vals_list):
        partners = super().create(vals_list)

        for partner in partners:
            if partner.club_person_type == "member":
                # Helper protegido perteneciente a esta capa histórica.
                # pylint: disable=protected-access
                partner._create_initial_membership_period()
                # pylint: enable=protected-access

        return partners

    def write(self, vals):
        previous_member_ids = set(
            self.filtered(lambda partner: partner.club_person_type == "member").ids
        )

        result = super().write(vals)

        for partner in self:
            became_member = (
                partner.id not in previous_member_ids
                and partner.club_person_type == "member"
            )

            if became_member:
                # Helper protegido perteneciente a esta capa histórica.
                # pylint: disable=protected-access
                partner._create_initial_membership_period()
                # pylint: enable=protected-access

        return result
