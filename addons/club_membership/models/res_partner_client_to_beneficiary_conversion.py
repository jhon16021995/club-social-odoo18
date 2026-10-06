from odoo import fields, models
from odoo.exceptions import AccessError, ValidationError

_CLUB_CLIENT_TO_BENEFICIARY_INTERNAL_TOKEN = object()


class ResPartnerClientToBeneficiaryConversion(models.Model):
    _inherit = "res.partner"  # pylint: disable=consider-merging-classes-inherited

    def _is_club_client_to_beneficiary_internal_write(self):
        return (
            self.env.context.get("club_client_to_beneficiary_internal_token")
            is _CLUB_CLIENT_TO_BENEFICIARY_INTERNAL_TOKEN
        )

    def _check_club_client_to_beneficiary_permission(self):
        if not self.env.user.has_group(
            "club_membership.group_club_client_to_beneficiary"
        ):
            raise AccessError(
                self.env._(
                    "No tiene permiso para convertir un Cliente en Beneficiario."
                )
            )

    def action_open_club_client_to_beneficiary_wizard(self):
        self.ensure_one()
        self._check_club_client_to_beneficiary_permission()

        if self.club_person_type != "client":
            raise ValidationError(
                self.env._(
                    "La conversión a Beneficiario solo puede iniciarse "
                    "desde una Persona que actualmente sea Cliente."
                )
            )

        if self.is_company:
            raise ValidationError(
                self.env._(
                    "Una empresa Cliente no puede convertirse en "
                    "Beneficiario. El Beneficiario debe ser una "
                    "persona individual."
                )
            )

        return {
            "type": "ir.actions.act_window",
            "name": self.env._("Convertir Cliente en Beneficiario"),
            "res_model": "club.client.to.beneficiary.wizard",
            "view_mode": "form",
            "views": [
                (
                    self.env.ref(
                        "club_membership.view_club_client_to_beneficiary_wizard_form"
                    ).id,
                    "form",
                )
            ],
            "target": "new",
            "context": {
                "default_person_id": self.id,
            },
        }

    def action_convert_client_to_beneficiary(
        self,
        conversion_vals,
    ):
        self.ensure_one()
        self._check_club_client_to_beneficiary_permission()

        conversion_vals = dict(conversion_vals or {})

        member_id = conversion_vals.pop(
            "member_id",
            False,
        )

        member = self.env["res.partner"]

        if (
            isinstance(member_id, int)
            and not isinstance(member_id, bool)
            and member_id > 0
        ):
            member = self.env["res.partner"].browse(member_id).exists()

        conversion_vals["member"] = member

        beneficiary = self._execute_club_client_to_beneficiary_conversion(
            conversion_vals
        )

        return beneficiary.id

    def _check_club_client_to_beneficiary_preconditions(
        self,
        member,
    ):
        self.ensure_one()

        if self.club_person_type != "client":
            raise ValidationError(
                self.env._(
                    "La conversión a Beneficiario solo puede aplicarse "
                    "a una Persona que actualmente sea Cliente."
                )
            )

        if self.is_company:
            raise ValidationError(
                self.env._(
                    "Una empresa Cliente no puede convertirse en "
                    "Beneficiario. El Beneficiario debe ser una "
                    "persona individual."
                )
            )

        if not member or len(member) != 1:
            raise ValidationError(
                self.env._("Debe seleccionar un Socio titular válido.")
            )

        member = member.exists()

        if not member:
            raise ValidationError(
                self.env._("Debe seleccionar un Socio titular válido.")
            )

        if member.club_person_type != "member":
            raise ValidationError(
                self.env._(
                    "El titular del nuevo vínculo debe tener la condición de Socio."
                )
            )

        if member == self:
            raise ValidationError(
                self.env._(
                    "Una Persona no puede registrarse como Beneficiario de sí misma."
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
                    "vigente inconsistente y no puede convertirse en "
                    "Beneficiario."
                )
            )

        finalized_period = Period.search(
            [
                ("person_id", "=", self.id),
                ("state", "=", "finalized"),
            ],
            limit=1,
        )

        if finalized_period:
            raise ValidationError(
                self.env._(
                    "Este Cliente posee historia real como Ex-Socio. "
                    "La conversión de un Ex-Socio a Beneficiario requiere "
                    "un proceso controlado específico y todavía no debe "
                    "realizarse mediante Cliente a Beneficiario."
                )
            )

        current_beneficiary = self.env["club.beneficiary"].search(
            [
                ("person_id", "=", self.id),
                ("state", "in", ("active", "blocked")),
            ],
            limit=1,
        )

        if current_beneficiary:
            raise ValidationError(
                self.env._(
                    "La Persona Cliente ya presenta un vínculo vigente "
                    "como Beneficiario. Debe resolver primero esa "
                    "inconsistencia."
                )
            )

        return True

    def _execute_club_client_to_beneficiary_conversion(
        self,
        conversion_vals,
    ):
        self.ensure_one()

        conversion_vals = dict(conversion_vals or {})

        member = conversion_vals.get("member")
        relationship = conversion_vals.get("relationship")
        start_date = conversion_vals.get("start_date")
        special_condition = conversion_vals.get(
            "special_condition",
            "none",
        )
        relationship_detail = conversion_vals.get(
            "relationship_detail",
        )
        observations = conversion_vals.get(
            "observations",
        )

        self._check_club_client_to_beneficiary_preconditions(member)

        effective_date = fields.Date.to_date(start_date)

        if not effective_date:
            raise ValidationError(
                self.env._(
                    "Debe indicar la fecha de inicio del vínculo de Beneficiario."
                )
            )

        if not relationship:
            raise ValidationError(
                self.env._("Debe seleccionar el vínculo con el Socio titular.")
            )

        clean_context = {
            key: value
            for key, value in self.env.context.items()
            if not key.startswith("default_")
        }

        with self.env.cr.savepoint():
            conversion_partner = self.with_context(
                club_client_to_beneficiary_internal_token=(
                    _CLUB_CLIENT_TO_BENEFICIARY_INTERNAL_TOKEN
                )
            )

            conversion_partner.write(
                {
                    "club_person_type": False,
                }
            )

            beneficiary = (
                self.env["club.beneficiary"]
                .with_context(**clean_context)
                .create(
                    {
                        "person_id": self.id,
                        "member_id": member.id,
                        "relationship": relationship,
                        "relationship_detail": relationship_detail,
                        "special_condition": special_condition or "none",
                        "start_date": effective_date,
                        "observations": observations,
                    }
                )
            )

        return beneficiary

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
            and new_person_type not in ("client", "member")
            and not self._is_club_client_to_beneficiary_internal_write()
        ):
            raise ValidationError(
                self.env._(
                    "Un Cliente no puede abandonar su condición mediante "
                    "edición directa. Debe utilizar un proceso controlado "
                    "de conversión."
                )
            )

        return super()._prepare_club_member_write_vals(
            partner,
            vals,
        )
