"""The organization: projects, one global record per circle, which circles each project covers, source-specific
circle code aliases, project/circle user access and the history of changes to all of them.

Identity of the data tables: site, daily, monthly, upload and RCA records store the project ``key`` (e.g.
"4G Saturation") and the circle ``code`` (e.g. "MP") as text. Both are therefore fixed once created; names,
short codes and descriptions can be edited without touching any historical record. Nothing here creates sites,
daily or monthly values, uploads, reporting obligations or RCA records.
"""
from django.conf import settings
from django.db import models
from django.db.models import Q


class Project(models.Model):
    key = models.CharField(max_length=20, unique=True,
                           help_text='Identifier stored on site, daily, upload and RCA records (e.g. "4G Saturation"). Fixed once created.')
    code = models.CharField(max_length=12, unique=True, help_text='Short label, e.g. "4G".')
    name = models.CharField(max_length=80, unique=True)
    description = models.TextField(blank=True)
    is_active = models.BooleanField(default=True)
    sort_order = models.PositiveSmallIntegerField(default=100)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['sort_order', 'name']

    def __str__(self):
        return self.key


class Circle(models.Model):
    """One global record per circle, whichever projects it belongs to."""
    code = models.CharField(max_length=20, unique=True, help_text='Canonical code stored on the data records (e.g. "MP"). Fixed once created.')
    name = models.CharField(max_length=80, unique=True, help_text='Canonical name, e.g. "Madhya Pradesh".')
    description = models.TextField(blank=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['code']

    def __str__(self):
        return self.code


class ProjectCircle(models.Model):
    """The circle belongs to the project (eligibility only: no sites, data, obligations or access follow from it)."""
    project = models.ForeignKey(Project, on_delete=models.PROTECT, related_name='circles')
    circle = models.ForeignKey(Circle, on_delete=models.PROTECT, related_name='projects')
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['project__sort_order', 'project__name', 'circle__code']
        constraints = [models.UniqueConstraint(fields=['project', 'circle'], name='org_project_circle_unique')]

    def __str__(self):
        return f'{self.project.key} / {self.circle.code}'


class CircleAlias(models.Model):
    """A circle code or name as one source writes it (e.g. the raw daily CSV's "OR") and the circle it means.

    Project-specific aliases take precedence over source-wide ones (``project`` empty). Circle aliases only: site
    identifier mappings are separate.
    """

    class Source(models.TextChoices):
        RAW_DAILY_CSV = 'raw_daily_csv', 'Raw daily CSV (network availability dump)'
        MASTER_WORKBOOK = 'master_workbook', 'Master workbook (Up-Time Report)'
        DAYWISE_REPORT = 'daywise_report', 'Day-wise outage report'
        ESCALATION_MATRIX = 'escalation_matrix', 'Consolidated Escalation Matrix'
        RCA_WORKBOOK = 'rca_workbook', 'RCA workbook'

    source = models.CharField(max_length=30, choices=Source.choices)
    project = models.ForeignKey(Project, null=True, blank=True, on_delete=models.PROTECT, related_name='aliases',
                                help_text='Empty: applies to every project of the source.')
    raw_code = models.CharField(max_length=60, help_text='As written in the source.')
    raw_key = models.CharField(max_length=60, help_text='Matching key: trimmed, inner spaces collapsed, case-folded.')
    circle = models.ForeignKey(Circle, on_delete=models.PROTECT, related_name='aliases')
    is_active = models.BooleanField(default=True)
    notes = models.CharField(max_length=300, blank=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name='+')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['source', 'raw_key']
        constraints = [
            models.UniqueConstraint(fields=['source', 'raw_key'], condition=Q(project__isnull=True), name='org_alias_unique_source_wide'),
            models.UniqueConstraint(fields=['source', 'project', 'raw_key'], condition=Q(project__isnull=False),
                                    name='org_alias_unique_per_project'),
        ]

    def __str__(self):
        return f'{self.source}: {self.raw_code} -> {self.circle.code}'


class UserCircleAccess(models.Model):
    """A user may work with one project's data of one circle (CI users; Admins and NOC Leads are not limited)."""
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='circle_access')
    project_circle = models.ForeignKey(ProjectCircle, on_delete=models.PROTECT, related_name='user_access')
    granted_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name='+')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=['user', 'project_circle'], name='org_user_access_unique')]


class OrganizationChange(models.Model):
    """Read-only history of every organization change (who, when, before and after)."""
    entity_type = models.CharField(max_length=30)
    entity_id = models.CharField(max_length=40)
    entity_label = models.CharField(max_length=120)
    action = models.CharField(max_length=40)
    previous = models.JSONField(null=True, blank=True)
    new = models.JSONField(null=True, blank=True)
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name='+')
    actor_name = models.CharField(max_length=150, blank=True, help_text='Kept if the account is later removed; "system" for migrations.')
    reason = models.CharField(max_length=500, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at', '-id']
        indexes = [models.Index(fields=['entity_type', 'entity_id'])]
