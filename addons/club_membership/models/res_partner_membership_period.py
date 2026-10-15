from odoo import api, fields, models
from odoo.exceptions import ValidationError


class ResPartnerMembershipPeriod(models.Model):
    # Esta extensión se mantiene separada intencionalmente de la capa
    # principal de res.partner y de la corrección de alta errónea.
    # La separación conserva responsabilidades y permite que la capa
    # de corrección controlada permanezca al final del orden de carga.
    _inherit = "res.partner"  # pylint: disable=consider-merging-classes-inherited

    club_membership_period_ids = fields.One2many(
        comodel_name="club.membership.period",
        inverse_name="person_id",
        string="Períodos de membresía",
        readonly=True,
    )

    club_is_former_member = fields.Boolean(
        string="Ex-Socio",
        compute="_compute_club_is_former_member",
        store=True,
        index=True,
        readonly=True,
    )

    @api.depends(
        "club_person_type",
        "club_membership_period_ids.state",
    )
    def _compute_club_is_former_member(self):
        for partner in self:
            period_states = set(partner.club_membership_period_ids.mapped("state"))

            partner.club_is_former_member = (
                partner.club_person_type != "member"
                and "current" not in period_states
                and "finalized" in period_states
            )

    def _create_initial_membership_period(self):
        self.ensure_one()

        if self.club_person_type != "member":
            return self.env["club.membership.period"]

        Period = self.env["club.membership.period"]

        real_history = Period.search(
            [
                ("person_id", "=", self.id),
                ("state", "in", ("current", "finalized")),
            ],
            limit=1,
        )

        if real_history:
            raise ValidationError(
                self.env._(
                    "No puede generarse un alta inicial de Socio "
                    "porque la Persona ya posee un período real "
                    "de membresía."
                )
            )

        return Period._create_period_internal(  # pylint: disable=protected-access
            {
                "person_id": self.id,
                "start_date": self.club_join_date,
                "origin": "initial",
                "member_code": self.club_member_code,
                "opening_member_state": self.club_member_state,
            }
        )

    @api.model_create_multi
    def create(self, vals_list):
        partners = super().create(vals_list)

        for partner in partners:
            if partner.club_person_type == "member":
                # Helper protegido perteneciente a esta capa histórica.
                # pylint: disable=protected-access
                partner._create_initial_membership_period()
                # pylint: enable=protected-access

        return partners

    def write(self, vals):
        previous_member_ids = set(
            self.filtered(lambda partner: partner.club_person_type == "member").ids
        )

        result = super().write(vals)

        for partner in self:
            became_member = (
                partner.id not in previous_member_ids
                and partner.club_person_type == "member"
            )

            if became_member:
                # Helper protegido perteneciente a esta capa histórica.
                # pylint: disable=protected-access
                partner._create_initial_membership_period()
                # pylint: enable=protected-access

        return result

    def get_club_member_state_as_of(self, at_date):
        """Reconstrucción histórica inicial para Finanzas.

        Usa el estado de apertura del período y las transiciones
        efectivas Activo/Ausente del Kardex. Otras transiciones
        todavía requieren pruebas y tratamiento específico.

        No genera cuotas, pagos ni asientos contables.
        """
        from odoo import fields
        from odoo.exceptions import ValidationError

        self.ensure_one()

        if isinstance(at_date, (bool, int, float)):
            raise ValidationError(
                self.env._("Debe indicar una fecha de consulta válida.")
            )

        try:
            cutoff = fields.Date.to_date(at_date)
        except (TypeError, ValueError, OverflowError):
            cutoff = False

        if not cutoff:
            raise ValidationError(
                self.env._("Debe indicar una fecha de consulta válida.")
            )

        periods = self.env["club.membership.period"].search(
            [
                ("person_id", "=", self.id),
                ("start_date", "<=", cutoff),
                ("state", "in", ("current", "finalized")),
            ],
            order="start_date desc, id desc",
        )

        # Mantener bloqueada la frontera del día de finalización
        # hasta definir su semántica funcional para Finanzas.
        if periods.filtered(lambda period: period.end_date == cutoff):
            raise ValidationError(
                self.env._(
                    "La fecha consultada coincide con una finalización "
                    "de membresía pendiente de definición contable."
                )
            )

        covering = periods.filtered(
            lambda period: not period.end_date or period.end_date > cutoff
        )

        if len(covering) > 1:
            raise ValidationError(
                self.env._(
                    "Existen períodos de membresía superpuestos. "
                    "No es posible determinar el estado histórico."
                )
            )

        if not covering:
            return False

        period = covering[0]
        current_state = period.opening_member_state

        if not current_state:
            raise ValidationError(
                self.env._("El período carece de estado inicial histórico.")
            )

        events = self.env["club.kardex.event"].search(
            [
                ("member_id", "=", self.id),
                ("event_type", "=", "member_state_changed"),
            ],
            order="effective_date asc, event_datetime asc, id asc",
        )

        last_effective_date = False

        for event in events:
            # No usar la fecha de registro como sustituto
            # de la fecha efectiva.
            if not event.effective_date:
                raise ValidationError(
                    self.env._(
                        "El Kardex contiene un cambio de estado sin "
                        "fecha efectiva. No puede reconstruirse "
                        "el estado histórico."
                    )
                )

            # Eventos de otros períodos o posteriores al corte
            # no modifican el estado en la fecha consultada.
            if event.effective_date < period.start_date:
                continue

            if event.effective_date > cutoff:
                continue

            if event.effective_date == last_effective_date:
                raise ValidationError(
                    self.env._(
                        "Existen varios cambios de estado con "
                        "la misma fecha efectiva. Su orden "
                        "histórico requiere validación."
                    )
                )

            if not event.member_state_from or not event.member_state_to:
                raise ValidationError(
                    self.env._(
                        "El Kardex contiene una transición "
                        "sin estados anterior y nuevo completos."
                    )
                )

            if event.member_state_from != current_state:
                raise ValidationError(
                    self.env._(
                        "La secuencia histórica del Kardex "
                        "no coincide con el estado anterior "
                        "del Socio."
                    )
                )

            allowed = {
                ("active", "absent"),
                ("absent", "active"),
                ("active", "inactive"),
                ("inactive", "active"),
                ("temporary", "inactive"),
                ("inactive", "temporary"),
                ("lifetime", "inactive"),
                ("inactive", "lifetime"),
            }

            if (
                event.member_state_from,
                event.member_state_to,
            ) not in allowed:
                raise ValidationError(
                    self.env._(
                        "El Kardex contiene una transición "
                        "institucional todavía no soportada "
                        "por la consulta histórica."
                    )
                )

            current_state = event.member_state_to
            last_effective_date = event.effective_date

        return current_state
