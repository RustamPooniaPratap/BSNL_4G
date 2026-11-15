"""RCA Site Scope (All / O&M Start / O&M Not Started Sites): one rule from the Consolidation Matrix O&M Start Date
(sitedata.Site.om_start_date on or before the last day of the record's month), applied to the register, the summary pages
and the submissions view. Synthetic records in the test database only."""
from datetime import date

from django.test import TestCase
from django.urls import reverse

from apps.accounts import services as access
from apps.accounts.models import Role, RolePermission
from apps.dashboard import metrics
from apps.rca import sitescope
from apps.rca.models import RcaRecord
from apps.rca.parser import text_key
from tests.auth_helpers import portal_user
from tests.sitedata_factory import make_site

G4 = '4G Saturation'


def site(circle, sid, om_start_date):
    return make_site(sid, technology=G4, circle=circle, on_air_date=date(2025, 1, 1), om_start_date=om_start_date)


def record(circle, sid, day=date(2026, 10, 5), bucket='TCS', om_on_row='Yes', occurrence=1, project=G4):
    return RcaRecord.objects.create(reporting_date=day, project=project, project_raw=project, circle=circle, circle_raw=circle, site_id=sid, site_key=sid,
                                    final_bucket=bucket, final_bucket_key=text_key(bucket), om_start_raw=om_on_row, om_start=om_on_row == 'Yes',
                                    rca_text='x', rca_key='x', outage_minutes=10, occurrence=occurrence)


