import { useState } from 'react';
import { Link, Navigate, useLocation, useNavigate, useSearchParams } from 'react-router-dom';
import { CalendarDays, ChartLine, FileWarning, ListTree, MapPin, MapPinned, Table2, TimerOff, type LucideIcon } from 'lucide-react';
import { Alert, AlertDescription } from '@/components/ui/alert';
import { Skeleton } from '@/components/ui/skeleton';
import { cn } from '@/lib/utils';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table';
import { ChartCard } from '../../components/dashboard/ChartCard';
import { DataTable } from '../../components/dashboard/DataTable';
import { reportTypeColor } from '../../components/dashboard/constants';
import { RootCauseBreakdown } from '../../components/rca/RcaBreakdown';
import { RcaOverviewTable } from '../../components/rca/RcaOverviewTable';
import { RcaAnalysisTile, RcaKpiTile, RcaSection } from '../../components/rca/RcaTiles';
import type { Tint } from '../../components/portfolio/PortfolioKpis';
import { RankedBars, RcaFilterBar, Segmented, SourceValue, type BarRow } from '../../components/rca/RcaShared';
import { FILTER_KEYS, formatMin, rcaCoverageText, shortProject, type FilterKey } from '../../lib/rca';
import { useApiQuery } from '../../hooks/useApiQuery';
import { formatDate, formatNumber } from '../../lib/format';
import { fetchRcaOptions, fetchRcaSummary } from '../../services/api';
import type { RcaCircle, RcaClassificationCounts, RcaOptions, RcaRanked, RcaSummary } from '../../types/rca';
import { SelectField } from '../../components/data/DataEntry';
import { Field } from '../../components/dashboard/FilterBar';
import { PageHeading } from '../../context/pageHeader';
import { usePopulation } from '../../context/population';
import { useRcaBucketMappingRevision } from '../../lib/rcaBucketMapping';

type Measure = 'records' | 'minutes';
type CircleMeasure = 'records' | 'minutes';
type Network = string;  // 'all' or a project of the data

/** The RCA Summary pages: one dataset (the same filtered API response), several views. */
const SUMMARY_VIEWS = [
  { path: '/rca/summary', label: 'Overview', description: 'Headline totals of the filtered RCA records, and where to look next.' },
  { path: '/rca/summary/breakdown', label: 'Circle-wise RCA Breakdown', description: 'RCA records per circle and Final Bucket reporting category, with totals and shares.' },
  { path: '/rca/summary/root-causes', label: 'Root Cause Analysis', description: 'RCA classifications (Final Bucket, Bucket - 2).' },
  { path: '/rca/summary/circles', label: 'Project & Circle Analysis', description: 'Circles compared within 4G Saturation and LWE, and the sites with the largest outages.' },
  { path: '/rca/summary/trends', label: 'Daily & Monthly Trends', description: 'RCA records per reporting date, and per month from the dates with records.' },
] as const;
type SummaryView = (typeof SUMMARY_VIEWS)[number];

/**
 * RCA Summary (Admin): one snapshot of the stored RCA records, split into an Overview and analysis pages. Every page
 * reads the same filters from the URL (date, project, circle, buckets…), so moving between them keeps the selection.
 */
