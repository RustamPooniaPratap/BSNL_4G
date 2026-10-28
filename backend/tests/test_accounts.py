"""Sign-in, roles and account administration (Django sessions, CSRF, Admin / CI)."""
import tempfile
from pathlib import Path

from django.contrib.sessions.models import Session
from django.core.cache import cache
from django.test import Client, TestCase, override_settings
from django.urls import reverse

from apps.accounts.models import must_change_password
from apps.accounts.roles import role_of
from apps.dashboard import workbook

from .auth_helpers import PASSWORD, portal_user
from .workbook_factory import write_workbook

# Every protected endpoint with a request that would succeed for an allowed user.
DASHBOARD = ['dashboard-filters', 'dashboard-summary', 'dashboard-trends', 'dashboard-breakdowns', 'dashboard-records',
             'dashboard-source', 'dashboard-monthly', 'dashboard-thresholds', 'dashboard-period', 'dashboard-alerts',
             'dashboard-workbook']
ADMIN_ONLY_GET = ['dashboard-teams', 'dashboard-teams-monthly', 'dashboard-teams-top', 'rca-cycles', 'list-raw-files', 'email-status', 'auth-users']


class AuthTestCase(TestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls._tmp = tempfile.TemporaryDirectory()
        cls._override = override_settings(MASTER_WORKBOOK_PATH=str(write_workbook(Path(cls._tmp.name) / 'master.xlsx')))
        cls._override.enable()
        workbook.clear_cache()

    @classmethod
    def tearDownClass(cls):
        cls._override.disable()
        workbook.clear_cache()
        cls._tmp.cleanup()
        super().tearDownClass()

    def setUp(self):
        cache.clear()  # login throttles
        self.admin = portal_user('asha.admin', 'admin')
        self.ci = portal_user('ravi.ci', 'ci')
        self.client = Client(enforce_csrf_checks=True)

    def csrf(self, client=None):
        return (client or self.client).get(reverse('auth-csrf')).json()['csrf_token']

    def sign_in(self, username, password=PASSWORD, client=None):
        client = client or self.client
        return client.post(reverse('auth-login'), {'username': username, 'password': password}, content_type='application/json',
                           HTTP_X_CSRFTOKEN=self.csrf(client))

    def post(self, name, data=None, *, args=None, method='post'):
        token = self.client.get(reverse('auth-csrf')).json()['csrf_token']
        return getattr(self.client, method)(reverse(name, args=args), data or {}, content_type='application/json', HTTP_X_CSRFTOKEN=token)


class SignedOutTests(AuthTestCase):
    def test_every_protected_endpoint_answers_401(self):
        for name in DASHBOARD + ADMIN_ONLY_GET + ['auth-me']:
            self.assertEqual(self.client.get(reverse(name)).status_code, 401, name)
        self.assertEqual(self.client.get(reverse('health-check')).status_code, 200)  # liveness only

    def test_there_is_no_registration_endpoint(self):
        for path in ('/api/auth/register/', '/api/auth/signup/', '/api/register/'):
            self.assertEqual(self.client.post(path, {}).status_code, 404, path)
        self.assertEqual(self.post('auth-users', {'username': 'new.user', 'role': 'admin'}).status_code, 401)


class SignInTests(AuthTestCase):
    def test_admin_signs_in_with_a_renewed_session_and_sees_everything(self):
        self.client.get(reverse('auth-csrf'))
        before = self.client.session.session_key
        response = self.sign_in('asha.admin')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['user'], {'username': 'asha.admin', 'name': '', 'role': 'admin', 'role_label': 'Admin',
                                                   'must_change_password': False, 'circles': None})
        self.assertNotEqual(self.client.session.session_key, before)
        self.assertTrue(response.cookies['sessionid']['httponly'])
        for name in DASHBOARD + ADMIN_ONLY_GET:
            self.assertEqual(self.client.get(reverse(name)).status_code, 200, name)

    def test_remember_me_keeps_the_session_for_seven_days_otherwise_it_ends_with_the_browser(self):
        self.sign_in('asha.admin')
        self.assertTrue(self.client.session.get_expire_at_browser_close())
        other = Client(enforce_csrf_checks=True)
        other.post(reverse('auth-login'), {'username': 'ravi.ci', 'password': PASSWORD, 'remember': True},
                   content_type='application/json', HTTP_X_CSRFTOKEN=self.csrf(other))
        self.assertFalse(other.session.get_expire_at_browser_close())
        self.assertEqual(other.session.get_expiry_age(), 7 * 24 * 60 * 60)

    def test_wrong_password_unknown_login_and_inactive_account_get_the_same_generic_error(self):
        portal_user('old.ci', 'ci', active=False)
        answers = [self.sign_in('asha.admin', 'wrong-password'), self.sign_in('nobody.here'), self.sign_in('old.ci')]
        self.assertEqual({(r.status_code, r.json()['error']) for r in answers}, {(400, 'Invalid login ID or password.')})
        self.assertNotIn('_auth_user_id', self.client.session)

    def test_an_account_without_a_portal_role_cannot_sign_in(self):
        portal_user('no.role', None)
        self.assertEqual(self.sign_in('no.role').status_code, 400)

    def test_login_is_throttled_per_login_id(self):
        statuses = [self.sign_in('asha.admin', 'wrong-password').status_code for _ in range(6)]
        self.assertEqual(statuses, [400] * 5 + [429])

    def test_audit_log_records_sign_ins_without_passwords(self):
        with self.assertLogs('audit', level='INFO') as logs:
            self.sign_in('asha.admin', 'Wrong-Secret-123')
            self.sign_in('asha.admin')
        text = '\n'.join(logs.output)
        self.assertIn('login_failed', text)
        self.assertIn('login_success', text)
        self.assertNotIn('Wrong-Secret-123', text)
        self.assertNotIn(PASSWORD, text)
        self.assertNotIn(self.client.session.session_key, text)


