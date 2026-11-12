"""Master Data API: paginated, filtered and sorted on the server; exports of the filtered records; Data Panel saves.

- Every portal user may open it. Admins and NOC Leads see every record; a CI user only the project/circle pairs granted
  to them (accounts.scope). Phone numbers (``Column.contact``) are returned to Admins only.
- Always the database tables of the data layer (apps.sitedata) and the RCA register (it is the database explorer).
"""
from __future__ import annotations

import calendar
import csv
import io
from datetime import date, datetime

from django.db.models import DateField, F, Q, QuerySet
from django.db.models.functions import TruncMonth
from django.http import HttpResponse, StreamingHttpResponse
from django.utils import timezone
from openpyxl import Workbook
from rest_framework.decorators import api_view, parser_classes, permission_classes
from rest_framework.exceptions import NotFound, PermissionDenied, ValidationError
from rest_framework.parsers import JSONParser
from rest_framework.response import Response

from apps.accounts.access import can, pairs_for, pairs_q
from apps.accounts.audit import audit
from apps.accounts.catalog import data_module
from apps.accounts.permissions import IsPortalUser
from apps.accounts.roles import ADMIN, role_of
from apps.dashboard.metrics import POPULATION_COLUMNS, WEEKS, population as population_info
from apps.dashboard.serializers import parse_scope
from apps.rca import taxonomy

from .datasets import DATASETS, Column, Dataset

PAGE_SIZES = (25, 50, 100, 200)
POPULATION_COLUMNS_LABELS = {k: population_info(k)['label'] for k in POPULATION_COLUMNS}
XLSX_MAX_ROWS = 200_000  # larger exports: CSV (streamed)
PERIODS = ('daily', 'weekly', 'monthly', 'overall')


def _dataset(key: str) -> Dataset:
    if key not in DATASETS:
        raise NotFound('No such dataset.')
    return DATASETS[key]


def _columns(request, ds: Dataset) -> list[Column]:
    admin = role_of(request.user) == ADMIN
    return [c for c in ds.columns if admin or not c.contact]


def _date(value: str | None, name: str) -> date | None:
    if not value:
        return None
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise ValidationError({name: 'Give the date as YYYY-MM-DD.'}) from exc


def _int(value: str | None, name: str, low: int, high: int) -> int | None:
    if not value:
        return None
    if not value.isdigit() or not low <= int(value) <= high:
        raise ValidationError({name: f'Give a number from {low} to {high}.'})
    return int(value)


def _require(request, ds: Dataset, action: str) -> None:
    """The dataset's own permission (Users & Roles › Data Panel · <dataset>), checked on every request."""
    if not can(request.user, data_module(ds.key), action):
        raise PermissionDenied(f'You do not have the {action.capitalize()} permission on {ds.label}.')


def scoped(request, ds: Dataset, action: str = 'view') -> QuerySet:
    """The dataset's records inside the project/circle pairs of the user's permission on it (accounts.access)."""
    return ds.queryset().filter(pairs_q(pairs_for(request.user, data_module(ds.key), action), ds.project, ds.circle))


def period_range(ds: Dataset, params) -> tuple[date | None, date | None]:
    """First and last day selected by the period view (None: open)."""
    period = params.get('period') or 'overall'
    if period not in PERIODS:
        raise ValidationError({'period': f'Choose one of {", ".join(PERIODS)}.'})
    year = _int(params.get('year'), 'year', 2000, 2100)
    month = _int(params.get('month'), 'month', 1, 12)
    if period == 'daily' and year and month:
        day = _date(params.get('date'), 'date')
        last = calendar.monthrange(year, month)[1]
        return (day, day) if day else (date(year, month, 1), date(year, month, last))
    if period == 'weekly' and year and month:
        week = _int(params.get('week'), 'week', 1, len(WEEKS))
        last = calendar.monthrange(year, month)[1]
        _, first_day, last_day = WEEKS[(week or 1) - 1]
        return date(year, month, first_day), date(year, month, min(last_day, last))
    if period == 'monthly' and year:
        start = _int(params.get('month_from'), 'month_from', 1, 12) or 1
        end = _int(params.get('month_to'), 'month_to', 1, 12) or 12
        return date(year, start, 1), date(year, end, calendar.monthrange(year, end)[1])
    return _date(params.get('date_from'), 'date_from'), _date(params.get('date_to'), 'date_to')


def population_filter(qs: QuerySet, ds: Dataset, scope: str | None) -> QuerySet:
    """Records of the site population ``scope`` (None: unchanged), by the Consolidation Matrix effective date: Site
    Master / Escalation: effective today; Daily: effective on the reporting date; Monthly: effective in the month.
    Dashboard-scope sites only (outside-scope sites belong to no population)."""
    if scope is None or ds.population is None:
        return qs
    column = POPULATION_COLUMNS[scope][1]
    if ds.population == 'site':
        return qs.filter(reporting_scope='dashboard', **{f'{column}__isnull': False, f'{column}__lte': timezone.localdate()})
    qs = qs.filter(**{'site__reporting_scope': 'dashboard', f'site__{column}__isnull': False})
    if ds.population == 'daily':
        return qs.filter(**{f'site__{column}__lte': F('report_date')})
    return qs.annotate(_population_month=TruncMonth(f'site__{column}', output_field=DateField())).filter(_population_month__lte=F('month'))


