"""Approved calculation / reporting rules across consumers (DATA_PIPELINE_AUDIT C-3..C-13; rules B-3..B-7).

- USD / NSLA: one per-site rule each (metrics.usd_mask / nsla_mask), identical in the dashboard, All KPI's, the RCA
  breakdown and the Excel export.
- Weeks and months: Complete only when ended and covered for the units in view; otherwise Provisional, figures shown.
- History months: reporting days (never calendar days), each site's own effective dates.
- Emailed reports equal the portal download; missing-submission alerts from the coverage table.
Test database only (sitedata factory records).
"""
from __future__ import annotations

import io
from datetime import date

from django.urls import reverse
from openpyxl import load_workbook

from apps.dashboard import metrics
from apps.sitedata import portfolio
from tests.auth_helpers import SignedInTestCase, portal_user
from tests.sitedata_factory import make_daily, make_site, make_unit

G4, LWE = '4G Saturation', 'LWE'
OCT = [date(2026, 10, d) for d in range(1, 10)]  # data through 9 Oct
EXACT = 1440 * (1 - 0.985)  # 21.60000000000002 in floating point: exactly 98.5%


def days(n: int, month: int = 10) -> list[date]:
    return [date(2026, month, d) for d in range(1, n + 1)]


class Base(SignedInTestCase):
    def setUp(self):
        super().setUp()
        portfolio.clear_cache()
        self.addCleanup(portfolio.clear_cache)

    def get(self, name, expected=200, **params):
        response = self.client.get(reverse(name), params)
        self.assertEqual(response.status_code, expected, response.content[:400])
        return response.json()

    def site(self, sid, outages, *, technology=G4, circle='MP', on_air=date(2025, 1, 1), om=date(2025, 1, 1), dates=OCT):
        site = make_site(sid, technology=technology, circle=circle, on_air_date=on_air, om_start_date=om)
        for day, outage in zip(dates, outages):
            if outage is not None:
                make_daily(site, day, outage)
        return site


