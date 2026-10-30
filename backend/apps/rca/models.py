"""RCA (root-cause analysis) records, their reviewed cause categories and follow-up workflow.

Three kinds of data are kept apart:
- Source facts (RcaRecord): the workbook's columns as written (Final Bucket, Bucket - 2 and the RCA
  text are separate fields; none is rewritten). Normalised companions (``*_key``, ``circle``,
  ``project``) exist only for filtering and matching.
- Reviewed classification (RcaCauseCategory, RcaCauseMapping): an Admin maps an RCA description
  (by its normalised text) to a canonical category. Nothing is mapped automatically.
- Workflow (RcaWorkflow, RcaComment, RcaEvent): follow-up entered by users. Absent until someone
  records it, so an imported record shows "not recorded", never a guessed status.

A site may have many RCA records, also several on one date (separate outages): an imported record is
unique per (reporting date, project, site, occurrence), where occurrence ranks the site's rows of that date
by cause and outage (see parser). Manually recorded incidents are not limited.
"""
from django.conf import settings
from django.db import models
from django.db.models import Q


class RcaReportingCycle(models.Model):
    """One RCA reporting period: a reporting date or a date range (the RCA workbook's "Date" values) and the
    project / circle data it is expected to cover.

    Periods never overlap, so every RCA record belongs to at most one period. The status is derived
    (cycles.status), never stored: from the expected scope, the accepted records and the final reports.
    """
    reporting_date = models.DateField(unique=True, help_text='First day of the period (the only day for a single-date period).')
    period_end = models.DateField(null=True, blank=True, help_text='Last day of the period; blank for a single reporting date.')
    name = models.CharField(max_length=200, blank=True, help_text='Report name, e.g. "October 2026 RCA Report".')
    notes = models.TextField(blank=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name='+')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-reporting_date']

    def __str__(self):
        return f'RCA period {self.reporting_date}–{self.end}'

    @property
    def end(self):
        return self.period_end or self.reporting_date


class RcaRequiredSubmission(models.Model):
    """One project / circle the period is expected to cover, configured by an Admin (the expected scope)."""
    cycle = models.ForeignKey(RcaReportingCycle, on_delete=models.CASCADE, related_name='required')
    project = models.CharField(max_length=20)
    circle = models.CharField(max_length=20)

    class Meta:
        ordering = ['project', 'circle']
        constraints = [models.UniqueConstraint(fields=['cycle', 'project', 'circle'], name='rca_required_unit')]


class RcaImportBatch(models.Model):
    class UploadType(models.TextChoices):
        CIRCLE = 'circle', 'Circle RCA (one project, circle and reporting date)'
        CONSOLIDATED = 'consolidated', 'Consolidated RCA (several circles and dates)'
        LEGACY = 'legacy', 'Uploaded before upload types existed'

    class Status(models.TextChoices):
        PREVIEWED = 'previewed', 'Previewed'
        COMMITTED = 'committed', 'Committed'
        FAILED = 'failed', 'Failed'
        REJECTED = 'rejected', 'Rejected (validation errors)'
        DISCARDED = 'discarded', 'Discarded'

    original_filename = models.CharField(max_length=255)
    checksum_sha256 = models.CharField(max_length=64, db_index=True)
    sheet_name = models.CharField(max_length=64)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.PREVIEWED)
    imported_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name='+')
    uploaded_at = models.DateTimeField(auto_now_add=True)
    committed_at = models.DateTimeField(null=True, blank=True)
    # {"inserted": n, "unchanged": n, "conflicts": n, "overwritten": n, "skipped_conflicts": n, "rejected": n}
    counts = models.JSONField(default=dict, blank=True)
    # Validation result shown before commit: counts by project / circle / date, issues, conflicts.
    report = models.JSONField(default=dict, blank=True)
    # Parsed valid rows held between preview and commit (the uploaded file itself is not kept).
    rows = models.JSONField(default=list, blank=True)
    conflict_action = models.CharField(max_length=20, blank=True, help_text='"skip" or "overwrite", chosen at commit when conflicts exist.')
    error = models.TextField(blank=True)
    # Report details entered with the upload (blank for imports made before they existed).
    report_name = models.CharField(max_length=200, blank=True)
    period_start = models.DateField(null=True, blank=True)
    period_end = models.DateField(null=True, blank=True)
    project_scope = models.CharField(max_length=20, blank=True, help_text='"4G Saturation", "LWE" or "both".')
    remarks = models.TextField(blank=True)
    # The reporting period the upload was accepted into (set at commit; earlier if the period already exists).
    cycle = models.ForeignKey(RcaReportingCycle, null=True, blank=True, on_delete=models.PROTECT, related_name='submissions')
    units = models.JSONField(default=list, blank=True, help_text='[[project, circle], ...] represented in the valid rows.')
    missing_action = models.CharField(max_length=20, blank=True,
                                      help_text='"keep" or "withdraw": stored records of the units that the file no longer lists.')
    stored_path = models.CharField(max_length=500, blank=True, help_text='Copy of the uploaded file kept for audit.')
    file_size = models.PositiveIntegerField(null=True, blank=True)
    # How the file was uploaded. Only a committed circle upload is a circle's submission; uploads made before the types
    # existed stay "legacy" and are never counted as one.
    upload_type = models.CharField(max_length=20, choices=UploadType.choices, default=UploadType.LEGACY)
    circle = models.CharField(max_length=20, null=True, blank=True, help_text='Circle of a circle upload (its project is project_scope).')

    class Meta:
        ordering = ['-uploaded_at']
        indexes = [models.Index(fields=['upload_type', 'status', 'period_start'], name='rca_batch_submission_idx')]

    def __str__(self):
        return f'RCA import #{self.pk} {self.original_filename} ({self.status})'


