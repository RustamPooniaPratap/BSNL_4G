"""Circle-wise Root Cause Breakdown on the RCA Summary (apps.rca.breakdown). Synthetic records in the test database."""
from datetime import date
from itertools import count

from django.urls import reverse

from apps.rca import breakdown
from apps.rca.models import RcaRecord
from apps.rca.parser import text_key

from .auth_helpers import SignedInTestCase, portal_user

_ids = count(1)
LABELS = ['IaaSP Power', 'IaaSP Others', 'IaaSP Battery', 'IaaSP OFC', 'BSNL OFC',
          'BSNL Media', 'Others', 'TCS', 'DMW', 'HFCL']


def record(circle: str, final_bucket: str, day=date(2026, 10, 21), project='4G Saturation', site_id=None):
    n = next(_ids)
    sid = site_id or f'S{n}'
    return RcaRecord.objects.create(
        reporting_date=day, project=project, project_raw=project, circle=circle, circle_raw=circle, site_id=sid, site_key=sid,
        occurrence=n,
        final_bucket=final_bucket, final_bucket_key=text_key(final_bucket), bucket_2='-', rca_text='x', rca_key='x')


class MappingTests(SignedInTestCase):
    def test_columns_are_the_approved_final_buckets_and_count_only_themselves(self):
        from apps.rca import taxonomy
        self.assertEqual([label for label, _ in breakdown.COLUMNS], LABELS)
        self.assertEqual([label for label, _ in breakdown.COLUMNS], list(taxonomy.APPROVED))  # the one taxonomy
        cases = {'BSNL OFC': 'BSNL OFC', 'IaasP OFC': 'IaaSP OFC', 'HFCl': 'HFCL', ' Others ': 'Others', 'IaaSP Battery': 'IaaSP Battery'}
        self.assertEqual({raw: breakdown.category_of(raw) for raw in cases}, cases)
        # No aliases or equivalents: former legacy values and anything else are Not mapped, never put in a column.
        for unknown in ('ssa ofc', 'VSAT', 'Other Media', 'Above 98.5%', 'NC', 'BBNL Media', 'BBNL OFC', 'Iaasp Other', 'Iaasp Link',
                        'Tech Delay', 'BB', 'Theft', 'BSNL OFC Break', 'ETR/SSA OFC', 'Vsat-Media', 'bsnl Hub site', 'Ceragon',
                        'Other', 'BSNL Link', 'PTPL Techn', '', '-', 'Solar'):
            self.assertIsNone(breakdown.category_of(unknown), unknown)
        self.assertEqual(breakdown.PENDING, ())
        values = [v for _, vs in breakdown.COLUMNS if vs for v in vs]
        self.assertEqual(len({text_key(v) for v in values}), len(values))  # one column per value: no double counting