class UsdNslaIdenticalEverywhereTests(Base):
    """One fixture: EXACT (98.5% every day) is USD, not NSLA; ONEBAD (one bad day, 99.2% over the period) is USD, not
    NSLA; BELOW (97.9%) is USD and NSLA; NOTOM (no O&M Start date, 58%) is excluded from NSLA (and from the O&M Start USD);
    ZERO is neither; MISSING has no value (never zero)."""

    def setUp(self):
        super().setUp()
        self.site('EXACT', [EXACT] * 9)
        self.site('ONEBAD', [100] + [0] * 8)
        self.site('BELOW', [30] * 9)
        self.site('NOTOM', [600] * 9, om=None)
        self.site('ZERO', [0] * 9)
        self.site('MISSING', [None] * 9)
        portfolio.clear_cache()

    def test_nsla_and_usd_are_the_same_in_every_consumer(self):
        period = dict(date_from='2026-10-01', date_to='2026-10-09')
        # Dashboard: trend-period KPI (O&M Start scope for the O&M Start USD population), summary, records, team NSLA.
        kpi = self.get('dashboard-period', scope='om_start', period='range', start_date='2026-10-01', end_date='2026-10-09')
        self.assertEqual((kpi['nsla_sites']['count'], kpi['unique_sites_down']['count']), (1, 3))
        self.assertEqual(self.get('dashboard-period', scope='on_air')['nsla_sites']['count'], 1)  # NSLA ignores the scope
        summary = self.get('dashboard-summary')['metrics']
        self.assertEqual((summary['nsla_sites_mtd'], summary['nsla_eligible_sites']), (1, 5))
        records = self.get('dashboard-records', scope='on_air', below_sla='true')['records']
        self.assertEqual([r['site_id'] for r in records], ['BELOW'])
        team = self.get('dashboard-teams-monthly', group='ci')['totals']['months']['2026-10']
        self.assertEqual((team['nsla_sites'], team['population']), (1, 5))
        # All KPI's
        kpis = self.get('allkpis-summary', **period)['current']
        self.assertEqual((kpis['usd_sites'], kpis['nsla_sites']), (3, 1))
        sites = {r['site_id']: r for r in self.get('allkpis-sites', **period)['rows']}
        self.assertEqual({s: (sites[s]['usd'], sites[s]['nsla']) for s in ('EXACT', 'ONEBAD', 'BELOW', 'NOTOM', 'ZERO')},
                         {'EXACT': (True, False), 'ONEBAD': (True, False), 'BELOW': (True, True), 'NOTOM': (False, False),
                          'ZERO': (False, False)})
        # RCA breakdown
        from apps.rca import breakdown
        rca = breakdown.site_metrics(period, None, ['MP'])
        self.assertEqual((rca['total']['usd_sites'], rca['total']['nsla_sites']), (3, 1))
        self.assertEqual(rca['nsla_site_keys'], {(G4, 'BELOW')})
        # Excel export (Summ: Unique Site Down and NSLA, O&M Start sites, month to date)
        wb = load_workbook(io.BytesIO(self.client.get(reverse('dashboard-export-consolidated'), {'reporting_date': '2026-10-09'}).content))
        self.assertEqual((self.summ_total(wb, 'Unique Site Down'), self.summ_total(wb, 'NSLA Sites')), (3, 1))

    def summ_total(self, wb, title: str):
        ws = wb['Summ']
        cells = [[c.value for c in row] for row in ws.iter_rows()]
        top = next(i for i, row in enumerate(cells) if any(isinstance(v, str) and f'- {title}' in v for v in row))
        header = cells[top + 1]
        total = next(row for row in cells[top + 2:] if 'Grand Total' in row)
        return total[header.index('Oct-26 MTD')]

    def test_rca_nsla_records_match_on_project_and_site_key(self):
        from tests.test_rca_breakdown import record
        from apps.rca.models import RcaRecord
        from apps.sitedata.identifiers import key_of
        for sid, project in (('below', G4), ('BELOW  ', G4), ('BELOW', LWE), ('EXACT', G4)):
            r = record('MP', 'BSNL OFC', day=date(2026, 10, 2), project=project, site_id=sid)
            RcaRecord.objects.filter(pk=r.pk).update(site_key=key_of(sid))
        b = self.get('rca-summary', rca_scope='nsla', date_from='2026-10-01', date_to='2026-10-09')['breakdown']
        self.assertEqual(b['nsla_rca_records'], 2)  # the two 4G BELOW spellings; not LWE BELOW, not EXACT


