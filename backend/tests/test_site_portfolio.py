"""Site Portfolio on the new data layer (/api/site-portfolio/, apps.sitedata.portfolio). Synthetic files, test database only."""
import dataclasses
from datetime import datetime

import numpy as np
import pandas as pd
from django.urls import reverse

from apps.accounts import services as access_services
from apps.accounts.models import Role, RolePermission
from apps.dashboard import metrics
from apps.sitedata import calculations, portfolio
from apps.sitedata.models import DailySitePerformance
from tests.auth_helpers import SignedInTestCase, portal_user
from tests.test_sitedata import MATRIX_HEADER, SiteDataTestCase, write_sheet
from tests.workbook_factory import DEFAULT_SITES, write_workbook

G4, LWE = '4G Saturation', 'LWE'
# Entity, Circle, BSNL Site ID, Name, BA, OA, District, O&M Start Date, On-Air status, On-Air Date, IE, CI, B1, B28
MATRIX = [
    ['4G Saturation', 'Madhya Pradesh', 'UVMP001', 'Alpha', 'B', 'O', 'D', datetime(2025, 10, 1), 'Yes', datetime(2024, 7, 1), 'IE One', 'CI East', '', ''],
    ['4G Saturation', 'Madhya Pradesh', 'UVMP002', 'Bravo', 'B', 'O', 'D', None, 'Yes', datetime(2026, 10, 2), 'IE Two', 'CI West', '', ''],  # On-Air from 2 Oct
    ['4G Saturation', 'Rajasthan', 'UVRJ001', 'Delta', 'B', 'O', 'D', datetime(2025, 1, 1), 'Yes', datetime(2025, 1, 1), 'IE RJ', 'CI RJ', '', ''],
    ['LWE', 'Madhya Pradesh', 'LWEMP01', 'Echo', 'B', 'O', 'D', datetime(2026, 11, 15), 'Yes', datetime(2025, 1, 1), 'IE L', 'CI L', '', ''],  # O&M from Nov
    ['LWE', 'Odisha', 'LWEOD01', 'Foxtrot', 'B', 'O', 'D', datetime(2025, 1, 1), 'Yes', datetime(2025, 1, 1), 'IE OD', 'CI OD', '', ''],
    ['LWE', 'Odisha', 'LWEOD02', 'Juliet', 'B', 'O', 'D', datetime(2025, 1, 1), 'Yes', datetime(2025, 1, 1), 'IE OD', 'CI OD', '', ''],
    ['VI-HPSC', 'Delhi-NCR', 'VIDL001', 'Hotel', 'D', 'D', 'D', None, 'Yes', None, '', '', '', ''],     # outside the dashboard scope
    ['Sterlite', 'Madhya Pradesh', 'STMP001', 'India', 'D', 'D', 'D', None, 'Yes', None, '', '', '', ''],
]
# Daily outage minutes on 1-3 Oct (workbook factory): UVMP001 [0, 144, 1440], UVMP002 [72, 0, 0], UVRJ001 [0, 0, 0],
# LWEMP01 [288, 0, 0], LWEOD01 [0, 720, blank], LWEOD02 [0, 0, 0]; UVMP003 and LWEBH01 are not in the matrix (unmatched).
# LWEOD02 keeps Odisha LWE reporting on 3 Oct, so LWEOD01's blank is a site gap and 3 Oct a complete reporting date.
SITES = [*DEFAULT_SITES, ('LWE', 'Odisha', 'LWEOD02', 'Juliet', 'Yes', 'Yes', [0, 0, 0])]