def request_population(request, ds: Dataset) -> str | None:
    """The optional ``scope`` of a request (on_air / om_start; absent: None = no population filter; invalid: HTTP 400)."""
    scope = parse_scope(request.query_params.get('scope'), default=None)
    return scope if ds.population else None


def filtered(request, ds: Dataset, action: str = 'view') -> QuerySet:
    p = request.query_params
    qs = population_filter(scoped(request, ds, action), ds, request_population(request, ds))
    for key, path in (('project', ds.project), ('circle', ds.circle)):
        if p.get(key):
            qs = qs.filter(**{path: p[key]})
    for key, path in (('site_id', ds.site_id), ('site_name', ds.site_name)):
        if path and p.get(key):
            qs = qs.filter(**{f'{path}__icontains': p[key].strip()})
    for choice in ds.choices:
        value = p.get(choice.key)
        if value:
            qs = qs.filter(**{choice.field: value in ('true', 'True') if choice.key == 'on_air' else value})
    time_field = ds.date or ds.month
    if time_field:
        start, end = period_range(ds, p)
        if start:
            qs = qs.filter(**{f'{time_field}__gte': start.replace(day=1) if ds.month else start})
        if end:
            qs = qs.filter(**{f'{time_field}__lte': end})
    if p.get('q'):
        q = Q()
        for f in ds.search:
            q |= Q(**{f'{f}__icontains': p['q'].strip()})
        qs = qs.filter(q)
    return qs


def _ordering(request, ds: Dataset, columns: list[Column]) -> list[str]:
    sort = request.query_params.get('sort') or ds.default_sort
    desc = sort.startswith('-')
    col = next((c for c in columns if c.key == sort.lstrip('-')), None)
    path = col.field if col else sort.lstrip('-')
    if not col and path != 'id':
        raise ValidationError({'sort': 'Unknown column.'})
    return [f'{"-" if desc else ""}{path}', 'id']


def _rows(qs: QuerySet, ds: Dataset, columns: list[Column]) -> list[dict]:
    paths = [c.field for c in columns]
    out = []
    for values in qs.values_list('id', *paths):
        row = {'_id': values[0]}
        for c, v in zip(columns, values[1:]):
            row[c.key] = v.isoformat() if isinstance(v, (date, datetime)) else v
        if ds.key == 'rca' and 'final_bucket' in row and 'bucket_2' in row:  # the approved bucketization (apps.rca.taxonomy), never a stored guess
            row['classification'] = taxonomy.status_label(taxonomy.resolve(row['final_bucket'], row['bucket_2']).status)
        out.append(row)
    return out


def _column_json(ds: Dataset, columns: list[Column]) -> list[dict]:
    out = [{'key': c.key, 'label': c.label, 'kind': c.kind, 'hidden': c.hidden} for c in columns]
    if ds.key == 'rca':
        out.append({'key': 'classification', 'label': 'Approved classification', 'kind': 'text', 'hidden': True, 'sortable': False})
    return out


@api_view(['GET'])
@permission_classes([IsPortalUser])
def datasets(request):
    """The datasets the user may view, each with what they may do on it (View, Add, Edit, Export; never Delete)."""
    from .editing import capabilities
    visible = [(d, capabilities(request.user, d)) for d in DATASETS.values()]
    visible = [(d, c) for d, c in visible if c['view']]
    if not visible:
        raise PermissionDenied('You do not have access to any Data Panel dataset.')
    return Response({'datasets': [{'key': d.key, 'label': d.label, 'description': d.description, 'time': bool(d.date or d.month),
                                   'columns': _column_json(d, _columns(request, d)),
                                   'filters': {'site': bool(d.site_id), 'choices': [{'key': c.key, 'label': c.label} for c in d.choices],
                                               # the optional site population filter (``scope``) of site-based datasets
                                               'population': bool(d.population)},
                                   'permissions': caps}
                                  for d, caps in visible],
                     'page_sizes': PAGE_SIZES, 'weeks': [{'value': i + 1, 'label': f'{w[0]} (days {w[1]}–{w[2] if w[2] < 31 else "end"})'}
                                                         for i, w in enumerate(WEEKS)]})


