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


# The approved hierarchy of RCA_buckets.xlsx (12 Nov 2026), written out independently of taxonomy.py so a change there is caught.
EXPECTED = {
    'IaasP Power': ['CCU fault', 'EB power cut', 'Solar Panel fault', 'RM fail', 'MPPT Issue', 'Contactor faulty', 'Power cable faulty',
                    'LVD issue', 'Backplane faulty', 'High V & Low V', 'SMPS Issue', 'Others'],
    'IaasP Others': ['Shadow issue', 'EB Cable fault', 'EB tx. Faulty', 'EB Bill not paid', 'IaasP Theft', 'CT payment Issue', 'Owner issue',
                     'Natural Clamity', 'Tech Delay', 'IaasP Link', 'Meter Faulty'],
    'IaasP Battery': ['Battery issue', 'BB Theft', 'Low back Up', 'BMS faulty'],
    'IaasP OFC': ['Incremental Fibre'],
    'BSNL OFC': ['SSA OFC', 'BSNL OFC', 'ETR OFC', 'BBNL OFC', 'WTR OFC', 'NTR', 'CNTX', 'JCNL', 'Maha IT', 'Pace OFC'],
    'BSNL Media': ['Nokia mini link', 'NEC Mini link', 'CPAN issue', 'Maan Media issue', 'BSNL Link', 'Vsat Media', 'BSNL Hub', 'BSNL Others',
                   'Fluctuation'],
    'Others': ['4G Sat. link site', 'IP site link', 'Others site link', 'ATC site link', 'Non IaasP Theft', 'Fire Incident'],
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
        self.assertEqual(taxonomy.resolve('IaasP Others', 'Natural Clamity').status, 'approved')
        self.assertEqual(taxonomy.resolve('DMW', 'Ceragon Radio').status, 'final_only')  # a warning, not corrected
        self.assertEqual(taxonomy.resolve('IaasP Others', 'Natural Calamity').status, 'final_only')

    def test_ceragoan_radio_and_natural_clamity_upload_exactly_as_approved_with_no_warning(self):
        day = datetime(2026, 10, 21)
        row = lambda site, final, b2: [day, '4G Satu', 'Odisha', site, 'S', '', '', 'Yes', 5, final, b2, 'cause']  # noqa: E731
        path = workbook(Path(self.tmp.name) / 'approved.xlsx', rows=[
            row('OD1', 'DMW', 'Ceragoan Radio'), row('OD2', 'IaasP Others', 'Natural Clamity'),
            row('OD3', ' DMW ', ' Ceragoan Radio '), row('OD4', 'IaasP Others', '  Natural Clamity')])  # surrounding spaces
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
        path = workbook(Path(self.tmp.name) / 'other.xlsx', rows=[row('OD1', 'DMW', 'Ceragon Radio'), row('OD2', 'IaasP Others', 'Natural Calamity')])
        result = parse(path, 'other.xlsx')
        warnings = [i for i in result['report']['all_issues'] if i['severity'] == 'warning']
        self.assertEqual([i['code'] for i in warnings], ['sub_bucket_not_approved', 'sub_bucket_not_approved'])
        self.assertTrue(all('not an approved Sub Bucket' in i['message'] and 'spelling' not in i['message'].lower() for i in warnings))
        self.assertEqual({r['bucket_2'] for r in result['rows']}, {'Ceragon Radio', 'Natural Calamity'})  # kept as uploaded, not corrected

    def test_others_under_iaasp_power_is_approved(self):
        self.assertEqual(taxonomy.resolve('IaasP Power', 'Others'), taxonomy.Resolution('IaasP Power', 'Others', 'approved'))

    def test_an_approved_sub_bucket_under_another_final_bucket_is_a_classification_mismatch(self):
        self.assertEqual(taxonomy.resolve('BSNL Media', 'SSA OFC'), taxonomy.Resolution('BSNL Media', None, 'mismatch', ('BSNL OFC',)))
        self.assertEqual(taxonomy.resolve('IaasP Power', 'EB Cable fault').other_final_buckets, ('IaasP Others',))
        self.assertEqual(taxonomy.resolve('Others', 'Fluctuation').other_final_buckets, ('BSNL Media', 'DMW', 'HFCL'))
        for parent in ('BSNL Media', 'DMW', 'HFCL'):
            self.assertEqual(taxonomy.resolve(parent, 'Fluctuation').status, 'approved')

    def test_matching_ignores_surrounding_spaces_and_case_only_and_never_renames(self):
        self.assertEqual(taxonomy.resolve('  iaasp power ', ' ccu FAULT '), taxonomy.Resolution('IaasP Power', 'CCU fault', 'approved'))
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
            row('OD4', 'Vsat', 'Vsat'), row('OD5', 'TCS', '-'), row('OD6', 'BSNL Media', 'SSA OFC'), row('OD7', 'IaasP Power', 'Others'),
            row('OD8', 'DMW', 'Ceragoan Radio'), row('OD9', 'IaasP Others', 'Natural Clamity'), row('OD10', '', 'BBU')])
        report = parse(path, 'tax.xlsx')
        parsed, r = report['rows'], report['report']
        stored = {x['site_id']: (x['final_bucket'], x['bucket_2']) for x in parsed}
        self.assertEqual(stored, {'OD1': ('Iaasp Power', 'CCU FAULT'), 'OD2': ('DMW', 'Fluctuation'), 'OD3': ('Others', 'Flacuation'),
                                  'OD5': ('TCS', '-'), 'OD7': ('IaasP Power', 'Others'), 'OD8': ('DMW', 'Ceragoan Radio'),
                                  'OD9': ('IaasP Others', 'Natural Clamity')})  # as uploaded: nothing renamed
        self.assertEqual((r['valid_rows'], r['rejected_rows']), (7, 3))
        errors = {i['site_id']: i['code'] for i in r['all_issues'] if i['severity'] == 'error'}
        self.assertEqual(errors, {'OD4': 'final_bucket_not_approved', 'OD6': 'sub_bucket_classification_mismatch', 'OD10': 'missing_final_bucket'})
        self.assertEqual(r['classification_mismatches'], [{'final_bucket': 'BSNL Media', 'value': 'SSA OFC', 'belongs_to': ['BSNL OFC'],
                                                           'rows': 1, 'example_rows': [7]}])
        warnings = {i['site_id']: i['code'] for i in r['all_issues'] if i['severity'] == 'warning' and i['code'].startswith('sub_bucket')}
        self.assertEqual(warnings, {'OD3': 'sub_bucket_not_approved', 'OD5': 'sub_bucket_missing'})  # IaasP Power / Others is approved
        self.assertEqual(r['classification'], {'approved': 5, 'final_only': 1, 'unapproved': 0, 'blank': 1})
        self.assertNotIn('bucket_spelling_approved', r['issue_counts'])


