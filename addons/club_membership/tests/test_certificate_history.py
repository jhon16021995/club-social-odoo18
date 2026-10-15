from dateutil.relativedelta import relativedelta
from odoo import fields
from odoo.exceptions import AccessError, ValidationError
from odoo.tests import tagged
from odoo.tests.common import TransactionCase


@tagged("post_install", "-at_install")
class TestCertificateHistory(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()

        cls.admin = cls.env.ref("base.user_admin")
        cls.Partner = cls.env["res.partner"].with_user(cls.admin)
        cls.Certificate = cls.env["club.certificate"].with_user(cls.admin)

    @classmethod
    def _birthdate_for_age(cls, age):
        today = fields.Date.context_today(cls.Partner)
        return fields.Date.to_string(today - relativedelta(years=age))

    @classmethod
    def _next_available_id_number(cls, start):
        number = start

        while cls.Partner.search(
            [("club_id_number", "=", str(number))],
            limit=1,
        ):
            number += 1

        return str(number)

    @classmethod
    def _create_member(cls, name, start_number):
        today = fields.Date.context_today(cls.Partner)

        return cls.Partner.create(
            {
                "name": name,
                "company_type": "person",
                "is_company": False,
                "club_person_type": "member",
                "club_id_number": cls._next_available_id_number(start_number),
                "club_birthdate": cls._birthdate_for_age(40),
                "club_join_date": today,
            }
        )

    @classmethod
    def _create_certificate(cls, member):
        return cls.Certificate.create(
            {
                "member_id": member.id,
                "registration_origin": "new",
                "total_value": 1000.0,
                "opening_balance": 1000.0,
            }
        )

    def test_create_rejects_direct_withdrawal_marker(self):
        member = self._create_member(
            "Socio con intento de marca RET directa",
            99720000500,
        )

        for requested_value in (True, False):
            with self.env.cr.savepoint(), self.assertRaises(AccessError):
                self.Certificate.create(
                    {
                        "member_id": member.id,
                        "registration_origin": "new",
                        "total_value": 1000.0,
                        "opening_balance": 1000.0,
                        "state": "passive",
                        "passive_by_member_withdrawal": requested_value,
                    }
                )

        certificates = self.Certificate.search([("member_id", "=", member.id)])
        self.assertFalse(certificates)

    def test_create_rejects_direct_membership_end_marker(self):
        member = self._create_member(
            "Socio con intento de marca de baja directa",
            99720000600,
        )

        for requested_value in (True, False):
            with self.env.cr.savepoint(), self.assertRaises(AccessError):
                self.Certificate.create(
                    {
                        "member_id": member.id,
                        "registration_origin": "new",
                        "total_value": 1000.0,
                        "opening_balance": 1000.0,
                        "state": "passive",
                        "passive_by_membership_end": requested_value,
                    }
                )

        certificates = self.Certificate.search([("member_id", "=", member.id)])
        self.assertFalse(certificates)

    def test_new_active_certificate_is_allowed_after_historical_certificate(self):
        member = self._create_member(
            "Socio con Certificados históricos",
            99720000100,
        )

        historical_certificate = self._create_certificate(member)
        historical_certificate.write(
            {
                "state": "transferred",
            }
        )

        current_certificate = self._create_certificate(member)

        certificates = self.Certificate.search(
            [("member_id", "=", member.id)],
            order="id",
        )

        self.assertEqual(len(certificates), 2)
        self.assertEqual(historical_certificate.state, "transferred")
        self.assertEqual(current_certificate.state, "active")

    def test_certificate_owner_cannot_change_after_creation(self):
        original_member = self._create_member(
            "Socio titular original inmutable",
            99720000300,
        )
        replacement_member = self._create_member(
            "Socio receptor de intento de reasignacion",
            99720000400,
        )

        historical_certificate = self._create_certificate(original_member)
        historical_certificate.write({"state": "transferred"})

        active_certificate = self._create_certificate(original_member)

        for certificate in (
            active_certificate,
            historical_certificate,
        ):
            with self.subTest(state=certificate.state):
                with (
                    self.env.cr.savepoint(),
                    self.assertRaisesRegex(
                        ValidationError,
                        "no puede modificarse después",
                    ),
                ):
                    certificate.write({"member_id": replacement_member.id})

                certificate.invalidate_recordset(["member_id"])

                self.assertEqual(
                    certificate.member_id,
                    original_member,
                )

        self.assertEqual(
            self.Certificate.search_count([("member_id", "=", original_member.id)]),
            2,
        )
        self.assertEqual(
            self.Certificate.search_count([("member_id", "=", replacement_member.id)]),
            0,
        )

    def test_member_cannot_have_two_active_certificates(self):
        member = self._create_member(
            "Socio con intento de Certificado activo duplicado",
            99720000200,
        )

        self._create_certificate(member)

        with self.env.cr.savepoint(), self.assertRaises(ValidationError):
            self._create_certificate(member)

        active_certificates = self.Certificate.search(
            [
                ("member_id", "=", member.id),
                ("state", "=", "active"),
            ]
        )

        self.assertEqual(len(active_certificates), 1)

    def test_historical_certificate_cannot_become_active_if_another_is_active(self):
        member = self._create_member(
            "Socio con intento de reactivar Certificado histórico",
            99720000300,
        )

        historical_certificate = self.Certificate.create(
            {
                "member_id": member.id,
                "registration_origin": "new",
                "total_value": 1000.0,
                "opening_balance": 1000.0,
                "state": "transferred",
            }
        )

        current_certificate = self._create_certificate(member)

        with self.env.cr.savepoint(), self.assertRaises(ValidationError):
            historical_certificate.write(
                {
                    "state": "active",
                }
            )

        historical_certificate.invalidate_recordset()
        current_certificate.invalidate_recordset()

        self.assertEqual(historical_certificate.state, "transferred")
        self.assertEqual(current_certificate.state, "active")

    def test_historical_and_current_certificates_keep_member_id_number(self):
        member = self._create_member(
            "Socio con número de Certificado estable",
            99720000400,
        )

        historical_certificate = self._create_certificate(member)
        historical_certificate.write(
            {
                "state": "transferred",
            }
        )

        current_certificate = self._create_certificate(member)

        self.assertEqual(
            historical_certificate.certificate_number,
            member.club_id_number,
        )
        self.assertEqual(
            current_certificate.certificate_number,
            member.club_id_number,
        )
        self.assertEqual(
            historical_certificate.certificate_number,
            current_certificate.certificate_number,
        )
