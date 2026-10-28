"""Signed-in test clients: the API needs a portal user for every endpoint except health and sign-in."""
from django.contrib.auth import get_user_model
from django.test import TestCase

from apps.accounts.models import set_must_change_password
from apps.accounts.roles import set_role

PASSWORD = 'Test-only-passw0rd!'  # test database only


def portal_user(username: str, role: str | None = 'admin', *, active: bool = True, must_change: bool = False, password: str = PASSWORD):
    user = get_user_model().objects.create_user(username=username, password=password, is_active=active)
    if role:
        set_role(user, role)
    if must_change:
        set_must_change_password(user, True)
    return user


class SignedInTestCase(TestCase):
    """Each test runs with a signed-in user of ``role`` (Admin by default)."""
    role = 'admin'

    def setUp(self):
        super().setUp()
        self.user = portal_user(f'{self.role}-tester', self.role)
        self.client.force_login(self.user)
