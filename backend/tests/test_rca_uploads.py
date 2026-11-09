"""Upload Circle RCA and Upload Consolidated RCA: one central RcaRecord table and RCA Summary, circle submissions kept
apart from data availability, daily periods, scope-limited withdrawals, and who may upload what.

Synthetic workbooks and Up-Time sites in the test database only; files go to a temporary DATA_DIR.
"""
from datetime import datetime
from pathlib import Path

from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import reverse

from apps.accounts.roles import set_rca_consolidated
from apps.accounts.scope import set_pairs
from apps.rca.models import RcaEvent, RcaImportBatch, RcaRecord, RcaReport, RcaReportingCycle
from tests.auth_helpers import portal_user
from tests.test_rca import RcaTestCase, uptime_sites, workbook

D21, D22 = datetime(2026, 10, 21), datetime(2026, 10, 22)
OD_21 = [[D21, '4G Satu', 'Odisha', 'OD0001', 'Bravo', 'KORAPUT', 'KORAPUT', 'Yes', 90, 'BSNL OFC', 'Fiber', 'Cut'],
         [D21, '4G Satu', 'Odisha', 'OD0002', 'Echo', 'KORAPUT', 'KORAPUT', 'Yes', 30, 'Others', '', '']]
RJ_21 = [[D21, '4G Satu', 'Rajasthan', 'RJ0001', 'Charlie', 'Jaisalmer', 'JODHPUR', 'Yes', 5, 'TCS', 'TCS', 'TCS issue']]
LWE_OD_21 = [[D21, 'LWE', 'Odisha', 'LWEOD0001', 'Lima', '', '', 'Yes', 4, 'BSNL OFC', 'Fiber', 'Cut']]
OD_22 = [[D22, '4G Satu', 'Odisha', 'OD0001', 'Bravo', '', '', 'Yes', 60, 'HFCL', 'HFCL', 'UBR alignment']]
SCOPE = [['4G Saturation', 'OD'], ['4G Saturation', 'RJ'], ['LWE', 'OD']]


class UploadCase(RcaTestCase):
    def setUp(self):
        super().setUp()
        uptime_sites(('4G Saturation', 'OD', 'OD0001'), ('4G Saturation', 'OD', 'OD0002'), ('4G Saturation', 'RJ', 'RJ0001'),
                     ('LWE', 'OD', 'LWEOD0001'))
        self.noc = portal_user('noc', 'noc_lead')
        self.uploader = portal_user('consolidator', 'noc_lead')
        set_rca_consolidated(self.uploader, True)
        self.client.force_login(self.admin)

    def post(self, rows, name='rca.xlsx', **details):
        path = workbook(Path(self.tmp.name) / name, rows=rows)
        return self.client.post(reverse('rca-import-preview'), {'file': SimpleUploadedFile(name, path.read_bytes()), **details})

    def circle(self, rows, project='4G Saturation', circle='OD', day='2026-10-21', name='circle.xlsx'):
        return self.post(rows, name, upload_type='circle', project=project, circle=circle, reporting_date=day)

    def consolidated(self, rows, name='all.xlsx', **details):
        return self.post(rows, name, **{'upload_type': 'consolidated', 'report_name': 'Daily RCA', 'project_scope': 'both', **details})

    def commit(self, batch_id, **choices):
        return self.client.post(reverse('rca-import-commit', args=[batch_id]), choices, content_type='application/json')

    def imported(self, response, **choices) -> dict:
        self.assertEqual(response.status_code, 201, response.content)
        self.assertEqual(response.json()['status'], 'previewed', response.json().get('error'))
        done = self.commit(response.json()['id'], **choices)
        self.assertEqual(done.status_code, 200, done.content)
        return done.json()

    def units(self, day='2026-10-21') -> dict:
        cycle = RcaReportingCycle.objects.get(reporting_date=day)
        self.client.force_login(self.admin)
        detail = self.client.get(reverse('rca-cycle', args=[cycle.pk])).json()
        return {(u['project'], u['circle']): u for u in detail['units']} | {'_status': detail['status']}

    def configure(self, day='2026-10-21'):
        cycle = RcaReportingCycle.objects.get(reporting_date=day)
        self.client.force_login(self.admin)
        response = self.client.put(reverse('rca-cycle-required', args=[cycle.pk]), {'units': SCOPE}, content_type='application/json')
        self.assertEqual(response.status_code, 200, response.content)