class CsrfTests(AuthTestCase):
    def test_unsafe_requests_without_a_valid_csrf_token_are_rejected(self):
        response = self.client.post(reverse('auth-login'), {'username': 'asha.admin', 'password': PASSWORD}, content_type='application/json')
        self.assertEqual(response.status_code, 403)
        self.assertEqual(self.sign_in('asha.admin').status_code, 200)
        for token in (None, 'not-the-token'):
            headers = {'HTTP_X_CSRFTOKEN': token} if token else {}
            response = self.client.post(reverse('auth-logout'), content_type='application/json', **headers)
            self.assertEqual(response.status_code, 403, token)
        self.assertEqual(self.client.get(reverse('auth-me')).status_code, 200)  # still signed in


class CiRoleTests(AuthTestCase):
    def setUp(self):
        super().setUp()
        self.sign_in('ravi.ci')

    def test_ci_sees_the_operational_dashboards_only(self):
        for name in DASHBOARD:
            self.assertEqual(self.client.get(reverse(name)).status_code, 200, name)
        for name in ADMIN_ONLY_GET:
            self.assertEqual(self.client.get(reverse(name)).status_code, 403, name)
        # Restricted data cannot be reached with other parameters either.
        self.assertEqual(self.client.get(reverse('dashboard-teams'), {'group': 'ie', 'circle': 'MP'}).status_code, 403)

    def test_ci_cannot_send_email_upload_workbooks_or_raw_files(self):
        self.assertEqual(self.post('email-send', {'to': 'a@example.com', 'subject': 's', 'body': 'b'}).status_code, 403)
        self.assertEqual(self.post('email-send-reminder', {}).status_code, 403)
        token = self.csrf()
        self.assertEqual(self.client.post(reverse('dashboard-workbook'), {}, HTTP_X_CSRFTOKEN=token).status_code, 403)
        self.assertEqual(self.client.post(reverse('upload-file'), {}, HTTP_X_CSRFTOKEN=token).status_code, 403)

    def test_ci_cannot_create_accounts_or_change_any_role_including_their_own(self):
        self.assertEqual(self.post('auth-users', {'username': 'evil.admin', 'role': 'admin'}).status_code, 403)
        self.assertEqual(self.post('auth-user', {'role': 'admin'}, args=[self.ci.pk], method='patch').status_code, 403)
        self.assertEqual(self.post('auth-user-reset-password', args=[self.admin.pk]).status_code, 403)
        self.ci.refresh_from_db()
        self.assertEqual(role_of(self.ci), 'ci')
        self.assertEqual(self.client.get('/admin/').status_code, 404)  # Django's admin site is not installed


