from odoo import api, fields, models
from odoo.exceptions import AccessError, ValidationError


class ClubPersonAuditEvent(models.Model):
    _name = "club.person.audit.event"
    _description = "Evento de auditoría de identidad de Persona"
    _order = "event_datetime desc, id desc"

    _SENSITIVE_FIELD_SELECTION = [
        ("name", "Nombre / Razón social"),
        ("club_id_number", "Número de carnet"),
        ("club_id_extension", "Extensión del carnet"),
        ("club_birthdate", "Fecha de nacimiento"),
    ]

    person_id = fields.Many2one(
        comodel_name="res.partner",
        string="Persona",
        required=True,
        readonly=True,
        index=True,
        ondelete="restrict",
    )

    member_id = fields.Many2one(
        comodel_name="res.partner",
        string="Socio al momento de la corrección",
        readonly=True,
        index=True,
        ondelete="restrict",
        domain=[("club_person_type", "=", "member")],
    )

    field_name = fields.Selection(
        selection=_SENSITIVE_FIELD_SELECTION,
        string="Dato corregido",
        required=True,
        readonly=True,
        index=True,
    )

    old_value = fields.Text(
        string="Valor anterior",
        required=True,
        readonly=True,
    )

    new_value = fields.Text(
        string="Valor nuevo",
        required=True,
        readonly=True,
    )

    reason = fields.Text(
        string="Motivo de la corrección",
        required=True,
        readonly=True,
    )

    user_id = fields.Many2one(
        comodel_name="res.users",
        string="Usuario",
        required=True,
        readonly=True,
        ondelete="restrict",
    )

    event_datetime = fields.Datetime(
        string="Fecha y hora",
        required=True,
        readonly=True,
        index=True,
    )

    @api.model_create_multi
    def create(self, vals_list):
        if not self.env.context.get("club_person_audit_internal_create"):
            raise AccessError(
                self.env._(
                    "Los eventos de auditoría de Persona solo pueden ser "
                    "creados por procesos autorizados del sistema."
                )
            )

        audit_user_id = self.env.context.get("club_person_audit_user_id")

        if not audit_user_id:
            raise AccessError(
                self.env._(
                    "No se pudo determinar el usuario responsable de la corrección."
                )
            )

        prepared_vals_list = []

        for original_vals in vals_list:
            vals = dict(original_vals)
            vals["user_id"] = audit_user_id
            vals["event_datetime"] = fields.Datetime.now()
            prepared_vals_list.append(vals)

        return super().create(prepared_vals_list)

    def write(self, vals):
        if not self.env.context.get("club_person_audit_internal_write"):
            raise AccessError(
                self.env._(
                    "Los eventos de auditoría de Persona son históricos "
                    "y no pueden modificarse."
                )
            )

        return super().write(vals)

    @api.ondelete(at_uninstall=False)
    def _unlink_except_module_uninstall(self):
        raise ValidationError(
            self.env._(
                "Los eventos de auditoría de Persona son históricos "
                "y no pueden eliminarse."
            )
        )

    @api.model
    def _normalize_audit_value(self, value):
        if value is False or value is None or value == "":
            return self.env._("Sin valor")

        return str(value)

    @api.model
    def _log_event(
        self,
        person,
        field_name,
        old_value,
        new_value,
        reason,
    ):
        if not person or not person.exists():
            raise ValidationError(
                self.env._(
                    "Todo evento de auditoría debe estar vinculado "
                    "a una Persona válida."
                )
            )

        supported_fields = dict(self._SENSITIVE_FIELD_SELECTION)

        if field_name not in supported_fields:
            raise ValidationError(
                self.env._(
                    "El campo indicado no forma parte de los datos "
                    "sensibles auditables."
                )
            )

        reason = (reason or "").strip()

        if not reason:
            raise ValidationError(
                self.env._("Debe indicar el motivo de la corrección.")
            )

        normalized_old_value = self._normalize_audit_value(old_value)
        normalized_new_value = self._normalize_audit_value(new_value)

        if normalized_old_value == normalized_new_value:
            raise ValidationError(
                self.env._(
                    "La corrección debe modificar realmente el valor "
                    "del dato seleccionado."
                )
            )

        member = (
            person if person.club_person_type == "member" else self.env["res.partner"]
        )

        vals = {
            "person_id": person.id,
            "member_id": member.id if member else False,
            "field_name": field_name,
            "old_value": normalized_old_value,
            "new_value": normalized_new_value,
            "reason": reason,
        }

        responsible_user_id = self.env.user.id

        return (
            self.sudo()
            .with_context(
                club_person_audit_internal_create=True,
                club_person_audit_user_id=responsible_user_id,
            )
            .create(vals)
        )
