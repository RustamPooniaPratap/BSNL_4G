"""Sending BSNL Module emails through the portal's one outgoing account (Administration › Alert › Email setup).

Safeguards against accidental real sends:
1. Nothing is sent unless the server sets BSNL_EMAIL_SEND_ENABLED=true (environment; off by default, so development and
   test servers never send). Downloads (.eml / Excel / Word) never send.
2. The account must be the active, tested Alert account (apps.alerts.engine.active_account); no second SMTP setting.
3. Scheduled sending is off until an authorised user enables it (scheduler.SETTING), and each scheduled period of a
   report is sent at most once (ReportRun.slot_key).
"Accepted" means the SMTP server accepted the message; delivery to the mailbox is not known.
"""
from __future__ import annotations

import os

from django.db import IntegrityError, transaction
from django.utils import timezone

from apps.alerts import engine, mailer

from . import documents, letters
from .models import BsnlLetter, LetterStatus, ReportRun

ENV_FLAG = 'BSNL_EMAIL_SEND_ENABLED'


class SendingDisabled(Exception):
    pass


def sending_enabled() -> bool:
    return os.getenv(ENV_FLAG, 'false').strip().lower() in ('1', 'true', 'yes', 'on')


def require_enabled() -> None:
    if not sending_enabled():
        raise SendingDisabled(f'Email sending is disabled on this server ({ENV_FLAG} is not set to true). '
                              'Download the email instead, or ask the administrator to enable sending.')


def _send(to, cc, subject, html, files) -> str:
    account = engine.active_account()
    return mailer.send(account, mailer.Outgoing(to=list(to), cc=list(cc), bcc=[], subject=subject,
                                                text='This report is in HTML format.', html=html, files=files))


def send_report(report: dict, *, circle, trigger: str, user=None, slot_key: str | None = None) -> ReportRun | None:
    """Send one report email and record it. Returns None when a scheduled slot was already taken."""
    require_enabled()
    name = report['file'] + '.xlsx'
    try:
        with transaction.atomic():
            run = ReportRun.objects.create(
                report_type=report['report_type'], circle=circle, project=report.get('project', ''),
                period_start=report['period']['start'], period_end=report['period']['end'], trigger=trigger, slot_key=slot_key,
                to=report['to'], cc=report['cc'], subject=report['subject'][:250], attachment_name=name[:200], created_by=user)
    except IntegrityError:
        return None
    if not report['to']:
        run.status, run.error = ReportRun.Status.SKIPPED, 'No To recipients in the Distribution Master.'
    else:
        try:
            response = _send(report['to'], report['cc'], report['subject'], report['html'],
                             [(name, documents.xlsx(report['sheets']), documents.XLSX)])
            run.status, run.smtp_response = ReportRun.Status.SENT, response[:500]
        except (engine.NotReady, mailer.MailError, OSError) as exc:
            run.status, run.error = ReportRun.Status.FAILED, str(exc)[:2000]
    run.finished_at = timezone.now()
    run.save(update_fields=['status', 'smtp_response', 'error', 'finished_at'])
    return run


def send_letter(letter: BsnlLetter, user) -> BsnlLetter:
    """Send an Approved letter to its approved recipients; success makes it Sent, a failure keeps it Approved."""
    require_enabled()
    if letter.status != LetterStatus.APPROVED:
        raise letters.LetterConflict('Only an Approved letter can be sent.')
    rc = letter.recipients or {}
    if not rc.get('to'):
        raise letters.LetterError('The letter has no To recipient. Add the BSNL contact to the Distribution Master, '
                                  'return the letter to Draft and approve it again.')
    name = documents.safe_name(letter.reference)
    try:
        response = _send(rc['to'], rc.get('cc', []), letters.subject(letter),
                         f'<div style="font-family:Calibri,Arial,sans-serif;font-size:11pt">{letter.current_html}</div>',
                         [(f'{name}.doc', letters.doc_html(letter).encode('utf-8'), documents.DOC),
                          (f'Annexure_{name}.xlsx', letters.annexure_xlsx(letter.annexure), documents.XLSX)])
    except (engine.NotReady, mailer.MailError, OSError) as exc:
        letter.send_status, letter.send_error = BsnlLetter.SendStatus.FAILED, str(exc)[:2000]
        letter.save(update_fields=['send_status', 'send_error', 'updated_at'])
        letters.record(letter, 'send_failed', user, note=letter.send_error[:500])
        return letter
    letter.send_status, letter.send_error, letter.smtp_response = BsnlLetter.SendStatus.SENT, '', response[:500]
    letter.save(update_fields=['send_status', 'send_error', 'smtp_response', 'updated_at'])
    return letters.transition(letter, LetterStatus.SENT, user, note=f'Sent by email: {response[:200]}')
