from odoo import api, fields, models
from odoo.exceptions import AccessError, ValidationError


class ClubKardexEvent(models.Model):
    _name = "club.kardex.event"
    _description = "Evento de Kardex del Socio"
    _order = "event_datetime desc, id desc"
    _rec_name = "description"

    member_id = fields.Many2one(
        comodel_name="res.partner",
        string="Socio",
        required=True,
        readonly=True,
        index=True,
        ondelete="restrict",
        domain=[("club_person_type", "=", "member")],
    )

    event_datetime = fields.Datetime(
        string="Fecha y hora",
        required=True,
        readonly=True,
        index=True,
        default=fields.Datetime.now,
    )

    user_id = fields.Many2one(
        comodel_name="res.users",
        string="Usuario",
        required=True,
        readonly=True,
        ondelete="restrict",
    )

    event_type = fields.Selection(
        selection=[
            ("member_created", "Alta de socio"),
            (
                "member_personal_data_updated",
                "Modificación de datos personales",
            ),
            (
                "member_identity_updated",
                "Modificación de identificación",
            ),
            (
                "member_code_changed",
                "Cambio de código de asociado",
            ),
            (
                "member_join_date_changed",
                "Cambio de fecha de ingreso",
            ),
            (
                "member_state_changed",
                "Cambio de estado del asociado",
            ),
            (
                "member_legal_state_changed",
                "Cambio de estado legal",
            ),
            (
                "beneficiary_created",
                "Registro de beneficiario",
            ),
            (
                "beneficiary_updated",
                "Modificación de beneficiario",
            ),
            (
                "beneficiary_finalized",
                "Finalización de vínculo de beneficiario",
            ),
            (
                "beneficiary_reassigned",
                "Reasignación de beneficiario",
            ),
            (
                "beneficiary_blocked",
                "Bloqueo de beneficiario",
            ),
            (
                "beneficiary_reactivated",
                "Reactivación de beneficiario",
            ),
            (
                "beneficiary_age_blocked",
                "Bloqueo automático por edad",
            ),
            (
                "beneficiary_converted",
                "Beneficiario convertido en socio",
            ),
            (
                "member_created_from_beneficiary",
                "Alta proveniente de beneficiario",
            ),
            (
                "certificate_created",
                "Registro de certificado patrimonial",
            ),
            (
                "certificate_updated",
                "Modificación de certificado patrimonial",
            ),
            (
                "certificate_state_changed",
                "Cambio de estado del certificado",
            ),
        ],
        string="Tipo de evento",
        required=True,
        readonly=True,
        index=True,
    )

    description = fields.Char(
        string="Descripción",
        required=True,
        readonly=True,
    )

    old_value = fields.Text(
        string="Valor anterior",
        readonly=True,
    )

    new_value = fields.Text(
        string="Valor nuevo",
        readonly=True,
    )

    reason = fields.Text(
        string="Motivo",
        readonly=True,
    )

    beneficiary_id = fields.Many2one(
        comodel_name="club.beneficiary",
        string="Beneficiario relacionado",
        readonly=True,
        ondelete="restrict",
    )

    certificate_id = fields.Many2one(
        comodel_name="club.certificate",
        string="Certificado relacionado",
        readonly=True,
        ondelete="restrict",
    )

    origin = fields.Selection(
        selection=[
            ("manual", "Manual"),
            ("automatic", "Automático"),
        ],
        string="Origen",
        required=True,
        readonly=True,
        default="manual",
    )

    @api.model_create_multi
    def create(self, vals_list):
        if not self.env.context.get("club_kardex_internal_create"):
            raise AccessError(
                self.env._(
                    "Los eventos del Kardex solo pueden ser "
                    "creados por procesos autorizados del sistema."
                )
            )

        return super().create(vals_list)

    def write(self, vals):
        if not self.env.context.get("club_kardex_internal_write"):
            raise AccessError(
                self.env._(
                    "Los eventos del Kardex son históricos y no pueden modificarse."
                )
            )

        return super().write(vals)

    @api.ondelete(at_uninstall=False)
    def _unlink_except_module_uninstall(self):
        raise ValidationError(
            self.env._("Los eventos del Kardex son históricos y no pueden eliminarse.")
        )

    @api.model
    def _log_event(
        self,
        member,
        event_type,
        description,
        **event_data,
    ):
        if not member or member.club_person_type != "member":
            raise ValidationError(
                self.env._("Todo evento del Kardex debe estar vinculado a un socio.")
            )

        origin = event_data.get(
            "origin",
            "manual",
        )

        if origin not in (
            "manual",
            "automatic",
        ):
            raise ValidationError(
                self.env._("El origen del evento debe ser Manual o Automático.")
            )

        beneficiary = event_data.get("beneficiary")

        certificate = event_data.get("certificate")

        if certificate and certificate.member_id != member:
            raise ValidationError(
                self.env._(
                    "El certificado relacionado debe pertenecer "
                    "al mismo socio del evento de Kardex."
                )
            )

        vals = {
            "member_id": member.id,
            "event_datetime": fields.Datetime.now(),
            "user_id": self.env.user.id,
            "event_type": event_type,
            "description": description,
            "old_value": (event_data.get("old_value") or False),
            "new_value": (event_data.get("new_value") or False),
            "reason": (event_data.get("reason") or False),
            "beneficiary_id": (beneficiary.id if beneficiary else False),
            "certificate_id": (certificate.id if certificate else False),
            "origin": origin,
        }

        return self.sudo().with_context(club_kardex_internal_create=True).create(vals)
