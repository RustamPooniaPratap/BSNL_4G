import { useState } from 'react';
import { Link, Navigate, useLocation, useNavigate, useSearchParams } from 'react-router-dom';
import { CalendarDays, ChevronRight, Info } from 'lucide-react';
import { Alert, AlertDescription } from '@/components/ui/alert';
import { Card } from '@/components/ui/card';
import { Skeleton } from '@/components/ui/skeleton';
import { cn } from '@/lib/utils';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table';
import { ChartCard } from '../../components/dashboard/ChartCard';
import { DataTable } from '../../components/dashboard/DataTable';
import { reportTypeColor } from '../../components/dashboard/constants';
import { RootCauseBreakdown } from '../../components/rca/RcaBreakdown';
import { RankedBars, RcaFilterBar, Segmented, SourceValue, type BarRow } from '../../components/rca/RcaShared';
import { FILTER_KEYS, formatMin, rcaCoverageText, shortProject, type FilterKey } from '../../lib/rca';
import { useApiQuery } from '../../hooks/useApiQuery';
import { formatDate, formatNumber } from '../../lib/format';
import { fetchRcaOptions, fetchRcaSummary } from '../../services/api';
import type { RcaCircle, RcaOptions, RcaRanked, RcaSummary } from '../../types/rca';
import { SelectField } from '../../components/data/DataEntry';
import { Field } from '../../components/dashboard/FilterBar';
import { PageHeading } from '../../context/pageHeader';

type Measure = 'records' | 'minutes';
type CircleMeasure = 'records' | 'minutes' | 'rate';
type Network = 'all' | '4G Saturation' | 'LWE';

