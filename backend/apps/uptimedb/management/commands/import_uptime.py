"""Preview or commit an Up-Time Report workbook import (same code as the Database import page).

    python manage.py import_uptime <workbook.xlsx> [--reconciliation <report.xlsx>]
    python manage.py import_uptime --commit <batch id> [--conflicts primary|reconciliation]

The first form only validates and prints the preview (no business data is written).
"""
import json
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from apps.uptimedb import datasource, importer
from apps.uptimedb.models import DataImportBatch


class Command(BaseCommand):
    help = 'Preview (default) or commit an Up-Time Report import into PostgreSQL.'

    def add_arguments(self, parser):
        parser.add_argument('workbook', nargs='?')
        parser.add_argument('--reconciliation')
        parser.add_argument('--commit', type=int, metavar='BATCH')
        parser.add_argument('--conflicts', choices=importer.CONFLICT_CHOICES, default='')
        parser.add_argument('--project', choices=importer.PROJECTS, help='For a sheet without a Project column.')
        parser.add_argument('--daily-only', action='store_true', help='Write only daily values, for sites already in the database.')

    def handle(self, *args, workbook=None, reconciliation=None, commit=None, conflicts='', project=None, daily_only=False, **options):
        try:
            if commit:
                batch = DataImportBatch.objects.filter(pk=commit).first()
                if batch is None:
                    raise CommandError(f'No import #{commit}.')
                batch = importer.commit(batch, conflict_source=conflicts)
                self.stdout.write(json.dumps({'batch': batch.pk, 'status': batch.status, 'counts': batch.counts,
                                              'database': datasource.completeness()}, indent=1, default=str))
                return
            if not workbook:
                raise CommandError('Give a workbook to preview, or --commit <batch id>.')
            path = Path(workbook)
            other = Path(reconciliation) if reconciliation else None
            for p in filter(None, [path, other]):
                if not p.is_file():
                    raise CommandError(f'{p} was not found.')
            batch = importer.preview(path, path.name, reconciliation=other, reconciliation_name=other.name if other else '',
                                     via='command', project=project, daily_only=daily_only)
        except importer.ImportRejected as exc:
            raise CommandError(str(exc)) from exc
        report = batch.report
        for role in ('primary', 'reconciliation'):
            part = report.get(role)
            if part:
                part = {k: v for k, v in part.items() if k not in ('all_issues',)}
                self.stdout.write(f'--- {role}\n' + json.dumps(part, indent=1, default=str))
        if 'comparison' in report:
            c = report['comparison']
            self.stdout.write('--- comparison\n' + json.dumps({**c, 'differences': {k: v['count'] for k, v in c['differences'].items()}}, indent=1))
        self.stdout.write(f"--- database effect {report['database_effect']}")
        if 'daily_effect' in report:
            self.stdout.write('--- daily-only effect\n' + json.dumps(report['daily_effect'], indent=1))
        self.stdout.write(self.style.SUCCESS(f'Preview saved as import #{batch.pk}. Commit with: manage.py import_uptime --commit {batch.pk}'
                                             + (' --conflicts primary|reconciliation' if 'comparison' in report else '')))
