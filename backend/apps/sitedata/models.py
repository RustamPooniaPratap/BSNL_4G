"""The new BSNL site and performance data layer (Phase 1, docs/phase1-database-audit.md).

- One Site per BSNL Site ID. The Consolidation Matrix is authoritative for the attributes it holds; other uploads never
  overwrite them. A site missing from a newer matrix is flagged, never deleted.
- Every identifier that names a site (BSNL Site ID, BTS IP ID, 2100 / 700 MHz band IDs) is a SiteIdentifier, so raw rows
  with several identifiers resolve to one site and can never create several daily records.
- DailySitePerformance is the only daily table, for 4G Saturation and LWE alike: one record per site, date and
  technology. The first accepted value wins; a different later value is logged as a conflict (DailyPerformanceEvent)
  and changes the record only through an authorized, audited correction.
- MonthlySitePerformance holds monthly results calculated from the daily records, with revisions: all reported days
  (daily_derived) and the O&M Start days from the site's matrix O&M Start Date (om_start, rules.om_effective_from).
- O&M Start comes only from the matrix O&M Start Date; a missing or unreadable date flags the site for review.
- IdentifierConflict blocks identifiers that the matrix gives to more than one site: they are never assigned or matched.
- UploadBatch is the upload history of every file kind.

Missing values are never 0: a site-day without a value has no DailySitePerformance record.
These tables are the only operational data of the application (the legacy uptimedb tables were removed).
"""
from django.conf import settings
from django.core.exceptions import PermissionDenied
from django.db import models
from django.db.models import F, Q


class Technology(models.TextChoices):
    G4 = '4G Saturation', '4G Saturation'
    LWE = 'LWE', 'LWE'


class UploadBatch(models.Model):
    class Kind(models.TextChoices):
        UPTIME_MASTER = 'uptime_master', 'Uptime Master'
        CONSOLIDATION_MATRIX = 'consolidation_matrix', 'Consolidation Matrix'
        LWE_BAND_MAPPING = 'lwe_band_mapping', 'LWE Band ID mapping'
        RAW_CSV_4G = 'raw_csv_4g', '4G raw CSV'
        RAW_CSV_LWE = 'raw_csv_lwe', 'LWE raw CSV'
        CORRECTION = 'correction', 'Authorized correction'

    class Validation(models.TextChoices):
        PENDING = 'pending', 'Pending'
        PASSED = 'passed', 'Passed'
        WARNINGS = 'passed_with_warnings', 'Passed with warnings'
        FAILED = 'failed', 'Failed'

    class Processing(models.TextChoices):
        PREVIEWED = 'previewed', 'Previewed (nothing written)'
        COMMITTED = 'committed', 'Committed'
        FAILED = 'failed', 'Failed'
        DISCARDED = 'discarded', 'Discarded'

    kind = models.CharField(max_length=30, choices=Kind.choices)
    original_filename = models.CharField(max_length=255)
    checksum_sha256 = models.CharField(max_length=64, blank=True, db_index=True)
    stored_path = models.CharField(max_length=500, blank=True, help_text='Staged copy of the upload; the original is never modified.')
    uploaded_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name='+')
    uploaded_at = models.DateTimeField(auto_now_add=True)
    committed_at = models.DateTimeField(null=True, blank=True)
    circle = models.CharField(max_length=20, blank=True)
    reporting_date = models.DateField(null=True, blank=True)
    technology = models.CharField(max_length=20, choices=Technology.choices, blank=True)
    records_received = models.PositiveIntegerField(default=0)
    records_accepted = models.PositiveIntegerField(default=0)
    records_rejected = models.PositiveIntegerField(default=0)
    records_duplicate = models.PositiveIntegerField(default=0)
    records_unmatched = models.PositiveIntegerField(default=0)
    records_conflict = models.PositiveIntegerField(default=0)
    records_superseded = models.PositiveIntegerField(default=0, help_text='Stored values of a lower-precedence source replaced by this upload.')
    validation_status = models.CharField(max_length=30, choices=Validation.choices, default=Validation.PENDING)
    processing_status = models.CharField(max_length=20, choices=Processing.choices, default=Processing.PREVIEWED)
    # Validation report: counts by reason, examples, attribute differences, warnings.
    report = models.JSONField(default=dict, blank=True)
    remarks = models.TextField(blank=True)
    error = models.TextField(blank=True)

    class Meta:
        ordering = ['-uploaded_at']
        indexes = [models.Index(fields=['kind', 'circle', 'reporting_date'])]

    def __str__(self):
        return f'#{self.pk} {self.get_kind_display()} {self.original_filename} ({self.processing_status})'


