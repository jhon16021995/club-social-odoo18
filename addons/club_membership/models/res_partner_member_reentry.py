from odoo import fields, models
from odoo.exceptions import AccessError, ValidationError

_CLUB_MEMBER_REENTRY_INTERNAL_TOKEN = object()


class ResPartnerMemberReentry(models.Model):
    _inherit = "res.partner"  # pylint: disable=consider-merging-classes-inherited

    def _is_club_member_reentry_internal_write(self):
        return (
            self.env.context.get("club_member_reentry_internal_token")
            is _CLUB_MEMBER_REENTRY_INTERNAL_TOKEN
        )

    def _check_club_member_reentry_permission(self):
        if not self.env.user.has_group("club_membership.group_club_member_reentry"):
            raise AccessError(
                self.env._("No tiene permiso para reingresar un Ex-Socio como Socio.")
            )

    def _log_club_member_created(self, partner):
        if self._is_club_member_reentry_internal_write():
            return None

        return super()._log_club_member_created(partner)

    def _create_initial_membership_period(self):
        self.ensure_one()

        if not self._is_club_member_reentry_internal_write():
            return super()._create_initial_membership_period()

        effective_date = fields.Date.to_date(
            self.env.context.get("club_member_reentry_effective_date")
        )

        if not effective_date:
            raise ValidationError(
                self.env._(
                    "No se encontró la fecha efectiva del Reingreso "
                    "para crear el nuevo período de membresía."
                )
            )

        Period = self.env["club.membership.period"]

        return Period._create_period_internal(  # pylint: disable=protected-access
            {
                "person_id": self.id,
                "start_date": effective_date,
                "origin": "reentry",
                "member_code": self.club_member_code,
            }
        )

    def action_open_club_member_reentry_wizard(self):
        self.ensure_one()
        self._check_club_member_reentry_permission()

        if self.club_person_type:
            raise ValidationError(
                self.env._(
                    "El Reingreso como Socio solo puede aplicarse a un Ex-Socio "
                    "sin un rol actual de Socio o Cliente."
                )
            )

        if not self.club_is_former_member:
            raise ValidationError(
                self.env._(
                    "La Persona no posee la condición institucional de Ex-Socio."
                )
            )

        return {
            "type": "ir.actions.act_window",
            "name": self.env._("Reingresar Ex-Socio como Socio"),
            "res_model": "club.member.reentry.wizard",
            "view_mode": "form",
            "views": [
                (
                    self.env.ref(
                        "club_membership.view_club_member_reentry_wizard_form"
                    ).id,
                    "form",
                )
            ],
            "target": "new",
            "context": {
                "default_person_id": self.id,
            },
        }

    def action_reenter_club_member(
        self,
        reason,
        effective_date=False,
    ):
        self.ensure_one()
        self._check_club_member_reentry_permission()

        return self._execute_club_member_reentry(
            reason,
            effective_date=effective_date,
        )

    def _execute_club_member_reentry(
        self,
        reason,
        effective_date=False,
        *,
        allow_client_role=False,
    ):
        self.ensure_one()

        normalized_reason = (reason or "").strip()

        if not normalized_reason:
            raise ValidationError(
                self.env._("Debe indicar el motivo del Reingreso como Socio.")
            )

        reentry_date = fields.Date.to_date(effective_date)

        if not reentry_date:
            raise ValidationError(
                self.env._("Debe indicar la fecha efectiva del Reingreso como Socio.")
            )

        today = fields.Date.context_today(self)

        if reentry_date > today:
            raise ValidationError(
                self.env._("La fecha efectiva del Reingreso no puede ser futura.")
            )

        if self.club_person_type and not (
            allow_client_role and self.club_person_type == "client"
        ):
            raise ValidationError(
                self.env._(
                    "El Reingreso como Socio solo puede aplicarse a un Ex-Socio "
                    "sin un rol actual de Socio o Cliente."
                )
            )

        if not self.club_is_former_member:
            raise ValidationError(
                self.env._(
                    "La Persona no posee la condición institucional de Ex-Socio."
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
                self.env._("La Persona ya posee un período de membresía vigente.")
            )

        last_finalized_period = Period.search(
            [
                ("person_id", "=", self.id),
                ("state", "=", "finalized"),
            ],
            order="end_date desc, id desc",
            limit=1,
        )

        if not last_finalized_period:
            raise ValidationError(
                self.env._(
                    "No existe un período legítimo de membresía finalizado "
                    "que permita realizar el Reingreso."
                )
            )

        if reentry_date < last_finalized_period.end_date:
            raise ValidationError(
                self.env._(
                    "La fecha efectiva del Reingreso no puede ser anterior "
                    "a la fecha de finalización de la última membresía."
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
                    "Un Ex-Socio con un vínculo vigente como Beneficiario "
                    "no puede Reingresar como Socio. Finalice primero "
                    "el vínculo de Beneficiario."
                )
            )

        certificate = self.club_certificate_ids[:1]

        if (
            certificate
            and certificate.passive_by_membership_end
            and certificate.state != "passive"
        ):
            raise ValidationError(
                self.env._(
                    "El Certificado marcado como Pasivo por baja definitiva "
                    "presenta un estado inconsistente y no puede ser "
                    "reactivado automáticamente."
                )
            )

        reentry_partner = self.with_context(
            club_member_reentry_internal_token=(_CLUB_MEMBER_REENTRY_INTERNAL_TOKEN),
            club_member_reentry_effective_date=fields.Date.to_string(reentry_date),
        )

        # Helper interno protegido usado exclusivamente por este
        # proceso controlado de Reingreso.
        # pylint: disable=protected-access
        reentry_partner._write_club_member_values_internal(
            {
                "club_person_type": "member",
                "club_join_date": reentry_date,
                "club_member_state": "active",
                "club_legal_state": "regular",
            },
            reason=normalized_reason,
            origin="manual",
            effective_date=reentry_date,
        )
        # pylint: enable=protected-access

        self.invalidate_recordset()

        if certificate and certificate.passive_by_membership_end:
            # Restauración causal mediante helper interno propio
            # del flujo de Reingreso.
            # pylint: disable=protected-access
            certificate._write_member_reentry_values_internal(
                {
                    "state": "active",
                    "passive_by_membership_end": False,
                },
                reason=normalized_reason,
            )
            # pylint: enable=protected-access

        self._log_club_kardex_event(
            self,
            "membership_reentered",
            self.env._("Reingreso como Socio."),
            old_value=self.env._("Condición institucional: Ex-Socio"),
            new_value=self.env._(
                "Socio Activo · Código %(code)s · Fecha de ingreso %(date)s",
                code=self.club_member_code,
                date=fields.Date.to_string(reentry_date),
            ),
            reason=self.env._(
                "Fecha efectiva: %(date)s. Motivo: %(reason)s",
                date=fields.Date.to_string(reentry_date),
                reason=normalized_reason,
            ),
            origin="manual",
        )

        return True
