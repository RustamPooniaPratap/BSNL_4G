"""Queries over RCA records: filters, the register page, the summary and the cause-mapping queue.

Placeholders ("-", blank) in Final Bucket, Bucket - 2 and RCA are counted as unclassified, never as a
root cause. Canonical categories come only from Admin-approved mappings; records whose description
has no mapping are "unreviewed".

RCA applicability follows the source field Final Bucket: "Other Media" records are outside RCA recording
under the reporting process (RCA_NOT_APPLICABLE). They stay visible as their own group, are left out of
the missing-information count and the completeness denominator, and are never shown as a technical root
cause. A blank Bucket - 2 alone never makes a record "Other Media": records of any other Final Bucket with
a blank or "-" cause field are "RCA Required - Missing Information".
"""
from __future__ import annotations

import logging
from collections import Counter, defaultdict
from datetime import date

from django.db.models import Count, OuterRef, Q, QuerySet, Subquery, Sum
from rest_framework.exceptions import ValidationError

from .models import RcaCauseCategory, RcaCauseMapping, RcaRecord, RcaWorkflow

logger = logging.getLogger(__name__)
UNCLASSIFIED = '__unclassified__'
UNREVIEWED = 'unreviewed'
# Final Bucket values (normalised keys) for which RCA recording is not applicable, as confirmed by the business.
RCA_NOT_APPLICABLE = {'other media': 'Other Media'}
NOT_APPLICABLE_LABEL = 'Other Media — RCA Not Applicable'
MISSING_LABEL = 'RCA Required — Missing Information'
NOT_APPLICABLE_Q = Q(final_bucket_key__in=list(RCA_NOT_APPLICABLE))
BLANK_CAUSE_Q = Q(final_bucket_key='') | Q(bucket_2_key='') | Q(rca_key='')
ORDERINGS = {
    'outage_desc': ('-outage_minutes', 'id'), 'outage_asc': ('outage_minutes', 'id'), 'site': ('site_id', 'id'),
    'date_desc': ('-reporting_date', '-outage_minutes', 'id'), 'circle': ('project', 'circle', '-outage_minutes', 'id'),
}
MAX_PAGE_SIZE = 100


def _date(value: str | None, name: str) -> date | None:
    if not value:
        return None
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise ValidationError({name: f'"{value}" is not a date (YYYY-MM-DD).'}) from exc


def with_category(qs: QuerySet) -> QuerySet:
    mapping = RcaCauseMapping.objects.filter(rca_key=OuterRef('rca_key'))
    return qs.annotate(category_id=Subquery(mapping.values('category_id')[:1]),
                       category_name=Subquery(mapping.values('category__name')[:1]))


def filtered(params) -> QuerySet:
    """Records matching the query parameters (date / date_from / date_to, project, circle, buckets, category, q)."""
    # order_by() clears Meta.ordering, which would otherwise leak into DISTINCT / GROUP BY queries.
    qs = with_category(RcaRecord.objects.order_by())
    day = _date(params.get('date'), 'date')
    start, end = _date(params.get('date_from'), 'date_from'), _date(params.get('date_to'), 'date_to')
    if day:
        qs = qs.filter(reporting_date=day)
    if start:
        qs = qs.filter(reporting_date__gte=start)
    if end:
        qs = qs.filter(reporting_date__lte=end)
    if params.get('project'):
        qs = qs.filter(project=params['project'])
    if params.get('circle'):
        qs = qs.filter(circle=params['circle'])
    for name, field in (('final_bucket', 'final_bucket_key'), ('bucket_2', 'bucket_2_key')):
        value = params.get(name)
        if value:
            qs = qs.filter(**{field: '' if value == UNCLASSIFIED else value})
    category = params.get('category')
    if category == UNREVIEWED:
        qs = qs.filter(category_id__isnull=True).exclude(rca_key='')
    elif category == UNCLASSIFIED:
        qs = qs.filter(rca_key='')
    elif category:
        qs = qs.filter(category_id=category)
    applicability = params.get('rca')
    if applicability == 'not_applicable':
        qs = qs.filter(NOT_APPLICABLE_Q)
    elif applicability == 'required':
        qs = qs.exclude(NOT_APPLICABLE_Q)
    elif applicability == 'missing':
        qs = qs.exclude(NOT_APPLICABLE_Q).filter(BLANK_CAUSE_Q)
    if params.get('status'):
        status = params['status']
        qs = qs.filter(Q(workflow__isnull=True) | Q(workflow__status='')) if status == 'not_recorded' else qs.filter(workflow__status=status)
    q = (params.get('q') or '').strip()
    if q:
        qs = qs.filter(Q(site_id__icontains=q) | Q(site_name__icontains=q) | Q(rca_text__icontains=q) | Q(oa__icontains=q) | Q(ba__icontains=q))
    return qs


