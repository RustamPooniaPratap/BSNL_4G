"""Site-level uptime data imported from the Master workbook's Up-Time Report sheet.

Identity: a site is (project, circle, normalised btsIpId). The original ID is kept as written.
Every row records the import batch that last wrote it, so values trace back to a file and row.
Missing values are NULL, never 0.
"""
from django.conf import settings
from django.db import models


class DataImportBatch(models.Model):
    """One import into the uptime tables: a Master workbook, or one circle's raw daily CSV (CNMC dump)."""

    class Status(models.TextChoices):
        PREVIEWED = 'previewed', 'Previewed'
        COMMITTED = 'committed', 'Committed'
        FAILED = 'failed', 'Failed'
        REJECTED = 'rejected', 'Rejected (cannot be imported)'
        DISCARDED = 'discarded', 'Discarded'

    class Kind(models.TextChoices):
        MASTER_WORKBOOK = 'master_workbook', 'Master workbook'
        RAW_DAILY_CSV = 'raw_daily_csv', 'Raw daily CSV'
        # Records added or changed by hand in the Data Panel (one batch per Save; nothing is read from a file).
        DATA_PANEL = 'data_panel', 'Data Panel edit'

    kind = models.CharField(max_length=20, choices=Kind.choices, default=Kind.MASTER_WORKBOOK)
    # Raw daily CSV uploads: the details entered with the file (blank for Master workbook imports).
    project = models.CharField(max_length=20, blank=True)
    circle = models.CharField(max_length=20, blank=True)
    reporting_date = models.DateField(null=True, blank=True)
    remarks = models.TextField(blank=True)

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
        indexes = [models.Index(fields=['kind', 'project', 'circle', 'reporting_date'])]

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


class EscalationImportBatch(models.Model):
    """One import of the Consolidated Escalation Matrix ("Raw Data" sheet): preview first, then commit."""

    class Status(models.TextChoices):
        PREVIEWED = 'previewed', 'Previewed'
        COMMITTED = 'committed', 'Committed'
        FAILED = 'failed', 'Failed'

    original_filename = models.CharField(max_length=255)
    checksum_sha256 = models.CharField(max_length=64, db_index=True)
    sheet_name = models.CharField(max_length=64)
    stored_path = models.CharField(max_length=500, help_text='Staged copy of the file (the original is never modified).')
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.PREVIEWED)
    imported_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name='+')
    initiated_via = models.CharField(max_length=40, default='command')
    uploaded_at = models.DateTimeField(auto_now_add=True)
    committed_at = models.DateTimeField(null=True, blank=True)
    # {"inserted": n, "updated": n, "unchanged": n, "not_in_this_file": n}
    counts = models.JSONField(default=dict, blank=True)
    # Parse summary and the cross-check against the Up-Time Report tables.
    report = models.JSONField(default=dict, blank=True)
    error = models.TextField(blank=True)

    class Meta:
        ordering = ['-uploaded_at']

    def __str__(self):
        return f'#{self.pk} {self.original_filename} ({self.status})'


