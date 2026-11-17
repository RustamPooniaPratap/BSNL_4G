"""BSNL Module: Auto Email Reports and BSNL Letters (apps/bsnl). Test database only; email delivery is always mocked."""
from __future__ import annotations

import email
import email.policy
import io
import os
import zipfile
from datetime import date, datetime, timedelta
from unittest.mock import patch
from zoneinfo import ZoneInfo

import numpy as np
from django.test import TestCase
from django.urls import reverse
from openpyxl import load_workbook

from apps.accounts.models import AccessAssignment, Role, RolePermission
from apps.alerts.mailer import MailError
from apps.bsnl import common, delivery, documents, letters, reports, scheduler
from apps.bsnl.classification import get_bucket_classification
from apps.bsnl.common import Period
from apps.bsnl.models import (BsnlLetter, CircleLetterProfile, DistributionRecipient, LetterEvent, LetterStatus, RcaBucketMapping,
                              ReportRun)
from apps.common.models import Setting
from apps.dashboard import metrics
from apps.organization.models import Circle, Project, ProjectCircle
from apps.rca.models import RcaRecord
from apps.sitedata import dashboard_source, portfolio
from apps.tickets.models import Ticket
from tests.auth_helpers import portal_user
from tests.sitedata_factory import make_daily, make_site

G4, LWE = '4G Saturation', 'LWE'
DAYS = [date(2026, 11, 2) + timedelta(days=i) for i in range(14)]  # Mon 2 Nov .. Sun 15 Nov
LATEST = DAYS[-1]
IST = ZoneInfo('Asia/Kolkata')
SEND_ON = {delivery.ENV_FLAG: 'true'}


def mail_ok():
    return patch('apps.bsnl.delivery.mailer.send', return_value='250 2.0.0 queued')


def account_ok():
    return patch('apps.bsnl.delivery.engine.active_account', return_value=object())


class BsnlTestCase(TestCase):
    def setUp(self):
        portfolio.clear_cache()
        self.addCleanup(portfolio.clear_cache)
        self.g4, _ = Project.objects.get_or_create(key=G4, defaults={'code': '4G', 'name': G4})
        self.lwe, _ = Project.objects.get_or_create(key=LWE, defaults={'code': 'LWE', 'name': LWE})
        self.mp, _ = Circle.objects.get_or_create(code='MP', defaults={'name': 'Madhya Pradesh'})
        self.kl, _ = Circle.objects.get_or_create(code='KL', defaults={'name': 'Kerala'})
        self.pc = {}
        for project, circle in ((self.g4, self.mp), (self.lwe, self.mp), (self.g4, self.kl)):
            self.pc[(project.key, circle.code)], _ = ProjectCircle.objects.get_or_create(project=project, circle=circle)
        # MP 4G: two CIs; S1 fails SLA, S2 has a small outage, S3/S4 clean. KL 4G: K1 clean. MP LWE: L1 has an outage.
        spec = [('UVMPS1', G4, 'MP', 'CI One', 'NE A', 60.0), ('UVMPS2', G4, 'MP', 'CI One', 'NE A', 10.0),
                ('UVMPS3', G4, 'MP', 'CI Two', 'NE B', 0.0), ('UVMPS4', G4, 'MP', 'CI Two', 'NE B', 0.0),
                ('UVKLK1', G4, 'KL', 'CI Kay', 'NE K', 0.0), ('LWEMPL1', LWE, 'MP', 'CI Lwe', 'NE L', 30.0)]
        self.sites = {}
        for site_id, tech, circle, ci, ie, outage in spec:
            site = make_site(site_id, technology=tech, circle=circle, ci_name=ci, ie_name=ie, on_air_date=date(2026, 1, 1))
            self.sites[site_id] = site
            for day in DAYS:
                make_daily(site, day, outage)
        self.admin = portal_user('bsnl-admin', 'admin')
        self.client.force_login(self.admin)

    def dataset(self, pairs=None):
        portfolio.clear_cache()
        return dashboard_source.dataset(pairs, reports.SCOPE)

    def rca(self, site_id, day, minutes, final='BSNL OFC', sub='SSA OFC', text='Fibre cut by BSNL', project=None, circle=None):
        site = self.sites[site_id]
        return RcaRecord.objects.create(reporting_date=day, project=project or site.technology, project_raw=project or site.technology,
                                        circle=circle or site.circle, circle_raw=circle or site.circle, site_id=site_id, site_key=site.site_key,
                                        site_name=site.site_name, outage_minutes=minutes, final_bucket=final, final_bucket_key=final.lower(),
                                        bucket_2=sub, bucket_2_key=sub.lower(), rca_text=text)

    def recipient(self, circle, report_type, email_addr, kind='To', active=True):
        return DistributionRecipient.objects.create(circle=circle, report_type=report_type, name=email_addr.split('@')[0],
                                                    designation='Circle Head', email=email_addr, kind=kind, is_active=active)

    def scoped(self, username, perms, pairs):
        role = Role.objects.create(name=f'{username} role')
        for module, action in perms:
            RolePermission.objects.create(role=role, module=module, action=action)
        user = portal_user(username, role=None)
        for project, circle in pairs:
            AccessAssignment.objects.create(user=user, role=role, project=Project.objects.get(key=project),
                                            project_circle=self.pc[(project, circle)])
        return user


class PeriodTests(TestCase):
    def test_d1_and_weekly_periods_follow_the_reference(self):
        self.assertEqual(common.d1_period(date(2026, 11, 15)), Period(date(2026, 11, 15), date(2026, 11, 15)))
        # Week = Monday..Sunday ending on the latest Sunday on or before the D-1 date (reference weekRange).
        self.assertEqual(common.week_period(date(2026, 11, 15)), Period(date(2026, 11, 9), date(2026, 11, 15)))  # a Sunday
        self.assertEqual(common.week_period(date(2026, 11, 14)), Period(date(2026, 11, 2), date(2026, 11, 8)))  # a Saturday
        self.assertEqual(common.week_period(date(2026, 11, 16)), Period(date(2026, 11, 9), date(2026, 11, 15)))  # a Monday

    def test_previous_and_month_to_date_boundaries(self):
        week = Period(date(2026, 11, 9), date(2026, 11, 15))
        self.assertEqual(week.previous(), Period(date(2026, 11, 2), date(2026, 11, 8)))
        self.assertEqual(week.month_to_date(), Period(date(2026, 11, 1), date(2026, 11, 15)))
        day = Period(date(2026, 12, 1), date(2026, 12, 1))
        self.assertEqual(day.previous(), Period(date(2026, 11, 30), date(2026, 11, 30)))
        self.assertEqual(day.month_to_date(), day)
        self.assertEqual(Period(date(2026, 11, 9), date(2026, 11, 15)).days, 7)

    def test_indian_number_format(self):
        self.assertEqual(common.fmt(1234567.891, 2), '12,34,567.89')
        self.assertEqual(common.fmt(None), '–')
        self.assertEqual(common.fmt(-0.004, 2), '0.00')

    def test_outage_minutes_round_half_up_after_aggregation(self):
        rows = [
            {'site_id': 'S1', 'cause': 'SSA OFC', 'outage_minutes': 0.4},
            {'site_id': 'S2', 'cause': 'SSA OFC', 'outage_minutes': 0.4},
        ]
        self.assertEqual(common.whole_minutes(1.5), 2)
        self.assertEqual(common.fmt(common.whole_minutes(1234.6)), '1,235')
        self.assertEqual(letters.summary(rows)['outage_minutes'], 1)
        self.assertEqual(letters.causes(rows)[0]['outage_minutes'], 0.8)


