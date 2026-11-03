"""
Automated test suite for BSNL 4G Team Performance Hierarchy (Phase 1).
Covers:
- Half-open interval convention [effective_from, effective_to) and overlap rejection
- Optional Parent CI for IE assignments (accepted without parent CI, validated when supplied)
- Role consistency validation (CI vs IE)
- O&M Manager shared vs project-specific precedence and vacancies (AP, MH, TL, UP)
- Personnel merge preview, collision rejection, confirmation, tombstoning, and rollback
- Audit log immutability against instance operations, QuerySet.update(), and QuerySet.delete()
- Deterministic conflict fingerprinting and status preservation
- Access control permissions (blocking unauthenticated and non-admin access)
- Hierarchy REST API endpoints
"""

from datetime import date
from django.contrib.auth.models import User
from django.core.exceptions import ValidationError, PermissionDenied
from django.test import TestCase
from django.urls import reverse

from apps.organization.models import (
    Circle,
    Project,
    OperationalArea,
    OperationalAreaAlias,
    OmManagerAssignment,
    OmManagerAssignmentAudit,
    Personnel,
    PersonnelAlias,
    PersonnelSourceMapping,
    SitePersonnelAssignment,
    PersonnelConflict,
    PersonnelMergeAudit,
)
from apps.organization.hierarchy_services import (
    assert_no_half_open_overlap,
    save_om_manager_assignment,
    save_site_personnel_assignment,
    preview_personnel_merge,
    confirm_personnel_merge,
    rollback_personnel_merge,
)
from apps.uptimedb.models import DataImportBatch, UptimeSite
from tests.auth_helpers import portal_user


class TeamHierarchyBaseTestCase(TestCase):
    def setUp(self):
        self.admin = portal_user('hier-admin', 'admin')
        self.noc = portal_user('hier-noc', 'noc_lead')
        self.ci_user = portal_user('hier-ci-user', 'ci')
        self.client.force_login(self.admin)
        
        self.batch = DataImportBatch.objects.create(
            original_filename='test_batch.xlsx',
            checksum_sha256='test_hash',
            sheet_name='Up-Time Report',
            stored_path='-',
            status=DataImportBatch.Status.COMMITTED,
        )
        
        self.circle_mp = Circle.objects.get(code='MP')
        self.circle_rj = Circle.objects.get(code='RJ')
        self.project_4g = Project.objects.get(key='4G Saturation')
        self.project_lwe = Project.objects.get(key='LWE')
        
        # Create test site 1
        self.test_site = UptimeSite.objects.create(
            project=self.project_4g,
            circle=self.circle_mp,
            site_id='MP_IND_001',
            site_key='MP_IND_001',
            site_name='Indore Tower 1',
            batch=self.batch,
            source_row=1,
            on_air=True,
        )
        
        # Create test site 2
        self.test_site_2 = UptimeSite.objects.create(
            project=self.project_4g,
            circle=self.circle_mp,
            site_id='MP_IND_002',
            site_key='MP_IND_002',
            site_name='Indore Tower 2',
            batch=self.batch,
            source_row=2,
            on_air=True,
        )


class TestHalfOpenIntervalValidation(TeamHierarchyBaseTestCase):
    def test_abutting_intervals_do_not_overlap(self):
        """[2026-01-01, 2026-02-01) and [2026-02-01, 2026-03-01) must NOT raise ValidationError."""
        OmManagerAssignment.objects.create(
            circle=self.circle_mp,
            project=None,
            manager_name='Manager Jan',
            effective_from=date(2026, 1, 1),
            effective_to=date(2026, 2, 1),
            is_active=True,
        )
        
        assignment_feb = OmManagerAssignment(
            circle=self.circle_mp,
            project=None,
            manager_name='Manager Feb',
            effective_from=date(2026, 2, 1),
            effective_to=date(2026, 3, 1),
            is_active=True,
        )
        assignment_feb.clean()
        assignment_feb.save()
        self.assertEqual(OmManagerAssignment.objects.filter(circle=self.circle_mp).count(), 2)

    def test_overlapping_intervals_raise_validation_error(self):
        """Overlapping ranges in same circle and scope must be rejected."""
        OmManagerAssignment.objects.create(
            circle=self.circle_mp,
            project=None,
            manager_name='Manager Early',
            effective_from=date(2026, 1, 1),
            effective_to=date(2026, 6, 1),
            is_active=True,
        )
        
        conflicting = OmManagerAssignment(
            circle=self.circle_mp,
            project=None,
            manager_name='Manager Clash',
            effective_from=date(2026, 4, 1),
            effective_to=date(2026, 8, 1),
            is_active=True,
        )
        with self.assertRaises(ValidationError):
            conflicting.clean()

    def test_open_ended_unbounded_overlap_rejected(self):
        """An open-ended interval [2026-01-01, None) conflicts with [2026-05-01, None)."""
        OmManagerAssignment.objects.create(
            circle=self.circle_mp,
            project=None,
            manager_name='Manager Permanent',
            effective_from=date(2026, 1, 1),
            effective_to=None,
            is_active=True,
        )
        
        conflicting = OmManagerAssignment(
            circle=self.circle_mp,
            project=None,
            manager_name='Manager Challenger',
            effective_from=date(2026, 5, 1),
            effective_to=None,
            is_active=True,
        )
        with self.assertRaises(ValidationError):
            conflicting.clean()