class EscalationSite(models.Model):
    """One site of the Consolidated Escalation Matrix: dates, status and the escalation chain.

    Identity: (project, normalised BSNL Site ID). It is linked to the Up-Time Report site with the same project,
    circle and ID (``uptime_site``), which also connects it to the monthly, daily and RCA records. Dates the source
    writes as text ("NO", "-") are NULL, with the text kept in the matching ``*_raw`` field.
    """

    class Match(models.TextChoices):
        MATCHED = 'matched', 'Matched to an Up-Time Report site'
        NOT_IN_UPTIME = 'not_in_uptime', 'Dashboard project, but not in the Up-Time Report'
        OTHER_ENTITY = 'other_entity', 'Not a dashboard project (e.g. VI-HPSC, Sterlite)'

    project = models.CharField(max_length=40, help_text='"4G Saturation" or "LWE"; other entities as written.')
    entity_raw = models.CharField(max_length=60, blank=True)
    site_type = models.CharField(max_length=60, blank=True)
    circle = models.CharField(max_length=40, help_text='Circle code as on the dashboard (e.g. Chattishgarh to CG).')
    circle_raw = models.CharField(max_length=60, blank=True)
    site_id = models.CharField(max_length=60, help_text='BSNL Site ID as in the source.')
    site_key = models.CharField(max_length=60, help_text='Matching key: trimmed, upper case, inner spaces collapsed.')
    site_name = models.CharField(max_length=200, blank=True)
    village_code = models.CharField(max_length=100, blank=True)
    ba = models.CharField(max_length=100, blank=True)
    oa = models.CharField(max_length=100, blank=True)
    district = models.CharField(max_length=100, blank=True)
    sub_district = models.CharField(max_length=100, blank=True)
    commissioning_date = models.DateField(null=True, blank=True)
    commissioning_raw = models.CharField(max_length=60, blank=True)
    commissioning_status = models.CharField(max_length=40, blank=True)
    om_status = models.CharField(max_length=40, blank=True)
    om_start_date = models.DateField(null=True, blank=True)
    om_start_raw = models.CharField(max_length=60, blank=True)
    eb_status = models.CharField(max_length=40, blank=True)
    dg_status = models.CharField(max_length=40, blank=True)
    case_type = models.CharField(max_length=40, blank=True)
    on_air_status = models.CharField(max_length=40, blank=True)
    on_air_date = models.DateField(null=True, blank=True)
    on_air_raw = models.CharField(max_length=60, blank=True)
    ie_emp_code = models.CharField(max_length=40, blank=True)
    ie_name = models.CharField(max_length=120, blank=True)
    ie_contact = models.CharField(max_length=60, blank=True)
    ci_emp_code = models.CharField(max_length=40, blank=True)
    ci_name = models.CharField(max_length=120, blank=True)
    ci_contact = models.CharField(max_length=60, blank=True)
    il_emp_code = models.CharField(max_length=40, blank=True)
    il_name = models.CharField(max_length=120, blank=True)
    il_contact = models.CharField(max_length=60, blank=True)
    om_manager_emp_code = models.CharField(max_length=40, blank=True)
    om_manager_name = models.CharField(max_length=120, blank=True)
    om_manager_contact = models.CharField(max_length=60, blank=True)
    cbh_name = models.CharField(max_length=120, blank=True)
    cbh_contact = models.CharField(max_length=60, blank=True)
    ct_status = models.CharField(max_length=40, blank=True)
    ct_name = models.CharField(max_length=120, blank=True)
    ct_contact = models.CharField(max_length=60, blank=True)
    site_address = models.TextField(blank=True)
    latitude = models.FloatField(null=True, blank=True, help_text='NULL when the source has 0 or text.')
    longitude = models.FloatField(null=True, blank=True, help_text='NULL when the source has 0 or text.')
    rigger_emp_code = models.CharField(max_length=40, blank=True)
    rigger_name = models.CharField(max_length=120, blank=True)
    rigger_contact = models.CharField(max_length=60, blank=True)
    remarks = models.TextField(blank=True)
    smps_make = models.CharField(max_length=60, blank=True)
    bts_id_b1 = models.CharField(max_length=60, blank=True, help_text='BTS Site ID_B1(21MHz).')
    bts_id_b28 = models.CharField(max_length=60, blank=True, help_text='BTS Site ID_B28(7MHz).')
    master_bts_id = models.CharField(max_length=60, blank=True)
    # Source columns without a field above (e.g. the unnamed LWE connection status column), kept as written.
    extra = models.JSONField(default=dict, blank=True)
    uptime_site = models.OneToOneField(UptimeSite, null=True, blank=True, on_delete=models.SET_NULL, related_name='escalation')
    match_status = models.CharField(max_length=20, choices=Match.choices, default=Match.NOT_IN_UPTIME)
    batch = models.ForeignKey(EscalationImportBatch, on_delete=models.PROTECT, related_name='sites')
    source_file = models.CharField(max_length=255, blank=True)
    source_row = models.PositiveIntegerField(help_text='1-based Excel row in source_file.')
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=['project', 'site_key'], name='escalation_site_identity')]
        indexes = [models.Index(fields=['project', 'circle']), models.Index(fields=['site_key'])]

    def __str__(self):
        return f'{self.project} {self.circle} {self.site_id}'
