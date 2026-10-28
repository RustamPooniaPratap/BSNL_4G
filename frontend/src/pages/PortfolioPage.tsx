import { useMemo } from 'react';
import { useSearchParams } from 'react-router-dom';
import { CircleAlert, Database, RotateCcw, Layers3 } from 'lucide-react';
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert';
import { Skeleton } from '@/components/ui/skeleton';
import { NoWorkbook, SelectField } from '../components/data/DataEntry';
import { Button } from '@/components/ui/button';
import { Label } from '@/components/ui/label';
import { BUCKET_COLORS, BUCKET_ORDER } from '../components/dashboard/constants';
import { CircleBreakdownTable } from '../components/portfolio/CircleBreakdownTable';
import { PeriodControls } from '../components/portfolio/PeriodControls';
import { CompositeTile, ConversionActivityTile, KpiSection, KpiTile, SummaryMetricsTile, type Segment } from '../components/portfolio/PortfolioKpis';
import { useTracking } from '../context/tracking';
import { PageHeading } from '../context/pageHeader';
import { useWorkbook } from '../context/workbook';
import { useApiQuery } from '../hooks/useApiQuery';
import { useDashboardFilters } from '../hooks/useDashboardFilters';
import { formatDate, formatNumber, formatPct, formatShortDate } from '../lib/format';
import {
  buildKpis, buildPeriodKpis, circleBreakdown, detailLink, type Kpi, type PortfolioFilters,
} from '../lib/portfolio';
import {
  applyChange, availability, monthPeriod, periodQuery, resolveSelection, type Period,
} from '../lib/periods';
import { fetchBreakdowns, fetchConversionActivity, fetchOmHeads, fetchPeriod, fetchFilterOptions, fetchSummary } from '../services/api';

const pctOf = (part: number, whole: number) => (whole ? formatPct((100 * part) / whole, 1) : '—');

