"""Query-parameter validation shared by the dashboard endpoints.

Values that depend on the workbook (circles, reporting dates) are checked
against the loaded dataset, so an unknown circle or an unreported date is a
400 error rather than a silent fallback to defaults.
"""
from datetime import date, timedelta

from rest_framework import serializers

from .metrics import BUCKET_IDS, DEFAULT_SCOPE, SCOPES, SORT_FIELDS, WEEKS, Selection, month_options
from .workbook import REPORT_TYPES

MAX_TREND_DAYS = 92
SCOPE_ERROR = 'Unknown population "{input}". Expected one of: ' + ', '.join(SCOPES) + f' (default {DEFAULT_SCOPE}).'


def scope_field():
    """The ``scope`` (site population) parameter of every site-metric endpoint: on_air | om_start, default on_air."""
    return serializers.ChoiceField(choices=list(SCOPES), required=False, default=DEFAULT_SCOPE,
                                   error_messages={'invalid_choice': SCOPE_ERROR})


def parse_scope(value, default: str | None = DEFAULT_SCOPE) -> str | None:
    """The validated population of a request parameter (endpoints without a serializer): missing -> ``default``
    (DEFAULT_SCOPE; None where the filter is optional, see masterdata); anything else than on_air / om_start (including
    the former "all") -> HTTP 400 {error, details: {scope: [...]}}."""
    value = (value or '').strip()
    if not value:
        return default
    if value not in SCOPES:
        raise serializers.ValidationError({'scope': [SCOPE_ERROR.format(input=value)]})
    return value
# Accept the workbook's own spelling as an alias for the canonical report type.
REPORT_TYPE_ALIASES = {**{raw: canonical for raw, canonical in REPORT_TYPES.items()},
                       **{canonical: canonical for canonical in REPORT_TYPES.values()}}


class SelectionSerializer(serializers.Serializer):
    report_type = serializers.CharField(required=False, allow_blank=True, default='')
    circle = serializers.CharField(required=False, allow_blank=True, default='')
    scope = scope_field()

    def validate_report_type(self, value):
        if not value:
            return None
        if value in REPORT_TYPE_ALIASES:
            return REPORT_TYPE_ALIASES[value]
        from apps.organization.services import project_keys
        known = project_keys()  # a project of the Organization, with or without data yet
        if value not in known:
            raise serializers.ValidationError(f"Unknown report type. Expected one of: {', '.join(known)}.")
        return value

    def validate(self, attrs):
        dataset = self.context['dataset']
        circle = attrs.get('circle') or None
        if circle and circle not in set(dataset.sites['circle']):
            from apps.organization.services import circle_codes
            if circle not in circle_codes():  # an Organization circle without data yet is valid (and matches no site)
                raise serializers.ValidationError({'circle': 'Unknown circle.'})
        if attrs['scope'] == 'om_start' and not dataset.has_om_start:
            raise serializers.ValidationError({'scope': 'The O&M Start scope is not available in this workbook.'})
        attrs['selection'] = Selection(attrs.get('report_type'), circle, attrs['scope'])
        return attrs


class SnapshotSerializer(SelectionSerializer):
    reporting_date = serializers.DateField(required=False, allow_null=True, default=None)

    def validate(self, attrs):
        attrs = super().validate(attrs)
        dataset = self.context['dataset']
        day = attrs.get('reporting_date')
        if day is None:
            day = dataset.latest_date
            if day is None:
                raise serializers.ValidationError({'reporting_date': 'The workbook has no reported dates yet.'})
        elif day not in dataset.reported_dates:
            raise serializers.ValidationError({'reporting_date': (
                f'No data has been reported for {day.isoformat()}. Available dates: '
                f'{dataset.reported_dates[0].isoformat()} to {dataset.latest_date.isoformat()}.'
                if dataset.reported_dates else 'The workbook has no reported dates yet.'
            )})
        attrs['reporting_date'] = day
        return attrs


