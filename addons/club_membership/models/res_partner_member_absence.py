from odoo import api, fields, models
from odoo.exceptions import AccessError, ValidationError


class ResPartnerMemberAbsence(models.Model):
    _inherit = "res.partner"

    club_entry_suspended_by_absence = fields.Boolean(
        string="Ingreso suspendido por ausencia",
        compute="_compute_club_entry_suspended_by_absence",
        readonly=True,
    )

    @api.depends(
        "club_member_state",
        "club_beneficiary_link_ids.state",
        "club_beneficiary_link_ids.member_id.club_member_state",
    )
    def _compute_club_entry_suspended_by_absence(self):
        for partner in self:
            if partner.club_person_type == "member":
                suspended = partner.club_member_state == "absent"
            else:
                suspended = any(
                    link.state == "active"
                    and link.member_id.club_member_state == "absent"
                    for link in partner.club_beneficiary_link_ids
                )

            partner.club_entry_suspended_by_absence = suspended

    club_absence_expected_return_date = fields.Date(
        string="Fecha prevista de retorno de ausencia",
        readonly=True,
        copy=False,
    )

    def check_club_entry_absence_restriction(self):
        """Comprueba la suspensión por ausencia, no autoriza el ingreso."""
        self.ensure_one()
        self.check_access("read")

        if self.club_entry_suspended_by_absence:
            raise ValidationError(
                self.env._("Ingreso suspendido por ausencia del Socio titular.")
            )

        return True

    def action_mark_club_member_absent(
        self,
        reason,
        *,
        effective_date=False,
        expected_return_date=False,
    ):
        self.ensure_one()

        self.check_access("read")

        if not (
            self.env.user.has_group("base.group_system")
            or self.env.user.has_group("club_membership.group_club_member_absence")
        ):
            raise AccessError(
                self.env._("No tiene permiso para registrar la ausencia de un Socio.")
            )

        if self.club_person_type != "member":
            raise ValidationError(self.env._("La operación requiere un Socio."))

        if self.club_member_state != "active":
            raise ValidationError(
                self.env._("Solo puede registrarse la ausencia de un Socio Activo.")
            )

        normalized_reason = (reason or "").strip()

        if not normalized_reason:
            raise ValidationError(self.env._("Debe indicar el motivo de la ausencia."))

        absence_date = fields.Date.to_date(effective_date) if effective_date else False

        if not absence_date:
            raise ValidationError(
                self.env._("Debe indicar la fecha efectiva de ausencia.")
            )

        today = fields.Date.context_today(self)

        if absence_date > today:
            raise ValidationError(
                self.env._("La ausencia no puede registrarse con fecha futura.")
            )

        current_periods = self.club_membership_period_ids.filtered(
            lambda period: period.state == "current"
        )

        if len(current_periods) != 1:
            raise ValidationError(
                self.env._(
                    "El Socio debe tener exactamente un período de membresía vigente."
                )
            )

        if absence_date < current_periods.start_date:
            raise ValidationError(
                self.env._(
                    "La ausencia no puede comenzar antes "
                    "del período de membresía vigente."
                )
            )

        expected_return = (
            fields.Date.to_date(expected_return_date) if expected_return_date else False
        )

        if expected_return and expected_return < absence_date:
            raise ValidationError(
                self.env._(
                    "La fecha prevista de retorno no puede ser anterior a la ausencia."
                )
            )

        self.sudo()._write_club_member_values_internal(
            {
                "club_member_state": "absent",
                "club_absence_expected_return_date": (expected_return or False),
            },
            reason=normalized_reason,
            origin="manual",
            effective_date=absence_date,
        )

        return True

    def write(self, vals):
        if (
            "club_absence_expected_return_date" in vals
            and not self._is_club_member_state_internal_write()
        ):
            raise ValidationError(
                self.env._(
                    "La fecha prevista de retorno solo puede "
                    "modificarse mediante un proceso controlado."
                )
            )

        return super().write(vals)

    def action_return_club_member_from_absence(
        self,
        reason,
        *,
        effective_date=False,
    ):
        self.ensure_one()

        self.check_access("read")

        if not (
            self.env.user.has_group("base.group_system")
            or self.env.user.has_group("club_membership.group_club_member_absence")
        ):
            raise AccessError(
                self.env._("No tiene permiso para registrar el retorno de un Socio.")
            )

        if self.club_person_type != "member" or self.club_member_state != "absent":
            raise ValidationError(
                self.env._("Solo puede retornar un Socio que se encuentra Ausente.")
            )

        normalized_reason = (reason or "").strip()

        if not normalized_reason:
            raise ValidationError(self.env._("Debe indicar el motivo del retorno."))

        return_date = fields.Date.to_date(effective_date) if effective_date else False

        if not return_date:
            raise ValidationError(
                self.env._("Debe indicar la fecha efectiva del retorno.")
            )

        today = fields.Date.context_today(self)

        if return_date > today:
            raise ValidationError(self.env._("El retorno no puede tener fecha futura."))

        periods = self.club_membership_period_ids.filtered(
            lambda period: period.state == "current"
        )

        if len(periods) != 1:
            raise ValidationError(
                self.env._("El Socio debe conservar exactamente un período vigente.")
            )

        absence_event = (
            self.env["club.kardex.event"]
            .sudo()
            .search(
                [
                    ("member_id", "=", self.id),
                    ("event_type", "=", "member_state_changed"),
                    ("member_state_to", "=", "absent"),
                ],
                order="event_datetime desc, id desc",
                limit=1,
            )
        )

        if not absence_event or not absence_event.effective_date:
            raise ValidationError(
                self.env._("No se encontró el inicio de la ausencia en el Kardex.")
            )

        if return_date < absence_event.effective_date:
            raise ValidationError(
                self.env._("El retorno no puede ser anterior al inicio de la ausencia.")
            )

        self.sudo()._write_club_member_values_internal(
            {
                "club_member_state": "active",
                "club_absence_expected_return_date": False,
            },
            reason=normalized_reason,
            origin="manual",
            effective_date=return_date,
        )

        return True

    def _open_club_absence_wizard(
        self, *, expected_state, wizard_model, view_xmlid, title
    ):
        self.ensure_one()

        if not (
            self.env.user.has_group("base.group_system")
            or self.env.user.has_group("club_membership.group_club_member_absence")
        ):
            raise AccessError(self.env._("No tiene permiso para gestionar ausencias."))

        self.check_access("read")

        if (
            self.club_person_type != "member"
            or self.club_member_state != expected_state
        ):
            raise ValidationError(
                self.env._("El estado actual del Socio no permite esta operación.")
            )

        return {
            "type": "ir.actions.act_window",
            "name": title,
            "res_model": wizard_model,
            "view_mode": "form",
            "views": [(self.env.ref(view_xmlid).id, "form")],
            "target": "new",
            "context": dict(
                self.env.context,
                default_member_id=self.id,
            ),
        }

    def action_open_club_member_absence_wizard(self):
        return self._open_club_absence_wizard(
            expected_state="active",
            wizard_model="club.member.absence.wizard",
            view_xmlid="club_membership.view_club_member_absence_wizard_form",
            title=self.env._("Registrar ausencia"),
        )

    def action_open_club_member_absence_return_wizard(self):
        return self._open_club_absence_wizard(
            expected_state="absent",
            wizard_model="club.member.absence.return.wizard",
            view_xmlid="club_membership.view_club_member_absence_return_wizard_form",
            title=self.env._("Registrar retorno"),
        )


class ClubBeneficiaryAbsenceAccess(models.Model):
    _inherit = "club.beneficiary"

    club_entry_suspended_by_absence = fields.Boolean(
        string="Ingreso suspendido por ausencia del titular",
        compute="_compute_club_entry_suspended_by_absence",
        readonly=True,
    )

    @api.depends("state", "member_id.club_member_state")
    def _compute_club_entry_suspended_by_absence(self):
        for link in self:
            link.club_entry_suspended_by_absence = (
                link.state == "active" and link.member_id.club_member_state == "absent"
            )

    def check_club_entry_absence_restriction(self):
        """Comprueba la suspensión del vínculo por ausencia."""
        self.ensure_one()
        self.check_access("read")

        if self.club_entry_suspended_by_absence:
            raise ValidationError(
                self.env._("Ingreso suspendido por ausencia del Socio titular.")
            )

        return True
