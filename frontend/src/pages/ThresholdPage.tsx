import { useMemo, useState } from 'react';
import { Link, useSearchParams } from 'react-router-dom';
import {
  AlertOctagon, ArrowDown, ArrowDownRight, ArrowLeft, ArrowUp, ArrowUpDown, ArrowUpRight, Database, ExternalLink,
  FileUp, Gauge, Minus,
} from 'lucide-react';
import {
  Bar, BarChart, CartesianGrid, Cell, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis,
} from 'recharts';
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert';
import { Button, buttonVariants } from '@/components/ui/button';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Skeleton } from '@/components/ui/skeleton';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table';
import { cn } from '@/lib/utils';
import { Field, SelectField } from '../components/data/DataEntry';
import { ChartCard } from '../components/dashboard/ChartCard';
import { AXIS_TICK, BUCKET_COLORS, BUCKET_ORDER } from '../components/dashboard/constants';
import { DataTable } from '../components/dashboard/DataTable';
import { FilterBar } from '../components/dashboard/FilterBar';
import { SiteDetailSheet } from '../components/dashboard/SiteDetailSheet';
import { SiteTable } from '../components/dashboard/SiteTable';
import { UnifiedThresholdTable } from '../components/dashboard/ThresholdMonthlyTable';
import { PeriodStatusBadge } from '../components/reporting/ReportingStatus';
import { useWorkbook } from '../context/workbook';
import { useApiQuery } from '../hooks/useApiQuery';
import { useFilterOptions } from '../hooks/useFilterOptions';
import { useDashboardFilters, type ResolvedFilters } from '../hooks/useDashboardFilters';
import { formatDate, formatNumber, formatPct, formatShortDate } from '../lib/format';
import { fetchThresholds } from '../services/api';
import type { BucketId, SiteRecord, ThresholdBucket, ThresholdPeriod, ThresholdResponse, ThresholdRow, ThresholdValue } from '../types';
import { populationSites } from '../lib/population';

type Mode = 'count' | 'pct';
type ThresholdId = BucketId;

/** Headings per bucket. Only the <60% bucket is presented as critical. */
const BUCKET_COPY: Record<BucketId, { title: string; subtitle: string }> = {
  lt_60: { title: 'Critical low uptime: below 60%', subtitle: 'Sites needing immediate attention' },
  '60_90': { title: 'Uptime 60% to below 90%', subtitle: 'Sites below 90% but at or above 60%' },
  '90_97': { title: 'Uptime 90% to below 97%', subtitle: 'Sites below 97% but at or above 90%' },
  '97_98_5': { title: 'Uptime 97% to below 98.5%', subtitle: 'Sites just short of the 98.5% mark' },
  gte_98_5: { title: 'High availability: 98.5% and above', subtitle: 'Sites meeting the 98.5% uptime mark' },
};
/** Whether more sites in the bucket is good (true), bad (false) or neither (null). */
const RISE_IS_GOOD: Record<BucketId, boolean | null> = { lt_60: false, '60_90': null, '90_97': null, '97_98_5': null, gte_98_5: true };
const RECENT_MONTHS = 3;

const shortType = (type: string | null) => (type === '4G Saturation' ? '4G' : type ?? '');
const rowLabel = (row: ThresholdRow) => (row.circle ? `${row.circle} · ${shortType(row.report_type)}` : 'Grand Total');
/** The exact rule, from the workbook's Bucket formula: lower bound inclusive, upper bound exclusive. */
const definition = (b: ThresholdBucket) => (b.lower == null ? `uptime < ${b.upper}%`
  : b.upper == null ? `uptime ≥ ${b.lower}%` : `${b.lower}% ≤ uptime < ${b.upper}%`);

/** Count or percentage of a bucket in one period; null when nothing was reported. */
const pick = (value: ThresholdValue | undefined, id: ThresholdId, mode: Mode) =>
  (value ? value[id][mode === 'count' ? 'count' : 'pct'] : null);
const show = (v: number | null, mode: Mode) => (v == null ? '—' : mode === 'count' ? formatNumber(v) : formatPct(v, 1));

/** Site Explorer (Overview site table) with the circle, date and bucket applied. */
function siteExplorerLink(filters: ResolvedFilters, row: ThresholdRow, threshold: ThresholdId, date: string, basis: 'mtd' | 'daily') {
  const query = new URLSearchParams({ scope: filters.scope, date, bucket: threshold });
  const reportType = row.report_type ?? filters.reportType;
  const circle = row.circle ?? filters.circle;
  if (reportType) query.set('report_type', reportType);
  if (circle) query.set('circle', circle);
  if (basis === 'daily') query.set('bucket_basis', 'daily');
  return `/?${query}`;
}

const range = (p: ThresholdPeriod) => `${formatShortDate(p.start)}–${formatShortDate(p.end)}`;

/** Short name of a period, as used in headings: "MTD to 02 Oct", "Sep-26", "Wk-1 (01–07 Oct)", "02 Oct". */
function periodLabel(p: ThresholdPeriod, reportingDate: string) {
  if (p.kind === 'mtd') return `MTD to ${formatShortDate(reportingDate)}`;
  if (p.kind === 'week') return `${p.label} (${range(p)})`;
  if (p.kind === 'day') return formatShortDate(p.start);
  return p.label;
}

/** Picker entry: the period with its dates and how many days it covers. */
function periodOption(p: ThresholdPeriod, reportingDate: string) {
  if (p.kind === 'mtd') return `MTD · ${formatShortDate(p.start)}–${formatShortDate(reportingDate)} (${p.days_reported} days)`;
  if (p.kind === 'month') return `Month · ${p.label} (${p.days_reported} days)`;
  if (p.kind === 'week') return `Week · ${p.label} (${range(p)}, ${p.days_reported} day${p.days_reported === 1 ? '' : 's'}${p.partial ? ' so far' : ''})`;
  return `Date · ${formatDate(p.start)}`;
}

