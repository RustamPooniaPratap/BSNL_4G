"""All KPI's (optional module, apps/allkpis): approved definitions on the new data layer (sitedata), test database only."""
from datetime import date, datetime

from django.urls import reverse

from apps.rca.models import RcaRecord
from apps.rca.parser import text_key
from apps.sitedata import portfolio, uptime_master
from tests.auth_helpers import SignedInTestCase, portal_user
from tests.test_sitedata import SiteDataTestCase
from tests.workbook_factory import write_workbook

G4 = '4G Saturation'
# (project, circle, site, name, On-Air, O&M Start, outage minutes on 1-3 Oct); None = not reported.
SITES = [
    ('4G Satu.', 'MP', 'UVMP101', 'Exactly 98.5', 'Yes', 'Yes', [0, 21.6, 0]),    # USD (outage > 0), not NSLA (98.5% exactly)
    ('4G Satu.', 'MP', 'UVMP102', 'Below 98.5', 'Yes', 'Yes', [21.7, 0, 0]),      # USD and NSLA (98.49%)
    ('4G Satu.', 'MP', 'UVMP103', 'Not reported', 'Yes', 'Yes', [None, None, None]),  # missing: neither
    ('4G Satu.', 'MP', 'UVMP104', 'No O&M Start', 'Yes', None, [600, 600, 600]),  # not O&M Start: neither
    ('4G Satu.', 'RJ', 'UVRJ101', 'Rajasthan', 'Yes', 'Yes', [0, 0, 0]),
]
OCT = date(2026, 10, 1)
CIRCLES = {'MP': 'Madhya Pradesh', 'RJ': 'Rajasthan'}


def matrix(om_dates=True):
    """The Consolidation Matrix of SITES: On-Air from 2025, O&M Start dates where the site is O&M Start (the source of
    truth for both); CI East / West alternate as in the workbook factory, one IE per circle."""
    rows = []
    for index, (_, circle, sid, name, _on_air, om, _) in enumerate(SITES):
        rows.append(['4G Saturation', CIRCLES[circle], sid, name, 'B', 'O', 'D', datetime(2025, 1, 1) if om and om_dates else None,
                     'Yes', datetime(2025, 1, 1), f'IE {circle}', 'CI East' if index % 2 == 0 else 'CI West', '', ''])
    return rows


