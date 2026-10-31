"""Alert & Email Automation: account security, schedules, reminders from the real trackers, upload-failure events,
attachments and scope, history, retry, duplicate prevention, worker recovery and permissions.

SMTP is mocked (Django's locmem backend or a raising stub): no email leaves the machine. Synthetic records only.
"""
import smtplib
import tempfile
from datetime import date, datetime, time, timedelta
from pathlib import Path
from unittest import mock
from zoneinfo import ZoneInfo

from django.core import mail
from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.mail.backends.locmem import EmailBackend as LocmemBackend
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from apps.accounts.scope import set_pairs
from apps.alerts import engine, mailer
from apps.alerts.models import Automation, EmailAccount, Execution, Message
from apps.alerts.schedule import next_run
from apps.rca import cycles
from apps.rca.models import RcaImportBatch
from apps.uptimedb.models import DataImportBatch, SiteDailyPerformance, UptimeSite
from tests.auth_helpers import portal_user

IST = ZoneInfo('Asia/Kolkata')


class Failing:
    """An SMTP connection the server refuses."""
    def __init__(self, *a, **k):
        pass

    def open(self):
        raise smtplib.SMTPAuthenticationError(535, b'5.7.3 Authentication unsuccessful')

    def send_messages(self, messages):
        raise smtplib.SMTPRecipientsRefused({'x@y.z': (550, b'mailbox unavailable')})

    def close(self):
        pass


def locmem(account):
    return LocmemBackend()


