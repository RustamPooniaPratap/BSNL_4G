"""Files of the BSNL Module: Excel workbooks, .eml drafts (reference makeEml), the Word letter (reference letterDocHTML)
and the sanitising of edited letter HTML.

An .eml is an unsent draft ("X-Unsent: 1", no From): opening it in Outlook gives a ready-to-send message. Building one
never sends anything.
"""
from __future__ import annotations

import io
import re
from email.message import EmailMessage
from email.policy import SMTP
from html import escape
from html.parser import HTMLParser

from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill

XLSX = 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
DOC = 'application/msword'
EML = 'message/rfc822'
_BAD_SHEET = re.compile(r'[\\/?*\[\]:]')


def xlsx(sheets: list[dict]) -> bytes:
    """[{name, rows}] -> workbook bytes; the first row of each sheet is the header (reference xlsxB64)."""
    book = Workbook()
    book.remove(book.active)
    used: dict[str, int] = {}
    for sheet in sheets:
        name = _BAD_SHEET.sub(' ', sheet['name'])[:30] or 'Sheet'
        if name in used:
            used[name] += 1
            name = f'{name[:26]} {used[name]}'
        else:
            used[name] = 1
        ws = book.create_sheet(name)
        minute_columns = {
            index for index, value in enumerate(sheet['rows'][0] if sheet['rows'] else [])
            if 'outage minutes' in str(value).lower()
        }
        for i, row in enumerate(sheet['rows']):
            ws.append(['' if v is None else v for v in row])
            if i == 0:
                for cell in ws[1]:
                    cell.font = Font(bold=True, color='FFFFFF')
                    cell.fill = PatternFill('solid', fgColor='14325C')
            else:
                for index in minute_columns:
                    cell = ws.cell(row=i + 1, column=index + 1)
                    if isinstance(cell.value, (int, float)):
                        cell.number_format = '#,##,##0'
        ws.freeze_panes = 'A2'
    if not book.sheetnames:
        book.create_sheet('Sheet')
    out = io.BytesIO()
    book.save(out)
    return out.getvalue()


def eml(*, to: list[str], cc: list[str], subject: str, html: str, attachments: list[tuple[str, bytes, str]]) -> bytes:
    msg = EmailMessage(policy=SMTP)
    if to:
        msg['To'] = ', '.join(to)
    if cc:
        msg['Cc'] = ', '.join(cc)
    msg['Subject'] = subject
    msg['X-Unsent'] = '1'
    msg.set_content('This message is in HTML format.')
    msg.add_alternative(f'<html><body>{html}</body></html>', subtype='html')
    for name, content, mime in attachments:
        main, _, sub = mime.partition('/')
        msg.add_attachment(content, maintype=main, subtype=sub, filename=name)
    return msg.as_bytes()


def word_doc(title: str, letter_html: str, annexure_html: str) -> str:
    return ('<html xmlns:o="urn:schemas-microsoft-com:office:office" xmlns:w="urn:schemas-microsoft-com:office:word">'
            f'<head><meta charset="utf-8"><title>{escape(title)}</title></head>'
            f'<body style="font-family:Calibri,Arial,sans-serif;font-size:11pt">{letter_html}'
            f'<br style="page-break-before:always">{annexure_html}</body></html>')


def safe_name(text: str) -> str:
    return re.sub(r'[^\w\-]+', '_', text, flags=re.ASCII)


# --- Sanitising edited letters ----------------------------------------------------------------------------------------

ALLOWED_TAGS = {'p', 'br', 'b', 'strong', 'i', 'em', 'u', 'span', 'div', 'table', 'thead', 'tbody', 'tr', 'th', 'td',
                'h2', 'h3', 'h4', 'ul', 'ol', 'li', 'font'}
VOID = {'br'}
DROP_WITH_CONTENT = {'script', 'style', 'iframe', 'object', 'embed', 'template', 'noscript', 'svg', 'math', 'head', 'title'}
ALLOWED_ATTRS = {'style', 'colspan', 'rowspan', 'align'}
_STYLE_OK = re.compile(r'^[\w\s#%.,:;()\-\'"]*$')


class _Sanitizer(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.out: list[str] = []
        self.skip = 0
        self.open: list[str] = []

    def handle_starttag(self, tag, attrs):
        if tag in DROP_WITH_CONTENT:
            self.skip += 1
            return
        if self.skip or tag not in ALLOWED_TAGS:
            return
        kept = []
        for name, value in attrs:
            value = value or ''
            if name not in ALLOWED_ATTRS:
                continue
            if name == 'style' and (not _STYLE_OK.match(value) or re.search(r'url\s*\(|expression|javascript|@import|behavior', value, re.I)):
                continue
            if name in ('colspan', 'rowspan') and not value.isdigit():
                continue
            kept.append(f' {name}="{escape(value, quote=True)}"')
        self.out.append(f'<{tag}{"".join(kept)}>')
        if tag not in VOID:
            self.open.append(tag)

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)
        if tag in self.open and tag not in VOID:
            self.handle_endtag(tag)

    def handle_endtag(self, tag):
        if tag in DROP_WITH_CONTENT:
            self.skip = max(0, self.skip - 1)
            return
        if self.skip or tag not in ALLOWED_TAGS or tag in VOID or tag not in self.open:
            return
        while self.open:
            last = self.open.pop()
            self.out.append(f'</{last}>')
            if last == tag:
                break

    def handle_data(self, data):
        if not self.skip:
            self.out.append(escape(data, quote=False))

    def close(self):
        super().close()
        while self.open:
            self.out.append(f'</{self.open.pop()}>')


def sanitize(html: str) -> str:
    """Only formatting markup survives (no scripts, links, images, event handlers, URLs or unknown tags)."""
    parser = _Sanitizer()
    parser.feed(html or '')
    parser.close()
    return ''.join(parser.out)
