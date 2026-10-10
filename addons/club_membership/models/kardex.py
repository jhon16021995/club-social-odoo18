from odoo import api, fields, models
from odoo.exceptions import AccessError, ValidationError

_CLUB_KARDEX_REGISTRATION_CORRECTION_TOKEN = object()


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

    effective_date = fields.Date(
        string="Fecha efectiva",
        readonly=True,
        index=True,
        copy=False,
    )

    member_state_from = fields.Selection(
        selection=[
            ("active", "Activo"),
            ("active_arrears", "Activo en mora"),
            ("lifetime", "Vitalicio"),
            ("absent", "Ausente"),
            ("temporary", "Transitorio"),
            ("inactive", "Pasivo"),
        ],
        string="Estado anterior del asociado",
        readonly=True,
        copy=False,
    )

    member_state_to = fields.Selection(
        selection=[
            ("active", "Activo"),
            ("active_arrears", "Activo en mora"),
            ("lifetime", "Vitalicio"),
            ("absent", "Ausente"),
            ("temporary", "Transitorio"),
            ("inactive", "Pasivo"),
        ],
        string="Estado nuevo del asociado",
        readonly=True,
        copy=False,
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
                "member_identity_corrected",
                "Corrección de identidad",
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
                "member_historical_contributions_changed",
                "Cambio de Aportes Ordinarios Pagados históricos",
            ),
            (
                "member_state_changed",
                "Cambio de estado del asociado",
            ),
            (
                "membership_ended",
                "Baja definitiva de membresía",
            ),
            (
                "membership_reentered",
                "Reingreso como Socio",
            ),
            (
                "former_member_converted_to_client",
                "Ex-Socio convertido en Cliente",
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
                "member_registration_error_corrected",
                "Corrección de alta errónea de Socio",
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

    person_audit_event_id = fields.Many2one(
        comodel_name="club.person.audit.event",
        string="Auditoría de identidad relacionada",
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
    def _log_registration_error_correction(
        self,
        member,
        description,
        **event_data,
    ):
        beneficiary = event_data.get("beneficiary")

        if not member or not beneficiary or beneficiary.person_id != member:
            raise ValidationError(
                self.env._(
                    "La corrección de alta errónea debe vincular "
                    "al Beneficiario con la misma Persona corregida."
                )
            )

        # Llamada protegida intencional dentro del mismo modelo:
        # esta ruta solo existe para la corrección controlada de alta errónea.
        # pylint: disable=protected-access
        result = self.with_context(
            club_kardex_registration_correction_token=(
                _CLUB_KARDEX_REGISTRATION_CORRECTION_TOKEN
            )
        )._log_event(
            member,
            "member_registration_error_corrected",
            description,
            **event_data,
        )
        # pylint: enable=protected-access

        return result

    @api.model
    def _log_event(
        self,
        member,
        event_type,
        description,
        **event_data,
    ):
        registration_correction = (
            self.env.context.get("club_kardex_registration_correction_token")
            is _CLUB_KARDEX_REGISTRATION_CORRECTION_TOKEN
            and event_type == "member_registration_error_corrected"
        )

        if not member or (
            member.club_person_type != "member" and not registration_correction
        ):
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
        person_audit_event = event_data.get("person_audit_event")

        if certificate and certificate.member_id != member:
            raise ValidationError(
                self.env._(
                    "El certificado relacionado debe pertenecer "
                    "al mismo socio del evento de Kardex."
                )
            )

        if person_audit_event and person_audit_event.person_id != member:
            raise ValidationError(
                self.env._(
                    "La auditoría de identidad relacionada debe "
                    "pertenecer a la misma Persona del Socio."
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
            "effective_date": (
                fields.Date.to_date(event_data.get("effective_date"))
                if event_data.get("effective_date")
                else False
            ),
            "member_state_from": (event_data.get("member_state_from") or False),
            "member_state_to": (event_data.get("member_state_to") or False),
            "beneficiary_id": (beneficiary.id if beneficiary else False),
            "certificate_id": (certificate.id if certificate else False),
            "person_audit_event_id": (
                person_audit_event.id if person_audit_event else False
            ),
            "origin": origin,
        }

        return self.sudo().with_context(club_kardex_internal_create=True).create(vals)
