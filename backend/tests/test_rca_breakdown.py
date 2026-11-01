"""Circle-wise Root Cause Breakdown on the RCA Summary (apps.rca.breakdown). Synthetic records in the test database."""
from datetime import date
from itertools import count

from django.urls import reverse

from apps.rca import breakdown
from apps.rca.models import RcaRecord
from apps.rca.parser import text_key

from .auth_helpers import SignedInTestCase, portal_user

_ids = count(1)
LABELS = ['PTPL-Battery', 'PTPL-OFC', 'PTPL-Others', 'BSNL-OFC', 'BSNL-Media', 'BSNL-Others', 'BBNL-OFC',
          'DMW', 'HFCL', 'Iaasp Link', 'Iaasp OFC', 'Iaasp Others', 'Iaasp Power', 'TCS', 'Tech Delay', 'Theft', 'Vsat', 'Others']


def record(circle: str, final_bucket: str, day=date(2026, 10, 21), project='4G Saturation'):
    n = next(_ids)
    return RcaRecord.objects.create(
        reporting_date=day, project=project, project_raw=project, circle=circle, circle_raw=circle, site_id=f'S{n}', site_key=f'S{n}',
        final_bucket=final_bucket, final_bucket_key=text_key(final_bucket), bucket_2='-', rca_text='x', rca_key='x')


class MappingTests(SignedInTestCase):
    def test_columns_in_the_workbook_order_with_confirmed_equivalents_only(self):
        self.assertEqual([label for label, _ in breakdown.COLUMNS], LABELS)
        cases = {'BSNL OFC': 'BSNL-OFC', 'ssa ofc': 'BSNL-OFC', 'IaasP OFC': 'Iaasp OFC', 'VSAT': 'Vsat', 'HFCl': 'HFCL',
                 'Other Media': 'Others', 'Above 98.5%': 'Others', 'NC': 'Others', 'Others': 'Others', 'BBNL Media': 'BBNL-OFC',
                 'Iaasp Other': 'Iaasp Others', 'Iaasp Link': 'Iaasp Link',
                 # confirmed 30 Oct 2026 for values that were Not mapped
                 'BSNL OFC Break': 'BSNL-OFC', 'ETR/SSA OFC': 'BSNL-OFC', 'Vsat-Media': 'BSNL-Media', 'bsnl Hub site': 'BSNL-Media', 'Ceragon': 'DMW'}
        self.assertEqual({raw: breakdown.category_of(raw) for raw in cases}, cases)
        for unknown in ('BB', 'Other', 'Below 60%', '71-90%', 'BSNL Link', 'PTPL Techn', '', '-', 'Solar'):  # PTPL Techn: out of scope
            self.assertIsNone(breakdown.category_of(unknown), unknown)  # never guessed, never "Others"
        self.assertEqual(breakdown.PENDING, ())  # BSNL-Link and PTPL-Techn are out of scope: no column at all
        values = [v for _, vs in breakdown.COLUMNS if vs for v in vs]
        self.assertEqual(len({text_key(v) for v in values}), len(values))  # one column per value: no double counting


class SummaryBreakdownTests(SignedInTestCase):
    def setUp(self):
        super().setUp()
        for circle, bucket, n in (('MP', 'BSNL OFC', 3), ('MP', 'SSA OFC', 1), ('MP', 'Other Media', 2), ('MP', 'BB', 1),
                                  ('OD', 'TCS', 4), ('OD', 'Iaasp Link', 1), ('OD', '-', 1)):
            for _ in range(n):
                record(circle, bucket)
        record('MP', 'TCS', day=date(2026, 10, 25), project='LWE')

    def get(self, **params):
        response = self.client.get(reverse('rca-summary'), params)
        self.assertEqual(response.status_code, 200, response.content[:300])
        return response.json()['breakdown']

    def test_counts_totals_and_percentages_reconcile(self):
        b = self.get()
        self.assertEqual(b['through'], '2026-10-25')
        rows = {r['circle']: r for r in b['rows']}
        self.assertEqual({k: v for k, v in rows['MP']['counts'].items() if v}, {'BSNL-OFC': 4, 'Others': 2, 'TCS': 1})
        self.assertEqual({k: v for k, v in rows['OD']['counts'].items() if v}, {'TCS': 4, 'Iaasp Link': 1})
        for r in (rows['MP'], rows['OD']):
            self.assertEqual(r['grand_total'], sum(v for v in r['counts'].values() if v))
        for label in LABELS:
            self.assertEqual(b['totals'][label], sum(r['counts'][label] or 0 for r in b['rows']), label)
        self.assertEqual(b['grand_total'], 12)
        self.assertEqual((b['percent_of_total']['TCS'], b['percent_of_total']['BSNL-OFC'], b['percent_of_total']['PTPL-OFC']), (41.67, 33.33, 0.0))
        self.assertNotIn('BSNL-Link', b['totals'])
        self.assertNotIn('PTPL-Techn', [c['label'] for c in b['columns']])
        # Unmapped values stay visible and outside the Grand Total: every record is accounted for.
        self.assertEqual(b['not_mapped'], {'records': 2, 'values': [{'final_bucket': 'BB', 'records': 1}, {'final_bucket': '(blank)', 'records': 1}]})
        self.assertEqual((rows['MP']['not_mapped'], rows['OD']['not_mapped']), (1, 1))
        self.assertEqual(b['records'], RcaRecord.objects.count())

    def test_the_selected_period_and_filters_apply(self):
        b = self.get(date_from='2026-10-21', date_to='2026-10-21')
        self.assertEqual((b['through'], b['grand_total'], b['totals']['TCS']), ('2026-10-21', 11, 4))  # the 25 Oct LWE record is out
        b = self.get(project='LWE')
        self.assertEqual((b['grand_total'], b['totals']['TCS']), (1, 1))
        b = self.get(circle='OD')
        self.assertEqual([r['circle'] for r in b['rows']], ['OD'])

    def test_an_empty_period_has_no_division_error_and_no_invented_zeros(self):
        b = self.get(date_from='2026-09-01', date_to='2026-09-30')
        self.assertTrue(b['empty'])
        self.assertEqual((b['grand_total'], b['through']), (0, '2026-09-30'))
        self.assertTrue(all(v is None for v in b['percent_of_total'].values()))
        self.assertTrue(all(r['grand_total'] is None and not r['has_records'] for r in b['rows']))

    def test_existing_kpis_are_unchanged_and_the_page_stays_admin_only(self):
        response = self.client.get(reverse('rca-summary')).json()
        self.assertEqual(response['kpis']['records'], 14)
        self.client.force_login(portal_user('rca-ci', 'ci'))
        self.assertEqual(self.client.get(reverse('rca-summary')).status_code, 403)