class AllKpisTests(SignedInTestCase, SiteDataTestCase):
    def setUp(self):
        super().setUp()
        portfolio.clear_cache()
        self.addCleanup(portfolio.clear_cache)
        self.load()

    def load(self, om_dates=True):
        self.load_matrix(matrix(om_dates))
        path = write_workbook(self.tmp / 'kpi.xlsx', SITES)
        uptime_master.commit(uptime_master.preview(path, 'kpi.xlsx', user=self.admin), user=self.admin)
        portfolio.clear_cache()

    def get(self, name, **params):
        response = self.client.get(reverse(name), params)
        self.assertEqual(response.status_code, 200, response.content[:300])
        return response.json()

    def test_usd_and_nsla_follow_the_approved_definitions(self):
        s = self.get('allkpis-summary', circle='MP', date_from='2026-10-01', date_to='2026-10-03')['current']
        self.assertEqual((s['om_start_sites'], s['usd_sites'], s['nsla_sites']), (3, 2, 1))  # 101 + 102 USD; only 102 NSLA
        sites = {r['site_id']: r for r in self.get('allkpis-sites', circle='MP', date_from='2026-10-01', date_to='2026-10-03')['rows']}
        self.assertEqual((sites['UVMP101']['usd'], sites['UVMP101']['nsla']), (True, False))  # exactly 98.5% is not NSLA
        self.assertEqual((sites['UVMP103']['usd'], sites['UVMP103']['nsla'], sites['UVMP103']['availability_pct']), (False, False, None))
        self.assertEqual((sites['UVMP104']['usd'], sites['UVMP104']['nsla']), (False, False))  # not an O&M Start site

    def test_missing_values_are_reporting_gaps_not_low_availability(self):
        s = self.get('allkpis-summary', circle='MP', date_from='2026-10-01', date_to='2026-10-03')['current']
        self.assertEqual((s['missing_site_days'], s['sites_without_any_value'], s['expected_site_days']), (3, 1, 12))
        self.assertEqual(s['sites_with_values'], 3)  # the unreported site is in no threshold bucket
        self.assertEqual(s['below_60_sites'], 1)  # only UVMP104 (600 min a day)

    def test_availability_is_outage_weighted_and_monthly_comes_from_daily_records(self):
        s = self.get('allkpis-summary', circle='MP', date_from='2026-10-01', date_to='2026-10-03')['current']
        outage = 21.6 + 21.7 + 1800
        self.assertAlmostEqual(s['availability_pct'], round(100 * (1 - outage / (1440 * 9)), 4), places=3)  # 9 reported site-days
        month = self.get('allkpis-trends', circle='MP', granularity='month')['points']
        self.assertEqual([p['key'] for p in month], ['2026-10'])
        self.assertAlmostEqual(month[0]['availability_pct'], s['availability_pct'], places=3)
        days = self.get('allkpis-trends', circle='MP', date_from='2026-10-01', date_to='2026-10-03', granularity='day')['points']
        self.assertEqual([p['usd_sites'] for p in days], [1, 1, 0])  # 1 Oct: UVMP102; 2 Oct: UVMP101 (104 is not O&M Start)
        self.assertEqual([p['nsla_sites'] for p in days], [1, 0, 0])

    def test_no_o_and_m_start_data_means_not_available_never_carried_forward(self):
        # No O&M Start dates in the site master (test database only; a matrix import never blanks stored dates).
        from apps.sitedata.models import Site
        Site.objects.update(om_start_date=None, om_start_raw='')
        portfolio.clear_cache()
        r = self.get('allkpis-summary', circle='MP', date_from='2026-10-01', date_to='2026-10-03')
        self.assertEqual((r['current']['om_start_sites'], r['current']['usd_sites'], r['current']['nsla_sites']), (None, None, None))
        self.assertEqual((r['om_start']['available'], r['om_start']['missing_months']), (False, ['Oct 2026']))
        self.assertIsNotNone(r['current']['availability_pct'])  # availability does not need O&M Start

    def test_hierarchy_keeps_an_ie_with_its_ci_and_filters_cascade(self):
        ies = self.get('allkpis-hierarchy', level='ie', circle='MP', date_from='2026-10-01', date_to='2026-10-03')['rows']
        self.assertEqual(sorted(r['key'] for r in ies), ['MP::CI East::IE MP', 'MP::CI West::IE MP'])  # one IE name, two CIs
        self.assertEqual(sum(r['total_sites'] for r in ies), 4)
        options = self.get('allkpis-filters', circle='MP')
        self.assertEqual({i['key'] for i in options['ies']}, {'MP::CI East::IE MP', 'MP::CI West::IE MP'})
        self.assertEqual(options['site_count'], 4)  # RJ is outside the selected circle
        east = self.get('allkpis-summary', ie='MP::CI East::IE MP', date_from='2026-10-01', date_to='2026-10-03')['current']
        self.assertEqual(east['total_sites'], 2)

    def test_rca_uses_the_approved_final_bucket_mapping_and_ownership_is_not_configured(self):
        for bucket in ('bsnl ofc', 'TCS', 'BBNL OFC'):  # BBNL OFC is a Sub Bucket, not a Final Bucket: Not mapped
            RcaRecord.objects.create(reporting_date=date(2026, 10, 2), project=G4, project_raw=G4, circle='MP', circle_raw='MP', site_id='UVMP101',
                                     site_key='UVMP101', occurrence=RcaRecord.objects.count() + 1, final_bucket=bucket, final_bucket_key=text_key(bucket),
                                     rca_text='x', rca_key='x')
        r = self.get('allkpis-rca', date_from='2026-10-01', date_to='2026-10-03')
        counts = {b['bucket']: b['records'] for b in r['buckets']}
        self.assertEqual((counts['BSNL OFC'], counts['TCS'], r['not_mapped']['records']), (1, 1, 1))
        self.assertEqual(len(r['buckets']), 10)
        self.assertFalse(r['ownership']['configured'])

    def test_access_follows_existing_permissions_and_circles(self):
        from apps.accounts import services as access
        from apps.accounts.models import Role, RolePermission
        role = Role.objects.create(name='MP viewer')
        RolePermission.objects.create(role=role, module='dashboard', action='view')
        user = portal_user('mp-kpi', 'member')
        access.assign(self.user, user, role, G4, ['MP'])
        self.client.force_login(user)
        s = self.get('allkpis-summary', date_from='2026-10-01', date_to='2026-10-03')['current']
        self.assertEqual(s['total_sites'], 4)  # never RJ
        self.assertEqual(self.client.get(reverse('allkpis-rca')).status_code, 403)  # no RCA Summary View
        self.client.force_login(portal_user('nobody-kpi', 'member'))
        self.assertEqual(self.client.get(reverse('allkpis-summary')).status_code, 403)

    def test_no_site_handover_in_any_response(self):
        """Site Handover is not a project concept: no All KPI's response contains site_handover_status or a handover label."""
        import json
        period = {'date_from': '2026-10-01', 'date_to': '2026-10-03'}
        responses = [self.get('allkpis-filters'), self.get('allkpis-summary', **period), self.get('allkpis-trends', granularity='day', **period),
                     self.get('allkpis-hierarchy', level='circle', **period), self.get('allkpis-sites', **period), self.get('allkpis-rca', **period)]
        for body in responses:
            self.assertNotIn('handover', json.dumps(body).lower())
        pending = responses[1]['pending']
        self.assertEqual(list(pending), ['rca_ownership'])  # the RCA ownership status stays "Not configured"
        self.assertTrue(pending['rca_ownership'].startswith('Not configured'))
