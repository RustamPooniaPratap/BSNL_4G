"""Backfill daily outage from a day-wise outage workbook (sheet "Day Wise Outage") for sites already in the master.

    python manage.py import_daywise <workbook.xlsx> --project LWE                  # read-only reconciliation
    python manage.py import_daywise <workbook.xlsx> --project LWE --commit         # write, in one transaction
    python manage.py import_daywise <workbook.xlsx> --project LWE --commit --allow-rejected

The file path is always given explicitly; nothing reads it at runtime afterwards (a staged copy is kept with the batch).
Without --commit nothing is written. Conflicting stored values are never changed; rejected rows are never written.
"""
import json
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError
from django.db import connection

from apps.uptimedb import daywise
from apps.uptimedb.importer import PROJECTS


class Command(BaseCommand):
    help = 'Reconcile (default) or commit a day-wise outage backfill into the existing daily-performance table.'

    def add_arguments(self, parser):
        parser.add_argument('workbook')
        parser.add_argument('--project', choices=PROJECTS, required=True)
        parser.add_argument('--sheet', default=daywise.SHEET)
        parser.add_argument('--commit', action='store_true', help='Write the resolved site/days (default: report only).')
        parser.add_argument('--allow-rejected', action='store_true', help='Commit even though some rows could not be matched (they are not written).')
        parser.add_argument('--details', action='store_true', help='Also print the rejected rows, conflicts, invalid cells and flagged values.')

    def handle(self, *args, workbook, project, sheet, commit=False, allow_rejected=False, details=False, **options):
        path = Path(workbook)
        if not path.is_file():
            raise CommandError(f'{path} was not found.')
        db = connection.settings_dict
        self.stdout.write(f'Database: {connection.vendor} "{db["NAME"]}" on {db["HOST"] or "local socket"}:{db["PORT"] or "default"}')
        try:
            if commit:
                batch = daywise.commit(path, project, allow_rejected=allow_rejected)
                self.stdout.write(json.dumps({'batch': batch.pk, 'status': batch.status, 'counts': batch.counts,
                                              'summary': batch.report['summary']}, indent=1, default=str))
                return
            result = daywise.analyse(daywise.parse(path, filename=path.name, sheet=sheet), project)
        except daywise.DaywiseError as exc:
            raise CommandError(str(exc)) from exc
        out = daywise.report(result)
        self.stdout.write('Read only: nothing was written.\n' + json.dumps(out if details else out['summary'], indent=1, default=str))