class WeekStatusTests(Base):
    """4G MP covered every day 1-9 Oct; LWE MP misses 5 Oct and 9 Oct. Week 1 is Complete for 4G, Provisional for LWE;
    Week 2 (data through 9 Oct) is Provisional for both, with its figures shown."""

    def setUp(self):
        super().setUp()
        make_unit(G4, 'MP')
        make_unit(LWE, 'MP')
        self.site('G1', [10] * 9)
        self.site('G2', [0] * 9)
        self.site('L1', [20, 20, 20, 20, None, 20, 20, 20, None], technology=LWE)
        portfolio.clear_cache()

    def test_dashboard_weeks_thresholds_period_and_all_kpis(self):
        g4 = self.get('dashboard-trends', scope='on_air', report_type=G4)['weeks']
        self.assertEqual([(w['status'], w['complete']) for w in g4[:2]], [('Complete', True), ('Provisional', False)])
        self.assertEqual((g4[1]['days_reported'], g4[1]['uptime_pct']), (2, round(100 * (1 - 20 / (1440 * 4)), 4)))
        self.assertEqual(g4[1]['missing'], [])  # not ended yet; no missing day so far
        lwe = self.get('dashboard-trends', scope='on_air', report_type=LWE)['weeks']
        self.assertEqual([w['status'] for w in lwe[:2]], ['Provisional', 'Provisional'])
        self.assertEqual(lwe[0]['missing'], [{'date': '2026-10-05', 'units': ['LWE MP']}])
        self.assertEqual(lwe[1]['missing'], [{'date': '2026-10-09', 'units': ['LWE MP']}])
        periods = {p['key']: p for p in self.get('dashboard-thresholds', scope='on_air', report_type=G4)['periods']}
        self.assertEqual((periods['w1']['status'], periods['w2']['status'], periods['w2']['days_reported']), ('Complete', 'Provisional', 2))
        self.assertEqual(self.get('dashboard-period', scope='on_air', report_type=G4, period='weeks', weeks='1')['status'], 'Complete')
        week2 = self.get('dashboard-period', scope='on_air', report_type=G4, period='weeks', weeks='2')
        self.assertEqual((week2['status'], week2['days_reported']), ('Provisional', 2))
        self.assertEqual(self.get('site-portfolio-period', scope='on_air', report_type=G4, period='weeks', weeks='1')['status'], 'Complete')
        points = self.get('allkpis-trends', project=G4, granularity='week', date_from='2026-10-01', date_to='2026-10-09')['points']
        self.assertEqual([(p['label'], p['status']) for p in points], [('Week 1 Oct 2026', 'Complete'), ('Week 2 Oct 2026', 'Provisional')])
        self.assertIsNotNone(points[1]['availability_pct'])
        lwe_points = self.get('allkpis-trends', project=LWE, granularity='week', date_from='2026-10-01', date_to='2026-10-09')['points']
        self.assertEqual([p['status'] for p in lwe_points], ['Provisional', 'Provisional'])

    def test_restricted_users_see_their_own_units(self):
        from apps.accounts.scope import set_pairs
        user = portal_user('ci-4g', 'ci')
        set_pairs(user, [(G4, 'MP')])
        self.client.force_login(user)
        weeks = self.get('dashboard-trends', scope='on_air')['weeks']
        self.assertEqual([w['status'] for w in weeks[:2]], ['Complete', 'Provisional'])
        user = portal_user('ci-lwe', 'ci')
        set_pairs(user, [(LWE, 'MP')])
        self.client.force_login(user)
        weeks = self.get('dashboard-trends', scope='on_air')['weeks']
        self.assertEqual([w['status'] for w in weeks[:2]], ['Provisional', 'Provisional'])

    def test_export_headers_label_provisional_weeks(self):
        response = self.client.get(reverse('dashboard-export-consolidated'), {'reporting_date': '2026-10-09', 'report_type': G4})
        ws = load_workbook(io.BytesIO(response.content))['Up-Time Report']
        headers = [c.value for c in ws[2]]
        self.assertEqual((headers.count('Wk-1'), headers.count('Wk-2 (Provisional)')), (2, 2))
        bucket = next(ws.cell(row=3, column=i + 1).value for i, h in enumerate(headers) if h == 'Bucket'
                      and isinstance(ws.cell(row=3, column=i + 1).value, str))
        self.assertIn('ROUND(', bucket)
        trend = load_workbook(io.BytesIO(response.content))['Day wise Trend']
        texts = {c.value for row in trend.iter_rows() for c in row if isinstance(c.value, str)}
        self.assertIn('Wk-2 (Oct-26) (Provisional)', texts)

    def test_missing_submission_alert_only_for_the_missing_unit(self):
        alerts = self.get('dashboard-alerts')['alerts']
        missing = [a for a in alerts if a['title'].startswith('Missing CSV')]
        self.assertEqual([(a['title'], a['severity'], a['link']) for a in missing],
                         [('Missing CSV: LWE MP 2026-10-09', 'warning', '/daily-ingestion')])

    def test_month_status_is_provisional_until_the_month_ends(self):
        months = self.get('dashboard-monthly', scope='on_air', report_type=G4)['months']
        self.assertEqual((months[-1]['status'], months[-1]['finalization_status']), ('Provisional', None))


