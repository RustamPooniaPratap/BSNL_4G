"""Scheduled Auto Email Reports: Daily D-1 at 09:00 IST and Weekly every Monday at 10:00 IST.

Runs inside the portal's existing worker (``manage.py run_alerts``, which calls ``tick`` on every pass; ``--once`` for
Task Scheduler / cron). Nothing is scheduled unless an authorised user enables it (SETTING) and the server allows
sending (delivery.sending_enabled). Each report period is sent once per Circle (ReportRun.slot_key), so a restart or a
second worker never sends twice.

D-1 is the latest complete reporting date of the uptime data: if yesterday's data is not complete at 09:00, the report
goes out on the first pass after it is (and a period already sent is never sent again).
"""
from __future__ import annotations

import logging
from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo

from django.utils import timezone

from apps.common.models import Setting

from . import delivery, reports
from .common import DAILY_HOUR, TIMEZONE, WEEKLY_DAY, WEEKLY_HOUR, report_period
from .models import ReportRun, ReportType

logger = logging.getLogger(__name__)
SETTING = 'bsnl.auto_reports'
LAST_CHECK = 'bsnl.auto_reports.last_check'
CHECK_EVERY = timedelta(minutes=10)
DEFAULTS = {'daily': False, 'weekly': False}


def settings_value() -> dict:
    return {**DEFAULTS, **(Setting.get(SETTING, {}) or {})}


def due(report_type: str, now: datetime) -> bool:
    local = timezone.localtime(now, ZoneInfo(TIMEZONE))
    if report_type == ReportType.D1:
        return local.time() >= time(DAILY_HOUR)
    return local.weekday() > WEEKLY_DAY or (local.weekday() == WEEKLY_DAY and local.time() >= time(WEEKLY_HOUR))


def _targets(ds):
    from apps.organization.models import Circle
    codes = sorted(set(ds.sites['circle']))
    circles = list(Circle.objects.filter(code__in=codes).order_by('name'))
    return [None] + circles  # the All India summary, then one email per Circle


def tick(now: datetime | None = None, *, dataset=None, force: bool = False) -> dict:
    """One pass. The data is checked at most every CHECK_EVERY (the worker passes every 30 seconds); ``force`` skips that
    wait (tests, ``run_alerts --once`` runs every pass anyway when called less often)."""
    now = now or timezone.now()
    counts = {'sent': 0, 'failed': 0, 'skipped': 0}
    config = settings_value()
    wanted = [t for t, key in ((ReportType.D1, 'daily'), (ReportType.WEEKLY, 'weekly')) if config.get(key) and due(t, now)]
    if not wanted or not delivery.sending_enabled():
        return counts
    last = Setting.get(LAST_CHECK)
    if not force and last and now - datetime.fromisoformat(last) < CHECK_EVERY:
        return counts
    Setting.put(LAST_CHECK, now.isoformat())
    if dataset is None:
        from apps.sitedata import dashboard_source
        dataset = dashboard_source.dataset(None, reports.SCOPE)
    try:
        latest = reports.latest_date(dataset)
    except reports.ReportError as exc:
        logger.warning('BSNL scheduled reports not built: %s', exc)
        return counts
    for report_type in wanted:
        start = report_period(report_type, latest).start.isoformat()
        sent = set(ReportRun.objects.filter(slot_key__startswith=f'{report_type}|', period_start=start).values_list('slot_key', flat=True))
        for circle in _targets(dataset):
            if f'{report_type}|{circle.code if circle else "ALL"}|{start}' in sent:
                continue
            try:
                report = reports.build(dataset, report_type, {'code': circle.code, 'name': circle.name} if circle else None,
                                       source='uptime data')
            except reports.ReportError as exc:
                logger.warning('BSNL %s report for %s not built: %s', report_type, circle or 'All India', exc)
                continue
            slot = f'{report_type}|{circle.code if circle else "ALL"}|{report["period"]["start"]}'
            run = delivery.send_report(report, circle=circle, trigger='schedule', slot_key=slot)
            if run is not None:
                counts[{'sent': 'sent', 'failed': 'failed'}.get(run.status, 'skipped')] += 1
    return counts
