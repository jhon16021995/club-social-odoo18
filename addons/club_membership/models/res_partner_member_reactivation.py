from odoo import fields, models
from odoo.exceptions import AccessError, ValidationError


class ResPartnerMemberReactivation(models.Model):
    # This extension intentionally remains separate because member
    # reactivation is an isolated controlled workflow.
    _inherit = "res.partner"  # pylint: disable=consider-merging-classes-inherited

    club_state_before_withdrawal = fields.Selection(
        selection=[
            ("active", "Activo"),
            ("active_arrears", "Activo en mora"),
            ("lifetime", "Vitalicio"),
            ("absent", "Ausente"),
            ("temporary", "Transitorio"),
        ],
        string="Estado previo al último retiro",
        readonly=True,
        copy=False,
    )

    club_last_withdrawal_date = fields.Date(
        string="Fecha efectiva del último retiro",
        readonly=True,
        copy=False,
    )

    club_last_withdrawal_cause = fields.Selection(
        selection=[
            ("voluntary", "Retiro / baja voluntaria"),
            ("death", "Fallecimiento"),
            ("administrative", "Otro motivo administrativo"),
        ],
        string="Causa del último retiro",
        readonly=True,
        copy=False,
    )

    club_last_reactivation_date = fields.Date(
        string="Fecha efectiva de la última reactivación",
        readonly=True,
        copy=False,
    )

    def action_withdraw_club_member(
        self,
        reason,
        effective_date=False,
        withdrawal_cause="voluntary",
    ):
        self.ensure_one()

        withdrawal_causes = {
            "voluntary": self.env._("Retiro / baja voluntaria"),
            "death": self.env._("Fallecimiento"),
            "administrative": self.env._("Otro motivo administrativo"),
        }

        normalized_reason = (reason or "").strip()

        if not normalized_reason:
            raise ValidationError(
                self.env._("Debe indicar el motivo del retiro del Socio.")
            )

        if withdrawal_cause not in withdrawal_causes:
            raise ValidationError(
                self.env._("La causa de baja seleccionada no es válida.")
            )

        withdrawal_date = (
            fields.Date.to_date(effective_date)
            if effective_date
            else fields.Date.context_today(self)
        )

        if (
            self.club_last_reactivation_date
            and withdrawal_date < self.club_last_reactivation_date
        ):
            raise ValidationError(
                self.env._(
                    "La fecha efectiva del nuevo retiro no puede ser "
                    "anterior a la última reactivación del Socio."
                )
            )

        traced_reason = self.env._(
            "Causa: %(cause)s. Detalle: %(reason)s",
            cause=withdrawal_causes[withdrawal_cause],
            reason=normalized_reason,
        )

        partner = self.with_context(
            club_member_withdrawal_cause=withdrawal_cause,
        )

        return super(
            ResPartnerMemberReactivation,
            partner,
        ).action_withdraw_club_member(
            traced_reason,
            effective_date=effective_date,
        )

    def _check_club_member_reactivation_permission(self):
        if not self.env.user.has_group(
            "club_membership.group_club_member_reactivation"
        ):
            raise AccessError(
                self.env._("No tiene permiso para reactivar a un Socio Pasivo.")
            )

    def action_open_club_member_reactivation_wizard(self):
        self.ensure_one()
        self._check_club_member_reactivation_permission()

        if self.club_person_type != "member":
            raise ValidationError(
                self.env._("La reactivación solo puede aplicarse a un Socio.")
            )

        if self.club_member_state != "inactive":
            raise ValidationError(
                self.env._("Solo puede reactivarse un Socio que se encuentre Pasivo.")
            )

        return {
            "type": "ir.actions.act_window",
            "name": self.env._("Reactivar Socio Pasivo"),
            "res_model": "club.member.reactivation.wizard",
            "view_mode": "form",
            "views": [
                (
                    self.env.ref(
                        "club_membership.view_club_member_reactivation_wizard_form"
                    ).id,
                    "form",
                )
            ],
            "target": "new",
            "context": {
                "default_member_id": self.id,
            },
        }

    def action_reactivate_club_member(
        self,
        reason,
        effective_date=False,
    ):
        self.ensure_one()
        self._check_club_member_reactivation_permission()

        if self.club_person_type != "member":
            raise ValidationError(
                self.env._("La reactivación solo puede aplicarse a un Socio.")
            )

        if self.club_member_state != "inactive":
            raise ValidationError(
                self.env._("Solo puede reactivarse un Socio que se encuentre Pasivo.")
            )

        normalized_reason = (reason or "").strip()

        if not normalized_reason:
            raise ValidationError(
                self.env._("Debe indicar el motivo de la reactivación del Socio.")
            )

        today = fields.Date.context_today(self)
        reactivation_date = (
            fields.Date.to_date(effective_date) if effective_date else today
        )

        if reactivation_date > today:
            raise ValidationError(
                self.env._("La fecha efectiva de la reactivación no puede ser futura.")
            )

        if not self.club_last_withdrawal_date:
            raise ValidationError(
                self.env._(
                    "El Socio Pasivo no tiene registrada una fecha "
                    "estructural de último retiro. Debe regularizarse "
                    "su historial antes de utilizar esta reactivación."
                )
            )

        if reactivation_date < self.club_last_withdrawal_date:
            raise ValidationError(
                self.env._(
                    "La fecha efectiva de la reactivación no puede ser "
                    "anterior al último retiro del Socio."
                )
            )

        target_state = self.club_state_before_withdrawal

        if not target_state:
            raise ValidationError(
                self.env._(
                    "No se conoce el estado que tenía el Socio antes "
                    "del último retiro. Debe regularizarse su historial "
                    "antes de reactivarlo."
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
                    "Un Socio con un vínculo vigente como Beneficiario "
                    "debe permanecer Pasivo. Finalice primero el vínculo "
                    "de Beneficiario antes de reactivar al Socio."
                )
            )

        certificate = self.club_certificate_ids[:1]

        if (
            certificate
            and certificate.passive_by_member_withdrawal
            and certificate.state != "passive"
        ):
            raise ValidationError(
                self.env._(
                    "El Certificado Patrimonial tiene una inconsistencia: "
                    "figura marcado por retiro del Socio pero no está Pasivo."
                )
            )

        eligible_beneficiaries = self.club_beneficiary_ids.filtered(
            lambda beneficiary: (
                beneficiary.state == "blocked"
                and beneficiary.blocked_by_member_withdrawal
            )
        )

        certificate_reason = self.env._(
            "Reactivación del Socio titular. Motivo: %(reason)s",
            reason=normalized_reason,
        )

        if (
            certificate
            and certificate.state == "passive"
            and certificate.passive_by_member_withdrawal
        ):
            certificate._write_member_withdrawal_values_internal(  # pylint: disable=protected-access
                {
                    "state": "active",
                    "passive_by_member_withdrawal": False,
                },
                reason=certificate_reason,
            )

        if eligible_beneficiaries:
            eligible_beneficiaries._write_member_withdrawal_values_internal(  # pylint: disable=protected-access
                {
                    "state": "active",
                    "blocked_by_member_withdrawal": False,
                }
            )

        kardex_reason = self.env._(
            "Fecha efectiva: %(date)s\nMotivo: %(reason)s",
            date=fields.Date.to_string(reactivation_date),
            reason=normalized_reason,
        )

        self._write_club_member_values_internal(
            {
                "club_member_state": target_state,
                "club_state_before_withdrawal": False,
                "club_last_reactivation_date": reactivation_date,
            },
            reason=kardex_reason,
            origin="manual",
            effective_date=reactivation_date,
        )

        return True

    def write(self, vals):
        vals = dict(vals)

        withdrawal_cause = self.env.context.get("club_member_withdrawal_cause")

        if (
            self._is_club_member_state_internal_write()
            and vals.get("club_member_state") == "inactive"
            and withdrawal_cause
        ):
            vals["club_last_withdrawal_cause"] = withdrawal_cause

        protected_withdrawal_fields = {
            "club_state_before_withdrawal",
            "club_last_withdrawal_date",
            "club_last_withdrawal_cause",
            "club_last_reactivation_date",
        }

        if (
            protected_withdrawal_fields.intersection(vals)
            and not self._is_club_member_state_internal_write()
        ):
            raise AccessError(
                self.env._(
                    "Los datos técnicos del retiro y reactivación del Socio "
                    "solo pueden modificarse mediante los procesos "
                    "controlados del sistema."
                )
            )

        return super().write(vals)