export function RcaSummaryPage() {
  const location = useLocation();
  const [params, setParams] = useSearchParams();
  const navigate = useNavigate();
  const mappingRevision = useRcaBucketMappingRevision();
  const options = useApiQuery(`rca-options-summary-${mappingRevision}`, (signal) => fetchRcaOptions(signal, true));
  const view = SUMMARY_VIEWS.find((v) => v.path === location.pathname.replace(/\/+$/, ''));
  const query = new URLSearchParams();
  for (const key of FILTER_KEYS) {
    const v = params.get(key);
    // No Site Scope here: Population is the site control, so an old site_scope in the URL never filters the records.
    if (v && key !== 'q' && key !== 'status' && key !== 'site_scope') query.set(key, v);
  }
  // Site metrics (sites, USD, NSLA) follow the global population, the one site control of the RCA Summary.
  const { scope, sitesLabel } = usePopulation();
  const summary = useApiQuery(`rca-summary-${scope}-${query}-${mappingRevision}`, (signal) => fetchRcaSummary(query, scope, signal));
  if (!view) return <Navigate to={{ pathname: '/rca/summary', search: location.search }} replace />;  // unknown subpage: the Overview
  const onFilter = (key: FilterKey, value: string, extra: Partial<Record<FilterKey, string>> = {}) => setParams((cur) => {
    const next = new URLSearchParams(cur);
    for (const [k, v] of Object.entries({ [key]: value, ...extra })) { if (v) next.set(k, v); else next.delete(k); }
    if (key === 'project') next.delete('circle');
    return next;
  }, { replace: true });
  // A bar opens the register with the same filters plus that classification.
  const openRegister = (extra: Record<string, string>) => {
    const next = new URLSearchParams(query);
    for (const [k, v] of Object.entries(extra)) next.set(k, v);
    navigate(`/rca?${next}`);
  };
  const s = summary.data;

  return (
    <div className="space-y-3">
      <PageHeading title={view.path === '/rca/summary' ? 'RCA Summary' : `RCA Summary · ${view.label}`}
        subtitle={options.data ? `${showingText(options.data, params)} · Population: ${sitesLabel} · ${rcaCoverageText(options.data.dates)}` : `Accepted RCA records · Population: ${sitesLabel}`} />
      <SummaryNav current={view} search={location.search} />
      {options.error && <Alert variant="destructive"><AlertDescription>{options.error.message}</AlertDescription></Alert>}
      {options.data ? (
        <RcaFilterBar options={options.data} params={params} onChange={onFilter} onReset={() => setParams(new URLSearchParams(), { replace: true })} population
          lead={<ReportingDateSelect options={options.data} params={params} onChange={(from, to) => setParams((cur) => {
            const next = new URLSearchParams(cur);
            if (from) { next.set('date_from', from); next.set('date_to', to); } else { next.delete('date_from'); next.delete('date_to'); }
            return next;
          }, { replace: true })} />} />
      ) : !options.error && <Skeleton className="h-16 w-full" />}

      {summary.error && <Alert variant="destructive" role="alert"><AlertDescription>{summary.error.message}</AlertDescription></Alert>}
      {!s && !summary.error && <Skeleton className="h-96 w-full" aria-label="Loading the RCA summary" />}
      {s && (
        <>
          {s.dates.length <= 1 && !query.get('date_from') && !query.get('date_to') && (
            <p className="flex items-center gap-2 rounded-lg border bg-muted/40 px-4 py-2 text-sm text-muted-foreground">
              <CalendarDays className="size-4 shrink-0" aria-hidden="true" />
              {s.dates.length ? `Single-date snapshot: ${formatDate(s.dates[0].date)}. Trends over time appear once RCA data for more reporting dates is imported.` : 'No RCA records match these filters.'}
            </p>
          )}
          {view.path === '/rca/summary' && (
            <RcaOverviewTable query={query} />
          )}
          {view.path === '/rca/summary/breakdown' && (
            <RootCauseBreakdown
              data={s.breakdown}
              rcaScope={(params.get('rca_scope') === 'nsla' ? 'nsla' : 'all')}
              onRcaScopeChange={(scope) => onFilter('rca_scope' as FilterKey, scope === 'nsla' ? 'nsla' : '')}
            />
          )}
          {view.path === '/rca/summary/root-causes' && (
            <>
              {s.classification && <ClassificationStatus counts={s.classification} />}
              <div className="grid gap-4 xl:grid-cols-2">
                <ClassificationCard title="RCA classification: Final Bucket" items={s.final_buckets} field="final_bucket" onSelect={openRegister} />
                <ClassificationCard title="Secondary classification: Bucket - 2 (per Final Bucket)" items={s.bucket_2} field="bucket_2" onSelect={openRegister}
                  scopeNote={s.kpis.rca_not_applicable.records ? `RCA-applicable records only: the ${formatNumber(s.kpis.rca_not_applicable.records)} ${s.kpis.rca_not_applicable.label} records are not included.` : undefined} />
              </div>
            </>
          )}
          {view.path === '/rca/summary/circles' && (
            <>
              <CircleCard circles={s.circles} onSelect={(circle) => openRegister({ circle })} />
              <TopRecords s={s} />
            </>
          )}
          {view.path === '/rca/summary/trends' && <TrendsCard dates={s.dates} />}
        </>
      )}
    </div>
  );
}

