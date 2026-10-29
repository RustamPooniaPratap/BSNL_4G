"""Circle-wise Root Cause Breakdown on the RCA Summary (apps.rca.breakdown). Synthetic records in the test database."""
from datetime import date
from itertools import count

from django.urls import reverse

from apps.rca import breakdown
from apps.rca.models import RcaRecord
from apps.rca.parser import text_key

from .auth_helpers import SignedInTestCase, portal_user

_ids = count(1)
LABELS = ['PTPL-Battery', 'PTPL-OFC', 'PTPL-Techn', 'PTPL-Others', 'BSNL-OFC', 'BSNL-Media', 'BSNL-Link', 'BSNL-Others', 'BBNL-OFC',
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
                 'Iaasp Other': 'Iaasp Others', 'Iaasp Link': 'Iaasp Link', 'PTPL Techn': 'PTPL-Techn'}
        self.assertEqual({raw: breakdown.category_of(raw) for raw in cases}, cases)
        for unknown in ('BB', 'Other', 'Below 60%', '71-90%', 'BSNL Link', '', '-', 'Solar'):
            self.assertIsNone(breakdown.category_of(unknown), unknown)  # never guessed, never "Others"
        self.assertEqual(breakdown.PENDING, ('BSNL-Link',))
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
            if label != 'BSNL-Link':
                self.assertEqual(b['totals'][label], sum(r['counts'][label] or 0 for r in b['rows']), label)
        self.assertEqual(b['grand_total'], 12)
        self.assertEqual((b['percent_of_total']['TCS'], b['percent_of_total']['BSNL-OFC'], b['percent_of_total']['PTPL-OFC']), (41.67, 33.33, 0.0))
        self.assertIsNone(b['totals']['BSNL-Link'])  # pending: empty, not 0
        self.assertIsNone(rows['MP']['counts']['BSNL-Link'])
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
