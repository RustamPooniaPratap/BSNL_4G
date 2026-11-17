from django.conf import settings
from django.core.exceptions import PermissionDenied
from django.db import models
from django.utils import timezone

from apps.sitedata.models import Site


class TicketStatus(models.TextChoices):
    OPEN = 'Open', 'Open'
    CLOSED = 'Closed', 'Closed'


class TicketUploadBatch(models.Model):
    class Status(models.TextChoices):
        PREVIEWED = 'previewed', 'Previewed'
        COMMITTED = 'committed', 'Committed'
        FAILED = 'failed', 'Failed'
        DISCARDED = 'discarded', 'Discarded'

    original_filename = models.CharField(max_length=255)
    checksum_sha256 = models.CharField(max_length=64, db_index=True)
    file_size = models.PositiveIntegerField()
    uploaded_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name='+')
    uploaded_at = models.DateTimeField(auto_now_add=True)
    committed_at = models.DateTimeField(null=True, blank=True)
    status = models.CharField(max_length=12, choices=Status.choices, default=Status.PREVIEWED)
    counts = models.JSONField(default=dict, blank=True)
    duplicate_of = models.ForeignKey('self', null=True, blank=True, on_delete=models.SET_NULL, related_name='reuploads')
    error = models.TextField(blank=True)

    class Meta:
        ordering = ['-uploaded_at', '-id']

    def __str__(self):
        return f'#{self.pk} {self.original_filename} ({self.status})'


class TicketSequence(models.Model):
    year = models.PositiveSmallIntegerField(unique=True)
    next_number = models.PositiveIntegerField(default=1)


class Ticket(models.Model):
    portal_ticket_id = models.CharField(max_length=24, unique=True)
    source_serial = models.CharField(max_length=50, blank=True)
    outage_date = models.DateField()
    project = models.CharField(max_length=20)
    circle = models.CharField(max_length=20)
    master_site = models.ForeignKey(Site, null=True, blank=True, on_delete=models.PROTECT, related_name='ofc_tickets')
    site_id = models.CharField(max_length=60)
    site_key = models.CharField(max_length=80)
    site_name = models.CharField(max_length=200, blank=True)
    oa = models.CharField(max_length=100, blank=True)
    ba = models.CharField(max_length=100, blank=True)
    actual_down_time = models.DateTimeField()
    reporting_time_to_partner = models.DateTimeField(null=True, blank=True)
    restoration_time = models.DateTimeField(null=True, blank=True)
    outage_minutes = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    mttr_hours = models.DecimalField(max_digits=10, decimal_places=4, null=True, blank=True)
    vendor_name = models.CharField(max_length=200, blank=True)
    outage_bucket = models.CharField(max_length=120, blank=True)
    detail_rca = models.TextField(blank=True)
    status = models.CharField(max_length=10, choices=TicketStatus.choices, default=TicketStatus.OPEN)
    email_id = models.EmailField(max_length=254)
    source_values = models.JSONField(default=dict, blank=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name='+')
    updated_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name='+')
    created_batch = models.ForeignKey(TicketUploadBatch, null=True, on_delete=models.SET_NULL, related_name='created_tickets')
    last_batch = models.ForeignKey(TicketUploadBatch, null=True, on_delete=models.SET_NULL, related_name='updated_tickets')
    last_uploaded_at = models.DateTimeField()
    closure_remarks = models.TextField(blank=True)
    closed_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name='+')
    closed_at = models.DateTimeField(null=True, blank=True)
    closure_source = models.CharField(max_length=16, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at', '-id']
        constraints = [
            models.UniqueConstraint(fields=['site_key', 'outage_date', 'actual_down_time'], name='ticket_outage_match_unique'),
        ]
        indexes = [
            models.Index(fields=['project', 'circle', 'status'], name='ticket_scope_status_idx'),
            models.Index(fields=['outage_date'], name='ticket_outage_date_idx'),
            models.Index(fields=['vendor_name'], name='ticket_vendor_idx'),
        ]

    def __str__(self):
        return self.portal_ticket_id


class TicketEvent(models.Model):
    class Source(models.TextChoices):
        EXCEL = 'excel_import', 'Excel Import'
        MANUAL = 'manual', 'Manual'

    ticket = models.ForeignKey(Ticket, on_delete=models.PROTECT, related_name='events')
    batch = models.ForeignKey(TicketUploadBatch, null=True, blank=True, on_delete=models.SET_NULL, related_name='events')
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name='+')
    actor_name = models.CharField(max_length=150, blank=True)
    action = models.CharField(max_length=32)
    source = models.CharField(max_length=16, choices=Source.choices)
    status_before = models.CharField(max_length=10, blank=True)
    status_after = models.CharField(max_length=10, blank=True)
    remarks = models.TextField(blank=True)
    changes = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['created_at', 'id']
        indexes = [models.Index(fields=['ticket', 'created_at'], name='ticket_event_history_idx')]

    def save(self, *args, **kwargs):
        if self.pk:
            raise PermissionDenied('Ticket history is append-only.')
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise PermissionDenied('Ticket history cannot be deleted.')


