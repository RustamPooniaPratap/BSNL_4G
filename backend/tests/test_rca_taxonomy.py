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
from apps.uptimedb.models import AppSetting
from tests.test_rca import RcaTestCase, workbook


def record(final, b2, *, day=date(2026, 10, 21), project='4G Saturation', circle='OD', site='OD0001', minutes=10.0, occurrence=1):
    return RcaRecord.objects.create(reporting_date=day, project=project, project_raw=project, circle=circle, circle_raw=circle, site_id=site,
                                    site_key=site, occurrence=occurrence, outage_minutes=minutes, final_bucket=final, final_bucket_key=text_key(final),
                                    bucket_2=b2, bucket_2_key=text_key(b2), rca_text='Cause', rca_key='cause', source='import')


class TaxonomyTests(RcaTestCase):
    def test_every_approved_pair_is_approved_and_kept_as_named(self):
        pairs = [(f, c) for f, children in taxonomy.APPROVED.items() for c in children]
        self.assertEqual(len(pairs), 10 + 10 + 4 + 1 + 10 + 9 + 5 + 10 + 7 + 9)
        for final, child in pairs:
            self.assertEqual(taxonomy.resolve(final, child), taxonomy.Resolution(final, child, 'approved'), (final, child))

    def test_spelling_only_differences_take_the_approved_name(self):
        self.assertEqual(taxonomy.resolve('Iaasp Others', 'IAASP LINK'), taxonomy.Resolution('IaaSP Others', 'IaaSP Link', 'approved'))
        self.assertEqual(taxonomy.resolve('BSNL OFC', 'BSNL-OFC'), taxonomy.Resolution('BSNL OFC', 'BSNL OFC', 'approved'))
        self.assertEqual(taxonomy.resolve('HFCl', 'hfcl  radio'), taxonomy.Resolution('HFCL', 'HFCL Radio', 'approved'))

    def test_invalid_pairs_typos_other_words_and_blanks_are_left_as_written(self):
        self.assertEqual(taxonomy.resolve('BSNL Media', 'SSA OFC').status, 'final_only')  # SSA OFC belongs to BSNL OFC
        self.assertEqual(taxonomy.resolve('Iaasp Others', 'Tech Deay'), taxonomy.Resolution('IaaSP Others', 'Tech Deay', 'final_only'))
        self.assertEqual(taxonomy.resolve('BSNL OFC', 'JCNL OFC').bucket_2, 'JCNL OFC')  # not "JCNL": other words
        self.assertEqual(taxonomy.resolve('Vsat', 'Vsat'), taxonomy.Resolution('Vsat', 'Vsat', 'unapproved'))
        self.assertEqual(taxonomy.resolve('-', ''), taxonomy.Resolution('-', '', 'blank'))
        self.assertEqual(taxonomy.resolve('TCS', '-').status, 'blank')
        self.assertNotEqual(taxonomy.resolve('', 'Fluctuation').final_bucket, 'Others')  # a blank is never Others

    def test_fluctuation_is_valid_only_under_its_three_parents(self):
        for parent in ('BSNL Media', 'DMW', 'HFCL'):
            self.assertEqual(taxonomy.resolve(parent, 'fluctuation'), taxonomy.Resolution(parent, 'Fluctuation', 'approved'))
        self.assertEqual(taxonomy.resolve('Others', 'Fluctuation').status, 'final_only')
        self.assertEqual(taxonomy.resolve('Others', 'Flacuation').bucket_2, 'Flacuation')

    def test_imports_apply_the_approved_spelling_and_flag_pairs_outside_it(self):
        day = datetime(2026, 10, 21)
        row = lambda site, final, b2: [day, '4G Satu', 'Odisha', site, 'S', '', '', 'Yes', 5, final, b2, 'cause']  # noqa: E731
        path = workbook(Path(self.tmp.name) / 'tax.xlsx', rows=[row('OD1', 'Iaasp Power', 'CCU FAULT'), row('OD2', 'DMW', 'Fluctuation'),
                                                                 row('OD3', 'Others', 'Flacuation'), row('OD4', 'Vsat', 'Vsat'), row('OD5', 'TCS', '-')])
        parsed = parse(path, 'tax.xlsx')
        stored = {r['site_id']: (r['final_bucket'], r['bucket_2']) for r in parsed['rows']}
        self.assertEqual(stored, {'OD1': ('IaaSP Power', 'CCU fault'), 'OD2': ('DMW', 'Fluctuation'), 'OD3': ('Others', 'Flacuation'),
                                  'OD4': ('Vsat', 'Vsat'), 'OD5': ('TCS', '-')})
        self.assertEqual(parsed['report']['classification'], {'approved': 2, 'final_only': 1, 'unapproved': 1, 'blank': 1})
        self.assertEqual(parsed['report']['valid_rows'], 5)  # flagged for review, never rejected
        self.assertEqual(parsed['report']['issue_counts']['bucket_pair_not_approved'], 2)


