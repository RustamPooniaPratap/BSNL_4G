"""Import an LWE Band ID mapping workbook into the database (apps.sitedata.bandmap).

    python manage.py import_lwe_mapping "Data/reference/LWE Band ID.xlsx"            # preview: report + exception CSV
    python manage.py import_lwe_mapping "Data/reference/LWE Band ID.xlsx" --commit   # preview, then commit

The preview writes nothing to the mapping tables. Runs against the database of the active settings: the new tables
exist only where the sitedata migration has been applied (not the live database until the cutover is approved).
"""
import json
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from apps.sitedata import bandmap, uploads


class Command(BaseCommand):
    help = 'Preview (and optionally commit) an LWE Band ID mapping workbook.'

    def add_arguments(self, parser):
        parser.add_argument('workbook')
        parser.add_argument('--commit', action='store_true', help='Commit after the preview.')

    def handle(self, workbook, commit=False, **options):
        path = Path(workbook)
        if not path.is_file():
            raise CommandError(f'{path} does not exist.')
        batch = bandmap.preview(path, path.name)
        report = batch.report
        self.stdout.write(json.dumps({'upload': batch.pk, 'validation': batch.validation_status, 'error': batch.error,
                                      'counts': report.get('counts'), 'changes': report.get('changes'),
                                      'rejected_by_reason': report.get('rejected_by_reason'), 'quality': report.get('quality'),
                                      'exception_report': report.get('exception_report'), 'warnings': report.get('warnings')}, indent=1, default=str))
        if commit:
            try:
                bandmap.commit(batch)
            except uploads.UploadRejected as exc:
                raise CommandError(str(exc)) from exc
            self.stdout.write(self.style.SUCCESS(f'Committed upload #{batch.pk}.'))