class BucketTests(BsnlTestCase):
    def test_seeded_mapping_blank_and_unapproved_buckets(self):
        self.assertEqual(RcaBucketMapping.objects.get(final_bucket='BSNL OFC').bucket, 'Customer')
        self.assertEqual(RcaBucketMapping.objects.get(final_bucket='BSNL Media').bucket, 'Customer')
        self.assertEqual(RcaBucketMapping.objects.get(final_bucket='IaasP Power').bucket, 'Own')
        self.assertEqual(RcaBucketMapping.objects.get(final_bucket='IaasP Others').bucket, 'Own')
        for final in ('Others', 'TCS', 'DMW', 'HFCL'):
            self.assertEqual(RcaBucketMapping.objects.get(final_bucket=final).bucket, 'Third party')
        mapping = common.bucket_map()
        self.assertEqual(common.bucket_of('bsnl  ofc', mapping), 'Customer')  # case and spaces ignored (taxonomy)
        self.assertEqual(common.bucket_of('IaaSP Power', mapping), 'Own')
        self.assertEqual(common.bucket_of('', mapping), 'Unclassified')
        self.assertEqual(common.bucket_of(None, mapping), 'Unclassified')
        self.assertEqual(common.bucket_of('-', mapping), 'Unclassified')
        self.assertEqual(common.bucket_of('Something else', mapping), 'Unclassified')

    def test_classification_fields_share_the_current_mapping_and_missing_rows_are_unclassified(self):
        mapped = get_bucket_classification('  iAaSp   pOwEr ')
        self.assertEqual((mapped.ownership, mapped.bucket_2, mapped.mapped_bucket), ('Own', 'Own', 'Own'))

        RcaBucketMapping.objects.filter(final_bucket='IaasP Power').update(bucket='Customer', updated_by=self.admin)
        changed = get_bucket_classification('iaasp power')
        self.assertEqual((changed.ownership, changed.bucket_2, changed.mapped_bucket), ('Customer', 'Customer', 'Customer'))

        RcaBucketMapping.objects.filter(final_bucket='IaasP Power').delete()
        missing = get_bucket_classification('IaasP Power')
        self.assertEqual((missing.ownership, missing.bucket_2, missing.mapped_bucket), ('Unclassified', 'Unclassified', 'Unclassified'))

    def test_admin_can_override_the_mapping_and_others_cannot(self):
        url = reverse('bsnl-bucket-mapping')
        response = self.client.put(url, {'mapping': [{'final_bucket': 'IaasP Others', 'bucket': 'Third party'}]}, content_type='application/json')
        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(common.bucket_of('IaasP Others', common.bucket_map()), 'Third party')
        pending = self.client.put(url, {'mapping': [{'final_bucket': 'IaasP Others', 'bucket': 'Pending'}]}, content_type='application/json')
        self.assertEqual(pending.status_code, 200, pending.content)
        self.assertEqual(next(row['bucket'] for row in pending.json()['mapping'] if row['final_bucket'] == 'IaasP Others'), 'Pending')
        bad = self.client.put(url, {'mapping': [{'final_bucket': 'Not a bucket', 'bucket': 'Own'}]}, content_type='application/json')
        self.assertEqual(bad.status_code, 400)
        duplicate = self.client.put(url, {'mapping': [
            {'final_bucket': 'IaasP Power', 'bucket': 'Own'}, {'final_bucket': '  iaasp   power ', 'bucket': 'Customer'},
        ]}, content_type='application/json')
        self.assertEqual(duplicate.status_code, 400)
        self.client.force_login(portal_user('noc', 'noc_lead'))
        self.assertEqual(self.client.get(url).status_code, 200)
        self.assertEqual(self.client.put(url, {'mapping': []}, content_type='application/json').status_code, 403)