class SiteColumnsTests(SignedInTestCase):
    """Total, USD and NSLA Sites: Site Master and performance (the Overview's period_summary), never RCA records."""

    @classmethod
    def setUpClass(cls):
        import tempfile
        from pathlib import Path

        from django.test import override_settings

        from apps.dashboard import workbook

        from .test_metrics import USD_SITES
        from .workbook_factory import write_workbook
        super().setUpClass()
        cls._tmp = tempfile.TemporaryDirectory()
        cls._override = override_settings(MASTER_WORKBOOK_PATH=str(write_workbook(Path(cls._tmp.name) / 'usd.xlsx', USD_SITES)))
        cls._override.enable()
        workbook.clear_cache()

    @classmethod
    def tearDownClass(cls):
        from apps.dashboard import workbook
        cls._override.disable()
        workbook.clear_cache()
        cls._tmp.cleanup()
        super().tearDownClass()

    def setUp(self):
        super().setUp()
        for _ in range(5):  # many RCA records on one circle: they must not change the site counts
            record('MP', 'BSNL OFC', day=date(2026, 10, 2))
        record('RJ', 'TCS', day=date(2026, 10, 2))

    def sites(self, **params):
        response = self.client.get(reverse('rca-summary'), params)
        self.assertEqual(response.status_code, 200, response.content[:300])
        return response.json()['breakdown']

    def test_columns_per_circle_and_a_total_without_double_counting(self):
        b = self.sites()
        s = b['sites']
        mp, rj = s['rows']['MP'], s['rows']['RJ']
        # MP (4G + LWE): 5 active 4G sites (the inactive one excluded) + 1 LWE site; USD 101, 102, 103 + LWE MP.
        self.assertEqual((mp['total_sites'], mp['usd_sites']), (6, 4))
        self.assertEqual((rj['total_sites'], rj['usd_sites']), (1, 1))
        self.assertEqual({k: s['total'][k] for k in ('total_sites', 'usd_sites')}, {'total_sites': 7, 'usd_sites': 5})
        for key in ('total_sites', 'usd_sites', 'nsla_sites'):
            self.assertEqual(s['total'][key], sum(r[key] for r in s['rows'].values()), key)
        self.assertEqual(b['grand_total'], 6)  # the RCA counts are unchanged by the new columns

    def test_usd_and_nsla_reuse_the_overview_calculation_for_the_same_selection(self):
        from apps.dashboard.metrics import PENALTY_BUCKETS, Selection, period_summary
        from apps.uptimedb.datasource import current_dataset
        ds = current_dataset()
        for params, selection, days in (({}, Selection(scope='on_air'), [1, 2, 3]),
                                        ({'date': '2026-10-01'}, Selection(scope='on_air'), [1]),
                                        ({'project': '4G Saturation', 'circle': 'MP'}, Selection('4G Saturation', 'MP', 'on_air'), [1, 2, 3])):
            p = period_summary(ds, selection, dates=[date(2026, 10, d) for d in days], label='')
            total = self.sites(**params)['sites']['total']
            self.assertEqual(total['usd_sites'], p['unique_sites_down']['count'], params)
            self.assertEqual(total['nsla_sites'], sum(p['buckets'][b] for b in PENALTY_BUCKETS), params)

    def test_the_period_and_project_filters_change_the_values_and_rca_filters_do_not(self):
        mtd, day = self.sites()['sites']['rows']['MP'], self.sites(date='2026-10-01')['sites']['rows']['MP']
        self.assertEqual((mtd['usd_sites'], day['usd_sites']), (4, 3))  # 101, 102 (4G) + LWE MP on 1 Oct only
        self.assertEqual(self.sites(project='LWE')['sites']['rows']['MP']['total_sites'], 1)
        self.assertEqual(self.sites(final_bucket='tcs')['sites']['rows']['MP'], mtd)  # RCA filters describe records, not sites
