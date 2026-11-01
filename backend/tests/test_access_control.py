"""User management and project/circle access control: custom roles, permission matrix, assignments, data isolation,
access preview and access history. Synthetic users, workbooks and records in the isolated test database only.
"""
import tempfile
from datetime import date, timedelta
from pathlib import Path

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse

from apps.accounts.access import can, pairs_for
from apps.accounts.models import AccessAssignment, AccessEvent, Role
from apps.dashboard import workbook as dashboard_workbook
from apps.organization.models import Circle, Project, ProjectCircle
from apps.rca.models import RcaRecord
from tests.auth_helpers import portal_user
from tests.test_rca_uploads import OD_21, RJ_21, UploadCase
from tests.workbook_factory import write_workbook

G4, LWE = '4G Saturation', 'LWE'


def perms(*items):
    return [{'module': m, 'action': a} for m, a in items]


class AdminApi:
    """Calls the Users & Roles API as ``self.admin``."""

    def api(self, method, name, data=None, args=None, **params):
        self.client.force_login(self.admin)
        url = reverse(name, args=args)
        if method == 'get':
            return self.client.get(url, params)
        return getattr(self.client, method)(url, data or {}, content_type='application/json')

    def role(self, name, *items) -> int:
        response = self.api('post', 'access-roles', {'name': name, 'permissions': perms(*items)})
        self.assertEqual(response.status_code, 201, response.content)
        return response.json()['role']['id']

    def assign(self, user, role_id, project, circles=None, **extra):
        body = {'user': user.pk, 'role': role_id, 'project': project, 'scope': 'project' if circles is None else 'circles', 'circles': circles or [], **extra}
        response = self.api('post', 'access-assignments', body)
        self.assertEqual(response.status_code, 201, response.content)
        return response.json()['assignments']


class RolesTests(AdminApi, TestCase):
    def setUp(self):
        self.admin = portal_user('acl-admin', 'admin')

    def test_no_dummy_data_only_the_three_built_in_roles(self):
        self.assertEqual(sorted(Role.objects.values_list('system_key', flat=True)), ['admin', 'ci', 'noc_lead'])
        self.assertEqual(AccessAssignment.objects.count(), 0)
        self.assertEqual(get_user_model().objects.count(), 1)  # the test's own Admin

    def test_a_new_role_has_no_permissions_and_admin_configures_exactly_what_it_may_do(self):
        response = self.api('post', 'access-roles', {'name': 'IE'})
        self.assertEqual(response.status_code, 201)
        role = response.json()['role']
        self.assertEqual((role['permissions'], role['system'], role['users']), ([], False, []))
        updated = self.api('patch', 'access-role', {'permissions': perms(('rca_upload', 'upload'))}, args=[role['id']]).json()['role']
        self.assertEqual(updated['permissions'], perms(('rca_upload', 'upload')))
        # Only catalogue permissions exist: nothing administrative, nothing invented.
        bad = self.api('patch', 'access-role', {'permissions': perms(('users', 'manage'))}, args=[role['id']])
        self.assertEqual(bad.status_code, 400)
        self.assertEqual(self.api('post', 'access-roles', {'name': 'ie'}).status_code, 400)  # names are unique, case-insensitively

    def test_built_in_roles_are_protected_and_cloning_copies_permissions(self):
        ci = Role.objects.get(system_key='ci')
        self.assertEqual(self.api('patch', 'access-role', {'permissions': []}, args=[ci.pk]).status_code, 400)
        self.assertEqual(self.api('delete', 'access-role', args=[ci.pk]).status_code, 400)
        self.assertEqual(Role.objects.get(pk=ci.pk).permissions.count(), 17)  # Master Data view/export became per-dataset grants
        copy = self.api('post', 'access-role-clone', {'name': 'CI Editor'}, args=[ci.pk]).json()['role']
        self.assertEqual(len(copy['permissions']), 17)
        self.assertFalse(copy['system'])
        admin_role = Role.objects.get(system_key='admin')
        user = portal_user('someone', None)
        refused = self.api('post', 'access-assignments', {'user': user.pk, 'role': admin_role.pk, 'project': G4, 'scope': 'project'})
        self.assertEqual(refused.status_code, 400)  # Admin is an account role, never granted through an assignment

    def test_an_admin_cannot_change_their_own_access(self):
        role = self.role('Viewer', ('dashboard', 'view'))
        response = self.api('post', 'access-assignments', {'user': self.admin.pk, 'role': role, 'project': G4, 'scope': 'project'})
        self.assertEqual(response.status_code, 400)

    def test_only_admins_reach_user_management(self):
        ci = portal_user('acl-ci', 'ci', all_circles=True)
        self.client.force_login(ci)
        for name in ('access-roles', 'access-assignments', 'access-history', 'access-catalog', 'auth-users'):
            self.assertEqual(self.client.get(reverse(name)).status_code, 403, name)
        self.assertEqual(self.client.post(reverse('access-roles'), {'name': 'Me'}, content_type='application/json').status_code, 403)