class ReportCalculationTests(BsnlTestCase):
    def test_report_duration_aggregates_raw_minutes_before_rounding(self):
        frame = reports.Frame(
            sites=None, outage=np.array([0.4, 0.4]), days=np.array([1, 1]), uptime=np.array([99.0, 99.0]),
            nsla=np.array([False, False]), usd=np.array([False, False]), block=np.empty((2, 0)),
        )
        rca = [{'bucket': 'Customer', 'outage_minutes': 0.4}, {'bucket': 'Customer', 'outage_minutes': 0.4}]

        result = reports.aggregate(frame, rca=rca)

        self.assertEqual(result.outage_minutes, 0.8)
        self.assertEqual(reports._agg_json(result)['outage_minutes'], 1)
        self.assertEqual(reports._agg_json(result)['customer_minutes'], 1)

    def test_uptime_nsla_and_usd_match_the_dashboard_rules(self):
        ds = self.dataset()
        week = common.week_period(LATEST)
        f = reports.frame(ds, week, circle='MP', project=G4)
        a = reports.aggregate(f)
        expected_up = metrics.uptime_pct(7 * (60 + 10), 4 * 7)
        self.assertEqual((a.n, a.up, a.nm, a.usd), (4, expected_up, 1, 2))  # S1: 60 min/day -> 95.83% < 98.5
        self.assertAlmostEqual(a.hours, 7 * 70 / 60)
        summary = metrics.period_summary(ds, metrics.Selection(report_type=G4, circle='MP', scope=reports.SCOPE), dates=week.dates(), label='w')
        self.assertEqual(summary['uptime_pct'], a.up)
        self.assertEqual(summary['nsla_sites']['count'], a.nm)
        self.assertEqual(summary['unique_sites_down']['count'], a.usd)
        self.assertAlmostEqual(a.up, 98.7847, places=4)
        self.assertEqual(reports.status(a.up), 'Meets SLA')
        self.assertEqual(reports.status(98.5), 'Meets SLA')
        self.assertEqual(reports.status(98.0), 'Minor breach')
        self.assertEqual(reports.status(97.99), 'Breach')
        self.assertEqual(reports.status(None), 'No data')

    def test_circle_report_contains_only_its_circle_and_the_reference_sections(self):
        self.rca('UVMPS1', LATEST, 45)
        self.rca('UVKLK1', LATEST, 30)
        ds = self.dataset()
        report = reports.build(ds, 'D-1', {'code': 'MP', 'name': 'Madhya Pradesh'})
        self.assertEqual(report['subject'], 'D-1 4G Site Performance – Madhya Pradesh – 15 Nov 2026')
        self.assertEqual(report['period'], {'start': '2026-11-15', 'end': '2026-11-15', 'label': '15 Nov 2026'})
        names = [s['name'] for s in report['sheets']]
        self.assertEqual(names, ['KPI summary', 'CI ranking', 'NE performance', 'Not meeting SLA', 'RCA buckets', 'All sites'])
        all_sites = report['sheets'][-1]['rows']
        self.assertEqual({r[2] for r in all_sites[1:]}, {'MP'})
        self.assertEqual(len(all_sites) - 1, 5)  # 4 x 4G + 1 LWE of MP
        self.assertIn('Month to date', report['sheets'][0]['rows'][0])
        self.assertEqual(report['kpis']['customer_minutes'], 45)  # the MP record only
        self.assertIn('Outage Minutes', report['html'])
        self.assertNotIn('outage hours', report['html'].lower())
        self.assertIn(45, report['sheets'][0]['rows'][-1])
        self.assertIn('UVMPS1', report['html'])
        self.assertNotIn('UVKLK1', report['html'])

    def test_weekly_report_has_trends_previous_week_and_project_filter(self):
        ds = self.dataset()
        report = reports.build(ds, 'Weekly', {'code': 'MP', 'name': 'Madhya Pradesh'}, project=G4)
        self.assertEqual(report['period']['start'], '2026-11-09')
        self.assertIn('Week-wise trend', [s['name'] for s in report['sheets']])
        kpi = report['sheets'][0]['rows']
        self.assertEqual(kpi[0], ['KPI', 'This week', 'Previous week', 'Change'])
        self.assertEqual(kpi[3][0:3], ['Sites not meeting SLA', 1, 1])
        self.assertEqual(len(report['sheets'][-1]['rows']) - 1, 4)  # the LWE site is filtered out

    def test_all_india_ranks_circles_by_nsla_share(self):
        self.rca('UVMPS1', LATEST, 45)
        ds = self.dataset()
        report = reports.build(ds, 'Weekly', None)
        ranking = next(s for s in report['sheets'] if s['name'] == 'Circle ranking')['rows']
        self.assertEqual([r[2] for r in ranking[1:]], ['Kerala', 'Madhya Pradesh'])  # KL has no NSLA site
        self.assertIn('Outage Minutes', report['html'])
        self.assertIn('Outage Minutes by RCA bucket', report['html'])
        all_sites = next(s for s in report['sheets'] if s['name'] == 'All sites')
        self.assertIn('Outage Minutes', all_sites['rows'][0])

    def test_recipient_resolution_by_circle_and_report_type(self):
        self.recipient(self.mp, 'D-1', 'head.mp@example.com')
        self.recipient(self.mp, 'D-1', 'noc@example.com', 'Cc')
        self.recipient(self.mp, 'D-1', 'old@example.com', active=False)
        self.recipient(self.mp, 'Weekly', 'weekly.mp@example.com')
        self.recipient(self.kl, 'D-1', 'head.kl@example.com')
        self.recipient(None, 'All India', 'business@example.com')
        self.assertEqual(reports.recipients('MP', 'D-1'), {'to': ['head.mp@example.com'], 'cc': ['noc@example.com']})
        self.assertEqual(reports.recipients('MP', 'Weekly'), {'to': ['weekly.mp@example.com'], 'cc': []})
        self.assertEqual(reports.recipients(None, 'All India'), {'to': ['business@example.com'], 'cc': []})
        report = reports.build(self.dataset(), 'D-1', None)
        self.assertEqual(report['to'], ['business@example.com'])

    def test_overview_lists_circles_with_status_and_recipients(self):
        self.recipient(self.mp, 'D-1', 'head.mp@example.com')
        data = self.client.get(reverse('bsnl-report-overview'), {'type': 'D-1'}).json()
        self.assertEqual(data['period']['start'], '2026-11-15')
        mp = next(r for r in data['circles'] if r['circle'] == 'MP')
        self.assertEqual((mp['sites'], mp['not_meeting_sla'], mp['to'], mp['can_send']), (5, 2, ['head.mp@example.com'], True))
        self.assertEqual(self.client.get(reverse('bsnl-report-overview'), {'type': 'Monthly'}).status_code, 400)


