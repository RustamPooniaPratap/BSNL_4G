"""API Master (Phase 1: API Registry).

One row per (URL name, HTTP method) of the portal's own URL configuration, discovered by ``discovery.sync()``. The registry
records review and publication decisions only: it never changes how an internal endpoint behaves, and an Approved endpoint
becomes callable from outside only when an external wrapper exists for it (a later phase). Blocked endpoints
(authentication, user management, administration, uploads, exports, writes…) can never be approved.
"""
from django.conf import settings
from django.db import models


class ApiEndpoint(models.Model):
    class Status(models.TextChoices):
        PENDING = 'pending', 'Pending'
        APPROVED = 'approved', 'Approved'
        REJECTED = 'rejected', 'Rejected'
        DEPRECATED = 'deprecated', 'Deprecated'

    key = models.CharField(max_length=200, unique=True, help_text='Stable identifier: "<URL name>:<METHOD>".')
    url_name = models.CharField(max_length=150)
    path = models.CharField(max_length=300, help_text='Route as written in the URL configuration, e.g. /api/dashboard/summary/.')
    method = models.CharField(max_length=10)
    module = models.CharField(max_length=60, help_text='Portal area, from the route prefix.')
    name = models.CharField(max_length=200)
    description = models.TextField(blank=True, help_text="First paragraph of the view's docstring.")
    view = models.CharField(max_length=300, help_text='Dotted path of the view function or class.')
    permission_classes = models.JSONField(default=list, blank=True)
    authentication_classes = models.JSONField(default=list, blank=True)
    path_params = models.JSONField(default=list, blank=True, help_text='[{"name", "type"}] from the route converters.')
    blocked = models.BooleanField(default=False, help_text='Never exposed externally (cannot be approved).')
    block_reason = models.CharField(max_length=200, blank=True)
    field_review = models.CharField(max_length=300, blank=True,
                                    help_text='Why the response fields need an explicit review before approval (e.g. staff names).')
    status = models.CharField(max_length=12, choices=Status.choices, default=Status.PENDING)
    review_note = models.TextField(blank=True)
    reviewed_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name='+')
    reviewed_at = models.DateTimeField(null=True, blank=True)
    present = models.BooleanField(default=True, help_text='False when the route no longer exists in the URL configuration.')
    first_seen = models.DateTimeField(auto_now_add=True)
    last_seen = models.DateTimeField()
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['module', 'path', 'method']
        indexes = [models.Index(fields=['status']), models.Index(fields=['module'])]

    def __str__(self) -> str:
        return f'{self.method} {self.path}'