class TemporaryPasswordTests(AuthTestCase):
    def test_a_temporary_password_must_be_changed_before_using_the_portal(self):
        portal_user('new.ci', 'ci', must_change=True)
        response = self.sign_in('new.ci')
        self.assertTrue(response.json()['user']['must_change_password'])
        blocked = self.client.get(reverse('dashboard-summary'))
        self.assertEqual((blocked.status_code, blocked.json()['details']), (403, {'code': 'password_change_required'}))
        weak = self.post('auth-password', {'current_password': PASSWORD, 'new_password': 'password'})
        self.assertEqual(weak.status_code, 400)
        self.assertIn('new_password', weak.json()['details'])
        changed = self.post('auth-password', {'current_password': PASSWORD, 'new_password': 'Fresh-Strong-Pass-42'})
        self.assertEqual(changed.status_code, 200)
        self.assertFalse(changed.json()['user']['must_change_password'])
        self.assertEqual(self.client.get(reverse('dashboard-summary')).status_code, 200)

    def test_wrong_current_password_is_refused(self):
        self.sign_in('ravi.ci')
        response = self.post('auth-password', {'current_password': 'not-it', 'new_password': 'Fresh-Strong-Pass-42'})
        self.assertEqual((response.status_code, list(response.json()['details'])), (400, ['current_password']))


class LogoutTests(AuthTestCase):
    def test_logout_deletes_the_server_side_session(self):
        self.sign_in('asha.admin')
        key = self.client.session.session_key
        self.assertEqual(self.post('auth-logout').status_code, 200)
        self.assertFalse(Session.objects.filter(session_key=key).exists())
        stolen = Client()
        stolen.cookies['sessionid'] = key  # replaying the old cookie does not work
        self.assertEqual(stolen.get(reverse('dashboard-summary')).status_code, 401)