class BothTypesTests(UploadCase):
    def test_both_types_save_into_the_same_table_and_feed_the_same_summary(self):
        circle = self.imported(self.circle(OD_21))
        consolidated = self.imported(self.consolidated(RJ_21 + LWE_OD_21))
        self.assertEqual((circle['upload_type'], circle['circle'], consolidated['upload_type'], consolidated['circle']),
                         ('circle', 'OD', 'consolidated', None))
        by_batch = dict(RcaRecord.objects.values_list('site_key', 'batch_id'))
        self.assertEqual(by_batch, {'OD0001': circle['id'], 'OD0002': circle['id'], 'RJ0001': consolidated['id'], 'LWEOD0001': consolidated['id']})
        summary = self.client.get(reverse('rca-summary'), {'date': '2026-10-21'}).json()
        self.assertEqual(summary['kpis']['records'], 4)
        self.assertEqual({(c['project'], c['circle']) for c in summary['circles']},
                         {('4G Saturation', 'OD'), ('4G Saturation', 'RJ'), ('LWE', 'OD')})

    def test_a_circle_file_rejects_other_projects_circles_and_sites_and_holds_one_date(self):
        other = [[D21, '4G Satu', 'Rajasthan', 'RJ0001', 'Charlie', '', '', 'Yes', 5, 'TCS', 'TCS', 'x'],
                 [D21, 'LWE', 'Odisha', 'LWEOD0001', 'Lima', '', '', 'Yes', 4, 'BSNL OFC', 'Fiber', 'Cut'],
                 [D21, '4G Satu', 'Odisha', 'RJ0001', 'Wrong', '', '', 'Yes', 5, 'TCS', 'TCS', 'x']]  # an RJ site written as OD
        preview = self.circle(OD_21 + other).json()
        self.assertEqual(preview['status'], 'previewed')
        codes = preview['report']['issue_counts']
        self.assertEqual((codes.get('outside_circle'), codes.get('outside_project_scope'), codes.get('site_of_other_circle')), (1, 1, 2))  # the RJ row is also an RJ site
        self.assertEqual((preview['counts']['valid'], preview['counts']['rejected']), (2, 3))
        self.assertEqual(self.commit(preview['id']).status_code, 409)  # rejected rows need explicit confirmation
        self.assertEqual(self.commit(preview['id'], accept_rejected=True).status_code, 200)
        self.assertEqual(set(RcaRecord.objects.values_list('site_key', flat=True)), {'OD0001', 'OD0002'})
        two_days = self.circle(OD_21 + OD_22, day='2026-10-22', name='two.xlsx').json()
        self.assertEqual(two_days['status'], 'rejected')
        self.assertIn('A circle file holds one reporting date', two_days['error'])
        self.assertEqual(self.commit(two_days['id']).status_code, 409)
        self.assertEqual(RcaRecord.objects.count(), 2)

    def test_duplicates_are_skipped_and_differences_need_an_overwrite_choice(self):
        self.imported(self.circle(OD_21))
        again = self.imported(self.circle(OD_21, name='again.xlsx'))
        self.assertEqual((again['counts']['inserted'], again['counts']['unchanged']), (0, 2))
        changed = [list(r) for r in OD_21]
        changed[0][8] = 95
        consolidated = self.consolidated(changed, period_start='2026-10-21').json()
        self.assertEqual(consolidated['report']['conflict_rows'], 1)
        self.assertEqual(self.commit(consolidated['id']).status_code, 409)
        overwrite = self.commit(consolidated['id'], conflict_action='overwrite').json()
        record = RcaRecord.objects.get(site_key='OD0001')
        self.assertEqual((record.outage_minutes, record.batch_id), (95, overwrite['id']))
        self.assertTrue(RcaEvent.objects.filter(record=record, action='source_overwritten').exists())
        self.assertEqual(RcaRecord.objects.count(), 2)