class ReportExportTests(BsnlTestCase):
    def test_preview_eml_xlsx_and_all_circle_zip(self):
        self.recipient(self.mp, 'Weekly', 'head.mp@example.com')
        self.recipient(self.mp, 'Weekly', 'noc@example.com', 'Cc')
        params = {'type': 'Weekly', 'circle': 'MP'}
        preview = self.client.get(reverse('bsnl-report-preview'), params).json()
        self.assertEqual((preview['to'], preview['cc']), (['head.mp@example.com'], ['noc@example.com']))
        self.assertTrue(preview['attachment'].endswith('.xlsx'))
        self.assertEqual(preview['sheet_count'], len(preview['sheets']))

        eml = self.client.get(reverse('bsnl-report-download'), {**params, 'file': 'eml'})
        self.assertEqual(eml.status_code, 200)
        message = email.message_from_bytes(eml.content, policy=email.policy.default)
        self.assertEqual(message['To'], 'head.mp@example.com')
        self.assertEqual(message['X-Unsent'], '1')
        self.assertEqual(message['Subject'], preview['subject'])
        body = message.get_body(preferencelist=('html',)).get_content()
        self.assertIn('Outage Minutes', body)
        self.assertNotIn('outage hours', body.lower())
        attachments = [p.get_filename() for p in message.walk() if p.get_filename()]
        self.assertEqual(attachments, [preview['attachment']])

        xlsx = self.client.get(reverse('bsnl-report-download'), {**params, 'file': 'xlsx'})
        book = load_workbook(io.BytesIO(xlsx.content))
        self.assertEqual(book.sheetnames, preview['sheets'])
        all_sites = book['All sites']
        headers = [cell.value for cell in all_sites[1]]
        minute_column = headers.index('Outage Minutes') + 1
        self.assertIsInstance(all_sites.cell(row=2, column=minute_column).value, int)
        self.assertEqual(all_sites.cell(row=2, column=minute_column).number_format, '#,##,##0')

        bundle = self.client.get(reverse('bsnl-report-download-all'), {'type': 'Weekly'})
        self.assertEqual(bundle.status_code, 200)
        names = zipfile.ZipFile(io.BytesIO(bundle.content)).namelist()
        self.assertEqual(len(names), 2)  # one .eml per circle (KL, MP)
        self.assertTrue(all(n.endswith('.eml') for n in names))
        self.assertEqual(ReportRun.objects.count(), 0)  # downloads never send

    def test_manual_send_is_blocked_unless_enabled_and_records_success_and_failure(self):
        self.recipient(self.mp, 'D-1', 'head.mp@example.com')
        url, body = reverse('bsnl-report-send'), {'type': 'D-1', 'circle': 'MP'}
        self.assertEqual(self.client.post(url, body, content_type='application/json').status_code, 409)  # flag off
        with patch.dict(os.environ, SEND_ON), account_ok(), mail_ok() as send:
            ok = self.client.post(url, body, content_type='application/json')
        self.assertEqual(ok.status_code, 200, ok.content)
        self.assertEqual(send.call_args.args[1].to, ['head.mp@example.com'])
        self.assertEqual(send.call_args.args[1].files[0][0], ok.json()['run']['attachment'])
        with patch.dict(os.environ, SEND_ON), account_ok(), patch('apps.bsnl.delivery.mailer.send', side_effect=MailError('SMTP down')):
            failed = self.client.post(url, body, content_type='application/json')
        self.assertEqual(failed.status_code, 502)
        self.assertEqual(list(ReportRun.objects.order_by('id').values_list('status', 'error')), [('sent', ''), ('failed', 'SMTP down')])
        runs = self.client.get(reverse('bsnl-report-runs')).json()['runs']
        self.assertEqual(len(runs), 2)


class SchedulerTests(BsnlTestCase):
    def at(self, *args):
        return datetime(*args, tzinfo=IST)

    def enable(self, daily=True, weekly=True):
        Setting.put(scheduler.SETTING, {'daily': daily, 'weekly': weekly})

    def test_nothing_runs_when_disabled_before_time_or_without_the_server_flag(self):
        self.recipient(self.mp, 'D-1', 'head.mp@example.com')
        ds = self.dataset()
        with patch.dict(os.environ, SEND_ON), account_ok(), mail_ok() as send:
            self.assertEqual(scheduler.tick(self.at(2026, 11, 16, 9, 30), dataset=ds, force=True), {'sent': 0, 'failed': 0, 'skipped': 0})
            self.enable()
            scheduler.tick(self.at(2026, 11, 16, 8, 59), dataset=ds, force=True)  # before 09:00 IST
        with account_ok(), mail_ok() as send_off:
            scheduler.tick(self.at(2026, 11, 16, 9, 30), dataset=ds, force=True)  # server flag off
        self.assertFalse(send.called or send_off.called)
        self.assertEqual(ReportRun.objects.count(), 0)

    def test_daily_and_weekly_send_once_per_circle_and_period_with_mocked_delivery(self):
        self.recipient(self.mp, 'D-1', 'head.mp@example.com')
        self.recipient(self.kl, 'D-1', 'head.kl@example.com')
        self.recipient(None, 'All India', 'business@example.com')
        self.recipient(self.mp, 'Weekly', 'weekly.mp@example.com')
        self.enable()
        ds = self.dataset()
        monday = self.at(2026, 11, 16, 10, 5)
        with patch.dict(os.environ, SEND_ON), account_ok(), mail_ok() as send:
            first = scheduler.tick(monday, dataset=ds, force=True)
            again = scheduler.tick(monday + timedelta(minutes=30), dataset=ds, force=True)
        self.assertEqual(first, {'sent': 5, 'failed': 0, 'skipped': 1})  # D-1: All India, KL, MP; Weekly: MP sent, KL & All India no To
        self.assertEqual(again, {'sent': 0, 'failed': 0, 'skipped': 0})
        self.assertEqual(send.call_count, 5)
        slots = set(ReportRun.objects.values_list('slot_key', flat=True))
        self.assertIn('D-1|MP|2026-11-15', slots)
        self.assertIn('Weekly|MP|2026-11-09', slots)
        self.assertTrue(all(r.trigger == 'schedule' for r in ReportRun.objects.all()))

    def test_weekly_waits_for_monday_ten_and_failures_are_recorded(self):
        self.recipient(self.mp, 'Weekly', 'weekly.mp@example.com')
        self.enable(daily=False)
        ds = self.dataset()
        with patch.dict(os.environ, SEND_ON), account_ok(), patch('apps.bsnl.delivery.mailer.send', side_effect=MailError('refused')):
            scheduler.tick(self.at(2026, 11, 16, 9, 59), dataset=ds, force=True)
            self.assertEqual(ReportRun.objects.count(), 0)
            scheduler.tick(self.at(2026, 11, 16, 10, 0), dataset=ds, force=True)
        run = ReportRun.objects.get(circle=self.mp)
        self.assertEqual((run.status, run.error, run.report_type), ('failed', 'refused', 'Weekly'))

    def test_inactive_email_account_fails_safely(self):
        self.recipient(self.mp, 'D-1', 'head.mp@example.com')
        self.enable(weekly=False)
        with patch.dict(os.environ, SEND_ON):
            scheduler.tick(self.at(2026, 11, 16, 9, 30), dataset=self.dataset(), force=True)
        run = ReportRun.objects.get(circle=self.mp)
        self.assertEqual(run.status, 'failed')
        self.assertIn('account', run.error.lower())