class AssignmentTests(AdminApi, TestCase):
    def setUp(self):
        self.admin = portal_user('acl-admin', 'admin')
        self.user = portal_user('rahul', 'member')
        self.editor = self.role('CI Editor', ('dashboard', 'view'), ('csv_upload', 'upload'))
        self.analyst = self.role('RCA Analyst', ('rca_register', 'view'))

    def test_one_login_many_circles_and_different_roles_per_circle(self):
        self.assign(self.user, self.editor, G4, ['RJ', 'MP'])  # several circles at once
        self.assign(self.user, self.analyst, LWE, ['MP'])
        self.assertEqual(AccessAssignment.objects.filter(user=self.user).count(), 3)  # one row per circle, no comma lists
        self.assertEqual(pairs_for(self.user, 'csv_upload', 'upload'), {(G4, 'RJ'), (G4, 'MP')})
        self.assertEqual(pairs_for(self.user, 'rca_register', 'view'), {(LWE, 'MP')})
        self.assertFalse(can(self.user, 'csv_upload', 'upload', LWE, 'MP'))
        self.assertFalse(can(self.user, 'rca_register', 'view', G4, 'RJ'))
        self.assertFalse(can(self.user, 'dashboard', 'view', G4, 'OD'))
        # Remove one circle without touching the others; change the role of one circle only.
        mp = AccessAssignment.objects.get(user=self.user, role_id=self.editor, project_circle__circle__code='MP')
        self.assertEqual(self.api('delete', 'access-assignment', args=[mp.pk]).status_code, 204)
        rj = AccessAssignment.objects.get(user=self.user, role_id=self.editor)
        self.assertEqual(self.api('patch', 'access-assignment', {'role': self.analyst}, args=[rj.pk]).status_code, 200)
        self.assertEqual(pairs_for(get_user_model().objects.get(pk=self.user.pk), 'rca_register', 'view'), {(LWE, 'MP'), (G4, 'RJ')})

    def test_project_wide_viewer_gives_no_write_permission_and_a_circle_editor_adds_to_that_circle_only(self):
        viewer = self.role('Viewer', ('dashboard', 'view'))
        self.assign(self.user, viewer, G4)  # entire project
        self.assertEqual(pairs_for(self.user, 'dashboard', 'view'), {(G4, 'MP'), (G4, 'OD'), (G4, 'RJ')})
        self.assertFalse(can(self.user, 'csv_upload', 'upload'))
        self.assertFalse(can(self.user, 'dashboard', 'export'))
        self.assertFalse(can(self.user, 'dashboard', 'view', LWE, 'MP'))  # a project-wide grant is for that project only
        self.assign(self.user, self.editor, G4, ['MP'])
        self.user = get_user_model().objects.get(pk=self.user.pk)
        self.assertEqual(pairs_for(self.user, 'csv_upload', 'upload'), {(G4, 'MP')})

    def test_only_organization_associations_are_assignable_and_new_ones_grant_nothing(self):
        refused = self.api('post', 'access-assignments', {'user': self.user.pk, 'role': self.editor, 'project': G4, 'scope': 'circles', 'circles': ['BH']})
        self.assertEqual(refused.status_code, 400)  # BH is not a circle of 4G Saturation
        self.assign(self.user, self.editor, G4, ['MP'])
        ProjectCircle.objects.create(project=Project.objects.get(key=G4), circle=Circle.objects.get(code='BH'))
        self.user = get_user_model().objects.get(pk=self.user.pk)
        self.assertEqual(pairs_for(self.user, 'dashboard', 'view'), {(G4, 'MP')})  # the new association grants nothing
        self.assign(self.user, self.editor, G4, ['BH'])  # but it can be assigned now

    def test_inactive_expired_or_deactivated_access_grants_nothing(self):
        [a] = self.assign(self.user, self.editor, G4, ['MP'])
        self.assertTrue(can(self.user, 'dashboard', 'view', G4, 'MP'))
        checks = [
            ({'status': 'inactive'}, 'Assignment inactive'),
            ({'status': 'active', 'valid_until': (date.today() - timedelta(days=1)).isoformat()}, 'Expired'),
        ]
        for body, problem in checks:
            self.assertEqual(self.api('patch', 'access-assignment', body, args=[a['id']]).status_code, 200)
            fresh = get_user_model().objects.get(pk=self.user.pk)
            self.assertFalse(can(fresh, 'dashboard', 'view', G4, 'MP'), problem)
        self.api('patch', 'access-assignment', {'valid_until': None}, args=[a['id']])
        self.api('patch', 'access-role', {'is_active': False}, args=[self.editor])
        self.assertFalse(can(get_user_model().objects.get(pk=self.user.pk), 'dashboard', 'view'))
        self.api('patch', 'access-role', {'is_active': True}, args=[self.editor])
        ProjectCircle.objects.filter(project__key=G4, circle__code='MP').update(is_active=False)
        self.assertFalse(can(get_user_model().objects.get(pk=self.user.pk), 'dashboard', 'view'))
        ProjectCircle.objects.filter(project__key=G4, circle__code='MP').update(is_active=True)
        self.user.is_active = False
        self.user.save()
        self.assertFalse(can(get_user_model().objects.get(pk=self.user.pk), 'dashboard', 'view'))

    def test_preview_explains_without_changing_anything_and_history_records_every_change(self):
        self.assign(self.user, self.editor, G4, ['RJ'])
        before = AccessAssignment.objects.count()
        preview = self.api('get', 'access-preview', user=self.user.pk, project=G4, circle='RJ', module='csv_upload').json()
        self.assertEqual(preview['actions'][0]['allowed'], True)
        self.assertEqual(preview['actions'][0]['granted_by'][0]['role'], 'CI Editor')
        other = self.api('get', 'access-preview', user=self.user.pk, project=G4, circle='MP', module='csv_upload').json()
        self.assertEqual(other['actions'][0]['allowed'], False)
        self.assertEqual(AccessAssignment.objects.count(), before)
        a = AccessAssignment.objects.get(user=self.user)
        self.api('delete', 'access-assignment', args=[a.pk])
        actions = list(AccessEvent.objects.values_list('action', flat=True))
        for expected in ('role_created', 'assignment_added', 'assignment_revoked'):
            self.assertIn(expected, actions)
        event = AccessEvent.objects.filter(action='assignment_revoked').first()
        self.assertEqual((event.actor_name, event.target_name, event.scope), ('acl-admin', 'rahul', 'CI Editor · 4G Saturation · RJ'))
        history = self.api('get', 'access-history', user=self.user.pk).json()['events']
        self.assertTrue(history and all('password' not in str(e).lower() for e in history))


