"""RCA upload workflow: the NOC Lead's workbook upload, duplicates and corrections, received versus pending coverage,
partial and final consolidated reports, and who may do what.

Synthetic workbooks and Up-Time sites only; files are written to a temporary DATA_DIR.
"""
import io
from datetime import datetime
from pathlib import Path

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import override_settings
from django.urls import reverse
from openpyxl import load_workbook

from apps.rca.models import RcaEvent, RcaImportBatch, RcaRecord, RcaReport, RcaReportingCycle
from apps.accounts.roles import set_rca_consolidated
from tests.auth_helpers import portal_user
from tests.test_rca import RcaTestCase, uptime_sites, workbook

DAY = datetime(2026, 10, 21)
OD = [
    [DAY, '4G Satu', 'Odisha', 'OD0001', 'Bravo', 'KORAPUT', 'KORAPUT', 'Yes', 90, 'IaasP OFC', 'BSNL MEDIA', 'Media Fluctuation'],
    [DAY, '4G Satu', 'Odisha', 'OD0002', 'Echo', 'KORAPUT', 'KORAPUT', 'Yes', 30, 'Others', '', ''],
]
RJ = [[DAY, '4G Satu', 'Rajasthan', 'RJ0001', 'Charlie', 'Jaisalmer', 'JODHPUR', 'Yes', 5, 'BSNL OFC', '', '']]
BH = [[DAY, 'LWE', 'Bihar', 'LWEBH0063', 'Haibatpur', 'Gaya', 'Gaya', 'Yes', 20.6, 'BSNL Media', 'BSNL Media', 'Media Flacuatation']]
LWE_OD = [[DAY, 'LWE', 'Odisha', 'LWEOD0001', 'Lima', '', '', 'Yes', 4, 'BSNL OFC', 'Fiber', 'Cut']]
WORKBOOK = OD + RJ + BH
DETAILS = {'upload_type': 'consolidated', 'report_name': 'October 2026 RCA Report', 'period_start': '2026-10-21', 'period_end': '', 'project_scope': 'both', 'remarks': ''}
SCOPE = [['4G Saturation', 'OD'], ['4G Saturation', 'RJ'], ['LWE', 'BH'], ['LWE', 'OD']]


@override_settings()
class UploadTestCase(RcaTestCase):
    def setUp(self):
        super().setUp()
        self.noc = portal_user('noc-lead', 'noc_lead')
        self.other_noc = portal_user('noc-lead-2', 'noc_lead')
        for user in (self.noc, self.other_noc):  # consolidated uploads need the group; being a NOC Lead is not enough
            set_rca_consolidated(user, True)
        uptime_sites(('4G Saturation', 'OD', 'OD0001'), ('4G Saturation', 'OD', 'OD0002'), ('4G Saturation', 'OD', 'OD0003'),
                     ('4G Saturation', 'RJ', 'RJ0001'), ('LWE', 'BH', 'LWEBH0063'), ('LWE', 'OD', 'LWEOD0001'))
        self.client.force_login(self.noc)

    def upload(self, rows, name='rca.xlsx', **details):
        path = workbook(Path(self.tmp.name) / name, rows=rows)
        return self.client.post(reverse('rca-import-preview'), {'file': SimpleUploadedFile(name, path.read_bytes()), **{**DETAILS, **details}})

    def commit(self, batch_id, **choices):
        return self.client.post(reverse('rca-import-commit', args=[batch_id]), choices, content_type='application/json')

    def imported(self, rows, name='rca.xlsx', choices=None, **details) -> dict:
        preview = self.upload(rows, name, **details)
        self.assertEqual(preview.status_code, 201, preview.content)
        self.assertEqual(preview.json()['status'], 'previewed', preview.json().get('error'))
        response = self.commit(preview.json()['id'], **(choices or {}))
        self.assertEqual(response.status_code, 200, response.content)
        return response.json()

    def period(self) -> RcaReportingCycle:
        return RcaReportingCycle.objects.get()

    def as_admin(self, method, name, args=(), data=None, **kwargs):
        self.client.force_login(self.admin)
        response = getattr(self.client, method)(reverse(name, args=args), data or {}, content_type='application/json', **kwargs)
        self.client.force_login(self.noc)
        return response

    def detail(self) -> dict:
        return self.as_admin('get', 'rca-cycle', [self.period().pk]).json()

    def sheets(self, response):
        content = b''.join(response.streaming_content) if response.streaming else response.content
        # Release the stored file (Windows cannot delete an open file) without firing request_finished, which would close
        # the database connection inside the test transaction on PostgreSQL (as Django's own test client avoids).
        from django.core.signals import request_finished
        from django.db import close_old_connections
        request_finished.disconnect(close_old_connections)
        try:
            response.close()
        finally:
            request_finished.connect(close_old_connections)
        return load_workbook(io.BytesIO(content))


