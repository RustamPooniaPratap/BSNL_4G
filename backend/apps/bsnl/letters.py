"""BSNL Letters: the reference ``custOutages`` / ``letterHTML`` / ``annexHTML`` on the portal's RCA records.

Outage selection (decision 17 Nov 2026; the portal holds no outage start / end times):
- the records are the active RCA records (apps.rca.RcaRecord) of the Circle, optionally of one project (site category);
- only the Customer (BSNL) bucket is kept (common.bucket_of with RcaBucketMapping: BSNL OFC and BSNL Media by default);
- a record belongs to a period when its reporting date is within the period: an RCA record is one site-day, so clipping
  the outage to the period (reference ``a = max(start, ps)``, ``b = min(end, pe)``) is exact at day level and every
  duration is the record's own outage minutes / 60. There are no open-ended records, so no cut-off is needed;
- the RCA records carry no planned / unplanned flag, so no record is excluded as planned;
- rows are ordered by reporting date, then Site ID (reference: by outage start).
The annexure shows the reporting date as Start and End, which is the period the duration was measured in.
"""
from __future__ import annotations

from collections import OrderedDict
from datetime import date

from django.db import IntegrityError, transaction
from django.utils import timezone
from html import escape

from apps.organization.models import Circle

from . import documents
from .common import Period, d_long, d_short, fmt, rca_rows, whole_minutes
from .models import Bucket, BsnlLetter, CircleLetterProfile, LetterEvent, LetterSequence, LetterStatus, ReportType
from .reports import recipients

ANNEX_HEADERS = ['#', 'Site ID', 'Cluster', 'NE', 'Start', 'End', 'Outage Minutes', 'RCA', 'Ticket']
ANNEX_XLSX_HEADERS = ['#', 'Site ID', 'Site Name', 'Circle', 'Cluster', 'NE', 'Outage Start', 'Outage End',
                      'Outage Minutes', 'RCA', 'Bucket', 'Ticket No']
TRANSITIONS = {
    LetterStatus.DRAFT: {LetterStatus.APPROVED},
    LetterStatus.APPROVED: {LetterStatus.SENT, LetterStatus.DRAFT},
    LetterStatus.SENT: {LetterStatus.ACKNOWLEDGED, LetterStatus.ACCEPTED, LetterStatus.REJECTED},
    LetterStatus.ACKNOWLEDGED: {LetterStatus.ACCEPTED, LetterStatus.REJECTED},
    LetterStatus.ACCEPTED: set(),
    LetterStatus.REJECTED: set(),
}


class LetterError(Exception):
    status_code = 400


class LetterConflict(LetterError):
    status_code = 409


def latest_rca_date() -> date | None:
    from apps.rca.models import RcaRecord
    return RcaRecord.objects.order_by('-reporting_date').values_list('reporting_date', flat=True).first()


def cust_outages(circle: str, period: Period, *, project: str = '', pairs=None) -> list[dict]:
    """Customer (BSNL)-bucket RCA records of a Circle in the period, with site attributes and the matching ticket."""
    from apps.sitedata.models import Site
    from apps.tickets.models import Ticket

    rows = [r for r in rca_rows(period, circles=[circle], projects=[project] if project else None, pairs=pairs)
            if r['bucket'] == Bucket.CUSTOMER]
    keys = {r['site_key'] for r in rows}
    sites = {s['site_key']: s for s in Site.objects.filter(site_key__in=keys).values('site_key', 'site_name', 'ci_name', 'ie_name')}
    tickets: dict[tuple, list[str]] = {}
    for t in Ticket.objects.filter(site_key__in=keys, outage_date__gte=period.start, outage_date__lte=period.end).order_by('portal_ticket_id') \
            .values('site_key', 'outage_date', 'portal_ticket_id'):
        tickets.setdefault((t['site_key'], t['outage_date']), []).append(t['portal_ticket_id'])
    out = []
    for r in sorted(rows, key=lambda x: (x['reporting_date'], x['site_key'], x['id'])):
        site = sites.get(r['site_key'], {})
        minutes = float(r['outage_minutes'] or 0.0)
        out.append({
            'site_id': r['site_id'], 'site_name': r['site_name'] or site.get('site_name', ''), 'circle': r['circle'],
            'project': r['project'], 'cluster': (site.get('ci_name') or '').strip() or 'Unassigned',
            'ne': (site.get('ie_name') or '').strip() or 'Unassigned', 'date': r['reporting_date'].isoformat(),
            'start': r['reporting_date'].isoformat(), 'end': r['reporting_date'].isoformat(),
            'outage_minutes': minutes, 'hours': round(minutes / 60.0, 4),
            'rca': (r['rca_text'] or '').strip() or r['cause'], 'cause': r['cause'], 'final_bucket': r['final'],
            'bucket': r['bucket'], 'ticket': ', '.join(tickets.get((r['site_key'], r['reporting_date']), [])),
        })
    return out