class MasterCorrectionTests(RcaTestCase):
    """RCA_buckets.xlsx correction (12 Nov 2026): the 15 required checks."""

    def upload(self, name, rows):
        day = datetime(2026, 10, 21)
        row = lambda site, final, b2: [day, '4G Satu', 'Odisha', site, 'S', '', '', 'Yes', 5, final, b2, 'cause']  # noqa: E731
        return parse(workbook(Path(self.tmp.name) / name, rows=[row(*r) for r in rows]), name)

    def test_01_all_ten_final_buckets(self):
        self.assertEqual(list(taxonomy.APPROVED), ['IaasP Power', 'IaasP Others', 'IaasP Battery', 'IaasP OFC', 'BSNL OFC', 'BSNL Media',
                                                   'Others', 'TCS', 'DMW', 'HFCL'])

    def test_02_every_sub_bucket_belongs_to_its_final_bucket_only(self):
        for final, children in EXPECTED.items():
            for child in children:
                owners = tuple(f for f, c in EXPECTED.items() if child in c)
                self.assertEqual(tuple(taxonomy.finals_of_sub_bucket(child)), owners, child)
                for other in EXPECTED:
                    if other not in owners:
                        self.assertNotEqual(taxonomy.resolve(other, child).status, 'approved', (other, child))

    def test_03_no_obsolete_configuration_remains(self):
        self.assertEqual(sum(len(c) for c in taxonomy.APPROVED.values()), 79)
        self.assertNotIn('IaaSP Power', taxonomy.APPROVED)  # the old spelling is no longer a label
        from apps.rca.breakdown import COLUMNS
        self.assertEqual([label for label, _ in COLUMNS], list(EXPECTED))

    def test_04_05_06_power_others_smps_and_meter_faulty_pass(self):
        result = self.upload('pass.xlsx', [('OD1', 'IaasP Power', 'Others'), ('OD2', 'IaasP Power', 'SMPS Issue'),
                                           ('OD3', 'IaasP Others', 'Meter Faulty')])
        self.assertEqual(result['report']['classification'], {'approved': 3, 'final_only': 0, 'unapproved': 0, 'blank': 0})
        self.assertEqual(result['report']['sub_bucket_warnings']['rows'], 0)

    def test_07_nec_minilink_is_a_formatting_variant(self):
        self.assertEqual(taxonomy.resolve('BSNL Media', 'NEC minilink'), taxonomy.Resolution('BSNL Media', 'NEC Mini link', 'approved'))
        self.assertEqual(taxonomy.match_key(' NEC  Mini link '), taxonomy.match_key('nec minilink'))
        self.assertNotEqual(taxonomy.match_key('NEC-Mini link'), taxonomy.match_key('NEC Mini link'))  # no fuzzy matching

    def test_08_final_bucket_case_variants_are_normalised(self):
        for raw, canonical in [('IaaSP Power', 'IaasP Power'), ('Iaasp Power', 'IaasP Power'), ('IaaSP Others', 'IaasP Others'),
                               ('IaaSP Battery', 'IaasP Battery'), ('Iaasp OFC', 'IaasP OFC'), ('HFCl', 'HFCL')]:
            self.assertEqual(taxonomy.resolve(raw, '').final_bucket, canonical, raw)

    def test_09_10_contractor_faulty_remains_a_warning(self):
        # Low V is an approved alias of High V & Low V (12 Nov 2026): HighLowVoltageAliasTests.
        result = self.upload('warn.xlsx', [('OD2', 'IaasP Power', 'Contractor faulty')])
        report = result['report']
        self.assertEqual((report['valid_rows'], report['rejected_rows']), (1, 0))
        codes = [i['code'] for i in report['all_issues'] if i['severity'] == 'warning' and i['code'].startswith('sub_bucket')]
        self.assertEqual(codes, ['sub_bucket_not_approved'])
        self.assertEqual({r['bucket_2'] for r in result['rows']}, {'Contractor faulty'})  # never auto-mapped

    def test_11_sub_bucket_options_carry_their_final_buckets(self):
        self.client.force_login(self.admin)
        options = self.client.get(reverse('rca-options')).json()
        self.assertEqual(options['classification'], [{'final_bucket': f, 'bucket_2': c} for f, c in EXPECTED.items()])
        by_label = {o['label']: o for o in options['bucket_2'] if not o.get('unclassified')}
        self.assertEqual(by_label['Meter Faulty']['final_buckets'], ['IaasP Others'])
        self.assertEqual(by_label['Fluctuation']['final_buckets'], ['BSNL Media', 'DMW', 'HFCL'])

    def test_12_invalid_combinations_are_rejected_or_warned(self):
        result = self.upload('bad.xlsx', [('OD1', 'BSNL Media', 'SSA OFC'), ('OD2', 'Vsat', 'Vsat'), ('OD3', 'TCS', 'Contractor faulty')])
        issues = {i['site_id']: (i['severity'], i['code']) for i in result['report']['all_issues']
                  if i['code'] not in ('project_label_to_confirm', 'whitespace_trimmed')}
        self.assertEqual(issues, {'OD1': ('error', 'sub_bucket_classification_mismatch'), 'OD2': ('error', 'final_bucket_not_approved'),
                                  'OD3': ('warning', 'sub_bucket_not_approved')})

    def test_13_filters_and_reports_use_canonical_labels(self):
        record('IaaSP Power', 'CCU fault', site='OD1', minutes=10)
        record('Iaasp Power', 'CCU FAULT', site='OD2', minutes=5)
        record('HFCl', 'HFCL Radio', site='OD3', minutes=1)
        self.client.force_login(self.admin)
        options = self.client.get(reverse('rca-options')).json()
        self.assertEqual([o['label'] for o in options['final_buckets'] if o.get('approved')], list(EXPECTED))
        summary = self.client.get(reverse('rca-summary')).json()
        finals = {i['label']: i['records'] for i in summary['final_buckets'] if i.get('approved')}
        self.assertEqual((finals['IaasP Power'], finals['HFCL']), (2, 1))
        listed = self.client.get(reverse('rca-records'), {'final_bucket': 'iaasp power'}).json()
        self.assertEqual(listed['count'], 2)

    def test_14_15_original_values_and_history_stay_intact(self):
        record('IaaSP Power', 'Low V', site='OD1', minutes=12.5)
        record('HFCl', 'HFCL Radio', site='OD2', minutes=3.0)
        fields = ('final_bucket', 'bucket_2', 'final_bucket_key', 'bucket_2_key', 'outage_minutes', 'reporting_date')
        before = list(RcaRecord.objects.order_by('id').values_list(*fields))
        self.client.force_login(self.admin)
        self.client.get(reverse('rca-summary'))
        self.client.get(reverse('rca-options'))
        call_command('rca_bucketization', stdout=StringIO())
        after = list(RcaRecord.objects.order_by('id').values_list(*fields))
        self.assertEqual(after, before)
        self.assertEqual(after[0][:2], ('IaaSP Power', 'Low V'))  # the uploaded text, kept for audit
        self.assertEqual(RcaRecord.objects.count(), 2)