class UserAdministrationTests(AuthTestCase):
    def setUp(self):
        super().setUp()
        self.sign_in('asha.admin')

    def test_admin_provisions_a_ci_with_a_one_time_temporary_password(self):
        with self.assertLogs('audit', level='INFO') as logs:
            response = self.post('auth-users', {'username': 'meena.ci', 'first_name': 'Meena', 'role': 'ci',
                                                'is_superuser': True, 'is_staff': True, 'groups': ['Admin']})  # extra fields ignored
        self.assertEqual(response.status_code, 201)
        body = response.json()
        temp = body['temporary_password']
        self.assertEqual((body['user']['role'], body['user']['must_change_password'], body['user']['is_superuser']), ('ci', True, False))
        self.assertNotIn(temp, '\n'.join(logs.output))
        from django.contrib.auth import get_user_model
        user = get_user_model().objects.get(username='meena.ci')
        self.assertFalse(user.is_staff or user.is_superuser)
        self.assertNotEqual(user.password, temp)  # stored hashed
        self.assertTrue(user.check_password(temp))
        listed = self.client.get(reverse('auth-users')).json()['users']
        self.assertNotIn('password', listed[0])
        self.assertEqual(self.post('auth-users', {'username': 'MEENA.ci', 'role': 'ci'}).status_code, 400)  # unique login ID
        self.assertEqual(self.post('auth-users', {'username': 'x', 'role': 'owner'}).status_code, 400)

    def test_admin_changes_roles_deactivates_and_resets_with_sessions_revoked(self):
        ci_client = Client(enforce_csrf_checks=True)
        self.sign_in('ravi.ci', client=ci_client)
        self.assertEqual(ci_client.get(reverse('dashboard-summary')).status_code, 200)

        reset = self.post('auth-user-reset-password', args=[self.ci.pk])
        self.assertEqual(reset.status_code, 200)
        self.assertEqual(ci_client.get(reverse('dashboard-summary')).status_code, 401)  # signed out everywhere
        self.ci.refresh_from_db()
        self.assertTrue(must_change_password(self.ci))
        self.assertTrue(self.ci.check_password(reset.json()['temporary_password']))

        self.assertEqual(self.post('auth-user', {'role': 'admin'}, args=[self.ci.pk], method='patch').json()['user']['role'], 'admin')
        self.assertEqual(self.post('auth-user', {'is_active': False}, args=[self.ci.pk], method='patch').json()['user']['is_active'], False)
        self.assertEqual(self.sign_in('ravi.ci', reset.json()['temporary_password'], client=Client(enforce_csrf_checks=True)).status_code, 400)

    def test_admin_cannot_lock_themselves_out_or_touch_superusers(self):
        self.assertEqual(self.post('auth-user', {'role': 'ci'}, args=[self.admin.pk], method='patch').status_code, 403)
        self.assertEqual(self.post('auth-user', {'is_active': False}, args=[self.admin.pk], method='patch').status_code, 403)
        from django.contrib.auth import get_user_model
        root = get_user_model().objects.create_superuser('root.owner', password=PASSWORD)
        self.assertEqual(self.post('auth-user-reset-password', args=[root.pk]).status_code, 403)
        self.assertEqual(role_of(root), 'admin')  # superusers are Admins


class DevLoginBypassTests(AuthTestCase):
    ON = {'DEBUG': True, 'DEV_LOGIN_BYPASS': True, 'DEV_LOGIN_USER': 'ravi.ci'}

    def bypass(self, client=None, **extra):
        client = client or self.client
        return client.post(reverse('auth-dev-login'), {}, content_type='application/json', HTTP_X_CSRFTOKEN=self.csrf(client), **extra)

    def test_off_by_default(self):
        self.assertEqual(self.client.get(reverse('auth-dev-login')).status_code, 404)
        self.assertEqual(self.bypass().status_code, 404)
        self.assertEqual(self.client.get(reverse('auth-me')).status_code, 401)

    def test_signs_in_as_the_configured_account_with_its_own_role_when_every_guard_holds(self):
        with override_settings(**self.ON), self.assertLogs('audit', level='INFO') as logs:
            self.assertEqual(self.client.get(reverse('auth-dev-login')).json(), {'enabled': True, 'username': 'ravi.ci', 'role': 'ci'})
            response = self.bypass()
            self.assertEqual(response.json()['user']['role'], 'ci')
            self.assertEqual(self.client.get(reverse('dashboard-summary')).status_code, 200)
            self.assertEqual(self.client.get(reverse('dashboard-teams')).status_code, 403)  # still a CI
        self.assertIn('login_bypass', '\n'.join(logs.output))

    def test_refused_without_debug_from_another_computer_without_csrf_or_for_an_inactive_account(self):
        with override_settings(**{**self.ON, 'DEBUG': False}):
            self.assertEqual(self.bypass().status_code, 404)
        with override_settings(**self.ON):
            self.assertEqual(self.bypass(REMOTE_ADDR='10.0.0.7').status_code, 404)
            no_token = self.client.post(reverse('auth-dev-login'), {}, content_type='application/json')
            self.assertEqual(no_token.status_code, 403)
            self.ci.is_active = False
            self.ci.save()
            self.assertEqual(self.bypass().status_code, 404)