/** Executive landing page: portfolio KPIs and the circle-wise breakdown. */
export function PortfolioPage() {
  const workbook = useWorkbook();
  const { version } = workbook;
  const options = useApiQuery(workbook.active ? `${version}|filters` : null, fetchFilterOptions);
  const { filters, setFilters, reset, isDefault } = useDashboardFilters(options.data);
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
  const q = {
    onAir: params('on_air', f.date), omStart: params('om_start', f.date), all: params('all', f.date),
    previous: params('on_air', previousDate),
  };

  const onAir = useApiQuery(k('onAir', q.onAir), (s) => fetchSummary(q.onAir, s));
  const omStart = useApiQuery(omAvailable ? k('om', q.omStart) : null, (s) => fetchSummary(q.omStart, s));
  const all = useApiQuery(k('all', q.all), (s) => fetchSummary(q.all, s));
  const previous = useApiQuery(previousDate ? k('prev', q.previous) : null, (s) => fetchSummary(q.previous, s));
  const pq = {
    sel: daily ? null : periodParams('on_air', sel?.selected), selOm: daily || !omAvailable ? null : periodParams('om_start', sel?.selected),
    cmp: daily ? null : periodParams('on_air', sel?.comparison), cmpOm: daily || !omAvailable ? null : periodParams('om_start', sel?.comparison),
  };
  const periodSel = useApiQuery(pq.sel ? k('period', pq.sel) : null, (s) => fetchPeriod(pq.sel!, s));
  const periodSelOm = useApiQuery(pq.selOm ? k('period', pq.selOm) : null, (s) => fetchPeriod(pq.selOm!, s));
  const periodCmp = useApiQuery(pq.cmp ? k('period', pq.cmp) : null, (s) => fetchPeriod(pq.cmp!, s));
  const periodCmpOm = useApiQuery(pq.cmpOm ? k('period', pq.cmpOm) : null, (s) => fetchPeriod(pq.cmpOm!, s));
  const breakdown = useApiQuery(k('breakdown', q.onAir), (s) => fetchBreakdowns(q.onAir, s));
  // Site Scope and O&M Start by circle: the same breakdown for the other two scopes.
  const breakdownAll = useApiQuery(k('breakdownAll', q.all), (s) => fetchBreakdowns(q.all, s));
  const breakdownOm = useApiQuery(omAvailable ? k('breakdownOm', q.omStart) : null, (s) => fetchBreakdowns(q.omStart, s));
  const omHeadSheet = useApiQuery(workbook.active ? 'om-heads' : null, fetchOmHeads);
  const omHeads = Object.fromEntries((omHeadSheet.data?.heads ?? []).map((h) => [`${h.report_type}|${h.circle}`, h.om_head]));
  // On-Air / O&M Start this month vs last month (dated escalation matrix); the month is the selected date's.
  const activityParams = new URLSearchParams();
  if (f.reportType) activityParams.set('report_type', f.reportType);
  if (f.circle) activityParams.set('circle', f.circle);
  if (f.date) activityParams.set('month', f.date.slice(0, 7));
  const activity = useApiQuery(workbook.active ? `activity|${activityParams}` : null, (s) => fetchConversionActivity(activityParams, s));

  if (!workbook.loading && !workbook.active) return <NoWorkbook />;
  const fatal = workbook.error ?? options.error ?? onAir.error ?? all.error;
  if (fatal) {
    return (
      <Alert variant="destructive" className="mx-auto mt-10 max-w-2xl">
        <Database />
        <AlertTitle>Portfolio data is unavailable</AlertTitle>
        <AlertDescription>{fatal.message} No sample or estimated figures are shown in its place.</AlertDescription>
      </Alert>
    );
  }
  if (!options.data || !filters || !onAir.data || !all.data || !av || !sel) {
    return (
      <div className="space-y-4" aria-busy="true" aria-label="Loading site portfolio">
        <Skeleton className="h-10 w-72" />
        <Skeleton className="h-20 w-full" />
        <div className="grid grid-cols-2 gap-3 xl:grid-cols-4">{Array.from({ length: 8 }, (_, i) => <Skeleton key={i} className="h-28" />)}</div>
      </div>
    );
  }

  const summary = onAir.data;
  const day = formatShortDate(summary.reporting_date);
  const mtdLabel = `MTD ${formatShortDate(summary.mtd_window.start).slice(0, 2)}–${day}`;
  const kpiList = buildKpis({ onAir: summary, omStart: omStart.data, all: all.data, previous: previous.data }, f, { day: `On ${day}`, mtd: mtdLabel });
  const byId = Object.fromEntries(kpiList.map((x) => [x.id, x])) as Record<string, Kpi>;
  const comparison = sel.comparison;
  const compareOn = Boolean(comparison?.available);
  const vsLabel = comparison ? `vs ${daily ? formatShortDate(comparison.id) : comparison.label.split(' · ')[0]}` : undefined;
  // Weekly / monthly figures; the date range shown is the one the backend used.
  const periodData = !daily && periodSel.data ? { onAir: periodSel.data, omStart: periodSelOm.data } : null;
  const cmpData = !daily && periodCmp.data ? { onAir: periodCmp.data, omStart: periodCmpOm.data } : null;
  const shortLabel = sel.selected.label.split(' · ')[0];
  // Threshold Analysis has these periods for the reporting month only (weeks, MTD) and for full months.
  const thresholdsPeriod = sel.view === 'week' && sel.week.startsWith(av.currentMonth) ? `w${sel.week.slice(-1)}`
    : sel.view === 'month' && sel.basis === 'full' ? sel.month : null;
  // Days compared: calendar days for full months, days with data otherwise.
  const lengthOf = (d: { kind: string; days_reported: number } | null | undefined, p: Period | null) => (!d || !p ? null : d.kind === 'months' ? p.days : d.days_reported);
  const [selDays, cmpDays] = [lengthOf(periodSel.data, sel.selected), lengthOf(periodCmp.data, comparison)];
  const lengthsDiffer = selDays != null && cmpDays != null && selDays !== cmpDays;
  const periodKpis = periodData ? Object.fromEntries(buildPeriodKpis(periodData, cmpData, { ...f, date: av.latest }, shortLabel, thresholdsPeriod, !lengthsDiffer).map((x) => [x.id, x])) as Record<string, Kpi> : null;
  const monthEnabled = (key: string, forComparison: boolean) => {
    if (!forComparison && !av.fullMonths.has(key) && !av.dailyMonths.has(key)) return 'No data in the workbook';
    if (forComparison) {
      const p = monthPeriod(key, sel.basis, av);
      return p.available ? null : p.reason ?? 'Not available';
    }
    return null;
  };
  const total = all.data.metrics.sites_total;
  const onAirSites = summary.metrics.sites_in_scope;
  const omSites = omStart.data?.metrics.sites_in_scope ?? null;
  // Per project: the circle-wise breakdowns of the same scopes and filters, summed by report type. A split is
  // shown only when it adds up to its KPI's total, so the lines under a KPI always reconcile with it.
  const PROJECTS = ['4G Saturation', 'LWE'];
  const byProject = (b: typeof breakdownAll.data | null | undefined) => {
    if (!b) return null;
    const totals = new Map<string, number>();
    for (const c of b.circles) totals.set(c.report_type, (totals.get(c.report_type) ?? 0) + c.sites_in_scope);
    return totals;
  };
  const [scopeBy, onAirBy, omBy] = [byProject(breakdownAll.data), byProject(breakdown.data), omAvailable ? byProject(breakdownOm.data) : null];
  const projects = PROJECTS.filter((type) => scopeBy?.has(type));
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
  const scopeText = [f.circle ? `Circle ${f.circle}` : 'All circles', f.reportType || 'All projects'].join(' · ');
  const periodBucketSegments: Segment[] | null = periodData?.onAir.buckets ? [...BUCKET_ORDER].reverse().map((id) => ({
    label: bucketCounts.get(id)?.label ?? options.data!.buckets.find((b) => b.id === id)?.label ?? id, value: periodData.onAir.buckets![id], color: BUCKET_COLORS[id],
  })) : null;
  const periodBucketed = (periodBucketSegments ?? []).reduce((sum, x) => sum + x.value, 0);
  const periodError = periodSel.error ?? periodCmp.error;

  return (
    <div className="space-y-4">
      <PageHeading title="Site Portfolio — Summary"
        subtitle={`${scopeText} · ${daily ? `${formatDate(summary.reporting_date)} · ${mtdLabel} (${summary.mtd_window.days_reported} days)` : sel.selected.label}`} />
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
        <Button type="button" variant="ghost" size="icon" className="mt-5 size-9" aria-label="Reset filters" title="Reset filters"
          disabled={isDefault && !searchParams.get('view') && !searchParams.get('vs')} onClick={() => { reset(); setSearchParams(new URLSearchParams(), { replace: true }); }}>
          <RotateCcw />
        </Button>
        </div>
      </PeriodControls>

      <KpiSection label="Site portfolio" columns="portfolio">
        {/* Total sites and On-Air vs O&M Start, in one compact card. */}
        <SummaryMetricsTile label="Total sites, On-Air & O&M Start"
          definition={`Total sites: every site row in the Master workbook for the filter. On-Air sites: On-Air = "Yes". O&M Start sites: "O&M Start - ${month}" = "Yes". Percentages are of total sites. Difference = On-Air sites − O&M Start sites: On-Air sites not yet recorded as O&M Start (a blank or 0 flag means not recorded, not a confirmed failure). The 4G Saturation / LWE lines are the circle-wise counts summed per project (Difference per project = its On-Air − its O&M Start); they are shown only when they add up to the total.`}
          metrics={[
            { label: 'Total sites', value: total, tone: 'neutral', split: split(scopeBy, total), note: 'In the Master workbook' },
            { label: 'On-Air sites', value: onAirSites, tone: 'onAir', split: split(onAirBy, onAirSites), pct: total ? (100 * onAirSites) / total : null, note: `of ${formatNumber(total)} sites` },
            { label: 'O&M Start sites', value: omSites, tone: 'omStart', missing: 'No O&M Start column', split: split(omBy, omSites),
              pct: omSites != null && total ? (100 * omSites) / total : null, note: omSites == null ? undefined : `${month} status` },
            { label: 'Difference', value: omDifference, tone: 'gap', split: split(omDiffBy, omDifference), note: 'On-Air, not yet O&M Start' },
          ]}
          links={[{ to: detailLink('/', f, { scope: 'all' }), view: 'View all sites' }, { to: detailLink('/', f, { scope: 'om_start' }), view: 'View O&M Start sites' }]} />
        <ConversionActivityTile total={total} onAir={onAirSites} omStart={omSites} activity={activity.data}
          definition={`Achievement against total site scope (${formatNumber(total)} sites in the filter, Master workbook): On-Air = "Yes" and O&M Start - ${month} = "Yes"; the gap is total scope minus that count (blank or 0 = not marked yet). Monthly additions count sites by their Site On Air Date and O&M Start Date in the escalation matrix (Data/reference); a month with no dates in that file yet shows "—", not 0.`}
          link={detailLink('/', f, { scope: 'om_start' })} view="View O&M Start sites" />
      </KpiSection>

      {daily ? (
      <>
      <KpiSection label="Uptime buckets (MTD)">
        <KpiTile kpi={byId.gte_98_5} of={`of ${formatNumber(onAirSites)}`} compareOn={compareOn} vsLabel={vsLabel}
          sub={`${pctOf(summary.metrics.sites_at_or_above_98_5_mtd, onAirSites)} of On-Air sites`} />
        <KpiTile kpi={byId.lt_60} of={`of ${formatNumber(onAirSites)}`} compareOn={compareOn} vsLabel={vsLabel}
          sub={`${pctOf(summary.metrics.sites_below_60_mtd, onAirSites)} of On-Air sites`} />
        <CompositeTile label="Uptime bucket mix" icon={Layers3} tint="orange" value={breakdown.data ? bucketed : null} unit="On-Air sites with a value"
          definition="On-Air sites by their own MTD uptime, in the workbook's buckets (each lower bound included). Shares are of the sites with a value this month; sites that never reported are not placed in a bucket."
          sub={bucketed && onAirSites > bucketed ? `${formatNumber(onAirSites - bucketed)} On-Air sites have no value yet` : undefined}
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
        <div className="grid grid-cols-2 gap-3 xl:grid-cols-4" aria-busy="true" aria-label="Loading period figures">{Array.from({ length: 4 }, (_, i) => <Skeleton key={i} className="h-36" />)}</div>
      ) : (
      <>
      <KpiSection label={`Uptime buckets · ${shortLabel}`}>
        <KpiTile kpi={periodKpis.gte_98_5} of={`of ${formatNumber(periodData.onAir.sites_in_scope)}`} compareOn={Boolean(cmpData)} vsLabel={vsLabel}
          sub={`${pctOf(periodData.onAir.sites_at_or_above_98_5, periodData.onAir.sites_in_scope)} of On-Air sites`} />
        <KpiTile kpi={periodKpis.lt_60} of={`of ${formatNumber(periodData.onAir.sites_in_scope)}`} compareOn={Boolean(cmpData)} vsLabel={vsLabel}
          sub={`${pctOf(periodData.onAir.sites_below_60, periodData.onAir.sites_in_scope)} of On-Air sites`} />
        <CompositeTile label="Uptime bucket mix" icon={Layers3} tint="orange" value={periodBucketSegments ? periodBucketed : null} unit="On-Air sites with a value"
          definition={`On-Air sites by their own uptime over ${shortLabel}, in the workbook's buckets (each lower bound included). Sites without a value are not placed in a bucket.`}
          sub={periodBucketed && periodData.onAir.sites_in_scope > periodBucketed ? `${formatNumber(periodData.onAir.sites_in_scope - periodBucketed)} On-Air sites have no value in the period` : undefined}
          segments={periodBucketSegments} link={detailLink('/thresholds', { ...f, date: av.latest }, thresholdsPeriod ? { period: thresholdsPeriod } : {})} view="Open Threshold Analysis" />
      </KpiSection>
      </>
      )}

      {breakdownAll.data && breakdown.data && (!omAvailable || breakdownOm.data) ? (
        <CircleBreakdownTable
          {...circleBreakdown(breakdownAll.data, breakdown.data, omAvailable ? breakdownOm.data : null)}
          notes={tracking.portfolioNotes} omHeads={omHeads} omHeadSource={omHeadSheet.data?.source ?? null}
          onSaveNote={(key, note) => dispatch({ type: 'saveNote', key, note })}
          loading={breakdownAll.loading || breakdown.loading}
          periodNote={`Site counts come from the current On-Air and O&M Start flags in ${summary.source.workbook}; the reporting date does not change them.`} />
      ) : breakdownAll.error ?? breakdownOm.error ? (
        <Alert variant="destructive"><AlertTitle>Circle-wise breakdown unavailable</AlertTitle><AlertDescription>{(breakdownAll.error ?? breakdownOm.error)!.message}</AlertDescription></Alert>
      ) : <Skeleton className="h-80 w-full" aria-label="Loading circle-wise breakdown" />}

    </div>
  );
}
