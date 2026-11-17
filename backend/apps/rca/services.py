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



from django.db.models import Count, Max, Min, OuterRef, Q, QuerySet, Subquery, Sum

from rest_framework.exceptions import ValidationError

from apps.bsnl.classification import (
    filter_by_responsibility,
    get_bucket_classification,
    grouped_responsibility_totals,
    load_bucket_mapping,
    responsibility_label,
    responsibility_options,
)

from . import taxonomy
from .parser import text_key

from . import sitescope

from .breakdown import breakdown, site_metrics

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





def in_scope(pairs) -> QuerySet:

    """Records of the given project/circle pairs (None: every record; see accounts.access)."""

    from apps.accounts.access import pairs_q

    # order_by() clears Meta.ordering, which would otherwise leak into DISTINCT / GROUP BY queries.

    return RcaRecord.objects.order_by().filter(pairs_q(pairs))





def filtered(params, pairs=None, mapping: dict[str, str] | None = None) -> QuerySet:

    """Records matching the query parameters (date / date_from / date_to, project, circle, buckets, category, q),

    within ``pairs`` (the user's permitted project/circle pairs; None: all)."""

    qs = with_category(in_scope(pairs))

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

            if value == UNCLASSIFIED:
                qs = qs.filter(**{field: ''})
            elif name == 'bucket_2':
                qs = qs.filter(sub_bucket_q(value))
            else:
                qs = qs.filter(**{f'{field}__in': equivalent_keys(field, value)})

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

    responsibility = [value.strip() for value in (params.get('responsibility') or '').split(',') if value.strip()]
    if responsibility:
        qs = filter_by_responsibility(qs, responsibility, mapping)

    q = (params.get('q') or '').strip()

    if q:

        qs = qs.filter(Q(site_id__icontains=q) | Q(site_name__icontains=q) | Q(rca_text__icontains=q) | Q(oa__icontains=q) | Q(ba__icontains=q))

    # Site Scope (All / O&M Start / O&M Not Started Sites): one rule for every RCA page (sitescope).

    return sitescope.apply(qs, sitescope.parse(params.get('site_scope')))





def equivalent_keys(field: str, value: str) -> list[str]:
    """Stored keys of ``field`` that are the same bucket as ``value`` (case and whitespace ignored, apps.rca.taxonomy):
    a filter on the approved "NEC Mini link" also selects records uploaded as "NEC minilink"; the stored values are not
    changed."""
    wanted = taxonomy.match_key(value)
    keys = [k for k in RcaRecord.objects.order_by().values_list(field, flat=True).distinct() if k and taxonomy.match_key(k) == wanted]
    return keys or [value]


def sub_bucket_q(value: str) -> Q:
    """Records of a Sub Bucket: its spellings (case and whitespace ignored) plus its approved aliases under their own Final
    Bucket only (taxonomy.ALIASES: "Fluctuation" also selects BSNL Media / HFCL records uploaded as "Flactuation")."""
    q = Q(bucket_2_key__in=equivalent_keys('bucket_2_key', value))
    for final, alias in taxonomy.alias_pairs_of_sub_bucket(value):
        q |= Q(bucket_2_key__in=equivalent_keys('bucket_2_key', alias), final_bucket_key__in=equivalent_keys('final_bucket_key', final))
    return q


def _merge(items: list[dict], group) -> list[dict]:
    """Merge rows that are the same approved bucket under different spellings or spacing (one row, the approved label,
    every uploaded spelling kept in "variants")."""
    out: dict = {}
    for i in items:
        key = group(i)
        if key is None or key not in out:
            out[key if key is not None else id(i)] = i
            continue
        kept = out[key]
        kept['records'] += i['records']
        kept['outage_minutes'] = _round((kept['outage_minutes'] or 0) + (i['outage_minutes'] or 0))
        kept['variants'] = sorted(set(kept['variants']) | set(i['variants']))
    return list(out.values())


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