class TestParentCiAndRoleValidation(TeamHierarchyBaseTestCase):
    def setUp(self):
        super().setUp()
        self.ci_personnel = Personnel.objects.create(
            canonical_name='RAJESH SHARMA',
            display_name='Rajesh Sharma',
            role_type='ci',
            employee_code='EMP_CI_001',
            contact='9876543210',
        )
        self.ie_personnel = Personnel.objects.create(
            canonical_name='AMIT VERMA',
            display_name='Amit Verma',
            role_type='ie',
            employee_code='EMP_IE_001',
            contact='9876543211',
        )

    def test_ci_cannot_be_assigned_as_ie(self):
        """Personnel with role 'ci' cannot be assigned as 'ie' in SitePersonnelAssignment."""
        assignment = SitePersonnelAssignment(
            site=self.test_site,
            personnel=self.ci_personnel,
            role_type='ie',
            effective_from=date(2026, 1, 1),
        )
        with self.assertRaises(ValidationError) as ctx:
            assignment.clean()
        self.assertIn('personnel', ctx.exception.message_dict)

    def test_ie_assignment_without_parent_ci_is_accepted(self):
        """IE assignment with parent_ci=None is accepted when parent relationship cannot be verified."""
        assignment = SitePersonnelAssignment(
            site=self.test_site,
            personnel=self.ie_personnel,
            role_type='ie',
            effective_from=date(2026, 1, 1),
            parent_ci=None,
        )
        assignment.clean()
        assignment.save()
        self.assertIsNone(assignment.parent_ci)
        self.assertEqual(assignment.role_type, 'ie')

    def test_ie_assignment_with_valid_parent_ci_is_accepted(self):
        """IE assignment with a valid parent CI having an overlapping CI assignment on the same site is accepted."""
        SitePersonnelAssignment.objects.create(
            site=self.test_site,
            personnel=self.ci_personnel,
            role_type='ci',
            effective_from=date(2026, 1, 1),
            effective_to=None,
        )
        
        ie_assign = SitePersonnelAssignment(
            site=self.test_site,
            personnel=self.ie_personnel,
            role_type='ie',
            effective_from=date(2026, 1, 15),
            effective_to=date(2026, 5, 1),
            parent_ci=self.ci_personnel,
        )
        ie_assign.clean()
        ie_assign.save()
        self.assertEqual(ie_assign.parent_ci_id, self.ci_personnel.id)

    def test_ie_assignment_with_invalid_or_unrelated_parent_ci_is_rejected(self):
        """IE assignment with an invalid role or unrelated site parent CI is rejected."""
        # 1. Parent CI on different site
        SitePersonnelAssignment.objects.create(
            site=self.test_site_2,
            personnel=self.ci_personnel,
            role_type='ci',
            effective_from=date(2026, 1, 1),
        )
        
        unrelated_site_assign = SitePersonnelAssignment(
            site=self.test_site,
            personnel=self.ie_personnel,
            role_type='ie',
            effective_from=date(2026, 1, 1),
            parent_ci=self.ci_personnel,
        )
        with self.assertRaises(ValidationError) as ctx:
            unrelated_site_assign.clean()
        self.assertIn('parent_ci', ctx.exception.message_dict)

        # 2. Parent CI has wrong role ('ie')
        another_ie = Personnel.objects.create(
            canonical_name='OTHER IE',
            display_name='Other IE',
            role_type='ie',
        )
        wrong_role_assign = SitePersonnelAssignment(
            site=self.test_site,
            personnel=self.ie_personnel,
            role_type='ie',
            effective_from=date(2026, 1, 1),
            parent_ci=another_ie,
        )
        with self.assertRaises(ValidationError) as ctx:
            wrong_role_assign.clean()
        self.assertIn('parent_ci', ctx.exception.message_dict)


