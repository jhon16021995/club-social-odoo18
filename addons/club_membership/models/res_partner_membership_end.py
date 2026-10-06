from odoo import fields, models
from odoo.exceptions import AccessError, ValidationError

_CLUB_MEMBERSHIP_END_INTERNAL_TOKEN = object()


class ResPartnerMembershipEnd(models.Model):
    # Esta extensión permanece separada porque la baja definitiva
    # constituye un flujo institucional controlado e independiente
    # del retiro temporal RET y de la reactivación REA.
    _inherit = "res.partner"  # pylint: disable=consider-merging-classes-inherited

    def _check_club_membership_end_permission(self):
        if not self.env.user.has_group("club_membership.group_club_membership_end"):
            raise AccessError(
                self.env._(
                    "No tiene permiso para finalizar definitivamente "
                    "la membresía de un Socio."
                )
            )

    def _is_club_membership_end_internal_write(self):
        return (
            self.env.context.get("club_membership_end_internal_token")
            is _CLUB_MEMBERSHIP_END_INTERNAL_TOKEN
        )

    def _prepare_club_member_write_vals(
        self,
        partner,
        vals,
    ):
        if self._is_club_membership_end_internal_write():
            partner_vals = dict(vals)

            new_person_type = partner_vals.get(
                "club_person_type",
                partner.club_person_type,
            )

            if partner.club_person_type == "member" and new_person_type is False:
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
        if self._is_club_membership_end_internal_write():
            return

        super()._log_club_member_write_changes(
            partner,
            before_values,
            was_member,
        )

    def action_open_club_membership_end_wizard(self):
        self.ensure_one()
        self._check_club_membership_end_permission()

        if self.club_person_type != "member":
            raise ValidationError(
                self.env._(
                    "La baja definitiva solo puede aplicarse "
                    "a una Persona que actualmente sea Socio."
                )
            )

        return {
            "type": "ir.actions.act_window",
            "name": self.env._("Finalizar membresía definitivamente"),
            "res_model": "club.membership.end.wizard",
            "view_mode": "form",
            "views": [
                (
                    self.env.ref(
                        "club_membership.view_club_membership_end_wizard_form"
                    ).id,
                    "form",
                )
            ],
            "target": "new",
            "context": {
                "default_member_id": self.id,
            },
        }

    def action_end_club_membership(
        self,
        reason,
        effective_date=False,
    ):
        self.ensure_one()
        self._check_club_membership_end_permission()

        if self.club_person_type != "member":
            raise ValidationError(
                self.env._(
                    "La baja definitiva solo puede aplicarse "
                    "a una Persona que actualmente sea Socio."
                )
            )

        normalized_reason = (reason or "").strip()

        if not normalized_reason:
            raise ValidationError(
                self.env._(
                    "Debe indicar el motivo de la baja definitiva de la membresía."
                )
            )

        if not effective_date:
            raise ValidationError(
                self.env._(
                    "Debe indicar la fecha efectiva de la baja "
                    "definitiva de la membresía."
                )
            )

        today = fields.Date.context_today(self)
        end_date = fields.Date.to_date(effective_date)

        if end_date > today:
            raise ValidationError(
                self.env._(
                    "La fecha efectiva de la baja definitiva no puede ser futura."
                )
            )

        current_periods = self.env["club.membership.period"].search(
            [
                ("person_id", "=", self.id),
                ("state", "=", "current"),
            ]
        )

        if len(current_periods) != 1:
            raise ValidationError(
                self.env._(
                    "La membresía actual no posee exactamente un período "
                    "histórico vigente. Debe regularizarse el historial "
                    "antes de realizar la baja definitiva."
                )
            )

        current_beneficiaries = self.env["club.beneficiary"].search(
            [
                ("member_id", "=", self.id),
                ("state", "in", ("active", "blocked")),
            ]
        )

        if current_beneficiaries:
            raise ValidationError(
                self.env._(
                    "No puede finalizarse definitivamente la membresía "
                    "porque el Socio tiene %(count)s Beneficiario(s) "
                    "vigente(s) a su cargo. Finalice o reasigne primero "
                    "todos esos vínculos.",
                    count=len(current_beneficiaries),
                )
            )

        current_period = current_periods

        if end_date < current_period.start_date:
            raise ValidationError(
                self.env._(
                    "La fecha efectiva de la baja definitiva no puede "
                    "ser anterior al inicio del período de membresía vigente."
                )
            )

        if self.club_last_withdrawal_date and end_date < self.club_last_withdrawal_date:
            raise ValidationError(
                self.env._(
                    "La fecha efectiva de la baja definitiva no puede "
                    "ser anterior a la fecha del último retiro del Socio."
                )
            )

        if (
            self.club_last_reactivation_date
            and end_date < self.club_last_reactivation_date
        ):
            raise ValidationError(
                self.env._(
                    "La fecha efectiva de la baja definitiva no puede "
                    "ser anterior a la fecha de la última reactivación "
                    "del Socio."
                )
            )

        certificate = self.club_certificate_ids[:1]

        certificate_reason = self.env._(
            "Baja definitiva del Socio titular. "
            "Fecha efectiva: %(date)s. Motivo: %(reason)s",
            date=fields.Date.to_string(end_date),
            reason=normalized_reason,
        )

        if certificate and certificate.state == "active":
            certificate._write_membership_end_values_internal(  # pylint: disable=protected-access
                {
                    "state": "passive",
                    "passive_by_member_withdrawal": False,
                    "passive_by_membership_end": True,
                },
                reason=certificate_reason,
            )
        elif (
            certificate
            and certificate.state == "passive"
            and certificate.passive_by_member_withdrawal
        ):
            certificate._write_membership_end_values_internal(  # pylint: disable=protected-access
                {
                    "passive_by_member_withdrawal": False,
                    "passive_by_membership_end": True,
                },
                reason=certificate_reason,
            )

        # Método protegido intencional: la finalización del período
        # pertenece exclusivamente a este flujo institucional.
        current_period._finalize_period_internal(  # pylint: disable=protected-access
            end_date,
            normalized_reason,
        )

        kardex_reason = self.env._(
            "Fecha efectiva: %(date)s\nMotivo: %(reason)s",
            date=fields.Date.to_string(end_date),
            reason=normalized_reason,
        )

        self._log_club_kardex_event(
            self,
            "membership_ended",
            self.env._("Baja definitiva de membresía."),
            old_value=self.env._(
                "Socio vigente. Código de asociado: %(code)s",
                code=self.club_member_code,
            ),
            new_value=self.env._("Membresía finalizada definitivamente."),
            reason=kardex_reason,
            origin="manual",
        )

        # Se reutiliza el helper técnico de escritura de estado para
        # conservar las protecciones RET/REA, pero la salida del rol
        # Socio se autoriza exclusivamente mediante nuestro token.
        # pylint: disable=protected-access
        self.with_context(
            club_membership_end_internal_token=(_CLUB_MEMBERSHIP_END_INTERNAL_TOKEN)
        )._write_club_member_values_internal(
            {
                "club_person_type": False,
                "club_member_state": False,
                "club_legal_state": False,
                "club_join_date": False,
                "club_state_before_withdrawal": False,
                "club_last_withdrawal_date": False,
                "club_last_withdrawal_cause": False,
                "club_last_reactivation_date": False,
            },
            reason=kardex_reason,
            origin="manual",
            effective_date=end_date,
        )
        # pylint: enable=protected-access

        return True