class NocLeadUploadTests(UploadTestCase):
    def test_the_noc_lead_uploads_previews_confirms_and_sees_the_summary_of_their_own_upload(self):
        preview = self.upload(WORKBOOK, 'Oct_RCA.xlsx', remarks='First submission').json()
        self.assertEqual((preview['status'], preview['imported_by'], preview['report_name'], preview['remarks']),
                         ('previewed', 'noc-lead', 'October 2026 RCA Report', 'First submission'))
        self.assertEqual(RcaRecord.objects.count(), 0)  # nothing is written before the confirmation
        self.assertEqual(preview['units'], [['4G Saturation', 'OD'], ['4G Saturation', 'RJ'], ['LWE', 'BH']])
        # No Other Media rows (not an approved Final Bucket); OD0002 and RJ0001 have blank Bucket - 2 and RCA.
        self.assertEqual((preview['report']['rca_not_applicable_rows'], preview['report']['missing_rca_rows']), (0, 2))
        result = self.commit(preview['id']).json()
        c = result['counts']
        self.assertEqual((c['total'], c['inserted'], c['updated'], c['skipped'], c['rejected']), (4, 4, 0, 0, 0))
        self.assertEqual((result['status'], result['status_label']), ('committed', 'Imported'))
        self.assertEqual(result['report']['circles'], {'4G Saturation|OD': 2, '4G Saturation|RJ': 1, 'LWE|BH': 1})
        self.assertAlmostEqual(result['report']['outage_minutes'], 145.6)
        self.assertTrue(Path(RcaImportBatch.objects.get(pk=result['id']).stored_path).is_file())  # original kept for audit
        # The first accepted upload created the period; no expected scope is configured yet.
        period = self.period()
        self.assertEqual((period.name, period.reporting_date.isoformat(), period.end.isoformat()), ('October 2026 RCA Report', '2026-10-21', '2026-10-21'))
        # The NOC Lead sees their own upload and its consolidated workbook.
        mine = self.client.get(reverse('rca-imports')).json()['imports']
        self.assertEqual([b['id'] for b in mine], [result['id']])
        book = self.sheets(self.client.get(reverse('rca-import-workbook', args=[result['id']])))
        self.assertEqual(book.sheetnames, ['Report', 'Coverage', 'Uploads', 'Summary', 'RCA Master'])
        self.assertEqual(book['Report']['A2'].value, 'PARTIAL — EXPECTED SCOPE NOT CONFIGURED')
        # The register shows the accepted records to every portal user.
        self.client.force_login(self.ci)
        self.assertEqual(self.client.get(reverse('rca-records')).json()['count'], 4)

    def test_rejected_rows_are_reported_and_valid_rows_are_imported_only_after_explicit_confirmation(self):
        self.imported(OD)
        rows = [
            [datetime(2026, 10, 22), '4G Satu', 'Rajasthan', 'RJ0001', 'C', '', '', 'Yes', 5, 'BSNL OFC', 'x', 'y'],  # after the reporting date
            [DAY, 'LWE', 'Bihar', 'LWEBH0063', 'H', '', '', 'Yes', 5, 'BSNL OFC', 'x', 'y'],  # outside the project scope
            [DAY, '4G Satu', 'Odisha', 'OD9999', 'Nowhere', '', '', 'Yes', 5, 'BSNL OFC', 'x', 'y'],  # not an Up-Time site
            [DAY, '4G Satu', 'Rajasthan', 'RJ0001', 'C', '', '', 'Yes', 'abc', 'BSNL OFC', 'x', 'y'],  # not a number
            [DAY, '4G Satu', 'Odisha', 'OD0003', 'Fox', '', '', 'Yes', 7, 'BSNL OFC', 'x', 'y'],  # valid
        ]
        preview = self.upload(OD + rows, 'mixed.xlsx', project_scope='4G Saturation').json()
        self.assertEqual((preview['status'], preview['counts']['valid'], preview['counts']['rejected']), ('previewed', 3, 4))
        csv = self.client.get(reverse('rca-import-issues', args=[preview['id']])).content.decode('utf-8-sig')
        for code in ('after_reporting_period', 'outside_project_scope', 'unknown_site', 'invalid_outage'):
            self.assertIn(code, csv)
        refused = self.commit(preview['id'])
        self.assertEqual(refused.status_code, 409)
        self.assertIn('Confirm importing the 3 valid rows', refused.json()['error'])
        self.assertEqual(RcaRecord.objects.count(), 2)  # accepted data untouched
        result = self.commit(preview['id'], accept_rejected=True).json()
        self.assertEqual((result['counts']['inserted'], result['counts']['skipped'], result['counts']['rejected'], result['status_label']),
                         (1, 2, 4, 'Imported with rejected rows'))

    def test_an_unreadable_or_entirely_invalid_workbook_changes_nothing(self):
        self.imported(OD)
        path = workbook(Path(self.tmp.name) / 'bad.xlsx', rows=OD, headers=['Date', 'Project'])
        response = self.client.post(reverse('rca-import-preview'), {'file': SimpleUploadedFile('bad.xlsx', path.read_bytes()), **DETAILS})
        self.assertEqual(response.status_code, 400)
        failed = RcaImportBatch.objects.get(original_filename='bad.xlsx')
        self.assertEqual((failed.status, failed.imported_by, failed.report_name), ('failed', self.noc, 'October 2026 RCA Report'))
        none_valid = self.upload(OD, 'wrong-period.xlsx', period_start='2026-10-20').json()  # rows dated after the reporting date
        self.assertEqual(none_valid['status'], 'rejected')
        self.assertEqual(self.commit(none_valid['id']).status_code, 409)
        self.assertEqual(RcaRecord.objects.count(), 2)
        missing = self.client.post(reverse('rca-import-preview'), {'file': SimpleUploadedFile('a.xlsx', b'x'), 'project_scope': 'both'})
        self.assertEqual(set(missing.json()['details']), {'upload_type'})
        missing = self.client.post(reverse('rca-import-preview'), {'file': SimpleUploadedFile('a.xlsx', b'x'), 'upload_type': 'consolidated'})
        self.assertEqual(set(missing.json()['details']), {'report_name', 'project_scope'})

    def test_reuploading_the_same_workbook_creates_no_duplicates(self):
        data = workbook(Path(self.tmp.name) / 'same.xlsx', rows=WORKBOOK).read_bytes()  # the very same file, uploaded twice
        post = lambda: self.client.post(reverse('rca-import-preview'), {'file': SimpleUploadedFile('rca.xlsx', data), **DETAILS})  # noqa: E731
        first = post().json()
        self.assertEqual(self.commit(first['id']).status_code, 200)
        preview = post().json()
        self.assertIsNotNone(preview['report']['already_imported'])
        self.assertFalse(preview['report']['is_correction'])
        result = self.commit(preview['id']).json()
        self.assertEqual((result['counts']['inserted'], result['counts']['skipped'], result['correction']), (0, 4, False))
        self.assertEqual(RcaRecord.objects.count(), 4)

    def test_a_corrected_workbook_is_flagged_and_applied_only_through_explicit_choices(self):
        self.imported(WORKBOOK)
        corrected = [list(OD[0]), [DAY, '4G Satu', 'Odisha', 'OD0003', 'Fox', '', '', 'Yes', 12, 'BSNL OFC', 'Fiber', 'Cut'], *RJ, *BH]
        corrected[0][8] = 95  # outage changed; OD0002 no longer listed; OD0003 added
        preview = self.upload(corrected, 'Oct_RCA_v2.xlsx').json()
        r = preview['report']
        self.assertEqual((r['is_correction'], r['new_rows'], r['conflict_rows'], r['missing_rows']), (True, 1, 1, 1))
        self.assertEqual(r['conflicts'][0]['differences']['outage_minutes'], {'database': 90.0, 'file': 95.0})
        self.assertEqual(self.commit(preview['id']).status_code, 409)  # no silent overwrite
        self.assertEqual(self.commit(preview['id'], conflict_action='skip').status_code, 409)  # nor silent removal
        # Keeping the stored values: the returned workbook's conflicting outage does not replace the stored one.
        kept = self.commit(preview['id'], conflict_action='skip', missing_action='keep').json()
        self.assertEqual((kept['counts']['inserted'], kept['counts']['updated'], kept['counts']['withdrawn'], kept['correction']), (1, 0, 0, True))
        self.assertEqual(RcaRecord.objects.get(site_id='OD0001').outage_minutes, 90.0)
        # Applying the correction: the change is recorded and the dropped record withdrawn, not deleted.
        again = self.upload(corrected, 'Oct_RCA_v3.xlsx').json()
        applied = self.commit(again['id'], conflict_action='overwrite', missing_action='withdraw').json()
        self.assertEqual((applied['counts']['updated'], applied['counts']['withdrawn']), (1, 1))
        self.assertEqual(RcaRecord.objects.get(site_id='OD0001').outage_minutes, 95.0)
        self.assertTrue(RcaEvent.objects.filter(record__site_id='OD0001', action='source_overwritten').exists())
        withdrawn = RcaRecord.all_objects.get(site_id='OD0002')
        self.assertEqual(withdrawn.withdrawn_by_batch_id, applied['id'])
        self.assertEqual(self.client.get(reverse('rca-records'), {'q': 'OD0002'}).json()['count'], 0)
        self.assertEqual(RcaImportBatch.objects.filter(status='committed').count(), 3)  # history kept

    def test_periods_are_daily_and_never_overlap(self):
        self.imported(WORKBOOK)
        ranged = self.upload(WORKBOOK, period_start='2026-10-20', period_end='2026-10-22')
        self.assertEqual(ranged.status_code, 400)  # an upload is for one reporting date; periods are daily
        self.assertIn('periods are daily', str(ranged.json()))
        future = self.upload(WORKBOOK, period_start='2099-01-01')
        self.assertEqual(future.status_code, 400)
        self.imported(WORKBOOK + DAY2_ROWS, 'day2.xlsx', period_start='2026-10-22', report_name='RCA 22 Oct')
        periods = [(c.reporting_date.isoformat(), c.end.isoformat()) for c in RcaReportingCycle.objects.order_by('reporting_date')]
        self.assertEqual(periods, [('2026-10-21', '2026-10-21'), ('2026-10-22', '2026-10-22')])