def _labels(qs: QuerySet, key: str, label: str) -> dict[str, str]:
    """Display label per normalised key: the most frequent spelling in the source."""
    counts: dict[str, Counter] = defaultdict(Counter)
    for row in qs.values(key, label).annotate(n=Count('id')):
        counts[row[key]][row[label]] += row['n']
    return {k: c.most_common(1)[0][0] for k, c in counts.items()}


def _variants(qs: QuerySet, key: str, label: str) -> dict[str, list[str]]:
    groups: dict[str, set] = defaultdict(set)
    for row in qs.values(key, label).distinct():
        groups[row[key]].add(row[label])
    return {k: sorted(v) for k, v in groups.items()}


def options() -> dict:
    qs = RcaRecord.objects.order_by()
    buckets = lambda key, label: [  # noqa: E731
        {'value': k or UNCLASSIFIED, 'label': v if k else 'Unclassified (blank or "-")', 'unclassified': not k}
        for k, v in sorted(_labels(qs, key, label).items(), key=lambda kv: (kv[0] == '', kv[1].casefold()))
    ]
    return {
        'dates': [d.isoformat() for d in qs.values_list('reporting_date', flat=True).distinct().order_by('reporting_date')],
        'projects': sorted(qs.values_list('project', flat=True).distinct()),
        'circles': [{'project': p, 'circle': c, 'circle_raw': r} for p, c, r in
                    qs.values_list('project', 'circle', 'circle_raw').distinct().order_by('project', 'circle')],
        'final_buckets': buckets('final_bucket_key', 'final_bucket'),
        'bucket_2': buckets('bucket_2_key', 'bucket_2'),
        'categories': [{'value': str(c.pk), 'label': c.name} for c in RcaCauseCategory.objects.all()],
        'statuses': [{'value': v, 'label': label} for v, label in RcaWorkflow.Status.choices],
        'total_records': qs.count(),
    }


def workflow_json(workflow: RcaWorkflow | None) -> dict | None:
    if workflow is None:
        return None
    return {
        'status': workflow.status or None, 'status_label': workflow.get_status_display() if workflow.status else None,
        'review_status': workflow.review_status or None,
        'review_status_label': workflow.get_review_status_display() if workflow.review_status else None,
        'corrective_action': workflow.corrective_action or None, 'owner': workflow.owner or None,
        'target_date': workflow.target_date.isoformat() if workflow.target_date else None,
        'completed_date': workflow.completed_date.isoformat() if workflow.completed_date else None,
        'verification': workflow.verification or None,
        'verification_label': workflow.get_verification_display() if workflow.verification else None,
        'reviewer': workflow.reviewer.get_username() if workflow.reviewer else None,
        'reviewed_at': workflow.reviewed_at.isoformat() if workflow.reviewed_at else None,
        'updated_by': workflow.updated_by.get_username() if workflow.updated_by else None,
        'updated_at': workflow.updated_at.isoformat(),
    }


def record_json(rec: RcaRecord, *, full: bool = False) -> dict:
    workflow = getattr(rec, 'workflow', None)  # None until someone records follow-up
    data = {
        'id': rec.pk, 'reporting_date': rec.reporting_date.isoformat(), 'project': rec.project, 'project_raw': rec.project_raw,
        'circle': rec.circle, 'circle_raw': rec.circle_raw, 'site_id': rec.site_id, 'site_name': rec.site_name,
        'oa': rec.oa, 'ba': rec.ba, 'om_start_raw': rec.om_start_raw, 'om_start': rec.om_start,
        'outage_minutes': rec.outage_minutes, 'final_bucket': rec.final_bucket, 'final_bucket_unclassified': not rec.final_bucket_key,
        'bucket_2': rec.bucket_2, 'bucket_2_unclassified': not rec.bucket_2_key,
        'rca_text': rec.rca_text, 'rca_unclassified': not rec.rca_key,
        'rca_applicable': rec.final_bucket_key not in RCA_NOT_APPLICABLE,
        'category': {'id': rec.category_id, 'name': rec.category_name} if getattr(rec, 'category_id', None) else None,
        'source': rec.source, 'status': workflow.status or None if workflow else None,
        'status_label': workflow.get_status_display() if workflow and workflow.status else None,
    }
    if full:
        data.update({
            'source_file': rec.source_file or None, 'source_row': rec.source_row, 'batch': rec.batch_id,
            'created_by': rec.created_by.get_username() if rec.created_by else None, 'created_at': rec.created_at.isoformat(),
            'workflow': workflow_json(workflow),
            'comments': [{'id': c.pk, 'author': c.author.get_username() if c.author else None, 'text': c.text,
                          'evidence': c.evidence or None, 'created_at': c.created_at.isoformat()} for c in rec.comments.select_related('author')],
            'history': [{'action': e.action, 'user': e.user.get_username() if e.user else None, 'at': e.at.isoformat(), 'changes': e.changes}
                        for e in rec.events.select_related('user')[:50]],
            'other_records': [{'id': o.pk, 'reporting_date': o.reporting_date.isoformat(), 'outage_minutes': o.outage_minutes, 'rca_text': o.rca_text}
                              for o in RcaRecord.objects.filter(project=rec.project, site_key=rec.site_key).exclude(pk=rec.pk).order_by('-reporting_date')[:20]],
        })
    return data


