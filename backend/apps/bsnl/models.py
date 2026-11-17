"""BSNL Module: Auto Email Reports and BSNL Letters (reference: Data/reference/4G_KPI_Report (2) 6.html).

Only what the portal did not already hold is stored here. Sites, daily uptime and RCA records stay in their own apps
(sitedata, rca) and are read, never copied:

- RcaBucketMapping: the approved RCA Final Bucket -> responsibility bucket (Own / Customer / Third party / Pending).
- DistributionRecipient: the reference's "Distribution Master" (To / Cc per Circle and report type).
- CircleLetterProfile: the reference's "BSNL Circle Contacts" and "Sender Details" sheets, one row per Circle.
- ReportRun: every report email sent (or attempted), scheduled or manual, with its result.
- BsnlLetter / LetterEvent / LetterSequence: the letter register with its controlled workflow and append-only history.
"""
from __future__ import annotations

from django.conf import settings
from django.core.exceptions import PermissionDenied
from django.db import models
from django.db.models import Q


class Bucket(models.TextChoices):
    OWN = 'Own', 'Own'
    CUSTOMER = 'Customer', 'Customer (BSNL)'
    THIRD_PARTY = 'Third party', 'Third party'
    PENDING = 'Pending', 'Pending'


class ReportType(models.TextChoices):
    D1 = 'D-1', 'D-1'
    WEEKLY = 'Weekly', 'Weekly'
    ALL_INDIA = 'All India', 'All India'
    LETTER = 'BSNL letter', 'BSNL letter'


class RcaBucketMapping(models.Model):
    """Responsibility bucket of one approved Final Bucket (apps.rca.taxonomy.APPROVED). Blank Final Buckets are Pending."""
    final_bucket = models.CharField(max_length=100, unique=True)
    bucket = models.CharField(max_length=12, choices=Bucket.choices)
    updated_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name='+')
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['final_bucket']

    def __str__(self):
        return f'{self.final_bucket} -> {self.bucket}'


class DistributionRecipient(models.Model):
    class Kind(models.TextChoices):
        TO = 'To', 'To'
        CC = 'Cc', 'Cc'

    circle = models.ForeignKey('organization.Circle', null=True, blank=True, on_delete=models.PROTECT, related_name='+',
                               help_text='Blank for the All India summary.')
    report_type = models.CharField(max_length=12, choices=ReportType.choices)
    name = models.CharField(max_length=120)
    designation = models.CharField(max_length=120, blank=True)
    email = models.EmailField(max_length=254)
    kind = models.CharField(max_length=2, choices=Kind.choices, default=Kind.TO)
    is_active = models.BooleanField(default=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name='+')
    updated_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name='+')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['report_type', 'circle__name', 'kind', 'name']
        constraints = [
            models.UniqueConstraint(fields=['circle', 'report_type', 'email'], condition=Q(circle__isnull=False),
                                    name='bsnl_recipient_circle_unique'),
            models.UniqueConstraint(fields=['report_type', 'email'], condition=Q(circle__isnull=True),
                                    name='bsnl_recipient_all_india_unique'),
        ]
        indexes = [models.Index(fields=['report_type', 'circle', 'is_active'], name='bsnl_recipient_lookup_idx')]


class CircleLetterProfile(models.Model):
    """Addressee (BSNL) and sender of a Circle's letters."""
    circle = models.OneToOneField('organization.Circle', on_delete=models.PROTECT, related_name='+')
    bsnl_designation = models.CharField(max_length=200, blank=True)
    bsnl_address = models.TextField(blank=True)
    sender_name = models.CharField(max_length=120, blank=True)
    sender_designation = models.CharField(max_length=200, blank=True)
    company = models.CharField(max_length=200, blank=True)
    updated_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name='+')
    updated_at = models.DateTimeField(auto_now=True)


class ReportRun(models.Model):
    class Trigger(models.TextChoices):
        SCHEDULE = 'schedule', 'Scheduled'
        MANUAL = 'manual', 'Manual'

    class Status(models.TextChoices):
        PROCESSING = 'processing', 'Processing'
        SENT = 'sent', 'Accepted by SMTP'
        FAILED = 'failed', 'Failed'
        SKIPPED = 'skipped', 'Skipped'

    report_type = models.CharField(max_length=12, choices=ReportType.choices)
    circle = models.ForeignKey('organization.Circle', null=True, blank=True, on_delete=models.PROTECT, related_name='+',
                               help_text='Blank for the All India summary.')
    project = models.CharField(max_length=20, blank=True, help_text='Site category filter; blank = all projects.')
    period_start = models.DateField()
    period_end = models.DateField()
    trigger = models.CharField(max_length=10, choices=Trigger.choices)
    # Scheduled runs only: "<type>|<circle or ALL>|<period start>", so a period is sent once even with two workers.
    slot_key = models.CharField(max_length=80, unique=True, null=True, blank=True)
    status = models.CharField(max_length=12, choices=Status.choices, default=Status.PROCESSING)
    to = models.JSONField(default=list, blank=True)
    cc = models.JSONField(default=list, blank=True)
    subject = models.CharField(max_length=250, blank=True)
    attachment_name = models.CharField(max_length=200, blank=True)
    smtp_response = models.CharField(max_length=500, blank=True)
    error = models.TextField(blank=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name='+')
    created_at = models.DateTimeField(auto_now_add=True)
    finished_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ['-created_at', '-id']
        indexes = [models.Index(fields=['report_type', 'period_start'], name='bsnl_run_period_idx')]