class HistoryMonthTests(Base):
    """September is a history month with a missing day (30 Sep has no data): the export uses its reporting days, as the
    dashboard; a site On-Air from 5 Oct is not in September's population."""

    def setUp(self):
        super().setUp()
        sep = days(30, 9)
        self.site('H1', [100] * 29 + [None], dates=sep)
        self.site('H2', [0] * 29 + [None], dates=sep)
        for sid in ('H1', 'H2'):
            from apps.sitedata.models import Site
            for day in days(3):
                make_daily(Site.objects.get(bsnl_site_id=sid), day, 10)
        late = self.site('LATE', [500] * 3, on_air=date(2026, 10, 5), om=date(2026, 10, 5), dates=days(3))
        make_daily(late, date(2026, 9, 10), 700)  # a value before its On-Air date: never in September's On-Air population
        portfolio.clear_cache()

    def test_export_history_month_equals_the_dashboard(self):
        monthly = self.get('dashboard-monthly')['months']
        sep = next(m for m in monthly if m['key'] == '2026-09')
        self.assertEqual(sep['uptime_pct'], metrics.uptime_pct(100 * 29, 58))  # 58 reported site-days, not 60
        self.assertEqual((sep['sites_in_scope'], sep['status']), (2, 'Provisional'))  # LATE not On-Air in September
        wb = load_workbook(io.BytesIO(self.client.get(reverse('dashboard-export-consolidated'), {'reporting_date': '2026-10-03'}).content))
        ws = wb['Summ']
        cells = [[c.value for c in row] for row in ws.iter_rows()]
        top = next(i for i, row in enumerate(cells) if any(isinstance(v, str) and 'Overall Up-Time (On-Air sites)' in v for v in row))
        header = cells[top + 1]
        col = next(i for i, h in enumerate(header) if hasattr(h, 'month') and h.month == 9)
        total = next(row for row in cells[top + 2:] if 'Grand Total' in row)
        self.assertAlmostEqual(total[col], sep['uptime_pct'] / 100, places=6)
        up = wb['Up-Time Report']
        head = [c.value for c in up[2]]
        h1 = next(r for r in range(3, up.max_row + 1) if up.cell(row=r, column=3).value == 'H1')
        self.assertAlmostEqual(up.cell(row=h1, column=head.index('Sep-26 UpTime') + 1).value, 1 - 100 / 1440, places=9)

    def test_finalized_month_carries_its_status(self):
        from apps.sitedata.models import MonthFinalization
        MonthFinalization.objects.create(month=date(2026, 9, 1), status='incomplete_missing_data')
        sep = next(m for m in self.get('dashboard-monthly')['months'] if m['key'] == '2026-09')
        self.assertEqual((sep['finalization_status'], sep['finalization_label']), ('incomplete_missing_data', 'Incomplete — Missing Data'))


class EmailEqualsPortalTests(Base):
    def setUp(self):
        super().setUp()
        self.site('E1', [0] * 9)
        self.site('E2', [100] * 9)
        self.site('E3', [50] * 9, on_air=date(2026, 10, 20))  # not On-Air on the latest date: out of the default scope
        portfolio.clear_cache()

    def test_emailed_consolidated_report_equals_the_portal_download(self):
        from apps.alerts import reports
        name, data, _mime, _label = reports.build('consolidated', 'latest', None)
        portal = self.client.get(reverse('dashboard-export-consolidated'))
        self.assertEqual(portal.status_code, 200)

        def values(content):
            wb = load_workbook(io.BytesIO(content))
            return {ws.title: [[c.value for c in row] for row in ws.iter_rows()] for ws in wb.worksheets}
        self.assertEqual(values(data), values(portal.content))
        self.assertIn(name, portal['Content-Disposition'])