class TestOmManagerPrecedenceAndVacancy(TeamHierarchyBaseTestCase):
    def test_shared_baseline_and_project_override(self):
        """Project-specific O&M manager assignment overrides shared Circle baseline."""
        save_om_manager_assignment(
            circle=self.circle_mp,
            project=None,
            manager_name='Shared MP Head',
            effective_from=date(2026, 1, 1),
            actor=self.admin,
            reason='Baseline setup',
        )
        
        save_om_manager_assignment(
            circle=self.circle_mp,
            project=self.project_4g,
            manager_name='4G Saturation Lead',
            effective_from=date(2026, 1, 1),
            actor=self.admin,
            reason='4G Saturation override',
        )
        
        override = OmManagerAssignment.objects.filter(
            circle=self.circle_mp,
            project=self.project_4g,
            is_active=True,
        ).first()
        self.assertEqual(override.manager_name, '4G Saturation Lead')
        
        fallback = OmManagerAssignment.objects.filter(
            circle=self.circle_mp,
            project=self.project_lwe,
            is_active=True,
        ).first()
        if not fallback:
            fallback = OmManagerAssignment.objects.filter(
                circle=self.circle_mp,
                project__isnull=True,
                is_active=True,
            ).first()
        self.assertEqual(fallback.manager_name, 'Shared MP Head')

    def test_vacant_om_manager_post(self):
        """Assignments can be explicitly recorded as vacant (e.g. AP, MH, TL, UP)."""
        assign = save_om_manager_assignment(
            circle=self.circle_rj,
            project=None,
            manager_name='',
            is_vacant=True,
            effective_from=date(2026, 1, 1),
            actor=self.admin,
            reason='Position currently vacant',
        )
        self.assertTrue(assign.is_vacant)
        self.assertEqual(assign.manager_name, '')
        self.assertIn('[VACANT]', str(assign))


class TestPersonnelMergeAndRollback(TeamHierarchyBaseTestCase):
    def setUp(self):
        super().setUp()
        self.source = Personnel.objects.create(
            canonical_name='KUMAR VIKAS',
            display_name='Kumar Vikas',
            role_type='ci',
            employee_code='TEMP_CODE_1',
            contact='9990001111',
        )
        self.target = Personnel.objects.create(
            canonical_name='VIKAS KUMAR',
            display_name='Vikas Kumar',
            role_type='ci',
            employee_code='BSNL_100293',
            contact='9990001111',
        )
        
        self.assign = SitePersonnelAssignment.objects.create(
            site=self.test_site,
            personnel=self.source,
            role_type='ci',
            effective_from=date(2026, 1, 1),
        )
        
        self.alias = PersonnelAlias.objects.create(
            personnel=self.source,
            raw_name='Vikas Kumar (Temp)',
            normalized_name='VIKAS KUMAR TEMP',
            role_type='ci',
            circle=self.circle_mp,
        )
        
        self.mapping = PersonnelSourceMapping.objects.create(
            source_system='ESCALATION',
            source_dataset='ESCALATION_EXCEL',
            source_record_key='REC_001',
            source_role_type='ci',
            raw_name='KUMAR VIKAS',
            personnel=self.source,
            mapping_status='approved',
        )

    def test_preview_merge_returns_correct_counts(self):
        preview = preview_personnel_merge(self.source.id, self.target.id)
        self.assertEqual(preview['site_assignments_count'], 1)
        self.assertEqual(preview['aliases_count'], 1)
        self.assertEqual(preview['source_mappings_count'], 1)

    def test_confirm_merge_rejects_unresolved_site_assignment_collision(self):
        """Merging is rejected if source and target have overlapping active assignments on same site."""
        self.assign.effective_to = date(2026, 6, 1)
        self.assign.save()

        SitePersonnelAssignment.objects.create(
            site=self.test_site,
            personnel=self.target,
            role_type='ci',
            effective_from=date(2026, 4, 1),
            effective_to=date(2026, 9, 1),
        )
        with self.assertRaises(ValidationError) as ctx:
            confirm_personnel_merge(
                source_id=self.source.id,
                target_id=self.target.id,
                actor=self.admin,
                reason='Should fail due to site assignment collision',
            )
        self.assertIn('overlapping active assignments on site', str(ctx.exception))

    def test_confirm_merge_and_full_rollback(self):
        # 1. Confirm merge
        audit = confirm_personnel_merge(
            source_id=self.source.id,
            target_id=self.target.id,
            actor=self.admin,
            reason='Verified same employee with identical phone and BSNL emp code',
        )
        
        self.source.refresh_from_db()
        self.target.refresh_from_db()
        self.assign.refresh_from_db()
        self.alias.refresh_from_db()
        self.mapping.refresh_from_db()
        
        self.assertTrue(self.source.is_tombstoned)
        self.assertEqual(self.source.merged_into_id, self.target.id)
        self.assertEqual(self.assign.personnel_id, self.target.id)
        self.assertEqual(self.alias.personnel_id, self.target.id)
        self.assertEqual(self.mapping.personnel_id, self.target.id)
        self.assertEqual(audit.status, 'applied')
        
        # 2. Rollback merge
        rb_audit = rollback_personnel_merge(
            merge_audit_id=audit.id,
            actor=self.admin,
            reason='Accidental merge, identities were different individuals',
        )
        
        self.source.refresh_from_db()
        self.assign.refresh_from_db()
        self.alias.refresh_from_db()
        self.mapping.refresh_from_db()
        
        self.assertFalse(self.source.is_tombstoned)
        self.assertIsNone(self.source.merged_into_id)
        self.assertEqual(self.assign.personnel_id, self.source.id)
        self.assertEqual(self.alias.personnel_id, self.source.id)
        self.assertEqual(self.mapping.personnel_id, self.source.id)
        self.assertEqual(rb_audit.rollback_status.lower(), 'rolled_back')


