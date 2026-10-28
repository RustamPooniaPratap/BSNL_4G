import io
from contextlib import redirect_stdout
from unittest import mock

from django.core import mail
from django.core.cache import cache
from django.test import override_settings
from django.urls import reverse

from .auth_helpers import portal_user
from .test_dashboard_api import DashboardApiTestCase

CONSOLE = 'django.core.mail.backends.console.EmailBackend'
SMTP = 'django.core.mail.backends.smtp.EmailBackend'
REMINDER = {'circle': 'MP', 'report_type': 'LWE', 'reporting_date': '2026-10-03', 'to': 'circle.mp@example.com'}


class EmailApiTestCase(DashboardApiTestCase):
    def setUp(self):
        super().setUp()
        cache.clear()

    def post(self, name, data, expected_status=200):
        response = self.client.post(reverse(name), data, content_type='application/json')
        self.assertEqual(response.status_code, expected_status, response.content[:500])
        return response.json()


class ReminderTests(EmailApiTestCase):
    def test_template_states_only_known_facts(self):
        data = self.get('email-reminder-template', circle='MP', report_type='LWE', reporting_date='2026-10-03')
        self.assertEqual(data['subject'], 'Reminder: LWE uptime CSV for MP, 03 Oct 2026')
        self.assertIn('circle MP, reporting date 03 Oct 2026', data['body'])
        self.assertNotIn('due by', data['body'])  # no deadline configured, none invented
        with_deadline = self.get('email-reminder-template', circle='MP', report_type='LWE', reporting_date='2026-10-03',
                                 deadline='2026-10-04T10:00')
        self.assertIn('It was due by 04 Oct 2026, 10:00.', with_deadline['body'])

    def test_manual_reminder_sends_the_server_template_once(self):
        data = self.post('email-send-reminder', {**REMINDER, 'cc': 'lead@example.com', 'subject': 'ignored', 'body': 'ignored'})
        self.assertEqual(data['status'], 'printed')
        self.assertTrue(data['test_mode'])
        self.assertEqual(len(mail.outbox), 1)
        sent = mail.outbox[0]
        self.assertEqual(sent.to, ['circle.mp@example.com'])
        self.assertEqual(sent.cc, ['lead@example.com'])
        self.assertEqual(sent.subject, 'Reminder: LWE uptime CSV for MP, 03 Oct 2026')
        self.assertNotIn('ignored', sent.body)
        # A repeat (double click) is refused and nothing more is sent.
        repeat = self.post('email-send-reminder', REMINDER, expected_status=409)
        self.assertEqual(repeat['details'], {'code': 'duplicate'})
        self.assertEqual(len(mail.outbox), 1)

    def test_reminder_requires_a_known_circle_and_a_valid_recipient(self):
        errors = self.post('email-send-reminder', {**REMINDER, 'circle': 'XX'}, expected_status=400)['details']
        self.assertIn('circle', errors)
        errors = self.post('email-send-reminder', {**REMINDER, 'reporting_date': '03-10-2026'}, expected_status=400)['details']
        self.assertIn('reporting_date', errors)
        errors = self.post('email-send-reminder', {**REMINDER, 'to': ''}, expected_status=400)['details']
        self.assertEqual(errors['to'], ['Enter at least one recipient.'])
        self.assertEqual(len(mail.outbox), 0)


class PersonalEmailTests(EmailApiTestCase):
    MESSAGE = {'to': 'a@example.com, b@example.com', 'cc': '', 'subject': 'Edited subject', 'body': 'Edited body'}

    def test_sends_the_edited_subject_and_body(self):
        data = self.post('email-send', self.MESSAGE)
        self.assertEqual(data['to'], ['a@example.com', 'b@example.com'])
        self.assertEqual((mail.outbox[0].subject, mail.outbox[0].body), ('Edited subject', 'Edited body'))

    def test_rejects_invalid_or_missing_fields(self):
        errors = self.post('email-send', {'to': 'not-an-email', 'cc': 'x@', 'subject': ' ', 'body': ''}, expected_status=400)['details']
        self.assertEqual(errors, {'to': ['Not a valid email address: not-an-email.']})  # first problem found
        errors = self.post('email-send', {**self.MESSAGE, 'cc': 'x@'}, expected_status=400)['details']
        self.assertEqual(errors, {'cc': ['Not a valid email address: x@.']})
        errors = self.post('email-send', {**self.MESSAGE, 'subject': 'two\nlines', 'body': ''}, expected_status=400)['details']
        self.assertEqual(set(errors), {'subject', 'body'})
        self.assertEqual(len(mail.outbox), 0)

    def test_transport_failure_is_reported_not_hidden(self):
        with mock.patch('django.core.mail.EmailMessage.send', side_effect=OSError('connection refused')):
            data = self.post('email-send', self.MESSAGE, expected_status=502)
        self.assertIn('Nothing was delivered', data['error'])
        self.assertNotIn('connection refused', data['error'])


class ModeTests(EmailApiTestCase):
    @override_settings(EMAIL_BACKEND=CONSOLE)
    def test_console_backend_prints_and_is_labelled_test_mode(self):
        self.assertEqual(self.get('email-status')['test_mode'], True)
        out = io.StringIO()
        with mock.patch('sys.stdout', out), redirect_stdout(out):
            data = self.post('email-send', PersonalEmailTests.MESSAGE)
        self.assertIn('TEST MODE', data['message'])
        self.assertEqual(data['status'], 'printed')
        self.assertIn('Subject: Edited subject', out.getvalue())

    @override_settings(EMAIL_BACKEND=SMTP)
    def test_live_sending_is_labelled_live_and_needs_an_admin(self):
        self.assertFalse(self.get('email-status')['test_mode'])
        with mock.patch('django.core.mail.EmailMessage.send', return_value=1) as send:
            data = self.post('email-send', PersonalEmailTests.MESSAGE)
        self.assertEqual((data['status'], data['test_mode']), ('accepted', False))
        send.assert_called_once()

    def test_email_endpoints_refuse_signed_out_users_and_cis(self):
        self.client.logout()
        self.post('email-send', PersonalEmailTests.MESSAGE, expected_status=401)
        self.client.force_login(portal_user('ci-mailer', 'ci'))
        self.post('email-send', PersonalEmailTests.MESSAGE, expected_status=403)
        self.post('email-send-reminder', REMINDER, expected_status=403)
        self.assertEqual(len(mail.outbox), 0)
