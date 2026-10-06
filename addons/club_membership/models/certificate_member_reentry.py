from odoo import models
from odoo.exceptions import AccessError, ValidationError

_CERTIFICATE_MEMBER_REENTRY_INTERNAL_TOKEN = object()


class ClubCertificateMemberReentry(models.Model):
    _inherit = "club.certificate"  # pylint: disable=consider-merging-classes-inherited

    def _is_member_reentry_internal_write(self):
        return (
            self.env.context.get("club_certificate_member_reentry_internal_token")
            is _CERTIFICATE_MEMBER_REENTRY_INTERNAL_TOKEN
        )

    def _write_member_reentry_values_internal(
        self,
        vals,
        *,
        reason=False,
    ):
        return self.with_context(
            club_certificate_member_reentry_internal_token=(
                _CERTIFICATE_MEMBER_REENTRY_INTERNAL_TOKEN
            ),
            club_certificate_state_change_reason=reason or False,
        ).write(vals)

    def _check_member_withdrawal_write(
        self,
        vals,
        *,
        internal_member_withdrawal_write,
        internal_membership_end_write,
        internal_registration_error_void,
    ):
        if not self._is_member_reentry_internal_write():
            return super()._check_member_withdrawal_write(
                vals,
                internal_member_withdrawal_write=(internal_member_withdrawal_write),
                internal_membership_end_write=internal_membership_end_write,
                internal_registration_error_void=(internal_registration_error_void),
            )

        allowed_fields = {
            "state",
            "passive_by_membership_end",
        }

        if set(vals) - allowed_fields:
            raise AccessError(
                self.env._(
                    "El proceso interno de Reingreso solo puede restaurar "
                    "el estado causal del Certificado."
                )
            )

        if (
            vals.get("state") != "active"
            or vals.get("passive_by_membership_end") is not False
        ):
            raise AccessError(
                self.env._(
                    "La restauración del Certificado por Reingreso "
                    "requiere estado Activo y limpieza de la marca "
                    "de baja definitiva."
                )
            )

        for certificate in self:
            if (
                certificate.state != "passive"
                or not certificate.passive_by_membership_end
            ):
                raise ValidationError(
                    self.env._(
                        "Solo un Certificado Pasivo causado por baja "
                        "definitiva puede ser restaurado por Reingreso."
                    )
                )

        return None