class CorrectionTests(RcaTestCase):
    def test_only_certain_corrections_are_written_with_history_and_a_rerun_changes_nothing(self):
        fixable = record('Iaasp Others', 'IAASP LINK', site='OD1')
        final_only = record('Iaasp Power', 'BB', site='OD2')
        ambiguous = record('Others', 'Flacuation', site='OD3')
        correct = record('BSNL OFC', 'SSA OFC', site='OD4')
        blank = record('-', '', site='OD5')
        untouched = {r.pk: (r.reporting_date, r.project, r.circle, r.site_id, r.outage_minutes, r.rca_text) for r in RcaRecord.objects.all()}
        plan = {(i['final_bucket'], i['bucket_2']): i for i in rca_bucketization.plan()}
        self.assertEqual((plan[('Others', 'Flacuation')]['status'], plan[('Others', 'Flacuation')]['correction']), ('final_only', False))
        result = rca_bucketization.apply()
        self.assertEqual(result, {'corrected': 2, 'approved_now': 1, 'already_correct': 1, 'unresolved': 3})
        for rec, expected in ((fixable, ('IaaSP Others', 'IaaSP Link')), (final_only, ('IaaSP Power', 'BB')), (ambiguous, ('Others', 'Flacuation')),
                              (correct, ('BSNL OFC', 'SSA OFC')), (blank, ('-', ''))):
            rec.refresh_from_db()
            self.assertEqual((rec.final_bucket, rec.bucket_2), expected)
        fixable.refresh_from_db()
        self.assertEqual((fixable.final_bucket_key, fixable.bucket_2_key), ('iaasp others', 'iaasp link'))
        event = RcaEvent.objects.get(record=fixable, action='classification_corrected')
        self.assertEqual(event.changes['final_bucket'], {'from': 'Iaasp Others', 'to': 'IaaSP Others'})
        self.assertEqual({r.pk: (r.reporting_date, r.project, r.circle, r.site_id, r.outage_minutes, r.rca_text) for r in RcaRecord.objects.all()}, untouched)
        self.assertEqual(RcaRecord.objects.count(), 5)  # nothing deleted
        again = rca_bucketization.apply()
        self.assertEqual((again.get('corrected', 0), RcaEvent.objects.filter(action='classification_corrected').count()), (0, 2))

    def test_the_command_is_a_dry_run_unless_told_to_apply(self):
        rec = record('HFCl', 'HFCL Radio')
        out = StringIO()
        call_command('rca_bucketization', stdout=out)
        rec.refresh_from_db()
        self.assertEqual(rec.final_bucket, 'HFCl')
        self.assertIn('Dry run', out.getvalue())
        call_command('rca_bucketization', '--apply', stdout=StringIO())
        rec.refresh_from_db()
        self.assertEqual(rec.final_bucket, 'HFCL')


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
        self.assertEqual(options['classification'], taxonomy.classification())
        self.assertEqual([o['label'] for o in options['final_buckets']][-1:], ['Vsat'])  # unapproved after the approved ones
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
        self.assertEqual((self.options()['dates'], self.options()['final_buckets']), ([], []))

    def test_in_postgresql_mode_no_workbook_is_read(self):
        AppSetting.objects.update_or_create(key='dashboard_data_source', defaults={'value': 'database'})
        record('BSNL OFC', 'SSA OFC')
        with mock.patch('apps.dashboard.workbook.get_dataset', side_effect=AssertionError('a workbook was read')), \
                mock.patch('openpyxl.load_workbook', side_effect=AssertionError('a workbook was opened')):
            data = self.summary()
            self.assertEqual(data['kpis']['records'], 1)
            self.assertEqual(self.options()['total_records'], 1)