export function ThresholdPage() {
  const workbook = useWorkbook();
  const { version } = workbook;
  const options = useFilterOptions();
  // The population is the global selection (On-Air / O&M Start); this page has no default of its own.
  const { filters, setFilters, reset, isDefault } = useDashboardFilters(options.data);
  const [searchParams, setSearchParams] = useSearchParams();
  const mode: Mode = searchParams.get('show') === 'pct' ? 'pct' : 'count';
  const periodParam = searchParams.get('period');
  const vsParam = searchParams.get('vs');
  const selected = (BUCKET_ORDER as string[]).includes(searchParams.get('view') ?? '') ? (searchParams.get('view') as BucketId) : null;
  // Page-only settings (not the global filters): selecting a bucket never changes the filters.
  const setParam = (name: string, value: string | null) => setSearchParams((current) => {
    const params = new URLSearchParams(current);
    if (value) params.set(name, value);
    else params.delete(name);
    return params;
  }, { replace: name !== 'view' });

  // The backend resolves the period and its comparison (and computes every change) from these parameters.
  const thresholdParams = filters ? new URLSearchParams(filters.snapshotParams) : null;
  if (thresholdParams && periodParam) thresholdParams.set('period', periodParam);
  if (thresholdParams && vsParam) thresholdParams.set('vs', vsParam);
  const key = thresholdParams ? `${version}|thresholds|${thresholdParams}` : null;
  const result = useApiQuery(key, (signal) => fetchThresholds(thresholdParams!, signal));

  if (!workbook.loading && !workbook.error && !workbook.active) {
    return (
      <Card className="mx-auto mt-10 max-w-xl items-center gap-3 px-8 py-10 text-center">
        <FileUp className="size-8 text-muted-foreground" aria-hidden="true" />
        <h1 className="text-lg font-semibold">No reporting data loaded</h1>
        <p className="text-sm text-muted-foreground">Import the reporting data (Data Source page) to see threshold analysis.</p>
        <Link to="/workbook" className={buttonVariants({ size: 'sm' })}><FileUp /> Import data</Link>
      </Card>
    );
  }
  const fatal = workbook.error ?? options.error;
  if (fatal) {
    return (
      <Alert variant="destructive" className="mx-auto mt-10 max-w-2xl">
        <Database />
        <AlertTitle>Reporting data is unavailable</AlertTitle>
        <AlertDescription>{fatal.message}</AlertDescription>
      </Alert>
    );
  }
  if (!options.data || !filters) return <Skeleton className="h-96 w-full" aria-label="Loading threshold analysis" />;

  const scopeLabel = populationSites(filters.scope);
  const data = result.data;
  // The selectable periods, the selected one and its comparison, as resolved by the backend.
  const byKey = new Map((data?.periods ?? []).map((p) => [p.key, p]));
  const choices = (data?.selection.choices ?? []).map((k) => byKey.get(k)!).filter(Boolean);
  const period = data?.selection.period ? byKey.get(data.selection.period) ?? null : null;
  const vsKey = data?.selection.compare ?? null;
  const vsPeriod = choices.find((p) => p.key === vsKey) ?? null;
  const comparison: Comparison | null = data && vsPeriod ? { label: periodLabel(vsPeriod, data.reporting_date), key: vsPeriod.key, period: vsPeriod } : null;
  const currentLabel = data && period ? periodLabel(period, data.reporting_date) : '';
  const setPeriod = (key: string) => setSearchParams((current) => {
    const params = new URLSearchParams(current);
    if (key === 'mtd') params.delete('period');
    else params.set('period', key);
    params.delete('vs');  // a new period gets its natural comparison
    return params;
  }, { replace: true });

  return (
    <div className="space-y-3">
      <FilterBar options={options.data} filters={filters} onChange={setFilters} onReset={reset} canReset={!isDefault} showTrendRange={false}
        title="Threshold analysis"
        description={<>
          {options.data.month.label} · {[filters.reportType || 'All projects', filters.circle ? `Circle ${filters.circle}` : 'All circles', `Population: ${scopeLabel}`].join(' · ')}
          {' '}· all five uptime buckets; select one for its detailed analysis
        </>}
        actions={<Switch value={mode} onChange={(m) => setParam('show', m === 'pct' ? 'pct' : null)} label="Show values as"
          options={[['count', 'Site count'], ['pct', 'Percentage']]} />}
        extra={(
          <>
            <Field plain id="threshold-period" label="Period" className="w-48 gap-1 [&>label]:text-[11px] [&>label]:text-muted-foreground">
              <SelectField id="threshold-period" value={period?.key ?? ''} placeholder="Period" disabled={!data} onChange={setPeriod}
                options={choices.map((p) => ({ value: p.key, label: periodOption(p, data!.reporting_date) }))} />
            </Field>
            <Field plain id="threshold-compare" label="Compare with" className="w-48 gap-1 [&>label]:text-[11px] [&>label]:text-muted-foreground">
              <SelectField id="threshold-compare" value={vsKey ?? 'none'} placeholder="Compare with" disabled={!data}
                onChange={(v) => setParam('vs', v)}
                options={[{ value: 'none', label: 'No comparison' },
                  ...choices.filter((p) => p.key !== period?.key).map((p) => ({ value: p.key, label: periodOption(p, data!.reporting_date) }))]} />
            </Field>
          </>
        )} />

      {result.error ? (
        <Alert variant="destructive"><Database /><AlertTitle>Threshold analysis unavailable</AlertTitle><AlertDescription>{result.error.message}</AlertDescription></Alert>
      ) : !data ? (
        <div className="space-y-3" aria-busy="true">
          <Skeleton className="h-28 w-full" />
          <Skeleton className="h-72 w-full" />
        </div>
      ) : !period ? (
        <Alert><Database /><AlertTitle>No reported data</AlertTitle><AlertDescription>No period has reported uptime for these filters.</AlertDescription></Alert>
      ) : selected ? (
        <BucketDetail
          bucket={data.buckets.find((b) => b.id === selected)!} data={data} mode={mode} filters={filters} loading={result.loading}
          period={period} currentLabel={currentLabel} comparison={comparison} version={version}
          onBack={() => setParam('view', null)} />
      ) : (
        <>
          <PenaltyExposure data={data} period={period} currentLabel={currentLabel} scopeLabel={scopeLabel} onSelect={(id) => setParam('view', id)} />
          {/* One table: full months, matching-days MTD comparison and the Analyse action per bucket. */}
          <UnifiedThresholdTable data={data} mode={mode} scopeLabel={scopeLabel} onAnalyse={(id) => setParam('view', id)} />
        </>
      )}
    </div>
  );
}

