import { useMemo } from 'react';
import { useSearchParams } from 'react-router-dom';
import { CircleAlert, Database, RotateCcw, Layers3, ShieldAlert } from 'lucide-react';
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert';
import { Skeleton } from '@/components/ui/skeleton';
import { SelectField } from '../components/data/DataEntry';
import { Button } from '@/components/ui/button';
import { Label } from '@/components/ui/label';
import { BUCKET_COLORS, BUCKET_ORDER } from '../components/dashboard/constants';
import { CircleBreakdownTable } from '../components/portfolio/CircleBreakdownTable';
import { PeriodControls } from '../components/portfolio/PeriodControls';
import { CompositeTile, ConversionActivityTile, KpiSection, KpiTile, SummaryMetricsTile, type Segment } from '../components/portfolio/PortfolioKpis';
import { PeriodStatusBadge, ProvisionalBanner } from '../components/reporting/ReportingStatus';
import { useTracking } from '../context/tracking';
import { PageHeading } from '../context/pageHeader';
import { usePopulation } from '../context/population';
import { PopulationSelect } from '../components/PopulationSelect';
import { useApiQuery } from '../hooks/useApiQuery';
import { useOrganization } from '../hooks/useOrganization';
import { useDashboardFilters } from '../hooks/useDashboardFilters';
import { formatDate, formatNumber, formatPct, formatShortDate } from '../lib/format';
import {
  buildKpis, buildPeriodKpis, circleBreakdown, detailLink, type Kpi, type PortfolioFilters,
} from '../lib/portfolio';
import {
  applyChange, availability, monthPeriod, periodQuery, resolveSelection, shiftMonth, type Period,
} from '../lib/periods';
import {
  fetchPortfolioActivity, fetchPortfolioBreakdowns, fetchPortfolioFilters, fetchPortfolioPeriod, fetchPortfolioSummary,
} from '../services/sitePortfolioApi';

const pctOf = (part: number, whole: number) => (whole ? formatPct((100 * part) / whole, 1) : '—');

/**
 * Executive landing page: portfolio KPIs and the circle-wise breakdown. Reads the new data layer (/api/site-portfolio/):
 * sites, On-Air and O&M Start from the Consolidation Matrix and its dates, availability from the new daily records.
 */