class ActiveRecordManager(models.Manager):
    def get_queryset(self):
        return super().get_queryset().filter(withdrawn_at__isnull=True)


class RcaRecord(models.Model):
    class Source(models.TextChoices):
        IMPORT = 'import', 'Imported'
        MANUAL = 'manual', 'Recorded in the portal'

    reporting_date = models.DateField()
    project = models.CharField(max_length=20, help_text='Normalised: "4G Saturation" or "LWE".')
    project_raw = models.CharField(max_length=40, help_text='As written in the source, e.g. "4G Satu".')
    circle = models.CharField(max_length=20, help_text='Circle code used by the dashboard (Odisha -> OD).')
    circle_raw = models.CharField(max_length=60)
    site_id = models.CharField(max_length=60, help_text='As in the source (trimmed).')
    site_key = models.CharField(max_length=60, help_text='Matching key: trimmed, upper case, inner spaces collapsed.')
    occurrence = models.PositiveSmallIntegerField(default=1, help_text="Rank among the site's RCA rows of the date (1 for a single row).")
    site_name = models.CharField(max_length=200, blank=True)
    oa = models.CharField(max_length=100, blank=True)
    ba = models.CharField(max_length=100, blank=True)
    om_start_raw = models.CharField(max_length=20, blank=True, help_text='O&M Start (Yes/No) as written.')
    om_start = models.BooleanField(null=True, help_text='Yes / No for filtering; NULL when blank or unrecognised.')
    outage_minutes = models.FloatField(null=True, blank=True)
    final_bucket = models.CharField(max_length=100, blank=True, help_text='Final Bucket as written.')
    final_bucket_key = models.CharField(max_length=100, blank=True, help_text='Case and spaces ignored; "" for blank or "-".')
    bucket_2 = models.CharField(max_length=100, blank=True, help_text='Bucket - 2 as written.')
    bucket_2_key = models.CharField(max_length=100, blank=True)
    rca_text = models.TextField(blank=True, help_text='RCA description exactly as written (never changed by mapping).')
    rca_key = models.CharField(max_length=500, blank=True, db_index=True, help_text='Matching key for cause mapping.')
    source = models.CharField(max_length=10, choices=Source.choices, default=Source.IMPORT)
    batch = models.ForeignKey(RcaImportBatch, null=True, blank=True, on_delete=models.PROTECT, related_name='records')
    source_file = models.CharField(max_length=255, blank=True)
    source_row = models.PositiveIntegerField(null=True, blank=True, help_text='1-based Excel row.')
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name='+')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    # Set when a circle's corrected file no longer lists the record and the Admin chose to withdraw it. Kept for the
    # audit trail, left out of every register, summary and report (``objects``); ``all_objects`` includes it.
    withdrawn_at = models.DateTimeField(null=True, blank=True)
    withdrawn_by_batch = models.ForeignKey(RcaImportBatch, null=True, blank=True, on_delete=models.PROTECT, related_name='withdrawn_records')

    objects = ActiveRecordManager()
    all_objects = models.Manager()

    class Meta:
        base_manager_name = 'all_objects'
        ordering = ['-reporting_date', '-outage_minutes', 'id']
        constraints = [
            models.UniqueConstraint(fields=['reporting_date', 'project', 'site_key', 'occurrence'], condition=Q(source='import'),
                                    name='rca_import_incident'),
        ]
        indexes = [
            models.Index(fields=['reporting_date']),
            models.Index(fields=['project', 'circle']),
            models.Index(fields=['final_bucket_key']),
            models.Index(fields=['bucket_2_key']),
            models.Index(fields=['site_key']),
        ]

    def __str__(self):
        return f'{self.reporting_date} {self.project} {self.site_id}'