DAY2 = datetime(2026, 10, 22)
DAY2_ROWS = [[DAY2, '4G Satu', 'Odisha', 'OD0001', 'Bravo', '', '', 'Yes', 60, 'BSNL OFC', 'BSNL OFC', 'Ofc cut'],
             [DAY2, '4G Satu', 'Odisha', 'OD0001', 'Bravo', '', '', 'Yes', 15, 'HFCL', 'HFCL', 'UBR alignment'],  # a second outage
             [DAY2, '4G Satu', 'Rajasthan', 'RJ0001', 'Charlie', '', '', 'Yes', 7, 'TCS', 'TCS', 'TCS issue']]


class DailyHistoryTests(UploadTestCase):
    """The daily workbook is cumulative: each day's file repeats the earlier days."""

    def test_a_new_day_keeps_the_earlier_days_and_skips_their_repeated_rows(self):
        self.imported(WORKBOOK, report_name='RCA 21 Oct')
        preview = self.upload(WORKBOOK + DAY2_ROWS, 'Daily_22.xlsx', report_name='RCA 22 Oct', period_start='2026-10-22').json()
        days = {d['date']: d for d in preview['report']['by_date']}
        self.assertEqual((days['2026-10-21']['kind'], days['2026-10-21']['unchanged'], days['2026-10-21']['missing']),
                         ('earlier date: repeated', 4, 0))
        self.assertEqual((days['2026-10-22']['kind'], days['2026-10-22']['new']), ('reporting date: new', 3))
        self.assertEqual((preview['report']['earlier_date_rows'], preview['report']['missing_rows']), (4, 0))
        result = self.commit(preview['id']).json()  # no choice needed: nothing differs, nothing is withdrawn
        self.assertEqual((result['counts']['inserted'], result['counts']['skipped'], result['counts']['dates_changed']), (3, 4, ['2026-10-22']))
        self.assertEqual(RcaRecord.objects.filter(reporting_date='2026-10-21').count(), 4)  # history intact
        self.assertEqual(sorted(RcaRecord.objects.filter(site_id='OD0001', reporting_date='2026-10-22').values_list('occurrence', 'final_bucket')),
                         [(1, 'BSNL OFC'), (2, 'HFCL')])
        periods = list(RcaReportingCycle.objects.order_by('reporting_date').values_list('reporting_date', 'name'))
        self.assertEqual([(d.isoformat(), n) for d, n in periods], [('2026-10-21', 'RCA 21 Oct'), ('2026-10-22', 'RCA 22 Oct')])
        # The same daily workbook again: nothing new.
        again = self.imported(WORKBOOK + DAY2_ROWS, 'Daily_22_again.xlsx', report_name='RCA 22 Oct', period_start='2026-10-22')
        self.assertEqual((again['counts']['inserted'], again['counts']['skipped'], again['correction']), (0, 7, False))
        self.assertEqual(RcaRecord.objects.count(), 7)

    def test_an_earlier_day_is_never_withdrawn_and_its_corrections_need_a_choice(self):
        self.imported(WORKBOOK)
        changed = [list(r) for r in WORKBOOK[:2]] + DAY2_ROWS  # 21 Oct: RJ and BH no longer listed, OD0001 changed
        changed[0][8] = 95
        preview = self.upload(changed, 'Daily_22_v2.xlsx', period_start='2026-10-22').json()
        days = {d['date']: d for d in preview['report']['by_date']}
        self.assertEqual((days['2026-10-21']['kind'], days['2026-10-21']['changed'], days['2026-10-21']['missing']), ('earlier date: corrected', 1, 0))
        self.assertTrue(preview['report']['is_correction'])
        self.assertEqual(self.commit(preview['id']).status_code, 409)  # the 21 Oct difference needs a choice
        kept = self.commit(preview['id'], conflict_action='skip').json()
        self.assertEqual((kept['counts']['updated'], kept['correction']), (0, True))  # a corrected submission, stored values kept
        self.assertEqual(RcaRecord.objects.filter(reporting_date='2026-10-21').count(), 4)  # nothing of 21 Oct removed
        self.assertEqual(RcaRecord.objects.get(site_id='OD0001', reporting_date='2026-10-21').outage_minutes, 90.0)
        fix = self.upload(changed, 'Daily_22_v3.xlsx', period_start='2026-10-22').json()
        applied = self.commit(fix['id'], conflict_action='overwrite').json()
        self.assertEqual((applied['counts']['updated'], applied['correction'], applied['counts']['dates_changed']), (1, True, ['2026-10-21']))
        self.assertEqual(RcaRecord.objects.get(site_id='OD0001', reporting_date='2026-10-21').outage_minutes, 95.0)

    def test_earlier_days_not_yet_stored_are_added_under_their_own_date(self):
        result = self.imported(WORKBOOK + DAY2_ROWS, 'Daily_22.xlsx', period_start='2026-10-22')
        self.assertEqual((result['counts']['inserted'], result['counts']['dates_changed']), (7, ['2026-10-21', '2026-10-22']))
        self.assertEqual(sorted(d.isoformat() for d in RcaReportingCycle.objects.values_list('reporting_date', flat=True)),
                         ['2026-10-21', '2026-10-22'])
        first_day = RcaReportingCycle.objects.get(reporting_date='2026-10-21')
        detail = self.as_admin('get', 'rca-cycle', [first_day.pk]).json()
        self.assertEqual(([u['id'] for u in detail['uploads']], detail['records']), ([result['id']], 4))

    def test_the_workbook_is_checked_against_the_expected_daily_scope_and_the_admin_sees_daily_status(self):
        self.imported(WORKBOOK)
        day1 = self.period()
        self.as_admin('put', 'rca-cycle-required', [day1.pk], {'units': SCOPE})
        # 22 Oct: the expected scope carries over; the workbook has no LWE Bihar or LWE Odisha rows for 22 Oct.
        preview = self.upload(WORKBOOK + DAY2_ROWS, 'Daily_22.xlsx', period_start='2026-10-22').json()
        coverage = preview['report']['coverage']
        self.assertEqual((coverage['source'], coverage['missing']), ('previous period', [['LWE', 'BH'], ['LWE', 'OD']]))
        # A later period's scope is never used for an earlier date.
        self.as_admin('post', 'rca-cycles', data={'period_start': '2026-10-25', 'units': [['LWE', 'JH']]})
        check = self.upload(WORKBOOK + DAY2_ROWS, 'x.xlsx', period_start='2026-10-22').json()
        self.assertEqual(check['report']['coverage']['expected'], SCOPE)
        self.client.post(reverse('rca-import-discard', args=[check['id']]))
        self.commit(preview['id'])
        bad = workbook(Path(self.tmp.name) / 'bad.xlsx', rows=OD, headers=['Date', 'Project'])
        self.client.post(reverse('rca-import-preview'), {'file': SimpleUploadedFile('bad.xlsx', bad.read_bytes()), **{**DETAILS, 'period_start': '2026-10-22'}})
        listing = {c['period_start']: c for c in self.as_admin('get', 'rca-cycles').json()['cycles']}
        day2 = listing['2026-10-22']
        self.assertEqual((day2['status']['code'], day2['status']['received'], day2['status']['required']), ('partial', 2, 4))
        self.assertEqual({k: day2['uploads_summary'][k] for k in ('total', 'imported', 'validation_failed', 'corrections')},
                         {'total': 2, 'imported': 1, 'validation_failed': 1, 'corrections': 0})
        self.assertEqual(listing['2026-10-21']['status']['received'], 3)
        # The summary for one reporting date, and the months the records support.
        summary = self.as_admin('get', 'rca-summary', data={'date_from': '2026-10-22', 'date_to': '2026-10-22'}).json()
        self.assertEqual((summary['kpis']['records'], summary['cycle']['period_start'], summary['cycle']['matches_filter']), (3, '2026-10-22', True))
        options = self.as_admin('get', 'rca-options').json()
        self.assertEqual(options['months'], [{'month': '2026-10', 'dates_with_records': 2}])


