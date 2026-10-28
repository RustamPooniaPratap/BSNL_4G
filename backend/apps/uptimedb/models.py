"""Site-level uptime data imported from the Master workbook's Up-Time Report sheet.

Identity: a site is (project, circle, normalised btsIpId). The original ID is kept as written.
Every row records the import batch that last wrote it, so values trace back to a file and row.
Missing values are NULL, never 0.
"""
from django.conf import settings
from django.db import models


class DataImportBatch(models.Model):
    class Status(models.TextChoices):
        PREVIEWED = 'previewed', 'Previewed'
        COMMITTED = 'committed', 'Committed'
        FAILED = 'failed', 'Failed'
        DISCARDED = 'discarded', 'Discarded'

    original_filename = models.CharField(max_length=255)
    checksum_sha256 = models.CharField(max_length=64, db_index=True)
    sheet_name = models.CharField(max_length=64)
    stored_path = models.CharField(max_length=500, help_text='Staged copy of the upload (the original is never modified).')
    # Optional second workbook compared with the primary one (e.g. the RJ, MP & OD report).
    reconciliation_filename = models.CharField(max_length=255, blank=True)
    reconciliation_checksum = models.CharField(max_length=64, blank=True)
    reconciliation_path = models.CharField(max_length=500, blank=True)
    # Which file's values were applied to records that differ between the two ('' = no conflicts / no second file).
    conflict_source = models.CharField(max_length=20, blank=True)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.PREVIEWED)
    imported_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name='+')
    initiated_via = models.CharField(max_length=40, default='api')
    uploaded_at = models.DateTimeField(auto_now_add=True)
    committed_at = models.DateTimeField(null=True, blank=True)
    # Counts per record kind: {"sites": {"inserted": n, "updated": n, "unchanged": n}, "monthly": {...}, "daily": {...}}
    counts = models.JSONField(default=dict, blank=True)
    rejected_count = models.PositiveIntegerField(default=0)
    skipped_count = models.PositiveIntegerField(default=0)
    # The validation preview (counts, coverage, issues, conflicts) shown before commit.
    report = models.JSONField(default=dict, blank=True)
    error = models.TextField(blank=True)

    class Meta:
        ordering = ['-uploaded_at']

    def __str__(self):
        return f'#{self.pk} {self.original_filename} ({self.status})'


class UptimeSite(models.Model):
    project = models.CharField(max_length=20, help_text='Normalised: "4G Saturation" or "LWE".')
    project_raw = models.CharField(max_length=40, blank=True)
    circle = models.CharField(max_length=20, help_text='Circle code (LWE names normalised, e.g. Madhya Pradesh to MP).')
    circle_raw = models.CharField(max_length=60, blank=True)
    site_id = models.CharField(max_length=60, help_text='btsIpId as in the source (trimmed, as the dashboard reads it).')
    site_key = models.CharField(max_length=60, help_text='Matching key: trimmed, upper case, inner spaces collapsed.')
    site_name = models.CharField(max_length=200, blank=True)
    oa = models.CharField(max_length=100, blank=True)
    ba = models.CharField(max_length=100, blank=True)
    on_air_raw = models.CharField(max_length=40, blank=True)
    on_air = models.BooleanField(default=False, help_text='On-Air = "Yes".')
    eb = models.CharField(max_length=40, blank=True)
    od_eb_working_status = models.CharField(max_length=100, blank=True)
    solar_logic_done = models.CharField(max_length=60, blank=True, help_text='Solar Logic Done Date as written in the source.')
    ie_name = models.CharField(max_length=120, blank=True)
    ie_contact = models.CharField(max_length=60, blank=True)
    ci_name = models.CharField(max_length=120, blank=True)
    ci_contact = models.CharField(max_length=60, blank=True)
    # Source columns the dashboard does not use yet (e.g. Correction Plan, weekly uptime), kept as written.
    extra = models.JSONField(default=dict, blank=True)
    batch = models.ForeignKey(DataImportBatch, on_delete=models.PROTECT, related_name='sites')
    source_file = models.CharField(max_length=255, blank=True, help_text='File the values came from (the second workbook when its version was chosen).')
    source_row = models.PositiveIntegerField(help_text='1-based Excel row in source_file.')
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=['project', 'circle', 'site_key'], name='uptime_site_identity')]
        indexes = [models.Index(fields=['project', 'circle'])]

    def __str__(self):
        return f'{self.project} {self.circle} {self.site_id}'


class SiteMonthlyPerformance(models.Model):
    site = models.ForeignKey(UptimeSite, on_delete=models.CASCADE, related_name='months')
    month = models.DateField(help_text='First day of the reporting month.')
    ff_count = models.FloatField(null=True, blank=True, help_text='FF count as in the source.')
    outage_minutes = models.FloatField(null=True, blank=True)
    uptime_pct = models.FloatField(null=True, blank=True, help_text='Source monthly uptime, as a percentage.')
    bucket = models.CharField(max_length=30, blank=True, help_text='Threshold bucket as written in the source.')
    # O&M Start - <month>: None when the source has no such column for the month.
    om_start_raw = models.CharField(max_length=40, null=True, blank=True)
    om_start = models.BooleanField(null=True, help_text='O&M Start = "Yes"; NULL without the column.')
    batch = models.ForeignKey(DataImportBatch, on_delete=models.PROTECT, related_name='+')

    class Meta:
        constraints = [models.UniqueConstraint(fields=['site', 'month'], name='uptime_site_month')]


class SiteDailyPerformance(models.Model):
    site = models.ForeignKey(UptimeSite, on_delete=models.CASCADE, related_name='days')
    date = models.DateField()
    outage_minutes = models.FloatField(null=True, blank=True, help_text='NULL = not reported.')
    uptime_pct = models.FloatField(null=True, blank=True, help_text='Source daily uptime column, as a percentage.')
    batch = models.ForeignKey(DataImportBatch, on_delete=models.PROTECT, related_name='+')

    class Meta:
        constraints = [models.UniqueConstraint(fields=['site', 'date'], name='uptime_site_date')]
        indexes = [models.Index(fields=['date'])]


class AppSetting(models.Model):
    """Application-wide settings (e.g. which data source powers the dashboard)."""
    key = models.CharField(max_length=60, unique=True)
    value = models.CharField(max_length=200)
    updated_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name='+')
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f'{self.key}={self.value}'
