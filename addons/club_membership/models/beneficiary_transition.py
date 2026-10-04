from odoo import fields, models
from odoo.exceptions import ValidationError


class ClubBeneficiaryTransition(models.Model):
    _inherit = "club.beneficiary"

    def write(self, vals):
        if self.env.context.get("club_beneficiary_internal_transition_write"):
            return super().write(vals)

        if {
            "relationship",
            "relationship_detail",
        }.intersection(vals):
            raise ValidationError(
                self.env._(
                    "El vínculo de un Beneficiario no puede "
                    "cambiarse directamente. Use el proceso de "
                    "reasignación para conservar el historial."
                )
            )

        if vals.get("state") == "finalized":
            raise ValidationError(
                self.env._(
                    "Un vínculo de Beneficiario no puede finalizarse "
                    "editando directamente su estado. Use el proceso "
                    "de finalización."
                )
            )

        return super().write(vals)

    def _validate_transition_reason(self, reason):
        reason = (reason or "").strip()

        if not reason:
            raise ValidationError(
                self.env._("Debe indicar un motivo para realizar esta operación.")
            )

        return reason

    def _prepare_transition_dates(
        self,
        end_date=None,
        start_date=None,
    ):
        self.ensure_one()

        today = fields.Date.context_today(self)

        end_date = fields.Date.to_date(end_date) if end_date else today

        start_date = fields.Date.to_date(start_date) if start_date else end_date

        if self.start_date and end_date < self.start_date:
            raise ValidationError(
                self.env._(
                    "La fecha de finalización no puede ser "
                    "anterior a la fecha de inicio del vínculo."
                )
            )

        if start_date < end_date:
            raise ValidationError(
                self.env._(
                    "La fecha de inicio del nuevo vínculo no puede "
                    "ser anterior a la finalización del vínculo actual."
                )
            )

        return end_date, start_date

    def _write_finalized_transition(
        self,
        end_date,
        reason,
        extra_vals=None,
    ):
        self.ensure_one()

        if self.state == "finalized":
            raise ValidationError(
                self.env._("Este vínculo de Beneficiario ya está finalizado.")
            )

        vals = {
            "state": "finalized",
            "end_date": end_date,
            "end_reason": reason,
            "block_reason": False,
        }

        vals.update(dict(extra_vals or {}))

        self.with_context(
            club_beneficiary_internal_transition_write=True,
            club_beneficiary_skip_change_logging=True,
        ).write(vals)

    def finalize_link(
        self,
        end_date=None,
        reason=None,
        origin="manual",
    ):
        self.ensure_one()

        reason = self._validate_transition_reason(reason)

        if origin not in ("manual", "automatic"):
            raise ValidationError(
                self.env._("El origen de la finalización debe ser Manual o Automático.")
            )

        end_date, _start_date = self._prepare_transition_dates(
            end_date=end_date,
        )

        old_state = self._format_kardex_value(
            self,
            "state",
        )

        self._write_finalized_transition(
            end_date,
            reason,
        )

        self._log_kardex_event(
            self,
            "beneficiary_finalized",
            self.env._(
                "Vínculo del Beneficiario %(name)s finalizado.",
                name=self.name,
            ),
            old_value=old_state,
            new_value=self._format_kardex_value(
                self,
                "state",
            ),
            reason=reason,
            origin=origin,
        )

        return True

    def reassign_link(self, transition_vals):
        self.ensure_one()

        transition_vals = dict(transition_vals or {})

        if self.state == "finalized":
            raise ValidationError(
                self.env._("Un vínculo finalizado no puede reasignarse.")
            )

        new_member_id = transition_vals.get("new_member_id")
        relationship = transition_vals.get("relationship")

        special_condition = transition_vals.get(
            "special_condition",
            "none",
        )

        relationship_detail = transition_vals.get("relationship_detail")

        reason = self._validate_transition_reason(transition_vals.get("reason"))

        end_date, start_date = self._prepare_transition_dates(
            end_date=transition_vals.get("end_date"),
            start_date=transition_vals.get("start_date"),
        )

        new_member = self.env["res.partner"].browse(new_member_id).exists()

        if not new_member:
            raise ValidationError(
                self.env._("Debe seleccionar un Socio titular válido.")
            )

        if new_member.club_person_type != "member":
            raise ValidationError(
                self.env._("El nuevo titular debe tener la condición de Socio.")
            )

        relationship_detail = (
            (relationship_detail or "").strip()
            if relationship == "family_dependent"
            else False
        )

        if relationship == "family_dependent" and not relationship_detail:
            raise ValidationError(
                self.env._(
                    "Debe indicar el detalle cuando el nuevo vínculo "
                    "sea Familiar dependiente."
                )
            )

        current_detail = (
            (self.relationship_detail or "").strip()
            if self.relationship == "family_dependent"
            else False
        )

        if (
            new_member == self.member_id
            and relationship == self.relationship
            and relationship_detail == current_detail
        ):
            raise ValidationError(
                self.env._(
                    "La reasignación debe cambiar el Socio titular "
                    "o el vínculo con el Socio. Para modificar solo "
                    "la condición especial, edite esa condición "
                    "sin crear un nuevo vínculo."
                )
            )

        old_value = "\n".join(
            [
                self.env._(
                    "Socio titular: %(value)s",
                    value=self.member_id.display_name,
                ),
                self.env._(
                    "Vínculo: %(value)s",
                    value=self._format_kardex_value(
                        self,
                        "relationship",
                    ),
                ),
                self.env._(
                    "Estado: %(value)s",
                    value=self._format_kardex_value(
                        self,
                        "state",
                    ),
                ),
            ]
        )

        self._write_finalized_transition(
            end_date,
            reason,
        )

        clean_context = {
            key: value
            for key, value in self.env.context.items()
            if not key.startswith("default_")
        }

        new_link = (
            self.env["club.beneficiary"]
            .with_context(**clean_context)
            .create(
                {
                    "person_id": self.person_id.id,
                    "member_id": new_member.id,
                    "relationship": relationship,
                    "relationship_detail": relationship_detail,
                    "special_condition": special_condition or "none",
                    "start_date": start_date,
                    "end_date": False,
                    "end_reason": False,
                }
            )
        )

        new_value = "\n".join(
            [
                self.env._(
                    "Nuevo Socio titular: %(value)s",
                    value=new_member.display_name,
                ),
                self.env._(
                    "Nuevo vínculo: %(value)s",
                    value=self._format_kardex_value(
                        new_link,
                        "relationship",
                    ),
                ),
                self.env._(
                    "Fecha de inicio: %(value)s",
                    value=fields.Date.to_string(new_link.start_date),
                ),
            ]
        )

        self._log_kardex_event(
            self,
            "beneficiary_reassigned",
            self.env._(
                "Beneficiario %(name)s reasignado.",
                name=self.name,
            ),
            old_value=old_value,
            new_value=new_value,
            reason=reason,
            origin="manual",
        )

        return new_link

    def action_convert_to_member(self):
        self.ensure_one()

        person = self.person_id

        if person.club_person_type == "client":
            raise ValidationError(
                self.env._(
                    "Esta persona todavía tiene la condición "
                    "de Cliente. Debe finalizar primero esa "
                    "condición antes de convertirse en Socio."
                )
            )

        if person.club_person_type == "member":
            raise ValidationError(
                self.env._(
                    "Esta persona ya posee historial como Socio. "
                    "La reactivación de un Socio Pasivo se "
                    "realizará mediante el proceso específico "
                    "de reactivación."
                )
            )

        current_links = self.search(
            [
                ("person_id", "=", person.id),
                ("state", "in", ("active", "blocked")),
            ]
        )

        other_current_links = current_links.filtered(lambda link: link != self)

        if other_current_links:
            raise ValidationError(
                self.env._(
                    "Esta persona posee otro vínculo vigente como "
                    "Beneficiario. Debe finalizar primero ese vínculo "
                    "antes de convertirla en Socio."
                )
            )

        original_member = self.member_id
        was_finalized = self.state == "finalized"

        person.with_context(club_conversion_beneficiary_id=self.id).write(
            {
                "club_person_type": "member",
            }
        )

        conversion_vals = {
            "converted_member_id": person.id,
            "converted_at": fields.Datetime.now(),
        }

        if not was_finalized:
            self._write_finalized_transition(
                fields.Date.context_today(self),
                self.env._("Conversión a Socio"),
                extra_vals=conversion_vals,
            )
        else:
            self.with_context(
                club_beneficiary_internal_transition_write=True,
                club_beneficiary_skip_change_logging=True,
            ).write(conversion_vals)

        self._log_kardex_event(
            self,
            "beneficiary_converted",
            (
                self.env._(
                    "Beneficiario %(name)s convertido en Socio "
                    "desde un vínculo histórico finalizado.",
                    name=self.name,
                )
                if was_finalized
                else self.env._(
                    "Beneficiario %(name)s convertido en Socio.",
                    name=self.name,
                )
            ),
            old_value=self.env._(
                "Beneficiario de %(member)s",
                member=original_member.display_name,
            ),
            new_value=self.env._(
                "Socio %(member)s · Código %(code)s",
                member=person.display_name,
                code=person.club_member_code,
            ),
            reason=self.env._("Conversión a Socio"),
            origin="manual",
        )

        return {
            "type": "ir.actions.act_window",
            "name": self.env._("Socio"),
            "res_model": "res.partner",
            "res_id": person.id,
            "view_mode": "form",
            "views": [
                (
                    self.env.ref(
                        "club_membership.view_partner_form_club_membership"
                    ).id,
                    "form",
                )
            ],
            "target": "current",
        }

    def create_new_link(self, transition_vals):
        self.ensure_one()

        transition_vals = dict(transition_vals or {})

        if self.state != "finalized":
            raise ValidationError(
                self.env._(
                    "La creación de un nuevo vínculo desde el historial "
                    "solo puede realizarse desde un vínculo Finalizado."
                )
            )

        current_link = self.search(
            [
                ("person_id", "=", self.person_id.id),
                ("state", "in", ("active", "blocked")),
            ],
            limit=1,
        )

        if current_link:
            raise ValidationError(
                self.env._(
                    "Esta persona ya posee un vínculo vigente como "
                    "Beneficiario. Debe finalizarlo antes de crear otro."
                )
            )

        new_member_id = transition_vals.get("new_member_id")
        relationship = transition_vals.get("relationship")

        if not relationship:
            raise ValidationError(self.env._("Debe seleccionar el nuevo vínculo."))
        special_condition = transition_vals.get(
            "special_condition",
            "none",
        )
        relationship_detail = transition_vals.get("relationship_detail")

        start_date = transition_vals.get("start_date")
        start_date = (
            fields.Date.to_date(start_date)
            if start_date
            else fields.Date.context_today(self)
        )

        new_member = self.env["res.partner"].browse(new_member_id).exists()

        if not new_member:
            raise ValidationError(
                self.env._("Debe seleccionar un Socio titular válido.")
            )

        if new_member.club_person_type != "member":
            raise ValidationError(
                self.env._("El nuevo titular debe tener la condición de Socio.")
            )

        if new_member == self.person_id:
            raise ValidationError(
                self.env._(
                    "Una persona no puede registrarse como Beneficiario de sí misma."
                )
            )

        if self.end_date and start_date < self.end_date:
            raise ValidationError(
                self.env._(
                    "La fecha de inicio del nuevo vínculo no puede "
                    "ser anterior a la finalización del vínculo histórico."
                )
            )

        relationship_detail = (
            (relationship_detail or "").strip()
            if relationship == "family_dependent"
            else False
        )

        if relationship == "family_dependent" and not relationship_detail:
            raise ValidationError(
                self.env._(
                    "Debe indicar el detalle cuando el nuevo vínculo "
                    "sea Familiar dependiente."
                )
            )

        clean_context = {
            key: value
            for key, value in self.env.context.items()
            if not key.startswith("default_")
        }

        return (
            self.env["club.beneficiary"]
            .with_context(**clean_context)
            .create(
                {
                    "person_id": self.person_id.id,
                    "member_id": new_member.id,
                    "relationship": relationship,
                    "relationship_detail": relationship_detail,
                    "special_condition": (special_condition or "none"),
                    "start_date": start_date,
                    "end_date": False,
                    "end_reason": False,
                }
            )
        )

    def action_open_new_link_wizard(self):
        self.ensure_one()

        if self.state != "finalized":
            raise ValidationError(
                self.env._(
                    "Esta operación solo está disponible para vínculos Finalizados."
                )
            )

        current_link = self.search(
            [
                ("person_id", "=", self.person_id.id),
                ("state", "in", ("active", "blocked")),
            ],
            limit=1,
        )

        if current_link:
            raise ValidationError(
                self.env._(
                    "Esta persona ya posee un vínculo vigente como Beneficiario."
                )
            )

        return {
            "type": "ir.actions.act_window",
            "name": self.env._("Crear nuevo vínculo"),
            "res_model": "club.beneficiary.transition.wizard",
            "view_mode": "form",
            "view_id": self.env.ref(
                "club_membership.view_club_beneficiary_transition_wizard_form"
            ).id,
            "target": "new",
            "context": {
                "default_beneficiary_id": self.id,
                "default_operation": "new_link",
                "default_start_date": (fields.Date.context_today(self)),
            },
        }

    def action_open_finalize_wizard(self):
        self.ensure_one()

        if self.state == "finalized":
            raise ValidationError(
                self.env._("Este vínculo de Beneficiario ya está finalizado.")
            )

        return {
            "type": "ir.actions.act_window",
            "name": self.env._("Finalizar vínculo"),
            "res_model": "club.beneficiary.transition.wizard",
            "view_mode": "form",
            "view_id": self.env.ref(
                "club_membership.view_club_beneficiary_transition_wizard_form"
            ).id,
            "target": "new",
            "context": {
                "default_beneficiary_id": self.id,
                "default_operation": "finalize",
                "default_end_date": fields.Date.context_today(self),
            },
        }

    def action_open_reassign_wizard(self):
        self.ensure_one()

        if self.state == "finalized":
            raise ValidationError(
                self.env._("Un vínculo finalizado no puede reasignarse.")
            )

        today = fields.Date.context_today(self)

        return {
            "type": "ir.actions.act_window",
            "name": self.env._("Reasignar / cambiar vínculo"),
            "res_model": "club.beneficiary.transition.wizard",
            "view_mode": "form",
            "view_id": self.env.ref(
                "club_membership.view_club_beneficiary_transition_wizard_form"
            ).id,
            "target": "new",
            "context": {
                "default_beneficiary_id": self.id,
                "default_operation": "reassign",
                "default_new_member_id": self.member_id.id,
                "default_relationship": self.relationship,
                "default_relationship_detail": self.relationship_detail,
                "default_special_condition": self.special_condition,
                "default_end_date": today,
                "default_start_date": today,
            },
        }
