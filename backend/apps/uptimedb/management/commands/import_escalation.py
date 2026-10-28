"""Preview or commit a Consolidated Escalation Matrix import ("Raw Data" sheet).

    python manage.py import_escalation [<matrix.xlsx>]     # preview; default: the latest matrix in Data/reference
    python manage.py import_escalation --commit <batch id>

The preview writes no site rows; it prints the parse summary and the cross-check with the Up-Time Report tables.
"""
import json
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from apps.dashboard.activity import source_file
from apps.uptimedb import escalation
from apps.uptimedb.models import EscalationImportBatch


class Command(BaseCommand):
    help = 'Preview (default) or commit a Consolidated Escalation Matrix import into PostgreSQL.'

    def add_arguments(self, parser):
        parser.add_argument('matrix', nargs='?')
        parser.add_argument('--commit', type=int, metavar='BATCH')

    def handle(self, *args, matrix=None, commit=None, **options):
        try:
            if commit:
                batch = EscalationImportBatch.objects.filter(pk=commit).first()
                if batch is None:
                    raise CommandError(f'No escalation import #{commit}.')
                batch = escalation.commit(batch)
                self.stdout.write(json.dumps({'batch': batch.pk, 'status': batch.status, 'counts': batch.counts}, indent=1))
                return
            path = Path(matrix) if matrix else source_file()
            if path is None or not path.is_file():
                raise CommandError(f'{matrix or "No escalation matrix in Data/reference"} was not found.')
            batch = escalation.preview(path, path.name)
        except escalation.EscalationRejected as exc:
            raise CommandError(str(exc)) from exc
        self.stdout.write(json.dumps(batch.report, indent=1, default=str))
        self.stdout.write(f'\nPreviewed as import #{batch.pk}. Commit with: python manage.py import_escalation --commit {batch.pk}')