class Site(models.Model):
    """One BSNL site. Attributes come from the Consolidation Matrix (authoritative)."""

    class Scope(models.TextChoices):
        DASHBOARD = 'dashboard', 'Dashboard reporting scope'
        OUTSIDE = 'outside_scope', 'Outside the dashboard reporting scope'

    bsnl_site_id = models.CharField(max_length=60, help_text='BSNL Site ID as written in the matrix.')
    site_key = models.CharField(max_length=60, unique=True, help_text='Matching key: trimmed, upper case, inner spaces collapsed.')
    entity = models.CharField(max_length=60, help_text='Entity as written (e.g. "4G Saturation", "LWE", "Sterlite", "VI-HPSC").')
    technology = models.CharField(max_length=20, choices=Technology.choices, blank=True, help_text='Blank for sites outside the dashboard scope.')
    reporting_scope = models.CharField(max_length=20, choices=Scope.choices, help_text='Outside-scope sites are excluded from every KPI.')
    site_type = models.CharField(max_length=60, blank=True)
    circle = models.CharField(max_length=20)
    circle_raw = models.CharField(max_length=60, blank=True)
    site_name = models.CharField(max_length=200, blank=True)
    village_code = models.CharField(max_length=100, blank=True)
    ba = models.CharField(max_length=100, blank=True)
    oa = models.CharField(max_length=100, blank=True)
    district = models.CharField(max_length=100, blank=True)
    sub_district = models.CharField(max_length=100, blank=True)
    site_address = models.TextField(blank=True)
    latitude = models.FloatField(null=True, blank=True)
    longitude = models.FloatField(null=True, blank=True)
    commissioning_status = models.CharField(max_length=40, blank=True)
    commissioning_date = models.DateField(null=True, blank=True)
    commissioning_raw = models.CharField(max_length=60, blank=True)
    om_status = models.CharField(max_length=40, blank=True)
    om_start_date = models.DateField(null=True, blank=True)
    om_start_raw = models.CharField(max_length=60, blank=True)
    om_start_date_issue = models.CharField(max_length=20, blank=True, choices=[('', 'None'), ('missing', 'O&M Start Date missing'), ('invalid', 'O&M Start Date unreadable')],
                                           help_text='Data-quality review flag: set when the matrix has no readable O&M Start Date.')
    on_air_status = models.CharField(max_length=40, blank=True)
    on_air = models.BooleanField(default=False, help_text='Matrix On-Air status = "Yes".')
    on_air_date = models.DateField(null=True, blank=True)
    on_air_date_issue = models.CharField(max_length=20, blank=True, choices=[('', 'None'), ('missing', 'Site On-Air Date missing'), ('invalid', 'Site On-Air Date unreadable')],
                                         help_text='Data-quality review flag: set when the matrix has no readable Site On-Air Date.')
    on_air_raw = models.CharField(max_length=60, blank=True)
    eb_status = models.CharField(max_length=40, blank=True)
    dg_status = models.CharField(max_length=40, blank=True)
    case_type = models.CharField(max_length=40, blank=True)
    smps_make = models.CharField(max_length=60, blank=True)
    remarks = models.TextField(blank=True)
    ci_emp_code = models.CharField(max_length=40, blank=True)
    ci_name = models.CharField(max_length=120, blank=True)
    ci_contact = models.CharField(max_length=60, blank=True)
    ie_emp_code = models.CharField(max_length=40, blank=True)
    ie_name = models.CharField(max_length=120, blank=True)
    ie_contact = models.CharField(max_length=60, blank=True)
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
    rigger_emp_code = models.CharField(max_length=40, blank=True)
    rigger_name = models.CharField(max_length=120, blank=True)
    rigger_contact = models.CharField(max_length=60, blank=True)
    # Matrix columns without a field above, as written.
    extra = models.JSONField(default=dict, blank=True)
    # Columns only the Uptime Master has (EB, OD EB working status, Solar Logic Done Date, ...), as written. They never
    # replace a matrix attribute.
    uptime_master_fields = models.JSONField(default=dict, blank=True)
    present_in_latest_matrix = models.BooleanField(default=True, help_text='False when the latest committed matrix no longer lists the site.')
    matrix_batch = models.ForeignKey(UploadBatch, on_delete=models.PROTECT, related_name='matrix_sites', help_text='Matrix upload that last set the attributes.')
    source_row = models.PositiveIntegerField(help_text='1-based row in the matrix file.')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        indexes = [models.Index(fields=['reporting_scope', 'technology', 'circle'])]
        constraints = [
            models.CheckConstraint(
                condition=(Q(reporting_scope='dashboard') & ~Q(technology='')) | (Q(reporting_scope='outside_scope') & Q(technology='')),
                name='sitedata_site_scope_technology'),
        ]

    def __str__(self):
        return f'{self.bsnl_site_id} ({self.entity}, {self.circle})'