class LetterDataTests(BsnlTestCase):
    def test_only_customer_bucket_records_of_the_period_circle_and_project(self):
        self.rca('UVMPS1', date(2026, 11, 10), 90)
        self.rca('UVMPS2', date(2026, 11, 9), 30, final='BSNL Media', sub='BSNL Link', text='BSNL link down')
        self.rca('UVMPS3', date(2026, 11, 10), 60, final='IaasP Power', sub='EB power cut')  # Own bucket
        self.rca('UVMPS4', date(2026, 11, 8), 60)  # before the period
        self.rca('UVMPS4', date(2026, 11, 16), 60)  # after the period
        self.rca('UVKLK1', date(2026, 11, 10), 60)  # another circle
        self.rca('LWEMPL1', date(2026, 11, 11), 120)
        withdrawn = self.rca('UVMPS4', date(2026, 11, 12), 60)
        RcaRecord.all_objects.filter(pk=withdrawn.pk).update(withdrawn_at=datetime(2026, 11, 13, tzinfo=IST))
        week = Period(date(2026, 11, 9), date(2026, 11, 15))
        rows = letters.cust_outages('MP', week)
        self.assertEqual([(r['site_id'], r['start'], r['outage_minutes'], r['hours']) for r in rows],
                         [('UVMPS2', '2026-11-09', 30.0, 0.5), ('UVMPS1', '2026-11-10', 90.0, 1.5),
                          ('LWEMPL1', '2026-11-11', 120.0, 2.0)])
        self.assertEqual(rows[1]['cluster'], 'CI One')
        self.assertEqual(rows[1]['ne'], 'NE A')
        self.assertEqual(rows[1]['start'], rows[1]['end'])  # day-level: the reporting date is the period of the duration
        self.assertEqual(letters.summary(rows), {'outages': 3, 'sites': 3, 'outage_minutes': 240, 'hours': 4.0})
        self.assertEqual([r['site_id'] for r in letters.cust_outages('MP', week, project=G4)], ['UVMPS2', 'UVMPS1'])
        self.assertEqual(letters.causes(rows)[0]['cause'], 'SSA OFC')

    def test_ticket_number_is_taken_from_a_matching_ofc_ticket(self):
        self.rca('UVMPS1', date(2026, 11, 10), 90)
        site = self.sites['UVMPS1']
        Ticket.objects.create(portal_ticket_id='OFC-2026-00077', outage_date=date(2026, 11, 10), project=G4, circle='MP', site_id='UVMPS1',
                              site_key=site.site_key, actual_down_time=datetime(2026, 11, 10, 2, tzinfo=IST), email_id='t@example.com',
                              last_uploaded_at=datetime(2026, 11, 10, 3, tzinfo=IST))
        rows = letters.cust_outages('MP', Period(date(2026, 11, 9), date(2026, 11, 15)))
        self.assertEqual(rows[0]['ticket'], 'OFC-2026-00077')

    def test_reference_numbers_are_unique_per_circle_and_month(self):
        nov = Period(date(2026, 11, 9), date(2026, 11, 15))
        refs = [letters.next_reference(self.mp, nov) for _ in range(3)]
        self.assertEqual(refs, ['MP/BSNL/202611/001', 'MP/BSNL/202611/002', 'MP/BSNL/202611/003'])
        self.assertEqual(letters.next_reference(self.kl, nov), 'KL/BSNL/202611/001')
        self.assertEqual(letters.next_reference(self.mp, Period(date(2026, 12, 1), date(2026, 12, 1))), 'MP/BSNL/202612/001')

    def test_letter_html_uses_the_circle_profile_and_escapes_values(self):
        CircleLetterProfile.objects.create(circle=self.mp, bsnl_designation='The General Manager (Operations)',
                                           bsnl_address='Bhopal <HQ>\nMP', sender_name='A. Sender', sender_designation='Circle Head', company='Vendor Co')
        self.rca('UVMPS1', date(2026, 11, 10), 90, text='<script>x</script>')
        rows = letters.cust_outages('MP', Period(date(2026, 11, 9), date(2026, 11, 15)))
        html = letters.letter_html(self.mp, Period(date(2026, 11, 9), date(2026, 11, 15)), rows, 'MP/BSNL/202611/001', date(2026, 11, 17))
        for text in ('Ref: <b>MP/BSNL/202611/001</b>', 'Date: 17 Nov 2026', 'The General Manager (Operations)', 'Bhopal &lt;HQ&gt;<br>MP',
                     'Madhya Pradesh Circle – 9 Nov 2026 to 15 Nov 2026', '<b>1</b> outages at <b>1</b> 4G sites',
                     '<b>90 Outage Minutes</b>', '<th style="border:1px solid #999;padding:4px 8px;background:#eee;text-align:right">Outage Minutes</th>',
                     'A. Sender<br>Circle Head<br>Vendor Co', 'Encl.: Annexure – outage details (1 rows)'):
            self.assertIn(text, html)
        self.assertNotIn('hours', html.lower())
        annex = letters.annexure_html(rows)
        self.assertIn('&lt;script&gt;', annex)
        self.assertNotIn('<script>', annex)
        self.assertIn('Outage Minutes', annex)
        self.assertIn('90', annex)
        no_profile = letters.letter_html(self.kl, Period(date(2026, 11, 9), date(2026, 11, 15)), [], 'KL/1', date(2026, 11, 17))
        self.assertIn('[BSNL designation]', no_profile)


