"""Email account, templates and sending for the Alert module.

- The SMTP password is encrypted with Fernet (key: ALERT_ENCRYPTION_KEY, or derived from SECRET_KEY). It is never
  returned to the browser or written to a log; changing the key means re-entering the password.
- Two built-in layouts (``TEMPLATES``): reminder / alert and report distribution, in HTML and plain text. An Admin
  edits only the subject and the message; placeholders are {{name}} and every value is HTML-escaped.
- Sending uses Django's SMTP backend with the stored account. "Accepted" means the server accepted the message;
  delivery to the mailbox is not known.
"""
from __future__ import annotations

import base64
import hashlib
import html
import os
import re
from dataclasses import dataclass

from cryptography.fernet import Fernet, InvalidToken
from django.conf import settings
from django.core.mail import EmailMultiAlternatives
from django.core.mail.backends.smtp import EmailBackend
from django.utils import timezone

from .models import EmailAccount

PORTAL_URL = os.getenv('PORTAL_URL', 'http://localhost:5173')


def _fernet() -> Fernet:
    key = os.getenv('ALERT_ENCRYPTION_KEY') or base64.urlsafe_b64encode(hashlib.sha256(f'alerts:{settings.SECRET_KEY}'.encode()).digest()).decode()
    return Fernet(key.encode())


def encrypt(password: str) -> str:
    return _fernet().encrypt(password.encode()).decode() if password else ''


def decrypt(token: str) -> str:
    if not token:
        return ''
    try:
        return _fernet().decrypt(token.encode()).decode()
    except InvalidToken as exc:
        raise MailError('The stored password cannot be read (the encryption key changed). Enter the password again.') from exc


class MailError(Exception):
    """A safe message for the user (never contains the password)."""


def connection(account: EmailAccount) -> EmailBackend:
    password = decrypt(account.password_encrypted) if account.auth == EmailAccount.Auth.PASSWORD else ''
    return EmailBackend(host=account.host, port=account.port, username=account.username if account.auth == EmailAccount.Auth.PASSWORD else '',
                        password=password, use_tls=account.security == EmailAccount.Security.STARTTLS,
                        use_ssl=account.security == EmailAccount.Security.SSL, timeout=account.timeout, fail_silently=False)


def safe_error(exc: Exception) -> str:
    """The server's reason without any secret (SMTP errors carry the server text, never our password)."""
    text = str(getattr(exc, 'smtp_error', b'') or exc)
    if isinstance(getattr(exc, 'smtp_error', None), bytes):
        text = exc.smtp_error.decode(errors='replace')
    code = getattr(exc, 'smtp_code', None)
    return f'{type(exc).__name__}{f" {code}" if code else ""}: {text}'[:480]


def test_connection(account: EmailAccount) -> str:
    conn = connection(account)
    try:
        conn.open()
    except Exception as exc:  # network, TLS and authentication errors differ by server
        raise MailError(f'Connection failed: {safe_error(exc)}') from exc
    finally:
        try:
            conn.close()
        except Exception:  # noqa: S110 - closing a failed connection
            pass
    return f'Connected to {account.host}:{account.port} and signed in.' if account.auth == EmailAccount.Auth.PASSWORD else f'Connected to {account.host}:{account.port}.'


@dataclass
class Outgoing:
    to: list[str]
    cc: list[str]
    bcc: list[str]
    subject: str
    text: str
    html: str
    files: list[tuple[str, bytes, str]]  # (name, content, mimetype)


def send(account: EmailAccount, out: Outgoing) -> str:
    """Send one email; returns the server's acceptance note. Raises MailError with a safe reason."""
    sender = f'{account.from_name} <{account.from_email}>' if account.from_name else account.from_email
    msg = EmailMultiAlternatives(subject=out.subject, body=out.text, from_email=sender, to=out.to, cc=out.cc, bcc=out.bcc,
                                 reply_to=[account.reply_to] if account.reply_to else None, connection=connection(account))
    msg.attach_alternative(out.html, 'text/html')
    for name, content, mime in out.files:
        msg.attach(name, content, mime)
    try:
        count = msg.send(fail_silently=False)
    except Exception as exc:
        raise MailError(safe_error(exc)) from exc
    if not count:
        raise MailError('The mail server did not accept the message.')
    return f'Accepted by {account.host} at {timezone.localtime():%d %b %Y %H:%M}.'


# --- Templates -----------------------------------------------------------------------------------

PLACEHOLDERS = ('recipient_name', 'notification_title', 'notification_message', 'project_name', 'circle_name', 'report_date', 'status',
                'generated_at', 'report_name', 'report_period', 'portal_url', 'population')
TEMPLATES = {
    'reminder': {'label': 'Reminder / Alert', 'subject': 'Action Required – {{notification_title}} | {{circle_name}} | {{report_date}}'},
    'report': {'label': 'Report distribution', 'subject': '{{report_name}} – {{report_period}}'},
}
DEFAULT_MESSAGES = {
    'reminder': '{{notification_message}}',
    'report': 'Please find attached the requested report generated from the BSNL Reporting Portal.',
}
_TOKEN = re.compile(r'{{\s*([a-z_]+)\s*}}')


