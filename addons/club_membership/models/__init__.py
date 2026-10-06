from . import (
    beneficiary,
    beneficiary_transition,
    certificate,
    certificate_member_reentry,
    kardex,
    member_registration_correction,
    membership_period,
    person_audit,
    res_partner,
    res_partner_client_to_member_conversion,
    res_partner_identity,
    res_partner_member_reactivation,
    res_partner_membership_end,
    res_partner_membership_period,
)

# Esta extensión debe cargarse después de
# res_partner_membership_period porque reemplaza exclusivamente
# la creación automática del período inicial durante Reingreso.
# isort: off
from . import res_partner_member_reentry
# isort: on

# Este import debe ejecutarse después de las extensiones principales
# de res.partner porque habilita exclusivamente el flujo controlado
# de corrección de alta errónea de Socio.
# isort: off
from . import member_registration_correction_process
# isort: on