class FluctuationAliasTests(RcaTestCase):
    """Approved aliases (12 Nov 2026): BSNL Media / Flactuation and HFCL / Flactuation are BSNL Media / HFCL Fluctuation."""

    def upload(self, name, rows):
        day = datetime(2026, 10, 21)
        row = lambda site, final, b2: [day, '4G Satu', 'Odisha', site, 'S', '', '', 'Yes', 5, final, b2, 'cause']  # noqa: E731
        return parse(workbook(Path(self.tmp.name) / name, rows=[row(*r) for r in rows]), name)

    def test_both_aliases_resolve_to_their_canonical_pairs(self):
        self.assertEqual(taxonomy.resolve('BSNL Media', 'Flactuation'), taxonomy.Resolution('BSNL Media', 'Fluctuation', 'approved'))
        self.assertEqual(taxonomy.resolve('HFCL', 'Flactuation'), taxonomy.Resolution('HFCL', 'Fluctuation', 'approved'))
        self.assertEqual(taxonomy.resolve('hfcl', ' FLACTUATION ').bucket_2, 'Fluctuation')  # case and spaces only

    def test_aliases_are_scoped_to_their_final_bucket_and_not_fuzzy(self):
        self.assertEqual(taxonomy.resolve('DMW', 'Flactuation').status, 'final_only')  # not approved under DMW
        self.assertEqual(taxonomy.finals_of_sub_bucket('Flactuation'), ())
        self.assertEqual(taxonomy.resolve('BSNL Media', 'Flactuations').status, 'final_only')
        self.assertEqual(taxonomy.resolve('BSNL Media', 'Fluctation').status, 'final_only')
        self.assertEqual({f: list(c) for f, c in taxonomy.APPROVED.items()}, EXPECTED)  # the taxonomy itself is unchanged

    def test_alias_rows_pass_upload_validation_and_keep_the_source_label(self):
        result = self.upload('alias.xlsx', [('OD1', 'BSNL Media', 'Flactuation'), ('OD2', 'HFCL', 'Flactuation'), ('OD3', 'DMW', 'Flactuation')])
        report = result['report']
        self.assertEqual(report['classification'], {'approved': 2, 'final_only': 1, 'unapproved': 0, 'blank': 0})
        warnings = {i['site_id'] for i in report['all_issues'] if i['code'] == 'sub_bucket_not_approved'}
        self.assertEqual(warnings, {'OD3'})
        self.assertEqual({r['bucket_2'] for r in result['rows']}, {'Flactuation'})  # stored as uploaded, for audit

    def test_filters_and_summaries_use_canonical_fluctuation(self):
        record('BSNL Media', 'Fluctuation', site='OD1', minutes=10)
        record('BSNL Media', 'Flactuation', site='OD2', minutes=20)
        record('HFCL', 'Flactuation', site='OD3', minutes=5)
        record('DMW', 'Flactuation', site='OD4', minutes=1)
        before = list(RcaRecord.objects.order_by('id').values_list('final_bucket', 'bucket_2', 'bucket_2_key'))
        self.client.force_login(self.admin)
        summary = self.client.get(reverse('rca-summary')).json()
        pairs = {(i['final_bucket'], i['bucket_2']): i for i in summary['bucket_2'] if i['approved']}
        self.assertEqual(pairs[('BSNL Media', 'Fluctuation')]['records'], 2)
        self.assertEqual(pairs[('BSNL Media', 'Fluctuation')]['variants'], ['Flactuation', 'Fluctuation'])
        self.assertEqual(pairs[('HFCL', 'Fluctuation')]['records'], 1)
        self.assertNotIn(('DMW', 'Fluctuation'), pairs)  # DMW / Flactuation stays unapproved
        listed = self.client.get(reverse('rca-records'), {'bucket_2': 'fluctuation'}).json()
        self.assertEqual(sorted(r['site_id'] for r in listed['results']), ['OD1', 'OD2', 'OD3'])
        media = self.client.get(reverse('rca-records'), {'final_bucket': 'bsnl media', 'bucket_2': 'fluctuation'}).json()
        self.assertEqual(sorted(r['site_id'] for r in media['results']), ['OD1', 'OD2'])
        self.assertEqual(list(RcaRecord.objects.order_by('id').values_list('final_bucket', 'bucket_2', 'bucket_2_key')), before)


