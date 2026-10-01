{
    "name": "Club Social - Membership",
    "version": "18.0.1.0.0",
    "summary": "Gestión administrativa de socios del Club Social Petrolero Polanco",
    "category": "Services",
    "author": "Club Social Petrolero Polanco",
    "license": "LGPL-3",
    "depends": [
        "base",
        "contacts",
        "mail",
    ],
    "data": [
        "security/club_membership_security.xml",
        "security/ir.model.access.csv",
        "data/beneficiary_cron.xml",
        "views/res_partner_views.xml",
        "views/person_identity_correction_wizard_views.xml",
        "views/beneficiary_transition_wizard_views.xml",
        "views/certificate_views.xml",
        "views/kardex_views.xml",
    ],
    "application": True,
}