class SiteIdentifier(models.Model):
    """An identifier of a site. Each identifier (per kind) names exactly one site."""

    class Kind(models.TextChoices):
        BSNL_SITE_ID = 'bsnl_site_id', 'BSNL Site ID'
        BTS_IP_ID = 'bts_ip_id', 'BTS IP ID'
        BAND_2100 = 'band_2100', 'BTS Site ID (2100 MHz, B1)'
        BAND_700 = 'band_700', 'BTS Site ID (700 MHz, B28)'
        MASTER_BTS_ID = 'master_bts_id', 'Master BTS ID'
        # An Admin-approved alternate ID of an existing master site, for Up-Time Report rows (unmatched.map_alternate).
        ALTERNATE_SITE_ID = 'alternate_site_id', 'Approved alternate site ID'

    site = models.ForeignKey(Site, on_delete=models.PROTECT, related_name='identifiers')
    kind = models.CharField(max_length=20, choices=Kind.choices)
    value = models.CharField(max_length=80, help_text='As written in the source.')
    key = models.CharField(max_length=80, help_text='Normalised (trimmed, upper case, inner spaces collapsed).')
    batch = models.ForeignKey(UploadBatch, on_delete=models.PROTECT, related_name='+')
    source_row = models.PositiveIntegerField(null=True, blank=True)
    mapping_row = models.ForeignKey('LweMappingRow', null=True, blank=True, on_delete=models.PROTECT, related_name='active_identifiers',
                                    help_text='The LWE Band ID mapping row that supplied this identifier (mapping identifiers only).')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=['kind', 'key'], name='sitedata_identifier_unique')]
        indexes = [models.Index(fields=['site', 'kind'])]

    def __str__(self):
        return f'{self.get_kind_display()} {self.value} -> {self.site_id}'


class LweMappingRow(models.Model):
    """One row of an LWE Band ID mapping workbook, as imported. Every import keeps all its rows (accepted, rejected and
    duplicate) and they are never deleted, so each workbook version stays traceable. The active mapping used at runtime
    is the SiteIdentifier rows that point here."""

    class Status(models.TextChoices):
        ACCEPTED = 'accepted', 'Accepted'
        REJECTED = 'rejected', 'Rejected'
        DUPLICATE = 'duplicate', 'Identical repeat of an earlier row of the file'

    class Change(models.TextChoices):
        NONE = '', 'Not applicable'
        ADDED = 'added', 'Added (site had no mapping)'
        CHANGED = 'changed', 'Changed (identifiers differ from the active mapping)'
        UNCHANGED = 'unchanged', 'Unchanged'

    batch = models.ForeignKey(UploadBatch, on_delete=models.PROTECT, related_name='mapping_rows')
    source_row = models.PositiveIntegerField(help_text='1-based row in the workbook.')
    circle_raw = models.CharField(max_length=60, blank=True)
    bts_ip_id_raw = models.CharField(max_length=200, blank=True)
    band_2100_raw = models.CharField(max_length=200, blank=True)
    band_700_raw = models.CharField(max_length=200, blank=True)
    master_id_raw = models.CharField(max_length=80, blank=True)
    master_key = models.CharField(max_length=80, blank=True)
    circle = models.CharField(max_length=20, blank=True, help_text='Circle code resolved from circle_raw.')
    site = models.ForeignKey(Site, null=True, blank=True, on_delete=models.PROTECT, related_name='mapping_rows', help_text='Master ID resolved to a site.')
    status = models.CharField(max_length=20, choices=Status.choices)
    change = models.CharField(max_length=20, choices=Change.choices, blank=True)
    reject_code = models.CharField(max_length=40, blank=True)
    reject_message = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=['batch', 'source_row'], name='sitedata_mapping_row_unique')]
        indexes = [models.Index(fields=['master_key']), models.Index(fields=['batch', 'status'])]

    def __str__(self):
        return f'{self.master_id_raw} (upload #{self.batch_id}, row {self.source_row}, {self.status})'