class CoverageTests(UploadTestCase):
    def test_coverage_comes_only_from_the_configured_scope_and_accepted_records_and_completes_the_final_report(self):
        first = self.imported(WORKBOOK)
        period = self.period()
        self.assertEqual(self.detail()['status']['code'], 'unconfigured')
        self.assertEqual(self.as_admin('post', 'rca-cycle-finalize', [period.pk]).status_code, 409)
        data = self.as_admin('put', 'rca-cycle-required', [period.pk], {'units': SCOPE}).json()
        self.assertEqual((data['status']['code'], data['status']['received'], data['status']['required']), ('partial', 3, 4))
        units = {(u['project'], u['circle']): u for u in data['units']}
        self.assertEqual(units[('LWE', 'OD')]['status_label'], 'Pending — no accepted records')
        self.assertEqual((units[('4G Saturation', 'OD')]['records'], units[('4G Saturation', 'OD')]['source_files']), (2, ['rca.xlsx']))
        self.assertEqual(data['unexpected'], [])
        self.assertEqual([u['id'] for u in data['uploads']], [first['id']])
        # An upload that is only validated, not confirmed, is not received data.
        waiting = self.upload(LWE_OD, 'lwe.xlsx', project_scope='LWE').json()
        self.assertEqual((self.detail()['status']['code'], self.detail()['status']['received']), ('review', 3))
        # Confirming it: the LWE-only workbook holds LWE Odisha only, so the stored LWE Bihar record is outside its scope:
        # never listed as missing, never offered for withdrawal.
        self.assertEqual(waiting['report']['missing_rows'], 0)
        result = self.commit(waiting['id']).json()
        self.assertEqual(result['final_report']['version'], 1)  # every expected unit now has data
        detail = self.detail()
        self.assertEqual((detail['status']['code'], detail['status']['label']), ('final', 'Final report generated'))
        report = RcaReport.objects.get()
        book = self.sheets(self.as_admin('get', 'rca-cycle-report', [period.pk, report.pk]))
        self.assertEqual(book['Report']['A2'].value, 'FINAL — VERSION 1')
        master = list(book['RCA Master'].iter_rows(values_only=True))
        header = master[0]
        ids = [row[header.index('Record ID')] for row in master[1:]]
        self.assertEqual(sorted(ids), sorted(RcaRecord.objects.values_list('pk', flat=True)))  # each accepted record exactly once
        self.assertEqual({row[header.index('Upload ID')] for row in master[1:]}, {first['id'], result['id']})  # traceable to uploads
        rows = {row[3]: row for row in master[1:]}
        # Other Media is not an approved Final Bucket, so an upload cannot add it: OD0002 (Others, blank Bucket - 2 and RCA) needs RCA.
        self.assertEqual(rows['OD0002'][header.index('RCA applicability')], 'RCA Required — Missing Information')
        self.assertEqual(rows['RJ0001'][header.index('RCA applicability')], 'RCA Required — Missing Information')
        self.assertEqual((rows['OD0001'][1], rows['OD0001'][2]), ('4G Satu', 'Odisha'))  # source values as written
        self.assertEqual(book['Uploads'].max_row, 3)
        summary = {r[0]: r[1] for r in book['Summary'].iter_rows(values_only=True) if r and r[0]}
        self.assertEqual(summary['Accepted RCA records'], 5)
        # The NOC Lead downloads the same final file for their upload; the expected scope is now fixed.
        response = self.client.get(reverse('rca-import-workbook', args=[result['id']]))
        self.assertEqual(response['Content-Disposition'].split('filename=')[1].strip('"'), 'RCA_Master_2026-10-21_FINAL_v1.xlsx')
        self.sheets(response)  # reads and releases the file (see sheets)
        self.assertEqual(self.as_admin('put', 'rca-cycle-required', [period.pk], {'units': SCOPE[:1]}).status_code, 409)
        # A correction after finalization makes the period "revised" until an Admin generates v2.
        corrected = [list(r) for r in WORKBOOK]
        corrected[2][10], corrected[2][11] = 'Fiber', 'OFC cut'
        fix = self.upload(corrected, 'fix.xlsx').json()
        self.assertIsNone(self.commit(fix['id'], conflict_action='overwrite', missing_action='keep').json()['final_report'])
        self.assertEqual(self.detail()['status']['code'], 'revised')
        v2 = self.as_admin('post', 'rca-cycle-finalize', [period.pk])
        self.assertEqual((v2.status_code, v2.json()['report']['version']), (201, 2))
        self.assertIsNotNone(RcaReport.objects.get(version=1).superseded_at)
        again = self.as_admin('post', 'rca-cycle-finalize', [period.pk])
        self.assertEqual((again.status_code, again.json()['created']), (200, False))  # no extra version

    def test_an_admin_starts_a_period_with_its_expected_scope_and_the_summary_shows_it(self):
        started = self.as_admin('post', 'rca-cycles', data={'period_start': '2026-10-01', 'period_end': '2026-10-31',
                                                            'name': 'October 2026 RCA Report', 'units': SCOPE})
        self.assertEqual(started.status_code, 201, started.content)
        self.assertEqual((started.json()['period_label'], started.json()['status']['code']), ('01 Oct 2026 – 31 Oct 2026', 'awaiting'))
        upload = self.imported(WORKBOOK)  # reporting date 21 Oct: filed under the Admin's October period, no new period
        self.assertEqual((upload['cycle'], RcaReportingCycle.objects.count()), (started.json()['id'], 1))
        summary = self.as_admin('get', 'rca-summary', data={'date_from': '2026-10-01', 'date_to': '2026-10-31'}).json()
        self.assertEqual((summary['kpis']['records'], summary['cycle']['status']['received'], summary['cycle']['status']['required']), (4, 3, 4))
        self.assertEqual(summary['projects'][0]['project'], '4G Saturation')
        listing = self.as_admin('get', 'rca-cycles').json()
        self.assertEqual(listing['default_units'], SCOPE)  # the next period starts with this scope