class LetterWorkflowTests(BsnlTestCase):
    def setUp(self):
        super().setUp()
        self.rca('UVMPS1', date(2026, 11, 10), 90)
        self.rca('LWEMPL1', date(2026, 11, 11), 60)
        self.recipient(self.mp, 'BSNL letter', 'gm.mp@example.com')
        self.recipient(self.mp, 'BSNL letter', 'head.mp@example.com', 'Cc')
        self.body = {'circle': 'MP', 'period': 'period', 'date_from': '2026-11-09', 'date_to': '2026-11-15'}

    def open(self, **extra):
        return self.client.post(reverse('bsnl-letter-open'), {**self.body, **extra}, content_type='application/json')

    def test_open_persists_one_draft_per_circle_period_and_category(self):
        first = self.open()
        self.assertEqual(first.status_code, 201, first.content)
        letter = first.json()['letter']
        self.assertEqual((letter['reference'], letter['status'], letter['outage_count'], letter['total_hours'], letter['total_minutes']),
                         ('MP/BSNL/202611/001', 'Draft', 2, 2.5, 150))
        self.assertEqual(letter['annexure'][0]['outage_minutes'], 90)
        self.assertEqual(letter['causes'][0]['outage_minutes'], 150)
        self.assertNotIn('hours', letter['html'].lower())
        self.assertEqual(letter['recipients'], {'to': ['gm.mp@example.com'], 'cc': ['head.mp@example.com']})
        again = self.open()
        self.assertEqual((again.status_code, again.json()['letter']['id']), (200, letter['id']))
        self.assertEqual(self.open(project=G4).json()['letter']['reference'], 'MP/BSNL/202611/002')
        none = self.client.post(reverse('bsnl-letter-open'), {**self.body, 'circle': 'KL'}, content_type='application/json')
        self.assertEqual(none.status_code, 400)
        self.assertEqual(BsnlLetter.objects.count(), 2)

    def test_historical_letter_keeps_mapping_snapshot_and_draft_regeneration_uses_current_mapping(self):
        historical = self.open().json()['letter']
        historical_id = historical['id']
        self.assertEqual(historical['annexure'][0]['bucket'], 'Customer')
        self.client.post(reverse('bsnl-letter-approve', args=[historical_id]))
        status_url = reverse('bsnl-letter-status', args=[historical_id])
        self.client.post(status_url, {'status': 'Sent', 'note': 'Sent outside the portal'}, content_type='application/json')
        self.client.post(status_url, {'status': 'Acknowledged'}, content_type='application/json')

        draft = self.open(project=G4).json()['letter']
        self.assertEqual(draft['annexure'][0]['bucket'], 'Customer')
        RcaBucketMapping.objects.filter(final_bucket='BSNL OFC').update(bucket='Pending', updated_by=self.admin)

        saved = self.client.get(reverse('bsnl-letter-detail', args=[historical_id])).json()['letter']
        self.assertEqual((saved['status'], saved['annexure'][0]['bucket']), ('Acknowledged', 'Customer'))
        regenerated = self.client.post(reverse('bsnl-letter-regenerate', args=[draft['id']])).json()['letter']
        self.assertEqual((regenerated['status'], regenerated['annexure'], regenerated['outage_count']), ('Draft', [], 0))

    def test_legacy_generated_letter_content_is_displayed_in_minutes_without_rewriting_it(self):
        created = self.open().json()['letter']
        letter = BsnlLetter.objects.get(pk=created['id'])
        legacy_rows = [{key: value for key, value in row.items() if key != 'outage_minutes'} for row in letter.annexure]
        letter.annexure = legacy_rows
        letter.generated_html = '<p>2.50 hours</p>'
        letter.save(update_fields=['annexure', 'generated_html'])
        event = letter.events.get(action='generated')
        LetterEvent.objects.filter(pk=event.pk).update(note='2 outages, 2.50 hours')

        detail = self.client.get(reverse('bsnl-letter-detail', args=[letter.pk])).json()['letter']

        self.assertIn('150 Outage Minutes', detail['html'])
        self.assertNotIn('hours', detail['html'].lower())
        self.assertEqual(detail['events'][0]['note'], '2 outages, 150 Outage Minutes')
        self.assertEqual(BsnlLetter.objects.get(pk=letter.pk).generated_html, '<p>2.50 hours</p>')
        word = self.client.get(reverse('bsnl-letter-download', args=[letter.pk, 'doc']))
        self.assertIn(b'150 Outage Minutes', word.content)
        self.assertNotIn(b'hours', word.content.lower())
        bad = self.client.post(reverse('bsnl-letter-open'), {**self.body, 'date_from': '2026-11-15', 'date_to': '2026-11-09'}, content_type='application/json')
        self.assertEqual(bad.status_code, 400)

    def test_editing_is_saved_sanitised_and_kept_apart_from_the_generated_letter(self):
        letter_id = self.open().json()['letter']['id']
        url = reverse('bsnl-letter-content', args=[letter_id])
        saved = self.client.put(url, {'html': '<p onclick="x()">Revised <b>text</b><script>alert(1)</script><img src=x></p>'},
                                content_type='application/json')
        self.assertEqual(saved.status_code, 200, saved.content)
        data = saved.json()['letter']
        self.assertEqual(data['html'], '<p>Revised <b>text</b></p>')
        self.assertTrue(data['edited'])
        self.assertIn('Subject: Site outages attributable to BSNL', data['generated_html'])
        letter = BsnlLetter.objects.get(pk=letter_id)
        self.assertEqual(letter.current_html, '<p>Revised <b>text</b></p>')
        self.assertIn('<p>Revised <b>text</b></p>', letters.doc_html(letter))
        self.assertEqual(self.client.put(url, {'html': '<script>only</script>'}, content_type='application/json').status_code, 400)
        regenerated = self.client.post(reverse('bsnl-letter-regenerate', args=[letter_id])).json()['letter']
        self.assertFalse(regenerated['edited'])
        self.assertEqual([e['action'] for e in regenerated['events']], ['generated', 'edited', 'regenerated'])

    def test_approval_status_history_and_eml_download(self):
        letter_id = self.open().json()['letter']['id']
        eml_url = reverse('bsnl-letter-download', args=[letter_id, 'eml'])
        self.assertEqual(self.client.get(eml_url).status_code, 409)  # Draft: approve first
        approved = self.client.post(reverse('bsnl-letter-approve', args=[letter_id])).json()['letter']
        self.assertEqual((approved['status'], approved['approved_by']), ('Approved', 'bsnl-admin'))
        self.assertIsNotNone(approved['approved_at'])
        self.assertEqual(self.client.put(reverse('bsnl-letter-content', args=[letter_id]), {'html': '<p>x</p>'},
                                         content_type='application/json').status_code, 409)
        eml = self.client.get(eml_url)
        self.assertEqual(eml.status_code, 200)
        message = email.message_from_bytes(eml.content, policy=email.policy.default)
        self.assertEqual((message['To'], message['Cc']), ('gm.mp@example.com', 'head.mp@example.com'))
        self.assertIn('(Ref MP/BSNL/202611/001)', message['Subject'])
        self.assertEqual(sorted(p.get_filename() for p in message.walk() if p.get_filename()),
                         ['Annexure_MP_BSNL_202611_001.xlsx', 'MP_BSNL_202611_001.doc'])
        self.assertEqual(BsnlLetter.objects.get(pk=letter_id).status, 'Approved')  # downloading never marks it sent

        status_url = reverse('bsnl-letter-status', args=[letter_id])
        self.assertEqual(self.client.post(status_url, {'status': 'Acknowledged'}, content_type='application/json').status_code, 409)
        self.assertEqual(self.client.post(status_url, {'status': 'Sent'}, content_type='application/json').status_code, 400)  # note required
        sent = self.client.post(status_url, {'status': 'Sent', 'note': 'Sent from Outlook'}, content_type='application/json').json()['letter']
        self.assertEqual(sent['status'], 'Sent')
        for target in ('Acknowledged', 'Exclusion accepted'):
            self.assertEqual(self.client.post(status_url, {'status': target}, content_type='application/json').status_code, 200)
        self.assertEqual(self.client.post(status_url, {'status': 'Draft'}, content_type='application/json').status_code, 409)
        history = list(LetterEvent.objects.filter(letter_id=letter_id).values_list('status_before', 'status_after'))
        self.assertEqual(history, [('', 'Draft'), ('Draft', 'Approved'), ('Approved', 'Sent'), ('Sent', 'Acknowledged'),
                                   ('Acknowledged', 'Exclusion accepted')])

    def test_send_requires_the_server_flag_and_failures_keep_the_letter_approved(self):
        letter_id = self.open().json()['letter']['id']
        send_url = reverse('bsnl-letter-send', args=[letter_id])
        self.assertEqual(self.client.post(send_url).status_code, 409)  # Draft
        self.client.post(reverse('bsnl-letter-approve', args=[letter_id]))
        self.assertEqual(self.client.post(send_url).status_code, 409)  # sending disabled on the server
        with patch.dict(os.environ, SEND_ON), account_ok(), patch('apps.bsnl.delivery.mailer.send', side_effect=MailError('mailbox full')):
            failed = self.client.post(send_url).json()['letter']
        self.assertEqual((failed['status'], failed['send_status'], failed['send_error']), ('Approved', 'failed', 'mailbox full'))
        with patch.dict(os.environ, SEND_ON), account_ok(), mail_ok() as send:
            sent = self.client.post(send_url).json()['letter']
        self.assertEqual((sent['status'], sent['send_status']), ('Sent', 'sent'))
        outgoing = send.call_args.args[1]
        self.assertEqual((outgoing.to, outgoing.cc), (['gm.mp@example.com'], ['head.mp@example.com']))
        self.assertEqual([f[0] for f in outgoing.files], ['MP_BSNL_202611_001.doc', 'Annexure_MP_BSNL_202611_001.xlsx'])
        self.assertEqual(send.call_count, 1)

    def test_word_excel_print_and_register_exports(self):
        letter_id = self.open().json()['letter']['id']
        doc = self.client.get(reverse('bsnl-letter-download', args=[letter_id, 'doc']))
        self.assertIn(b'urn:schemas-microsoft-com:office:word', doc.content)
        self.assertIn(b'Annexure', doc.content)
        self.assertIn(b'Outage Minutes', doc.content)
        self.assertNotIn(b'hours', doc.content.lower())
        sheet = load_workbook(io.BytesIO(self.client.get(reverse('bsnl-letter-download', args=[letter_id, 'xlsx'])).content))['Annexure']
        rows = list(sheet.values)
        self.assertEqual(list(rows[0]), letters.ANNEX_XLSX_HEADERS)
        self.assertEqual(rows[1][1:4], ('UVMPS1', 'UVMPS1', 'MP'))
        self.assertEqual(rows[1][8], 90)
        self.assertEqual(sheet.cell(row=2, column=9).number_format, '#,##,##0')
        printable = self.client.get(reverse('bsnl-letter-download', args=[letter_id, 'html']))
        self.assertEqual(printable['Content-Security-Policy'], "default-src 'none'; style-src 'unsafe-inline'")
        self.assertIn(b'Outage Minutes', printable.content)
        self.assertNotIn(b'hours', printable.content.lower())
        register = load_workbook(io.BytesIO(self.client.get(reverse('bsnl-letter-register')).content))['Register']
        register_rows = list(register.values)
        self.assertEqual(register_rows[0][4], 'Outage Minutes')
        self.assertEqual(register_rows[1][0], 'MP/BSNL/202611/001')
        self.assertEqual(register_rows[1][4], 150)
        self.assertEqual(register.cell(row=2, column=5).number_format, '#,##,##0')

    def test_overview_lists_circles_and_the_register(self):
        self.open()
        data = self.client.get(reverse('bsnl-letter-overview'), {'period': 'period', 'date_from': '2026-11-09', 'date_to': '2026-11-15'}).json()
        mp = next(r for r in data['circles'] if r['circle'] == 'MP')
        self.assertEqual((mp['outages'], mp['sites'], mp['hours'], mp['outage_minutes'], mp['to']),
                         (2, 2, 2.5, 150, ['gm.mp@example.com']))
        self.assertEqual(mp['letter']['reference'], 'MP/BSNL/202611/001')
        self.assertEqual(len(data['register']), 1)
        d1 = self.client.get(reverse('bsnl-letter-overview'), {'period': 'd1'}).json()
        self.assertEqual(d1['period']['start'], '2026-11-11')  # latest RCA reporting date