class LweMappingIdentifier(models.Model):
    """A normalised identifier of a mapping row (a cell can hold several, joined by ";;"). Not unique across rows or
    imports: history repeats identifiers; uniqueness of the active mapping is enforced by SiteIdentifier."""

    row = models.ForeignKey(LweMappingRow, on_delete=models.PROTECT, related_name='identifiers')
    kind = models.CharField(max_length=20, choices=SiteIdentifier.Kind.choices)
    value = models.CharField(max_length=80, help_text='As written (one token of the cell).')
    key = models.CharField(max_length=80)

    class Meta:
        constraints = [models.UniqueConstraint(fields=['row', 'kind', 'key'], name='sitedata_mapping_identifier_unique')]
        indexes = [models.Index(fields=['kind', 'key'])]


class IdentifierConflict(models.Model):
    """An identifier the matrix gives to more than one site (e.g. one band ID on several rows). It is never assigned or
    matched to any site, by the matrix, the LWE mapping or a raw CSV, while active. Kept for the exception report."""

    kind = models.CharField(max_length=20, choices=SiteIdentifier.Kind.choices)
    key = models.CharField(max_length=80)
    value = models.CharField(max_length=80, help_text='As written in the source.')
    claims = models.JSONField(default=list, help_text='[{"site_id", "circle", "entity", "row"}] of every site claiming it.')
    active = models.BooleanField(default=True, help_text='False once the latest matrix no longer gives it to several sites.')
    batch = models.ForeignKey(UploadBatch, on_delete=models.PROTECT, related_name='+', help_text='Matrix upload that last reported it.')
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=['kind', 'key'], name='sitedata_identifier_conflict_unique')]


class DailySitePerformance(models.Model):
    """The central daily record: one per site, reporting date and technology."""

    site = models.ForeignKey(Site, on_delete=models.PROTECT, related_name='daily')
    report_date = models.DateField()
    technology = models.CharField(max_length=20, choices=Technology.choices)
    circle = models.CharField(max_length=20, help_text='Circle of the site when the value was accepted.')
    availability_pct = models.FloatField()
    outage_minutes = models.FloatField(help_text='Over a full 24-hour reporting day: 1440 x (1 - availability / 100).')
    batch = models.ForeignKey(UploadBatch, on_delete=models.PROTECT, related_name='daily_records', help_text='Upload that set the current value.')
    source_row = models.PositiveIntegerField(null=True, blank=True, help_text='Row (or line) in the upload.')
    source_identifier = models.CharField(max_length=80, blank=True, help_text='Identifier the row used.')
    revision = models.PositiveIntegerField(default=1, help_text='1 = first accepted value; +1 per authorized correction.')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=['site', 'report_date', 'technology'], name='sitedata_daily_unique'),
            models.CheckConstraint(condition=Q(availability_pct__gte=0) & Q(availability_pct__lte=100), name='sitedata_daily_availability_range'),
            models.CheckConstraint(condition=Q(outage_minutes__gte=0) & Q(outage_minutes__lte=1440), name='sitedata_daily_outage_range'),
        ]
        indexes = [models.Index(fields=['report_date', 'technology', 'circle'])]


class AppendOnlyQuerySet(models.QuerySet):
    def update(self, **kwargs):
        raise PermissionDenied('Daily performance events are append-only.')

    def delete(self):
        raise PermissionDenied('Daily performance events are append-only.')