/** The RCA Summary pages as tabs; every link keeps the current filters. */
function SummaryNav({ current, search }: { current: SummaryView; search: string }) {
  return (
    <nav aria-label="RCA Summary pages" className="flex flex-wrap gap-1 rounded-xl border bg-card p-1 shadow-xs">
      {SUMMARY_VIEWS.map((v) => (
        <Link key={v.path} to={{ pathname: v.path, search }} aria-current={v.path === current.path ? 'page' : undefined}
          className={cn('rounded-lg px-3 py-1.5 text-sm font-medium transition-colors focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none',
            v.path === current.path ? 'bg-primary text-primary-foreground' : 'text-muted-foreground hover:bg-muted hover:text-foreground')}>
          {v.label}
        </Link>
      ))}
    </nav>
  );
}

/** Overview: one tile per analysis page (excluding circle-wise breakdown), with a figure taken from the same response. */
export function OverviewLinks({ s, search }: { s: RcaSummary; search: string }) {
  const topCause = s.final_buckets.filter((i) => !i.unclassified && !i.rca_not_applicable).sort((a, b) => b.records - a.records)[0];
  const topCircle = [...s.circles].sort((a, b) => b.records - a.records)[0];
  const facts: Record<string, { headline: string; detail: string }> = {
    '/rca/summary/root-causes': topCause
      ? { headline: topCause.label, detail: `Most frequent Final Bucket · ${formatNumber(topCause.records)} records` }
      : { headline: '—', detail: 'No classified Final Bucket in the filter' },
    '/rca/summary/circles': topCircle
      ? { headline: `${topCircle.circle} · ${shortProject(topCircle.project)}`, detail: `Most records · ${formatNumber(topCircle.records)}` }
      : { headline: '—', detail: 'No circle in the filter' },
    '/rca/summary/trends': { headline: formatNumber(s.dates.length), detail: `reporting date${s.dates.length === 1 ? '' : 's'} with records` },
  };
  const tiles = SUMMARY_VIEWS.filter((v) => v.path !== '/rca/summary' && v.path !== '/rca/summary/breakdown');
  return (
    <RcaSection heading="RCA analysis" label="RCA analysis pages" columns={3}>
      {tiles.map((v) => (
        <RcaAnalysisTile key={v.path} label={v.label} description={v.description} icon={VIEW_LOOK[v.path].icon} tint={VIEW_LOOK[v.path].tint}
          headline={facts[v.path].headline} headlineIsMetric={v.path === '/rca/summary/trends'}
          detail={facts[v.path].detail} to={{ pathname: v.path, search }} />
      ))}
    </RcaSection>
  );
}

/** Icon and tint of each analysis page, as the sidebar icons. */
const VIEW_LOOK: Record<string, { icon: LucideIcon; tint: Tint }> = {
  '/rca/summary/breakdown': { icon: Table2, tint: 'sky' },
  '/rca/summary/root-causes': { icon: ListTree, tint: 'violet' },
  '/rca/summary/circles': { icon: MapPinned, tint: 'teal' },
  '/rca/summary/trends': { icon: ChartLine, tint: 'emerald' },
};

/** RCA records per reporting date and per month (the sum of that month's dates with records). Dates without records are absent, not zero. */
function TrendsCard({ dates }: { dates: RcaSummary['dates'] }) {
  const months = new Map<string, { records: number; dates: number }>();
  for (const d of dates) {
    const key = d.date.slice(0, 7);
    const m = months.get(key) ?? { records: 0, dates: 0 };
    months.set(key, { records: m.records + d.records, dates: m.dates + 1 });
  }
  const daily: BarRow[] = dates.map((d) => ({ key: d.date, label: formatDate(d.date), value: d.records, display: formatNumber(d.records) }));
  const monthly: BarRow[] = [...months].map(([key, m]) => ({
    key, label: monthLabel(key), value: m.records, display: formatNumber(m.records), note: `${m.dates} reporting date${m.dates === 1 ? '' : 's'}`,
  }));
  return (
    <div className="grid gap-4 xl:grid-cols-2">
      <ChartCard title="Daily: RCA records per reporting date" description="Oldest first. Only dates with RCA records are listed; a missing date is not shown as zero." empty={!dates.length}>
        <RankedBars rows={daily} label="RCA records per reporting date" />
        <DataTable caption="RCA records per reporting date" columns={['Reporting date', 'Records']} rows={dates.map((d) => [formatDate(d.date), formatNumber(d.records)])} />
      </ChartCard>
      <ChartCard title="Monthly: RCA records per month" description="Each month adds up its reporting dates with records (the same rule as the month choice of the Reporting date filter)." empty={!dates.length}>
        <RankedBars rows={monthly} label="RCA records per month" />
        <DataTable caption="RCA records per month" columns={['Month', 'Records', 'Reporting dates with records']}
          rows={[...months].map(([key, m]) => [monthLabel(key), formatNumber(m.records), formatNumber(m.dates)])} />
      </ChartCard>
    </div>
  );
}

