import { Link, Navigate, useNavigate, useSearchParams } from 'react-router-dom';
import { AlertTriangle, ArrowRight, Database, FileUp, Layers3 } from 'lucide-react';
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert';
import { buttonVariants } from '@/components/ui/button';
import { Card } from '@/components/ui/card';
import { Skeleton } from '@/components/ui/skeleton';
import { CircleComparison } from '../components/dashboard/CircleComparison';
import { CircleSeriesPicker } from '../components/dashboard/CircleSeriesPicker';
import { FilterBar } from '../components/dashboard/FilterBar';
import { KpiCards } from '../components/dashboard/KpiCards';
import { OutageChart } from '../components/dashboard/OutageChart';
import { PeriodKpi } from '../components/dashboard/PeriodKpi';
import { TrendChart } from '../components/dashboard/TrendChart';
import { UPTIME_VIEWS, type UptimeChartView } from '../components/dashboard/constants';
import type { OutageChartView } from '../components/dashboard/OutageChart';
import { cn } from '@/lib/utils';
import { useWorkbook } from '../context/workbook';
import { useApiQuery } from '../hooks/useApiQuery';
import { selectDays, useDashboardFilters } from '../hooks/useDashboardFilters';
import { fetchBreakdowns, fetchFilterOptions, fetchMonthly, fetchPeriod, fetchSummary, fetchTrends } from '../services/api';
import { allCircleKeys, lowestCircles, parseSelection, selectedSeries } from '../lib/circleSeries';

/** Threshold Analysis › Uptime Buckets & Site Details (the bucket chart and site table moved there). */
const BUCKETS_PATH = '/thresholds/buckets';
/** Filters that also apply on the buckets page; the chart-only parameters stay behind. */
const SHARED_PARAMS = ['report_type', 'circle', 'scope', 'date'];
const bucketsLink = (current: URLSearchParams, extra: Record<string, string> = {}) => {
  const query = new URLSearchParams();
  SHARED_PARAMS.forEach((k) => { const v = current.get(k); if (v) query.set(k, v); });
  Object.entries(extra).forEach(([k, v]) => query.set(k, v));
  return query.size ? `${BUCKETS_PATH}?${query}` : BUCKETS_PATH;
};