@override_settings()
class AlertTestCase(TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        o = override_settings(DATA_DIR=Path(self._tmp.name))
        o.enable()
        self.addCleanup(o.disable)
        self.admin = portal_user('al-admin', 'admin')
        self.admin.email = 'admin@bsnl.example'
        self.admin.save()
        self.client.force_login(self.admin)
        p = mock.patch('apps.alerts.mailer.connection', locmem)
        p.start()
        self.addCleanup(p.stop)

    def account(self, active=True):
        return EmailAccount.objects.create(name='Portal', host='smtp.example', port=587, username='portal', password_encrypted=mailer.encrypt('s3cret'),
                                           from_email='portal@bsnl.example', is_active=active, tested_ok_at=timezone.now() if active else None)

    def automation(self, **kw):
        a = Automation.objects.create(**{'name': 'Auto', 'kind': 'custom', 'frequency': 'daily', 'run_time': time(9), 'template': 'report', **kw})
        return a


class AccountTests(AlertTestCase):
    def test_password_is_encrypted_never_returned_and_a_changed_connection_needs_a_new_test(self):
        body = {'name': 'Portal', 'host': 'smtp.office365.com', 'port': 587, 'security': 'starttls', 'auth': 'password', 'username': 'portal@bsnl.example',
                'password': 'Pa55-word', 'from_email': 'portal@bsnl.example', 'from_name': 'BSNL Portal', 'reply_to': '', 'timeout': 20}
        data = self.client.put(reverse('alert-account'), body, content_type='application/json').json()['account']
        self.assertTrue(data['password_set'])
        self.assertNotIn('Pa55-word', str(data))
        stored = EmailAccount.objects.get()
        self.assertNotIn('Pa55-word', stored.password_encrypted)
        self.assertEqual(mailer.decrypt(stored.password_encrypted), 'Pa55-word')
        self.assertEqual(self.client.post(reverse('alert-account-activate'), {'active': True}, content_type='application/json').status_code, 400)
        ok = self.client.post(reverse('alert-account-test'), {'to': 'me@bsnl.example'}, content_type='application/json')
        self.assertEqual((ok.status_code, len(mail.outbox), mail.outbox[0].to), (200, 1, ['me@bsnl.example']))
        self.assertTrue(self.client.post(reverse('alert-account-activate'), {'active': True}, content_type='application/json').json()['account']['is_active'])
        body.update(host='smtp.other.example', password='')  # blank password keeps the stored one
        data = self.client.put(reverse('alert-account'), body, content_type='application/json').json()['account']
        self.assertEqual((data['is_active'], data['tested_ok_at']), (False, None))
        self.assertEqual(mailer.decrypt(EmailAccount.objects.get().password_encrypted), 'Pa55-word')

    def test_a_failed_test_shows_the_server_reason_without_the_password(self):
        self.account(active=False)
        with mock.patch('apps.alerts.mailer.connection', lambda a: Failing()):
            r = self.client.post(reverse('alert-account-test'), {}, content_type='application/json')
        self.assertEqual(r.status_code, 502)
        self.assertIn('Authentication unsuccessful', r.json()['message'])
        self.assertNotIn('s3cret', r.json()['message'])


class ScheduleTests(AlertTestCase):
    def test_daily_weekly_monthly_once_and_end_date(self):
        now = datetime(2026, 10, 31, 10, 0, tzinfo=IST)  # Saturday 10:00
        daily = self.automation(run_time=time(9))
        self.assertEqual(next_run(daily, now), datetime(2026, 11, 1, 9, 0, tzinfo=IST))
        weekly = self.automation(frequency='weekly', weekday=0, run_time=time(8, 30))
        self.assertEqual(next_run(weekly, now), datetime(2026, 11, 2, 8, 30, tzinfo=IST))
        monthly = self.automation(frequency='monthly', month_day=5)
        self.assertEqual(next_run(monthly, now), datetime(2026, 11, 5, 9, 0, tzinfo=IST))
        once = self.automation(frequency='once', start_date=date(2026, 10, 31), run_time=time(11))
        self.assertEqual(next_run(once, now), datetime(2026, 10, 31, 11, 0, tzinfo=IST))
        self.assertIsNone(next_run(once, datetime(2026, 10, 31, 11, 0, tzinfo=IST)))
        ended = self.automation(end_date=date(2026, 10, 31))
        self.assertIsNone(next_run(ended, now))

    def test_each_slot_runs_once_and_a_one_time_email_switches_off(self):
        self.account()
        a = self.automation(frequency='once', start_date=date(2026, 10, 31), enabled=True, to_emails=['x@bsnl.example'])
        a.next_run_at = timezone.now() - timedelta(minutes=1)
        a.save()
        engine.tick()
        engine.tick()  # a second pass finds nothing new
        self.assertEqual(Execution.objects.filter(trigger='schedule').count(), 1)
        self.assertEqual(len(mail.outbox), 1)
        a.refresh_from_db()
        self.assertEqual((a.enabled, a.next_run_at), (False, None))
        self.assertIsNone(engine.queue(a, trigger='schedule', dedupe_key=Execution.objects.get().dedupe_key))  # same slot: refused


class ReminderTests(AlertTestCase):
    def setUp(self):
        super().setUp()
        self.account()
        batch = DataImportBatch.objects.create(original_filename='m.xlsx', checksum_sha256='x', sheet_name='S', stored_path='-', status='committed')
        for project, circle, n in (('4G Saturation', 'OD', 2), ('4G Saturation', 'MP', 1)):
            for i in range(n):
                UptimeSite.objects.create(project=project, circle=circle, site_id=f'{circle}{i}', site_key=f'{circle}{i}', batch=batch, source_row=1, on_air=True)
        self.day = timezone.localdate() - timedelta(days=1)
        SiteDailyPerformance.objects.create(site=UptimeSite.objects.get(site_id='MP0'), date=self.day, outage_minutes=0, batch=batch)  # MP complete
        self.ci = portal_user('al-ci-od', 'ci')
        self.ci.email = 'ci.od@bsnl.example'
        self.ci.save()
        set_pairs(self.ci, [('4G Saturation', 'OD')])

    def test_csv_reminder_goes_only_to_circles_with_pending_data_and_their_responsible_users(self):
        a = self.automation(kind='csv_reminder', template='reminder', project='4G Saturation', report_day='yesterday', include_responsible=True)
        ex = engine.process(engine.queue(a, trigger='manual', dedupe_key='m1'))
        self.assertEqual(ex.status, 'done')
        self.assertEqual(len(mail.outbox), 1)  # OD only: MP's data is complete
        sent = mail.outbox[0]
        self.assertEqual(sent.to, ['ci.od@bsnl.example'])
        self.assertIn('OD', sent.subject)
        html = sent.alternatives[0][0]
        self.assertIn('0 of 2 sites with data', html)

    def test_rca_reminder_counts_circle_uploads_only(self):
        cycle = cycles.cycle_for_date(self.day)
        cycles.set_required(cycle, [('4G Saturation', 'OD'), ('4G Saturation', 'MP')])
        RcaImportBatch.objects.create(original_filename='mp.xlsx', checksum_sha256='c', sheet_name='Sheet1', status='committed', upload_type='circle',
                                      project_scope='4G Saturation', circle='MP', period_start=self.day, period_end=self.day, committed_at=timezone.now())
        RcaImportBatch.objects.create(original_filename='all.xlsx', checksum_sha256='d', sheet_name='Sheet1', status='committed', upload_type='consolidated',
                                      project_scope='both', period_start=self.day, period_end=self.day, committed_at=timezone.now())
        a = self.automation(kind='rca_reminder', template='reminder', report_day='yesterday', include_responsible=False, to_emails=['noc@bsnl.example'])
        self.assertEqual([(p, c) for p, c, _, _ in engine.pending(a)], [('4G Saturation', 'OD')])  # MP sent its circle file; consolidated never counts
        engine.process(engine.queue(a, trigger='manual', dedupe_key='m2'))
        self.assertEqual([m.subject for m in mail.outbox], [f'Action Required – RCA Submission Pending | OD | {self.day:%d %b %Y}'])

    def test_attachments_are_limited_to_each_recipient(self):
        admin_copy = self.automation(kind='uptime_report', attachments=[{'report': 'csv_arrival', 'format': 'csv'}], report_day='yesterday',
                                     distribution='per_recipient')
        admin_copy.to_users.set([self.admin, self.ci])
        engine.process(engine.queue(admin_copy, trigger='manual', dedupe_key='m3'))
        files = {m.to[0]: m.attachments[0][1] if isinstance(m.attachments[0][1], str) else m.attachments[0][1].decode('utf-8-sig') for m in mail.outbox}
        self.assertIn('MP', files['admin@bsnl.example'])
        self.assertNotIn(',MP,', files['ci.od@bsnl.example'])  # the CI user's report has their circle only
        self.assertIn(',OD,', files['ci.od@bsnl.example'])

    def test_the_rca_master_report_is_never_sent_to_a_circle_limited_recipient(self):
        a = self.automation(kind='uptime_report', attachments=[{'report': 'rca_master', 'format': 'xlsx'}], distribution='per_recipient')
        a.to_users.set([self.ci])
        ex = engine.process(engine.queue(a, trigger='manual', dedupe_key='m4'))
        msg = ex.messages.get()
        self.assertEqual((msg.status, len(mail.outbox)), ('failed', 0))
        self.assertIn('covers every circle', msg.error)


class EventTests(AlertTestCase):
    def test_a_real_failed_upload_alerts_the_uploader_once(self):
        self.account()
        uploader = portal_user('al-noc', 'noc_lead')
        uploader.email = 'noc@bsnl.example'
        uploader.save()
        a = self.automation(kind='upload_failure', frequency='event', template='reminder', enabled=True)
        self.client.force_login(uploader)
        bad = SimpleUploadedFile('day.csv', b'\x00\x01 not a csv')
        r = self.client.post(reverse('raw-upload-preview'), {'file': bad, 'project': '4G Saturation', 'circle': 'OD', 'reporting_date': '2026-10-13'})
        self.assertGreaterEqual(r.status_code, 400)
        self.assertEqual(Execution.objects.filter(automation=a, trigger='event').count(), 1)
        engine.tick()
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(mail.outbox[0].to, ['noc@bsnl.example'])
        self.assertIn('failed', mail.outbox[0].subject.lower())


class HistoryTests(AlertTestCase):
    def test_failed_sends_retry_automatically_and_manually_and_resend_is_a_new_record(self):
        self.account()
        f = self.client.post(reverse('alert-files'), {'file': SimpleUploadedFile('note.pdf', b'%PDF-1.4 approved')}).json()
        a = self.automation(to_emails=['x@bsnl.example', 'X@bsnl.example'], subject='Hello {{recipient_name}}', message='<b>bold</b>', extra_file_id=f['id'],
                            attachments=[{'report': 'csv_arrival', 'format': 'csv'}])
        with mock.patch('apps.alerts.mailer.connection', lambda acc: Failing()):
            ex = engine.process(engine.queue(a, trigger='manual', dedupe_key='h1'))
        msg = ex.messages.get()
        self.assertEqual((msg.status, msg.attempts, msg.to), ('failed', 1, ['x@bsnl.example']))  # duplicates removed
        self.assertIn('mailbox unavailable', msg.error)
        self.assertIsNotNone(msg.next_retry_at)
        retried = self.client.post(reverse('alert-retry', args=[msg.pk])).json()['message']
        self.assertEqual((retried['status'], retried['attempts'], len(retried['attempt_log'])), ('accepted', 2, 2))
        sent = mail.outbox[0]
        self.assertEqual(sorted(n for n, _, _ in sent.attachments), sorted(['note.pdf', f'CSV_Arrival_Status_{timezone.localdate() - timedelta(days=1)}.csv']))
        self.assertIn('&lt;b&gt;bold&lt;/b&gt;', sent.alternatives[0][0])  # the message is escaped in HTML
        again = self.client.post(reverse('alert-resend', args=[msg.pk])).json()['message']
        self.assertEqual((again['resend_of'], Message.objects.count()), (msg.pk, 2))
        rows = self.client.get(reverse('alert-history'), {'status': 'accepted', 'recipient': 'x@bsnl'}).json()
        self.assertEqual(rows['total'], 2)

    def test_work_interrupted_by_a_stopped_worker_is_recovered_without_a_duplicate(self):
        self.account()
        a = self.automation(to_emails=['x@bsnl.example'])
        old = timezone.now() - timedelta(hours=1)
        stuck = Execution.objects.create(automation=a, automation_name=a.name, trigger='schedule', status='processing', started_at=old)
        sending = Execution.objects.create(automation=a, automation_name=a.name, trigger='schedule', status='processing', started_at=old)
        half = Message.objects.create(execution=sending, to=['x@bsnl.example'], subject='s', html='h', text='t', status='processing')
        engine.tick()
        stuck.refresh_from_db()
        half.refresh_from_db()
        self.assertEqual(stuck.status, 'done')  # re-queued and sent
        self.assertEqual(half.status, 'failed')  # not resent blindly
        self.assertEqual(len(mail.outbox), 1)


class ApiTests(AlertTestCase):
    def body(self, **kw):
        return {'name': 'Daily report', 'kind': 'uptime_report', 'frequency': 'daily', 'run_time': '09:00', 'timezone': 'Asia/Kolkata', 'template': 'report',
                'to_emails': ['a@bsnl.example'], 'attachments': [{'report': 'daily_uptime', 'format': 'xlsx'}], 'subject': '', 'message': '', **kw}

    def test_validation_preview_and_enable(self):
        bad = self.client.post(reverse('alert-automations'), self.body(message='{{password}}', to_emails=['not-an-email'],
                                                                       attachments=[{'report': 'daily_uptime', 'format': 'pdf'}]), content_type='application/json')
        self.assertEqual(set(bad.json()['details']), {'message', 'to_emails', 'attachments'})
        preview = self.client.post(reverse('alert-preview'), self.body(), content_type='application/json').json()
        self.assertEqual(preview['subject'], 'Daily report – Previous day')
        self.assertIn('Daily Uptime Report', preview['html'])
        self.assertIsNotNone(preview['next_run_at'])
        a = self.client.post(reverse('alert-automations'), self.body(), content_type='application/json').json()['automation']
        self.assertEqual(self.client.post(reverse('alert-enable', args=[a['id']]), {'enabled': True}, content_type='application/json').status_code, 400)
        self.account()
        on = self.client.post(reverse('alert-enable', args=[a['id']]), {'enabled': True}, content_type='application/json').json()['automation']
        self.assertTrue(on['enabled'] and on['next_run_at'])

    def test_only_admins_reach_the_alert_module(self):
        for role in ('noc_lead', 'ci'):
            self.client.force_login(portal_user(f'al-{role}', role))
            for name in ('alert-account', 'alert-options', 'alert-automations', 'alert-history'):
                self.assertEqual(self.client.get(reverse(name)).status_code, 403, name)
            self.assertEqual(self.client.put(reverse('alert-account'), {}, content_type='application/json').status_code, 403)