interface Comparison {
  label: string;
  /** Period key in the response. */
  key: string;
  period: ThresholdPeriod;
}

function ChangeCell({ value, unit, good }: { value: number | null; unit: 'sites' | 'pct'; good: boolean | null }) {
  if (value == null) return <span className="text-muted-foreground">—</span>;
  const Icon = value > 0 ? ArrowUpRight : value < 0 ? ArrowDownRight : Minus;
  const better = good == null || value === 0 ? null : (value > 0) === good;
  return (
    <span className={cn('inline-flex items-center justify-end gap-0.5 tabular-nums', better === true && 'text-emerald-700', better === false && 'text-destructive')}>
      <Icon className="size-3.5" aria-hidden="true" />
      {value > 0 ? '+' : ''}{unit === 'pct' ? `${value.toFixed(2)} pts` : formatNumber(value)}
    </span>
  );
}

/** Selected-period threshold summary, followed by the four below-threshold buckets. */
function PenaltyExposure({ data, period, currentLabel, scopeLabel, onSelect }: {
  data: ThresholdResponse; period: ThresholdPeriod; currentLabel: string; scopeLabel: string; onSelect: (id: BucketId) => void;
}) {
  const now = data.total.values[period.key];
  const population = data.total.sites_in_scope;
  const meetingCount = now?.gte_98_5.count ?? null;
  const belowCount = now?.below_98_5.count ?? null;
  const classified = meetingCount == null || belowCount == null ? null : meetingCount + belowCount;
  const unclassified = classified == null ? null : population - classified;
  const noValue = now?.no_value.count ?? null;
  const reportedUnclassified = now && classified != null ? Math.max(0, now.sites_reported - classified) : null;
  const percent = (count: number | null) => count == null || population <= 0 ? null : (count / population) * 100;
  const meetingPct = percent(meetingCount);
  const belowPct = percent(belowCount);
  const distributionFitsScope = classified != null && population > 0 && classified <= population;
  const distributionLabel = distributionFitsScope && meetingCount != null && belowCount != null
    ? `Threshold distribution: ${formatNumber(meetingCount)} meeting and ${formatNumber(belowCount)} below out of ${formatNumber(population)} sites in scope`
    : `Threshold distribution unavailable${classified != null && classified > population ? ': classified counts exceed the site scope' : `: no complete data for ${currentLabel}`}`;
  const completenessLabel = now == null ? `No threshold data for ${currentLabel}`
    : classified != null && classified > population ? 'Classified counts exceed the site scope'
      : unclassified != null && unclassified > 0
        ? `${formatNumber(unclassified)} unclassified${noValue ? ` · ${formatNumber(noValue)} no value` : ''}${reportedUnclassified ? ` · ${formatNumber(reportedUnclassified)} reported but not bucketed` : ''}`
        : 'All sites classified';
  const buckets = data.buckets.filter((b) => data.penalty.buckets.includes(b.id));
  return (
    <section aria-label="Uptime threshold summary" className="grid gap-3 lg:grid-cols-[minmax(0,1.15fr)_minmax(0,2fr)]">
      <Card className="gap-2 rounded-xl border-l-4 border-l-emerald-600 px-4 py-2.5 shadow-xs" role="group" aria-label="Uptime Threshold Summary">
        <div className="flex items-center justify-between gap-2">
          <p className="text-xs font-semibold text-foreground/80">Uptime Threshold Summary</p>
          <p className="truncate text-[10px] text-muted-foreground" title={currentLabel}>{currentLabel}</p>
        </div>
        <div className="grid grid-cols-2 gap-3">
          <div className="min-w-0">
            <p className="truncate text-[11px] font-medium text-emerald-700">Meeting Threshold — ≥{data.penalty.threshold}%</p>
            <p className="mt-0.5 flex items-baseline gap-2">
              <span className="text-xl leading-none font-semibold tracking-tight text-emerald-700 tabular-nums">{meetingCount == null ? '—' : formatNumber(meetingCount)}</span>
              <span className="text-xs font-semibold text-emerald-700 tabular-nums">{formatPct(meetingPct, 1)}</span>
            </p>
          </div>
          <div className="min-w-0 border-l pl-3">
            <p className="truncate text-[11px] font-medium text-red-700">Below Threshold — &lt;{data.penalty.threshold}%</p>
            <p className="mt-0.5 flex items-baseline gap-2">
              <span className="text-xl leading-none font-semibold tracking-tight text-red-700 tabular-nums">{belowCount == null ? '—' : formatNumber(belowCount)}</span>
              <span className="text-xs font-semibold text-red-700 tabular-nums">{formatPct(belowPct, 1)}</span>
            </p>
          </div>
        </div>
        <div className="flex h-1.5 w-full overflow-hidden rounded-full bg-muted" role="img" aria-label={distributionLabel}>
          {distributionFitsScope && meetingCount != null && belowCount != null && (
            <>
              {meetingCount > 0 && <div className="h-full bg-emerald-600" style={{ width: `${meetingPct}%` }} />}
              {belowCount > 0 && <div className="h-full bg-red-600" style={{ width: `${belowPct}%` }} />}
            </>
          )}
        </div>
        <div className="flex items-center justify-between gap-2 text-[10px] leading-tight text-muted-foreground">
          <span className="truncate" title={`${formatNumber(population)} ${scopeLabel}`}>{formatNumber(population)} {scopeLabel}</span>
          <span className="text-right">{completenessLabel}</span>
        </div>
      </Card>
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-4" role="group" aria-label="Below 98.5% by bucket">
        {buckets.map((b) => {
          const n = now ? now[b.id].count : null;
          const share = now ? now[b.id].pct : null;
          const critical = b.id === 'lt_60';
          return (
            <button key={b.id} type="button" onClick={() => onSelect(b.id)} aria-label={`${b.label}: ${n == null ? 'no data' : formatNumber(n)} sites, open analysis`}
              className={cn('rounded-xl border bg-card px-3 py-2.5 text-left shadow-xs transition-shadow hover:shadow-md focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none',
                critical && 'border-red-300 bg-red-50/60')}>
              <span className="flex items-center gap-1.5 text-xs font-medium text-muted-foreground">
                <span className="size-2.5 shrink-0 rounded-full" style={{ background: BUCKET_COLORS[b.id] }} aria-hidden="true" />{b.label}
              </span>
              <span className={cn('mt-1 block text-2xl leading-none font-semibold tabular-nums', critical ? 'text-red-600' : 'text-foreground')}>{n == null ? '—' : formatNumber(n)}</span>
              <span className="mt-1 block text-xs text-muted-foreground tabular-nums">{formatPct(share, 1)} of sites</span>
            </button>
          );
        })}
      </div>
    </section>
  );
}