@api_view(['GET'])
@permission_classes([IsPortalUser])
def records(request, key: str):
    ds = _dataset(key)
    _require(request, ds, 'view')
    columns = _columns(request, ds)
    qs = filtered(request, ds).order_by(*_ordering(request, ds, columns))
    size = _int(request.query_params.get('page_size'), 'page_size', 1, max(PAGE_SIZES)) or PAGE_SIZES[1]
    page = _int(request.query_params.get('page'), 'page', 1, 10**7) or 1
    total = qs.count()
    start = (page - 1) * size
    scope = request_population(request, ds)
    return Response({'total': total, 'page': page, 'page_size': size, 'pages': max(1, -(-total // size)),
                     'rows': _rows(qs[start:start + size], ds, columns),
                     'population': population_info(scope) if scope else None})


@api_view(['GET'])
@permission_classes([IsPortalUser])
def options(request, key: str):
    """Filter options from the records the user may see (projects, circles, years and months, choices)."""
    ds = _dataset(key)
    _require(request, ds, 'view')
    scope = request_population(request, ds)
    qs = population_filter(scoped(request, ds), ds, scope).order_by()
    out = {'projects': sorted(v for v in qs.values_list(ds.project, flat=True).distinct() if v)}
    project = request.query_params.get('project')
    circles_qs = qs.filter(**{ds.project: project}) if project else qs
    out['circles'] = sorted(v for v in circles_qs.values_list(ds.circle, flat=True).distinct() if v)
    time_field = ds.date or ds.month
    if time_field:
        months = sorted({(d.year, d.month) for d in qs.dates(time_field, 'month')})
        out['months'] = [{'year': y, 'month': m} for y, m in months]
        out['dates'] = [d.isoformat() for d in qs.dates(time_field, 'day')] if ds.date else []
    out['choices'] = {c.key: sorted({str(v) for v in qs.values_list(c.field, flat=True).distinct() if v not in (None, '')})[:500]
                      for c in ds.choices}
    # The population filter the dataset offers (site-based datasets only) and the one applied.
    out['scopes'] = [{'value': k, 'label': v} for k, v in POPULATION_COLUMNS_LABELS.items()] if ds.population else []
    out['population'] = population_info(scope) if scope else None
    return Response(out)


@api_view(['GET'])
@permission_classes([IsPortalUser])
def export(request, key: str):
    """The filtered records, sorted as shown, with the chosen columns (all if none): CSV (streamed) or Excel."""
    ds = _dataset(key)
    _require(request, ds, 'export')
    allowed = _columns(request, ds)
    wanted = [k for k in (request.query_params.get('columns') or '').split(',') if k]
    columns = [c for c in allowed if not wanted or c.key in wanted]
    qs = filtered(request, ds, 'export').order_by(*_ordering(request, ds, allowed))
    stamp = datetime.now().strftime('%Y%m%d-%H%M')
    if (request.query_params.get('file') or 'csv') == 'xlsx':
        if qs.count() > XLSX_MAX_ROWS:
            raise ValidationError({'file': f'More than {XLSX_MAX_ROWS:,} records: narrow the filters or export CSV.'})
        book = Workbook(write_only=True)
        sheet = book.create_sheet(ds.label[:31])
        sheet.append([c.label for c in columns])
        for chunk in _chunks(qs, ds, columns):
            for row in chunk:
                sheet.append([row[c.key] for c in columns])
        buf = io.BytesIO()
        book.save(buf)
        response = HttpResponse(buf.getvalue(), content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')
        response['Content-Disposition'] = f'attachment; filename="{ds.key}{_population_suffix(request, ds)}_{stamp}.xlsx"'
        return response

    def lines():
        out = io.StringIO()
        writer = csv.writer(out)
        writer.writerow([c.label for c in columns])
        yield '﻿' + out.getvalue()
        for chunk in _chunks(qs, ds, columns):
            out.seek(0)
            out.truncate()
            writer.writerows([row[c.key] for c in columns] for row in chunk)
            yield out.getvalue()
    response = StreamingHttpResponse(lines(), content_type='text/csv; charset=utf-8')
    response['Content-Disposition'] = f'attachment; filename="{ds.key}{_population_suffix(request, ds)}_{stamp}.csv"'
    return response


def _population_suffix(request, ds: Dataset) -> str:
    from apps.dashboard.metrics import POPULATION_SUFFIX
    scope = request_population(request, ds)
    return f'_{POPULATION_SUFFIX[scope]}' if scope else ''


def _chunks(qs: QuerySet, ds: Dataset, columns: list[Column], size: int = 5000):
    for start in range(0, qs.count(), size):
        yield _rows(qs[start:start + size], ds, columns)


@api_view(['POST'])
@parser_classes([JSONParser])
@permission_classes([IsPortalUser])
def save(request, key: str):
    """Data Panel: save every pending change of one dataset in one transaction (no partial save, no delete)."""
    from .editing import SaveRefused
    from .editing import save as save_changes
    ds = _dataset(key)
    _require(request, ds, 'view')
    try:
        result = save_changes(request.user, ds, request.data if isinstance(request.data, dict) else {}, request=request)
    except SaveRefused as exc:
        return Response({'error': str(exc), 'details': exc.details}, status=exc.status)
    if not result['saved']:
        return Response({'error': result['errors'].get('_form') or 'Nothing was saved: correct the highlighted cells.', 'details': result['errors']},
                        status=400)
    audit('data_panel_saved', request, dataset=ds.key, updated=result['updated'], added=result['added'])
    return Response(result)