class PermissionTests(BsnlTestCase):
    def setUp(self):
        super().setUp()
        self.rca('UVMPS1', date(2026, 11, 10), 90)
        self.rca('UVKLK1', date(2026, 11, 10), 90)
        self.body = {'circle': 'MP', 'period': 'period', 'date_from': '2026-11-09', 'date_to': '2026-11-15'}

    def test_signed_out_and_unpermitted_users_get_nothing(self):
        self.client.logout()
        for name in ('bsnl-report-options', 'bsnl-report-overview', 'bsnl-letter-overview', 'bsnl-recipients'):
            self.assertIn(self.client.get(reverse(name)).status_code, (401, 403))
        self.client.force_login(portal_user('nobody', role=None))
        self.assertEqual(self.client.get(reverse('bsnl-report-overview'), {'type': 'D-1'}).status_code, 403)
        self.assertEqual(self.client.get(reverse('bsnl-letter-overview'), {'period': 'd1'}).status_code, 403)
        self.assertEqual(self.client.get(reverse('bsnl-recipients')).status_code, 403)

    def test_circle_scoped_viewer_sees_only_their_circle_and_cannot_change_anything(self):
        viewer = self.scoped('mp-viewer', [('bsnl_reports', 'view'), ('bsnl_letters', 'view')], [(G4, 'MP'), (LWE, 'MP')])
        self.client.force_login(viewer)
        overview = self.client.get(reverse('bsnl-report-overview'), {'type': 'D-1'}).json()
        self.assertEqual([r['circle'] for r in overview['circles']], ['MP'])
        self.assertEqual(self.client.get(reverse('bsnl-report-preview'), {'type': 'D-1', 'circle': 'KL'}).status_code, 404)
        self.assertEqual(self.client.get(reverse('bsnl-report-preview'), {'type': 'D-1'}).status_code, 403)  # All India
        self.assertEqual(self.client.get(reverse('bsnl-report-preview'), {'type': 'D-1', 'circle': 'MP'}).status_code, 200)
        self.assertEqual(self.client.post(reverse('bsnl-report-send'), {'type': 'D-1', 'circle': 'MP'}, content_type='application/json').status_code, 409)
        with patch.dict(os.environ, SEND_ON):
            self.assertEqual(self.client.post(reverse('bsnl-report-send'), {'type': 'D-1', 'circle': 'MP'}, content_type='application/json').status_code, 403)
        letters_view = self.client.get(reverse('bsnl-letter-overview'), {'period': 'period', 'date_from': '2026-11-09', 'date_to': '2026-11-15'}).json()
        self.assertEqual([r['circle'] for r in letters_view['circles']], ['MP'])
        self.assertEqual(self.client.post(reverse('bsnl-letter-open'), self.body, content_type='application/json').status_code, 403)  # no Edit
        self.client.force_login(self.admin)
        kl = self.client.post(reverse('bsnl-letter-open'), {**self.body, 'circle': 'KL'}, content_type='application/json').json()['letter']
        mp = self.client.post(reverse('bsnl-letter-open'), self.body, content_type='application/json').json()['letter']
        self.client.force_login(viewer)
        self.assertEqual(self.client.get(reverse('bsnl-letter-detail', args=[kl['id']])).status_code, 404)  # another circle by URL
        self.assertEqual(self.client.get(reverse('bsnl-letter-download', args=[kl['id'], 'doc'])).status_code, 404)
        self.assertEqual(self.client.get(reverse('bsnl-letter-detail', args=[mp['id']])).status_code, 200)
        for name in ('bsnl-letter-approve', 'bsnl-letter-regenerate', 'bsnl-letter-send'):
            self.assertEqual(self.client.post(reverse(name, args=[mp['id']])).status_code, 403, name)
        self.assertEqual(self.client.put(reverse('bsnl-letter-content', args=[mp['id']]), {'html': '<p>x</p>'}, content_type='application/json').status_code, 403)
        self.assertEqual(self.client.post(reverse('bsnl-recipients'), {'circle': 'MP', 'report_type': 'D-1', 'name': 'x', 'email': 'x@example.com',
                                                                      'kind': 'To'}, content_type='application/json').status_code, 403)
        self.assertEqual([r['reference'] for r in self.client.get(reverse('bsnl-letter-overview'), {'period': 'd1'}).json()['register']],
                         [mp['reference']])

    def test_partial_circle_access_cannot_create_a_whole_circle_letter(self):
        editor = self.scoped('mp-4g-editor', [('bsnl_letters', 'view'), ('bsnl_letters', 'edit')], [(G4, 'MP')])
        self.client.force_login(editor)
        self.assertEqual(self.client.post(reverse('bsnl-letter-open'), self.body, content_type='application/json').status_code, 403)
        own = self.client.post(reverse('bsnl-letter-open'), {**self.body, 'project': G4}, content_type='application/json')
        self.assertEqual(own.status_code, 201, own.content)
        letter_id = own.json()['letter']['id']
        self.assertEqual(self.client.post(reverse('bsnl-letter-approve', args=[letter_id])).status_code, 403)  # no Approve

    def test_noc_lead_views_and_drafts_but_cannot_approve_or_manage(self):
        self.client.force_login(portal_user('noc-lead', 'noc_lead'))
        opened = self.client.post(reverse('bsnl-letter-open'), self.body, content_type='application/json')
        self.assertEqual(opened.status_code, 201)
        letter_id = opened.json()['letter']['id']
        self.assertEqual(self.client.post(reverse('bsnl-letter-approve', args=[letter_id])).status_code, 403)
        self.assertEqual(self.client.put(reverse('bsnl-report-schedule'), {'daily': True, 'weekly': False}, content_type='application/json').status_code, 403)
        self.assertEqual(self.client.put(reverse('bsnl-letter-profile-detail', args=['MP']), {'bsnl_designation': 'GM', 'bsnl_address': '',
                                         'sender_name': '', 'sender_designation': '', 'company': ''}, content_type='application/json').status_code, 403)