class TicketNotification(models.Model):
    class Kind(models.TextChoices):
        CREATED = 'created', 'New ticket'
        UPDATED = 'updated', 'Ticket updated'
        REOPENED = 'reopened', 'Ticket reopened'

    class Status(models.TextChoices):
        PENDING = 'pending', 'Pending'
        ACCEPTED = 'accepted', 'Accepted by SMTP'
        FAILED = 'failed', 'Failed'

    ticket = models.ForeignKey(Ticket, on_delete=models.PROTECT, related_name='notifications')
    batch = models.ForeignKey(TicketUploadBatch, null=True, blank=True, on_delete=models.SET_NULL, related_name='notifications')
    kind = models.CharField(max_length=12, choices=Kind.choices)
    recipient = models.EmailField(max_length=254)
    subject = models.CharField(max_length=250)
    text_body = models.TextField()
    html_body = models.TextField()
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.PENDING)
    attempts = models.PositiveSmallIntegerField(default=0)
    sent_at = models.DateTimeField(null=True, blank=True)
    error = models.TextField(blank=True)
    smtp_response = models.CharField(max_length=500, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at', '-id']
        indexes = [models.Index(fields=['status', 'created_at'], name='ticket_notification_status_idx')]


class TicketNotificationAttempt(models.Model):
    notification = models.ForeignKey(TicketNotification, on_delete=models.PROTECT, related_name='attempt_log')
    number = models.PositiveSmallIntegerField()
    attempted_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name='+')
    attempted_at = models.DateTimeField(default=timezone.now)
    accepted_at = models.DateTimeField(null=True, blank=True)
    accepted = models.BooleanField()
    detail = models.CharField(max_length=2000, blank=True)

    class Meta:
        ordering = ['number']
        constraints = [models.UniqueConstraint(fields=['notification', 'number'], name='ticket_notification_attempt_unique')]


class TicketImportRow(models.Model):
    batch = models.ForeignKey(TicketUploadBatch, on_delete=models.CASCADE, related_name='rows')
    excel_row = models.PositiveIntegerField()
    preview_outcome = models.CharField(max_length=24)
    result_outcome = models.CharField(max_length=24, blank=True)
    row_data = models.JSONField(default=dict, blank=True)
    errors = models.JSONField(default=list, blank=True)
    ticket = models.ForeignKey(Ticket, null=True, blank=True, on_delete=models.SET_NULL, related_name='import_rows')
    notification = models.ForeignKey(TicketNotification, null=True, blank=True, on_delete=models.SET_NULL, related_name='import_rows')

    class Meta:
        ordering = ['excel_row']
        constraints = [models.UniqueConstraint(fields=['batch', 'excel_row'], name='ticket_import_row_unique')]
