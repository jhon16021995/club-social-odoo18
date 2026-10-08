from odoo import models
from odoo.exceptions import AccessError, ValidationError

_CLUB_FORMER_MEMBER_TO_CLIENT_INTERNAL_TOKEN = object()


class ClubKardexFormerMemberToClient(models.Model):
    _inherit = "club.kardex.event"  # pylint: disable=consider-merging-classes-inherited

    def _log_former_member_to_client_event(self, person, reason):
        person.ensure_one()

        normalized_reason = (reason or "").strip()
        if not normalized_reason:
            raise ValidationError(
                self.env._(
                    "Debe indicar el motivo de la conversión de Ex-Socio a Cliente."
                )
            )

        Period = self.env["club.membership.period"]

        current_period = Period.search(
            [
                ("person_id", "=", person.id),
                ("state", "=", "current"),
            ],
            limit=1,
        )

        finalized_period = Period.search(
            [
                ("person_id", "=", person.id),
                ("state", "=", "finalized"),
            ],
            limit=1,
        )

        if (
            person.club_person_type != "client"
            or current_period
            or not finalized_period
        ):
            raise ValidationError(
                self.env._(
                    "El evento Ex-Socio convertido en Cliente solo puede "
                    "registrarse para una Persona con historia real de "
                    "membresía finalizada, sin período vigente y cuya "
                    "condición actual sea Cliente."
                )
            )

        vals = {
            "member_id": person.id,
            "user_id": self.env.user.id,
            "event_type": "former_member_converted_to_client",
            "description": self.env._("Conversión controlada de Ex-Socio a Cliente."),
            "old_value": self.env._("Condición institucional: Ex-Socio"),
            "new_value": self.env._("Cliente"),
            "reason": normalized_reason,
            "origin": "manual",
        }

        return self.sudo().with_context(club_kardex_internal_create=True).create(vals)


class ResPartnerFormerMemberToClientConversion(models.Model):
    _inherit = "res.partner"  # pylint: disable=consider-merging-classes-inherited

    def _is_club_former_member_to_client_internal_write(self):
        return (
            self.env.context.get("club_former_member_to_client_internal_token")
            is _CLUB_FORMER_MEMBER_TO_CLIENT_INTERNAL_TOKEN
        )

    def _check_club_former_member_to_client_permission(self):
        if not self.env.user.has_group(
            "club_membership.group_club_former_member_to_client"
        ):
            raise AccessError(
                self.env._("No tiene permiso para convertir un Ex-Socio en Cliente.")
            )

    def _normalize_club_former_member_to_client_reason(self, reason):
        normalized_reason = (reason or "").strip()

        if not normalized_reason:
            raise ValidationError(
                self.env._(
                    "Debe indicar el motivo de la conversión de Ex-Socio a Cliente."
                )
            )

        return normalized_reason

    def _check_club_former_member_to_client_preconditions(self):
        self.ensure_one()

        if self.club_person_type == "client":
            raise ValidationError(
                self.env._("Esta Persona ya tiene actualmente la condición de Cliente.")
            )

        if self.club_person_type == "member":
            raise ValidationError(
                self.env._(
                    "Una Persona que actualmente conserva la condición de Socio "
                    "no puede utilizar la conversión Ex-Socio a Cliente."
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
                    "La Persona presenta un período de membresía vigente. "
                    "Debe corregirse esa inconsistencia antes de convertirla "
                    "en Cliente."
                )
            )

        finalized_period = Period.search(
            [
                ("person_id", "=", self.id),
                ("state", "=", "finalized"),
            ],
            limit=1,
        )

        if not finalized_period:
            raise ValidationError(
                self.env._(
                    "La Persona no posee una membresía legítima finalizada "
                    "y por tanto no cumple la condición de Ex-Socio requerida "
                    "para este proceso."
                )
            )

        current_beneficiary_link = self.env["club.beneficiary"].search(
            [
                ("person_id", "=", self.id),
                ("state", "in", ("active", "blocked")),
            ],
            limit=1,
        )

        if current_beneficiary_link:
            raise ValidationError(
                self.env._(
                    "Esta Persona posee actualmente un vínculo vigente como "
                    "Beneficiario. Debe Finalizar primero ese vínculo antes "
                    "de convertir el Ex-Socio en Cliente."
                )
            )

        return finalized_period

    def action_open_club_former_member_to_client_wizard(self):
        self.ensure_one()
        self._check_club_former_member_to_client_permission()
        self._check_club_former_member_to_client_preconditions()

        return {
            "type": "ir.actions.act_window",
            "name": self.env._("Convertir Ex-Socio en Cliente"),
            "res_model": "club.former.member.to.client.wizard",
            "view_mode": "form",
            "views": [
                (
                    self.env.ref(
                        "club_membership.view_club_former_member_to_client_wizard_form"
                    ).id,
                    "form",
                )
            ],
            "target": "new",
            "context": {
                "default_person_id": self.id,
            },
        }

    def action_convert_former_member_to_client(self, reason=False):
        self.ensure_one()
        self._check_club_former_member_to_client_permission()

        normalized_reason = self._normalize_club_former_member_to_client_reason(reason)

        self._check_club_former_member_to_client_preconditions()

        with self.env.cr.savepoint():
            conversion_partner = self.with_context(
                club_former_member_to_client_internal_token=(
                    _CLUB_FORMER_MEMBER_TO_CLIENT_INTERNAL_TOKEN
                )
            )

            conversion_partner.write(
                {
                    "club_person_type": "client",
                }
            )

            self.invalidate_recordset()

            kardex = self.env["club.kardex.event"]
            kardex._log_former_member_to_client_event(  # pylint: disable=protected-access
                self,
                normalized_reason,
            )

        return self.id

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
            new_person_type == "client"
            and partner.club_person_type not in ("client", "member")
            and not self._is_club_former_member_to_client_internal_write()
        ):
            Period = self.env["club.membership.period"]

            current_period = Period.search(
                [
                    ("person_id", "=", partner.id),
                    ("state", "=", "current"),
                ],
                limit=1,
            )

            if current_period:
                raise ValidationError(
                    self.env._(
                        "Una Persona con un período de membresía vigente "
                        "no puede convertirse en Cliente mediante edición directa."
                    )
                )

            finalized_period = Period.search(
                [
                    ("person_id", "=", partner.id),
                    ("state", "=", "finalized"),
                ],
                limit=1,
            )

            if finalized_period:
                raise ValidationError(
                    self.env._(
                        "Un Ex-Socio no puede convertirse en Cliente mediante "
                        "edición directa. Debe utilizar la acción controlada "
                        "Convertir Ex-Socio en Cliente."
                    )
                )

        return super()._prepare_club_member_write_vals(
            partner,
            vals,
        )
