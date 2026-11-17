"""API Master, Phase 1 (API Registry): discovery from the real URL configuration, blocked / field-review classification,
synchronisation that keeps review decisions, the review workflow and Admin-only access. Nothing here changes how an internal
endpoint behaves, and no endpoint is callable from outside yet (external wrappers come in a later phase)."""
from django.test import TestCase
from django.urls import Resolver404, URLPattern, URLResolver, get_resolver, resolve, reverse
from django.utils import timezone

from apps.api_master import discovery
from apps.api_master.models import ApiEndpoint
from tests.auth_helpers import portal_user

S = ApiEndpoint.Status


def _independent_count() -> int:
    """Route+method operations counted without the discovery module (named routes, DRF handler methods)."""
    def walk(patterns):
        for p in patterns:
            if isinstance(p, URLResolver):
                yield from walk(p.url_patterns)
            elif isinstance(p, URLPattern) and p.name:
                yield p
    total = 0
    for p in walk(get_resolver().url_patterns):
        cls = getattr(p.callback, 'cls', None) or getattr(p.callback, 'view_class', None)
        total += sum(hasattr(cls, m) for m in ('get', 'post', 'put', 'patch', 'delete'))
    return total


class DiscoveryTests(TestCase):
    def setUp(self):
        self.found = {f.key: f for f in discovery.discover()}

    def test_every_route_and_method_of_the_url_configuration_is_found_once(self):
        self.assertEqual(len(self.found), _independent_count())
        self.assertIn('allkpis-summary:GET', self.found)
        self.assertEqual(self.found['allkpis-summary:GET'].path, '/api/all-kpis/summary/')
        self.assertEqual(self.found['allkpis-summary:GET'].permission_classes, ['Can_dashboard_view'])
        self.assertEqual(self.found['rca-record:GET'].path_params, [{'name': 'record_id', 'type': 'int'}])

    def test_authentication_user_management_and_the_former_dev_login_are_never_exposable(self):
        self.assertFalse(any('dev-login' in f.path for f in self.found.values()))
        for key in ('auth-login:POST', 'auth-csrf:GET', 'auth-me:GET', 'auth-users:GET', 'auth-user-reset-password:POST',
                    'access-assignments:POST', 'api-master-endpoints:GET'):
            self.assertTrue(self.found[key].blocked, key)

    def test_writes_uploads_exports_and_admin_only_endpoints_are_blocked(self):
        for f in self.found.values():
            if f.method != 'GET':
                self.assertTrue(f.blocked, f.key)
        for key in ('rca-import-preview:POST', 'raw-upload-preview:POST', 'dashboard-export-daily:GET', 'dashboard-teams:GET',
                    'dashboard-workbook:GET'):
            if key in self.found:
                self.assertTrue(self.found[key].blocked, key)
        exports = [f for f in self.found.values() if 'export' in f.path or f.path.endswith(('.csv/', '.xlsx', '.csv'))]
        self.assertTrue(exports and all(f.blocked for f in exports))
        tickets = [f for f in self.found.values() if f.path.startswith('/api/tickets/')]
        self.assertTrue(tickets)
        self.assertTrue(all(f.blocked and f.module == 'Ticket Management' for f in tickets))

    def test_only_read_only_dashboard_kpi_portfolio_and_rca_endpoints_are_reviewable(self):
        reviewable = [f for f in self.found.values() if not f.blocked]
        self.assertTrue(all(f.method == 'GET' for f in reviewable))
        self.assertEqual({f.module for f in reviewable}, {'Dashboard', "All KPI's", 'Site Portfolio', 'RCA'})
        for key in ('dashboard-summary:GET', 'allkpis-summary:GET', 'site-portfolio-summary:GET', 'rca-summary:GET', 'rca-overview:GET'):
            self.assertFalse(self.found[key].blocked, key)
            self.assertEqual(self.found[key].field_review, '', key)

    def test_responses_with_staff_names_or_records_need_a_field_review(self):
        for key in ('site-portfolio-breakdowns:GET', 'dashboard-om-heads:GET', 'allkpis-hierarchy:GET', 'dashboard-records:GET',
                    'rca-records:GET'):
            self.assertFalse(self.found[key].blocked, key)
            self.assertTrue(self.found[key].field_review, key)