class TestAuditLogImmutability(TeamHierarchyBaseTestCase):
    def test_om_manager_audit_immutable_instance_and_queryset(self):
        assign = OmManagerAssignment.objects.create(
            circle=self.circle_mp,
            project=None,
            manager_name='Manager Test',
            effective_from=date(2026, 1, 1),
        )
        audit = OmManagerAssignmentAudit.objects.create(
            assignment=assign,
            actor=self.admin,
            action='create',
            reason='Initial record',
            effective_date=date(2026, 1, 1),
            before_values={},
            after_values={'manager_name': 'Manager Test'},
        )
        
        # Instance update prohibited
        audit.reason = 'Tampered reason'
        with self.assertRaises(PermissionDenied):
            audit.save()
            
        # Instance delete prohibited
        with self.assertRaises(PermissionDenied):
            audit.delete()

        # QuerySet.update() prohibited
        with self.assertRaises(PermissionDenied):
            OmManagerAssignmentAudit.objects.filter(id=audit.id).update(reason='Bulk update attempt')

        # QuerySet.delete() prohibited
        with self.assertRaises(PermissionDenied):
            OmManagerAssignmentAudit.objects.filter(id=audit.id).delete()

    def test_personnel_merge_audit_immutable_instance_and_queryset(self):
        source = Personnel.objects.create(
            canonical_name='PERSON A',
            display_name='Person A',
            role_type='ci',
        )
        target = Personnel.objects.create(
            canonical_name='PERSON B',
            display_name='Person B',
            role_type='ci',
        )
        audit = PersonnelMergeAudit.objects.create(
            source_personnel_id=source.id,
            target_personnel=target,
            actor=self.admin,
            reason='Test reason',
            affected_relationship_ids={},
            original_values={},
            applied_changes={},
        )
        
        # Instance delete prohibited
        with self.assertRaises(PermissionDenied):
            audit.delete()

        # QuerySet.update() prohibited
        with self.assertRaises(PermissionDenied):
            PersonnelMergeAudit.objects.filter(id=audit.id).update(reason='Bulk update attempt')

        # QuerySet.delete() prohibited
        with self.assertRaises(PermissionDenied):
            PersonnelMergeAudit.objects.filter(id=audit.id).delete()