class SubmissionTrackingTests(UploadCase):
    def test_circle_submission_and_data_availability_are_separate(self):
        self.imported(self.consolidated(OD_21 + RJ_21 + LWE_OD_21))
        self.configure()
        units = self.units()
        od = units[('4G Saturation', 'OD')]
        self.assertEqual((od['submission_status'], od['submission_label'], od['status'], od['data_label']),
                         ('not_received', 'Not received', 'received', 'Data available'))  # consolidated data, no circle file
        self.assertEqual((units['_status']['received'], units['_status']['circle_submissions']), (3, 0))
        circle = self.imported(self.circle(OD_21))  # identical rows: nothing new, still a submission
        self.assertEqual(circle['counts']['inserted'], 0)
        units = self.units()
        od, rj = units[('4G Saturation', 'OD')], units[('4G Saturation', 'RJ')]
        self.assertEqual((od['submission_status'], od['submission']['batch'], rj['submission_status']), ('received', circle['id'], 'not_received'))
        self.assertIsNotNone(od['submission']['committed_at'])
        self.assertEqual(units[('LWE', 'OD')]['submission_status'], 'not_received')  # MP/OD 4G never counts for LWE

    def test_previews_failures_rejections_and_legacy_uploads_are_not_submissions(self):
        self.imported(self.consolidated(OD_21))
        self.configure()
        self.circle(RJ_21, circle='RJ')  # previewed only
        self.circle(OD_21 + OD_22, day='2026-10-22')  # rejected (two dates)
        self.client.post(reverse('rca-import-preview'), {'file': SimpleUploadedFile('bad.xlsx', b'not a workbook'), 'upload_type': 'circle',
                                                          'project': 'LWE', 'circle': 'OD', 'reporting_date': '2026-10-21'})  # failed
        RcaImportBatch.objects.create(original_filename='old.xlsx', checksum_sha256='x', sheet_name='Sheet1', status='committed',
                                      period_start=datetime(2026, 10, 21).date(), period_end=datetime(2026, 10, 21).date(),
                                      project_scope='4G Saturation', circle='OD')  # a legacy batch (default type)
        units = self.units()
        self.assertEqual({k: u['submission_status'] for k, u in units.items() if k != '_status'},
                         {('4G Saturation', 'OD'): 'not_received', ('4G Saturation', 'RJ'): 'not_received', ('LWE', 'OD'): 'not_received'})

    def test_a_circle_submission_counts_for_its_own_date_only(self):
        self.imported(self.circle(OD_21))
        self.imported(self.consolidated(OD_22, name='d22.xlsx'))
        self.configure('2026-10-22')
        self.assertEqual(self.units('2026-10-22')[('4G Saturation', 'OD')]['submission_status'], 'not_received')


class ScopeTests(UploadCase):
    def test_a_circle_upload_never_offers_to_withdraw_another_circle(self):
        self.imported(self.consolidated(OD_21 + RJ_21 + LWE_OD_21))
        preview = self.circle(OD_21[:1]).json()  # OD's corrected file drops OD0002
        missing = {(m['project'], m['circle'], m['site_id']) for m in preview['report']['missing']}
        self.assertEqual(missing, {('4G Saturation', 'OD', 'OD0002')})  # never RJ or LWE OD
        self.imported(self.circle(OD_21[:1], name='fix.xlsx'), missing_action='withdraw')
        self.assertEqual(set(RcaRecord.objects.values_list('site_key', flat=True)), {'OD0001', 'RJ0001', 'LWEOD0001'})

    def test_a_consolidated_upload_withdraws_only_within_its_reporting_date_units(self):
        self.imported(self.consolidated(OD_21 + RJ_21 + LWE_OD_21))
        later = self.consolidated(OD_21[:1] + OD_22, name='d22.xlsx').json()  # reporting date 22 Oct (latest in the file)
        self.assertEqual((later['period_start'], later['report']['missing_rows']), ('2026-10-22', 0))  # 21 Oct is history
        self.imported(self.consolidated(OD_21[:1] + OD_22, name='d22.xlsx'))
        same_day = self.consolidated(RJ_21, name='rj.xlsx', period_start='2026-10-21').json()  # RJ only
        self.assertEqual(same_day['report']['missing_rows'], 0)  # OD and LWE OD are not in this file: never missing
        self.assertEqual(RcaRecord.objects.count(), 5)  # 4 of 21 Oct, 1 of 22 Oct; nothing withdrawn


class DailyCycleTests(UploadCase):
    def test_multi_date_workbooks_use_one_daily_period_per_date(self):
        result = self.imported(self.consolidated(OD_21 + OD_22))
        periods = [(c.reporting_date.isoformat(), c.end.isoformat()) for c in RcaReportingCycle.objects.order_by('reporting_date')]
        self.assertEqual(periods, [('2026-10-21', '2026-10-21'), ('2026-10-22', '2026-10-22')])
        self.assertEqual(result['cycle'], RcaReportingCycle.objects.get(reporting_date='2026-10-22').pk)
        self.imported(self.circle(OD_21, name='od.xlsx'))  # reuses the 21 Oct period
        self.assertEqual(RcaReportingCycle.objects.count(), 2)

    def test_expected_units_carry_over_from_the_previous_day(self):
        self.imported(self.circle(OD_21))
        self.configure()
        self.imported(self.circle(OD_22, day='2026-10-22', name='d22.xlsx'))
        self.assertEqual(sorted(RcaReportingCycle.objects.get(reporting_date='2026-10-22').required.values_list('project', 'circle')),
                         sorted(tuple(u) for u in SCOPE))