/** The register link keeps the summary's filters. */
export const filterSearch = (query: URLSearchParams) => (query.toString() ? `?${query}` : '');

const monthBounds = (month: string): [string, string] => {
  const [y, m] = month.split('-').map(Number);
  const last = new Date(Date.UTC(y, m, 0)).getUTCDate();
  return [`${month}-01`, `${month}-${String(last).padStart(2, '0')}`];
};
const monthLabel = (month: string) => new Date(`${month}-01T00:00:00Z`).toLocaleDateString('en-IN', { month: 'short', year: 'numeric', timeZone: 'UTC' });

/**
 * One reporting date, or a month aggregated from the dates that have records (offered only for months with records).
 * It sets the From / To filters, so the summary below is calculated by the API for exactly those dates.
 */
function ReportingDateSelect({ options, params, onChange }: { options: RcaOptions; params: URLSearchParams; onChange: (from: string, to: string) => void }) {
  const from = params.get('date_from') ?? '';
  const to = params.get('date_to') ?? '';
  const month = options.months.find((m) => monthBounds(m.month).join() === [from, to].join());
  const value = !from && !to ? 'all' : from === to && options.dates.includes(from) ? `day:${from}` : month ? `month:${month.month}` : 'custom';
  const choices = [
    { value: 'all', label: 'All reporting dates' },
    ...[...options.dates].reverse().map((d) => ({ value: `day:${d}`, label: formatDate(d) })),
    ...options.months.map((m) => ({ value: `month:${m.month}`, label: `${monthLabel(m.month)} — month (${m.dates_with_records} reporting date${m.dates_with_records === 1 ? '' : 's'} with records)` })),
    ...(value === 'custom' ? [{ value: 'custom', label: 'Custom range (From / To below)' }] : []),
  ];
  return (
    <Field id="rca-reporting-date" label="Reporting date" className="w-72">
      <SelectField id="rca-reporting-date" value={value} placeholder="Reporting date" options={choices} onChange={(v) => {
        if (v === 'all' || v === 'custom') onChange('', '');
        else if (v.startsWith('day:')) onChange(v.slice(4), v.slice(4));
        else onChange(...monthBounds(v.slice(6)));
      }} />
    </Field>
  );
}

/** What the summary shows (in the top bar): every date, one reporting date, a month aggregate or a custom range. */
function showingText(options: RcaOptions, params: URLSearchParams) {
  const from = params.get('date_from') ?? '';
  const to = params.get('date_to') ?? '';
  const month = options.months.find((m) => monthBounds(m.month).join() === [from, to].join());
  if (!from && !to) return 'Showing every reporting date';
  if (from === to) return `Showing ${formatDate(from)}`;
  if (month) return `Showing ${monthLabel(month.month)}: the sum of ${month.dates_with_records} reporting date${month.dates_with_records === 1 ? '' : 's'} with records`;
  return `Showing ${from ? formatDate(from) : 'the first date'} – ${to ? formatDate(to) : 'the latest date'}`;
}

/** The three RCA totals of the filtered records, in the dashboard's KPI tile style (same values and wording as before). */
export function Kpis({ s, search }: { s: RcaSummary; search: string }) {
  const k = s.kpis;
  return (
    <RcaSection heading="RCA records" label="RCA summary KPIs" columns={3}>
      <RcaKpiTile label="Total RCA records" icon={FileWarning} tint="sky" value={formatNumber(k.records)} context="Incidents with an RCA in the filter"
        definition="Accepted RCA records (incidents) matching the filters. Withdrawn records are not counted." link={{ pathname: '/rca', search }} view="View records" />
      <RcaKpiTile label="Distinct affected sites" icon={MapPin} tint="violet" value={formatNumber(k.affected_sites)} context="Sites with at least one RCA record"
        definition="Distinct sites (project and Site ID) with at least one RCA record matching the filters." />
      <RcaKpiTile label="Total recorded outage" icon={TimerOff} tint="orange" value={k.outage_minutes == null ? null : formatNumber(Math.round(k.outage_minutes))}
        unit="min" missing="Not recorded"
        context={k.records_with_minutes === k.records ? 'Outage Min. of every record' : `From ${formatNumber(k.records_with_minutes)} records with a value`}
        definition="Sum of Outage Min. as written in the RCA records. A record without a value is left out, never counted as 0." />
    </RcaSection>
  );
}

