"""Alert & Email Automation: the outgoing email account, automations, their runs, each email and each send attempt.

Kept small on purpose: templates are the two built-in layouts (mailer.TEMPLATES) whose subject and message an Admin
edits on the automation; reports are generated on demand by the existing report services (reports.py) and only their
names and sizes are stored. All state lives in PostgreSQL, so the worker (``manage.py run_alerts``) survives restarts.
"""
from django.conf import settings
from django.db import models


class EmailAccount(models.Model):
    """The approved outgoing account (one active at a time). The password is stored encrypted and never returned."""

    class Security(models.TextChoices):
        STARTTLS = 'starttls', 'STARTTLS'
        SSL = 'ssl', 'SSL/TLS'
        NONE = 'none', 'None (internal relay)'

    class Auth(models.TextChoices):
        PASSWORD = 'password', 'Username and password (SMTP AUTH)'
        NONE = 'none', 'No authentication (approved relay)'

    name = models.CharField(max_length=100)
    host = models.CharField(max_length=200)
    port = models.PositiveIntegerField(default=587)
    security = models.CharField(max_length=10, choices=Security.choices, default=Security.STARTTLS)
    auth = models.CharField(max_length=10, choices=Auth.choices, default=Auth.PASSWORD)
    username = models.CharField(max_length=200, blank=True)
    password_encrypted = models.TextField(blank=True)
    from_email = models.EmailField()
    from_name = models.CharField(max_length=100, blank=True)
    reply_to = models.EmailField(blank=True)
    timeout = models.PositiveSmallIntegerField(default=20)
    # Automated emails are sent only while active; activation needs a successful test email after the last change.
    is_active = models.BooleanField(default=False)
    tested_ok_at = models.DateTimeField(null=True, blank=True)
    last_test = models.CharField(max_length=500, blank=True)
    updated_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name='+')
    updated_at = models.DateTimeField(auto_now=True)


class AlertFile(models.Model):
    """An additional file an Admin uploaded to attach to an automation (validated type and size)."""
    name = models.CharField(max_length=200)
    stored_path = models.CharField(max_length=500)
    size = models.PositiveIntegerField()
    uploaded_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name='+')
    uploaded_at = models.DateTimeField(auto_now_add=True)


class Automation(models.Model):
    class Kind(models.TextChoices):
        CSV_REMINDER = 'csv_reminder', 'CSV Arrival Reminder'
        RCA_REMINDER = 'rca_reminder', 'RCA Submission Reminder'
        UPTIME_REPORT = 'uptime_report', 'Automatic Uptime Report'
        UPLOAD_FAILURE = 'upload_failure', 'Upload Failure Alert'
        CUSTOM = 'custom', 'Custom Scheduled Email'

    class Frequency(models.TextChoices):
        ONCE = 'once', 'One time'
        DAILY = 'daily', 'Daily'
        WEEKLY = 'weekly', 'Weekly'
        MONTHLY = 'monthly', 'Monthly'
        EVENT = 'event', 'When it happens'

    class Distribution(models.TextChoices):
        SAME = 'same', 'Same report for all recipients'
        PER_RECIPIENT = 'per_recipient', 'Relevant report per recipient'

    class Population(models.TextChoices):  # the values of apps.dashboard.metrics.SCOPES
        ON_AIR = 'on_air', 'On-Air sites'
        OM_START = 'om_start', 'O&M Start sites'

    name = models.CharField(max_length=150)
    kind = models.CharField(max_length=20, choices=Kind.choices)
    enabled = models.BooleanField(default=False)
    # Schedule (in ``timezone``): once at ``start_date`` + ``run_time``; daily; weekly on ``weekday`` (0 = Monday); monthly
    # on ``month_day`` (1-28, every month has it).
    frequency = models.CharField(max_length=10, choices=Frequency.choices, default=Frequency.DAILY)
    run_time = models.TimeField(default='09:00')
    timezone = models.CharField(max_length=50, default='Asia/Kolkata')
    weekday = models.PositiveSmallIntegerField(default=0)
    month_day = models.PositiveSmallIntegerField(default=1)
    start_date = models.DateField(null=True, blank=True)
    end_date = models.DateField(null=True, blank=True)
    next_run_at = models.DateTimeField(null=True, blank=True, db_index=True)
    # Scope: a project key and circle codes of the Organization ('' / [] = every one the recipients may see).
    project = models.CharField(max_length=20, blank=True)
    circles = models.JSONField(default=list, blank=True)
    report_day = models.CharField(max_length=10, default='yesterday', help_text='"today", "yesterday" or "latest" (latest date with data).')
    # Site population of the attached uptime reports (the portal's ``scope``): emailed reports use the same population as
    # the portal download. Existing automations default to On-Air, the portal's default population.
    population = models.CharField(max_length=10, choices=Population.choices, default=Population.ON_AIR,
                                  help_text='Site population of the attached uptime reports: On-Air or O&M Start sites.')
    # Recipients: portal users, external addresses, and for reminders / failures the responsible users of the circle.
    to_users = models.ManyToManyField(settings.AUTH_USER_MODEL, blank=True, related_name='+')
    to_emails = models.JSONField(default=list, blank=True)
    cc = models.JSONField(default=list, blank=True)
    bcc = models.JSONField(default=list, blank=True)
    include_responsible = models.BooleanField(default=True, help_text='Reminders: users granted the circle. Failures: the uploader.')
    # Attachments: [{"report": "daily_uptime", "format": "xlsx"}, ...] (reports.CATALOG) and an optional uploaded file.
    attachments = models.JSONField(default=list, blank=True)
    extra_file = models.ForeignKey(AlertFile, null=True, blank=True, on_delete=models.SET_NULL, related_name='+')
    distribution = models.CharField(max_length=15, choices=Distribution.choices, default=Distribution.SAME)
    template = models.CharField(max_length=10, default='reminder')  # mailer.TEMPLATES
    subject = models.CharField(max_length=200, blank=True)
    message = models.TextField(blank=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name='+')
    updated_at = models.DateTimeField(auto_now=True)
    last_run_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ['name']