class DistributionMasterTests(BsnlTestCase):
    def test_validates_emails_prevents_duplicates_and_deactivates(self):
        url = reverse('bsnl-recipients')
        row = {'circle': 'MP', 'report_type': 'D-1', 'name': 'Circle Head', 'designation': 'Head', 'email': 'Head.MP@Example.com', 'kind': 'To'}
        created = self.client.post(url, row, content_type='application/json')
        self.assertEqual(created.status_code, 200, created.content)
        self.assertEqual(created.json()['recipient']['email'], 'head.mp@example.com')
        self.assertEqual(self.client.post(url, {**row, 'email': 'head.mp@example.com'}, content_type='application/json').status_code, 400)
        self.assertEqual(self.client.post(url, {**row, 'email': 'not-an-email'}, content_type='application/json').status_code, 400)
        self.assertEqual(self.client.post(url, {**row, 'circle': ''}, content_type='application/json').status_code, 400)
        self.assertEqual(self.client.post(url, {**row, 'report_type': 'All India'}, content_type='application/json').status_code, 400)
        self.assertEqual(self.client.post(url, {**row, 'report_type': 'All India', 'circle': ''}, content_type='application/json').status_code, 200)
        rid = created.json()['recipient']['id']
        off = self.client.put(reverse('bsnl-recipient-detail', args=[rid]), {**row, 'is_active': False}, content_type='application/json')
        self.assertFalse(off.json()['recipient']['is_active'])
        self.assertEqual(reports.recipients('MP', 'D-1'), {'to': [], 'cc': []})

    def test_profiles_are_saved_per_circle(self):
        data = {'bsnl_designation': 'The General Manager (Operations)', 'bsnl_address': 'Bhopal', 'sender_name': 'Head',
                'sender_designation': 'Circle Head – MP', 'company': 'Vendor'}
        self.assertEqual(self.client.put(reverse('bsnl-letter-profile-detail', args=['MP']), data, content_type='application/json').status_code, 200)
        self.assertEqual(CircleLetterProfile.objects.get(circle=self.mp).sender_name, 'Head')
        listed = {p['circle']: p for p in self.client.get(reverse('bsnl-letter-profiles')).json()['profiles']}
        self.assertEqual(listed['MP']['bsnl_address'], 'Bhopal')
        self.assertEqual(listed['KL']['bsnl_address'], '')


class SanitizerTests(TestCase):
    def test_only_formatting_markup_survives(self):
        dirty = ('<p style="color:red" onclick="steal()">A <a href="javascript:x">link</a><img src=x onerror=y>'
                 '<span style="background:url(http://x)">b</span><table><tr><td colspan="2">c</td></tr></table>'
                 '<style>p{}</style><iframe src="x"></iframe><b>bold')
        self.assertEqual(documents.sanitize(dirty),
                         '<p style="color:red">A link<span>b</span><table><tr><td colspan="2">c</td></tr></table><b>bold</b></p>')
