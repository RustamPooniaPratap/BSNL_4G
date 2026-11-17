"""The organization: projects, one global record per circle, which circles each project covers, source-specific
circle code aliases and the history of changes to all of them.

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
        TICKET_UPLOAD = 'ticket_upload', 'OFC ticket workbook'

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


# ==============================================================================
# TEAM PERFORMANCE HIERARCHY MODELS (PHASE 1)
# ==============================================================================

import hashlib
from datetime import date
from django.core.exceptions import PermissionDenied, ValidationError
from django.utils import timezone


class OperationalArea(models.Model):
    """
    Standardized Operational Area (OA / SSA / BA) within a Circle.
    Reconciles casing and whitespace variations found across live site records.
    """
    circle = models.ForeignKey(
        Circle,
        on_delete=models.PROTECT,
        related_name='operational_areas',
        db_index=True,
    )
    name = models.CharField(max_length=100)
    normalized_name = models.CharField(
        max_length=100,
        db_index=True,
        help_text="Standardized lowercase key: ' '.join(name.strip().lower().split()).",
    )
    code = models.CharField(max_length=20, blank=True, null=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'org_operational_area'
        verbose_name = 'Operational Area'
        verbose_name_plural = 'Operational Areas'
        ordering = ['circle__code', 'name']
        constraints = [
            models.UniqueConstraint(
                fields=['circle', 'normalized_name'],
                name='org_oa_unique_circle_normalized_name',
            ),
        ]

    def clean(self):
        super().clean()
        if self.name:
            self.name = ' '.join(self.name.strip().split())
            self.normalized_name = self.name.lower()

    def __str__(self):
        return f'{self.name} ({self.circle.code})'


class OperationalAreaAlias(models.Model):
    """
    Source raw string variations mapping to a canonical OperationalArea.
    """
    oa = models.ForeignKey(
        OperationalArea,
        on_delete=models.PROTECT,
        related_name='aliases',
        db_index=True,
    )
    raw_name = models.CharField(max_length=100)
    normalized_name = models.CharField(
        max_length=100,
        db_index=True,
        help_text='Standardized lowercase key.',
    )
    source = models.CharField(max_length=40, default='import')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'org_operational_area_alias'
        verbose_name = 'Operational Area Alias'
        verbose_name_plural = 'Operational Area Aliases'
        ordering = ['oa__circle__code', 'normalized_name']

    def clean(self):
        super().clean()
        if self.raw_name:
            self.normalized_name = ' '.join(self.raw_name.strip().lower().split())

    def __str__(self):
        return f"'{self.raw_name}' -> {self.oa.name} ({self.oa.circle.code})"


class OmManagerAssignment(models.Model):
    """
    Authoritative assignment of an O&M Manager to a Circle, optionally scoped to a Project.
    Closed historical assignments retain is_active=True and populate effective_to.
    Intervals are half-open: [effective_from, effective_to).
    """
    circle = models.ForeignKey(
        Circle,
        on_delete=models.PROTECT,
        related_name='om_assignments',
        db_index=True,
    )
    project = models.ForeignKey(
        Project,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name='om_assignments',
        db_index=True,
        help_text='Null indicates shared O&M management across all projects in Circle.',
    )
    manager_name = models.CharField(max_length=150, blank=True)
    employee_code = models.CharField(max_length=50, blank=True)
    contact = models.CharField(max_length=50, blank=True)
    email = models.EmailField(blank=True)

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name='om_circle_assignments',
        help_text='Portal login for the manager. Must be NULL if is_vacant=True.',
    )

    is_vacant = models.BooleanField(
        default=False,
        help_text='Explicit vacancy state. User must be NULL.',
    )
    is_active = models.BooleanField(
        default=True,
        db_index=True,
        help_text='True for operational & historical assignments. False only if voided by correction.',
    )

    effective_from = models.DateField(
        help_text='Inclusive start date of assignment.',
    )
    effective_to = models.DateField(
        null=True,
        blank=True,
        help_text='Exclusive end date of assignment. NULL indicates ongoing.',
    )

    notes = models.TextField(blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name='+',
    )
    updated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name='+',
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'org_om_manager_assignment'
        verbose_name = 'O&M Manager Assignment'
        verbose_name_plural = 'O&M Manager Assignments'
        ordering = ['circle__code', 'project__name', '-effective_from']
        constraints = [
            models.UniqueConstraint(
                fields=['circle'],
                condition=Q(project__isnull=True, effective_to__isnull=True, is_active=True),
                name='unique_active_shared_om_per_circle',
            ),
            models.UniqueConstraint(
                fields=['circle', 'project'],
                condition=Q(project__isnull=False, effective_to__isnull=True, is_active=True),
                name='unique_active_project_om_per_circle',
            ),
            models.CheckConstraint(
                check=Q(effective_to__isnull=True) | Q(effective_to__gt=models.F('effective_from')),
                name='om_assignment_half_open_dates_valid',
            ),
        ]

    def clean(self):
        super().clean()
        if self.is_vacant and self.user is not None:
            raise ValidationError({'user': 'A vacant assignment cannot be linked to a portal user.'})
        if self.effective_to and self.effective_from and self.effective_to <= self.effective_from:
            raise ValidationError({'effective_to': 'effective_to (exclusive) must be strictly greater than effective_from (inclusive).'})
        if self.project and self.circle:
            if not ProjectCircle.objects.filter(project=self.project, circle=self.circle, is_active=True).exists():
                raise ValidationError(f"Project '{self.project.name}' is not active in Circle '{self.circle.name}'.")
        if self.circle_id and self.effective_from:
            from apps.organization.hierarchy_services import assert_no_half_open_overlap
            existing_qs = OmManagerAssignment.objects.filter(circle_id=self.circle_id, project_id=self.project_id)
            assert_no_half_open_overlap(existing_qs, self.effective_from, self.effective_to, exclude_id=self.pk)

    def __str__(self):
        scope = f' / {self.project.name}' if self.project else ' (Shared)'
        status = ' [VACANT]' if self.is_vacant else f' - {self.manager_name}'
        return f'{self.circle.code}{scope}{status}'


class ImmutableAuditQuerySet(models.QuerySet):
    def delete(self):
        raise PermissionDenied('Audit log records cannot be deleted via QuerySet.delete().')

    def update(self, **kwargs):
        raise PermissionDenied('Audit log records cannot be updated via QuerySet.update().')


class ImmutableAuditManager(models.Manager):
    def get_queryset(self):
        return ImmutableAuditQuerySet(self.model, using=self._db)

class OmManagerAssignmentAudit(models.Model):
    objects = ImmutableAuditManager()
    """
    Immutable, append-only audit trail of every O&M Manager assignment mutation.
    """
    class ActionType(models.TextChoices):
        CREATE = 'create', 'Assignment Created'
        UPDATE = 'update', 'Assignment Updated'
        END = 'end', 'Assignment Ended'
        VACATE = 'vacate', 'Assignment Marked Vacant'
        REPLACE = 'replace', 'Assignment Replaced'
        RESTORE = 'restore', 'Assignment Restored'

    assignment = models.ForeignKey(
        OmManagerAssignment,
        null=True,
        on_delete=models.SET_NULL,
        related_name='audit_logs',
    )
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name='+',
    )
    action = models.CharField(max_length=20, choices=ActionType.choices)
    timestamp = models.DateTimeField(auto_now_add=True, db_index=True)
    reason = models.TextField(help_text='Mandatory business explanation.')
    effective_date = models.DateField(help_text='Operational effective date of change.')
    before_values = models.JSONField(default=dict)
    after_values = models.JSONField(default=dict)
    request_id = models.CharField(max_length=64, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'org_om_manager_assignment_audit'
        verbose_name = 'O&M Assignment Audit Log'
        verbose_name_plural = 'O&M Assignment Audit Logs'
        ordering = ['-timestamp']

    def delete(self, *args, **kwargs):
        raise PermissionDenied('Audit records cannot be deleted.')

    def save(self, *args, **kwargs):
        if self.pk:
            raise PermissionDenied('Audit records are append-only and cannot be modified.')
        super().save(*args, **kwargs)


class Personnel(models.Model):
    @property
    def is_tombstoned(self) -> bool:
        return bool(self.merged_into_id and not self.is_active)
    """
    Canonical individual personnel entity (Cluster In-Charge or Infrastructure Engineer).
    Primary key ID is permanent. Names, codes, and contacts are supporting evidence.
    """
    class RoleType(models.TextChoices):
        CI = 'ci', 'Cluster In-Charge (CI)'
        IE = 'ie', 'Infrastructure Engineer (IE)'

    display_name = models.CharField(max_length=150)
    canonical_name = models.CharField(
        max_length=150,
        db_index=True,
        help_text='Standardized trimmed single-spaced title-case name.',
    )
    role_type = models.CharField(
        max_length=10,
        choices=RoleType.choices,
        db_index=True,
    )
    employee_code = models.CharField(
        max_length=50,
        blank=True,
        null=True,
        db_index=True,
        help_text='Non-unique supporting evidence code.',
    )
    contact = models.CharField(max_length=50, blank=True, null=True, db_index=True)
    email = models.EmailField(blank=True, null=True)

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name='personnel_profile',
    )

    is_active = models.BooleanField(
        default=True,
        db_index=True,
        help_text='False if archived or merged into another record. Never physically deleted.',
    )

    merged_into = models.ForeignKey(
        'self',
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name='merged_subordinates',
        help_text='Points to the surviving Personnel record if merged.',
    )
    merged_at = models.DateTimeField(null=True, blank=True)
    merged_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name='+',
    )
    merge_reason = models.TextField(blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'org_personnel'
        verbose_name = 'Personnel'
        verbose_name_plural = 'Personnel'
        ordering = ['role_type', 'canonical_name']
        constraints = [
            models.UniqueConstraint(
                fields=['id', 'role_type'],
                name='unique_personnel_id_role_type',
            ),
        ]
        indexes = [
            models.Index(fields=['role_type', 'canonical_name']),
            models.Index(fields=['employee_code']),
            models.Index(fields=['contact']),
            models.Index(fields=['is_active', 'role_type']),
        ]

    def clean(self):
        super().clean()
        if self.canonical_name:
            self.canonical_name = ' '.join(self.canonical_name.strip().split())
        if self.employee_code:
            self.employee_code = self.employee_code.strip()
            if self.employee_code.upper() in ('-', 'TBD', 'NA', 'NULL', 'NONE'):
                self.employee_code = None
        if self.contact:
            self.contact = self.contact.strip().replace(' ', '').replace('-', '')
            if self.contact in ('-', 'TBD', '0000000000', '0'):
                self.contact = None

    def delete(self, *args, **kwargs):
        raise PermissionDenied('Personnel records cannot be deleted. Use the Merge workflow or set is_active=False.')

    def __str__(self):
        code_str = f' ({self.employee_code})' if self.employee_code else ''
        return f'[{self.get_role_type_display()}] {self.display_name}{code_str}'


class PersonnelSourceMapping(models.Model):
    """
    Persistent mapping of a specific source record to a canonical Personnel ID.
    Approved mappings are permanent and protected against subsequent imports.
    """
    class MappingStatus(models.TextChoices):
        APPROVED = 'approved', 'Approved by Admin'
        UNRESOLVED = 'unresolved', 'Unresolved / Pending Review'
        REJECTED = 'rejected', 'Rejected Mapping'

    source_system = models.CharField(max_length=50, default='consolidation_matrix')
    source_dataset = models.CharField(max_length=50, default='escalation_sites')
    source_record_key = models.CharField(
        max_length=150,
        db_index=True,
        help_text='Stable composite key derived from source data (e.g. site_id + role_type).',
    )
    source_role_type = models.CharField(max_length=10, choices=Personnel.RoleType.choices)
    source_circle = models.ForeignKey(
        Circle,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
    )
    source_project = models.ForeignKey(
        Project,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
    )
    raw_name = models.CharField(max_length=150)
    raw_employee_code = models.CharField(max_length=50, blank=True)

    personnel = models.ForeignKey(
        Personnel,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name='source_mappings',
    )
    mapping_status = models.CharField(
        max_length=20,
        choices=MappingStatus.choices,
        default=MappingStatus.UNRESOLVED,
        db_index=True,
    )
    approved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name='+',
    )
    approved_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'org_personnel_source_mapping'
        verbose_name = 'Personnel Source Mapping'
        verbose_name_plural = 'Personnel Source Mappings'
        constraints = [
            models.UniqueConstraint(
                fields=['source_system', 'source_dataset', 'source_record_key'],
                name='unique_source_record_mapping',
            ),
        ]

    def __str__(self):
        status = self.get_mapping_status_display()
        p_name = self.personnel.display_name if self.personnel else 'UNASSIGNED'
        return f'[{status}] {self.raw_name} -> {p_name} ({self.source_record_key})'


class PersonnelAlias(models.Model):
    """
    Source raw string mapping to canonical Personnel.
    """
    personnel = models.ForeignKey(
        Personnel,
        on_delete=models.PROTECT,
        related_name='aliases',
        db_index=True,
    )
    role_type = models.CharField(max_length=10, choices=Personnel.RoleType.choices, db_index=True)
    raw_name = models.CharField(max_length=150)
    normalized_name = models.CharField(
        max_length=150,
        db_index=True,
        help_text="Standardized key: ' '.join(raw_name.strip().lower().split()).",
    )
    source = models.CharField(max_length=40, default='import')
    circle = models.ForeignKey(
        Circle,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name='personnel_aliases',
        db_index=True,
    )
    project = models.ForeignKey(
        Project,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name='personnel_aliases',
        db_index=True,
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'org_personnel_alias'
        verbose_name = 'Personnel Alias'
        verbose_name_plural = 'Personnel Aliases'
        constraints = [
            models.UniqueConstraint(
                fields=['role_type', 'normalized_name'],
                condition=Q(circle__isnull=True, project__isnull=True),
                name='unique_global_personnel_alias',
            ),
            models.UniqueConstraint(
                fields=['role_type', 'circle', 'normalized_name'],
                condition=Q(circle__isnull=False, project__isnull=True),
                name='unique_circle_personnel_alias',
            ),
            models.UniqueConstraint(
                fields=['role_type', 'circle', 'project', 'normalized_name'],
                condition=Q(circle__isnull=False, project__isnull=False),
                name='unique_project_circle_personnel_alias',
            ),
            models.CheckConstraint(
                check=~Q(circle__isnull=True, project__isnull=False),
                name='personnel_alias_prohibit_project_without_circle',
            ),
        ]

    def clean(self):
        super().clean()
        if self.personnel and self.personnel.role_type != self.role_type:
            raise ValidationError(f"Alias role '{self.role_type}' does not match Personnel role '{self.personnel.role_type}'.")
        if self.project and not self.circle:
            raise ValidationError('A project-specific alias requires a Circle.')
        if self.raw_name:
            self.normalized_name = ' '.join(self.raw_name.strip().lower().split())

    def delete(self, *args, **kwargs):
        raise PermissionDenied('Aliases cannot be deleted. Deactivate or reassign through audited workflows.')

    def __str__(self):
        return f'{self.raw_name} -> {self.personnel.display_name} ({self.role_type})'


class SitePersonnelAssignment(models.Model):
    """
    Site-level assignment of a CI or IE.
    Intervals are half-open: [effective_from, effective_to).
    """
    site = models.ForeignKey(
        'sitedata.Site',  # the data layer's site master; PROTECT: sites are never deleted, assignments are ended
        on_delete=models.PROTECT,
        related_name='personnel_assignments',
        db_index=True,
    )
    personnel = models.ForeignKey(
        Personnel,
        on_delete=models.PROTECT,
        related_name='site_assignments',
        db_index=True,
    )
    role_type = models.CharField(
        max_length=10,
        choices=Personnel.RoleType.choices,
        db_index=True,
    )
    parent_ci = models.ForeignKey(
        Personnel,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name='supervised_ie_site_assignments',
        db_index=True,
        help_text='Mandatory for IE assignments where operational relationship is known.',
    )
    effective_from = models.DateField(help_text='Inclusive start date.')
    effective_to = models.DateField(null=True, blank=True, help_text='Exclusive end date. NULL = ongoing.')
    is_active = models.BooleanField(default=True, db_index=True)
    source = models.CharField(max_length=40, default='import')
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name='+',
    )
    updated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name='+',
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'org_site_personnel_assignment'
        verbose_name = 'Site Personnel Assignment'
        verbose_name_plural = 'Site Personnel Assignments'
        ordering = ['site', 'role_type', '-effective_from']
        constraints = [
            models.UniqueConstraint(
                fields=['site', 'role_type'],
                condition=Q(effective_to__isnull=True, is_active=True),
                name='unique_active_assignment_per_site_role',
            ),
            models.CheckConstraint(
                check=Q(effective_to__isnull=True) | Q(effective_to__gt=models.F('effective_from')),
                name='site_assignment_half_open_dates_valid',
            ),
        ]
        indexes = [
            models.Index(fields=['site', 'role_type', 'is_active']),
            models.Index(fields=['personnel', 'is_active']),
            models.Index(fields=['parent_ci', 'is_active']),
        ]

    def clean(self):
        super().clean()
        if self.personnel and self.personnel.role_type != self.role_type:
            raise ValidationError({'personnel': f"Personnel role '{self.personnel.role_type}' does not match assignment role '{self.role_type}'."})
        if self.effective_to and self.effective_from and self.effective_to <= self.effective_from:
            raise ValidationError({'effective_to': 'effective_to (exclusive) must be strictly greater than effective_from (inclusive).'})

        if self.site_id and self.role_type and self.effective_from:
            from apps.organization.hierarchy_services import assert_no_half_open_overlap
            existing_qs = SitePersonnelAssignment.objects.filter(site_id=self.site_id, role_type=self.role_type)
            assert_no_half_open_overlap(existing_qs, self.effective_from, self.effective_to, exclude_id=self.pk)

        if self.role_type == Personnel.RoleType.IE and self.parent_ci:
            if self.parent_ci.role_type != Personnel.RoleType.CI:
                raise ValidationError({'parent_ci': "The assigned parent_ci must have role_type='ci'."})

            eff_from = self.effective_from
            eff_to = self.effective_to or date(9999, 12, 31)

            ci_overlap_qs = SitePersonnelAssignment.objects.filter(
                site=self.site,
                personnel=self.parent_ci,
                role_type=Personnel.RoleType.CI,
                is_active=True,
                effective_from__lt=eff_to,
            ).filter(
                Q(effective_to__isnull=True) | Q(effective_to__gt=eff_from)
            )

            if not ci_overlap_qs.exists():
                raise ValidationError({
                    'parent_ci': (
                        f"Parent CI '{self.parent_ci.display_name}' has no overlapping CI assignment on site "
                        f"'{self.site.bsnl_site_id}' for the interval [{eff_from}, {self.effective_to or 'ongoing'})."
                    )
                })
        elif self.role_type == Personnel.RoleType.CI and self.parent_ci is not None:
            raise ValidationError({'parent_ci': 'A Cluster In-charge assignment cannot have a parent CI.'})

    def delete(self, *args, **kwargs):
        raise PermissionDenied('Site personnel assignments cannot be deleted. Set effective_to to close or is_active=False to void.')


class PersonnelConflict(models.Model):
    """
    Unresolved or contradictory identity evidence discovered during imports or manual entry.
    Deterministic fingerprint prevents duplicate conflict creation on repeated imports.
    """
    class ConflictType(models.TextChoices):
        UNMATCHED_NAME = 'unmatched_name', 'Unmatched Name'
        AMBIGUOUS_MATCH = 'ambiguous_match', 'Multiple Candidate Matches'
        SHARED_CODE_DIFF_NAME = 'shared_code_diff_name', 'Shared Employee Code Across Distinct Names'
        NAME_MULTI_CODES = 'name_multi_codes', 'Same Name Associated with Multiple Codes'
        CI_IE_CODE_COLLISION = 'ci_ie_code_collision', 'CI/IE Role Code Collision'
        CROSS_CIRCLE_NAME = 'cross_circle_name', 'Cross-Circle Name Collision'
        UNASSIGNED_SITE = 'unassigned_site', 'Site Missing Personnel in Source'

    class Status(models.TextChoices):
        OPEN = 'open', 'Open'
        UNDER_REVIEW = 'under_review', 'Under Review'
        RESOLVED = 'resolved', 'Resolved'
        REJECTED = 'rejected', 'Rejected / False Positive'

    fingerprint = models.CharField(
        max_length=64,
        unique=True,
        db_index=True,
        help_text='Deterministic hash preventing duplicate conflict creation.',
    )
    source_system = models.CharField(max_length=50, default='consolidation_matrix')
    source_dataset = models.CharField(max_length=50, default='escalation_sites')
    source_record_key = models.CharField(max_length=150, blank=True, db_index=True)
    conflict_type = models.CharField(max_length=35, choices=ConflictType.choices, db_index=True)
    role_type = models.CharField(max_length=10, choices=Personnel.RoleType.choices)

    raw_source_data = models.JSONField(default=dict)
    possible_matches = models.JSONField(default=list)

    status = models.CharField(max_length=20, choices=Status.choices, default=Status.OPEN, db_index=True)
    resolution = models.TextField(blank=True)
    resolved_personnel = models.ForeignKey(
        Personnel,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name='resolved_conflicts',
    )
    reviewed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name='+',
    )
    reviewed_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'org_personnel_conflict'
        verbose_name = 'Personnel Conflict'
        verbose_name_plural = 'Personnel Conflicts'
        ordering = ['status', '-updated_at']

    @classmethod
    def generate_fingerprint(cls, source_system, source_dataset, source_record_key, conflict_type, role_type):
        raw_token = f'{source_system}:{source_dataset}:{source_record_key.strip()}:{conflict_type}:{role_type}'
        return hashlib.sha256(raw_token.encode('utf-8')).hexdigest()

    def __str__(self):
        return f'[{self.get_status_display()}] {self.get_conflict_type_display()} ({self.source_record_key})'


class PersonnelMergeAudit(models.Model):
    objects = ImmutableAuditManager()
    """
    Immutable audit log of Personnel merge and recovery operations.
    """
    class MergeStatus(models.TextChoices):
        PREVIEWED = 'previewed', 'Preview Generated'
        APPLIED = 'applied', 'Merge Applied'
        ROLLED_BACK = 'rolled_back', 'Successfully Rolled Back'
        FAILED = 'failed', 'Rollback Failed'

    source_personnel_id = models.IntegerField(db_index=True)
    target_personnel = models.ForeignKey(
        Personnel,
        on_delete=models.PROTECT,
        related_name='target_merges',
    )
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name='+',
    )
    timestamp = models.DateTimeField(auto_now_add=True, db_index=True)
    reason = models.TextField()

    affected_relationship_ids = models.JSONField(default=dict)
    original_values = models.JSONField(default=dict)
    applied_changes = models.JSONField(default=dict)

    status = models.CharField(max_length=20, choices=MergeStatus.choices, default=MergeStatus.APPLIED, db_index=True)
    rollback_status = models.CharField(max_length=20, blank=True)
    rollback_actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name='+',
    )
    rollback_timestamp = models.DateTimeField(null=True, blank=True)
    rollback_reason = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'org_personnel_merge_audit'
        verbose_name = 'Personnel Merge Audit Log'
        verbose_name_plural = 'Personnel Merge Audit Logs'
        ordering = ['-timestamp']

    def delete(self, *args, **kwargs):
        raise PermissionDenied('Merge audit logs cannot be deleted.')

    def save(self, *args, **kwargs):
        if self.pk:
            # Allow rollback update
            if kwargs.get('update_fields') and set(kwargs['update_fields']).issubset({'status', 'rollback_status', 'rollback_actor', 'rollback_timestamp', 'rollback_reason'}):
                super().save(*args, **kwargs)
                return
            raise PermissionDenied('Merge audit records are append-only and cannot be modified.')
        super().save(*args, **kwargs)