class SiteScopeTests(TestCase):
    def setUp(self):
        self.admin = portal_user('scope-admin', 'admin')
        site('MP', 'MPYES', date(2026, 10, 31))            # started in October (on its last day; not in September)
        site('MP', 'MPNO', date(2026, 11, 1))              # starts the day after October ends
        site('RJ', 'RJYES', date(2026, 1, 15))
        site('MP', 'MPBLANK', None)                        # no O&M Start Date in the matrix: not started
        record('MP', 'MPYES')
        record('MP', 'MPYES', bucket='BSNL OFC', occurrence=2)
        record('MP', 'MPNO', om_on_row='Yes')              # the RCA row says Yes: the matrix date (November) decides
        record('RJ', 'RJYES')
        record('MP', 'NOTINMASTER')                        # cannot be linked: All Sites only
        record('MP', 'MPBLANK')                            # no O&M Start Date: O&M Not Started
        record('MP', 'MPYES', day=date(2026, 9, 20))       # September: the site was not started then
        self.client.force_login(self.admin)

    def register(self, **params):
        response = self.client.get(reverse('rca-records'), {'page_size': 100, **params})
        self.assertEqual(response.status_code, 200, response.content[:300])
        return sorted((r['site_id'], r['reporting_date']) for r in response.json()['results'])

    def summary(self, **params):
        response = self.client.get(reverse('rca-summary'), params)
        self.assertEqual(response.status_code, 200, response.content[:300])
        return response.json()

    def test_each_scope_follows_the_matrix_o_and_m_start_date_of_the_records_month(self):
        self.assertEqual(len(self.register()), 7)
        self.assertEqual(self.register(site_scope='all'), self.register())  # All Sites: exactly as before
        self.assertEqual(self.register(site_scope='om_start'), [('MPYES', '2026-10-05'), ('MPYES', '2026-10-05'), ('RJYES', '2026-10-05')])
        self.assertEqual(self.register(site_scope='om_not_started'), [('MPBLANK', '2026-10-05'), ('MPNO', '2026-10-05'), ('MPYES', '2026-09-20')])

    def test_any_month_is_classified_by_the_o_and_m_start_date_without_monthly_flags(self):
        # These months never had a legacy monthly O&M Start flag: the matrix date alone decides.
        record('MP', 'MPNO', day=date(2026, 12, 2))        # started 1 Nov: O&M Start in December
        record('MP', 'MPNO', day=date(2026, 11, 30))       # started 1 Nov: O&M Start in November
        record('MP', 'MPBLANK', day=date(2027, 1, 3))      # never started
        record('RJ', 'RJYES', day=date(2026, 1, 1))        # started 15 Jan: O&M Start for January (month-end rule)
        record('RJ', 'RJYES', day=date(2025, 12, 31))      # December 2025: before the date
        started = self.register(site_scope='om_start')
        self.assertIn(('MPNO', '2026-12-02'), started)
        self.assertIn(('MPNO', '2026-11-30'), started)
        self.assertIn(('RJYES', '2026-01-01'), started)
        not_started = self.register(site_scope='om_not_started')
        self.assertIn(('MPBLANK', '2027-01-03'), not_started)
        self.assertIn(('RJYES', '2025-12-31'), not_started)
        self.assertFalse(set(started) & set(not_started))

    def test_only_dashboard_sites_of_the_records_project_are_matched(self):
        make_site('LWEONLY', technology='LWE', circle='MP', om_start_date=date(2026, 1, 1))
        make_site('OUTSIDE', circle='MP', om_start_date=date(2026, 1, 1), outside_scope=True)
        record('MP', 'LWEONLY')                            # a 4G record of an LWE site: not linked
        record('MP', 'OUTSIDE')                            # outside the dashboard reporting scope: not linked
        scoped = self.register(site_scope='om_start') + self.register(site_scope='om_not_started')
        self.assertNotIn(('LWEONLY', '2026-10-05'), scoped)
        self.assertNotIn(('OUTSIDE', '2026-10-05'), scoped)
        self.assertIn(('LWEONLY', '2026-10-05'), self.register())

    def test_every_summary_figure_uses_the_scope_and_reconciles(self):
        before = self.summary()
        self.assertEqual({k: v for k, v in self.summary(site_scope='all').items() if k != 'site_scope'},
                         {k: v for k, v in before.items() if k != 'site_scope'})  # All Sites reproduces the existing results
        started = self.summary(site_scope='om_start')
        self.assertEqual((started['kpis']['records'], started['breakdown']['grand_total']), (3, 3))
        rows = {r['circle']: r for r in started['breakdown']['rows']}
        self.assertEqual((rows['MP']['grand_total'], rows['RJ']['grand_total']), (2, 1))
        self.assertEqual(sum(c['records'] for c in started['circles']), 3)
        self.assertEqual(started['site_scope']['coverage'], {'total': 7, 'om_start': 3, 'not_started': 3, 'unclassified': 1})
        not_started = self.summary(site_scope='om_not_started')
        self.assertEqual(not_started['kpis']['records'], 3)
        self.assertEqual(started['kpis']['records'] + not_started['kpis']['records'] + 1, before['kpis']['records'])

    def test_combines_with_project_circle_date_and_bucket_filters(self):
        self.assertEqual(self.register(site_scope='om_start', circle='RJ'), [('RJYES', '2026-10-05')])
        self.assertEqual(self.register(site_scope='om_start', project=G4, circle='MP', final_bucket=text_key('BSNL OFC')), [('MPYES', '2026-10-05')])
        self.assertEqual(self.register(site_scope='om_not_started', date_from='2026-10-01', date_to='2026-10-31'),
                         [('MPBLANK', '2026-10-05'), ('MPNO', '2026-10-05')])
        self.assertEqual(self.summary(site_scope='om_start', date_from='2026-09-01', date_to='2026-09-30')['kpis']['records'], 0)

    def test_an_unknown_scope_is_refused(self):
        self.assertEqual(self.client.get(reverse('rca-records'), {'site_scope': 'maybe'}).status_code, 400)
        self.assertEqual(sitescope.parse(''), sitescope.ALL)

    def test_project_circle_access_still_applies(self):
        role = Role.objects.create(name='RCA viewer')
        RolePermission.objects.create(role=role, module='rca_register', action='view')
        user = portal_user('mp-viewer', 'member')
        access.assign(self.admin, user, role, G4, ['MP'])
        self.client.force_login(user)
        self.assertEqual(self.register(site_scope='om_start'), [('MPYES', '2026-10-05'), ('MPYES', '2026-10-05')])  # never RJ

    def test_submissions_show_scoped_figures_without_changing_the_status(self):
        from apps.rca import cycles
        from apps.rca.models import RcaReportingCycle
        from tests.test_rca import active_scope
        cycle = RcaReportingCycle.objects.create(reporting_date=date(2026, 10, 5), created_by=self.admin)
        active_scope([(G4, 'MP')])
        plain = cycles.cycle_json(cycle, full=True)
        scoped = self.client.get(reverse('rca-cycle', args=[cycle.pk]), {'site_scope': 'om_not_started'}).json()
        [u] = scoped['units']
        self.assertEqual((u['records'], u['records_in_scope'], u['status']), (5, 2, plain['units'][0]['status']))
        self.assertEqual(scoped['status'], plain['status'])  # compliance is unchanged by the view

    def test_dashboard_site_columns_use_the_same_sites(self):
        import pandas as pd
        from types import SimpleNamespace
        ds = SimpleNamespace(sites=pd.DataFrame({'report_type': [G4] * 3, 'circle': ['MP'] * 3, 'on_air': [True, True, False], 'om_start': [True, False, True]}))
        mask = lambda scope: metrics.scope_mask(ds, metrics.Selection(scope=sitescope.dashboard_scope(scope))).tolist()  # noqa: E731
        self.assertEqual((mask('all'), mask('om_start'), mask('om_not_started')), ([True, True, False], [True, False, False], [False, True, False]))