/** One reusable analysis for whichever bucket is selected. */
function BucketDetail({ bucket, data, mode, filters, loading, period, currentLabel, comparison, version, onBack }: {
  bucket: ThresholdBucket; data: ThresholdResponse; mode: Mode; filters: ResolvedFilters; loading: boolean; period: ThresholdPeriod;
  currentLabel: string; comparison: Comparison | null; version: string; onBack: () => void;
}) {
  const currentKey = period.key;
  // The site list buckets by the uptime on a date or month to date; for a week or month it lists the MTD bucket.
  const siteBasis = period.kind === 'day' ? 'daily' : 'mtd';
  const siteDate = period.kind === 'day' ? period.start : data.reporting_date;
  const siteNote = period.kind === 'week' || period.kind === 'month' ? ' (by MTD uptime: site lists for a week or month are not available)' : '';
  const [circle, setCircle] = useState('');
  const [site, setSite] = useState<SiteRecord | null>(null);
  const id = bucket.id;
  const critical = id === 'lt_60';
  const copy = BUCKET_COPY[id];
  const Icon = critical ? AlertOctagon : Gauge;
  const now = data.total.values[currentKey];
  const before = comparison ? data.total.values[comparison.key] : null;
  const count = now ? now[id].count : null;
  const pct = now ? now[id].pct : null;
  const prevCount = before ? before[id].count : null;
  const prevPct = before ? before[id].pct : null;
  const change = data.total.comparison?.[id] ?? null;
  // Affected sites: the global filters, plus a circle picked here (local; global filters are unchanged).
  const siteParams = useMemo(() => {
    const p = new URLSearchParams(filters.snapshotParams);
    p.set('reporting_date', siteDate);
    if (circle) {
      const [reportType, code] = circle.split('|');
      p.set('report_type', reportType);
      p.set('circle', code);
    }
    return p;
  }, [filters.snapshotParams, circle, siteDate]);
  const explorerRow = circle ? data.rows.find((r) => `${r.report_type}|${r.circle}` === circle) ?? data.total : data.total;
  const activeFilters = [filters.reportType || 'All projects', filters.circle ? `Circle ${filters.circle}` : 'All circles', `Population: ${populationSites(filters.scope)}`];

  return (
    <section aria-labelledby={`section-${id}`} className={cn('space-y-3 rounded-xl border-l-4 pl-4', critical ? 'border-l-destructive' : 'border-l-slate-300')}
      style={critical ? undefined : { borderLeftColor: BUCKET_COLORS[id] }}>
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div>
          <Button variant="ghost" size="sm" className="-ml-2 mb-1" onClick={onBack}><ArrowLeft /> All buckets</Button>
          <h2 id={`section-${id}`} className={cn('flex items-center gap-2 text-base font-semibold', critical && 'text-destructive')}>
            <Icon className="size-4" aria-hidden="true" /> {copy.title}
          </h2>
          <p className="text-xs text-muted-foreground">
            {copy.subtitle} · rule: {definition(bucket)} (workbook label "{bucket.workbook_label}") · {currentLabel} · {activeFilters.join(' · ')}
          </p>
        </div>
        <Link to={siteExplorerLink(filters, explorerRow, id, siteDate, siteBasis)}
          className={buttonVariants({ size: 'sm', variant: critical ? 'destructive' : 'outline' })}>
          Open in Site Explorer <ExternalLink />
        </Link>
      </div>

      <div className="grid grid-cols-2 gap-3 xl:grid-cols-4" role="region" aria-label="Bucket summary">
        <SummaryCard label={`Sites · ${currentLabel}`} value={count == null ? 'No data' : formatNumber(count)} tone={critical && count ? 'critical' : undefined}
          detail={pct == null ? 'Not reported' : `${formatPct(pct, 2)} of sites in scope`} />
        <SummaryCard label={comparison ? `Sites · ${comparison.label}` : 'Comparison period'} value={prevCount == null ? '—' : formatNumber(prevCount)}
          detail={prevPct == null ? 'Not available' : `${formatPct(prevPct, 2)} of sites in scope`} />
        <SummaryCard label="Change in sites" value={<ChangeCell value={change?.change ?? null} unit="sites" good={RISE_IS_GOOD[id]} />}
          detail={change?.change_pct != null ? `${change.change_pct > 0 ? '+' : ''}${change.change_pct}% change` : 'Absolute change'} />
        <SummaryCard label="Change in share" value={<ChangeCell value={change?.change_pts ?? null} unit="pct" good={RISE_IS_GOOD[id]} />}
          detail="Percentage points of sites in scope" />
      </div>

      <ThresholdKpis data={data} id={id} mode={mode} />
      <div className="grid grid-cols-1 items-start gap-3 xl:grid-cols-2">
        <ThresholdTrend data={data} id={id} mode={mode} color={BUCKET_COLORS[id]} loading={loading} />
        <CircleChart data={data} id={id} mode={mode} color={BUCKET_COLORS[id]} loading={loading} period={period} label={currentLabel} />
      </div>
      <CircleChanges data={data} id={id} currentKey={currentKey} currentLabel={currentLabel} comparison={comparison} selected={circle} onSelect={setCircle} critical={critical} />
      <ThresholdTable data={data} id={id} mode={mode} filters={filters} critical={critical} title={copy.title} />

      <div id="affected-sites" className="scroll-mt-20">
        <SiteTable
          params={siteParams} version={version} bucket={id} bucketBasis={siteBasis}
          onBucketChange={(next) => { if (!next) onBack(); }} onSelectSite={setSite}
          title={`${critical ? 'Critical sites' : 'Sites'} in ${bucket.label}${circle ? ` · ${circle.split('|')[1]} ${shortType(circle.split('|')[0])}` : ''}${siteNote}`} />
      </div>
      <SiteDetailSheet site={site} onClose={() => setSite(null)} />
    </section>
  );
}

