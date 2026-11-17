"""The Alert worker and scheduler: ``manage.py run_alerts`` (keeps running) or ``--once`` (one pass, for cron / Task Scheduler).

All schedules and runs are in PostgreSQL, so stopping and starting the worker loses nothing: due runs are queued on the
next pass, each schedule slot only once. Run one worker process (a second one is safe: work is claimed with row locks).
"""
import logging
import time

from django.core.management.base import BaseCommand

from apps.alerts.engine import tick

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = 'Run the Alert & Email Automation scheduler and worker.'

    def add_arguments(self, parser):
        parser.add_argument('--once', action='store_true', help='One pass, then exit.')
        parser.add_argument('--interval', type=int, default=30, help='Seconds between passes (default 30).')

    def handle(self, *args, **options):
        while True:
            try:
                counts = tick()
                if any(counts.values()):
                    self.stdout.write(f'Alerts: {counts}')
            except Exception:  # keep the worker alive; the error is logged and the next pass retries
                logger.exception('Alert worker pass failed')
            try:  # BSNL Module scheduled reports (apps/bsnl/scheduler.py): off unless enabled; isolated from the alerts
                from apps.bsnl.scheduler import tick as bsnl_tick
                sent = bsnl_tick()
                if any(sent.values()):
                    self.stdout.write(f'BSNL reports: {sent}')
            except Exception:
                logger.exception('BSNL scheduled report pass failed')
            if options['once']:
                return
            time.sleep(max(5, options['interval']))