def row_minutes(row: dict) -> float:
    if row.get('outage_minutes') is not None:
        return float(row['outage_minutes'])
    return float(row.get('hours') or 0.0) * 60.0


def summary(rows: list[dict]) -> dict:
    minutes = sum(row_minutes(r) for r in rows)
    return {'outages': len(rows), 'sites': len({r['site_id'] for r in rows}),
            'outage_minutes': whole_minutes(minutes), 'hours': round(minutes / 60.0, 2)}


def causes(rows: list[dict]) -> list[dict]:
    by: dict[str, dict] = OrderedDict()
    for r in rows:
        c = by.setdefault(r['cause'], {'cause': r['cause'], 'outages': 0, 'outage_minutes': 0.0, 'hours': 0.0})
        c['outages'] += 1
        minutes = row_minutes(r)
        c['outage_minutes'] += minutes
        c['hours'] += minutes / 60.0
    return sorted(by.values(), key=lambda c: (-c['outage_minutes'], c['cause']))


def _date(iso: str) -> date:
    return date.fromisoformat(iso)


def letter_html(circle: Circle, period: Period, rows: list[dict], ref: str, letter_date: date) -> str:
    profile = CircleLetterProfile.objects.filter(circle=circle).first()
    per = f'{d_long(period.start)} to {d_long(period.end)}'
    s = summary(rows)
    td = 'border:1px solid #999;padding:4px 8px'
    desig = escape(profile.bsnl_designation) if profile and profile.bsnl_designation else '[BSNL designation]'
    addr = escape(profile.bsnl_address).replace('\n', '<br>') if profile and profile.bsnl_address else '[BSNL address]'
    sender = [escape(v) if v else ph for v, ph in ((profile and profile.sender_name, '[Sender name]'),
                                                    (profile and profile.sender_designation, '[Designation]'),
                                                    (profile and profile.company, '[Company]'))]
    cause_rows = ''.join(f'<tr><td style="{td}">{escape(c["cause"])}</td><td style="{td};text-align:right">{c["outages"]}</td>'
                         f'<td style="{td};text-align:right">{fmt(whole_minutes(c["outage_minutes"]))}</td></tr>' for c in causes(rows))
    name = escape(circle.name)
    return (f'<p style="display:flex;justify-content:space-between"><span>Ref: <b>{escape(ref)}</b></span><span>Date: {d_long(letter_date)}</span></p>'
            f'<p>To,<br>{desig}<br>Bharat Sanchar Nigam Limited, {name} Circle<br>{addr}</p>'
            f'<p><b>Subject: Site outages attributable to BSNL – {name} Circle – {per}</b></p>'
            '<p>Dear Sir / Madam,</p>'
            f'<p>During {per}, <b>{s["outages"]}</b> outages at <b>{s["sites"]}</b> 4G sites in {name} Circle, totalling '
            f'<b>{fmt(s["outage_minutes"])} Outage Minutes</b>, were caused by reasons within BSNL\'s scope. The site-wise details with start time, '
            'end time, outage minutes and RCA are given in the annexure.</p>'
            '<p>Summary by cause:</p>'
            f'<table style="border-collapse:collapse;font-size:13px"><tr><th style="{td};background:#eee;text-align:left">Cause</th>'
            f'<th style="{td};background:#eee;text-align:right">Outages</th><th style="{td};background:#eee;text-align:right">Outage Minutes</th></tr>'
            f'{cause_rows}<tr><td style="{td}"><b>Total</b></td><td style="{td};text-align:right"><b>{s["outages"]}</b></td>'
            f'<td style="{td};text-align:right"><b>{fmt(s["outage_minutes"])}</b></td></tr></table>'
            '<p>We request you to kindly note these outages as BSNL-attributable and exclude them from the uptime / SLA calculation '
            'for the period, and to take necessary action to avoid recurrence.</p>'
            f'<p>Thanks and regards,<br><br>{sender[0]}<br>{sender[1]}<br>{sender[2]}</p>'
            f'<p>Encl.: Annexure – outage details ({s["outages"]} rows)</p>')


