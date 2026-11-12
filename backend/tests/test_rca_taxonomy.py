"""The approved RCA bucketization (apps.rca.taxonomy) and the PostgreSQL data path of the RCA pages.

Synthetic records in the test database only.
"""
from datetime import date, datetime
from io import StringIO
from pathlib import Path
from unittest import mock

from django.core.management import call_command
from django.urls import reverse

from apps.rca import taxonomy
from apps.rca.management.commands import rca_bucketization
from apps.rca.models import RcaEvent, RcaRecord
from apps.rca.parser import parse, text_key
from tests.sitedata_factory import make_site
from tests.test_rca import RcaTestCase, workbook


def record(final, b2, *, day=date(2026, 10, 21), project='4G Saturation', circle='OD', site='OD0001', minutes=10.0, occurrence=1):
    return RcaRecord.objects.create(reporting_date=day, project=project, project_raw=project, circle=circle, circle_raw=circle, site_id=site,
                                    site_key=site, occurrence=occurrence, outage_minutes=minutes, final_bucket=final, final_bucket_key=text_key(final),
                                    bucket_2=b2, bucket_2_key=text_key(b2), rca_text='Cause', rca_key='cause', source='import')


# The final approved taxonomy (4 Nov 2026), written out independently of taxonomy.py so a change there is caught.
EXPECTED = {
    'IaaSP Power': ['CCU fault', 'EB power cut', 'Solar Panel fault', 'RM fail', 'MPPT issue', 'Contactor faulty', 'Power cable faulty',
                    'LVD issue', 'Backplane faulty', 'High V & Low V'],
    'IaaSP Others': ['Shadow issue', 'EB Cable fault', 'EB tx. Faulty', 'EB Bill not paid', 'IaaSP Theft', 'CT payment issue', 'Owner issue',
                     'Natural Clamity', 'Tech Delay', 'IaaSP Link'],
    'IaaSP Battery': ['Battery issue', 'BB Theft', 'Low back Up', 'BMS faulty'],
    'IaaSP OFC': ['Incremental Fibre'],
    'BSNL OFC': ['SSA OFC', 'BSNL OFC', 'ETR OFC', 'BBNL OFC', 'WTR OFC', 'NTR', 'CNTX', 'JCNL', 'Maha IT', 'Pace OFC'],
    'BSNL Media': ['Nokia mini link', 'NEC Mini link', 'CPAN issue', 'Maan Media issue', 'BSNL Link', 'Vsat Media', 'BSNL Hub', 'BSNL Others',
                   'Fluctuation'],
    'Others': ['4G Sat. link site', 'IP site link', 'Others site link', 'ATC site link', 'Non IaaSP Theft'],
    'TCS': ['RAC Card', 'CEF Card', 'CEF12 Card', 'FTU', 'RRH Hardware', 'RRH Cable', 'RRH Cipri Cable', 'BBU', 'Partial band', 'S1 Link'],
    'DMW': ['Ceragoan Radio', 'DMW Cipri Cable', 'DMW Power cable', 'DMW RSL Issue', 'DMW pole mount Issue', 'Fluctuation', 'Cascading Cable'],
    'HFCL': ['HFCL Radio', 'HFCL Switch', 'HFCL POE', 'HFCL Power cable', 'HFCL RSL Issue', 'HFCL Pole mount Issue', 'HFCL Port', 'HFCL MCX0',
             'Fluctuation'],
}