class FinalReportTests(UploadCase):
    def test_complete_data_from_a_consolidated_upload_finalises_without_circle_files(self):
        self.imported(self.circle(OD_21))
        self.configure()
        result = self.imported(self.consolidated(RJ_21 + LWE_OD_21))
        self.assertEqual(result['final_report']['version'], 1)  # every expected unit has data
        report = RcaReport.objects.get()
        self.assertEqual(report.record_count, 4)
        units = {(u['project'], u['circle']): u['submission_status'] for u in report.submissions}
        self.assertEqual(units, {('4G Saturation', 'OD'): 'received', ('4G Saturation', 'RJ'): 'not_received', ('LWE', 'OD'): 'not_received'})

    def test_complete_data_from_circle_uploads_finalises(self):
        self.imported(self.circle(OD_21))
        self.configure()
        self.imported(self.circle(RJ_21, circle='RJ', name='rj.xlsx'))
        result = self.imported(self.circle(LWE_OD_21, project='LWE', name='lwe.xlsx'))
        self.assertEqual(result['final_report']['version'], 1)


class PermissionTests(UploadCase):
    def test_ci_users_upload_circle_files_only_for_their_granted_project_and_circle(self):
        ci = portal_user('ci-od', 'ci')
        set_pairs(ci, [('4G Saturation', 'OD')])
        self.client.force_login(ci)
        rights = self.client.get(reverse('rca-imports')).json()['rights']
        self.assertEqual((rights['circle'], rights['consolidated'], rights['access']), (True, False, [{'project': '4G Saturation', 'circle': 'OD'}]))
        self.assertEqual(self.circle(LWE_OD_21, project='LWE').status_code, 403)  # OD under LWE is not granted
        self.assertEqual(self.circle(RJ_21, circle='RJ').status_code, 403)
        mine = self.imported(self.circle(OD_21))
        self.assertEqual(mine['circle'], 'OD')
        set_pairs(ci, [])  # access withdrawn between preview and commit
        waiting = self.circle(OD_21, name='w.xlsx')
        self.assertEqual(waiting.status_code, 403)
        none = portal_user('ci-none', 'ci')
        self.client.force_login(none)
        self.assertEqual(self.client.get(reverse('rca-imports')).json()['rights']['circle'], False)
        self.assertEqual(self.circle(OD_21).status_code, 403)

    def test_access_is_checked_again_at_commit(self):
        ci = portal_user('ci-od', 'ci')
        set_pairs(ci, [('4G Saturation', 'OD')])
        self.client.force_login(ci)
        preview = self.circle(OD_21).json()
        set_pairs(ci, [])
        self.assertEqual(self.commit(preview['id']).status_code, 403)
        self.assertEqual(RcaRecord.objects.count(), 0)

    def test_consolidated_uploads_need_admin_or_the_group(self):
        for user in (self.noc, portal_user('ci-any', 'ci')):
            self.client.force_login(user)
            self.assertEqual(self.consolidated(OD_21).status_code, 403, user.username)
        self.client.force_login(self.noc)
        self.assertEqual(self.circle(OD_21).status_code, 201)  # a NOC Lead still uploads circle files
        self.client.force_login(self.uploader)
        preview = self.consolidated(OD_21 + RJ_21, name='g.xlsx').json()
        set_rca_consolidated(self.uploader, False)  # removed from the group before confirming
        self.assertEqual(self.commit(preview['id']).status_code, 403)
        self.client.force_login(self.admin)
        response = self.client.patch(reverse('auth-user', args=[self.noc.pk]), {'rca_consolidated': True}, content_type='application/json')
        self.assertEqual((response.status_code, response.json()['user']['rca_consolidated']), (200, True))
        self.client.force_login(self.noc)
        self.assertEqual(self.client.get(reverse('auth-me')).json()['user']['rca_upload'], {'circle': True, 'consolidated': True})
        self.assertEqual(self.consolidated(OD_21, name='n.xlsx').status_code, 201)


class LegacyTests(UploadCase):
    def test_existing_batches_and_records_are_untouched_and_stay_legacy(self):
        legacy = RcaImportBatch.objects.create(original_filename='old.xlsx', checksum_sha256='x', sheet_name='Sheet1', status='committed')
        manual = RcaRecord.objects.create(reporting_date=D21.date(), project='4G Saturation', project_raw='4G', circle='OD', circle_raw='OD',
                                          site_id='OD0009', site_key='OD0009', source='manual', rca_text='Manual entry')
        self.assertEqual((legacy.upload_type, legacy.circle), ('legacy', None))
        self.imported(self.circle(OD_21))
        self.imported(self.consolidated(OD_21[:1], period_start='2026-10-21'), missing_action='withdraw')
        manual.refresh_from_db()
        self.assertIsNone(manual.withdrawn_at)  # manual records are never compared, listed as missing or withdrawn
        legacy.refresh_from_db()
        self.assertEqual((legacy.upload_type, legacy.status), ('legacy', 'committed'))