export function PortfolioPage() {
  const options = useApiQuery('site-portfolio|filters', fetchPortfolioFilters);
  const version = options.data?.source.loaded_at ?? '';
  const { filters, setFilters, reset, isDefault } = useDashboardFilters(options.data);
  const { scope, sitesLabel } = usePopulation();
  const [searchParams, setSearchParams] = useSearchParams();
  const { state: tracking, dispatch } = useTracking();

  const f: PortfolioFilters = { reportType: filters?.reportType ?? '', circle: filters?.circle ?? '', date: filters?.date ?? '' };
  const av = useMemo(() => (options.data ? availability(options.data) : null), [options.data]);
  const sel = av && options.data && f.date ? resolveSelection(searchParams, av, options.data.reporting_dates, f.date) : null;
  const daily = !sel || sel.view === 'day';
  // Daily: the comparison date's snapshot. Weekly / monthly: `period/` for both periods.
  const previousDate = daily && sel?.comparison?.available ? sel.comparison.id : null;
  const periodParams = (scope: string, period: Period | null | undefined) => {
    if (!period?.available) return null;
    const q = params(scope, null);
    Object.entries(periodQuery(period)).forEach(([key, value]) => q.set(key, value));
    return q;
  };
  const params = (scope: string, date: string | null, reportType = f.reportType) => {
    const q = new URLSearchParams({ scope });
    if (reportType) q.set('report_type', reportType);
    if (f.circle) q.set('circle', f.circle);
    if (date) q.set('reporting_date', date);
    return q;
  };
  const ready = Boolean(filters && f.date);
  const k = (name: string, q: URLSearchParams) => (ready ? `${version}|${name}|${q}` : null);
  const omAvailable = Boolean(options.data?.scopes.find((s) => s.value === 'om_start')?.available);
  // Site STATUS counts (total scope, On-Air, O&M Start) need both populations' site counts; they are shown as status
  // information only. Every performance figure below uses the selected population alone.
  const statusOm = omAvailable || scope === 'om_start';
  const q = {
    onAir: params('on_air', f.date), omStart: params('om_start', f.date),
    previous: params(scope, previousDate),
  };
  const statusOnAir = useApiQuery(k('status-onAir', q.onAir), (s) => fetchPortfolioSummary(q.onAir, s));
  const statusOmStart = useApiQuery(statusOm ? k('status-om', q.omStart) : null, (s) => fetchPortfolioSummary(q.omStart, s));
  // The selected population's summary is the same request as its status summary (fetched once).
  const selected = scope === 'on_air' ? statusOnAir : statusOmStart;
  const previous = useApiQuery(previousDate ? k('prev', q.previous) : null, (s) => fetchPortfolioSummary(q.previous, s));
  const pq = { sel: daily ? null : periodParams(scope, sel?.selected), cmp: daily ? null : periodParams(scope, sel?.comparison) };
  const periodSel = useApiQuery(pq.sel ? k('period', pq.sel) : null, (s) => fetchPortfolioPeriod(pq.sel!, s));
  const periodCmp = useApiQuery(pq.cmp ? k('period', pq.cmp) : null, (s) => fetchPortfolioPeriod(pq.cmp!, s));
  // Circle-wise status counts: the breakdowns of both populations; the bucket mix uses the selected one.
  const breakdownOnAir = useApiQuery(k('breakdown-onAir', q.onAir), (s) => fetchPortfolioBreakdowns(q.onAir, s));
  const breakdownOm = useApiQuery(statusOm ? k('breakdown-om', q.omStart) : null, (s) => fetchPortfolioBreakdowns(q.omStart, s));
  const breakdown = scope === 'on_air' ? breakdownOnAir : breakdownOm;
  const organization = useOrganization();
  // On-Air / O&M Start this month vs last month (Consolidation Matrix dates in the new data layer); the month is the selected date's.
  const activityParams = new URLSearchParams();
  if (f.reportType) activityParams.set('report_type', f.reportType);
  if (f.circle) activityParams.set('circle', f.circle);
  if (f.date) activityParams.set('month', f.date.slice(0, 7));
  const activity = useApiQuery(options.data ? `portfolio-activity|${activityParams}` : null, (s) => fetchPortfolioActivity(activityParams, s));
  const earlierActivityParams = new URLSearchParams(activityParams);
  if (f.date) earlierActivityParams.set('month', shiftMonth(f.date.slice(0, 7), -1));
  const earlierActivity = useApiQuery(ready ? `portfolio-activity-earlier|${earlierActivityParams}` : null,
    (s) => fetchPortfolioActivity(earlierActivityParams, s));

  // No fallback: if the new data layer cannot serve the page, its error is shown and no figures.
  const fatal = options.error ?? statusOnAir.error ?? selected.error;
  if (fatal) {
    return (
      <Alert variant="destructive" className="mx-auto mt-10 max-w-2xl">
        <Database />
        <AlertTitle>Portfolio data is unavailable</AlertTitle>
        <AlertDescription>{fatal.message} No sample or estimated figures are shown in its place.</AlertDescription>
      </Alert>
    );
  }
  if (!options.data || !filters || !statusOnAir.data || !selected.data || !av || !sel) {
    return (
      <div className="space-y-3" aria-busy="true" aria-label="Loading site portfolio">
        <Skeleton className="h-10 w-72" />
        <Skeleton className="h-20 w-full" />
        <div className="grid grid-cols-2 gap-2.5 xl:grid-cols-4">{Array.from({ length: 8 }, (_, i) => <Skeleton key={i} className="h-20" />)}</div>
      </div>
    );
  }

  const summary = selected.data;
  const day = formatShortDate(summary.reporting_date);
  const mtdLabel = `MTD ${formatShortDate(summary.mtd_window.start).slice(0, 2)}–${day}`;
  const total = statusOnAir.data.metrics.sites_total;
  const onAirSites = statusOnAir.data.metrics.sites_in_scope;
  const omSites = statusOmStart.data?.metrics.sites_in_scope ?? null;
  const kpiList = buildKpis({ selected: summary, previous: previous.data, status: { total, onAir: onAirSites, omStart: omSites } }, f,
    { day: `On ${day}`, mtd: mtdLabel }, sitesLabel);
  const byId = Object.fromEntries(kpiList.map((x) => [x.id, x])) as Record<string, Kpi>;
  const comparison = sel.comparison;
  const compareOn = Boolean(comparison?.available);
  const vsLabel = comparison ? `vs ${daily ? formatShortDate(comparison.id) : comparison.label.split(' · ')[0]}` : undefined;
  // Weekly / monthly figures; the date range shown is the one the backend used.
  const periodData = !daily && periodSel.data ? periodSel.data : null;
  const cmpData = !daily && periodCmp.data ? periodCmp.data : null;
  const shortLabel = sel.selected.label.split(' · ')[0];
  // Threshold Analysis has these periods for the reporting month only (weeks, MTD) and for full months.
  const thresholdsPeriod = sel.view === 'week' && sel.week.startsWith(av.currentMonth) ? `w${sel.week.slice(-1)}`
    : sel.view === 'month' && sel.basis === 'full' ? sel.month : null;
  // Days compared: calendar days for full months, days with data otherwise.
  const lengthOf = (d: { kind: string; days_reported: number } | null | undefined, p: Period | null) => (!d || !p ? null : d.kind === 'months' ? p.days : d.days_reported);
  const [selDays, cmpDays] = [lengthOf(periodSel.data, sel.selected), lengthOf(periodCmp.data, comparison)];
  const lengthsDiffer = selDays != null && cmpDays != null && selDays !== cmpDays;
  const periodKpis = periodData ? Object.fromEntries(buildPeriodKpis(periodData, cmpData, { ...f, date: av.latest }, shortLabel, thresholdsPeriod, !lengthsDiffer, sitesLabel).map((x) => [x.id, x])) as Record<string, Kpi> : null;
  const monthEnabled = (key: string, forComparison: boolean) => {
    if (!forComparison && !av.fullMonths.has(key) && !av.dailyMonths.has(key)) return 'No data in the workbook';
    if (forComparison) {
      const p = monthPeriod(key, sel.basis, av);
      return p.available ? null : p.reason ?? 'Not available';
    }
    return null;
  };
  const populationSites = summary.metrics.sites_in_scope;
  // Per project: the circle-wise breakdowns of the same filters, summed by report type. A split is shown only when it
  // adds up to its KPI's total, so the lines under a KPI always reconcile with it.
  const byProject = (b: typeof breakdownOnAir.data | null | undefined, field: 'sites_in_scope' | 'sites_total' = 'sites_in_scope') => {
    if (!b) return null;
    const totals = new Map<string, number>();
    for (const c of b.circles) totals.set(c.report_type, (totals.get(c.report_type) ?? 0) + c[field]);
    return totals;
  };
  const [scopeBy, onAirBy, omBy] = [byProject(breakdownOnAir.data, 'sites_total'), byProject(breakdownOnAir.data), omAvailable ? byProject(breakdownOm.data) : null];
  // Organization order first; a project in the data but not (yet) in the Organization is still shown, after them.
  const order = (organization.data?.projects ?? []).map((p) => p.key);
  const projectKeys = new Set([...(scopeBy?.keys() ?? []), ...(onAirBy?.keys() ?? []), ...(omBy?.keys() ?? [])]);
  const projects = [...order.filter((type) => projectKeys.has(type)), ...[...projectKeys].filter((type) => !order.includes(type)).sort()];
  const split = (counts: Map<string, number> | null, kpiTotal: number | null) => {
    if (!counts || kpiTotal == null) return null;
    const rows = projects.map((project) => ({ project, value: counts.get(project) ?? 0 }));
    return rows.reduce((n, r) => n + r.value, 0) === kpiTotal ? rows : null;
  };
  const omDiffBy = onAirBy && omBy ? new Map(projects.map((type) => [type, (onAirBy.get(type) ?? 0) - (omBy.get(type) ?? 0)])) : null;
  // Difference = On-Air − O&M Start, from the two API counts (On-Air and O&M Start scopes of summary/).
  const omDifference = omSites == null ? null : onAirSites - omSites;
  const month = options.data.month.label;
  const bucketCounts = new Map((breakdown.data?.buckets ?? []).map((b) => [b.id, b]));
  const bucketSegments: Segment[] | null = breakdown.data ? [...BUCKET_ORDER].reverse().map((id) => ({
    label: bucketCounts.get(id)?.label ?? id, value: bucketCounts.get(id)?.count ?? 0, color: BUCKET_COLORS[id],
  })) : null;
  const bucketed = (bucketSegments ?? []).reduce((sum, x) => sum + x.value, 0);
  const belowSla = breakdown.data
    ? BUCKET_ORDER.slice(0, -1).reduce((sum, id) => sum + (bucketCounts.get(id)?.count ?? 0), 0)
    : null;
  const belowSlaKpi: Kpi = {
    ...byId.gte_98_5,
    id: 'below_98_5',
    label: 'Sites Not Meeting SLA',
    value: belowSla,
    period: mtdLabel,
    definition: `${sitesLabel} with MTD availability below 98.5%, summed across all lower uptime buckets.`,
    delta: null,
    higherIsBetter: false,
    link: detailLink('/thresholds', f),
    tone: belowSla ? 'critical' : undefined,
  };
  const scopeText = [f.circle ? `Circle ${f.circle}` : 'All circles', f.reportType || 'All projects'].join(' · ');
  const periodBucketSegments: Segment[] | null = periodData?.buckets ? [...BUCKET_ORDER].reverse().map((id) => ({
    label: bucketCounts.get(id)?.label ?? options.data!.buckets.find((b) => b.id === id)?.label ?? id, value: periodData.buckets![id], color: BUCKET_COLORS[id],
  })) : null;
  const periodBucketed = (periodBucketSegments ?? []).reduce((sum, x) => sum + x.value, 0);
  const periodError = periodSel.error ?? periodCmp.error;
  const continuity = options.data.source.continuity;
  const daysUsed = periodSel.data ? ` · ${periodSel.data.days_reported} reporting days` : '';

  return (
    <div className="space-y-3">
      <PageHeading title="Site Portfolio — Summary"
        subtitle={`${scopeText} · Population: ${sitesLabel} · ${daily ? `${formatDate(summary.reporting_date)} · ${mtdLabel} (${summary.mtd_window.days_reported} days)` : `${sel.selected.label}${daysUsed}`}`} />
      <PeriodControls av={av} reportingDates={options.data.reporting_dates} sel={sel}
        onChange={(change) => setSearchParams((cur) => applyChange(cur, change), { replace: true })} monthEnabled={monthEnabled}
        notes={lengthsDiffer ? [`The periods cover a different number of days (${selDays} and ${cmpDays}): compare uptime and shares; outage minutes are not compared.`] : []}>
        <div className="flex items-start gap-2">
        <div className="flex flex-col gap-1">
          <Label htmlFor="portfolio-project" className="text-[11px] font-medium text-muted-foreground">Project</Label>
          <div className="w-36">
            <SelectField id="portfolio-project" value={f.reportType || 'all'} placeholder="All projects"
              onChange={(v) => {
                const reportType = v === 'all' ? '' : v;
                const keepCircle = options.data!.circles.find((c) => c.value === f.circle)?.report_types.includes(reportType);
                setFilters({ reportType, ...(reportType && !keepCircle ? { circle: '' } : {}) });
              }}
              options={[{ value: 'all', label: 'All projects' }, ...options.data.report_types.map((t) => ({ value: t.value, label: t.label }))]} />
          </div>
        </div>
        <div className="flex flex-col gap-1">
          <Label htmlFor="portfolio-circle" className="text-[11px] font-medium text-muted-foreground">Circle</Label>
          <div className="w-32">
            <SelectField id="portfolio-circle" value={f.circle || 'all'} placeholder="All circles" onChange={(v) => setFilters({ circle: v === 'all' ? '' : v })}
              options={[{ value: 'all', label: 'All circles' }, ...options.data.circles.filter((c) => !f.reportType || c.report_types.includes(f.reportType)).map((c) => ({ value: c.value, label: c.label }))]} />
          </div>
        </div>
        <PopulationSelect id="portfolio-population" unavailable={omAvailable ? [] : ['om_start']} />
        <Button type="button" variant="ghost" size="icon" className="mt-5 size-9" aria-label="Reset filters" title="Reset filters"
          disabled={isDefault && !searchParams.get('view') && !searchParams.get('vs')} onClick={() => { reset(); setSearchParams(new URLSearchParams({ scope }), { replace: true }); }}>
          <RotateCcw />
        </Button>
        </div>
      </PeriodControls>

      <ProvisionalBanner compact continuity={summary.source.continuity ?? continuity} />
      {periodSel.data?.status && !daily && (
        <p className="flex flex-wrap items-center gap-1.5 text-xs text-muted-foreground" aria-label="Period status">
          {sel.selected.label}: <PeriodStatusBadge status={periodSel.data.status} missing={periodSel.data.missing} />
          {periodCmp.data?.status && <>· comparison: <PeriodStatusBadge status={periodCmp.data.status} missing={periodCmp.data.missing} /></>}
        </p>
      )}

      {continuity && (continuity.excluded_after_gap?.length ?? 0) > 0 && (
        <Alert className="border-amber-300 bg-amber-50/70">
          <CircleAlert className="text-amber-700" />
          <AlertTitle>MTD ends on {formatDate(continuity.continuous_until)}</AlertTitle>
          <AlertDescription>
            A reporting date after it has no data, so MTD stops there. Later dates with data ({continuity.excluded_after_gap.map(formatShortDate).join(', ')}) are
            not used until the missing date is reported.
          </AlertDescription>
        </Alert>
      )}

      <KpiSection label="Site status (not filtered by population)" columns="portfolio">
        {/* Site status: total sites and On-Air vs O&M Start, in one compact card (status information, not performance). */}
        <SummaryMetricsTile label="Site status: total, On-Air & O&M Start"
          definition={`Site status, shown whatever the population. Total sites: every dashboard site of the Consolidation Matrix for the filter. On-Air sites: Site On-Air Date on or before the end of ${month}. O&M Start sites: O&M Start Date on or before the end of ${month} (a site without a date is not counted and is flagged for review). Percentages are of total sites. Difference = On-Air sites − O&M Start sites: On-Air sites not yet recorded as O&M Start (a blank or 0 flag means not recorded, not a confirmed failure). The 4G Saturation / LWE lines are the circle-wise counts summed per project (Difference per project = its On-Air − its O&M Start); they are shown only when they add up to the total.`}
          metrics={[
            { label: 'Total sites', value: total, tone: 'neutral', split: split(scopeBy, total), note: 'Site status · Consolidation Matrix' },
            { label: 'On-Air sites', value: onAirSites, tone: 'onAir', split: split(onAirBy, onAirSites), pct: total ? (100 * onAirSites) / total : null, note: `of ${formatNumber(total)} sites` },
            { label: 'O&M Start sites', value: omSites, tone: 'omStart', missing: 'No O&M Start column', split: split(omBy, omSites),
              pct: omSites != null && total ? (100 * omSites) / total : null, note: omSites == null ? undefined : `${month} status` },
            { label: 'Difference', value: omDifference, tone: 'gap', split: split(omDiffBy, omDifference), note: 'On-Air, not yet O&M Start' },
          ]} />
        <ConversionActivityTile total={total} onAir={onAirSites} omStart={omSites} activity={activity.data}
          earlierActivity={earlierActivity.data} earlierActivityLoading={earlierActivity.loading} earlierActivityError={earlierActivity.error}
          definition={`Site status, shown whatever the population. Achievement against total site scope (${formatNumber(total)} sites in the filter, Consolidation Matrix): Site On-Air Date and O&M Start Date on or before the end of ${month}; the gap is total scope minus that count (a site without a date is not counted). Monthly additions count sites by their Site On-Air Date and O&M Start Date in the Consolidation Matrix; a month later than the latest date in the matrix shows "—", not 0.`} />
      </KpiSection>

      {daily ? (
      <>
      <KpiSection label={`Uptime buckets (MTD) · Population: ${sitesLabel}`} columns="uptime">
        <KpiTile kpi={belowSlaKpi} of={`of ${formatNumber(bucketed)} sites with a value`} compareOn={false}
          icon={ShieldAlert} tint="red" view="Open Threshold Analysis"
          sub={`${belowSla == null ? '—' : pctOf(belowSla, bucketed)} of sites with a value`} />
        <KpiTile kpi={byId.gte_98_5} of={`of ${formatNumber(populationSites)}`} compareOn={compareOn} vsLabel={vsLabel}
          sub={`${pctOf(summary.metrics.sites_at_or_above_98_5_mtd, populationSites)} of ${sitesLabel}`} />
        <KpiTile kpi={byId.lt_60} of={`of ${formatNumber(populationSites)}`} compareOn={compareOn} vsLabel={vsLabel}
          sub={`${pctOf(summary.metrics.sites_below_60_mtd, populationSites)} of ${sitesLabel}`} />
        <CompositeTile label="Uptime bucket mix" icon={Layers3} tint="orange" value={breakdown.data ? bucketed : null} unit={`${sitesLabel} with a value`}
          definition={`${sitesLabel} by their own MTD uptime, in the workbook's buckets (each lower bound included). Shares are of the sites with a value this month; sites that never reported are not placed in a bucket.`}
          sub={bucketed && populationSites > bucketed ? `${formatNumber(populationSites - bucketed)} ${sitesLabel} have no value yet` : undefined}
          segments={bucketSegments} link={detailLink('/thresholds', f)} view="Open Threshold Analysis"
          note={breakdown.error ? breakdown.error.message : breakdown.data ? undefined : 'Loading…'} />
      </KpiSection>
      </>
      ) : !sel.selected.available ? (
        <Alert className="border-amber-300 bg-amber-50/70"><CircleAlert className="text-amber-700" /><AlertTitle>{sel.selected.label}: not available</AlertTitle>
          <AlertDescription>{sel.selected.reason} Choose another {sel.view === 'week' ? 'week' : 'month or basis'}.</AlertDescription></Alert>
      ) : periodError ? (
        <Alert variant="destructive"><Database /><AlertTitle>Period figures unavailable</AlertTitle><AlertDescription>{periodError.message}</AlertDescription></Alert>
      ) : !periodKpis || !periodData ? (
        <div className="grid grid-cols-2 gap-2.5 xl:grid-cols-4" aria-busy="true" aria-label="Loading period figures">{Array.from({ length: 4 }, (_, i) => <Skeleton key={i} className="h-28" />)}</div>
      ) : (
      <>
      <KpiSection label={`Uptime buckets · ${shortLabel}${daysUsed} · Population: ${sitesLabel}`}>
        <KpiTile kpi={periodKpis.gte_98_5} of={`of ${formatNumber(periodData.sites_in_scope)}`} compareOn={Boolean(cmpData)} vsLabel={vsLabel}
          sub={`${pctOf(periodData.sites_at_or_above_98_5, periodData.sites_in_scope)} of ${sitesLabel}`} />
        <KpiTile kpi={periodKpis.lt_60} of={`of ${formatNumber(periodData.sites_in_scope)}`} compareOn={Boolean(cmpData)} vsLabel={vsLabel}
          sub={`${pctOf(periodData.sites_below_60, periodData.sites_in_scope)} of ${sitesLabel}`} />
        <CompositeTile label="Uptime bucket mix" icon={Layers3} tint="orange" value={periodBucketSegments ? periodBucketed : null} unit={`${sitesLabel} with a value`}
          definition={`${sitesLabel} by their own uptime over ${shortLabel}, in the workbook's buckets (each lower bound included). Sites without a value are not placed in a bucket.`}
          sub={periodBucketed && periodData.sites_in_scope > periodBucketed ? `${formatNumber(periodData.sites_in_scope - periodBucketed)} ${sitesLabel} have no value in the period` : undefined}
          segments={periodBucketSegments} link={detailLink('/thresholds', { ...f, date: av.latest }, thresholdsPeriod ? { period: thresholdsPeriod } : {})} view="Open Threshold Analysis" />
      </KpiSection>
      </>
      )}

      {breakdownOnAir.data && (!omAvailable || breakdownOm.data) && breakdown.data ? (
        <CircleBreakdownTable
          {...circleBreakdown(breakdownOnAir.data, omAvailable ? breakdownOm.data : null, breakdown.data)}
          notes={tracking.portfolioNotes}
          onSaveNote={(key, note) => dispatch({ type: 'saveNote', key, note })}
          loading={breakdownOnAir.loading || breakdownOm.loading}
          periodNote={`Site status (shown whatever the population). Site counts come from the Site On-Air and O&M Start Dates in the Consolidation Matrix for ${month} (${summary.source.workbook}); the reporting date does not change them.`} />
      ) : breakdownOnAir.error ?? breakdownOm.error ? (
        <Alert variant="destructive"><AlertTitle>Circle-wise breakdown unavailable</AlertTitle><AlertDescription>{(breakdownOnAir.error ?? breakdownOm.error)!.message}</AlertDescription></Alert>
      ) : <Skeleton className="h-80 w-full" aria-label="Loading circle-wise breakdown" />}

    </div>
  );
}