class MonthlySerializer(SnapshotSerializer):
    # Comma-separated 'YYYY-MM' keys from filter options; empty means every month.
    months = serializers.CharField(required=False, allow_blank=True, default='', max_length=400)

    def validate(self, attrs):
        attrs = super().validate(attrs)
        raw = [key.strip() for key in attrs.get('months', '').split(',') if key.strip()]
        if not raw:
            attrs['months'] = None
            return attrs
        available = {m['key'] for m in month_options(self.context['dataset'])}
        unknown = sorted(set(raw) - available)
        if unknown:
            raise serializers.ValidationError({'months': f"Unknown month(s): {', '.join(unknown)}."})
        attrs['months'] = set(raw)
        return attrs


class TrendSerializer(SelectionSerializer):
    start_date = serializers.DateField(required=False, allow_null=True, default=None)
    end_date = serializers.DateField(required=False, allow_null=True, default=None)

    def validate(self, attrs):
        attrs = super().validate(attrs)
        dataset = self.context['dataset']
        start = attrs.get('start_date') or (dataset.reported_dates[0] if dataset.reported_dates else dataset.dates[0])
        end = attrs.get('end_date') or dataset.latest_date or dataset.dates[-1]
        if start > end:
            raise serializers.ValidationError({'start_date': 'start_date must be on or before end_date.'})
        if end - start > timedelta(days=MAX_TREND_DAYS - 1):
            raise serializers.ValidationError({'end_date': f'The trend range is limited to {MAX_TREND_DAYS} days.'})
        attrs['start_date'], attrs['end_date'] = start, end
        return attrs


class PeriodSerializer(SelectionSerializer):
    """The trend period picked in the filter bar: a date range, picked dates, weeks or months."""
    period = serializers.ChoiceField(choices=['range', 'days', 'weeks', 'months'], required=False, default='range')
    start_date = serializers.DateField(required=False, allow_null=True, default=None)
    end_date = serializers.DateField(required=False, allow_null=True, default=None)
    # Comma-separated lists; empty weeks / months mean all of them.
    days = serializers.CharField(required=False, allow_blank=True, default='', max_length=400)
    weeks = serializers.CharField(required=False, allow_blank=True, default='', max_length=20)
    months = serializers.CharField(required=False, allow_blank=True, default='', max_length=400)

    def validate(self, attrs):
        attrs = super().validate(attrs)
        ds = self.context['dataset']
        period = attrs['period']
        split = lambda value: [v.strip() for v in value.split(',') if v.strip()]  # noqa: E731
        attrs['dates'], attrs['month_keys'] = None, None
        attrs['status_dates'] = None  # calendar dates of the period, for its Complete / Provisional status

        if period == 'months':
            options = month_options(ds)
            keys = split(attrs['months']) or [m['key'] for m in options]
            unknown = sorted(set(keys) - {m['key'] for m in options})
            if unknown:
                raise serializers.ValidationError({'months': f"Unknown month(s): {', '.join(unknown)}."})
            labels = [m['label'] for m in options if m['key'] in keys]
            attrs['month_keys'] = keys
            attrs['status_dates'] = _month_calendar(keys)
            attrs['label'] = (labels[0] if len(labels) == 1 else f'{labels[0]} – {labels[-1]} ({len(labels)} months)'
                              if len(labels) == len(options) or _consecutive(options, keys) else f'{len(labels)} months')
        elif period == 'weeks':
            try:
                weeks = sorted({int(w) for w in split(attrs['weeks'])}) or [1, 2, 3, 4]
            except ValueError as exc:
                raise serializers.ValidationError({'weeks': 'Weeks must be numbers 1 to 4.'}) from exc
            if not set(weeks) <= {1, 2, 3, 4}:
                raise serializers.ValidationError({'weeks': 'Weeks must be numbers 1 to 4.'})
            # Every selected week shows the figures it has; a week that has not ended or has missing unit-days is
            # Provisional (approved rule B-4, metrics.week_status), reported in the response's 'status'.
            ranges = [WEEKS[w - 1] for w in weeks]
            attrs['dates'] = [d for d in ds.dates if any(first <= d.day <= last for _, first, last in ranges)]
            attrs['label'] = 'All weeks' if len(weeks) == 4 else f"Week{'s' if len(weeks) > 1 else ''} {', '.join(map(str, weeks))}"
        elif period == 'days':
            try:
                days = sorted({date.fromisoformat(d) for d in split(attrs['days'])})
            except ValueError as exc:
                raise serializers.ValidationError({'days': 'Dates must be YYYY-MM-DD.'}) from exc
            if not days:
                raise serializers.ValidationError({'days': 'Pick at least one date.'})
            attrs['dates'] = days
            attrs['label'] = (', '.join(d.strftime('%d %b') for d in days) if len(days) <= 3 else f'{len(days)} picked dates')
        else:
            start = attrs['start_date'] or (ds.reported_dates[0] if ds.reported_dates else ds.dates[0])
            end = attrs['end_date'] or ds.latest_date or ds.dates[-1]
            if start > end:
                raise serializers.ValidationError({'start_date': 'start_date must be on or before end_date.'})
            attrs['dates'] = [d for d in ds.dates if start <= d <= end]
            attrs['label'] = f"{start.strftime('%d %b')} – {end.strftime('%d %b')}"
        return attrs


