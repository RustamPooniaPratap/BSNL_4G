"""Assign a portal role to an existing account, e.g. after ``createsuperuser``.

    python manage.py set_role <login_id> admin|noc_lead|ci

No password is read, set or printed here.
"""
from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError

from apps.accounts.audit import audit
from apps.accounts.roles import ROLES, set_role


class Command(BaseCommand):
    help = 'Assign the portal role (admin, noc_lead or ci) to an existing user.'

    def add_arguments(self, parser):
        parser.add_argument('username')
        parser.add_argument('role', choices=list(ROLES))

    def handle(self, *args, username, role, **options):
        user = get_user_model().objects.filter(username=username).first()
        if user is None:
            raise CommandError(f'No user with login ID {username!r}. Create it first (createsuperuser for the first Admin).')
        set_role(user, role)
        audit('role_changed', None, user_id=user.pk, login_id=username, role=role, via='manage.py set_role')
        self.stdout.write(self.style.SUCCESS(f'{username} now has the {ROLES[role]} role.'))
