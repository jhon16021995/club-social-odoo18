from . import (
    beneficiary,
    beneficiary_transition,
    certificate,
    kardex,
    member_registration_correction,
    person_audit,
    res_partner,
    res_partner_identity,
)

# Este import debe ejecutarse después de las extensiones principales
# de res.partner porque habilita exclusivamente el flujo controlado
# de corrección de alta errónea de Socio.
# isort: off
from . import member_registration_correction_process
# isort: on
