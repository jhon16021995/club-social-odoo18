from odoo import api, fields, models
from odoo.exceptions import ValidationError


class ResPartnerMemberLifetime(models.Model):
    _inherit = "res.partner"

    club_ordinary_contributions_historical_paid = fields.Integer(
        string="Aportes Ordinarios Pagados históricos",
        default=0,
        copy=False,
    )

    club_ordinary_contributions_paid_total = fields.Integer(
        string="Total de Aportes Ordinarios Pagados",
        compute="_compute_club_ordinary_contributions_paid_total",
    )

    club_lifetime_eligible = fields.Boolean(
        string="Cumple requisitos para Vitalicio",
        compute="_compute_club_lifetime_eligible",
    )

    @api.depends("club_ordinary_contributions_historical_paid")
    def _compute_club_ordinary_contributions_paid_total(self):
        for partner in self:
            partner.club_ordinary_contributions_paid_total = (
                partner.club_ordinary_contributions_historical_paid or 0
            )

    @api.depends(
        "club_birthdate",
        "club_ordinary_contributions_historical_paid",
    )
    def _compute_club_lifetime_eligible(self):
        for partner in self:
            partner.club_lifetime_eligible = (
                bool(partner.club_birthdate)
                and partner.club_age >= 60
                and partner.club_ordinary_contributions_paid_total >= 360
            )

    @api.constrains("club_ordinary_contributions_historical_paid")
    def _check_club_ordinary_contributions_historical_paid(self):
        for partner in self:
            if partner.club_ordinary_contributions_historical_paid < 0:
                raise ValidationError(
                    self.env._(
                        "Los Aportes Ordinarios Pagados históricos "
                        "no pueden ser negativos."
                    )
                )

    @api.constrains(
        "club_member_state",
        "club_birthdate",
        "club_ordinary_contributions_historical_paid",
    )
    def _check_club_lifetime_requirements(self):
        for partner in self:
            if (
                partner.club_member_state == "lifetime"
                and not partner.club_lifetime_eligible
            ):
                raise ValidationError(
                    self.env._(
                        "Un Socio solo puede ser Vitalicio cuando posee "
                        "al menos 360 Aportes Ordinarios Pagados y tiene "
                        "60 años de edad o más."
                    )
                )

    def _log_club_kardex_event(
        self,
        member,
        event_type,
        description,
        **event_data,
    ):
        if event_type in {
            "member_created",
            "member_created_from_beneficiary",
        }:
            contribution_line = self.env._(
                "Aportes Ordinarios Pagados históricos: %(contributions)s",
                contributions=(member.club_ordinary_contributions_historical_paid),
            )
            current_value = event_data.get("new_value") or ""
            event_data["new_value"] = (
                f"{current_value}\n{contribution_line}"
                if current_value
                else contribution_line
            )

        return super()._log_club_kardex_event(
            member,
            event_type,
            description,
            **event_data,
        )

    def write(self, vals):
        contribution_field = "club_ordinary_contributions_historical_paid"

        if contribution_field not in vals:
            return super().write(vals)

        previous_values = {
            partner.id: (
                partner.club_person_type == "member",
                partner.club_ordinary_contributions_historical_paid,
            )
            for partner in self
        }

        result = super().write(vals)

        for partner in self:
            was_member, old_value = previous_values[partner.id]
            new_value = partner.club_ordinary_contributions_historical_paid

            if (
                was_member
                and partner.club_person_type == "member"
                and old_value != new_value
            ):
                self._log_club_kardex_event(
                    partner,
                    "member_historical_contributions_changed",
                    self.env._("Aportes Ordinarios Pagados históricos actualizados."),
                    old_value=str(old_value),
                    new_value=str(new_value),
                    origin="manual",
                )

        return result
