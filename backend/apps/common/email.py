"""Shared email sending for CSV arrival reminders and personal emails.

Every email the portal sends goes through ``send_email``: manual reminders, personal
emails and, once it exists, the automatic reminder job. The transport is Django's
``EMAIL_BACKEND``, so Microsoft Graph can be plugged in later as an email backend
without touching callers.

Test mode: with the console (or another local) backend, emails are printed in the
backend terminal and never leave the machine. Results then say "printed", never "sent".
"""
import hashlib
import logging
from dataclasses import dataclass
from datetime import date

from django.conf import settings
from django.core.cache import cache
from django.core.exceptions import ValidationError as DjangoValidationError
from django.core.mail import EmailMessage, get_connection
from django.core.validators import validate_email

logger = logging.getLogger(__name__)

# Backends that never deliver to a real mailbox.
LOCAL_BACKENDS = {
    'django.core.mail.backends.console.EmailBackend',
    'django.core.mail.backends.locmem.EmailBackend',
    'django.core.mail.backends.filebased.EmailBackend',
    'django.core.mail.backends.dummy.EmailBackend',
}
MAX_RECIPIENTS = 20
MAX_SUBJECT = 200
MAX_BODY = 20_000
# The same reminder (circle, report, date, To recipients) is not sent twice within this window.
REMINDER_REPEAT_SECONDS = 120


class EmailRejected(Exception):
    """The request is invalid or not allowed; ``details`` maps fields to messages."""

    def __init__(self, message: str, details: dict | None = None, status: int = 400):
        super().__init__(message)
        self.details = details or {}
        self.status = status


class EmailFailed(Exception):
    """The transport raised an error; the message is safe to show to the user."""


def test_mode() -> bool:
    return settings.EMAIL_BACKEND in LOCAL_BACKENDS


def status() -> dict:
    """What the UI needs to label sending: test mode or live, and the sender."""
    return {
        'test_mode': test_mode(),
        'transport': 'console' if settings.EMAIL_BACKEND.endswith('console.EmailBackend') else settings.EMAIL_BACKEND.rsplit('.', 2)[-2],
        'from_email': settings.DEFAULT_FROM_EMAIL,
        'automatic_reminders': False,  # no scheduler exists yet
    }


def clean_addresses(value, field: str, required: bool) -> list[str]:
    """A list or comma/semicolon separated string of addresses, each validated."""
    if isinstance(value, str):
        items = [a.strip() for a in value.replace(';', ',').split(',')]
    elif isinstance(value, list) and all(isinstance(a, str) for a in value):
        items = [a.strip() for a in value]
    elif value is None:
        items = []
    else:
        raise EmailRejected('Invalid email request.', {field: ['Enter email addresses separated by commas.']})
    items = [a for a in items if a]
    if required and not items:
        raise EmailRejected('Invalid email request.', {field: ['Enter at least one recipient.']})
    invalid = []
    for address in items:
        try:
            validate_email(address)
        except DjangoValidationError:
            invalid.append(address)
    if invalid:
        raise EmailRejected('Invalid email request.', {field: [f'Not a valid email address: {", ".join(invalid)}.']})
    unique = list(dict.fromkeys(a.lower() for a in items))
    if len(unique) > MAX_RECIPIENTS:
        raise EmailRejected('Invalid email request.', {field: [f'At most {MAX_RECIPIENTS} addresses.']})
    return unique


def clean_text(subject, body) -> tuple[str, str]:
    errors = {}
    subject = subject.strip() if isinstance(subject, str) else ''
    body = body.strip() if isinstance(body, str) else ''
    if not subject:
        errors['subject'] = ['Enter a subject.']
    elif len(subject) > MAX_SUBJECT:
        errors['subject'] = [f'At most {MAX_SUBJECT} characters.']
    elif '\n' in subject or '\r' in subject:
        errors['subject'] = ['The subject must be a single line.']
    if not body:
        errors['body'] = ['Enter a message.']
    elif len(body) > MAX_BODY:
        errors['body'] = [f'At most {MAX_BODY:,} characters.']
    if errors:
        raise EmailRejected('Invalid email request.', errors)
    return subject, body


@dataclass(frozen=True)
class Reminder:
    circle: str
    report_type: str
    reporting_date: date
    # The configured deadline, as text, only when the user has configured one.
    deadline: str | None = None


def short_type(report_type: str) -> str:
    return '4G' if report_type == '4G Saturation' else report_type


def reminder_content(reminder: Reminder) -> tuple[str, str]:
    """The standard reminder. States only known facts: no deadline unless one is configured."""
    day = reminder.reporting_date.strftime('%d %b %Y')
    report = short_type(reminder.report_type)
    subject = f'Reminder: {report} uptime CSV for {reminder.circle}, {day}'
    due = f'It was due by {reminder.deadline}. ' if reminder.deadline else ''
    named = report if report == reminder.report_type else f'{report} ({reminder.report_type})'
    body = (
        'Dear Sir/Madam,\n\n'
        f'The daily {named} uptime CSV for circle {reminder.circle}, reporting date {day}, '
        f'has not been received yet. {due}Please share it at the earliest.\n\n'
        'If it has already been sent, please ignore this reminder.\n\n'
        'Regards,\nBSNL 4G Saturation & LWE Reporting'
    )
    return subject, body


def send_email(*, to: list[str], cc: list[str], subject: str, body: str, kind: str, event_key: str | None = None) -> dict:
    """Send one email through the configured backend. Callers pass already validated fields.

    ``event_key`` identifies a reminder event; the same event is not sent twice within
    ``REMINDER_REPEAT_SECONDS`` (guards double clicks now and the automatic job later).
    """
    cache_key = f'email-event:{hashlib.sha256(event_key.encode()).hexdigest()}' if event_key else None
    if cache_key and not cache.add(cache_key, 1, timeout=REMINDER_REPEAT_SECONDS):
        raise EmailRejected(
            'This reminder was just sent to the same recipients. Wait two minutes before sending it again.',
            {'code': 'duplicate'}, status=409)
    message = EmailMessage(subject=subject, body=body, from_email=settings.DEFAULT_FROM_EMAIL, to=to, cc=cc,
                           connection=get_connection(timeout=settings.EMAIL_TIMEOUT))
    try:
        count = message.send(fail_silently=False)
    except Exception as exc:  # transport errors vary by backend
        if cache_key:
            cache.delete(cache_key)  # a failed send may be retried at once
        logger.warning('Email (%s) failed: %s', kind, type(exc).__name__)
        raise EmailFailed('The email could not be sent: the mail server did not accept it. Nothing was delivered.') from exc
    if not count:
        raise EmailFailed('The email backend reported that nothing was sent.')
    local = test_mode()
    logger.info('Email (%s) %s: %d recipient(s)', kind, 'printed (test mode)' if local else 'handed to the mail server', len(to) + len(cc))
    return {
        'status': 'printed' if local else 'accepted',
        'test_mode': local,
        'kind': kind,
        'to': to,
        'cc': cc,
        'subject': subject,
        'message': ('TEST MODE: the email was printed in the backend terminal. It was not delivered to anyone.' if local
                    else 'The mail server accepted the email for delivery.'),
    }