class OtherAliasTests(RcaTestCase):
    """Approved alias (12 Nov 2026): IaasP Power / Other is IaasP Power / Others, under IaasP Power only."""

    def test_other_resolves_to_others_under_iaasp_power_only(self):
        self.assertEqual(taxonomy.resolve('IaasP Power', 'Other'), taxonomy.Resolution('IaasP Power', 'Others', 'approved'))
        self.assertEqual(taxonomy.resolve('IaaSP Power', ' other ').bucket_2, 'Others')
        for final in EXPECTED:
            if final != 'IaasP Power':
                self.assertNotEqual(taxonomy.resolve(final, 'Other').status, 'approved', final)
        self.assertEqual(taxonomy.resolve('IaasP Power', 'Otherss').status, 'final_only')  # no fuzzy matching

    def test_other_records_group_under_others_and_keep_the_source_value(self):
        record('IaasP Power', 'Others', site='OD1', minutes=10)
        record('IaasP Power', 'Other', site='OD2', minutes=20)
        record('TCS', 'Other', site='OD3', minutes=5)
        before = list(RcaRecord.objects.order_by('id').values_list('final_bucket', 'bucket_2', 'bucket_2_key'))
        self.client.force_login(self.admin)
        summary = self.client.get(reverse('rca-summary')).json()
        pairs = {(i['final_bucket'], i['bucket_2']): i for i in summary['bucket_2']}
        self.assertEqual((pairs[('IaasP Power', 'Others')]['records'], pairs[('IaasP Power', 'Others')]['variants']), (2, ['Other', 'Others']))
        self.assertFalse(pairs[('TCS', 'Other')]['approved'])
        listed = self.client.get(reverse('rca-records'), {'final_bucket': 'iaasp power', 'bucket_2': 'others'}).json()
        self.assertEqual(sorted(r['site_id'] for r in listed['results']), ['OD1', 'OD2'])
        self.assertEqual(sorted(r['bucket_2'] for r in listed['results']), ['Other', 'Others'])  # as uploaded
        self.assertEqual(list(RcaRecord.objects.order_by('id').values_list('final_bucket', 'bucket_2', 'bucket_2_key')), before)