class DashboardIsolationTests(AdminApi, TestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls._tmp = tempfile.TemporaryDirectory()
        cls._override = override_settings(MASTER_WORKBOOK_PATH=str(write_workbook(Path(cls._tmp.name) / 'master.xlsx')))
        cls._override.enable()
        dashboard_workbook.clear_cache()

    @classmethod
    def tearDownClass(cls):
        cls._override.disable()
        dashboard_workbook.clear_cache()
        cls._tmp.cleanup()
        super().tearDownClass()

    def setUp(self):
        self.admin = portal_user('acl-admin', 'admin')
        self.user = portal_user('raj-user', 'member')
        self.viewer = self.role('Viewer', ('dashboard', 'view'))

    def sites(self, **params):
        self.client.force_login(self.user)
        response = self.client.get(reverse('dashboard-records'), {'page_size': 100, **params})
        self.assertEqual(response.status_code, 200, response.content)
        return sorted(r['site_id'] for r in response.json()['records'])

    def test_a_rajasthan_user_sees_only_rajasthan_in_tables_kpis_filters_search_and_details(self):
        self.assign(self.user, self.viewer, G4, ['RJ'])
        self.assertEqual(self.sites(), ['UVRJ001'])
        self.assertEqual(self.sites(circle='MP'), [])  # changing the URL parameters reaches nothing else
        self.assertEqual(self.sites(report_type=LWE), [])
        self.assertEqual(self.sites(search='UVMP'), [])
        filters = self.client.get(reverse('dashboard-filters')).json()
        self.assertEqual([c['value'] for c in filters['circles']], ['RJ'])
        self.assertEqual([t['value'] for t in filters['report_types']], [G4])
        summary = self.client.get(reverse('dashboard-summary')).json()
        self.client.force_login(self.admin)
        everything = self.client.get(reverse('dashboard-summary')).json()
        self.assertNotEqual(summary, everything)
        self.client.force_login(self.user)
        self.assertEqual(self.client.get(reverse('dashboard-record-detail', args=['UVMP001'])).status_code, 404)
        self.assertEqual(self.client.get(reverse('dashboard-record-detail', args=['UVRJ001'])).status_code, 200)
        # No export permission: no download, whatever the parameters.
        self.assertEqual(self.client.get(reverse('dashboard-export-daily'), {'report_type': G4, 'circle': 'RJ'}).status_code, 403)

    def test_two_circles_both_visible_and_lwe_kept_apart(self):
        self.assign(self.user, self.viewer, G4, ['RJ', 'MP'])
        self.assertEqual(self.sites(), ['UVMP001', 'UVMP002', 'UVRJ001'])  # on-air sites (the default scope)
        self.assign(self.user, self.viewer, LWE, ['MP'])
        self.assertEqual(self.sites(report_type=LWE), ['LWEMP01'])  # MP under LWE only once assigned, OD and BH never

    def test_no_assignment_means_no_dashboard(self):
        self.client.force_login(portal_user('nobody', 'ci'))
        self.assertEqual(self.client.get(reverse('dashboard-summary')).status_code, 403)


class RcaIsolationTests(AdminApi, UploadCase):
    def setUp(self):
        super().setUp()
        self.ie_user = portal_user('ie-user', 'member')
        self.ie = self.role('IE', ('rca_upload', 'upload'))

    def test_ie_uploads_its_circle_without_seeing_historical_records(self):
        self.imported(self.circle(RJ_21, circle='RJ', name='rj.xlsx'))  # history from another circle, by the Admin
        self.assign(self.ie_user, self.ie, G4, ['OD'])
        self.client.force_login(self.ie_user)
        me = self.client.get(reverse('auth-me')).json()['user']
        self.assertEqual((me['role'], me['permissions']), ('member', {'rca_upload': ['upload']}))
        imports = self.client.get(reverse('rca-imports')).json()
        self.assertEqual((imports['rights']['circle'], imports['records']), (True, None))  # no record count either
        self.assertEqual(self.circle(RJ_21, circle='RJ').status_code, 403)  # cross-circle upload refused
        done = self.imported(self.circle(OD_21))
        self.assertEqual(self.client.get(reverse('rca-import', args=[done['id']])).status_code, 200)  # their own result
        for name in ('rca-records', 'rca-summary', 'rca-options', 'dashboard-summary', 'master-datasets'):
            self.assertEqual(self.client.get(reverse(name)).status_code, 403, name)
        record = RcaRecord.objects.filter(circle='OD').first()
        self.assertEqual(self.client.get(reverse('rca-record', args=[record.pk])).status_code, 404)

    def test_register_and_summary_are_limited_to_the_assigned_circles(self):
        self.imported(self.circle(RJ_21, circle='RJ', name='rj.xlsx'))
        self.imported(self.circle(OD_21, name='od.xlsx'))
        analyst = self.role('RCA Analyst', ('rca_register', 'view'), ('rca_summary', 'view'))
        self.assign(self.ie_user, analyst, G4, ['RJ'])
        self.client.force_login(self.ie_user)
        rows = self.client.get(reverse('rca-records'), {'page_size': 100}).json()['results']
        self.assertEqual({r['circle'] for r in rows}, {'RJ'})
        self.assertEqual(self.client.get(reverse('rca-records'), {'circle': 'OD'}).json()['count'], 0)
        summary = self.client.get(reverse('rca-summary')).json()
        self.assertEqual({c['circle'] for c in summary['circles']}, {'RJ'})
        self.assertIsNone(summary['cycle'])
        od = RcaRecord.objects.filter(circle='OD').first()
        self.assertEqual(self.client.get(reverse('rca-record', args=[od.pk])).status_code, 404)
        self.assertEqual(self.client.put(reverse('rca-workflow', args=[od.pk]), {'owner': 'x'}, content_type='application/json').status_code, 404)
        rj = RcaRecord.objects.filter(circle='RJ').first()
        # View only: no follow-up edits even on the assigned circle.
        self.assertEqual(self.client.put(reverse('rca-workflow', args=[rj.pk]), {'owner': 'x'}, content_type='application/json').status_code, 404)