class PermissionTests(UploadTestCase):
    def test_noc_leads_see_only_their_own_uploads_and_ci_users_cannot_upload(self):
        mine = self.imported(WORKBOOK)
        self.client.force_login(self.other_noc)
        self.assertEqual(self.client.get(reverse('rca-imports')).json()['imports'], [])
        for name in ('rca-import', 'rca-import-issues', 'rca-import-workbook'):
            self.assertEqual(self.client.get(reverse(name, args=[mine['id']])).status_code, 404, name)
        self.assertEqual(self.commit(mine['id']).status_code, 404)
        # The NOC Lead has no Admin pages: periods, summary, users, team performance.
        for name, args in (('rca-cycles', []), ('rca-cycle', [1]), ('rca-summary', []), ('auth-users', []), ('dashboard-teams', [])):
            self.assertEqual(self.client.get(reverse(name, args=args)).status_code, 403, name)
        # CI users see only their own (circle) uploads, never another user's, a period workbook or a consolidated upload.
        self.client.force_login(self.ci)
        self.assertEqual(self.client.get(reverse('rca-imports')).json()['imports'], [])
        self.assertEqual(self.client.get(reverse('rca-import', args=[mine['id']])).status_code, 404)
        for name, args in (('rca-import-workbook', [mine['id']]), ('rca-cycles', [])):
            self.assertEqual(self.client.get(reverse(name, args=args)).status_code, 403, name)
        self.assertEqual(self.upload(WORKBOOK).status_code, 403)
        # An Admin sees every upload.
        everyone = self.as_admin('get', 'rca-imports', data=None, QUERY_STRING='all=1').json()
        self.assertEqual(([b['id'] for b in everyone['imports']], everyone['all']), ([mine['id']], True))
        self.client.logout()
        self.assertEqual(self.client.get(reverse('rca-imports')).status_code, 401)