/** The RCA Summary pages: one dataset (the same filtered API response), several views. */
const SUMMARY_VIEWS = [
  { path: '/rca/summary', label: 'Overview', description: 'Headline totals of the filtered RCA records, and where to look next.' },
  { path: '/rca/summary/breakdown', label: 'Circle-wise RCA Breakdown', description: 'RCA records per circle and Final Bucket reporting category, with totals and shares.' },
  { path: '/rca/summary/root-causes', label: 'Root Cause Analysis', description: 'RCA classifications (Final Bucket, Bucket - 2) and the standardised cause categories.' },
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
  const options = useApiQuery('rca-options', (signal) => fetchRcaOptions(signal));
  const view = SUMMARY_VIEWS.find((v) => v.path === location.pathname.replace(/\/+$/, ''));
  const query = new URLSearchParams();
  for (const key of FILTER_KEYS) {
    const v = params.get(key);
    if (v && key !== 'q' && key !== 'status') query.set(key, v);
  }
  const summary = useApiQuery(`rca-summary-${query}`, (signal) => fetchRcaSummary(query, signal));
  if (!view) return <Navigate to={{ pathname: '/rca/summary', search: location.search }} replace />;  // unknown subpage: the Overview
  const onFilter = (key: FilterKey, value: string) => setParams((cur) => {
    const next = new URLSearchParams(cur);
    if (value) next.set(key, value); else next.delete(key);
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
    <div className="space-y-4">
      <PageHeading title={view.path === '/rca/summary' ? 'RCA Summary' : `RCA Summary · ${view.label}`}
        subtitle={options.data ? `${showingText(options.data, params)} · ${rcaCoverageText(options.data.dates)}` : 'Accepted RCA records'} />
      <SummaryNav current={view} search={location.search} />
      {options.error && <Alert variant="destructive"><AlertDescription>{options.error.message}</AlertDescription></Alert>}
      {options.data ? (
        <RcaFilterBar options={options.data} params={params} onChange={onFilter} onReset={() => setParams(new URLSearchParams(), { replace: true })}
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
            <>
              <Kpis s={s} />
              <OverviewLinks s={s} search={location.search} />
            </>
          )}
          {view.path === '/rca/summary/breakdown' && <RootCauseBreakdown data={s.breakdown} />}
          {view.path === '/rca/summary/root-causes' && (
            <>
              <div className="grid gap-5 xl:grid-cols-2">
                <ClassificationCard title="RCA classification: Final Bucket" items={s.final_buckets} field="final_bucket" onSelect={openRegister} />
                <ClassificationCard title="Secondary classification: Bucket - 2" items={s.bucket_2} field="bucket_2" onSelect={openRegister}
                  scopeNote={s.kpis.rca_not_applicable.records ? `RCA-applicable records only: the ${formatNumber(s.kpis.rca_not_applicable.records)} ${s.kpis.rca_not_applicable.label} records are not included.` : undefined} />
              </div>
              <CategoryCard s={s} onSelect={(category) => openRegister({ category })} />
            </>
          )}
          {view.path === '/rca/summary/circles' && (
            <>
              <CircleCard circles={s.circles} populationSource={s.population_source} onSelect={(circle) => openRegister({ circle })} />
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

/** Overview: one line per analysis page, with a figure taken from the same response. */
function OverviewLinks({ s, search }: { s: RcaSummary; search: string }) {
  const topCause = s.final_buckets.filter((i) => !i.unclassified && !i.rca_not_applicable).sort((a, b) => b.records - a.records)[0];
  const topCircle = [...s.circles].sort((a, b) => b.records - a.records)[0];
  const facts: Record<string, string> = {
    '/rca/summary/breakdown': `${formatNumber(s.breakdown.grand_total)} records in the reporting categories${s.breakdown.not_mapped.records ? ` · ${formatNumber(s.breakdown.not_mapped.records)} not mapped` : ''}`,
    '/rca/summary/root-causes': topCause ? `Most frequent Final Bucket: ${topCause.label} (${formatNumber(topCause.records)})` : 'No classified Final Bucket in the filter',
    '/rca/summary/circles': topCircle ? `Most records: ${topCircle.circle} · ${shortProject(topCircle.project)} (${formatNumber(topCircle.records)})` : 'No circle in the filter',
    '/rca/summary/trends': `${formatNumber(s.dates.length)} reporting date${s.dates.length === 1 ? '' : 's'} with records`,
  };
  return (
    <section aria-label="RCA analysis pages" className="grid gap-3 md:grid-cols-2">
      {SUMMARY_VIEWS.slice(1).map((v) => (
        <Link key={v.path} to={{ pathname: v.path, search }}
          className="group flex flex-col gap-1 rounded-xl border bg-card px-4 py-3 shadow-xs transition-colors hover:bg-muted/40 focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none">
          <span className="flex items-center justify-between text-sm font-semibold">{v.label}<ChevronRight className="size-4 text-muted-foreground transition-transform group-hover:translate-x-0.5" aria-hidden="true" /></span>
          <span className="text-xs text-muted-foreground">{v.description}</span>
          <span className="mt-1 text-sm tabular-nums">{facts[v.path]}</span>
        </Link>
      ))}
    </section>
  );
}

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
    <div className="grid gap-5 xl:grid-cols-2">
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

/** The reporting period of the filtered dates (or the latest one): expected data received, pending, and its consolidated report. */
function Kpis({ s }: { s: RcaSummary }) {
  const k = s.kpis;
  const card = (label: string, value: string, note: string, tone?: string, link?: string) => (
    <Card className="gap-1 rounded-xl px-4 py-3" role="group" aria-label={label}>
      <p className="text-sm font-medium text-foreground/80">{label}</p>
      <p className={`text-2xl font-semibold tracking-tight tabular-nums ${tone ?? ''}`}>{value}</p>
      <p className="text-xs text-muted-foreground">{note}</p>
      {link && <Link to={link} className="mt-auto pt-1 text-xs font-medium underline-offset-2 hover:underline">View records →</Link>}
    </Card>
  );
  return (
    <section className="grid gap-3 sm:grid-cols-3" aria-label="RCA summary KPIs">
      {card('Total RCA records', formatNumber(k.records), 'Incidents with an RCA in the filter')}
      {card('Distinct affected sites', formatNumber(k.affected_sites), 'Sites with at least one RCA record')}
      {card('Total recorded outage', k.outage_minutes == null ? 'Not recorded' : `${formatNumber(Math.round(k.outage_minutes))} min`,
        k.records_with_minutes === k.records ? 'Outage Min. of every record' : `From ${formatNumber(k.records_with_minutes)} records with a value`)}
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
    key: i.key, label: i.rca_not_applicable ? `${i.label} — RCA not applicable` : i.label, muted: i.unclassified || i.rca_not_applicable,
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
      <RankedBars rows={rows} label={title} onSelect={(key) => onSelect({ [field]: key })} />
      <p className="mt-2 text-[11px] text-muted-foreground">
        Labels differing only in case or spacing are grouped (hover for the source spellings). Blank or "-" is listed as unclassified, not as a cause.
        {field === 'final_bucket' && ' Other Media is listed separately: RCA is not applicable to it, so it is not ranked as a technical cause.'}
        {scopeNote && ` ${scopeNote}`} Select a bar to open those records.
      </p>
      <DataTable caption={title} columns={['Label', 'Records', 'Outage minutes', 'Source spellings']}
        rows={rows.map((r) => { const i = items.find((x) => x.key === r.key)!; return [r.label, formatNumber(i.records), formatMin(i.outage_minutes), i.variants.join(', ') || '—']; })} />
    </ChartCard>
  );
}

function CircleCard({ circles, populationSource, onSelect }: { circles: RcaCircle[]; populationSource: string | null; onSelect: (circle: string) => void }) {
  const [network, setNetwork] = useState<Network>('all');
  const [measure, setMeasure] = useState<CircleMeasure>('records');
  const shown = circles.filter((c) => network === 'all' || c.project === network);
  const value = (c: RcaCircle) => (measure === 'records' ? c.records : measure === 'minutes' ? c.outage_minutes : c.records_per_100_sites);
  const sorted = [...shown].sort((a, b) => (value(b) ?? -1) - (value(a) ?? -1));
  const rows: BarRow[] = sorted.map((c) => ({
    key: c.circle, label: `${c.circle} · ${shortProject(c.project)}`, value: value(c),
    display: measure === 'records' ? formatNumber(c.records) : measure === 'minutes' ? formatMin(c.outage_minutes)
      : c.records_per_100_sites == null ? 'No population' : c.records_per_100_sites.toFixed(1),
    note: measure === 'rate' && c.portfolio_sites ? `of ${formatNumber(c.portfolio_sites)} sites` : undefined,
    title: `${c.records} records, ${formatMin(c.outage_minutes)}, ${c.affected_sites} affected sites${c.portfolio_sites ? `, ${c.portfolio_sites} sites in the portfolio` : ''}`,
  }));
  const colorOf = network === 'all' ? 'var(--chart-1)' : reportTypeColor(network);
  return (
    <ChartCard title="Circle-wise comparison"
      description={measure === 'rate' ? 'RCA records per 100 sites in the portfolio, so circles of different sizes compare more fairly.'
        : 'Raw totals: larger circles have more sites, so these are not a performance ranking on their own.'}
      action={(
        <div className="flex flex-wrap justify-end gap-2">
          <Segmented label="Network" value={network} onChange={setNetwork} options={[['all', 'All'], ['4G Saturation', '4G'], ['LWE', 'LWE']]} />
          <Segmented label="Circle measure" value={measure} onChange={setMeasure} options={[['records', 'Incidents'], ['minutes', 'Outage min'], ['rate', 'Per 100 sites']]} />
        </div>
      )}
      empty={!shown.length}>
      <RankedBars rows={rows} label="RCA by circle" color={colorOf} onSelect={onSelect} />
      <p className="mt-2 flex items-start gap-1.5 text-[11px] text-muted-foreground">
        <Info className="mt-px size-3 shrink-0" aria-hidden="true" />
        {populationSource ? `Per 100 sites uses: ${populationSource}.` : 'Per-site rates are not available: no Master data is loaded for the site population.'}
      </p>
      <DataTable caption="RCA by circle" columns={['Circle', 'Project', 'Records', 'Outage minutes', 'Affected sites', 'Portfolio sites', 'Records per 100 sites']}
        rows={sorted.map((c) => [c.circle, c.project, formatNumber(c.records), formatMin(c.outage_minutes), formatNumber(c.affected_sites),
          c.portfolio_sites == null ? '—' : formatNumber(c.portfolio_sites), c.records_per_100_sites == null ? '—' : c.records_per_100_sites.toFixed(1)])} />
    </ChartCard>
  );
}

function CategoryCard({ s, onSelect }: { s: RcaSummary; onSelect: (category: string) => void }) {
  const { mapped, unreviewed, no_description: none } = s.categories;
  const rows: BarRow[] = [
    ...mapped.map((c) => ({ key: String(c.id), label: c.name, value: c.records, display: formatNumber(c.records), note: formatMin(c.outage_minutes) })),
    ...(unreviewed.records ? [{ key: 'unreviewed', label: 'Unreviewed descriptions', value: unreviewed.records, display: formatNumber(unreviewed.records), muted: true,
      note: `${formatNumber(unreviewed.descriptions)} texts` }] : []),
  ];
  return (
    <ChartCard title="Standardised cause categories" description="From Admin-approved mappings of RCA descriptions only. Unreviewed descriptions are counted separately, never guessed.">
      {mapped.length === 0 && (
        <p className="mb-3 rounded-md bg-muted/60 px-3 py-2 text-xs text-muted-foreground">
          No descriptions have been reviewed yet: {formatNumber(unreviewed.descriptions)} distinct RCA texts ({formatNumber(unreviewed.records)} records) are waiting in the{' '}
          <Link to="/rca/mappings" className="font-medium text-foreground underline underline-offset-2">cause-mapping review queue</Link>.
        </p>
      )}
      <RankedBars rows={rows} label="Cause categories" onSelect={onSelect} />
      {none.records > 0 && <p className="mt-2 text-[11px] text-muted-foreground">{formatNumber(none.records)} records have no RCA description.</p>}
    </ChartCard>
  );
}

function TopRecords({ s }: { s: RcaSummary }) {
  return (
    <ChartCard title="Site-level attention: largest outages" description="The 15 RCA records with the most outage minutes in the filter. Open a record to review it and record follow-up." empty={!s.top_records.length}>
      <div className="overflow-x-auto">
        <Table>
          <TableHeader>
            <TableRow>{['Site ID', 'Site name', 'Circle', 'Project', 'Outage', 'Final Bucket', 'RCA'].map((h) => <TableHead key={h} className={h === 'Outage' ? 'text-right' : undefined}>{h}</TableHead>)}</TableRow>
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
                <TableCell className="max-w-80 truncate" title={r.rca_text}><SourceValue value={r.rca_text} unclassified={r.rca_unclassified} /></TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </div>
    </ChartCard>
  );
}