def unknown_placeholders(*texts: str) -> list[str]:
    return sorted({m for t in texts for m in _TOKEN.findall(t or '') if m not in PLACEHOLDERS})


def fill(text: str, values: dict, *, escape: bool) -> str:
    return _TOKEN.sub(lambda m: (html.escape(str(values.get(m.group(1), ''))) if escape else str(values.get(m.group(1), ''))), text or '')


def render(template: str, subject: str, message: str, values: dict, attachments: list[dict]) -> tuple[str, str, str]:
    """(subject, plain text, HTML) of one email. Rows whose value is empty are left out."""
    values = {'portal_url': PORTAL_URL, 'generated_at': timezone.localtime().strftime('%d %b %Y %H:%M'), **values}
    subj = fill(subject or TEMPLATES[template]['subject'], values, escape=False).replace('\n', ' ')[:250]
    body = message or DEFAULT_MESSAGES[template]
    rows = ([('Project', 'project_name'), ('Circle', 'circle_name'), ('Reporting Date', 'report_date'), ('Current Status', 'status')]
            if template == 'reminder' else
            [('Report', 'report_name'), ('Project', 'project_name'), ('Circle', 'circle_name'), ('Site Population', 'population'),
             ('Reporting Period', 'report_period'), ('Generated At', 'generated_at')])
    rows = [(label, str(values[key])) for label, key in rows if values.get(key)]
    e = html.escape
    title = values.get('notification_title') if template == 'reminder' else values.get('report_name')
    text_lines = ['BSNL 4G Saturation & LWE Reporting Portal', '', title or '', '', f"Dear {values.get('recipient_name') or 'Colleague'},", '',
                  fill(body, values, escape=False), ''] + [f'{label}: {v}' for label, v in rows]
    if attachments:
        text_lines += ['', 'Attachments:'] + [f"- {a['name']} ({a.get('period', '')}, {a.get('format', '').upper()})" for a in attachments]
    text_lines += ['', 'Please take the required action through the reporting portal.' if template == 'reminder' else 'The selected reports are attached to this email.',
                   f'Open Reporting Portal: {values["portal_url"]}', '', 'Regards,', 'BSNL Reporting Portal',
                   f"Automated notification generated on {values['generated_at']}."]
    table = ''.join(f'<tr><td style="padding:6px 10px;border:1px solid #e2e8f0;background:#f8fafc;color:#475569;width:38%">{e(label)}</td>'
                    f'<td style="padding:6px 10px;border:1px solid #e2e8f0;font-weight:600">{e(v)}</td></tr>' for label, v in rows)
    files = ''.join(f'<li>{e(a["name"])} <span style="color:#64748b">({e(str(a.get("period", "")))}, {e(str(a.get("format", "")).upper())})</span></li>'
                    for a in attachments)
    # The Admin's own text is escaped too (not only the values): nothing typed into a message becomes HTML.
    body_html = '<br>'.join(fill(e(line), values, escape=True) for line in body.split('\n'))
    html_doc = f"""<!doctype html><html><body style="margin:0;background:#f1f5f9;font-family:Segoe UI,Arial,sans-serif;color:#0f172a">
<table role="presentation" width="100%" cellpadding="0" cellspacing="0"><tr><td align="center" style="padding:24px 12px">
<table role="presentation" width="100%" style="max-width:600px;background:#ffffff;border-radius:12px;overflow:hidden;border:1px solid #e2e8f0">
<tr><td style="background:#1f3864;color:#ffffff;padding:16px 24px;font-size:15px;font-weight:600">BSNL 4G Saturation &amp; LWE Reporting Portal</td></tr>
<tr><td style="padding:24px">
<h1 style="margin:0 0 16px;font-size:20px">{e(title or '')}</h1>
<p style="margin:0 0 12px">Dear {e(values.get('recipient_name') or 'Colleague')},</p>
<p style="margin:0 0 16px;line-height:1.5">{body_html}</p>
{f'<table role="presentation" width="100%" style="border-collapse:collapse;font-size:14px;margin:0 0 16px">{table}</table>' if table else ''}
{f'<p style="margin:0 0 6px;font-weight:600">Attachments</p><ul style="margin:0 0 16px;padding-left:18px">{files}</ul>' if files else ''}
<p style="margin:0 0 16px">{'Please take the required action through the reporting portal.' if template == 'reminder' else 'The selected reports are attached to this email.'}</p>
<a href="{e(values['portal_url'])}" style="display:inline-block;background:#1f3864;color:#ffffff;text-decoration:none;padding:10px 18px;border-radius:8px;font-weight:600">Open Reporting Portal</a>
</td></tr>
<tr><td style="padding:14px 24px;background:#f8fafc;color:#64748b;font-size:12px">BSNL Reporting Portal<br>Automated notification generated on {e(values['generated_at'])}.</td></tr>
</table></td></tr></table></body></html>"""
    return subj, '\n'.join(text_lines), html_doc
