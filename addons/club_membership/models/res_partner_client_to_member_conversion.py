from odoo import models
from odoo.exceptions import AccessError, ValidationError

_CLUB_CLIENT_TO_MEMBER_INTERNAL_TOKEN = object()


class ResPartnerClientToMemberConversion(models.Model):
    _inherit = "res.partner"  # pylint: disable=consider-merging-classes-inherited

    def _is_club_client_to_member_internal_write(self):
        return (
            self.env.context.get("club_client_to_member_internal_token")
            is _CLUB_CLIENT_TO_MEMBER_INTERNAL_TOKEN
        )

    def _check_club_client_to_member_permission(self):
        if not self.env.user.has_group("club_membership.group_club_client_to_member"):
            raise AccessError(
                self.env._("No tiene permiso para convertir un Cliente en Socio.")
            )

    def action_open_club_client_to_member_wizard(self):
        self.ensure_one()
        self._check_club_client_to_member_permission()

        if self.club_person_type != "client":
            raise ValidationError(
                self.env._(
                    "La conversión a Socio solo puede iniciarse "
                    "desde una Persona que actualmente sea Cliente."
                )
            )

        return {
            "type": "ir.actions.act_window",
            "name": self.env._("Convertir Cliente en Socio"),
            "res_model": "club.client.to.member.wizard",
            "view_mode": "form",
            "views": [
                (
                    self.env.ref(
                        "club_membership.view_club_client_to_member_wizard_form"
                    ).id,
                    "form",
                )
            ],
            "target": "new",
            "context": {
                "default_person_id": self.id,
            },
        }

    def action_convert_client_to_member(
        self,
        reason=False,
        effective_date=False,
    ):
        self.ensure_one()
        self._check_club_client_to_member_permission()

        if self.club_person_type != "client":
            raise ValidationError(
                self.env._(
                    "La conversión a Socio solo puede aplicarse "
                    "a una Persona que actualmente sea Cliente."
                )
            )

        Period = self.env["club.membership.period"]

        current_period = Period.search(
            [
                ("person_id", "=", self.id),
                ("state", "=", "current"),
            ],
            limit=1,
        )

        if current_period:
            raise ValidationError(
                self.env._(
                    "La Persona Cliente presenta un período de membresía "
                    "vigente y no puede convertirse nuevamente en Socio."
                )
            )

        finalized_period = Period.search(
            [
                ("person_id", "=", self.id),
                ("state", "=", "finalized"),
            ],
            limit=1,
        )

        conversion_partner = self.with_context(
            club_client_to_member_internal_token=(_CLUB_CLIENT_TO_MEMBER_INTERNAL_TOKEN)
        )

        if finalized_period:
            # Reutiliza el motor protegido de MEM-15 sin pasar por
            # la acción pública de Reingreso, que correctamente exige
            # que el Ex-Socio no posea rol Cliente.
            # pylint: disable=protected-access
            return conversion_partner._execute_club_member_reentry(
                reason,
                effective_date=effective_date,
                allow_client_role=True,
            )
            # pylint: enable=protected-access

        conversion_partner.write(
            {
                "club_person_type": "member",
            }
        )

        return True

    def _prepare_club_member_write_vals(
        self,
        partner,
        vals,
    ):
        new_person_type = vals.get(
            "club_person_type",
            partner.club_person_type,
        )

        if (
            partner.club_person_type == "client"
            and new_person_type == "member"
            and not self._is_club_client_to_member_internal_write()
        ):
            raise ValidationError(
                self.env._(
                    "Un Cliente no puede convertirse en Socio mediante "
                    "edición directa. Debe utilizar la acción controlada "
                    "Convertir Cliente en Socio."
                )
            )

        return super()._prepare_club_member_write_vals(
            partner,
            vals,
        )