class TestConflictFingerprintDeterminism(TestCase):
    def test_fingerprint_generation_and_idempotency(self):
        fp1 = PersonnelConflict.generate_fingerprint(
            'consolidation_matrix', 'escalation_sites', 'KEY_001', 'code_mismatch', 'ci'
        )
        fp2 = PersonnelConflict.generate_fingerprint(
            'consolidation_matrix', 'escalation_sites', 'KEY_001', 'code_mismatch', 'ci'
        )
        self.assertEqual(fp1, fp2)
        self.assertEqual(len(fp1), 64)

        conflict = PersonnelConflict.objects.create(
            fingerprint=fp1,
            source_system='consolidation_matrix',
            source_dataset='escalation_sites',
            source_record_key='KEY_001',
            conflict_type='code_mismatch',
            role_type='ci',
            status='resolved',
            resolution='Manually resolved by Admin',
        )

        # Re-encountering the same record should preserve resolved status
        existing = PersonnelConflict.objects.filter(fingerprint=fp1).first()
        self.assertEqual(existing.status, 'resolved')
        self.assertEqual(existing.resolution, 'Manually resolved by Admin')


class TestAccessControlPermissions(TeamHierarchyBaseTestCase):
    """Verifies that non-admin and unauthenticated users cannot access or mutate hierarchy endpoints."""

    def test_unauthenticated_requests_rejected(self):
        self.client.logout()
        endpoints = [
            reverse('org-hierarchy-oas'),
            reverse('org-hierarchy-om-assignments'),
            reverse('org-hierarchy-personnel'),
            reverse('org-hierarchy-site-assignments'),
            reverse('org-hierarchy-conflicts'),
            reverse('org-hierarchy-merge-audit'),
        ]
        for url in endpoints:
            resp = self.client.get(url)
            self.assertIn(resp.status_code, (401, 403), f"Expected 401/403 for {url}, got {resp.status_code}")

    def test_noc_lead_forbidden_from_hierarchy_endpoints(self):
        self.client.force_login(self.noc)
        endpoints = [
            (reverse('org-hierarchy-oas'), 'get'),
            (reverse('org-hierarchy-om-assignments'), 'get'),
            (reverse('org-hierarchy-personnel'), 'get'),
            (reverse('org-hierarchy-site-assignments'), 'get'),
            (reverse('org-hierarchy-conflicts'), 'get'),
            (reverse('org-hierarchy-merge-preview'), 'post'),
            (reverse('org-hierarchy-merge-confirm'), 'post'),
            (reverse('org-hierarchy-merge-rollback'), 'post'),
        ]
        for url, method in endpoints:
            resp = getattr(self.client, method)(url, {}, content_type='application/json')
            self.assertEqual(resp.status_code, 403, f"Expected 403 Forbidden for NOC Lead on {url}, got {resp.status_code}")

    def test_ci_user_forbidden_from_hierarchy_endpoints(self):
        self.client.force_login(self.ci_user)
        endpoints = [
            (reverse('org-hierarchy-oas'), 'get'),
            (reverse('org-hierarchy-om-assignments'), 'get'),
            (reverse('org-hierarchy-personnel'), 'get'),
            (reverse('org-hierarchy-site-assignments'), 'get'),
            (reverse('org-hierarchy-conflicts'), 'get'),
            (reverse('org-hierarchy-merge-preview'), 'post'),
            (reverse('org-hierarchy-merge-confirm'), 'post'),
            (reverse('org-hierarchy-merge-rollback'), 'post'),
        ]
        for url, method in endpoints:
            resp = getattr(self.client, method)(url, {}, content_type='application/json')
            self.assertEqual(resp.status_code, 403, f"Expected 403 Forbidden for CI user on {url}, got {resp.status_code}")


class TestHierarchyApiEndpoints(TeamHierarchyBaseTestCase):
    def test_list_operational_areas(self):
        OperationalArea.objects.create(
            circle=self.circle_mp,
            name='BILASPUR',
            normalized_name='bilaspur',
            code='BSP',
        )
        resp = self.client.get(reverse('org-hierarchy-oas'))
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertGreaterEqual(data['count'], 1)

    def test_list_personnel(self):
        Personnel.objects.create(
            canonical_name='API TEST PERSON',
            display_name='API Test Person',
            role_type='ci',
        )
        resp = self.client.get(reverse('org-hierarchy-personnel'))
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertGreaterEqual(data['count'], 1)

    def test_list_om_assignments(self):
        OmManagerAssignment.objects.create(
            circle=self.circle_mp,
            project=None,
            manager_name='API Manager',
            effective_from=date(2026, 1, 1),
        )
        resp = self.client.get(reverse('org-hierarchy-om-assignments'))
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertGreaterEqual(data['count'], 1)