class DailyPerformanceEvent(models.Model):
    """Append-only log of conflicting values and authorized corrections of DailySitePerformance."""

    class Action(models.TextChoices):
        CONFLICT = 'conflict', 'Conflicting value not applied (stored value of equal or higher precedence kept)'
        SUPERSEDED = 'superseded', 'Stored value replaced by a source of higher precedence (Uptime Master over raw CSV)'
        CORRECTION = 'correction', 'Authorized correction applied'

    site = models.ForeignKey(Site, on_delete=models.PROTECT, related_name='+')
    report_date = models.DateField()
    technology = models.CharField(max_length=20, choices=Technology.choices)
    action = models.CharField(max_length=20, choices=Action.choices)
    proposed_availability_pct = models.FloatField()
    proposed_outage_minutes = models.FloatField()
    stored_availability_pct = models.FloatField(help_text='Value in the daily record at the time.')
    stored_outage_minutes = models.FloatField()
    batch = models.ForeignKey(UploadBatch, on_delete=models.PROTECT, related_name='+', help_text='Upload with the proposed value.')
    stored_batch = models.ForeignKey(UploadBatch, on_delete=models.PROTECT, related_name='+', help_text='Upload of the stored value.')
    source_row = models.PositiveIntegerField(null=True, blank=True)
    source_identifier = models.CharField(max_length=80, blank=True)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT, related_name='+')
    reason = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    objects = AppendOnlyQuerySet.as_manager()

    class Meta:
        ordering = ['-created_at']
        indexes = [models.Index(fields=['site', 'report_date']), models.Index(fields=['action', 'created_at'])]

    def save(self, *args, **kwargs):
        if self.pk:
            raise PermissionDenied('Daily performance events are append-only.')
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise PermissionDenied('Daily performance events are append-only.')


class MonthlySitePerformance(models.Model):
    """Site-wise monthly result. Revisions are kept; one current record per site, month and category."""

    class Category(models.TextChoices):
        DAILY_DERIVED = 'daily_derived', 'All reported days (outage-weighted)'
        OM_START = 'om_start', 'O&M Start days: reported days from the matrix O&M Start Date (outage-weighted)'
        ON_AIR = 'on_air', 'On-Air days: reported days from the matrix Site On-Air Date (outage-weighted)'

    site = models.ForeignKey(Site, on_delete=models.PROTECT, related_name='monthly')
    month = models.DateField(help_text='First day of the month.')
    technology = models.CharField(max_length=20, choices=Technology.choices)
    calculation_category = models.CharField(max_length=30, choices=Category.choices)
    total_outage_minutes = models.FloatField()
    availability_pct = models.FloatField(help_text='100 x (1 - total outage / (1440 x reporting days)).')
    reporting_days = models.PositiveSmallIntegerField(help_text='Days with a daily record (missing days are not counted as 0).')
    calendar_days = models.PositiveSmallIntegerField(help_text='Days of the month in the category (O&M Start: from the effective date).')
    effective_from = models.DateField(help_text='First day counted: the 1st, or the O&M Start Date when it falls in the month.')
    source_batches = models.JSONField(default=list, blank=True, help_text='Uploads of the daily records used.')
    revision = models.PositiveIntegerField(default=1)
    is_current = models.BooleanField(default=True)
    calculated_at = models.DateTimeField(auto_now_add=True)
    finalized_at = models.DateTimeField(null=True, blank=True)
    finalized_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT, related_name='+')

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=['site', 'month', 'calculation_category', 'revision'], name='sitedata_monthly_revision'),
            models.UniqueConstraint(fields=['site', 'month', 'calculation_category'], condition=Q(is_current=True), name='sitedata_monthly_current'),
            models.CheckConstraint(condition=Q(reporting_days__lte=F('calendar_days')), name='sitedata_monthly_days'),
        ]
        indexes = [models.Index(fields=['month', 'technology', 'is_current'])]


class ReportingUnit(models.Model):
    """A reporting unit: one circle and technology that submits its own daily CSV (approved rule B-1 / B-2). Expected on
    the dates from ``active_from`` to ``active_until`` (inclusive; open-ended when blank). Initially derived from the
    Consolidation Matrix; Admins add, deactivate and correct units, every change audited (ReportingUnitChange)."""

    technology = models.CharField(max_length=20, choices=Technology.choices)
    circle = models.CharField(max_length=20)
    active_from = models.DateField(help_text='First reporting date on which the unit is expected to submit data.')
    active_until = models.DateField(null=True, blank=True, help_text='Last expected reporting date (inclusive); blank = still active.')
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['technology', 'circle']
        constraints = [
            models.UniqueConstraint(fields=['technology', 'circle'], name='sitedata_reporting_unit_unique'),
            models.CheckConstraint(condition=Q(active_until__isnull=True) | Q(active_until__gte=F('active_from')), name='sitedata_reporting_unit_dates'),
        ]

    def __str__(self):
        return f'{self.technology} {self.circle}'

    def active_on(self, day) -> bool:
        return self.active_from <= day and (self.active_until is None or day <= self.active_until)


