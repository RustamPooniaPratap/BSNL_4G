"""Historical monthly Uptime import into MonthlySitePerformance (category historical_import; apps.sitedata.history).

    python manage.py uptime_history analyse [--out DIR]          # reads only: report + exception CSV, nothing written
    python manage.py uptime_history preview                      # stages the sources as previewed uploads (no monthly record)
    python manage.py uptime_history commit --batch N             # writes upload N's new and changed values
    python manage.py uptime_history retire --batch N --reason "" # withdraws upload N's records, restores earlier revisions

--confirm-full-month LWE:2026-07 releases a month held as MTD once it is confirmed to cover the whole month. Runs against
the database of the active settings: the historical category exists only where sitedata migration 0004 is applied.
"""
import json
from datetime import date
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from apps.sitedata import history
from apps.sitedata.models import UploadBatch


class Command(BaseCommand):
    help = 'Analyse, preview, commit or retire the historical monthly Uptime import.'

    def add_arguments(self, parser):
        parser.add_argument('action', choices=('analyse', 'preview', 'commit', 'retire'))
        parser.add_argument('--batch', type=int)
        parser.add_argument('--reason', default='')
        parser.add_argument('--out', help='Directory for the exception CSV (analyse).')
        parser.add_argument('--confirm-full-month', action='append', default=[], metavar='PROJECT:YYYY-MM')
        parser.add_argument('--consolidated')
        parser.add_argument('--lwe')
        parser.add_argument('--g4-check')

    def handle(self, action, batch=None, reason='', out=None, confirm_full_month=(), consolidated=None, lwe=None, g4_check=None, **options):
        try:
            if action in ('commit', 'retire'):
                upload = UploadBatch.objects.filter(pk=batch, kind=UploadBatch.Kind.UPTIME_HISTORY).first() if batch else None
                if upload is None:
                    raise CommandError('Give --batch with the id of a historical monthly upload.')
                if action == 'commit':
                    done = history.commit(upload)
                    self.stdout.write(json.dumps(done.report.get('committed'), indent=2))
                else:
                    self.stdout.write(json.dumps(history.retire(upload, reason=reason), indent=2))
                return
            confirmed = set()
            for item in confirm_full_month:
                project, _, month = item.partition(':')
                confirmed.add(({'4G': '4G Saturation'}.get(project, project), date.fromisoformat(f'{month}-01')))
            plan = history.default_plan(*(Path(p) if p else None for p in (consolidated, lwe, g4_check)))
            items = []
            for step in plan:
                kwargs = {'confirmed_full_months': confirmed, 'held_mtd': step['held_mtd'], 'cross_checks': step['cross_checks']}
                if action == 'preview':
                    upload = history.preview(step['path'], step['fmt'], step['allocation'], **kwargs)
                    self.stdout.write(f'Upload #{upload.pk} previewed: {upload.original_filename} ({upload.records_accepted} ready).')
                    continue
                analysis = history.analyse(step['path'], step['fmt'], step['allocation'], **kwargs)
                items += analysis['items']
                self.stdout.write(json.dumps(analysis['report'], indent=1, default=str))
            if action == 'analyse' and out:
                target = history.write_exception_csv(items, Path(out) / 'historical_monthly_exceptions.csv')
                self.stdout.write(f'Exceptions: {len(items)} -> {target}')
        except history.HistoryError as exc:
            raise CommandError(str(exc)) from exc