class TaxonomyTests(RcaTestCase):
    def test_exactly_the_ten_approved_final_buckets_with_their_sub_buckets(self):
        self.assertEqual(len(taxonomy.APPROVED), 10)
        self.assertEqual({f: list(c) for f, c in taxonomy.APPROVED.items()}, EXPECTED)
        self.assertEqual(list(taxonomy.APPROVED), list(EXPECTED))  # the approved order
        self.assertEqual(taxonomy.classification(), [{'final_bucket': f, 'bucket_2': c} for f, c in EXPECTED.items()])

    def test_every_sub_bucket_is_approved_under_its_own_final_bucket(self):
        for final, children in EXPECTED.items():
            for child in children:
                self.assertEqual(taxonomy.resolve(final, child), taxonomy.Resolution(final, child, 'approved'), (final, child))
                self.assertIn(final, taxonomy.finals_of_sub_bucket(child))

    def test_the_approved_spellings_are_accepted_and_the_old_ones_are_not(self):
        self.assertEqual(taxonomy.resolve('DMW', 'Ceragoan Radio').status, 'approved')
        self.assertEqual(taxonomy.resolve('IaaSP Others', 'Natural Clamity').status, 'approved')
        self.assertEqual(taxonomy.resolve('DMW', 'Ceragon Radio').status, 'final_only')  # a warning, not corrected
        self.assertEqual(taxonomy.resolve('IaaSP Others', 'Natural Calamity').status, 'final_only')

    def test_ceragoan_radio_and_natural_clamity_upload_exactly_as_approved_with_no_warning(self):
        day = datetime(2026, 10, 21)
        row = lambda site, final, b2: [day, '4G Satu', 'Odisha', site, 'S', '', '', 'Yes', 5, final, b2, 'cause']  # noqa: E731
        path = workbook(Path(self.tmp.name) / 'approved.xlsx', rows=[
            row('OD1', 'DMW', 'Ceragoan Radio'), row('OD2', 'IaaSP Others', 'Natural Clamity'),
            row('OD3', ' DMW ', ' Ceragoan Radio '), row('OD4', 'IaaSP Others', '  Natural Clamity')])  # surrounding spaces
        result = parse(path, 'approved.xlsx')
        rows, report = result['rows'], result['report']
        self.assertEqual((report['valid_rows'], report['rejected_rows']), (4, 0))
        self.assertEqual({r['bucket_2'] for r in rows}, {'Ceragoan Radio', 'Natural Clamity'})  # never rewritten to another spelling
        self.assertEqual(report['classification'], {'approved': 4, 'final_only': 0, 'unapproved': 0, 'blank': 0})
        self.assertEqual(report['sub_bucket_warnings']['rows'], 0)
        # No warning or note of any kind about these values: no spelling, Sub Bucket or classification issue.
        self.assertEqual([i['code'] for i in report['all_issues'] if i['code'] not in ('project_label_to_confirm', 'whitespace_trimmed')], [])
        self.assertFalse(any('spelling' in i['message'].lower() for i in report['all_issues']))
        self.assertEqual(report['label_variants'], {'final_bucket': [], 'bucket_2': [], 'om_start_raw': []})

    def test_other_spellings_are_unapproved_values_not_spelling_mistakes(self):
        day = datetime(2026, 10, 21)
        row = lambda site, final, b2: [day, '4G Satu', 'Odisha', site, 'S', '', '', 'Yes', 5, final, b2, 'cause']  # noqa: E731
        path = workbook(Path(self.tmp.name) / 'other.xlsx', rows=[row('OD1', 'DMW', 'Ceragon Radio'), row('OD2', 'IaaSP Others', 'Natural Calamity')])
        result = parse(path, 'other.xlsx')
        warnings = [i for i in result['report']['all_issues'] if i['severity'] == 'warning']
        self.assertEqual([i['code'] for i in warnings], ['sub_bucket_not_approved', 'sub_bucket_not_approved'])
        self.assertTrue(all('not an approved Sub Bucket' in i['message'] and 'spelling' not in i['message'].lower() for i in warnings))
        self.assertEqual({r['bucket_2'] for r in result['rows']}, {'Ceragon Radio', 'Natural Calamity'})  # kept as uploaded, not corrected

    def test_others_under_iaasp_power_is_accepted_with_a_sub_bucket_warning(self):
        # "Others" is not one of IaaSP Power's Sub Buckets nor any other's: the record is kept (a warning, never a rejection).
        self.assertEqual(taxonomy.resolve('IaaSP Power', 'Others'), taxonomy.Resolution('IaaSP Power', None, 'final_only'))

    def test_an_approved_sub_bucket_under_another_final_bucket_is_a_classification_mismatch(self):
        self.assertEqual(taxonomy.resolve('BSNL Media', 'SSA OFC'), taxonomy.Resolution('BSNL Media', None, 'mismatch', ('BSNL OFC',)))
        self.assertEqual(taxonomy.resolve('IaaSP Power', 'EB Cable fault').other_final_buckets, ('IaaSP Others',))
        self.assertEqual(taxonomy.resolve('Others', 'Fluctuation').other_final_buckets, ('BSNL Media', 'DMW', 'HFCL'))
        for parent in ('BSNL Media', 'DMW', 'HFCL'):
            self.assertEqual(taxonomy.resolve(parent, 'Fluctuation').status, 'approved')

    def test_matching_ignores_surrounding_spaces_and_case_only_and_never_renames(self):
        self.assertEqual(taxonomy.resolve('  iaasp power ', ' ccu FAULT '), taxonomy.Resolution('IaaSP Power', 'CCU fault', 'approved'))
        self.assertEqual(taxonomy.resolve('BSNL-OFC', 'SSA OFC').status, 'unapproved')  # punctuation is not ignored
        self.assertEqual(taxonomy.resolve('BSNL OFC', 'JCNL OFC').status, 'final_only')  # other words: not "JCNL"
        self.assertEqual(taxonomy.resolve('Vsat', 'Vsat').status, 'unapproved')
        self.assertEqual(taxonomy.resolve('Other Media', '').status, 'unapproved')  # not one of the 10

    def test_blank_values(self):
        self.assertEqual(taxonomy.resolve('-', '').status, 'blank')  # no Final Bucket: rejected at upload
        self.assertIsNone(taxonomy.resolve('', 'Fluctuation').final_bucket)  # a blank is never Others
        self.assertEqual(taxonomy.resolve('TCS', '-'), taxonomy.Resolution('TCS', None, 'blank'))  # Sub Bucket blank: a warning

    def test_uploads_validate_against_the_taxonomy_and_keep_the_values_as_uploaded(self):
        day = datetime(2026, 10, 21)
        row = lambda site, final, b2: [day, '4G Satu', 'Odisha', site, 'S', '', '', 'Yes', 5, final, b2, 'cause']  # noqa: E731
        path = workbook(Path(self.tmp.name) / 'tax.xlsx', rows=[
            row('OD1', 'Iaasp Power', 'CCU FAULT'), row('OD2', 'DMW', 'Fluctuation'), row('OD3', 'Others', 'Flacuation'),
            row('OD4', 'Vsat', 'Vsat'), row('OD5', 'TCS', '-'), row('OD6', 'BSNL Media', 'SSA OFC'), row('OD7', 'IaaSP Power', 'Others'),
            row('OD8', 'DMW', 'Ceragoan Radio'), row('OD9', 'IaaSP Others', 'Natural Clamity'), row('OD10', '', 'BBU')])
        report = parse(path, 'tax.xlsx')
        parsed, r = report['rows'], report['report']
        stored = {x['site_id']: (x['final_bucket'], x['bucket_2']) for x in parsed}
        self.assertEqual(stored, {'OD1': ('Iaasp Power', 'CCU FAULT'), 'OD2': ('DMW', 'Fluctuation'), 'OD3': ('Others', 'Flacuation'),
                                  'OD5': ('TCS', '-'), 'OD7': ('IaaSP Power', 'Others'), 'OD8': ('DMW', 'Ceragoan Radio'),
                                  'OD9': ('IaaSP Others', 'Natural Clamity')})  # as uploaded: nothing renamed
        self.assertEqual((r['valid_rows'], r['rejected_rows']), (7, 3))
        errors = {i['site_id']: i['code'] for i in r['all_issues'] if i['severity'] == 'error'}
        self.assertEqual(errors, {'OD4': 'final_bucket_not_approved', 'OD6': 'sub_bucket_classification_mismatch', 'OD10': 'missing_final_bucket'})
        self.assertEqual(r['classification_mismatches'], [{'final_bucket': 'BSNL Media', 'value': 'SSA OFC', 'belongs_to': ['BSNL OFC'],
                                                           'rows': 1, 'example_rows': [7]}])
        warnings = {i['site_id']: i['code'] for i in r['all_issues'] if i['severity'] == 'warning' and i['code'].startswith('sub_bucket')}
        self.assertEqual(warnings, {'OD3': 'sub_bucket_not_approved', 'OD5': 'sub_bucket_missing', 'OD7': 'sub_bucket_not_approved'})
        self.assertEqual(r['classification'], {'approved': 4, 'final_only': 2, 'unapproved': 0, 'blank': 1})
        self.assertNotIn('bucket_spelling_approved', r['issue_counts'])