function SummaryCard({ label, value, detail, tone }: { label: string; value: React.ReactNode; detail: string; tone?: 'critical' }) {
  return (
    <Card className="gap-0 px-3.5 py-2.5">
      <p className="truncate text-xs font-medium text-muted-foreground" title={label}>{label}</p>
      <p className={cn('mt-1 text-2xl leading-7 font-semibold tabular-nums', tone === 'critical' && 'text-destructive')}>{value}</p>
      <p className="mt-0.5 text-xs text-muted-foreground">{detail}</p>
    </Card>
  );
}

/** Each circle's sites in the bucket, its share, the change and its rank within its network. */
function CircleChanges({ data, id, currentKey, currentLabel, comparison, selected, onSelect, critical }: {
  data: ThresholdResponse; id: ThresholdId; currentKey: string; currentLabel: string; comparison: Comparison | null; selected: string;
  onSelect: (key: string) => void; critical: boolean;
}) {
  // Counts, shares and changes per circle are the backend's (the change is between the periods it resolved).
  const rows = data.rows.map((r) => {
    const now = r.values[currentKey];
    const change = comparison ? r.comparison?.[id] ?? null : null;
    return {
      key: `${r.report_type}|${r.circle}`, row: r, count: now ? now[id].count : null, pct: now ? now[id].pct : null,
      dCount: change?.change ?? null, dPct: change?.change_pts ?? null,
    };
  });
  // Rank by share of sites within each network only (4G and LWE are separate networks).
  const rank = new Map<string, number>();
  ['4G Saturation', 'LWE'].forEach((t) => rows.filter((r) => r.row.report_type === t && r.pct != null)
    .sort((a, b) => (b.pct ?? 0) - (a.pct ?? 0)).forEach((r, i) => rank.set(r.key, i + 1)));
  return (
    <Card role="region" aria-label="Circle comparison for the bucket">
      <CardHeader>
        <CardTitle className="text-sm font-semibold">By circle</CardTitle>
        <CardDescription className="text-xs">
          {currentLabel}{comparison ? `, change against ${comparison.label}` : ''}. Share is of each circle's sites in scope; rank is by
          share within the circle's network. Select a circle to list its sites below.
        </CardDescription>
      </CardHeader>
      <CardContent className="px-0">
        <div className="max-h-80 overflow-auto">
          <Table className="text-xs">
            <TableHeader className="sticky top-0 bg-card">
              <TableRow className="bg-muted/50 hover:bg-muted/50">
                <TableHead className="pl-4">Circle</TableHead>
                <TableHead className="text-right">Sites in scope</TableHead>
                <TableHead className="text-right">In bucket</TableHead>
                <TableHead className="text-right">Share</TableHead>
                <TableHead className="text-right">Change</TableHead>
                <TableHead className="text-right">Change (pts)</TableHead>
                <TableHead className="pr-4 text-right">Rank</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {rows.map((r) => (
                <TableRow key={r.key} className={cn('cursor-pointer', selected === r.key && 'bg-primary/5')} tabIndex={0}
                  aria-selected={selected === r.key} aria-label={`${rowLabel(r.row)}: list its sites`}
                  onClick={() => onSelect(selected === r.key ? '' : r.key)}
                  onKeyDown={(e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); onSelect(selected === r.key ? '' : r.key); } }}>
                  <TableCell className="pl-4 font-medium">{rowLabel(r.row)}</TableCell>
                  <TableCell className="text-right tabular-nums">{formatNumber(r.row.sites_in_scope)}</TableCell>
                  <TableCell className={cn('text-right tabular-nums', critical && r.count && 'font-semibold text-destructive')}>{r.count == null ? '—' : formatNumber(r.count)}</TableCell>
                  <TableCell className="text-right tabular-nums">{r.pct == null ? '—' : formatPct(r.pct, 2)}</TableCell>
                  <TableCell className="text-right"><ChangeCell value={r.dCount} unit="sites" good={RISE_IS_GOOD[id]} /></TableCell>
                  <TableCell className="text-right"><ChangeCell value={r.dPct} unit="pct" good={RISE_IS_GOOD[id]} /></TableCell>
                  <TableCell className="pr-4 text-right tabular-nums">{rank.get(r.key) ?? '—'}</TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </div>
      </CardContent>
    </Card>
  );
}

function ThresholdKpis({ data, id, mode }: { data: ThresholdResponse; id: ThresholdId; mode: Mode }) {
  const periods = data.periods;
  const days = periods.filter((p) => p.kind === 'day');
  const day = days.at(-1);
  const previousDay = days.at(-2);
  const week = [...periods].reverse().find((p) => p.kind === 'week' && data.total.values[p.key]);
  const months = periods.filter((p) => p.kind === 'month' && data.total.values[p.key]);
  const month = months.at(-1);
  const mtd = periods.find((p) => p.kind === 'mtd');
  const cards: { label: string; period?: ThresholdPeriod; previous?: ThresholdPeriod; previousLabel?: string }[] = [
    { label: day ? `On ${formatDate(day.start)}` : 'Selected date', period: day, previous: previousDay, previousLabel: 'previous day' },
    { label: mtd ? `${mtd.label} (${mtd.days_reported} days)` : 'Month to date', period: mtd },
    { label: week ? `${week.label} (${formatShortDate(week.start)}–${formatShortDate(week.end)})${week.partial ? ', so far' : ''}` : 'Week', period: week },
    { label: month ? `${month.label} (full month)` : 'Last full month', period: month, previous: months.at(-2), previousLabel: 'previous month' },
  ];
  return (
    <div className="grid grid-cols-2 gap-3 xl:grid-cols-4">
      {cards.map((card) => {
        const value = card.period ? data.total.values[card.period.key] : null;
        const other: Mode = mode === 'count' ? 'pct' : 'count';
        const current = pick(value, id, mode);
        const before = card.previous ? pick(data.total.values[card.previous.key], id, mode) : null;
        const delta = current != null && before != null ? current - before : null;
        return (
          <Card key={card.label} className="gap-0 px-3.5 py-2.5">
            <div className="flex items-center gap-1.5">
              <p className="truncate text-xs font-medium text-muted-foreground" title={card.label}>{card.label}</p>
              {card.period?.kind !== 'day' && <PeriodStatusBadge status={card.period?.status} missing={card.period?.missing} />}
            </div>
            <p className="mt-1 text-2xl leading-7 font-semibold tabular-nums">{value ? show(current, mode) : 'No data'}</p>
            <p className="mt-0.5 text-xs text-muted-foreground">
              {value ? `${show(pick(value, id, other), other)} ${other === 'pct' ? 'of sites' : 'sites'}` : 'Not reported for this period'}
              {delta != null && ` · ${delta > 0 ? '+' : ''}${mode === 'count' ? formatNumber(delta) : `${delta.toFixed(1)} pts`} vs ${card.previousLabel}`}
            </p>
          </Card>
        );
      })}
    </div>
  );
}

function ThresholdTrend({ data, id, mode, color, loading }: { data: ThresholdResponse; id: ThresholdId; mode: Mode; color: string; loading: boolean }) {
  const [view, setView] = useState<'daily' | 'monthly'>('daily');
  const kinds = view === 'daily' ? ['day'] : ['month', 'mtd'];
  const points = data.periods.filter((p) => kinds.includes(p.kind))
    .map((p) => ({ label: p.kind === 'day' ? formatShortDate(p.start) : p.label, value: pick(data.total.values[p.key], id, mode) }));
  const unit = mode === 'count' ? 'Sites' : '% of sites';
  const tick = (v: number) => (mode === 'count' ? formatNumber(v) : `${v}%`);
  return (
    <ChartCard
      title={view === 'daily' ? 'Daily trend' : 'Monthly trend'}
      description={`${unit}, all circles in the filters${view === 'monthly' ? '; the last bar is the month to date' : ''}.`}
      action={<Switch value={view} onChange={setView} options={[['daily', 'Daily'], ['monthly', 'Monthly']]} label="Trend granularity" />}
      loading={loading}
      empty={!points.some((p) => p.value != null)}
      emptyMessage="No reported data for this period."
    >
      <div className="h-56" role="img" aria-label={`${view} trend of ${unit.toLowerCase()}`}>
        <ResponsiveContainer width="100%" height="100%">
          {view === 'daily' ? (
            <LineChart data={points} margin={{ top: 8, right: 12, bottom: 0, left: 0 }}>
              <CartesianGrid strokeDasharray="3 3" vertical={false} stroke="var(--border)" />
              <XAxis dataKey="label" tick={AXIS_TICK} tickLine={false} axisLine={false} minTickGap={12} />
              <YAxis tickFormatter={tick} tick={AXIS_TICK} tickLine={false} axisLine={false} width={52} />
              <Tooltip formatter={(v) => [show(Number(v), mode), unit]} contentStyle={{ fontSize: 12, borderRadius: 8 }} />
              <Line isAnimationActive={false} type="linear" dataKey="value" stroke={color} strokeWidth={2.25} dot={{ r: 2.5 }} connectNulls={false} />
            </LineChart>
          ) : (
            <BarChart data={points} margin={{ top: 8, right: 12, bottom: 0, left: 0 }}>
              <CartesianGrid strokeDasharray="3 3" vertical={false} stroke="var(--border)" />
              <XAxis dataKey="label" tick={AXIS_TICK} tickLine={false} axisLine={false} interval={0} angle={-30} textAnchor="end" height={40} />
              <YAxis tickFormatter={tick} tick={AXIS_TICK} tickLine={false} axisLine={false} width={52} />
              <Tooltip formatter={(v) => [show(Number(v), mode), unit]} contentStyle={{ fontSize: 12, borderRadius: 8 }} cursor={{ fill: 'var(--muted)' }} />
              <Bar isAnimationActive={false} dataKey="value" fill={color} radius={[3, 3, 0, 0]} maxBarSize={32} />
            </BarChart>
          )}
        </ResponsiveContainer>
      </div>
      <DataTable caption={`${view} trend`} columns={['Period', unit]} rows={points.map((p) => [p.label, show(p.value, mode)])} />
    </ChartCard>
  );
}

function CircleChart({ data, id, mode, color, loading, period, label }: {
  data: ThresholdResponse; id: ThresholdId; mode: Mode; color: string; loading: boolean; period: ThresholdPeriod; label: string;
}) {
  const key = period.key;
  const points = data.rows
    .map((row) => ({ label: rowLabel(row), value: pick(row.values[key], id, mode) }))
    .filter((p) => p.value != null)
    .sort((a, b) => (b.value ?? 0) - (a.value ?? 0));
  const unit = mode === 'count' ? 'Sites' : '% of sites';
  return (
    <ChartCard
      title="By circle"
      description={`${unit} · ${label}, highest first.`}
      loading={loading}
      empty={!points.length}
      emptyMessage="No circle reported for this period."
    >
      <div style={{ height: Math.max(160, points.length * 26 + 24) }} role="img" aria-label={`Bar chart of ${unit.toLowerCase()} by circle`}>
        <ResponsiveContainer width="100%" height="100%">
          <BarChart data={points} layout="vertical" margin={{ top: 0, right: 40, bottom: 0, left: 8 }}>
            <CartesianGrid strokeDasharray="3 3" horizontal={false} stroke="var(--border)" />
            <XAxis type="number" tick={AXIS_TICK} tickLine={false} axisLine={false} tickFormatter={(v: number) => (mode === 'count' ? formatNumber(v) : `${v}%`)} />
            <YAxis type="category" dataKey="label" tick={AXIS_TICK} tickLine={false} axisLine={false} width={72} />
            <Tooltip formatter={(v) => [show(Number(v), mode), unit]} contentStyle={{ fontSize: 12, borderRadius: 8 }} cursor={{ fill: 'var(--muted)' }} />
            <Bar isAnimationActive={false} dataKey="value" radius={[0, 3, 3, 0]} maxBarSize={18}
              label={{ position: 'right', fontSize: 11, fill: 'var(--muted-foreground)', formatter: (v: unknown) => show(Number(v), mode) }}>
              {points.map((p) => <Cell key={p.label} fill={color} />)}
            </Bar>
          </BarChart>
        </ResponsiveContainer>
      </div>
    </ChartCard>
  );
}

function ThresholdTable({ data, id, mode, filters, critical, title }: {
  data: ThresholdResponse; id: ThresholdId; mode: Mode; filters: ResolvedFilters; critical: boolean; title: string;
}) {
  const [allMonths, setAllMonths] = useState(false);
  const [sort, setSort] = useState<{ key: string; desc: boolean } | null>(null);
  const months = data.periods.filter((p) => p.kind === 'month');
  const shownMonths = allMonths ? months : months.slice(-RECENT_MONTHS);
  const groups: { label: string; periods: ThresholdPeriod[] }[] = [
    { label: allMonths ? 'Months' : `Last ${Math.min(RECENT_MONTHS, months.length)} months`, periods: shownMonths },
    { label: 'Month to date', periods: data.periods.filter((p) => p.kind === 'mtd') },
    { label: 'Weeks', periods: data.periods.filter((p) => p.kind === 'week') },
    { label: 'Daily', periods: data.periods.filter((p) => p.kind === 'day') },
  ].filter((g) => g.periods.length);
  const columns = groups.flatMap((g) => g.periods);

  const rows = useMemo(() => {
    if (!sort) return data.rows;
    const value = (row: ThresholdRow) => (sort.key === 'circle' ? rowLabel(row) : sort.key === 'sites' ? row.sites_in_scope : pick(row.values[sort.key], id, mode));
    return [...data.rows].sort((a, b) => {
      const [x, y] = [value(a), value(b)];
      if (x == null || y == null) return x == null ? (y == null ? 0 : 1) : -1;  // no data last
      const order = x < y ? -1 : x > y ? 1 : 0;
      return sort.desc ? -order : order;
    });
  }, [data.rows, sort, id, mode]);

  const toggleSort = (key: string) => setSort((s) => ({ key, desc: s?.key === key ? !s.desc : key !== 'circle' }));
  const sortIcon = (key: string) => (sort?.key === key
    ? (sort.desc ? <ArrowDown className="size-3" /> : <ArrowUp className="size-3" />)
    : <ArrowUpDown className="size-3 opacity-40" />);
  const ariaSort = (key: string) => (sort?.key === key ? (sort.desc ? 'descending' : 'ascending') : undefined);

  const cell = (row: ThresholdRow, period: ThresholdPeriod, isTotal: boolean) => {
    const value = row.values[period.key];
    const v = pick(value, id, mode);
    const text = show(v, mode);
    const tip = value ? `${value.sites_reported} of ${row.sites_in_scope} sites reported` : 'No data reported';
    // Below 60%: a daily or MTD count opens the affected sites in the Site Explorer.
    if (value && value[id].count > 0 && (period.kind === 'day' || period.kind === 'mtd')) {
      return (
        <Link to={siteExplorerLink(filters, row, id, period.kind === 'day' ? period.start : data.reporting_date, period.kind === 'day' ? 'daily' : 'mtd')}
          title={`${tip}. View these sites`} className={cn('font-medium underline-offset-2 hover:underline', critical ? 'text-destructive' : 'text-primary')}>
          {text}
        </Link>
      );
    }
    return <span title={tip} className={cn(!value && 'text-muted-foreground', isTotal && 'font-semibold')}>{text}</span>;
  };

  return (
    <ChartCard
      title={`${title}: by circle`}
      description={`${mode === 'count' ? 'Site counts' : 'Percentage of sites in scope'}. Weeks are the workbook's (1–7, 8–14, 15–21, 22–end); a week in progress shows the days so far.${critical ? ' Select a daily or MTD figure to see the sites.' : ''}`}
      action={months.length > RECENT_MONTHS ? (
        <label className="flex items-center gap-1.5 text-xs text-muted-foreground">
          <input type="checkbox" checked={allMonths} onChange={(e) => setAllMonths(e.target.checked)} className="size-3.5 accent-primary" />
          All {months.length} months
        </label>
      ) : undefined}
      bodyClassName="px-0"
    >
      <div className="overflow-x-auto">
        <table className="w-full border-separate border-spacing-0 text-xs tabular-nums">
          <caption className="sr-only">{title} by circle and period</caption>
          <thead className="bg-muted/50">
            <tr>
              <th scope="col" rowSpan={2} className="sticky left-0 z-10 border-b bg-muted px-3 py-2 text-left font-medium" aria-sort={ariaSort('circle')}>
                <button type="button" onClick={() => toggleSort('circle')} className="inline-flex items-center gap-1">Entity · Circle {sortIcon('circle')}</button>
              </th>
              <th scope="col" rowSpan={2} className="border-b px-3 py-2 text-right font-medium" aria-sort={ariaSort('sites')}>
                <button type="button" onClick={() => toggleSort('sites')} className="inline-flex items-center gap-1">Sites {sortIcon('sites')}</button>
              </th>
              {groups.map((g) => (
                <th key={g.label} scope="colgroup" colSpan={g.periods.length} className="border-b border-l px-3 py-1.5 text-center text-[11px] font-semibold text-muted-foreground uppercase">
                  {g.label}
                </th>
              ))}
            </tr>
            <tr>
              {columns.map((p, i) => (
                <th key={p.key} scope="col" aria-sort={ariaSort(p.key)}
                  className={cn('border-b px-2.5 py-1.5 text-right font-medium whitespace-nowrap', columns[i - 1]?.kind !== p.kind && 'border-l')}>
                  <button type="button" onClick={() => toggleSort(p.key)} className="inline-flex items-center gap-1"
                    title={`${formatDate(p.start)} – ${formatDate(p.end)}${p.kind !== 'month' && p.kind !== 'day' ? ` · ${p.days_reported} of ${p.days} days reported` : ''}`}>
                    {p.kind === 'day' ? formatShortDate(p.start) : p.label}
                    {p.partial && <span className="font-normal text-muted-foreground">*</span>}
                    {sortIcon(p.key)}
                  </button>
                  {p.status && <div className="mt-0.5 flex justify-end"><PeriodStatusBadge status={p.status} missing={p.missing} /></div>}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {rows.map((row) => (
              <tr key={rowLabel(row)} className="hover:bg-muted/40">
                <th scope="row" className="sticky left-0 z-10 border-b bg-card px-3 py-1.5 text-left font-medium whitespace-nowrap">{rowLabel(row)}</th>
                <td className="border-b px-3 py-1.5 text-right">{formatNumber(row.sites_in_scope)}</td>
                {columns.map((p, i) => (
                  <td key={p.key} className={cn('border-b px-2.5 py-1.5 text-right', columns[i - 1]?.kind !== p.kind && 'border-l')}>{cell(row, p, false)}</td>
                ))}
              </tr>
            ))}
          </tbody>
          <tfoot>
            <tr className="bg-muted/60">
              <th scope="row" className="sticky left-0 z-10 bg-muted px-3 py-2 text-left font-semibold">Grand Total</th>
              <td className="px-3 py-2 text-right font-semibold">{formatNumber(data.total.sites_in_scope)}</td>
              {columns.map((p, i) => (
                <td key={p.key} className={cn('px-2.5 py-2 text-right', columns[i - 1]?.kind !== p.kind && 'border-l')}>{cell(data.total, p, true)}</td>
              ))}
            </tr>
          </tfoot>
        </table>
      </div>
      <p className="px-4 pt-2.5 text-xs text-muted-foreground">
        * In progress on the reporting date. — means no site in the row reported in that period. Hover a figure for the number of sites reported.
      </p>
    </ChartCard>
  );
}

function Switch<T extends string>({ value, onChange, options, label }: {
  value: T; onChange: (v: T) => void; options: [T, string][]; label: string;
}) {
  return (
    <div className="inline-flex rounded-lg border p-0.5" role="group" aria-label={label}>
      {options.map(([v, text]) => (
        <button key={v} type="button" aria-pressed={value === v} onClick={() => onChange(v)}
          className={cn('rounded-md px-2.5 py-1 text-xs font-medium transition-colors focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none',
            value === v ? 'bg-primary text-primary-foreground' : 'text-muted-foreground hover:text-foreground')}>
          {text}
        </button>
      ))}
    </div>
  );
}