/** How the filtered records fit the approved bucketization (counts from the server). */
function ClassificationStatus({ counts }: { counts: RcaClassificationCounts }) {
  const total = counts.approved + counts.final_only + counts.unapproved + counts.blank;
  const parts: [string, number, string][] = [
    ['Approved Final Bucket and Bucket - 2', counts.approved, 'bg-emerald-500'],
    ['Approved Final Bucket, Bucket - 2 to review', counts.final_only, 'bg-amber-400'],
    ['Final Bucket not in the approved list', counts.unapproved, 'bg-red-400'],
    ['Blank', counts.blank, 'bg-slate-300'],
  ];
  return (
    <section aria-label="Approved classification" className="rounded-xl border bg-card px-4 py-3 shadow-xs">
      <p className="text-sm font-medium text-foreground/80">Approved bucketization <span className="text-xs font-normal text-muted-foreground">· records of the filter by classification</span></p>
      <div className="mt-2 flex h-2 overflow-hidden rounded-full bg-muted" aria-hidden="true">
        {parts.map(([label, n, color]) => n > 0 && <div key={label} className={color} style={{ width: `${(100 * n) / (total || 1)}%` }} />)}
      </div>
      <ul className="mt-2 flex flex-wrap gap-x-5 gap-y-1 text-xs">
        {parts.map(([label, n, color]) => (
          <li key={label} className="flex items-center gap-1.5"><span className={cn('size-2 rounded-full', color)} aria-hidden="true" />{label}: <span className="font-semibold tabular-nums">{formatNumber(n)}</span></li>
        ))}
      </ul>
    </section>
  );
}

function ClassificationCard({ title, items, field, onSelect, scopeNote }: {
  title: string; items: RcaRanked[]; field: 'final_bucket' | 'bucket_2'; onSelect: (f: Record<string, string>) => void; scopeNote?: string;
}) {
  const [measure, setMeasure] = useState<Measure>('records');
  const totalRecords = items.reduce((a, i) => a + i.records, 0);
  // Technical causes are ranked; RCA-not-applicable (Other Media) and unclassified rows follow, muted.
  const classified = items.filter((i) => !i.unclassified && !i.rca_not_applicable);
  const ranked = [...classified].sort((a, b) => (measure === 'records' ? b.records - a.records : (b.outage_minutes ?? 0) - (a.outage_minutes ?? 0)));
  const rows: BarRow[] = [...ranked, ...items.filter((i) => i.rca_not_applicable), ...items.filter((i) => i.unclassified)].map((i) => ({
    key: i.key, label: i.rca_not_applicable ? `${i.label} — RCA not applicable` : i.approved === false && !i.unclassified ? `${i.label} (not approved)` : i.label,
    muted: i.unclassified || i.rca_not_applicable,
    value: measure === 'records' ? i.records : i.outage_minutes,
    display: measure === 'records' ? formatNumber(i.records) : formatMin(i.outage_minutes),
    note: measure === 'records' && totalRecords ? `${((100 * i.records) / totalRecords).toFixed(1)}%` : undefined,
    title: i.variants.length > 1 ? `Source spellings: ${i.variants.join(', ')}` : undefined,
  }));
  return (
    <ChartCard title={title}
      description={measure === 'records' ? 'Number of RCA records (incidents) per label, most first.' : 'Sum of Outage Min. per label, most first. A few long outages can outrank many short ones.'}
      action={<Segmented label={`${title} measure`} value={measure} onChange={setMeasure} options={[['records', 'Incidents'], ['minutes', 'Outage minutes']]} />}
      empty={!items.length}>
      <RankedBars rows={rows} label={title} onSelect={(key) => onSelect(items.find((i) => i.key === key)?.filter ?? { [field]: key })} />
      <p className="mt-2 text-[11px] text-muted-foreground">
        Labels differing only in case or spacing are grouped (hover for the source spellings). Blank or "-" is listed as unclassified, not as a cause.
        {field === 'bucket_2' && ' Each Bucket - 2 is read with its Final Bucket (e.g. Fluctuation under BSNL Media, DMW and HFCL are separate).'}
        {' "(not approved)": outside the approved bucketization, kept as recorded for review.'}
        {field === 'final_bucket' && ' Other Media is listed separately: RCA is not applicable to it, so it is not ranked as a technical cause.'}
        {scopeNote && ` ${scopeNote}`} Select a bar to open those records.
      </p>
      <DataTable caption={title} columns={['Label', 'Records', 'Outage minutes', 'Source spellings']}
        rows={rows.map((r) => { const i = items.find((x) => x.key === r.key)!; return [r.label, formatNumber(i.records), formatMin(i.outage_minutes), i.variants.join(', ') || '—']; })} />
    </ChartCard>
  );
}

