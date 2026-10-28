"""Portal account data that Django's User model has no field for.

Users, passwords, groups (roles) and sessions are Django's own; this only records whether the user
must replace a temporary password before using the portal, and the circles a CI user works for.
"""
from django.conf import settings
from django.db import models


class AccountProfile(models.Model):
    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='portal_profile')
    # Set when an Admin provisions the account or resets its password; cleared once the user sets their own.
    must_change_password = models.BooleanField(default=False)
    # Circle codes a CI user may upload raw daily data for and export (e.g. ["OD"]). Admins and NOC Leads are not
    # limited by it; a CI user without circles can upload nothing.
    circles = models.JSONField(default=list, blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self) -> str:
        return f'{self.user} (must change password: {self.must_change_password})'


def must_change_password(user) -> bool:
    profile = getattr(user, 'portal_profile', None) if user and user.is_authenticated else None
    return bool(profile and profile.must_change_password)


def set_must_change_password(user, value: bool) -> None:
    AccountProfile.objects.update_or_create(user=user, defaults={'must_change_password': value})