class RcaReport(models.Model):
    """A final consolidated RCA Master workbook of a cycle, kept per version for traceability.

    Partial (in-progress) workbooks are built on request and not stored, so they never create versions.
    """
    cycle = models.ForeignKey(RcaReportingCycle, on_delete=models.PROTECT, related_name='reports')
    version = models.PositiveIntegerField()
    generated_at = models.DateTimeField(auto_now_add=True)
    generated_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name='+')
    automatic = models.BooleanField(default=False, help_text='Generated when the last required submission was accepted.')
    filename = models.CharField(max_length=200)
    stored_path = models.CharField(max_length=500)
    checksum_sha256 = models.CharField(max_length=64)
    records_checksum = models.CharField(max_length=64, help_text='Fingerprint of the accepted records the report was built from.')
    record_count = models.PositiveIntegerField()
    summary = models.JSONField(default=dict, help_text='The RCA Summary computed from the same records.')
    submissions = models.JSONField(default=list, help_text='Required units and their accepted files at generation.')
    superseded_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ['-version']
        constraints = [models.UniqueConstraint(fields=['cycle', 'version'], name='rca_report_version')]


class RcaCauseCategory(models.Model):
    name = models.CharField(max_length=120, unique=True)
    description = models.TextField(blank=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name='+')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['name']

    def __str__(self):
        return self.name


class RcaCauseMapping(models.Model):
    """An Admin-approved mapping of one RCA description (by normalised text) to a canonical category."""
    rca_key = models.CharField(max_length=500, unique=True)
    example_text = models.TextField(help_text='One source description with this key, as written.')
    category = models.ForeignKey(RcaCauseCategory, on_delete=models.PROTECT, related_name='mappings')
    reviewed_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name='+')
    reviewed_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f'{self.example_text[:40]} -> {self.category}'


class RcaWorkflow(models.Model):
    """Follow-up for one RCA record, entered by users (none of it comes from the workbook)."""

    class Status(models.TextChoices):
        INVESTIGATION = 'investigation', 'Investigation'
        RCA_REVIEW = 'rca_review', 'RCA Review'
        ACTION_PENDING = 'action_pending', 'Action Pending'
        ACTION_COMPLETED = 'action_completed', 'Action Completed'
        CLOSED = 'closed', 'Verified / Closed'

    class Review(models.TextChoices):
        PENDING = 'pending', 'Pending review'
        CONFIRMED = 'confirmed', 'Root cause confirmed'
        REVISION = 'needs_revision', 'Needs revision'

    class Verification(models.TextChoices):
        EFFECTIVE = 'effective', 'Effective'
        NOT_EFFECTIVE = 'not_effective', 'Not effective'
        NOT_VERIFIABLE = 'not_verifiable', 'Could not be verified'

    record = models.OneToOneField(RcaRecord, on_delete=models.CASCADE, related_name='workflow')
    status = models.CharField(max_length=20, choices=Status.choices, blank=True)
    review_status = models.CharField(max_length=20, choices=Review.choices, blank=True)
    corrective_action = models.TextField(blank=True)
    owner = models.CharField(max_length=120, blank=True, help_text='Assigned owner or team.')
    target_date = models.DateField(null=True, blank=True)
    completed_date = models.DateField(null=True, blank=True)
    verification = models.CharField(max_length=20, choices=Verification.choices, blank=True)
    reviewer = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name='+')
    reviewed_at = models.DateTimeField(null=True, blank=True)
    updated_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name='+')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)


class RcaComment(models.Model):
    record = models.ForeignKey(RcaRecord, on_delete=models.CASCADE, related_name='comments')
    author = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name='+')
    text = models.TextField()
    evidence = models.CharField(max_length=500, blank=True, help_text='Reference to evidence (document number, link, ticket).')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['created_at']


class RcaEvent(models.Model):
    """Audit trail of changes to a record's workflow (who, when, which fields from what to what)."""
    record = models.ForeignKey(RcaRecord, on_delete=models.CASCADE, related_name='events')
    user = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name='+')
    action = models.CharField(max_length=40)
    changes = models.JSONField(default=dict, blank=True)
    at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-at']