class LetterStatus(models.TextChoices):
    DRAFT = 'Draft', 'Draft'
    APPROVED = 'Approved', 'Approved'
    SENT = 'Sent', 'Sent'
    ACKNOWLEDGED = 'Acknowledged', 'Acknowledged'
    ACCEPTED = 'Exclusion accepted', 'Exclusion accepted'
    REJECTED = 'Exclusion rejected', 'Exclusion rejected'


class LetterSequence(models.Model):
    """Next reference number per Circle and month of the period (row-locked when a number is taken)."""
    circle = models.ForeignKey('organization.Circle', on_delete=models.PROTECT, related_name='+')
    year_month = models.CharField(max_length=6)
    next_number = models.PositiveIntegerField(default=1)

    class Meta:
        constraints = [models.UniqueConstraint(fields=['circle', 'year_month'], name='bsnl_letter_sequence_unique')]


class BsnlLetter(models.Model):
    class PeriodKind(models.TextChoices):
        D1 = 'd1', 'D-1'
        WEEK = 'week', 'Last week'
        PERIOD = 'period', 'Selected From–To'

    class SendStatus(models.TextChoices):
        NONE = '', 'Not sent'
        SENT = 'sent', 'Accepted by SMTP'
        FAILED = 'failed', 'Failed'

    reference = models.CharField(max_length=40, unique=True)
    circle = models.ForeignKey('organization.Circle', on_delete=models.PROTECT, related_name='+')
    project = models.CharField(max_length=20, blank=True, help_text='Site category filter; blank = all projects of the circle.')
    period_kind = models.CharField(max_length=8, choices=PeriodKind.choices)
    period_start = models.DateField()
    period_end = models.DateField(help_text='Inclusive.')
    letter_date = models.DateField()
    outage_count = models.PositiveIntegerField()
    site_count = models.PositiveIntegerField()
    total_hours = models.DecimalField(max_digits=12, decimal_places=2)
    generated_html = models.TextField(help_text='The letter as generated from the data (never edited).')
    edited_html = models.TextField(blank=True, help_text='The reviewed letter; blank while it has not been edited.')
    annexure = models.JSONField(default=list, help_text='Annexure rows as generated (the data the letter states).')
    causes = models.JSONField(default=list)
    recipients = models.JSONField(default=dict, help_text='{"to": [...], "cc": [...]} when generated, approved or sent.')
    status = models.CharField(max_length=20, choices=LetterStatus.choices, default=LetterStatus.DRAFT)
    prepared_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name='+')
    approved_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name='+')
    approved_at = models.DateTimeField(null=True, blank=True)
    sent_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name='+')
    sent_at = models.DateTimeField(null=True, blank=True)
    send_status = models.CharField(max_length=8, choices=SendStatus.choices, blank=True, default=SendStatus.NONE)
    send_error = models.TextField(blank=True)
    smtp_response = models.CharField(max_length=500, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at', '-id']
        constraints = [
            models.UniqueConstraint(fields=['circle', 'project', 'period_start', 'period_end'], name='bsnl_letter_period_unique'),
            models.CheckConstraint(condition=Q(period_end__gte=models.F('period_start')), name='bsnl_letter_period_order'),
        ]
        indexes = [models.Index(fields=['status', 'created_at'], name='bsnl_letter_status_idx')]

    def __str__(self):
        return self.reference

    @property
    def current_html(self) -> str:
        return self.edited_html or self.generated_html


class LetterEvent(models.Model):
    letter = models.ForeignKey(BsnlLetter, on_delete=models.PROTECT, related_name='events')
    action = models.CharField(max_length=30)
    status_before = models.CharField(max_length=20, blank=True)
    status_after = models.CharField(max_length=20, blank=True)
    note = models.TextField(blank=True)
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name='+')
    actor_name = models.CharField(max_length=150, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['created_at', 'id']

    def save(self, *args, **kwargs):
        if self.pk:
            raise PermissionDenied('Letter history is append-only.')
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise PermissionDenied('Letter history cannot be deleted.')