def annexure_html(rows: list[dict]) -> str:
    td = 'border:1px solid #999;padding:3px 6px;font-size:11px'
    head = ''.join(f'<th style="{td};background:#eee;text-align:left">{h}</th>' for h in ANNEX_HEADERS)
    body = ''.join(
        f'<tr><td style="{td}">{i}</td><td style="{td}">{escape(r["site_id"])}</td><td style="{td}">{escape(r["cluster"])}</td>'
        f'<td style="{td}">{escape(r["ne"])}</td><td style="{td}">{d_long(_date(r["start"]))}</td><td style="{td}">{d_long(_date(r["end"]))}</td>'
        f'<td style="{td};text-align:right">{fmt(whole_minutes(row_minutes(r)))}</td><td style="{td}">{escape(r["rca"])}</td><td style="{td}">{escape(r["ticket"])}</td></tr>'
        for i, r in enumerate(rows, 1))
    return (f'<h3 style="font-size:14px">Annexure – BSNL-attributable outages</h3>'
            f'<p style="font-size:11px">Start and End are the RCA reporting date; Outage Minutes are the duration recorded for that day.</p>'
            f'<table style="border-collapse:collapse"><tr>{head}</tr>{body}</table>')


def annexure_xlsx(rows: list[dict]) -> bytes:
    data = [ANNEX_XLSX_HEADERS] + [[i, r['site_id'], r['site_name'], r['circle'], r['cluster'], r['ne'], r['start'], r['end'],
                                    whole_minutes(row_minutes(r)), r['rca'], r['bucket'], r['ticket']] for i, r in enumerate(rows, 1)]
    return documents.xlsx([{'name': 'Annexure', 'rows': data}])


def display_generated_html(letter: BsnlLetter) -> str:
    if letter.annexure and any(row.get('outage_minutes') is None for row in letter.annexure):
        return letter_html(letter.circle, Period(letter.period_start, letter.period_end), letter.annexure,
                           letter.reference, letter.letter_date)
    return letter.generated_html


def display_html(letter: BsnlLetter) -> str:
    return letter.edited_html or display_generated_html(letter)


def doc_html(letter: BsnlLetter) -> str:
    return documents.word_doc(letter.reference, display_html(letter), annexure_html(letter.annexure))


def subject(letter: BsnlLetter) -> str:
    return (f'Site outages attributable to BSNL – {letter.circle.name} Circle – {d_short(letter.period_start)} to '
            f'{d_short(letter.period_end)} (Ref {letter.reference})')


def eml(letter: BsnlLetter) -> bytes:
    rc = letter.recipients or {}
    name = documents.safe_name(letter.reference)
    return documents.eml(to=rc.get('to', []), cc=rc.get('cc', []), subject=subject(letter),
                         html=f'<div style="font-family:Calibri,Arial,sans-serif;font-size:11pt">{display_html(letter)}</div>',
                         attachments=[(f'{name}.doc', doc_html(letter).encode('utf-8'), documents.DOC),
                                      (f'Annexure_{name}.xlsx', annexure_xlsx(letter.annexure), documents.XLSX)])


# --- Persistence -----------------------------------------------------------------------------------------------------

def next_reference(circle: Circle, period: Period) -> str:
    """CODE/BSNL/YYYYMM/NNN, numbered per Circle and month of the period start under a row lock (never collides)."""
    ym = f'{period.start.year}{period.start.month:02d}'
    with transaction.atomic():
        LetterSequence.objects.get_or_create(circle=circle, year_month=ym)
        seq = LetterSequence.objects.select_for_update().get(circle=circle, year_month=ym)
        number = seq.next_number
        seq.next_number += 1
        seq.save(update_fields=['next_number'])
    return f'{circle.code}/BSNL/{ym}/{number:03d}'


def record(letter: BsnlLetter, action: str, user, *, before: str = '', after: str = '', note: str = '') -> None:
    name = (user.get_full_name() or user.get_username()) if user is not None and user.is_authenticated else 'system'
    LetterEvent.objects.create(letter=letter, action=action, status_before=before, status_after=after, note=note, actor=user if user and user.is_authenticated else None,
                               actor_name=name)


