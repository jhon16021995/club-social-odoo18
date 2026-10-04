from odoo import fields, models
from odoo.exceptions import AccessError, ValidationError

_MEMBER_REGISTRATION_CORRECTION_TOKEN = object()


class ResPartnerMemberRegistrationCorrection(models.Model):
    _inherit = "res.partner"

    def _check_member_registration_correction_permission(self):
        if not self.env.user.has_group(
            "club_membership.group_club_member_registration_correction"
        ):
            raise AccessError(
                self.env._("No tiene permiso para corregir un alta errónea de Socio.")
            )

    def _prepare_club_member_write_vals(
        self,
        partner,
        vals,
    ):
        internal_correction = (
            self.env.context.get("club_member_registration_correction_token")
            is _MEMBER_REGISTRATION_CORRECTION_TOKEN
        )

        if internal_correction:
            partner_vals = dict(vals)

            new_person_type = partner_vals.get(
                "club_person_type",
                partner.club_person_type,
            )

            if partner.club_person_type == "member" and new_person_type != "member":
                partner_vals["club_member_code"] = False
                return partner_vals

        return super()._prepare_club_member_write_vals(
            partner,
            vals,
        )

    def _log_club_member_write_changes(
        self,
        partner,
        before_values,
        was_member,
    ):
        internal_correction = (
            self.env.context.get("club_member_registration_correction_token")
            is _MEMBER_REGISTRATION_CORRECTION_TOKEN
        )

        if internal_correction:
            return

        super()._log_club_member_write_changes(
            partner,
            before_values,
            was_member,
        )

    def _get_registration_error_selection_label(
        self,
        field_name,
        value,
    ):
        self.ensure_one()

        if not value:
            return self.env._("Sin valor")

        field_description = self.fields_get([field_name])[field_name]

        selection = dict(field_description.get("selection", []))

        return selection.get(value, value)

    def _get_current_beneficiaries_as_member(self):
        self.ensure_one()

        return self.env["club.beneficiary"].search(
            [
                ("member_id", "=", self.id),
                ("state", "in", ("active", "blocked")),
            ],
            order="id",
        )

    def _get_registration_error_snapshot(
        self,
        certificate,
    ):
        self.ensure_one()

        return {
            "person_name": self.display_name,
            "id_number": self.club_id_number,
            "member_code": self.club_member_code,
            "member_state": (
                self._get_registration_error_selection_label(
                    "club_member_state",
                    self.club_member_state,
                )
            ),
            "legal_state": (
                self._get_registration_error_selection_label(
                    "club_legal_state",
                    self.club_legal_state,
                )
            ),
            "join_date": self.club_join_date,
            "certificate_number": (
                certificate.certificate_number if certificate else False
            ),
        }

    def _check_registration_error_correction_data(
        self,
        target_member,
        relationship,
        special_condition,
        reason,
    ):
        self.ensure_one()

        self._check_member_registration_correction_permission()

        if self.club_person_type != "member":
            raise ValidationError(
                self.env._(
                    "La corrección solo puede realizarse "
                    "sobre una Persona que actualmente sea Socio."
                )
            )

        if self.is_company:
            raise ValidationError(
                self.env._("Una empresa no puede convertirse en Beneficiario.")
            )

        if not self.club_id_number:
            raise ValidationError(
                self.env._("La Persona debe tener un número de carnet.")
            )

        if not self.club_birthdate:
            raise ValidationError(
                self.env._("La Persona debe tener fecha de nacimiento.")
            )

        current_beneficiaries = self._get_current_beneficiaries_as_member()

        if current_beneficiaries:
            raise ValidationError(
                self.env._(
                    "No se puede corregir el alta errónea de este "
                    "Socio porque tiene %(count)s Beneficiario(s) "
                    "vigente(s) a su cargo.\n\n"
                    "Debe finalizar manualmente todos los vínculos "
                    "vigentes antes de realizar la corrección. "
                    "Los vínculos históricos ya finalizados no "
                    "necesitan modificación.",
                    count=len(current_beneficiaries),
                )
            )

        if (
            not target_member
            or not target_member.exists()
            or target_member.club_person_type != "member"
        ):
            raise ValidationError(
                self.env._("Debe seleccionar un Socio titular válido.")
            )

        if target_member == self:
            raise ValidationError(
                self.env._("La Persona corregida no puede ser su propio Socio titular.")
            )

        current_link = self.env["club.beneficiary"].search(
            [
                ("person_id", "=", self.id),
                ("state", "in", ("active", "blocked")),
            ],
            limit=1,
        )

        if current_link:
            raise ValidationError(
                self.env._(
                    "Esta Persona ya tiene un vínculo vigente "
                    "como Beneficiario. Revise ese vínculo "
                    "antes de realizar la corrección."
                )
            )

        relationship_selection = dict(
            self.env["club.beneficiary"]
            .fields_get(["relationship"])["relationship"]
            .get("selection", [])
        )

        if relationship not in relationship_selection:
            raise ValidationError(
                self.env._("Debe seleccionar un vínculo válido para el Beneficiario.")
            )

        special_condition_selection = dict(
            self.env["club.beneficiary"]
            .fields_get(["special_condition"])["special_condition"]
            .get("selection", [])
        )

        if special_condition not in special_condition_selection:
            raise ValidationError(
                self.env._("La condición especial indicada no es válida.")
            )

        if not (reason or "").strip():
            raise ValidationError(
                self.env._("Debe indicar el motivo de la corrección de alta errónea.")
            )

        certificates = self.club_certificate_ids

        if len(certificates) > 1:
            raise ValidationError(
                self.env._(
                    "La Persona tiene más de un Certificado "
                    "Patrimonial. Debe revisar esta inconsistencia "
                    "antes de continuar."
                )
            )

    def _log_member_registration_error_kardex(
        self,
        *,
        target_member,
        beneficiary,
        certificate,
        snapshot,
        reason,
    ):
        self.ensure_one()

        old_value_lines = [
            self.env._("Condición anterior: Socio"),
            self.env._(
                "Código de asociado: %(value)s",
                value=snapshot["member_code"],
            ),
            self.env._(
                "Estado del asociado: %(value)s",
                value=snapshot["member_state"],
            ),
        ]

        if snapshot.get("join_date"):
            old_value_lines.append(
                self.env._(
                    "Fecha de ingreso: %(value)s",
                    value=fields.Date.to_string(snapshot["join_date"]),
                )
            )

        if snapshot.get("certificate_number"):
            old_value_lines.append(
                self.env._(
                    "Certificado: %(value)s",
                    value=snapshot["certificate_number"],
                )
            )

        relationship_field = beneficiary.fields_get(["relationship"])["relationship"]

        relationship_label = dict(relationship_field.get("selection", [])).get(
            beneficiary.relationship,
            beneficiary.relationship,
        )

        new_value_lines = [
            self.env._(
                "Condición correcta: Beneficiario de %(member)s",
                member=target_member.display_name,
            ),
            self.env._(
                "Vínculo: %(relationship)s",
                relationship=relationship_label,
            ),
            self.env._(
                "Carnet conservado: %(value)s",
                value=self.club_id_number,
            ),
        ]

        self._log_club_kardex_event(
            self,
            "member_registration_error_corrected",
            self.env._("Alta errónea de Socio corregida a vínculo de Beneficiario."),
            old_value="\n".join(old_value_lines),
            new_value="\n".join(new_value_lines),
            reason=reason,
            beneficiary=beneficiary,
            certificate=certificate,
            origin="manual",
        )

    def correct_member_registration_error_to_beneficiary(
        self,
        target_member,
        correction_values,
    ):
        self.ensure_one()

        correction_values = dict(correction_values or {})

        relationship = correction_values.get("relationship")
        relationship_detail = correction_values.get("relationship_detail")
        special_condition = correction_values.get("special_condition") or "none"
        start_date = correction_values.get("start_date")
        reason = correction_values.get("reason")

        normalized_reason = (reason or "").strip()
        normalized_relationship_detail = (relationship_detail or "").strip()

        self._check_registration_error_correction_data(
            target_member,
            relationship,
            special_condition,
            normalized_reason,
        )

        if not start_date:
            start_date = fields.Date.context_today(self)

        certificate = self.club_certificate_ids[:1]

        snapshot = self._get_registration_error_snapshot(certificate)

        if certificate:
            # Método privado intencional: solo lo invoca este proceso controlado.
            certificate._action_void_registration_error(  # pylint: disable=protected-access
                normalized_reason
            )

        if self.club_member_state != "inactive":
            # El helper protegido se comparte intencionalmente entre
            # extensiones controladas del mismo modelo res.partner.
            # pylint: disable=protected-access
            self.with_context(
                club_member_registration_correction_token=(
                    _MEMBER_REGISTRATION_CORRECTION_TOKEN
                )
            )._write_club_member_state_internal(
                "inactive",
                reason=normalized_reason,
                origin="manual",
            )
            # pylint: enable=protected-access

        beneficiary = self.env["club.beneficiary"].create(
            {
                "person_id": self.id,
                "member_id": target_member.id,
                "relationship": relationship,
                "relationship_detail": (
                    normalized_relationship_detail
                    if relationship == "family_dependent"
                    else False
                ),
                "special_condition": special_condition,
                "start_date": start_date,
            }
        )

        correction = self.env["club.member.registration.correction"]._log_event(  # pylint: disable=protected-access
            self,
            beneficiary,
            normalized_reason,
            certificate=certificate,
            snapshot=snapshot,
        )

        self._log_member_registration_error_kardex(
            target_member=target_member,
            beneficiary=beneficiary,
            certificate=certificate,
            snapshot=snapshot,
            reason=normalized_reason,
        )

        # El helper protegido se comparte intencionalmente entre
        # extensiones controladas del mismo modelo res.partner.
        # pylint: disable=protected-access
        self.with_context(
            club_member_registration_correction_token=(
                _MEMBER_REGISTRATION_CORRECTION_TOKEN
            )
        )._write_club_member_values_internal(
            {
                "club_person_type": False,
                "club_member_state": False,
                "club_legal_state": False,
                "club_join_date": False,
            }
        )
        # pylint: enable=protected-access

        return beneficiary, correction