export function DashboardPage() {
  const workbook = useWorkbook();
  const { version } = workbook;
  // Every key includes the workbook version, so a new upload refreshes all panels.
  const options = useApiQuery(workbook.active ? `${version}|filters` : null, fetchFilterOptions);
  const { filters, setFilters, reset, isDefault } = useDashboardFilters(options.data);
  const [searchParams, setSearchParams] = useSearchParams();
  const navigate = useNavigate();

  const snapshotKey = filters ? `${version}|${filters.snapshotParams}` : null;
  const trendKey = filters ? `${version}|${filters.trendParams}` : null;
  const summary = useApiQuery(snapshotKey, (signal) => fetchSummary(filters!.snapshotParams, signal));
  const breakdown = useApiQuery(snapshotKey, (signal) => fetchBreakdowns(filters!.snapshotParams, signal));
  const monthly = useApiQuery(filters ? `${version}|monthly|${filters.monthlyParams}` : null, (signal) => fetchMonthly(filters!.monthlyParams, signal));
  const trend = useApiQuery(trendKey, (signal) => fetchTrends(filters!.trendParams, signal));
  // The trend period card is shown on the 4G Saturation and LWE pages (a report type is selected), not the Overview.
  const showPeriod = Boolean(filters?.reportType);
  const period = useApiQuery(showPeriod ? `${version}|period|${filters!.periodParams}` : null, (signal) => fetchPeriod(filters!.periodParams, signal));

  // Bucket drill-downs (alerts, Site Portfolio, Threshold Analysis: /?bucket=lt_60…) now open the buckets page,
  // with every parameter kept, so existing links keep working.
  if (searchParams.get('bucket')) return <Navigate to={`${BUCKETS_PATH}?${searchParams}`} replace />;

  if (!workbook.loading && !workbook.error && !workbook.active) {
    return (
      <Card className="mx-auto mt-10 max-w-xl items-center gap-3 px-8 py-10 text-center">
        <FileUp className="size-8 text-muted-foreground" aria-hidden="true" />
        <h1 className="text-lg font-semibold">No Master workbook loaded</h1>
        <p className="text-sm text-muted-foreground">
          Upload the consolidated 4G Saturation &amp; LWE workbook to populate the dashboard. No sample data is shown until then.
        </p>
        <Link to="/workbook" className={buttonVariants({ size: 'sm' })}><FileUp /> Upload workbook</Link>
      </Card>
    );
  }

  const fatal = workbook.error ?? options.error;
  if (fatal) {
    return (
      <Alert variant="destructive" className="mx-auto mt-10 max-w-2xl">
        <Database />
        <AlertTitle>Reporting data is unavailable</AlertTitle>
        <AlertDescription>
          {fatal.message} The dashboard shows only data read from the Master workbook; no sample data is substituted.
        </AlertDescription>
      </Alert>
    );
  }

  if (!options.data || !filters) {
    return (
      <div className="space-y-4" aria-busy="true" aria-label="Loading dashboard">
        <Skeleton className="h-10 w-80" />
        <Skeleton className="h-20 w-full" />
        <div className="grid grid-cols-2 gap-3 xl:grid-cols-5">
          {Array.from({ length: 5 }, (_, i) => <Skeleton key={i} className="h-28" />)}
        </div>
        <p className="text-xs text-muted-foreground">Reading the Master workbook. The first load after a workbook change can take several seconds.</p>
      </div>
    );
  }

  // Picked dates apply to the outage chart too, so both charts show the same days.
  const pickedTrend = trend.data && filters.dayList.length
    ? { ...trend.data, series: selectDays(trend.data.series, filters.dayList) } : trend.data;
  const scopeLabel = options.data.scopes.find((s) => s.value === filters.scope)?.label ?? filters.scope;
  // Chart views live in the URL (?uptime_view=circles&series=…&outage_view=circles), so links keep them.
  const allKeys = allCircleKeys(options.data.circles);
  // The circles in the current data (only LWE circles on the LWE page), in a stable order (4G first).
  const rank = (key: string) => (allKeys.includes(key) ? allKeys.indexOf(key) : allKeys.length + (key.startsWith('4G') ? 0 : 1));
  const availableCircles = [...(trend.data?.circles ?? monthly.data?.circles ?? [])]
    .sort((a, b) => rank(a.key) - rank(b.key) || a.key.localeCompare(b.key));
  const uptimeView: UptimeChartView = (['circles', 'heatmap'] as string[]).includes(searchParams.get('uptime_view') ?? '')
    ? searchParams.get('uptime_view') as UptimeChartView : 'overall';
  const outageView: OutageChartView = searchParams.get('outage_view') === 'circles' ? 'circles' : 'overall';
  // By circle starts with the four circles with the lowest MTD uptime; never all circles.
  const order = availableCircles.map((c) => c.key);
  const selectedKeys = parseSelection(searchParams.get('series'), order, lowestCircles(breakdown.data?.circles ?? []))
    .sort((a, b) => order.indexOf(a) - order.indexOf(b));  // drawn in the same order as everywhere else (4G first)
  const circles = selectedSeries(availableCircles, selectedKeys, allKeys);
  const setParams = (changes: Record<string, string | null>) => setSearchParams((current) => {
    const next = new URLSearchParams(current);
    Object.entries(changes).forEach(([k, v]) => (v ? next.set(k, v) : next.delete(k)));
    return next;
  }, { replace: true });
  const setSeries = (keys: string[]) => setParams({ series: keys.length ? keys.join(',') : 'none' });
  const uptimeControls = (
    <div className="mb-2 flex flex-wrap items-center gap-2">
      <div className="inline-flex rounded-lg border p-0.5" role="group" aria-label="Uptime chart">
        {UPTIME_VIEWS.map((v) => (
          <button key={v.value} type="button" aria-pressed={uptimeView === v.value}
            onClick={() => setParams({ uptime_view: v.value === 'overall' ? null : v.value })}
            className={cn('rounded-md px-2.5 py-1 text-xs font-medium transition-colors focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none',
              uptimeView === v.value ? 'bg-primary text-primary-foreground' : 'text-muted-foreground hover:text-foreground')}>
            {v.label}
          </button>
        ))}
      </div>
      {uptimeView === 'circles' && availableCircles.length > 0 && (
        <CircleSeriesPicker available={availableCircles} selected={selectedKeys} allKeys={allKeys} onChange={setSeries} />
      )}
      {uptimeView === 'circles' && !selectedKeys.length && <span className="text-xs text-muted-foreground">Choose up to four circles to draw.</span>}
    </div>
  );

  return (
    <div className="space-y-4">
      <FilterBar options={options.data} filters={filters} onChange={setFilters} onReset={reset} canReset={!isDefault}
        title="Network uptime overview"
        description={<>{options.data.month.label} reporting month · {filterSummary(filters.reportType, filters.circle, scopeLabel)}</>} />

      {summary.error ? (
        <Alert variant="destructive"><AlertTriangle /><AlertTitle>Key indicators unavailable</AlertTitle><AlertDescription>{summary.error.message}</AlertDescription></Alert>
      ) : (
        <KpiCards summary={summary.data} loading={summary.loading} onShowBelow60={() => navigate(bucketsLink(searchParams, { bucket: 'lt_60' }))} />
      )}

      {showPeriod && <PeriodKpi period={period.data} loading={period.loading} error={period.error} />}

      <TrendChart
        trend={trend.data} loading={trend.loading} error={trend.error}
        monthly={monthly.data} monthlyLoading={monthly.loading} monthlyError={monthly.error}
        scopeLabel={scopeLabel} monthLabel={options.data.month.label}
        view={filters.trendView} onViewChange={(view) => setFilters({ trend: view === 'daily' ? '' : view })}
        dayList={filters.dayList} weekList={filters.weekList} monthsFiltered={filters.monthList.length > 0}
        chartView={uptimeView} circles={uptimeView === 'circles' ? circles : null} controls={uptimeControls}
        allCircles={availableCircles} onSelectCircle={(key) => setParams({ uptime_view: 'circles', series: key })}
      />

      <div className="grid grid-cols-1 items-start gap-4 xl:grid-cols-2">
        <OutageChart
          trend={pickedTrend} loading={trend.loading} error={trend.error}
          monthly={monthly.data} monthlyLoading={monthly.loading} monthlyError={monthly.error}
          view={filters.trendView} onViewChange={(view) => setFilters({ trend: view === 'daily' ? '' : view })}
          weekList={filters.weekList} picked={filters.dayList.length > 0} scopeLabel={scopeLabel}
          outageView={outageView} onOutageViewChange={(v) => setParams({ outage_view: v === 'overall' ? null : v })}
        />
        <CircleComparison breakdown={breakdown.data} loading={breakdown.loading} error={breakdown.error} />
      </div>

      <Link to={bucketsLink(searchParams)}
        className="flex items-center gap-3 rounded-xl border bg-card px-4 py-3 text-sm shadow-xs transition-colors hover:bg-muted/50 focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none">
        <Layers3 className="size-4 shrink-0 text-muted-foreground" aria-hidden="true" />
        <span className="flex-1"><span className="font-medium">Uptime buckets &amp; site details</span>
          <span className="text-muted-foreground"> · bucket chart by circle and the site-level table, for the same filters (Threshold Analysis)</span></span>
        <ArrowRight className="size-4 shrink-0 text-muted-foreground" aria-hidden="true" />
      </Link>
    </div>
  );
}

function filterSummary(reportType: string, circle: string, scopeLabel: string) {
  return [reportType || 'All projects', circle ? `Circle ${circle}` : 'All circles', scopeLabel].join(' · ');
}