class Execution(models.Model):
    """One run of an automation (scheduled, manual, an event, or a resend)."""

    class Status(models.TextChoices):
        QUEUED = 'queued', 'Queued'
        PROCESSING = 'processing', 'Processing'
        DONE = 'done', 'Done'
        PARTIAL = 'partial', 'Partly failed'
        FAILED = 'failed', 'Failed'
        SKIPPED = 'skipped', 'Nothing to send'

    automation = models.ForeignKey(Automation, null=True, on_delete=models.SET_NULL, related_name='executions')
    automation_name = models.CharField(max_length=150)
    trigger = models.CharField(max_length=10)  # schedule | manual | event | test
    scheduled_for = models.DateTimeField(null=True, blank=True)
    # Duplicate-send guard: one run per (automation, schedule slot) and per event.
    dedupe_key = models.CharField(max_length=200, null=True, blank=True, unique=True)
    event = models.JSONField(default=dict, blank=True)
    status = models.CharField(max_length=12, choices=Status.choices, default=Status.QUEUED)
    detail = models.TextField(blank=True)
    requested_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name='+')
    created_at = models.DateTimeField(auto_now_add=True)
    started_at = models.DateTimeField(null=True, blank=True)
    finished_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ['-created_at', '-id']


class Message(models.Model):
    """One email of a run. ``accepted`` means the mail server accepted it; delivery to the inbox is not known."""

    class Status(models.TextChoices):
        QUEUED = 'queued', 'Queued'
        PROCESSING = 'processing', 'Processing'
        ACCEPTED = 'accepted', 'Accepted by SMTP'
        FAILED = 'failed', 'Failed'

    execution = models.ForeignKey(Execution, on_delete=models.CASCADE, related_name='messages')
    resend_of = models.ForeignKey('self', null=True, blank=True, on_delete=models.SET_NULL, related_name='resends')
    to = models.JSONField(default=list)
    cc = models.JSONField(default=list, blank=True)
    bcc = models.JSONField(default=list, blank=True)
    recipient_names = models.JSONField(default=list, blank=True)
    subject = models.CharField(max_length=300)
    html = models.TextField()
    text = models.TextField()
    # [{"name", "report", "format", "period", "size"}]; the files themselves are regenerated for a retry.
    attachments = models.JSONField(default=list, blank=True)
    attachment_spec = models.JSONField(default=dict, blank=True)  # how to regenerate them (reports.build)
    status = models.CharField(max_length=12, choices=Status.choices, default=Status.QUEUED)
    error = models.TextField(blank=True)
    smtp_response = models.CharField(max_length=500, blank=True)
    attempts = models.PositiveSmallIntegerField(default=0)
    next_retry_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    sent_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ['-created_at', '-id']
        indexes = [models.Index(fields=['status', 'next_retry_at'])]


class Attempt(models.Model):
    """Each try to send a message (automatic retries and manual Retry are kept, never overwritten)."""
    message = models.ForeignKey(Message, on_delete=models.CASCADE, related_name='attempt_log')
    at = models.DateTimeField(auto_now_add=True)
    ok = models.BooleanField()
    detail = models.CharField(max_length=500)
    by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name='+')

    class Meta:
        ordering = ['at', 'id']

