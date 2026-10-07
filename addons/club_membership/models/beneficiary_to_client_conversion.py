from odoo import fields, models
from odoo.exceptions import AccessError, ValidationError

_CLUB_BENEFICIARY_TO_CLIENT_INTERNAL_TOKEN = object()


class ClubBeneficiaryToClientConversion(models.Model):
    _inherit = "club.beneficiary"

    def _check_club_beneficiary_to_client_permission(self):
        if not self.env.user.has_group(
            "club_membership.group_club_beneficiary_to_client"
        ):
            raise AccessError(
                self.env._(
                    "No tiene permiso para convertir un Beneficiario en Cliente."
                )
            )

    def _check_club_beneficiary_to_client_preconditions(self):
        self.ensure_one()

        person = self.person_id.exists()

        if not person:
            raise ValidationError(
                self.env._(
                    "No se encontró la Persona asociada al vínculo de Beneficiario."
                )
            )

        if self.state not in ("active", "blocked", "finalized"):
            raise ValidationError(
                self.env._(
                    "El estado del vínculo de Beneficiario no permite "
                    "la conversión a Cliente."
                )
            )

        if self.converted_member_id:
            raise ValidationError(
                self.env._(
                    "Este vínculo ya registra una conversión a Socio y no puede "
                    "utilizarse para convertir la Persona en Cliente."
                )
            )

        if person.is_company:
            raise ValidationError(
                self.env._(
                    "La Persona de un vínculo de Beneficiario debe ser individual "
                    "para convertirse en Cliente mediante este proceso."
                )
            )

        if person.club_person_type == "client":
            raise ValidationError(
                self.env._("Esta Persona ya tiene actualmente la condición de Cliente.")
            )

        if person.club_person_type == "member":
            raise ValidationError(
                self.env._(
                    "Una Persona que actualmente conserva la condición de Socio "
                    "no puede convertirse en Cliente mediante este proceso."
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

        if current_period:
            raise ValidationError(
                self.env._(
                    "La Persona presenta un período de membresía vigente "
                    "incompatible con la conversión de Beneficiario a Cliente."
                )
            )

        finalized_period = Period.search(
            [
                ("person_id", "=", person.id),
                ("state", "=", "finalized"),
            ],
            limit=1,
        )

        if finalized_period:
            raise ValidationError(
                self.env._(
                    "Esta Persona posee historia real como Ex-Socio. "
                    "La conversión Ex-Socio a Cliente requiere un proceso "
                    "controlado específico y no debe realizarse mediante "
                    "Beneficiario a Cliente."
                )
            )

        current_links = self.search(
            [
                ("person_id", "=", person.id),
                ("state", "in", ("active", "blocked")),
            ]
        )

        if self.state == "finalized" and current_links:
            raise ValidationError(
                self.env._(
                    "Esta Persona posee actualmente otro vínculo vigente como "
                    "Beneficiario. La conversión debe realizarse desde el vínculo "
                    "vigente correspondiente."
                )
            )

        other_current_links = current_links.filtered(lambda link: link != self)

        if other_current_links:
            raise ValidationError(
                self.env._(
                    "Esta Persona posee otro vínculo vigente como Beneficiario. "
                    "Debe resolver primero ese vínculo antes de convertirla "
                    "en Cliente."
                )
            )

        return person

    def action_open_club_beneficiary_to_client_wizard(self):
        self.ensure_one()
        self._check_club_beneficiary_to_client_permission()
        self._check_club_beneficiary_to_client_preconditions()

        return {
            "type": "ir.actions.act_window",
            "name": self.env._("Convertir Beneficiario en Cliente"),
            "res_model": "club.beneficiary.to.client.wizard",
            "view_mode": "form",
            "views": [
                (
                    self.env.ref(
                        "club_membership.view_club_beneficiary_to_client_wizard_form"
                    ).id,
                    "form",
                )
            ],
            "target": "new",
            "context": {
                "default_beneficiary_id": self.id,
            },
        }

    def action_convert_beneficiary_to_client(self, conversion_vals=None):
        self.ensure_one()
        self._check_club_beneficiary_to_client_permission()

        conversion_vals = dict(conversion_vals or {})

        person = self._check_club_beneficiary_to_client_preconditions()

        was_finalized = self.state == "finalized"
        effective_date = False
        reason = False

        if not was_finalized:
            end_date = conversion_vals.get("end_date")

            if not end_date:
                raise ValidationError(
                    self.env._(
                        "Debe indicar la fecha de finalización del vínculo "
                        "de Beneficiario."
                    )
                )

            effective_date = fields.Date.to_date(end_date)

            if not effective_date:
                raise ValidationError(
                    self.env._("Debe indicar una fecha de finalización válida.")
                )

            today = fields.Date.context_today(self)

            if effective_date > today:
                raise ValidationError(
                    self.env._(
                        "La fecha de finalización del vínculo no puede ser futura."
                    )
                )

            reason = self._validate_transition_reason(conversion_vals.get("reason"))

        with self.env.cr.savepoint():
            if not was_finalized:
                self.finalize_link(
                    end_date=effective_date,
                    reason=reason,
                )

            conversion_person = person.with_context(
                club_beneficiary_to_client_internal_token=(
                    _CLUB_BENEFICIARY_TO_CLIENT_INTERNAL_TOKEN
                )
            )

            conversion_person.write(
                {
                    "club_person_type": "client",
                }
            )

        return person.id


class ResPartnerBeneficiaryToClientProtection(models.Model):
    _inherit = "res.partner"

    def _is_club_beneficiary_to_client_internal_write(self):
        return (
            self.env.context.get("club_beneficiary_to_client_internal_token")
            is _CLUB_BENEFICIARY_TO_CLIENT_INTERNAL_TOKEN
        )

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
            and not self._is_club_beneficiary_to_client_internal_write()
        ):
            beneficiary_history = self.env["club.beneficiary"].search(
                [
                    ("person_id", "=", partner.id),
                ],
                limit=1,
            )

            if beneficiary_history:
                raise ValidationError(
                    self.env._(
                        "Una Persona con historial de Beneficiario no puede "
                        "convertirse en Cliente mediante edición directa. "
                        "Debe utilizar el proceso controlado de conversión "
                        "Beneficiario a Cliente."
                    )
                )

        return super()._prepare_club_member_write_vals(
            partner,
            vals,
        )