class ReportingUnitChange(models.Model):
    """Append-only audit trail of reporting-unit configuration changes (who, when, why, before and after)."""

    class Action(models.TextChoices):
        CREATED = 'created', 'Created'
        CORRECTED = 'corrected', 'Corrected'
        DEACTIVATED = 'deactivated', 'Deactivated'
        REACTIVATED = 'reactivated', 'Reactivated'

    unit = models.ForeignKey(ReportingUnit, on_delete=models.PROTECT, related_name='changes')
    action = models.CharField(max_length=20, choices=Action.choices)
    before = models.JSONField(default=dict, blank=True)
    after = models.JSONField(default=dict, blank=True)
    reason = models.TextField()
    user = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT, related_name='+')
    created_at = models.DateTimeField(auto_now_add=True)

    objects = AppendOnlyQuerySet.as_manager()

    class Meta:
        ordering = ['-created_at', '-id']

    def save(self, *args, **kwargs):
        if self.pk:
            raise PermissionDenied('Reporting-unit changes are append-only.')
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise PermissionDenied('Reporting-unit changes are append-only.')


class CoverageThreshold(models.Model):
    """The coverage threshold (approved rule B-6): the share of a unit's On-Air sites that must have a daily record for
    the unit-day to count as covered. Separate from the 98.5 % availability threshold. Effective-dated and append-only:
    each row records the new value, the previous value, the administrator, the time and the date it applies from, so
    earlier dates keep the threshold that applied to them."""

    value_pct = models.DecimalField(max_digits=5, decimal_places=2, help_text='Required coverage, 0-100 %.')
    previous_value_pct = models.DecimalField(max_digits=5, decimal_places=2, null=True, blank=True)
    effective_from = models.DateField(help_text='First reporting date the value applies to.')
    reason = models.TextField()
    changed_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT, related_name='+')
    changed_at = models.DateTimeField(auto_now_add=True)

    objects = AppendOnlyQuerySet.as_manager()

    class Meta:
        ordering = ['-effective_from', '-id']
        constraints = [models.CheckConstraint(condition=Q(value_pct__gte=0) & Q(value_pct__lte=100), name='sitedata_coverage_threshold_range')]

    def save(self, *args, **kwargs):
        if self.pk:
            raise PermissionDenied('Coverage threshold history is append-only.')
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise PermissionDenied('Coverage threshold history is append-only.')


class MonthFinalization(models.Model):
    """Finalization of a reporting month (approved rule B-7). A month may be finalized with missing data; it is then
    "Incomplete - Missing Data" and the missing unit-days are kept here. Late data after finalization needs the month to be
    reopened by an Admin with a reason (audited); the next finalization is a new revision."""

    class Status(models.TextChoices):
        COMPLETE = 'complete', 'Complete'
        INCOMPLETE = 'incomplete_missing_data', 'Incomplete — Missing Data'

    month = models.DateField(help_text='First day of the month.')
    revision = models.PositiveIntegerField(default=1)
    status = models.CharField(max_length=30, choices=Status.choices)
    missing = models.JSONField(default=list, blank=True, help_text='[{"technology", "circle", "dates": [...]}] not covered at finalization.')
    coverage = models.JSONField(default=dict, blank=True, help_text='Snapshot: dates, threshold(s) and covered unit-days at finalization.')
    finalized_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT, related_name='+')
    finalized_at = models.DateTimeField(auto_now_add=True)
    notes = models.TextField(blank=True)
    reopened_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT, related_name='+')
    reopened_at = models.DateTimeField(null=True, blank=True)
    reopen_reason = models.TextField(blank=True)

    class Meta:
        ordering = ['-month', '-revision']
        constraints = [
            models.UniqueConstraint(fields=['month', 'revision'], name='sitedata_month_finalization_revision'),
            models.UniqueConstraint(fields=['month'], condition=Q(reopened_at__isnull=True), name='sitedata_month_finalization_open'),
        ]
