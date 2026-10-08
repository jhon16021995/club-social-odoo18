from odoo import api, fields, models
from odoo.exceptions import AccessError, ValidationError

_CLUB_FORMER_MEMBER_TO_BENEFICIARY_INTERNAL_TOKEN = object()


class ResPartnerFormerMemberToBeneficiaryConversion(models.Model):
    _inherit = "res.partner"  # pylint: disable=consider-merging-classes-inherited

    club_has_current_beneficiary_link = fields.Boolean(
        string="Tiene vínculo vigente como Beneficiario",
        compute="_compute_club_has_current_beneficiary_link",
        readonly=True,
    )

    @api.depends("club_beneficiary_link_ids.state")
    def _compute_club_has_current_beneficiary_link(self):
        for partner in self:
            partner.club_has_current_beneficiary_link = any(
                link.state in ("active", "blocked")
                for link in partner.club_beneficiary_link_ids
            )

    def _check_club_former_member_to_beneficiary_permission(self):
        if not self.env.user.has_group(
            "club_membership.group_club_former_member_to_beneficiary"
        ):
            raise AccessError(
                self.env._(
                    "No tiene permiso para convertir un Ex-Socio en Beneficiario."
                )
            )

    def _check_club_former_member_to_beneficiary_preconditions(self, member):
        self.ensure_one()

        if self.club_person_type:
            raise ValidationError(
                self.env._(
                    "La conversión Ex-Socio a Beneficiario solo puede "
                    "aplicarse cuando la Persona no posee un rol actual "
                    "de Socio o Cliente."
                )
            )

        if self.is_company:
            raise ValidationError(
                self.env._(
                    "Una empresa Ex-Socio no puede convertirse en Beneficiario. "
                    "El Beneficiario debe ser una persona individual."
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
                    "La Persona presenta un período de membresía vigente "
                    "y no puede convertirse en Beneficiario como Ex-Socio."
                )
            )

        finalized_period = Period.search(
            [
                ("person_id", "=", self.id),
                ("state", "=", "finalized"),
            ],
            order="end_date desc, id desc",
            limit=1,
        )

        if not finalized_period:
            raise ValidationError(
                self.env._(
                    "La Persona no cumple la condición de Ex-Socio. "
                    "Debe existir al menos un período de membresía "
                    "legítimamente finalizado."
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
                    "La Persona ya posee un vínculo vigente como Beneficiario. "
                    "Debe resolver primero ese vínculo."
                )
            )

        return finalized_period

    def action_open_club_former_member_to_beneficiary_wizard(self):
        self.ensure_one()
        self._check_club_former_member_to_beneficiary_permission()

        if self.club_person_type:
            raise ValidationError(
                self.env._(
                    "La conversión Ex-Socio a Beneficiario solo puede "
                    "iniciarse cuando la Persona no posee un rol actual."
                )
            )

        if self.is_company:
            raise ValidationError(
                self.env._("Una empresa Ex-Socio no puede convertirse en Beneficiario.")
            )

        Period = self.env["club.membership.period"]

        if Period.search(
            [
                ("person_id", "=", self.id),
                ("state", "=", "current"),
            ],
            limit=1,
        ):
            raise ValidationError(
                self.env._("La Persona presenta un período de membresía vigente.")
            )

        if not Period.search(
            [
                ("person_id", "=", self.id),
                ("state", "=", "finalized"),
            ],
            limit=1,
        ):
            raise ValidationError(
                self.env._("La Persona no cumple la condición de Ex-Socio.")
            )

        if self.env["club.beneficiary"].search(
            [
                ("person_id", "=", self.id),
                ("state", "in", ("active", "blocked")),
            ],
            limit=1,
        ):
            raise ValidationError(
                self.env._("La Persona ya posee un vínculo vigente como Beneficiario.")
            )

        return {
            "type": "ir.actions.act_window",
            "name": self.env._("Convertir Ex-Socio en Beneficiario"),
            "res_model": "club.former.member.to.beneficiary.wizard",
            "view_mode": "form",
            "views": [
                (
                    self.env.ref(
                        "club_membership."
                        "view_club_former_member_to_beneficiary_wizard_form"
                    ).id,
                    "form",
                )
            ],
            "target": "new",
            "context": {
                "default_person_id": self.id,
            },
        }

    def action_convert_former_member_to_beneficiary(self, conversion_vals):
        self.ensure_one()
        self._check_club_former_member_to_beneficiary_permission()

        conversion_vals = dict(conversion_vals or {})

        member_id = conversion_vals.pop("member_id", False)
        member = self.env["res.partner"]

        if (
            isinstance(member_id, int)
            and not isinstance(member_id, bool)
            and member_id > 0
        ):
            member = self.env["res.partner"].browse(member_id).exists()

        relationship = conversion_vals.get("relationship")
        relationship_detail = conversion_vals.get("relationship_detail")
        special_condition = conversion_vals.get("special_condition", "none")
        start_date = conversion_vals.get("start_date")
        observations = conversion_vals.get("observations")

        last_finalized_period = (
            self._check_club_former_member_to_beneficiary_preconditions(member)
        )

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

        if (
            last_finalized_period.end_date
            and effective_date < last_finalized_period.end_date
        ):
            raise ValidationError(
                self.env._(
                    "La fecha de inicio del vínculo de Beneficiario no puede "
                    "ser anterior a la finalización de la última membresía."
                )
            )

        clean_context = {
            key: value
            for key, value in self.env.context.items()
            if not key.startswith("default_")
        }

        with self.env.cr.savepoint():
            beneficiary = (
                self.env["club.beneficiary"]
                .with_context(
                    **clean_context,
                    club_former_member_to_beneficiary_internal_token=(
                        _CLUB_FORMER_MEMBER_TO_BENEFICIARY_INTERNAL_TOKEN
                    ),
                )
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

        return beneficiary.id


class ClubBeneficiaryFormerMemberProtection(models.Model):
    _inherit = "club.beneficiary"

    def _is_club_former_member_to_beneficiary_internal_create(self):
        return (
            self.env.context.get("club_former_member_to_beneficiary_internal_token")
            is _CLUB_FORMER_MEMBER_TO_BENEFICIARY_INTERNAL_TOKEN
        )

    @api.model_create_multi
    def create(self, vals_list):
        if not self._is_club_former_member_to_beneficiary_internal_create():
            for vals in vals_list:
                state = vals.get("state", "active")

                if state not in ("active", "blocked"):
                    continue

                person_id = vals.get("person_id")

                if (
                    not isinstance(person_id, int)
                    or isinstance(person_id, bool)
                    or person_id <= 0
                ):
                    continue

                person = self.env["res.partner"].browse(person_id).exists()

                if (
                    person
                    and not person.club_person_type
                    and person.club_is_former_member
                ):
                    raise ValidationError(
                        self.env._(
                            "Un Ex-Socio no puede registrarse como "
                            "Beneficiario vigente mediante creación directa. "
                            "Debe utilizar el proceso controlado "
                            "Convertir Ex-Socio en Beneficiario."
                        )
                    )

        return super().create(vals_list)
