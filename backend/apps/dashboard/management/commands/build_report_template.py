"""Build the clean template for the Full Consolidated Report from a consolidated workbook (run once by a developer).

    python manage.py build_report_template "<4G_LWE_Consolidated ….xlsx>"

The source is read once and never needed again: the output (apps/dashboard/report_templates/consolidated_template.xlsx)
keeps the 13 sheets, their order and visibility, styles, column widths, row heights, merged cells, freeze panes and
header rows, but no report data: every site row of "Up-Time Report" is removed (row 3 stays, emptied, as the style
prototype), every number, date and formula in the summary sheets is cleared, and the hand-maintained sheets keep only
their titles and headers (no names, phone numbers or counts).
"""
from datetime import date, datetime
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError
from openpyxl import load_workbook

from apps.dashboard.report_export import TEMPLATE_PATH, UPTIME_SHEET

# Hand-maintained sheets: only rows containing a header ("Circle", "Bucket", "IE name"…) or a title above one keep text.
MANUAL_SHEETS = ('Repeated Sites', 'Signoff status', "CI's Performance", "IE's Performance", 'One Pager Summary', 'Bucketization')
HEADER_WORDS = ('circle', 'bucket', "ci's name", 'ie name')


def _is_data(value) -> bool:
    return isinstance(value, (int, float, date, datetime)) or (isinstance(value, str) and value.startswith('='))


class Command(BaseCommand):
    help = 'Build the clean consolidated-report template from a consolidated workbook.'

    def add_arguments(self, parser):
        parser.add_argument('workbook')

    def handle(self, *args, workbook, **options):
        source = Path(workbook)
        if not source.is_file():
            raise CommandError(f'{source} was not found.')
        wb = load_workbook(source)
        if UPTIME_SHEET not in wb.sheetnames:
            raise CommandError(f'No "{UPTIME_SHEET}" sheet in {source.name}.')
        for ws in wb.worksheets:
            if ws.title == UPTIME_SHEET:
                ws.delete_rows(4, ws.max_row)
                for cell in ws[3]:
                    cell.value = None
                for cell in ws[1]:
                    cell.value = None  # SUBTOTAL formulas are written again for the exported rows
                ws.conditional_formatting = type(ws.conditional_formatting)()
                continue
            header_rows = set()
            if ws.title in MANUAL_SHEETS:
                for row in ws.iter_rows():
                    if any(isinstance(c.value, str) and c.value.strip().lower() in HEADER_WORDS for c in row):
                        header_rows.update({row[0].row, row[0].row - 1})
            for row in ws.iter_rows():
                for cell in row:
                    if cell.value is None or type(cell).__name__ == 'MergedCell':
                        continue
                    if _is_data(cell.value) or (ws.title in MANUAL_SHEETS and cell.row not in header_rows):
                        cell.value = None
            for chart in list(ws._charts):
                ws._charts.remove(chart)
        TEMPLATE_PATH.parent.mkdir(parents=True, exist_ok=True)
        wb.save(TEMPLATE_PATH)
        self.stdout.write(f'Template written: {TEMPLATE_PATH} ({TEMPLATE_PATH.stat().st_size:,} bytes), sheets: {wb.sheetnames}')