def _month_calendar(keys: list[str]) -> list[date]:
    import calendar
    out = []
    for key in keys:
        year, month = map(int, key.split('-'))
        out += [date(year, month, d) for d in range(1, calendar.monthrange(year, month)[1] + 1)]
    return out


def period_status(ds, params: dict) -> dict | None:
    """Complete / Provisional status of a validated period (PeriodSerializer) over the selection's reporting units
    (metrics.dates_status); None without coverage information."""
    import numpy as np

    from .metrics import base_mask, dates_status, units_of_rows
    dates = params.get('status_dates') or params.get('dates') or []
    return dates_status(ds, dates, units_of_rows(ds, np.flatnonzero(base_mask(ds, params['selection']))))


def _consecutive(options: list[dict], keys: list[str]) -> bool:
    positions = [i for i, m in enumerate(options) if m['key'] in keys]
    return positions == list(range(positions[0], positions[-1] + 1))


class RecordsSerializer(SnapshotSerializer):
    search = serializers.CharField(required=False, allow_blank=True, default='', max_length=100, trim_whitespace=True)
    bucket = serializers.ChoiceField(choices=list(BUCKET_IDS), required=False, allow_blank=True, default='')
    # Whether ``bucket`` applies to each site's MTD uptime or its uptime on the reporting date.
    bucket_basis = serializers.ChoiceField(choices=['mtd', 'daily'], required=False, default='mtd')
    sort = serializers.ChoiceField(choices=list(SORT_FIELDS), required=False, default='site_id')
    direction = serializers.ChoiceField(choices=['asc', 'desc'], required=False, default='asc')
    page = serializers.IntegerField(required=False, default=1, min_value=1)
    page_size = serializers.IntegerField(required=False, default=25, min_value=1, max_value=100)
    # Sites assigned to one CI or IE ("Unassigned" selects sites without a name).
    ci_name = serializers.CharField(required=False, allow_blank=True, default='', max_length=120, trim_whitespace=True)
    ie_name = serializers.CharField(required=False, allow_blank=True, default='', max_length=120, trim_whitespace=True)
    # NSLA only: sites whose MTD uptime is below 98.5% (sites without a value are not NSLA).
    below_sla = serializers.BooleanField(required=False, default=False)


class TeamSerializer(SnapshotSerializer):
    group = serializers.ChoiceField(choices=['ci', 'ie'], required=False, default='ci')


class TeamMonthlySerializer(TeamSerializer):
    # 'YYYY-MM'; empty means the latest month with data.
    month = serializers.RegexField(r'^\d{4}-\d{2}$', required=False, allow_blank=True, default='')


class DailyExportSerializer(SelectionSerializer):
    """Daily Uptime Report: exactly one reporting date (current or an earlier month with daily values)."""
    date = serializers.DateField()
