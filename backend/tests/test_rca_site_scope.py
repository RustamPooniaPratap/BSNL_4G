"""RCA Site Scope (All / O&M Start / O&M Not Started Sites): one rule from the Site Master's monthly O&M Start, applied
to the register, the summary pages and the submissions view. Synthetic records in the test database only."""
from datetime import date

from django.test import TestCase
from django.urls import reverse

from apps.accounts import services as access
from apps.accounts.models import Role, RolePermission
from apps.dashboard import metrics
from apps.rca import sitescope
from apps.rca.models import RcaRecord
from apps.rca.parser import text_key
from apps.uptimedb.models import DataImportBatch, SiteMonthlyPerformance, UptimeSite
from tests.auth_helpers import portal_user

G4, OCT, SEP = '4G Saturation', date(2026, 10, 1), date(2026, 9, 1)


def site(circle, sid, batch, om_oct, om_sep=None):
    s = UptimeSite.objects.create(project=G4, circle=circle, site_id=sid, site_key=sid, on_air=True, on_air_raw='Yes', batch=batch, source_row=1)
    for month, om in ((OCT, om_oct), (SEP, om_sep)):
        SiteMonthlyPerformance.objects.create(site=s, month=month, om_start=om, om_start_raw=None if om is None else ('Yes' if om else 'No'), batch=batch)
    return s


def record(circle, sid, day=date(2026, 10, 5), bucket='TCS', om_on_row='Yes', occurrence=1):
    return RcaRecord.objects.create(reporting_date=day, project=G4, project_raw=G4, circle=circle, circle_raw=circle, site_id=sid, site_key=sid,
                                    final_bucket=bucket, final_bucket_key=text_key(bucket), om_start_raw=om_on_row, om_start=om_on_row == 'Yes',
                                    rca_text='x', rca_key='x', outage_minutes=10, occurrence=occurrence)


class SiteScopeTests(TestCase):
    def setUp(self):
        self.admin = portal_user('scope-admin', 'admin')
        batch = DataImportBatch.objects.create(original_filename='m.xlsx', checksum_sha256='x', sheet_name='s', stored_path='-',
                                               status=DataImportBatch.Status.COMMITTED)
        site('MP', 'MPYES', batch, True, om_sep=False)     # started in October (not in September)
        site('MP', 'MPNO', batch, False)
        site('RJ', 'RJYES', batch, True)
        site('MP', 'MPBLANK', batch, None)                 # no O&M Start value for October
        record('MP', 'MPYES')
        record('MP', 'MPYES', bucket='BSNL OFC', occurrence=2)
        record('MP', 'MPNO', om_on_row='Yes')              # the RCA row says Yes: the Site Master (No) decides
        record('RJ', 'RJYES')
        record('MP', 'NOTINMASTER')                        # cannot be linked: All Sites only
        record('MP', 'MPBLANK')                            # no O&M value that month: All Sites only
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

    def test_each_scope_follows_the_site_master_o_and_m_start_of_the_records_month(self):
        self.assertEqual(len(self.register()), 7)
        self.assertEqual(self.register(site_scope='all'), self.register())  # All Sites: exactly as before
        self.assertEqual(self.register(site_scope='om_start'), [('MPYES', '2026-10-05'), ('MPYES', '2026-10-05'), ('RJYES', '2026-10-05')])
        self.assertEqual(self.register(site_scope='om_not_started'), [('MPNO', '2026-10-05'), ('MPYES', '2026-09-20')])

    def test_every_summary_figure_uses_the_scope_and_reconciles(self):
        before = self.summary()
        self.assertEqual({k: v for k, v in self.summary(site_scope='all').items() if k != 'site_scope'},
                         {k: v for k, v in before.items() if k != 'site_scope'})  # All Sites reproduces the existing results
        started = self.summary(site_scope='om_start')
        self.assertEqual((started['kpis']['records'], started['breakdown']['grand_total']), (3, 3))
        rows = {r['circle']: r for r in started['breakdown']['rows']}
        self.assertEqual((rows['MP']['grand_total'], rows['RJ']['grand_total']), (2, 1))
        self.assertEqual(sum(c['records'] for c in started['circles']), 3)
        self.assertEqual(started['site_scope']['coverage'], {'total': 7, 'om_start': 3, 'not_started': 2, 'unclassified': 2})
        not_started = self.summary(site_scope='om_not_started')
        self.assertEqual(not_started['kpis']['records'], 2)
        self.assertEqual(started['kpis']['records'] + not_started['kpis']['records'] + 2, before['kpis']['records'])

    def test_combines_with_project_circle_date_and_bucket_filters(self):
        self.assertEqual(self.register(site_scope='om_start', circle='RJ'), [('RJYES', '2026-10-05')])
        self.assertEqual(self.register(site_scope='om_start', project=G4, circle='MP', final_bucket=text_key('BSNL OFC')), [('MPYES', '2026-10-05')])
        self.assertEqual(self.register(site_scope='om_not_started', date_from='2026-10-01', date_to='2026-10-31'), [('MPNO', '2026-10-05')])
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
        from apps.rca.models import RcaReportingCycle, RcaRequiredSubmission
        cycle = RcaReportingCycle.objects.create(reporting_date=date(2026, 10, 5), created_by=self.admin)
        RcaRequiredSubmission.objects.create(cycle=cycle, project=G4, circle='MP')
        plain = cycles.cycle_json(cycle, full=True)
        scoped = self.client.get(reverse('rca-cycle', args=[cycle.pk]), {'site_scope': 'om_not_started'}).json()
        [u] = scoped['units']
        self.assertEqual((u['records'], u['records_in_scope'], u['status']), (5, 1, plain['units'][0]['status']))
        self.assertEqual(scoped['status'], plain['status'])  # compliance is unchanged by the view

    def test_dashboard_site_columns_use_the_same_sites(self):
        import pandas as pd
        from types import SimpleNamespace
        ds = SimpleNamespace(sites=pd.DataFrame({'report_type': [G4] * 3, 'circle': ['MP'] * 3, 'on_air': [True, True, False], 'om_start': [True, False, True]}))
        mask = lambda scope: metrics.scope_mask(ds, metrics.Selection(scope=sitescope.dashboard_scope(scope))).tolist()  # noqa: E731
        self.assertEqual((mask('all'), mask('om_start'), mask('om_not_started')), ([True, True, False], [True, False, False], [False, True, False]))