function CircleCard({ circles, onSelect }: { circles: RcaCircle[]; onSelect: (circle: string) => void }) {
  const [network, setNetwork] = useState<Network>('all');
  const [measure, setMeasure] = useState<CircleMeasure>('records');
  const shown = circles.filter((c) => network === 'all' || c.project === network);
  const value = (c: RcaCircle) => (measure === 'records' ? c.records : c.outage_minutes);
  const sorted = [...shown].sort((a, b) => (value(b) ?? -1) - (value(a) ?? -1));
  const rows: BarRow[] = sorted.map((c) => ({
    key: c.circle, label: `${c.circle} · ${shortProject(c.project)}`, value: value(c),
    display: measure === 'records' ? formatNumber(c.records) : formatMin(c.outage_minutes),
    title: `${c.records} records, ${formatMin(c.outage_minutes)}, ${c.affected_sites} affected sites`,
  }));
  const colorOf = network === 'all' ? 'var(--chart-1)' : reportTypeColor(network);
  return (
    <ChartCard title="Circle-wise comparison"
      description="Raw totals: larger circles have more sites, so these are not a performance ranking on their own."
      action={(
        <div className="flex flex-wrap justify-end gap-2">
          <Segmented label="Network" value={network} onChange={setNetwork}
            options={[['all', 'All'], ...[...new Set(circles.map((c) => c.project))].sort().map((p) => [p, shortProject(p)] as [string, string])]} />
          <Segmented label="Circle measure" value={measure} onChange={setMeasure} options={[['records', 'Incidents'], ['minutes', 'Outage min']]} />
        </div>
      )}
      empty={!shown.length}>
      <RankedBars rows={rows} label="RCA by circle" color={colorOf} onSelect={onSelect} />
      <DataTable caption="RCA by circle" columns={['Circle', 'Project', 'Records', 'Outage minutes', 'Affected sites']}
        rows={sorted.map((c) => [c.circle, c.project, formatNumber(c.records), formatMin(c.outage_minutes), formatNumber(c.affected_sites)])} />
    </ChartCard>
  );
}



function TopRecords({ s }: { s: RcaSummary }) {
  return (
    <ChartCard title="Site-level attention: largest outages" description="The 15 RCA records with the most outage minutes in the filter. Open a record to review it and record follow-up." empty={!s.top_records.length}>
      <div className="overflow-x-auto">
        <Table>
          <TableHeader>
            <TableRow>{['Site ID', 'Site name', 'Circle', 'Project', 'Outage', 'Final Bucket', 'Responsibility', 'RCA'].map((h) => <TableHead key={h} className={h === 'Outage' ? 'text-right' : undefined}>{h}</TableHead>)}</TableRow>
          </TableHeader>
          <TableBody>
            {s.top_records.map((r) => (
              <TableRow key={r.id}>
                <TableCell className="font-mono text-xs"><Link to={`/rca?record=${r.id}`} className="underline underline-offset-2">{r.site_id}</Link></TableCell>
                <TableCell className="max-w-40 truncate">{r.site_name || '—'}</TableCell>
                <TableCell>{r.circle}</TableCell>
                <TableCell>{shortProject(r.project)}</TableCell>
                <TableCell className="text-right tabular-nums">{formatMin(r.outage_minutes)}</TableCell>
                <TableCell><SourceValue value={r.final_bucket} unclassified={r.final_bucket_unclassified} /></TableCell>
                <TableCell>{r.mapped_bucket}</TableCell>
                <TableCell className="max-w-80 truncate" title={r.rca_text}><SourceValue value={r.rca_text} unclassified={r.rca_unclassified} /></TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </div>
    </ChartCard>
  );
}