def options(pairs=None) -> dict:

    qs = in_scope(pairs)

    # The Final Bucket and Sub Bucket filters offer the approved taxonomy only (apps.rca.taxonomy), with the approved names.
    # A Sub Bucket lists the Final Buckets it belongs to ("Fluctuation": BSNL Media, DMW and HFCL); blank Sub Buckets
    # (a warning at upload, never a category) keep their own "Unclassified" choice.
    final_buckets = [{'value': text_key(f), 'label': f, 'unclassified': False, 'approved': True} for f in taxonomy.APPROVED]
    sub_buckets: dict[str, dict] = {}
    for final, children in taxonomy.APPROVED.items():
        for child in children:
            item = sub_buckets.setdefault(text_key(child), {'value': text_key(child), 'label': child, 'unclassified': False,
                                                            'approved': True, 'final_buckets': []})
            item['final_buckets'].append(final)
    bucket_2 = [*sub_buckets.values(), {'value': UNCLASSIFIED, 'label': 'Unclassified (blank or "-")', 'unclassified': True, 'approved': False,
                                        'final_buckets': []}]

    return {

        'dates': [d.isoformat() for d in qs.values_list('reporting_date', flat=True).distinct().order_by('reporting_date')],

        # Months with records, and how many of their days have records (a month is aggregated only from these).

        'months': [{'month': m, 'dates_with_records': n} for m, n in sorted(Counter(

            d.strftime('%Y-%m') for d in qs.values_list('reporting_date', flat=True).distinct()).items())],

        'projects': sorted(qs.values_list('project', flat=True).distinct()),

        'circles': [{'project': p, 'circle': c, 'circle_raw': r} for p, c, r in

                    qs.values_list('project', 'circle', 'circle_raw').distinct().order_by('project', 'circle')],

        'final_buckets': final_buckets,

        'bucket_2': bucket_2,

        'responsibilities': responsibility_options(),

        'categories': [{'value': str(c.pk), 'label': c.name} for c in RcaCauseCategory.objects.all()],

        'statuses': [{'value': v, 'label': label} for v, label in RcaWorkflow.Status.choices],

        # The approved bucketization (apps.rca.taxonomy), the one list the pages use.

        'classification': taxonomy.classification(),

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





def record_json(rec: RcaRecord, *, full: bool = False, mapping: dict[str, str] | None = None) -> dict:

    workflow = getattr(rec, 'workflow', None)  # None until someone records follow-up
    classification = get_bucket_classification(rec.final_bucket, mapping if mapping is not None else load_bucket_mapping())
    data = {

        'id': rec.pk, 'reporting_date': rec.reporting_date.isoformat(), 'project': rec.project, 'project_raw': rec.project_raw,

        'circle': rec.circle, 'circle_raw': rec.circle_raw, 'site_id': rec.site_id, 'site_name': rec.site_name,

        'oa': rec.oa, 'ba': rec.ba, 'om_start_raw': rec.om_start_raw, 'om_start': rec.om_start,

        'outage_minutes': rec.outage_minutes, 'final_bucket': rec.final_bucket, 'final_bucket_unclassified': not rec.final_bucket_key,

        'bucket_2': rec.bucket_2, 'bucket_2_unclassified': not rec.bucket_2_key,
        'ownership': classification.ownership, 'responsibility_bucket_2': classification.bucket_2,
        'mapped_bucket': classification.mapped_bucket,

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





def register(params, pairs=None) -> dict:

    mapping = load_bucket_mapping()
    qs = filtered(params, pairs, mapping).select_related('workflow')

    ordering = ORDERINGS.get(params.get('ordering') or 'outage_desc', ORDERINGS['outage_desc'])

    try:

        page = max(1, int(params.get('page') or 1))

        size = min(MAX_PAGE_SIZE, max(1, int(params.get('page_size') or 25)))

    except ValueError as exc:

        raise ValidationError({'page': 'Page and page size must be whole numbers.'}) from exc

    total = qs.count()

    rows = qs.order_by(*ordering)[(page - 1) * size: page * size]
    return {'count': total, 'page': page, 'page_size': size, 'pages': max(1, -(-total // size)),
            'results': [record_json(r, mapping=mapping) for r in rows]}





def _population(scope: str = 'on_air') -> dict[tuple[str, str], int] | None:

    """Sites of the population ``scope`` (On-Air / O&M Start sites of the reporting month) per (project, circle) in the
    dashboard dataset (sitedata), for per-100-site rates; None if unavailable."""

    try:

        from apps.dashboard import metrics
        from apps.sitedata.dashboard_source import dataset

        ds = dataset(None, scope)
        sites = ds.sites[metrics.population_flags(ds, scope)]

        return {(t, c): int(n) for (t, c), n in sites.groupby(['report_type', 'circle']).size().items()}

    except Exception as exc:  # no data in the data layer: rates are shown as unavailable

        logger.info('RCA summary: site population unavailable (%s)', exc)

        return None





def summary(params, pairs=None) -> dict:

    """RCA Summary. ``site_scope`` (all / om_start / om_not_started) filters the RCA records, unchanged; ``scope`` (the
    site population: on_air / om_start, default on_air, invalid -> HTTP 400) decides the site figures: the breakdown's
    Total / O&M Start / USD / NSLA site columns (breakdown.site_metrics, where the two combine: the population narrowed by
    the site scope) and the population of the per-100-site rates (``portfolio_sites``)."""

    from apps.dashboard.metrics import population as population_info
    from apps.dashboard.serializers import parse_scope

    population_scope = parse_scope(params.get('scope'))

    mapping = load_bucket_mapping()
    qs = filtered(params, pairs, mapping)
    responsibility = grouped_responsibility_totals(qs, mapping)

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

        for i in items:

            i['approved'] = key == 'final_bucket_key' and not i['unclassified'] and taxonomy.is_approved_final(i['label'])

            if i['approved']:  # shown with the approved name; the uploaded spellings stay listed as variants

                i['label'] = taxonomy.approved_final(i['label'])

        items = _merge(items, lambda i: ('final', i['label']) if i['approved'] else None)

        # Technical causes first (ranked), then RCA-not-applicable groups, then unclassified.

        return sorted(items, key=lambda i: (i['unclassified'], i['rca_not_applicable'], -i['records'], i['label'].casefold()))



    def ranked_pairs(base: QuerySet) -> list[dict]:

        """Bucket - 2 per Final Bucket: a sub-bucket is always read with its parent ("Fluctuation" under BSNL Media, DMW and

        HFCL are three groups). The filter of a group sets both fields."""

        finals = _labels(base, 'final_bucket_key', 'final_bucket')

        children = _labels(base, 'bucket_2_key', 'bucket_2')

        variants = _variants(base, 'bucket_2_key', 'bucket_2')

        rows = base.values('final_bucket_key', 'bucket_2_key').annotate(records=Count('id'), minutes=Sum('outage_minutes'))

        items = []

        for r in rows:

            fk, ck = r['final_bucket_key'], r['bucket_2_key']

            final, child = finals.get(fk, ''), children.get(ck, '')

            resolved = taxonomy.resolve(final, child)

            status = resolved.status if ck else 'blank'

            final, child = resolved.final_bucket or final, resolved.bucket_2 or child  # approved names where they match

            items.append({'key': f'{fk or UNCLASSIFIED}||{ck or UNCLASSIFIED}', 'label': f'{child} · {final or "no Final Bucket"}' if ck else

                          f'Unclassified (blank or "-") · {final or "no Final Bucket"}', 'unclassified': not ck, 'rca_not_applicable': False,

                          'final_bucket': final, 'bucket_2': child, 'approved': status == 'approved',

                          'filter': {'final_bucket': fk or UNCLASSIFIED, 'bucket_2': ck or UNCLASSIFIED},

                          'records': r['records'], 'outage_minutes': _round(r['minutes']), 'variants': variants.get(ck, []) if ck else []})

        items = _merge(items, lambda i: ('pair', i['final_bucket'], i['bucket_2']) if i['approved'] else None)

        return sorted(items, key=lambda i: (i['unclassified'], -i['records'], i['label'].casefold()))



    pair_status = Counter()

    for r in qs.values('final_bucket', 'bucket_2').annotate(n=Count('id')):

        pair_status[taxonomy.count_status(taxonomy.resolve(r['final_bucket'], r['bucket_2']).status)] += r['n']



    population = _population(population_scope)

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

    projects = [{

        'project': r['project'], 'records': r['records'], 'outage_minutes': _round(r['minutes']), 'affected_sites': r['sites'],

        'rca_not_applicable': r['not_applicable'], 'incomplete_records': r['incomplete'],

    } for r in qs.values('project').annotate(

        records=Count('id'), minutes=Sum('outage_minutes'), sites=Count('site_key', distinct=True),

        not_applicable=Count('id', filter=NOT_APPLICABLE_Q), incomplete=Count('id', filter=~NOT_APPLICABLE_Q & BLANK_CAUSE_Q),

    ).order_by('project')]



    mapped = qs.filter(category_id__isnull=False)

    categories = [{'id': r['category_id'], 'name': r['category_name'], 'records': r['records'], 'outage_minutes': _round(r['minutes'])}

                  for r in mapped.values('category_id', 'category_name').annotate(records=Count('id'), minutes=Sum('outage_minutes')).order_by('-records')]

    unreviewed = qs.filter(category_id__isnull=True).exclude(rca_key='').aggregate(records=Count('id'), minutes=Sum('outage_minutes'),

                                                                                   descriptions=Count('rca_key', distinct=True))

    no_text = qs.filter(rca_key='').aggregate(records=Count('id'), minutes=Sum('outage_minutes'))



    top = qs.select_related('workflow').filter(outage_minutes__isnull=False).order_by('-outage_minutes', 'id')[:15]

    # Circle-wise Root Cause Breakdown: every circle of the selected project (site master), or the selected circle.

    if params.get('circle'):

        breakdown_circles = [params['circle']]

    else:

        breakdown_circles = sorted({c for (t, c) in (population or {}) if not params.get('project') or t == params['project']})

    end = _date(params.get('date'), 'date') or _date(params.get('date_to'), 'date_to')

    latest = qs.aggregate(latest=Max('reporting_date'))['latest']

    through = (end or latest).isoformat() if (end or latest) else None

    scope = sitescope.parse(params.get('site_scope'))

    unscoped = filtered({**dict(params.items()), 'site_scope': sitescope.ALL}, pairs, mapping) if scope != sitescope.ALL else qs

    bounds = qs.aggregate(earliest=Min('reporting_date'), latest=Max('reporting_date'))
    rca_dates = (bounds['earliest'], bounds['latest']) if bounds['earliest'] or bounds['latest'] else None
    circles_for_metrics = sorted(set(breakdown_circles) | set(qs.values_list('circle', flat=True).distinct()))
    site_perf = site_metrics(params, pairs, circles_for_metrics, rca_dates=rca_dates)

    # RCA Scope Toggle for Circle-wise Root Cause Breakdown table only:
    # 'all' (default): all RCA records matching current filters
    # 'nsla': only RCA records belonging to sites of the selected population qualifying as NSLA
    rca_scope = (params.get('rca_scope') or 'all').strip().lower()
    nsla_site_keys = site_perf.get('nsla_site_keys') if site_perf else set()
    all_breakdown = breakdown(qs, circles=breakdown_circles, through=through)
    # NSLA records: matched on (project, site key) (identifiers.key_of on both sides), never on the raw site ID alone.
    nsla_qs = qs.none()
    if nsla_site_keys:
        by_project: dict[str, set[str]] = {}
        for technology, key in nsla_site_keys:
            by_project.setdefault(technology, set()).add(key)
        match = Q()
        for technology, keys in by_project.items():
            match |= Q(project=technology, site_key__in=keys)
        nsla_qs = qs.filter(match)
    nsla_breakdown = breakdown(nsla_qs, circles=breakdown_circles, through=through)

    active_breakdown = nsla_breakdown if rca_scope == 'nsla' else all_breakdown
    active_breakdown['rca_scope'] = rca_scope
    active_breakdown['all_rca_records'] = all_breakdown['records']
    active_breakdown['nsla_rca_records'] = nsla_breakdown['records']
    active_breakdown['sites'] = site_perf
    active_breakdown['missing_availability'] = site_perf.get('missing_availability') if site_perf else None

    return {
        # The Site Scope applied to every figure below, and how the records of the other filters are classified.
        'site_scope': {'scope': scope, 'label': sitescope.SCOPES[scope], 'coverage': sitescope.coverage(unscoped.order_by())},
        # The site population of the site figures (site columns, per-100-site rates).
        'population': population_info(population_scope),
        'breakdown': active_breakdown,
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

        'bucket_2': ranked_pairs(applicable),

        # Records of the filter by approved-classification status (approved pair, approved Final Bucket only, not approved, blank).

        'classification': {k: pair_status.get(k, 0) for k in taxonomy.STATUS_LABELS},

        'circles': circles,

        'projects': projects,

        'population_source': (f"{population_info(population_scope)['label']} per circle in the dashboard's data layer (reporting month)"
                              if population else None),

        'categories': {

            'mapped': categories,

            'unreviewed': {'records': unreviewed['records'], 'outage_minutes': _round(unreviewed['minutes']), 'descriptions': unreviewed['descriptions']},

            'no_description': {'records': no_text['records'], 'outage_minutes': _round(no_text['minutes'])},

        },

        'top_records': [record_json(r, mapping=mapping) for r in top],

        'responsibility': [{'bucket': bucket, 'label': responsibility_label(bucket), **totals}
                           for bucket, totals in responsibility.items()],

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



