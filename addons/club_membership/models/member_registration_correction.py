from odoo import api, fields, models
from odoo.exceptions import AccessError, ValidationError


class ClubMemberRegistrationCorrection(models.Model):
    _name = "club.member.registration.correction"
    _description = "Auditoría de corrección de alta errónea de Socio"
    _order = "event_datetime desc, id desc"

    person_id = fields.Many2one(
        comodel_name="res.partner",
        string="Persona corregida",
        required=True,
        readonly=True,
        index=True,
        ondelete="restrict",
    )

    person_name = fields.Char(
        string="Nombre al momento de la corrección",
        required=True,
        readonly=True,
    )

    id_number = fields.Char(
        string="Carnet al momento de la corrección",
        required=True,
        readonly=True,
        index=True,
    )

    old_member_code = fields.Char(
        string="Código de asociado anterior",
        required=True,
        readonly=True,
    )

    old_member_state = fields.Char(
        string="Estado anterior del asociado",
        required=True,
        readonly=True,
    )

    old_legal_state = fields.Char(
        string="Estado legal anterior",
        readonly=True,
    )

    old_join_date = fields.Date(
        string="Fecha de ingreso anterior",
        readonly=True,
    )

    target_member_id = fields.Many2one(
        comodel_name="res.partner",
        string="Socio titular correcto",
        required=True,
        readonly=True,
        index=True,
        ondelete="restrict",
    )

    beneficiary_id = fields.Many2one(
        comodel_name="club.beneficiary",
        string="Vínculo de Beneficiario resultante",
        required=True,
        readonly=True,
        index=True,
        ondelete="restrict",
    )

    certificate_id = fields.Many2one(
        comodel_name="club.certificate",
        string="Certificado anulado",
        readonly=True,
        index=True,
        ondelete="restrict",
    )

    certificate_number = fields.Char(
        string="Número de certificado al momento de la corrección",
        readonly=True,
    )

    reason = fields.Text(
        string="Motivo de la corrección",
        required=True,
        readonly=True,
    )

    user_id = fields.Many2one(
        comodel_name="res.users",
        string="Usuario responsable",
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
        if not self.env.context.get(
            "club_member_registration_correction_internal_create"
        ):
            raise AccessError(
                self.env._(
                    "Las auditorías de corrección de alta errónea "
                    "solo pueden ser creadas por el proceso "
                    "autorizado del sistema."
                )
            )

        responsible_user_id = self.env.context.get(
            "club_member_registration_correction_user_id"
        )

        if not responsible_user_id:
            raise AccessError(
                self.env._(
                    "No se pudo determinar el usuario responsable de la corrección."
                )
            )

        prepared_vals_list = []

        for original_vals in vals_list:
            vals = dict(original_vals)
            vals["user_id"] = responsible_user_id
            vals["event_datetime"] = fields.Datetime.now()
            prepared_vals_list.append(vals)

        return super().create(prepared_vals_list)

    def write(self, vals):  # pylint: disable=method-required-super
        raise AccessError(
            self.env._(
                "Las auditorías de corrección de alta errónea "
                "son históricas y no pueden modificarse."
            )
        )

    @api.ondelete(at_uninstall=False)
    def _unlink_except_module_uninstall(self):
        raise ValidationError(
            self.env._(
                "Las auditorías de corrección de alta errónea "
                "son históricas y no pueden eliminarse."
            )
        )

    @api.model
    def _log_event(
        self,
        person,
        beneficiary,
        reason,
        *,
        certificate=None,
        snapshot=None,
    ):
        if not person or not person.exists():
            raise ValidationError(
                self.env._("La corrección debe estar vinculada a una Persona válida.")
            )

        if not beneficiary or not beneficiary.exists():
            raise ValidationError(
                self.env._(
                    "La corrección debe estar vinculada al Beneficiario resultante."
                )
            )

        target_member = beneficiary.member_id

        if not target_member or target_member.club_person_type != "member":
            raise ValidationError(
                self.env._(
                    "Debe existir un Socio titular válido para registrar la corrección."
                )
            )

        if beneficiary.person_id != person:
            raise ValidationError(
                self.env._(
                    "El Beneficiario resultante debe corresponder "
                    "a la misma Persona corregida."
                )
            )

        if certificate and certificate.member_id != person:
            raise ValidationError(
                self.env._(
                    "El Certificado relacionado debe pertenecer a la Persona corregida."
                )
            )

        normalized_reason = (reason or "").strip()

        if not normalized_reason:
            raise ValidationError(
                self.env._("Debe indicar el motivo de la corrección de alta errónea.")
            )

        snapshot = dict(snapshot or {})

        old_member_code = (snapshot.get("member_code") or "").strip()

        if not old_member_code:
            raise ValidationError(
                self.env._(
                    "No se pudo conservar el código de asociado "
                    "anterior en la auditoría."
                )
            )

        id_number = (snapshot.get("id_number") or person.club_id_number or "").strip()

        if not id_number:
            raise ValidationError(
                self.env._("No se pudo conservar el carnet de la Persona corregida.")
            )

        vals = {
            "person_id": person.id,
            "person_name": (snapshot.get("person_name") or person.display_name),
            "id_number": id_number,
            "old_member_code": old_member_code,
            "old_member_state": (
                snapshot.get("member_state") or self.env._("Sin valor")
            ),
            "old_legal_state": (snapshot.get("legal_state") or False),
            "old_join_date": (snapshot.get("join_date") or False),
            "target_member_id": target_member.id,
            "beneficiary_id": beneficiary.id,
            "certificate_id": (certificate.id if certificate else False),
            "certificate_number": (
                snapshot.get("certificate_number")
                or (certificate.certificate_number if certificate else False)
            ),
            "reason": normalized_reason,
        }

        responsible_user_id = self.env.user.id

        return (
            self.sudo()
            .with_context(
                club_member_registration_correction_internal_create=True,
                club_member_registration_correction_user_id=(responsible_user_id),
            )
            .create(vals)
        )
