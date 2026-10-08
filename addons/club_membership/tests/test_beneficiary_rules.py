from dateutil.relativedelta import relativedelta
from odoo import fields
from odoo.exceptions import ValidationError
from odoo.tests import tagged
from odoo.tests.common import TransactionCase


@tagged("post_install", "-at_install")
class TestBeneficiaryRules(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()

        cls.admin = cls.env.ref("base.user_admin")

        cls.Partner = cls.env["res.partner"].with_user(cls.admin)
        cls.Beneficiary = cls.env["club.beneficiary"].with_user(cls.admin)
        cls.Kardex = cls.env["club.kardex.event"].with_user(cls.admin)

        cls.member = cls._create_member(
            name="Socio titular prueba Beneficiarios",
            start_number=99200000100,
        )

    @classmethod
    def _next_available_id_number(cls, start):
        number = start

        while cls.Partner.search(
            [
                ("club_id_number", "=", str(number)),
            ],
            limit=1,
        ):
            number += 1

        return str(number)

    @classmethod
    def _birthdate_for_age(cls, age):
        today = fields.Date.context_today(cls.Partner)

        return fields.Date.to_string(today - relativedelta(years=age))

    @classmethod
    def _create_member(
        cls,
        name,
        start_number,
        state="active",
        is_company=False,
    ):
        vals = {
            "name": name,
            "company_type": ("company" if is_company else "person"),
            "is_company": is_company,
            "club_person_type": "member",
            "club_id_number": (cls._next_available_id_number(start_number)),
            "club_member_state": state,
        }

        if not is_company:
            vals["club_birthdate"] = cls._birthdate_for_age(40)

        return cls.Partner.create(vals)

    def _create_person(
        self,
        name,
        start_number,
        age=20,
    ):
        return self.Partner.create(
            {
                "name": name,
                "company_type": "person",
                "is_company": False,
                "club_id_number": (self._next_available_id_number(start_number)),
                "club_birthdate": (self._birthdate_for_age(age)),
            }
        )

    def _create_beneficiary(
        self,
        person,
        relationship="spouse",
        member=None,
        special_condition="none",
        relationship_detail=False,
    ):
        return self.Beneficiary.create(
            {
                "person_id": person.id,
                "member_id": (member or self.member).id,
                "relationship": relationship,
                "relationship_detail": (relationship_detail),
                "special_condition": (special_condition),
            }
        )

    def test_relationship_and_special_condition_catalog(self):
        relationship_keys = {
            key for key, _label in (self.Beneficiary._fields["relationship"].selection)
        }

        self.assertEqual(
            relationship_keys,
            {
                "spouse",
                "partner",
                "child",
                "stepchild",
                "parent",
                "worker",
                "family_dependent",
            },
        )

        special_condition_keys = {
            key
            for key, _label in (self.Beneficiary._fields["special_condition"].selection)
        }

        self.assertEqual(
            special_condition_keys,
            {
                "none",
                "health_dependent",
            },
        )

        self.assertNotIn(
            "sibling",
            relationship_keys,
        )
        self.assertNotIn(
            "other",
            relationship_keys,
        )
        self.assertNotIn(
            "legal_guardianship",
            special_condition_keys,
        )

    def test_family_dependent_requires_detail(self):
        person = self._create_person(
            "Familiar dependiente prueba",
            99200000200,
            age=20,
        )

        with self.assertRaises(ValidationError):
            self._create_beneficiary(
                person,
                relationship="family_dependent",
            )

        beneficiary = self._create_beneficiary(
            person,
            relationship="family_dependent",
            relationship_detail="Sobrino dependiente",
        )

        self.assertEqual(
            beneficiary.relationship,
            "family_dependent",
        )
        self.assertEqual(
            beneficiary.relationship_detail,
            "Sobrino dependiente",
        )

    def test_detail_is_cleared_for_other_relationships(self):
        person = self._create_person(
            "Cónyuge con detalle residual",
            99200000300,
            age=35,
        )

        beneficiary = self._create_beneficiary(
            person,
            relationship="spouse",
            relationship_detail="Dato que no corresponde",
        )

        self.assertFalse(beneficiary.relationship_detail)

    def test_health_condition_is_allowed_for_non_age_limited_relationship(self):
        person = self._create_person(
            "Padre dependiente por salud",
            99200000400,
            age=65,
        )

        beneficiary = self._create_beneficiary(
            person,
            relationship="parent",
            special_condition="health_dependent",
        )

        self.assertEqual(
            beneficiary.state,
            "active",
        )
        self.assertEqual(
            beneficiary.special_condition,
            "health_dependent",
        )

    def test_worker_requires_company_member(self):
        worker_person = self._create_person(
            "Trabajador prueba",
            99200000500,
            age=30,
        )

        with self.assertRaises(ValidationError):
            self._create_beneficiary(
                worker_person,
                relationship="worker",
            )

        company_member = self._create_member(
            name="Empresa socia prueba",
            start_number=99200000600,
            is_company=True,
        )

        beneficiary = self._create_beneficiary(
            worker_person,
            relationship="worker",
            member=company_member,
        )

        self.assertEqual(
            beneficiary.member_id,
            company_member,
        )
        self.assertEqual(
            beneficiary.relationship,
            "worker",
        )

    def test_age_limited_relationship_rejects_age_25_without_health(self):
        person = self._create_person(
            "Hijo de 25 años",
            99200000700,
            age=25,
        )

        with self.assertRaises(ValidationError):
            self._create_beneficiary(
                person,
                relationship="child",
            )

        beneficiary = self._create_beneficiary(
            person,
            relationship="child",
            special_condition="health_dependent",
        )

        self.assertEqual(
            beneficiary.state,
            "active",
        )
        self.assertEqual(
            beneficiary.special_condition,
            "health_dependent",
        )

    def test_removing_health_after_age_25_finalizes_link(self):
        person = self._create_person(
            "Hijastro mayor con salud",
            99200000800,
            age=30,
        )

        beneficiary = self._create_beneficiary(
            person,
            relationship="stepchild",
            special_condition="health_dependent",
        )

        beneficiary.write(
            {
                "special_condition": "none",
            }
        )

        beneficiary.invalidate_recordset()

        self.assertEqual(
            beneficiary.state,
            "finalized",
        )
        self.assertTrue(beneficiary.end_date)
        self.assertEqual(
            beneficiary.end_reason,
            ("Fin de condición especial con límite de edad cumplido"),
        )
        self.assertFalse(beneficiary.block_reason)

        event = self.Kardex.search(
            [
                (
                    "beneficiary_id",
                    "=",
                    beneficiary.id,
                ),
                (
                    "event_type",
                    "=",
                    "beneficiary_finalized",
                ),
            ],
            order="id desc",
            limit=1,
        )

        self.assertTrue(event)
        self.assertEqual(
            event.origin,
            "automatic",
        )
        self.assertEqual(
            event.reason,
            beneficiary.end_reason,
        )

    def test_cron_finalizes_age_limited_current_link(self):
        person = self._create_person(
            "Familiar que alcanzará límite de edad",
            99200000900,
            age=24,
        )

        beneficiary = self._create_beneficiary(
            person,
            relationship="family_dependent",
            relationship_detail="Familiar a cargo",
        )

        self.assertEqual(
            beneficiary.state,
            "active",
        )
        self.assertLess(
            person.club_age,
            25,
        )

        # El vínculo nació válidamente antes de los 25 años.
        # Modificamos solo la fecha en la transacción de prueba para
        # simular el paso del tiempo sin ejecutar un write funcional.
        simulated_birthdate = self._birthdate_for_age(30)

        self.env.cr.execute(
            """
            UPDATE res_partner
               SET club_birthdate = %s
             WHERE id = %s
            """,
            (
                simulated_birthdate,
                person.id,
            ),
        )

        self.env.invalidate_all()

        person = self.Partner.browse(person.id)
        beneficiary = self.Beneficiary.browse(beneficiary.id)

        self.assertGreaterEqual(
            person.club_age,
            25,
        )
        self.assertEqual(
            beneficiary.state,
            "active",
        )
        self.assertEqual(
            beneficiary.special_condition,
            "none",
        )

        self.Beneficiary._cron_finalize_age_limit_beneficiaries()  # pylint: disable=protected-access

        beneficiary.invalidate_recordset()

        self.assertEqual(
            beneficiary.state,
            "finalized",
        )
        self.assertTrue(beneficiary.end_date)
        self.assertEqual(
            beneficiary.end_reason,
            "Límite de edad alcanzado",
        )
        self.assertFalse(beneficiary.block_reason)

        event = self.Kardex.search(
            [
                (
                    "beneficiary_id",
                    "=",
                    beneficiary.id,
                ),
                (
                    "event_type",
                    "=",
                    "beneficiary_finalized",
                ),
            ],
            order="id desc",
            limit=1,
        )

        self.assertTrue(event)
        self.assertEqual(
            event.origin,
            "automatic",
        )
        self.assertEqual(
            event.reason,
            "Límite de edad alcanzado",
        )

    def test_member_cannot_be_current_beneficiary_even_if_passive(self):
        active_member = self._create_member(
            name="Socio activo no puede ser Beneficiario",
            start_number=99200001000,
            state="active",
        )

        with self.assertRaises(ValidationError):
            self._create_beneficiary(
                active_member,
                relationship="spouse",
            )

        passive_member = self._create_member(
            name="Socio Pasivo tampoco puede ser Beneficiario",
            start_number=99200001001,
            state="inactive",
        )

        with (
            self.assertRaisesRegex(
                ValidationError,
                "incluso si se encuentra Pasivo",
            ),
            self.env.cr.savepoint(),
        ):
            self._create_beneficiary(
                passive_member,
                relationship="spouse",
            )

        self.assertFalse(
            self.Beneficiary.search(
                [
                    ("person_id", "=", passive_member.id),
                    ("state", "in", ("active", "blocked")),
                ],
                limit=1,
            )
        )

        passive_member.invalidate_recordset()
        self.assertEqual(passive_member.club_member_state, "inactive")

    def test_direct_finalization_is_blocked_but_controlled_flow_works(self):
        person = self._create_person(
            "Beneficiario finalización controlada",
            99200001100,
            age=32,
        )

        beneficiary = self._create_beneficiary(
            person,
            relationship="partner",
        )

        today = fields.Date.context_today(beneficiary)

        with self.assertRaises(ValidationError):
            beneficiary.write(
                {
                    "state": "finalized",
                    "end_date": today,
                    "end_reason": "Intento directo",
                }
            )

        beneficiary.invalidate_recordset()

        self.assertEqual(
            beneficiary.state,
            "active",
        )

        beneficiary.finalize_link(
            end_date=today,
            reason="Finalización administrativa de prueba",
        )

        beneficiary.invalidate_recordset()

        self.assertEqual(
            beneficiary.state,
            "finalized",
        )
        self.assertEqual(
            beneficiary.end_reason,
            "Finalización administrativa de prueba",
        )

        events = self.Kardex.search(
            [
                (
                    "beneficiary_id",
                    "=",
                    beneficiary.id,
                ),
                (
                    "event_type",
                    "=",
                    "beneficiary_finalized",
                ),
            ]
        )

        self.assertEqual(
            len(events),
            1,
        )
        self.assertEqual(
            events.origin,
            "manual",
        )

    def test_convert_beneficiary_to_member_reuses_same_person(self):
        person = self._create_person(
            "Beneficiario convertido en Socio",
            99200001200,
            age=33,
        )

        original_id = person.id
        original_carnet = person.club_id_number

        beneficiary = self._create_beneficiary(
            person,
            relationship="spouse",
        )

        beneficiary.action_convert_to_member()

        person.invalidate_recordset()
        beneficiary.invalidate_recordset()

        self.assertEqual(
            person.id,
            original_id,
        )
        self.assertEqual(
            person.club_person_type,
            "member",
        )
        self.assertEqual(
            person.club_member_code,
            original_carnet,
        )
        self.assertEqual(
            person.club_member_state,
            "active",
        )

        self.assertEqual(
            self.Partner.search_count(
                [
                    (
                        "club_id_number",
                        "=",
                        original_carnet,
                    ),
                ]
            ),
            1,
        )

        self.assertEqual(
            beneficiary.state,
            "finalized",
        )
        self.assertEqual(
            beneficiary.end_reason,
            "Conversión a Socio",
        )
        self.assertEqual(
            beneficiary.converted_member_id,
            person,
        )
        self.assertTrue(beneficiary.converted_at)

        original_member_conversion_events = self.Kardex.search(
            [
                (
                    "member_id",
                    "=",
                    self.member.id,
                ),
                (
                    "beneficiary_id",
                    "=",
                    beneficiary.id,
                ),
                (
                    "event_type",
                    "=",
                    "beneficiary_converted",
                ),
            ]
        )

        self.assertEqual(
            len(original_member_conversion_events),
            1,
        )

        new_member_origin_events = self.Kardex.search(
            [
                (
                    "member_id",
                    "=",
                    person.id,
                ),
                (
                    "beneficiary_id",
                    "=",
                    beneficiary.id,
                ),
                (
                    "event_type",
                    "=",
                    "member_created_from_beneficiary",
                ),
            ]
        )

        self.assertEqual(
            len(new_member_origin_events),
            1,
        )

        generic_finalization_events = self.Kardex.search(
            [
                (
                    "beneficiary_id",
                    "=",
                    beneficiary.id,
                ),
                (
                    "event_type",
                    "=",
                    "beneficiary_finalized",
                ),
            ]
        )

        self.assertFalse(generic_finalization_events)

    def test_convert_blocked_beneficiary_to_member(self):
        person = self._create_person(
            "Beneficiario bloqueado convertido en Socio",
            99200001300,
            age=34,
        )

        original_carnet = person.club_id_number

        beneficiary = self._create_beneficiary(
            person,
            relationship="partner",
        )

        beneficiary.write(
            {
                "state": "blocked",
                "block_reason": "Bloqueo administrativo de prueba",
            }
        )

        beneficiary.invalidate_recordset()

        self.assertEqual(
            beneficiary.state,
            "blocked",
        )

        beneficiary.action_convert_to_member()

        person.invalidate_recordset()
        beneficiary.invalidate_recordset()

        self.assertEqual(
            person.club_person_type,
            "member",
        )
        self.assertEqual(
            person.club_member_code,
            original_carnet,
        )
        self.assertEqual(
            beneficiary.state,
            "finalized",
        )
        self.assertEqual(
            beneficiary.end_reason,
            "Conversión a Socio",
        )
        self.assertFalse(
            beneficiary.block_reason,
        )
        self.assertEqual(
            beneficiary.converted_member_id,
            person,
        )

    def test_convert_finalized_beneficiary_to_member_preserves_history(self):
        person = self._create_person(
            "Beneficiario histórico convertido en Socio",
            99200001400,
            age=36,
        )

        original_id = person.id
        original_carnet = person.club_id_number

        beneficiary = self._create_beneficiary(
            person,
            relationship="spouse",
        )

        today = fields.Date.context_today(beneficiary)
        historical_reason = "Finalización histórica previa"

        beneficiary.finalize_link(
            end_date=today,
            reason=historical_reason,
        )

        beneficiary.invalidate_recordset()

        original_end_date = beneficiary.end_date
        original_end_reason = beneficiary.end_reason

        beneficiary.action_convert_to_member()

        person.invalidate_recordset()
        beneficiary.invalidate_recordset()

        self.assertEqual(
            person.id,
            original_id,
        )
        self.assertEqual(
            person.club_id_number,
            original_carnet,
        )
        self.assertEqual(
            person.club_person_type,
            "member",
        )
        self.assertEqual(
            person.club_member_code,
            original_carnet,
        )

        self.assertEqual(
            beneficiary.state,
            "finalized",
        )
        self.assertEqual(
            beneficiary.end_date,
            original_end_date,
        )
        self.assertEqual(
            beneficiary.end_reason,
            original_end_reason,
        )
        self.assertEqual(
            beneficiary.end_reason,
            historical_reason,
        )
        self.assertEqual(
            beneficiary.converted_member_id,
            person,
        )
        self.assertTrue(
            beneficiary.converted_at,
        )

        self.assertEqual(
            self.Partner.search_count(
                [
                    (
                        "club_id_number",
                        "=",
                        original_carnet,
                    ),
                ]
            ),
            1,
        )

    def test_finalized_beneficiary_can_create_new_link_reusing_person(self):
        person = self._create_person(
            "Beneficiario histórico con nuevo vínculo",
            99200001500,
            age=38,
        )

        original_carnet = person.club_id_number

        beneficiary = self._create_beneficiary(
            person,
            relationship="spouse",
        )

        today = fields.Date.context_today(beneficiary)

        beneficiary.finalize_link(
            end_date=today,
            reason="Cierre del vínculo anterior",
        )

        beneficiary.invalidate_recordset()

        historical_state = beneficiary.state
        historical_end_date = beneficiary.end_date
        historical_end_reason = beneficiary.end_reason

        new_member = self._create_member(
            name="Nuevo Socio titular para vínculo histórico",
            start_number=99200001600,
        )

        new_link = beneficiary.create_new_link(
            {
                "new_member_id": new_member.id,
                "relationship": "partner",
                "special_condition": "none",
                "start_date": today,
            }
        )

        beneficiary.invalidate_recordset()
        person.invalidate_recordset()
        new_link.invalidate_recordset()

        self.assertNotEqual(
            new_link.id,
            beneficiary.id,
        )
        self.assertEqual(
            new_link.person_id,
            person,
        )
        self.assertEqual(
            new_link.member_id,
            new_member,
        )
        self.assertEqual(
            new_link.relationship,
            "partner",
        )
        self.assertEqual(
            new_link.state,
            "active",
        )

        self.assertEqual(
            beneficiary.state,
            historical_state,
        )
        self.assertEqual(
            beneficiary.end_date,
            historical_end_date,
        )
        self.assertEqual(
            beneficiary.end_reason,
            historical_end_reason,
        )

        self.assertEqual(
            person.club_id_number,
            original_carnet,
        )
        self.assertEqual(
            self.Partner.search_count(
                [
                    (
                        "club_id_number",
                        "=",
                        original_carnet,
                    ),
                ]
            ),
            1,
        )

        current_links = self.Beneficiary.search(
            [
                ("person_id", "=", person.id),
                ("state", "in", ("active", "blocked")),
            ]
        )

        self.assertEqual(
            current_links,
            new_link,
        )

    def test_new_link_is_blocked_when_person_already_has_current_link(self):
        person = self._create_person(
            "Beneficiario con vínculo vigente existente",
            99200001700,
            age=39,
        )

        historical_link = self._create_beneficiary(
            person,
            relationship="spouse",
        )

        today = fields.Date.context_today(historical_link)

        historical_link.finalize_link(
            end_date=today,
            reason="Vínculo histórico finalizado",
        )

        current_member = self._create_member(
            name="Socio titular del vínculo vigente",
            start_number=99200001800,
        )

        current_link = self._create_beneficiary(
            person,
            relationship="partner",
            member=current_member,
        )

        current_link.write(
            {
                "state": "blocked",
                "block_reason": "Bloqueo administrativo de prueba",
            }
        )

        another_member = self._create_member(
            name="Otro Socio titular de prueba",
            start_number=99200001900,
        )

        with self.assertRaises(ValidationError):
            historical_link.create_new_link(
                {
                    "new_member_id": another_member.id,
                    "relationship": "spouse",
                    "special_condition": "none",
                    "start_date": today,
                }
            )

        historical_link.invalidate_recordset()
        current_link.invalidate_recordset()

        self.assertEqual(
            historical_link.state,
            "finalized",
        )
        self.assertEqual(
            current_link.state,
            "blocked",
        )