class HighLowVoltageAliasTests(RcaTestCase):
    """High V, Low V and High V & Low V are one Sub Bucket of IaasP Power: High V & Low V is canonical, the other two are
    approved aliases under IaasP Power only."""

    def upload(self, name, rows):
        day = datetime(2026, 10, 21)
        row = lambda site, final, b2: [day, '4G Satu', 'Odisha', site, 'S', '', '', 'Yes', 5, final, b2, 'cause']  # noqa: E731
        return parse(workbook(Path(self.tmp.name) / name, rows=[row(*r) for r in rows]), name)

    def test_all_three_labels_resolve_to_the_canonical_pair(self):
        canonical = taxonomy.Resolution('IaasP Power', 'High V & Low V', 'approved')
        for value in ('High V & Low V', 'High V', 'Low V', ' low v ', 'HIGH V'):
            self.assertEqual(taxonomy.resolve('IaasP Power', value), canonical, value)
        self.assertEqual(taxonomy.resolve('IaaSP Power', 'Low V'), canonical)  # Final Bucket spelling variant

    def test_high_v_and_low_v_are_not_approved_under_other_final_buckets_and_not_fuzzy(self):
        for final in EXPECTED:
            if final != 'IaasP Power':
                for value in ('High V', 'Low V'):
                    self.assertNotEqual(taxonomy.resolve(final, value).status, 'approved', (final, value))
        self.assertEqual(taxonomy.finals_of_sub_bucket('Low V'), ())
        self.assertEqual(taxonomy.resolve('IaasP Power', 'Low Volt').status, 'final_only')
        self.assertEqual(taxonomy.resolve('IaasP Power', 'High V/Low V').status, 'final_only')

    def test_all_three_pass_upload_validation_and_keep_the_uploaded_label(self):
        result = self.upload('hv.xlsx', [('OD1', 'IaasP Power', 'High V'), ('OD2', 'IaasP Power', 'Low V'),
                                         ('OD3', 'IaasP Power', 'High V & Low V'), ('OD4', 'TCS', 'Low V')])
        report = result['report']
        self.assertEqual((report['valid_rows'], report['rejected_rows']), (4, 0))
        self.assertEqual(report['classification'], {'approved': 3, 'final_only': 1, 'unapproved': 0, 'blank': 0})
        self.assertEqual({i['site_id'] for i in report['all_issues'] if i['code'] == 'sub_bucket_not_approved'}, {'OD4'})
        self.assertEqual({r['site_id']: r['bucket_2'] for r in result['rows']},
                         {'OD1': 'High V', 'OD2': 'Low V', 'OD3': 'High V & Low V', 'OD4': 'Low V'})  # as uploaded

    def test_options_offer_only_the_canonical_label(self):
        self.client.force_login(self.admin)
        options = self.client.get(reverse('rca-options')).json()
        power = next(c for c in options['classification'] if c['final_bucket'] == 'IaasP Power')['bucket_2']
        self.assertIn('High V & Low V', power)
        self.assertFalse({'High V', 'Low V'} & set(power))
        labels = {o['label'] for o in options['bucket_2']}
        self.assertIn('High V & Low V', labels)
        self.assertFalse({'High V', 'Low V'} & labels)

    def test_filters_and_summaries_group_all_three_and_records_stay_unchanged(self):
        record('IaasP Power', 'High V & Low V', site='OD1', minutes=10)
        record('IaasP Power', 'High V', site='OD2', minutes=20)
        record('IaasP Power', 'Low V', site='OD3', minutes=30)
        record('TCS', 'Low V', site='OD4', minutes=1)
        fields = ('final_bucket', 'bucket_2', 'final_bucket_key', 'bucket_2_key', 'outage_minutes')
        before = list(RcaRecord.objects.order_by('id').values_list(*fields))
        self.client.force_login(self.admin)
        summary = self.client.get(reverse('rca-summary')).json()
        pairs = {(i['final_bucket'], i['bucket_2']): i for i in summary['bucket_2']}
        hv = pairs[('IaasP Power', 'High V & Low V')]
        self.assertEqual((hv['records'], hv['outage_minutes'], hv['approved']), (3, 60.0, True))
        self.assertEqual(hv['variants'], ['High V', 'High V & Low V', 'Low V'])
        self.assertNotIn(('IaasP Power', 'Low V'), pairs)
        self.assertNotIn(('IaasP Power', 'High V'), pairs)
        self.assertFalse(pairs[('TCS', 'Low V')]['approved'])
        listed = self.client.get(reverse('rca-records'), {'bucket_2': 'high v & low v'}).json()
        self.assertEqual(sorted(r['site_id'] for r in listed['results']), ['OD1', 'OD2', 'OD3'])  # not TCS / Low V
        self.assertEqual(sorted(r['bucket_2'] for r in listed['results']), ['High V', 'High V & Low V', 'Low V'])
        self.assertEqual(list(RcaRecord.objects.order_by('id').values_list(*fields)), before)


class DailyAvailabilityCeilingTests(RcaTestCase):
    """The RCA exception (no upper outage limit) does not reach daily 4G / LWE availability: 0-1,440 minutes there."""

    def test_daily_outage_above_a_day_is_still_out_of_range(self):
        from apps.sitedata import rules
        self.assertEqual(rules.check_outage('1440').value, 1440.0)
        self.assertEqual(rules.check_outage('1441').code, 'outage_out_of_range')
        self.assertEqual(rules.check_outage('-1').code, 'outage_out_of_range')
        with self.assertRaises(ValueError):
            rules.availability_from_outage(1500)


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