class SitePortfolioTests(SignedInTestCase, SiteDataTestCase):
    def setUp(self):
        super().setUp()
        portfolio.clear_cache()
        self.addCleanup(portfolio.clear_cache)

    def load(self, sites=None):
        self.load_matrix(MATRIX)
        from apps.sitedata import uptime_master
        uptime_master.commit(uptime_master.preview(write_workbook(self.tmp / 'oct.xlsx', SITES if sites is None else sites), 'oct.xlsx',
                                                   user=self.admin), user=self.admin)
        calculations.calculate_month(datetime(2026, 10, 1).date())

    def get(self, name, **params):
        response = self.client.get(reverse(f'site-portfolio-{name}'), params)
        self.assertEqual(response.status_code, 200, response.content[:400])
        return response.json()

    def summary(self, scope, **params):
        return self.get('summary', scope=scope, reporting_date='2026-10-03', **params)

    def test_kpi_counts_from_the_matrix_dates_and_outside_scope_excluded(self):
        self.load()
        counts = {s: self.summary(s)['metrics']['sites_in_scope'] for s in ('on_air', 'om_start')}
        self.assertEqual(counts, {'on_air': 6, 'om_start': 4})  # O&M: UVMP001, UVRJ001, LWEOD01/02; LWEMP01 starts in Nov
        for scope in ('on_air', 'om_start'):
            summary = self.summary(scope)
            self.assertEqual(summary['metrics']['sites_total'], 6)  # full Matrix inventory, independent of population
            self.assertEqual(summary['status_counts']['total'], 6)
        self.assertEqual(self.summary('on_air')['source']['data_layer'], 'sitedata')

    def test_circle_breakdown_separates_technologies_and_reconciles_with_the_kpis(self):
        self.load()
        on_air = self.get('breakdowns', scope='on_air', reporting_date='2026-10-03')['circles']
        rows = {(c['report_type'], c['circle']): c for c in on_air}
        self.assertEqual({key: row['sites_in_scope'] for key, row in rows.items()},
                         {(G4, 'MP'): 2, (G4, 'RJ'): 1, (LWE, 'MP'): 1, (LWE, 'OD'): 2})  # MP has both technologies
        self.assertEqual({key: row['sites_total'] for key, row in rows.items()},
                         {(G4, 'MP'): 2, (G4, 'RJ'): 1, (LWE, 'MP'): 1, (LWE, 'OD'): 2})
        self.assertEqual(sum(row['sites_total'] for row in rows.values()), 6)
        for scope in ('on_air', 'om_start'):
            circles = self.get('breakdowns', scope=scope, reporting_date='2026-10-03')['circles']
            summary = self.summary(scope)
            self.assertEqual(sum(c['sites_in_scope'] for c in circles), summary['metrics']['sites_in_scope'], scope)
            self.assertEqual(sum(c['sites_total'] for c in circles), summary['metrics']['sites_total'], scope)
        om_rows = {(c['report_type'], c['circle']): c for c in self.get('breakdowns', scope='om_start', reporting_date='2026-10-03')['circles']}
        self.assertEqual((rows[(G4, 'MP')]['ci_count'], rows[(G4, 'MP')]['ie_count']), (2, 2))
        self.assertEqual((om_rows[(G4, 'MP')]['ci_count'], om_rows[(G4, 'MP')]['ie_count']), (1, 1))
        self.assertEqual((om_rows[(LWE, 'MP')]['sites_total'], om_rows[(LWE, 'MP')]['sites_in_scope'],
                          om_rows[(LWE, 'MP')]['ci_count'], om_rows[(LWE, 'MP')]['ie_count']), (1, 0, 0, 0))

    def test_duplicate_matrix_site_ids_do_not_inflate_inventory_or_population_counts(self):
        self.load()
        ds = portfolio.portfolio_dataset('on_air')
        duplicate = 0
        sites = pd.concat([ds.sites, ds.sites.iloc[[duplicate]]], ignore_index=True)
        history = tuple({**entry, 'outage': np.concatenate([entry['outage'], entry['outage'][[duplicate]]], axis=0)}
                        for entry in ds.daily_history)
        monthly = (np.concatenate([ds.monthly_outage, ds.monthly_outage[[duplicate]]], axis=0)
                   if ds.monthly_outage is not None else None)
        duplicated = dataclasses.replace(
            ds, sites=sites, outage=np.concatenate([ds.outage, ds.outage[[duplicate]]], axis=0),
            daily_history=history, monthly_outage=monthly, _positions={},
        )

        summary = metrics.summary(duplicated, metrics.Selection(None, None, 'on_air'), datetime(2026, 10, 3).date())
        breakdown = metrics.breakdown(duplicated, metrics.Selection(None, None, 'on_air'), datetime(2026, 10, 3).date(),
                                      include_inventory=True)

        self.assertEqual((summary['metrics']['sites_total'], summary['metrics']['sites_in_scope'],
                          summary['status_counts']['total']), (6, 6, 6))
        self.assertEqual(sum(row['sites_total'] for row in breakdown['circles']), 6)
        self.assertEqual(sum(row['sites_in_scope'] for row in breakdown['circles']), 6)

    def _om_head_role(self, *, can_view=False):
        role = Role.objects.create(name='O&M Head')
        if can_view:
            RolePermission.objects.create(role=role, module='dashboard', action='view')
        return role

    def _assign_om_head(self, user, role, project=G4, circles=None, status='active'):
        return access_services.assign(self.admin, user, role, project, circles, status=status)

    def test_breakdown_lists_active_heads_for_circle_and_multiple_assignments(self):
        self.load()
        role = self._om_head_role()
        first = portal_user('head-one', None)
        first.first_name, first.last_name = 'Ada', 'Head'
        first.save(update_fields=['first_name', 'last_name'])
        second = portal_user('head-two', None)
        second.first_name, second.last_name = 'Bela', 'Head'
        second.save(update_fields=['first_name', 'last_name'])
        inactive_user = portal_user('inactive-head', None, active=False)
        other_role = Role.objects.create(name='Other role')
        unrelated = portal_user('not-a-head', None)

        self._assign_om_head(first, role, circles=['MP'])
        self._assign_om_head(second, role, circles=['MP'])
        self._assign_om_head(second, role, circles=['RJ'])
        self._assign_om_head(inactive_user, role, circles=['MP'])
        inactive_assignment_user = portal_user('inactive-assignment', None)
        self._assign_om_head(inactive_assignment_user, role, circles=['MP'], status='inactive')
        self._assign_om_head(unrelated, other_role, circles=['MP'])

        rows = {(row['report_type'], row['circle']): row for row in self.get('breakdowns', scope='on_air', reporting_date='2026-10-03')['circles']}
        self.assertEqual(rows[(G4, 'MP')]['om_heads'], ['Ada Head', 'Bela Head'])
        self.assertEqual(rows[(G4, 'RJ')]['om_heads'], ['Bela Head'])
        self.assertEqual(rows[(LWE, 'MP')]['om_heads'], [])
        self.assertEqual(rows[(LWE, 'OD')]['om_heads'], [])

    def test_project_wide_head_assignment_expands_to_active_project_circles(self):
        self.load()
        role = self._om_head_role()
        head = portal_user('project-head', None)
        head.first_name, head.last_name = 'Casey', 'Head'
        head.save(update_fields=['first_name', 'last_name'])
        self._assign_om_head(head, role, circles=None)

        rows = {(row['report_type'], row['circle']): row for row in self.get('breakdowns', scope='on_air', reporting_date='2026-10-03')['circles']}
        self.assertEqual(rows[(G4, 'MP')]['om_heads'], ['Casey Head'])
        self.assertEqual(rows[(G4, 'RJ')]['om_heads'], ['Casey Head'])
        self.assertEqual(rows[(LWE, 'MP')]['om_heads'], [])

    def test_head_role_or_assignment_changes_are_reflected_and_access_is_scoped(self):
        self.load()
        role = self._om_head_role(can_view=True)
        other_role = Role.objects.create(name='Other assignment')
        head = portal_user('scoped-head', None)
        head.first_name, head.last_name = 'Dana', 'Head'
        head.save(update_fields=['first_name', 'last_name'])
        outside = portal_user('outside-head', None)
        outside.first_name, outside.last_name = 'Eli', 'Head'
        outside.save(update_fields=['first_name', 'last_name'])
        assignment = self._assign_om_head(head, role, circles=['MP'])[0]
        self._assign_om_head(outside, role, project=LWE, circles=['MP'])

        self.client.force_login(head)
        response = self.client.get(reverse('site-portfolio-breakdowns'), {'scope': 'on_air', 'reporting_date': '2026-10-03'})
        self.assertEqual(response.status_code, 200, response.content[:400])
        rows = response.json()['circles']
        self.assertEqual([(row['report_type'], row['circle']) for row in rows], [(G4, 'MP')])
        self.assertEqual(rows[0]['om_heads'], ['Dana Head'])

        self.client.force_login(self.admin)
        access_services.update_assignment(self.admin, assignment, role=other_role)
        rows = self.get('breakdowns', scope='on_air', reporting_date='2026-10-03')['circles']
        mp = next(row for row in rows if (row['report_type'], row['circle']) == (G4, 'MP'))
        self.assertEqual(mp['om_heads'], [])

        changed = Role.objects.get(pk=role.pk)
        changed.is_active = False
        changed.save(update_fields=['is_active'])
        self.assertEqual(next(row for row in self.get('breakdowns', scope='on_air', reporting_date='2026-10-03')['circles']
                              if (row['report_type'], row['circle']) == (LWE, 'MP'))['om_heads'], [])

    def test_circle_and_technology_filters_are_independent(self):
        self.load()
        self.assertEqual(self.summary('on_air', circle='MP')['metrics']['sites_in_scope'], 3)               # 4G + LWE in MP
        self.assertEqual(self.summary('on_air', circle='MP', report_type=LWE)['metrics']['sites_in_scope'], 1)
        self.assertEqual(self.summary('on_air', report_type=G4)['metrics']['sites_in_scope'], 3)
        options = self.get('filters')
        by_circle = {c['value']: c['report_types'] for c in options['circles']}  # plus the Organization's other configured circles
        self.assertEqual(by_circle['MP'], [G4, LWE])
        self.assertIn(LWE, by_circle['OD'])
        self.assertIn(G4, by_circle['RJ'])

    def test_on_air_availability_counts_each_site_from_its_on_air_date(self):
        self.load()
        on_air = self.summary('on_air')['metrics']
        # UVMP002 is On-Air from 2 Oct: its 72 minutes on 1 Oct are not On-Air days. LWEOD01 has no 3 Oct value (missing, not 0).
        outage, site_days = 1584 + 0 + 0 + 288 + 720 + 0, 3 + 2 + 3 + 3 + 2 + 3
        self.assertAlmostEqual(on_air['mtd_uptime_pct'], round(100 * (1 - outage / (1440 * site_days)), 4), places=3)
        self.assertEqual(on_air['sites_total'], 6)  # Inventory remains full while performance uses On-Air dates.

    def test_date_filter_and_missing_records(self):
        self.load()
        day1 = self.get('summary', scope='on_air', reporting_date='2026-10-01')
        self.assertEqual((day1['reporting_date'], day1['mtd_window']['days_reported']), ('2026-10-01', 1))
        day3 = self.summary('on_air')
        self.assertEqual(day3['mtd_window']['days_reported'], 3)
        self.assertEqual(day3['metrics']['sites_reported'], 5)  # LWEOD01 has no 3 Oct value
        bad = self.client.get(reverse('site-portfolio-summary'), {'scope': 'on_air', 'reporting_date': '2026-10-09'})
        self.assertEqual(bad.status_code, 400)  # no data on 9 Oct: not a reporting date

    def test_a_gap_day_does_not_hide_later_dates(self):
        # Nobody reported on 2 Oct: 1 and 3 Oct are both reporting dates; 2 Oct is not reported (never zero).
        sites = [('4G Satu.', 'MP', 'UVMP001', 'Alpha', 'Yes', 'Yes', [0, None, 30]), ('4G Satu.', 'RJ', 'UVRJ001', 'Delta', 'Yes', 'Yes', [0, None, 0])]
        self.load(sites)
        options = self.get('filters')
        self.assertEqual(options['reporting_dates'], ['2026-10-01', '2026-10-03'])
        continuity = options['source']['continuity']
        self.assertEqual((continuity['dates_with_data'], continuity['continuous_until'], continuity['excluded_after_gap']),
                         (['2026-10-01', '2026-10-03'], '2026-10-03', []))
        self.assertEqual(self.client.get(reverse('site-portfolio-summary'), {'scope': 'on_air', 'reporting_date': '2026-10-03'}).status_code, 200)
        self.assertEqual(self.get('summary', scope='on_air', reporting_date='2026-10-03')['mtd_window']['days_reported'], 2)

    def test_period_reports_the_reporting_days_used(self):
        self.load()
        days = self.get('period', scope='on_air', period='days', days='2026-10-01,2026-10-02', label='1-2 Oct')
        self.assertEqual(days['days_reported'], 2)
        month = self.get('period', scope='on_air', period='months', months='2026-10', label='Oct-26')
        self.assertEqual((month['kind'], month['days_reported']), ('months', 3))  # the days with data, not 31 calendar days

    def test_conversion_activity_from_the_matrix_dates(self):
        self.load()
        activity = self.get('conversion-activity', month='2026-10')
        self.assertEqual((activity['on_air']['this_month']['count'], activity['om_start']['this_month']['count']), (1, 0))  # UVMP002 On-Air 2 Oct
        self.assertEqual(activity['sites'], 6)

    def test_no_fallback_to_the_old_tables_when_the_new_layer_is_empty(self):
        response = self.client.get(reverse('site-portfolio-filters'))
        self.assertEqual(response.status_code, 503)
        self.assertIn('new data layer', response.json()['error'])

    def test_users_see_only_their_circles(self):
        from apps.accounts import services as access
        from apps.accounts.models import Role, RolePermission
        self.load()
        role = Role.objects.create(name='MP viewer')
        RolePermission.objects.create(role=role, module='dashboard', action='view')
        user = portal_user('mp-portfolio', 'member')
        access.assign(self.user, user, role, G4, ['MP'])
        self.client.force_login(user)
        self.assertEqual(self.summary('on_air')['metrics']['sites_in_scope'], 2)  # 4G MP only
        self.assertEqual(self.get('conversion-activity', month='2026-10')['sites'], 2)

    def test_nothing_is_written_by_the_api(self):
        self.load()
        before = DailySitePerformance.objects.count()
        for name in ('filters', 'summary', 'breakdowns'):
            self.client.get(reverse(f'site-portfolio-{name}'), {'scope': 'on_air', 'reporting_date': '2026-10-03'})
        self.assertEqual(DailySitePerformance.objects.count(), before)

    def test_no_site_handover_field_in_any_response(self):
        """There is no Site Handover concept: no Site Portfolio response may contain such a field."""
        import json
        self.load()
        responses = [self.get('filters'), self.summary('on_air'), self.summary('om_start'),
                 self.get('breakdowns', scope='on_air', reporting_date='2026-10-03'),
                     self.get('period', scope='on_air', period='days', days='2026-10-01', label='1 Oct'),
                     self.get('conversion-activity', month='2026-10')]
        for body in responses:
            self.assertNotIn('handover', json.dumps(body).lower())
