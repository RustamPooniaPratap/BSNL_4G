"""Content of the technician outage notification (subject, plain text and HTML).

The recipient is a field technician or partner contact who has no portal account. The email is informational only:
it carries the ticket's outage details and nothing that grants access. It contains no portal link, login or
password-reset instruction, token or closure action. Ticket closure is done by an authorized user inside the portal.

The layout lives in ``email_templates/outage_notification.html`` (with ``outage_notification_row.html`` for each detail
row) and ``outage_notification.txt``, so it can be changed without touching ticket creation or sending
(``services.send_notification``). The files use ``string.Template`` placeholders (``${name}``); every value is
HTML-escaped before it is placed in the HTML layout. (Django's template engine is not used: its test instrumentation
fails on this project's Python version with Django 5.1.)
"""
from __future__ import annotations

from datetime import datetime
from functools import lru_cache
from html import escape
from pathlib import Path
from string import Template

from django.utils import timezone

TEMPLATE_DIR = Path(__file__).resolve().parent / 'email_templates'

HEADINGS = {
    'created': 'New OFC Outage Ticket',
    'updated': 'OFC Outage Ticket Updated',
    'reopened': 'OFC Outage Ticket Reopened',
}
INTROS = {
    'created': 'An OFC outage has been recorded for a site under your responsibility. The outage details are below.',
    'updated': 'The details of an OFC outage ticket for a site under your responsibility have been updated. The current details are below.',
    'reopened': 'An OFC outage ticket for a site under your responsibility has been reopened. The current details are below.',
}
NOTICE = ('This is an informational notification only. No reply or action through this email is required. '
          'Ticket closure is handled by the authorized BSNL team.')


def _when(value: datetime | None) -> str:
    return timezone.localtime(value).strftime('%d %b %Y, %H:%M') if value else ''


def _number(value) -> str:
    return '' if value is None else format(value.normalize(), 'f') if hasattr(value, 'normalize') else str(value)


def detail_rows(ticket) -> list[tuple[str, str]]:
    """(label, value) of the ticket's outage details. Empty optional values are left out."""
    rows = [
        ('Ticket ID', ticket.portal_ticket_id),
        ('Reporting Date', ticket.outage_date.strftime('%d %b %Y') if ticket.outage_date else ''),
        ('Circle', ticket.circle),
        ('Site ID', ticket.site_id),
        ('Site Name', ticket.site_name),
        ('OA', ticket.oa),
        ('BA', ticket.ba),
        ('Actual Down Time', _when(ticket.actual_down_time)),
        ('Reporting Time to Partner', _when(ticket.reporting_time_to_partner)),
        ('Restoration Time', _when(ticket.restoration_time)),
        ('Outage Minutes', _number(ticket.outage_minutes)),
        ('MTTR (Hours)', _number(ticket.mttr_hours)),
        ('Vendor Name', ticket.vendor_name),
        ('Outage Bucket', ticket.outage_bucket),
        ('Detailed RCA', ticket.detail_rca),
        ('Recipient Email', ticket.email_id),
    ]
    return [(label, str(value).strip()) for label, value in rows if value not in (None, '') and str(value).strip()]


@lru_cache(maxsize=None)
def _template(name: str) -> Template:
    return Template((TEMPLATE_DIR / name).read_text(encoding='utf-8'))


def render(ticket, kind: str) -> tuple[str, str, str]:
    heading = HEADINGS[kind]
    subject = f'{heading} – {ticket.portal_ticket_id} – {ticket.site_name or ticket.site_id}'.replace('\n', ' ')[:250]
    rows = detail_rows(ticket)
    values = {'subject': subject, 'heading': heading, 'ticket_id': ticket.portal_ticket_id, 'intro': INTROS[kind], 'notice': NOTICE}
    text = _template('outage_notification.txt').substitute(values, rows='\n'.join(f'{label}: {value}' for label, value in rows))
    row = _template('outage_notification_row.html')
    html_rows = ''.join(row.substitute(label=escape(label), value=escape(value)) for label, value in rows)
    html = _template('outage_notification.html').substitute({k: escape(v) for k, v in values.items()}, rows=html_rows)
    return subject, text, html