class SyncTests(TestCase):
    def test_new_endpoints_are_pending_and_a_second_sync_changes_nothing(self):
        first = discovery.sync()
        self.assertEqual(first['created'], first['discovered'])
        self.assertEqual(set(ApiEndpoint.objects.values_list('status', flat=True)), {S.PENDING})
        second = discovery.sync()
        self.assertEqual((second['created'], second['updated'], second['no_longer_present']), (0, 0, 0))

    def test_review_decisions_are_kept_and_vanished_routes_are_marked(self):
        discovery.sync()
        ApiEndpoint.objects.filter(key='allkpis-summary:GET').update(status=S.APPROVED, review_note='ok')
        ApiEndpoint.objects.create(key='gone:GET', url_name='gone', path='/api/gone/', method='GET', module='Other', name='GET Gone',
                                   view='x', last_seen=timezone.now())
        result = discovery.sync()
        self.assertEqual(ApiEndpoint.objects.get(key='allkpis-summary:GET').status, S.APPROVED)
        self.assertFalse(ApiEndpoint.objects.get(key='gone:GET').present)
        self.assertEqual(result['no_longer_present'], 1)

    def test_an_approved_endpoint_that_becomes_blocked_returns_to_pending(self):
        discovery.sync()
        ApiEndpoint.objects.filter(key='auth-me:GET').update(status=S.APPROVED, blocked=False)  # e.g. approved before a rule existed
        self.assertEqual(discovery.sync()['approvals_withdrawn'], 1)
        row = ApiEndpoint.objects.get(key='auth-me:GET')
        self.assertEqual((row.status, row.blocked), (S.PENDING, True))
        self.assertIn('Returned to Pending', row.review_note)


class RegistryApiTests(TestCase):
    def setUp(self):
        self.admin = portal_user('api-admin', 'admin')
        self.client.force_login(self.admin)
        self.client.post(reverse('api-master-sync'))

    def review(self, key, **body):
        pk = ApiEndpoint.objects.get(key=key).pk
        return self.client.post(reverse('api-master-endpoint-review', args=[pk]), body, content_type='application/json')

    def test_admins_only(self):
        for role in ('noc_lead', 'ci'):
            self.client.force_login(portal_user(f'api-{role}', role, all_circles=True))
            for url in (reverse('api-master-overview'), reverse('api-master-endpoints')):
                self.assertEqual(self.client.get(url).status_code, 403, (role, url))
            self.assertEqual(self.client.post(reverse('api-master-sync')).status_code, 403)
        self.client.logout()
        self.assertEqual(self.client.get(reverse('api-master-endpoints')).status_code, 401)

    def test_overview_counts_come_from_the_registry(self):
        o = self.client.get(reverse('api-master-overview')).json()
        self.assertEqual(o['total'], ApiEndpoint.objects.filter(present=True).count())
        self.assertEqual((o['approved'], o['pending']), (0, o['total']))
        self.assertEqual(o['blocked'] + o['reviewable'], o['total'])
        self.assertEqual(sum(o['methods'].values()), o['total'])

    def test_list_search_and_filters(self):
        rows = self.client.get(reverse('api-master-endpoints'), {'q': 'all-kpis', 'method': 'GET'}).json()['results']
        self.assertTrue(rows and all('/api/all-kpis/' in r['path'] for r in rows))
        blocked = self.client.get(reverse('api-master-endpoints'), {'access': 'blocked'}).json()
        self.assertTrue(all(r['blocked'] for r in blocked['results']))
        detail = self.client.get(reverse('api-master-endpoint', args=[rows[0]['id']])).json()
        self.assertIn('permission_classes', detail)
        self.assertIsNone(detail['external_route'])

    def test_approval_needs_a_reason_and_a_reviewable_endpoint(self):
        self.assertIn('note', self.review('allkpis-summary:GET', status='approved', note='').json()['details'])
        ok = self.review('allkpis-summary:GET', status='approved', note='Aggregated KPIs only; scope-limited.')
        self.assertEqual(ok.status_code, 200)
        self.assertEqual((ok.json()['status'], ok.json()['reviewed_by']), ('approved', 'api-admin'))
        refused = self.review('auth-login:POST', status='approved', note='no')
        self.assertEqual(refused.status_code, 400)
        self.assertIn('never be exposed', refused.json()['details']['status'])

    def test_sensitive_fields_need_an_explicit_confirmation(self):
        r = self.review('site-portfolio-breakdowns:GET', status='approved', note='ok')
        self.assertEqual(r.status_code, 400)
        self.assertIn('fields_reviewed', r.json()['details'])
        self.assertEqual(ApiEndpoint.objects.get(key='site-portfolio-breakdowns:GET').status, S.PENDING)

    def test_status_transitions(self):
        self.assertEqual(self.review('rca-summary:GET', status='deprecated', note='x').status_code, 400)  # pending -> deprecated
        self.assertEqual(self.review('rca-summary:GET', status='approved', note='x').status_code, 200)
        self.assertEqual(self.review('rca-summary:GET', status='deprecated', note='replaced').status_code, 200)
        self.assertEqual(self.review('rca-summary:GET', status='pending', note='reopen').status_code, 200)
        self.assertEqual(self.review('rca-summary:GET', status='rejected', note='not needed').status_code, 200)

    def test_approval_changes_nothing_on_the_internal_endpoint_and_exposes_nothing_externally(self):
        self.review('allkpis-summary:GET', status='approved', note='ok')
        self.client.logout()
        self.assertEqual(self.client.get('/api/all-kpis/summary/').status_code, 401)  # still the portal session login
        with self.assertRaises(Resolver404):  # no external route exists yet (wrappers come in a later phase)
            resolve('/api/external/v1/all-kpis/summary/')