class ReportCommandTests(RcaTestCase):
    def test_the_command_reports_the_taxonomy_status_and_changes_nothing(self):
        record('Iaasp Others', 'IAASP LINK', site='OD1')
        record('BSNL Media', 'SSA OFC', site='OD2')
        record('Vsat', 'Vsat', site='OD3')
        before = list(RcaRecord.objects.order_by('id').values_list('final_bucket', 'bucket_2', 'final_bucket_key', 'bucket_2_key'))
        plan = {(i['final_bucket'], i['bucket_2']): i for i in rca_bucketization.plan()}
        self.assertEqual(plan[('Iaasp Others', 'IAASP LINK')]['status'], 'approved')
        self.assertEqual((plan[('BSNL Media', 'SSA OFC')]['status'], plan[('BSNL Media', 'SSA OFC')]['sub_bucket_belongs_to']), ('mismatch', 'BSNL OFC'))
        self.assertEqual(plan[('Vsat', 'Vsat')]['status'], 'unapproved')
        out = StringIO()
        call_command('rca_bucketization', stdout=out)
        self.assertIn('Report only: nothing was changed.', out.getvalue())
        self.assertEqual(list(RcaRecord.objects.order_by('id').values_list('final_bucket', 'bucket_2', 'final_bucket_key', 'bucket_2_key')), before)
        self.assertFalse(RcaEvent.objects.exists())