def register(params) -> dict:
    qs = filtered(params).select_related('workflow')
    ordering = ORDERINGS.get(params.get('ordering') or 'outage_desc', ORDERINGS['outage_desc'])
    try:
        page = max(1, int(params.get('page') or 1))
        size = min(MAX_PAGE_SIZE, max(1, int(params.get('page_size') or 25)))
    except ValueError as exc:
        raise ValidationError({'page': 'Page and page size must be whole numbers.'}) from exc
    total = qs.count()
    rows = qs.order_by(*ordering)[(page - 1) * size: page * size]
    return {'count': total, 'page': page, 'page_size': size, 'pages': max(1, -(-total // size)),
            'results': [record_json(r) for r in rows]}


def _population() -> dict[tuple[str, str], int] | None:
    """Sites per (project, circle) in the dashboard's current Master data, for per-site rates; None if unavailable."""
    try:
        from apps.uptimedb.datasource import current_dataset
        sites = current_dataset().sites
        return {(t, c): int(n) for (t, c), n in sites.groupby(['report_type', 'circle']).size().items()}
    except Exception as exc:  # no workbook / database data loaded: rates are shown as unavailable
        logger.info('RCA summary: site population unavailable (%s)', exc)
        return None


def summary(params) -> dict:
    qs = filtered(params)
    totals = qs.aggregate(records=Count('id'), minutes=Sum('outage_minutes'),
                          with_minutes=Count('id', filter=Q(outage_minutes__isnull=False)))
    sites = qs.values('project', 'site_key').distinct().count()
    not_applicable = qs.filter(NOT_APPLICABLE_Q)
    applicable = qs.exclude(NOT_APPLICABLE_Q)
    na = not_applicable.aggregate(records=Count('id'), minutes=Sum('outage_minutes'),
                                  blank_bucket_2=Count('id', filter=Q(bucket_2_key='')))
    applicable_count = applicable.count()
    missing = applicable.filter(BLANK_CAUSE_Q)
    missing_count = missing.count()

    def ranked(base: QuerySet, key: str, label: str) -> list[dict]:
        labels = _labels(base, key, label)
        variants = _variants(base, key, label)
        rows = base.values(key).annotate(records=Count('id'), minutes=Sum('outage_minutes'))
        items = [{'key': r[key] or UNCLASSIFIED, 'label': labels[r[key]] if r[key] else 'Unclassified (blank or "-")',
                  'unclassified': not r[key], 'rca_not_applicable': key == 'final_bucket_key' and r[key] in RCA_NOT_APPLICABLE,
                  'records': r['records'], 'outage_minutes': _round(r['minutes']),
                  'variants': variants.get(r[key], []) if r[key] else []} for r in rows]
        # Technical causes first (ranked), then RCA-not-applicable groups, then unclassified.
        return sorted(items, key=lambda i: (i['unclassified'], i['rca_not_applicable'], -i['records'], i['label'].casefold()))

    population = _population()
    circles = []
    for r in qs.values('project', 'circle').annotate(records=Count('id'), minutes=Sum('outage_minutes'),
                                                     sites=Count('site_key', distinct=True)):
        pop = population.get((r['project'], r['circle'])) if population else None
        circles.append({
            'project': r['project'], 'circle': r['circle'], 'records': r['records'], 'outage_minutes': _round(r['minutes']),
            'affected_sites': r['sites'], 'portfolio_sites': pop,
            # Rates only with a population: raw counts are not a fair comparison between circles of different sizes.
            'records_per_100_sites': round(100 * r['records'] / pop, 1) if pop else None,
            'minutes_per_portfolio_site': round((r['minutes'] or 0) / pop, 1) if pop and r['minutes'] is not None else None,
        })
    circles.sort(key=lambda c: -c['records'])

    mapped = qs.filter(category_id__isnull=False)
    categories = [{'id': r['category_id'], 'name': r['category_name'], 'records': r['records'], 'outage_minutes': _round(r['minutes'])}
                  for r in mapped.values('category_id', 'category_name').annotate(records=Count('id'), minutes=Sum('outage_minutes')).order_by('-records')]
    unreviewed = qs.filter(category_id__isnull=True).exclude(rca_key='').aggregate(records=Count('id'), minutes=Sum('outage_minutes'),
                                                                                   descriptions=Count('rca_key', distinct=True))
    no_text = qs.filter(rca_key='').aggregate(records=Count('id'), minutes=Sum('outage_minutes'))

    top = qs.select_related('workflow').filter(outage_minutes__isnull=False).order_by('-outage_minutes', 'id')[:15]
    return {
        'kpis': {
            'records': totals['records'], 'affected_sites': sites, 'outage_minutes': _round(totals['minutes']),
            'records_with_minutes': totals['with_minutes'],
            # Missing information counts RCA-applicable records only; Other Media is reported separately.
            'incomplete_records': missing_count,
            'incomplete_by_field': {
                'final_bucket': applicable.filter(final_bucket_key='').count(), 'bucket_2': applicable.filter(bucket_2_key='').count(),
                'rca': applicable.filter(rca_key='').count(),
            },
            'missing_label': MISSING_LABEL,
            'rca_applicable_records': applicable_count,
            'completeness_pct': round(100 * (applicable_count - missing_count) / applicable_count, 1) if applicable_count else None,
            'rca_not_applicable': {
                'label': NOT_APPLICABLE_LABEL, 'final_buckets': list(RCA_NOT_APPLICABLE.values()),
                'records': na['records'], 'outage_minutes': _round(na['minutes']), 'blank_bucket_2': na['blank_bucket_2'],
            },
        },
        'dates': [{'date': r['reporting_date'].isoformat(), 'records': r['n']}
                  for r in qs.values('reporting_date').annotate(n=Count('id')).order_by('reporting_date')],
        'final_buckets': ranked(qs, 'final_bucket_key', 'final_bucket'),
        # Bucket - 2 is a cause breakdown: RCA-applicable records only (Other Media is counted in kpis.rca_not_applicable).
        'bucket_2': ranked(applicable, 'bucket_2_key', 'bucket_2'),
        'circles': circles,
        'population_source': 'Sites per circle in the dashboard\'s current Master data' if population else None,
        'categories': {
            'mapped': categories,
            'unreviewed': {'records': unreviewed['records'], 'outage_minutes': _round(unreviewed['minutes']), 'descriptions': unreviewed['descriptions']},
            'no_description': {'records': no_text['records'], 'outage_minutes': _round(no_text['minutes'])},
        },
        'top_records': [record_json(r) for r in top],
    }


def cause_queue(params) -> dict:
    """Distinct RCA descriptions (by normalised text) with counts; unmapped ones form the review queue."""
    qs = RcaRecord.objects.order_by().exclude(rca_key='')
    mappings = {m.rca_key: m for m in RcaCauseMapping.objects.select_related('category', 'reviewed_by')}
    texts: dict[str, Counter] = defaultdict(Counter)
    for row in qs.values('rca_key', 'rca_text').annotate(n=Count('id')):
        texts[row['rca_key']][row['rca_text']] += row['n']
    stats = {r['rca_key']: r for r in qs.values('rca_key').annotate(records=Count('id'), minutes=Sum('outage_minutes'))}
    items = []
    for key, counter in texts.items():
        mapping = mappings.get(key)
        items.append({
            'key': key, 'text': counter.most_common(1)[0][0], 'spellings': [t for t, _ in counter.most_common()],
            'records': stats[key]['records'], 'outage_minutes': _round(stats[key]['minutes']),
            'category': {'id': mapping.category_id, 'name': mapping.category.name} if mapping else None,
            'reviewed_by': mapping.reviewed_by.get_username() if mapping and mapping.reviewed_by else None,
            'reviewed_at': mapping.reviewed_at.isoformat() if mapping else None,
        })
    q = (params.get('q') or '').strip().casefold()
    if q:
        items = [i for i in items if any(q in t.casefold() for t in i['spellings'])]
    items.sort(key=lambda i: (-i['records'], i['text'].casefold()))
    unmapped = [i for i in items if i['category'] is None]
    return {
        'categories': [{'id': c.pk, 'name': c.name, 'description': c.description,
                        'descriptions': c.n} for c in RcaCauseCategory.objects.annotate(n=Count('mappings'))],
        'queue': unmapped,
        'mapped': [i for i in items if i['category'] is not None],
        'stats': {
            'descriptions': len(texts), 'mapped_descriptions': sum(1 for k in texts if k in mappings),
            'records': sum(s['records'] for s in stats.values()),
            'mapped_records': sum(s['records'] for k, s in stats.items() if k in mappings),
            'no_description_records': RcaRecord.objects.filter(rca_key='').count(),
        },
    }


def _round(value):
    return None if value is None else round(float(value), 2)

