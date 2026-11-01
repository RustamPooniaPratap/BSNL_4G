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


# --- Roles, permissions and project/circle assignments ----------------------------------------------
# A user's rights outside the Admin and NOC Lead roles come only from assignments: role X on project P (all its circles,
# or one circle of it). What a role may do is a set of (module, action) grants from ``catalog.modules()``; a new role has
# none. Admin and NOC Lead stay Django groups with their fixed rights (see ``access``).

class Role(models.Model):
    """A role used in assignments. System roles mirror the portal's built-in roles and cannot be edited or deleted."""
    name = models.CharField(max_length=60, unique=True)
    description = models.CharField(max_length=300, blank=True)
    # 'admin' / 'noc_lead' / 'ci' for the built-in roles, '' for roles created by an Admin.
    system_key = models.CharField(max_length=20, blank=True, db_index=True)
    is_active = models.BooleanField(default=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name='+')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-system_key', 'name']

    @property
    def is_system(self) -> bool:
        return bool(self.system_key)

    def __str__(self) -> str:
        return self.name


class RolePermission(models.Model):
    role = models.ForeignKey(Role, on_delete=models.CASCADE, related_name='permissions')
    module = models.CharField(max_length=30)
    action = models.CharField(max_length=20)

    class Meta:
        ordering = ['module', 'action']
        constraints = [models.UniqueConstraint(fields=['role', 'module', 'action'], name='acc_role_permission_unique')]


class AccessAssignment(models.Model):
    """Role ``role`` for ``user`` on ``project``: every circle of the project (``project_circle`` empty) or one circle."""

    class Status(models.TextChoices):
        ACTIVE = 'active', 'Active'
        INACTIVE = 'inactive', 'Inactive'

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='access_assignments')
    role = models.ForeignKey(Role, on_delete=models.PROTECT, related_name='assignments')
    project = models.ForeignKey('organization.Project', on_delete=models.PROTECT, related_name='access_assignments')
    project_circle = models.ForeignKey('organization.ProjectCircle', null=True, blank=True, on_delete=models.PROTECT,
                                       related_name='access_assignments', help_text='Empty: the entire project.')
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.ACTIVE)
    valid_until = models.DateField(null=True, blank=True, help_text='Optional: the assignment stops granting after this date.')
    granted_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name='+')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['user_id', 'project__sort_order', 'project_circle__circle__code', 'role__name']
        constraints = [
            models.UniqueConstraint(fields=['user', 'role', 'project'], condition=models.Q(project_circle__isnull=True),
                                    name='acc_assignment_unique_project'),
            models.UniqueConstraint(fields=['user', 'role', 'project_circle'], condition=models.Q(project_circle__isnull=False),
                                    name='acc_assignment_unique_circle'),
        ]


class AccessEvent(models.Model):
    """Access history: users, roles, permissions and assignments (never passwords or tokens)."""
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name='+')
    actor_name = models.CharField(max_length=150, blank=True)
    target_user = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name='+')
    target_name = models.CharField(max_length=150, blank=True, help_text='User or role concerned (kept if it is removed).')
    action = models.CharField(max_length=40)
    scope = models.CharField(max_length=200, blank=True)
    details = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at', '-id']