class SummaryBreakdownTests(SignedInTestCase):
    def setUp(self):
        super().setUp()
        for circle, bucket, n in (('MP', 'BSNL OFC', 3), ('MP', 'bsnl ofc', 1), ('MP', 'Others', 2), ('MP', 'IaaSP Battery', 1),
                                  ('OD', 'TCS', 4), ('OD', 'IaaSP Others', 1), ('OD', '-', 1)):
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
        self.assertEqual({k: v for k, v in rows['MP']['counts'].items() if v}, {'BSNL OFC': 4, 'Others': 2, 'IaaSP Battery': 1, 'TCS': 1})
        self.assertEqual({k: v for k, v in rows['OD']['counts'].items() if v}, {'TCS': 4, 'IaaSP Others': 1})
        for r in (rows['MP'], rows['OD']):
            self.assertEqual(r['grand_total'], sum(v for v in r['counts'].values() if v))
        for label in LABELS:
            self.assertEqual(b['totals'][label], sum(r['counts'][label] or 0 for r in b['rows']), label)
        self.assertEqual(b['grand_total'], 13)
        self.assertEqual((b['percent_of_total']['TCS'], b['percent_of_total']['BSNL OFC'], b['percent_of_total']['IaaSP OFC']), (38.46, 30.77, 0.0))
        self.assertNotIn('BSNL-Link', b['totals'])
        self.assertNotIn('PTPL-Techn', [c['label'] for c in b['columns']])
        # Unmapped values stay visible and outside the Grand Total: every record is accounted for.
        self.assertEqual(b['not_mapped'], {'records': 1, 'values': [{'final_bucket': '(blank)', 'records': 1}]})
        self.assertEqual((rows['MP']['not_mapped'], rows['OD']['not_mapped']), (0, 1))
        self.assertEqual(b['records'], RcaRecord.objects.count())

    def test_the_selected_period_and_filters_apply(self):
        b = self.get(date_from='2026-10-21', date_to='2026-10-21')
        self.assertEqual((b['through'], b['grand_total'], b['totals']['TCS']), ('2026-10-21', 12, 4))  # the 25 Oct LWE record is out
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
    """Total, O&M Start, USD and NSLA Sites: Site Master and performance, never RCA records."""

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
        # RCA records on MP: 3 for UVMP102 (an NSLA site), 2 for UVMP101 (USD but >=98.5% uptime)
        for _ in range(3):
            record('MP', 'BSNL OFC', day=date(2026, 10, 2), site_id='UVMP102')
        for _ in range(2):
            record('MP', 'BSNL OFC', day=date(2026, 10, 2), site_id='UVMP101')
        # RCA record on RJ for UVRJ101 (an NSLA site)
        record('RJ', 'TCS', day=date(2026, 10, 2), site_id='UVRJ101')

    def sites(self, **params):
        response = self.client.get(reverse('rca-summary'), params)
        self.assertEqual(response.status_code, 200, response.content[:300])
        return response.json()['breakdown']

    def test_columns_per_circle_and_a_total_without_double_counting(self):
        b = self.sites()
        s = b['sites']
        mp, rj = s['rows']['MP'], s['rows']['RJ']
        # MP (4G + LWE): 6 active sites, 4 O&M Start sites; USD: 101, 102 + LWE MP (103 is down but not O&M Start -> excluded from USD).
        # NSLA: UVMP102 (outage 100, 200, 300 > 21.6 min). UVMP101 has outage 1 min <= 21.6 min -> not NSLA.
        self.assertEqual((mp['total_sites'], mp['om_start_sites'], mp['usd_sites'], mp['nsla_sites']), (6, 4, 3, 1))
        # RJ: UVRJ101 is O&M Start, USD (30 min), NSLA (30 min > 21.6 min -> <98.5%).
        self.assertEqual((rj['total_sites'], rj['om_start_sites'], rj['usd_sites'], rj['nsla_sites']), (1, 1, 1, 1))
        self.assertEqual({k: s['total'][k] for k in ('total_sites', 'om_start_sites', 'usd_sites', 'nsla_sites')},
                         {'total_sites': 7, 'om_start_sites': 5, 'usd_sites': 4, 'nsla_sites': 2})
        for key in ('total_sites', 'om_start_sites', 'usd_sites', 'nsla_sites'):
            self.assertEqual(s['total'][key], sum(r[key] for r in s['rows'].values()), key)
        self.assertEqual(b['grand_total'], 6)

    def test_rca_scope_toggle_filters_breakdown_records_without_affecting_kpis(self):
        # 1. All RCA (default)
        b_all = self.sites()
        self.assertEqual(b_all['rca_scope'], 'all')
        self.assertEqual(b_all['grand_total'], 6)
        self.assertEqual(b_all['all_rca_records'], 6)
        self.assertEqual(b_all['nsla_rca_records'], 4)  # 3 UVMP102 + 1 UVRJ101

        # 2. NSLA RCA (<98.5%)
        b_nsla = self.sites(rca_scope='nsla')
        self.assertEqual(b_nsla['rca_scope'], 'nsla')
        # Only records belonging to NSLA sites (UVMP102 and UVRJ101) appear in the table
        self.assertEqual(b_nsla['grand_total'], 4)
        self.assertEqual(b_nsla['rows'][0]['counts']['BSNL OFC'], 3)  # UVMP102 records only; UVMP101 (2 records) excluded

        # 3. Strict requirement: Site KPIs and Total row are identical between All RCA and NSLA RCA
        self.assertEqual(b_nsla['sites']['total'], b_all['sites']['total'])
        for circle in ('MP', 'RJ'):
            self.assertEqual(b_nsla['sites']['rows'][circle], b_all['sites']['rows'][circle])

        # 4. Strict requirement: Summary KPI cards remain unaffected
        resp_all = self.client.get(reverse('rca-summary'), {'rca_scope': 'all'}).json()
        resp_nsla = self.client.get(reverse('rca-summary'), {'rca_scope': 'nsla'}).json()
        self.assertEqual(resp_all['kpis'], resp_nsla['kpis'])

    def test_availability_thresholds_for_nsla(self):
        # 98.49% availability means outage > 21.6 min -> qualifies as NSLA
        # Exactly 98.5% availability means outage = 21.6 min -> does NOT qualify
        # 99.0% availability means outage = 14.4 min -> does NOT qualify
        self.assertGreater(1440 * (1 - 0.9849), breakdown.NSLA_OUTAGE_MINUTES_THRESHOLD)
        self.assertAlmostEqual(1440 * (1 - 0.985), breakdown.NSLA_OUTAGE_MINUTES_THRESHOLD)
        self.assertLess(1440 * (1 - 0.99), breakdown.NSLA_OUTAGE_MINUTES_THRESHOLD)

    def test_missing_availability_notification_identifies_unreported_om_sites(self):
        b = self.sites()
        missing = b.get('missing_availability')
        self.assertIsNotNone(missing)
        # UVMP105 is an On-Air site in USD_SITES with [None, None, None]; it is not O&M Start so not in missing OM list
        self.assertEqual(missing['count'], 0)
