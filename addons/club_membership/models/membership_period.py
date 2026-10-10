from odoo import api, fields, models
from odoo.exceptions import AccessError, ValidationError

_CLUB_MEMBERSHIP_PERIOD_INTERNAL_TOKEN = object()


class ClubMembershipPeriod(models.Model):
    _name = "club.membership.period"
    _description = "Período histórico de membresía"
    _order = "start_date desc, id desc"

    person_id = fields.Many2one(
        comodel_name="res.partner",
        string="Persona",
        required=True,
        readonly=True,
        index=True,
        ondelete="restrict",
    )

    start_date = fields.Date(
        string="Fecha de inicio",
        required=True,
        readonly=True,
        index=True,
    )

    end_date = fields.Date(
        string="Fecha de finalización",
        readonly=True,
        index=True,
    )

    origin = fields.Selection(
        selection=[
            ("initial", "Alta inicial"),
            ("reentry", "Reingreso"),
            ("migrated", "Migrado"),
        ],
        string="Origen",
        required=True,
        readonly=True,
        default="initial",
    )

    member_code = fields.Char(
        string="Código de asociado histórico",
        readonly=True,
        copy=False,
    )

    opening_member_state = fields.Selection(
        selection=[
            ("active", "Activo"),
            ("active_arrears", "Activo en mora"),
            ("lifetime", "Vitalicio"),
            ("absent", "Ausente"),
            ("temporary", "Transitorio"),
            ("inactive", "Pasivo"),
        ],
        string="Estado del asociado al inicio",
        readonly=True,
        index=True,
        copy=False,
    )

    end_reason = fields.Text(
        string="Motivo de finalización",
        readonly=True,
        copy=False,
    )

    ended_at = fields.Datetime(
        string="Registrado como finalizado el",
        readonly=True,
        copy=False,
    )

    end_user_id = fields.Many2one(
        comodel_name="res.users",
        string="Finalizado por",
        readonly=True,
        copy=False,
        ondelete="restrict",
    )

    void_reason = fields.Text(
        string="Motivo de anulación",
        readonly=True,
        copy=False,
    )

    voided_at = fields.Datetime(
        string="Anulado el",
        readonly=True,
        copy=False,
    )

    void_user_id = fields.Many2one(
        comodel_name="res.users",
        string="Anulado por",
        readonly=True,
        copy=False,
        ondelete="restrict",
    )

    state = fields.Selection(
        selection=[
            ("current", "Vigente"),
            ("finalized", "Finalizada"),
            ("voided", "Anulada por alta errónea"),
        ],
        string="Estado",
        compute="_compute_state",
        store=True,
        readonly=True,
        index=True,
    )

    @api.depends("end_date", "voided_at")
    def _compute_state(self):
        for period in self:
            if period.voided_at:
                period.state = "voided"
            elif period.end_date:
                period.state = "finalized"
            else:
                period.state = "current"

    def _is_internal_period_operation(self):
        return (
            self.env.context.get("club_membership_period_internal_token")
            is _CLUB_MEMBERSHIP_PERIOD_INTERNAL_TOKEN
        )

    @api.model
    def _create_period_internal(self, vals):
        period = self.with_context(
            club_membership_period_internal_token=(
                _CLUB_MEMBERSHIP_PERIOD_INTERNAL_TOKEN
            )
        ).create(vals)

        return period.with_context(club_membership_period_internal_token=False)

    def _write_period_internal(self, vals):
        return self.with_context(
            club_membership_period_internal_token=(
                _CLUB_MEMBERSHIP_PERIOD_INTERNAL_TOKEN
            )
        ).write(vals)

    def _void_period_internal(self, reason):
        self.ensure_one()

        normalized_reason = (reason or "").strip()

        if not normalized_reason:
            raise ValidationError(
                self.env._(
                    "Debe registrar el motivo de anulación del período de membresía."
                )
            )

        if self.state != "current":
            raise ValidationError(
                self.env._(
                    "Solo un período de membresía vigente "
                    "puede anularse por alta errónea."
                )
            )

        return self._write_period_internal(
            {
                "void_reason": normalized_reason,
                "voided_at": fields.Datetime.now(),
                "void_user_id": self.env.user.id,
            }
        )

    def _finalize_period_internal(self, end_date, reason):
        self.ensure_one()

        normalized_reason = (reason or "").strip()

        if not normalized_reason:
            raise ValidationError(
                self.env._(
                    "Debe registrar el motivo de finalización del período de membresía."
                )
            )

        if self.state != "current":
            raise ValidationError(
                self.env._("Solo un período de membresía vigente puede finalizarse.")
            )

        final_date = fields.Date.to_date(end_date)

        if not final_date:
            raise ValidationError(
                self.env._(
                    "Debe registrar la fecha efectiva de finalización "
                    "del período de membresía."
                )
            )

        if final_date < self.start_date:
            raise ValidationError(
                self.env._(
                    "La fecha de finalización de la membresía no puede "
                    "ser anterior a la fecha de inicio."
                )
            )

        return self._write_period_internal(
            {
                "end_date": final_date,
                "end_reason": normalized_reason,
                "ended_at": fields.Datetime.now(),
                "end_user_id": self.env.user.id,
            }
        )

    @api.model_create_multi
    def create(self, vals_list):
        if not self._is_internal_period_operation():
            raise AccessError(
                self.env._(
                    "Los períodos de membresía solo pueden crearse "
                    "mediante un proceso controlado del sistema."
                )
            )

        return super().create(vals_list)

    def write(self, vals):
        if not self._is_internal_period_operation():
            raise AccessError(
                self.env._(
                    "Los períodos de membresía no pueden modificarse directamente."
                )
            )

        return super().write(vals)

    @api.constrains(
        "start_date",
        "end_date",
    )
    def _check_period_dates(self):
        for period in self:
            if period.end_date and period.end_date < period.start_date:
                raise ValidationError(
                    self.env._(
                        "La fecha de finalización de la membresía no puede "
                        "ser anterior a la fecha de inicio."
                    )
                )

    @api.constrains(
        "person_id",
        "end_date",
        "voided_at",
    )
    def _check_single_current_period(self):
        for period in self:
            if period.end_date or period.voided_at:
                continue

            duplicate = self.search(
                [
                    ("id", "!=", period.id),
                    ("person_id", "=", period.person_id.id),
                    ("end_date", "=", False),
                    ("voided_at", "=", False),
                ],
                limit=1,
            )

            if duplicate:
                raise ValidationError(
                    self.env._(
                        "Una Persona no puede tener más de un período "
                        "de membresía vigente."
                    )
                )

    @api.constrains(
        "end_date",
        "voided_at",
        "void_reason",
        "void_user_id",
    )
    def _check_terminal_state_consistency(self):
        for period in self:
            if period.end_date and period.voided_at:
                raise ValidationError(
                    self.env._(
                        "Un período de membresía no puede estar "
                        "finalizado y anulado al mismo tiempo."
                    )
                )

            if period.voided_at:
                if not (period.void_reason or "").strip():
                    raise ValidationError(
                        self.env._(
                            "Un período anulado debe conservar el motivo de anulación."
                        )
                    )

                if not period.void_user_id:
                    raise ValidationError(
                        self.env._(
                            "Un período anulado debe conservar "
                            "el usuario que registró la anulación."
                        )
                    )

            elif period.void_reason or period.void_user_id:
                raise ValidationError(
                    self.env._(
                        "Los datos de anulación solo pueden existir "
                        "en un período efectivamente anulado."
                    )
                )

    @api.ondelete(at_uninstall=False)
    def _unlink_except_module_uninstall(self):
        raise ValidationError(
            self.env._(
                "Los períodos de membresía son históricos y no pueden eliminarse."
            )
        )