def _content(letter: BsnlLetter, rows: list[dict]) -> None:
    period = Period(letter.period_start, letter.period_end)
    s = summary(rows)
    letter.outage_count, letter.site_count, letter.total_hours = s['outages'], s['sites'], s['hours']
    letter.annexure, letter.causes = rows, [{**c, 'hours': round(c['hours'], 4)} for c in causes(rows)]
    letter.generated_html = letter_html(letter.circle, period, rows, letter.reference, letter.letter_date)
    letter.recipients = recipients(letter.circle.code, ReportType.LETTER)


def open_letter(circle: Circle, period: Period, kind: str, *, project: str, user, pairs) -> tuple[BsnlLetter, bool]:
    existing = BsnlLetter.objects.filter(circle=circle, project=project, period_start=period.start, period_end=period.end).first()
    if existing:
        return existing, False
    rows = cust_outages(circle.code, period, project=project, pairs=pairs)
    if not rows:
        raise LetterError(f'No Customer (BSNL)-bucket outages in {circle.name} for this period, so no letter is needed.')
    try:
        with transaction.atomic():
            letter = BsnlLetter(circle=circle, project=project, period_kind=kind, period_start=period.start, period_end=period.end,
                                letter_date=timezone.localdate(), prepared_by=user, reference=next_reference(circle, period))
            _content(letter, rows)
            letter.save()
            record(letter, 'generated', user, after=LetterStatus.DRAFT,
                   note=f'{letter.outage_count} outages, {fmt(summary(rows)["outage_minutes"])} Outage Minutes')
    except IntegrityError:  # another user opened the same letter at the same moment
        return BsnlLetter.objects.get(circle=circle, project=project, period_start=period.start, period_end=period.end), False
    return letter, True


def regenerate(letter: BsnlLetter, user, pairs) -> BsnlLetter:
    with transaction.atomic():
        letter = BsnlLetter.objects.select_for_update().select_related('circle').get(pk=letter.pk)
        if letter.status != LetterStatus.DRAFT:
            raise LetterConflict('Only a Draft letter can be regenerated.')
        rows = cust_outages(letter.circle.code, Period(letter.period_start, letter.period_end), project=letter.project, pairs=pairs)
        letter.letter_date = timezone.localdate()
        _content(letter, rows)
        had_edits = bool(letter.edited_html)
        letter.edited_html = ''
        letter.save()
        record(letter, 'regenerated', user,
               note=f'{letter.outage_count} outages, {fmt(summary(rows)["outage_minutes"])} Outage Minutes'
               + ('; edits discarded' if had_edits else ''))
    return letter


def save_edit(letter: BsnlLetter, html: str, user) -> BsnlLetter:
    clean = documents.sanitize(html).strip()
    if not clean:
        raise LetterError('The letter cannot be empty.')
    if len(clean) > 500_000:
        raise LetterError('The letter is too long.')
    with transaction.atomic():
        letter = BsnlLetter.objects.select_for_update().get(pk=letter.pk)
        if letter.status != LetterStatus.DRAFT:
            raise LetterConflict('Only a Draft letter can be edited.')
        letter.edited_html = '' if clean == letter.generated_html else clean
        letter.save(update_fields=['edited_html', 'updated_at'])
        record(letter, 'edited' if letter.edited_html else 'edits_reverted', user)
    return letter


def transition(letter: BsnlLetter, target: str, user, *, note: str = '') -> BsnlLetter:
    with transaction.atomic():
        letter = BsnlLetter.objects.select_for_update().select_related('circle').get(pk=letter.pk)
        if target not in TRANSITIONS.get(letter.status, set()):
            raise LetterConflict(f'A letter in status "{letter.status}" cannot become "{target}".')
        before = letter.status
        letter.status = target
        fields = ['status', 'updated_at']
        if target == LetterStatus.APPROVED:
            letter.approved_by, letter.approved_at = user, timezone.now()
            letter.recipients = recipients(letter.circle.code, ReportType.LETTER)
            fields += ['approved_by', 'approved_at', 'recipients']
        if target == LetterStatus.DRAFT:
            letter.approved_by, letter.approved_at = None, None
            fields += ['approved_by', 'approved_at']
        if target == LetterStatus.SENT and not letter.sent_at:
            letter.sent_by, letter.sent_at = user, timezone.now()
            fields += ['sent_by', 'sent_at']
        letter.save(update_fields=fields)
        record(letter, 'status', user, before=before, after=target, note=note)
    return letter