class DatabaseSummaryTests(RcaTestCase):
    def summary(self, **params):
        self.client.force_login(self.admin)
        return self.client.get(reverse('rca-summary'), params).json()

    def options(self):
        self.client.force_login(self.admin)
        return self.client.get(reverse('rca-options')).json()

    def test_summary_filters_and_buckets_come_from_the_stored_records(self):
        record('BSNL Media', 'Fluctuation', site='OD1', minutes=30)
        record('DMW', 'Fluctuation', site='OD2', minutes=20)
        record('HFCL', 'Fluctuation', site='OD3', minutes=10)
        record('Vsat', 'Vsat', site='LWEBH1', project='LWE', circle='BH', day=date(2026, 10, 22), minutes=5)
        data = self.summary()
        self.assertEqual((data['kpis']['records'], data['kpis']['affected_sites'], data['kpis']['outage_minutes']), (4, 4, 65))
        flux = sorted(i['label'] for i in data['bucket_2'] if i['bucket_2'] == 'Fluctuation')
        self.assertEqual(flux, ['Fluctuation · BSNL Media', 'Fluctuation · DMW', 'Fluctuation · HFCL'])  # never merged by name
        self.assertEqual(data['classification'], {'approved': 3, 'final_only': 0, 'unapproved': 1, 'blank': 0})
        vsat = next(i for i in data['final_buckets'] if i['label'] == 'Vsat')
        self.assertFalse(vsat['approved'])
        options = self.options()
        self.assertEqual((options['projects'], options['dates']), (['4G Saturation', 'LWE'], ['2026-10-21', '2026-10-22']))
        # The dropdowns offer exactly the taxonomy the validation uses: the 10 Final Buckets and their Sub Buckets.
        self.assertEqual(options['classification'], taxonomy.classification())
        self.assertEqual([o['label'] for o in options['final_buckets']], list(EXPECTED))
        subs = {o['label']: o['final_buckets'] for o in options['bucket_2'] if not o['unclassified']}
        self.assertEqual(subs, {c: [f for f, cs in EXPECTED.items() if c in cs] for cs in EXPECTED.values() for c in cs})
        self.assertNotIn('Vsat', [o['label'] for o in options['final_buckets']])  # a stored unapproved value is not offered
        dmw = next(i for i in data['bucket_2'] if i['final_bucket'] == 'DMW')
        self.assertEqual(self.summary(**dmw['filter'])['kpis']['records'], 1)  # a pair's filter selects exactly that pair
        self.assertEqual(self.summary(project='LWE')['kpis']['records'], 1)
        self.assertEqual(self.summary(circle='OD', date_from='2026-10-21', date_to='2026-10-21')['kpis']['records'], 3)

    def test_new_corrected_and_withdrawn_records_change_the_results(self):
        rec = record('BSNL OFC', 'SSA OFC', site='OD1')
        self.assertEqual(self.summary()['kpis']['records'], 1)
        record('TCS', 'RAC Card', site='RJ1', circle='RJ', day=date(2026, 10, 23))
        data = self.summary()
        self.assertEqual(data['kpis']['records'], 2)
        self.assertIn('2026-10-23', self.options()['dates'])
        self.assertIn('RJ', {c['circle'] for c in self.options()['circles']})
        rec.final_bucket, rec.final_bucket_key, rec.bucket_2, rec.bucket_2_key = 'BSNL Media', 'bsnl media', 'BSNL Link', 'bsnl link'
        rec.save()
        totals = {i['label']: i['records'] for i in self.summary()['final_buckets']}
        self.assertEqual((totals.get('BSNL OFC'), totals['BSNL Media']), (None, 1))
        rec.withdrawn_at = datetime(2026, 10, 24)
        rec.save()
        self.assertEqual(self.summary()['kpis']['records'], 1)
        self.assertNotIn('BSNL Media', {i['label'] for i in self.summary()['final_buckets']})

    def test_no_records_means_empty_results_never_sample_data(self):
        data = self.summary()
        self.assertEqual((data['kpis']['records'], data['final_buckets'], data['bucket_2'], data['circles'], data['dates']), (0, [], [], [], []))
        # The dropdowns still offer the approved taxonomy (it never comes from the records).
        self.assertEqual((self.options()['dates'], [o['label'] for o in self.options()['final_buckets']]), ([], list(EXPECTED)))

    def test_no_workbook_is_read(self):
        make_site('OD0001', technology='4G Saturation', circle='OD')  # the data layer has sites: it is the only source
        record('BSNL OFC', 'SSA OFC')
        with mock.patch('apps.dashboard.workbook.get_dataset', side_effect=AssertionError('a workbook was read')), \
                mock.patch('openpyxl.load_workbook', side_effect=AssertionError('a workbook was opened')):
            data = self.summary()
            self.assertEqual(data['kpis']['records'], 1)
            self.assertEqual(self.options()['total_records'], 1)
