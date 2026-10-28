import { useState } from 'react';
import { Link, useNavigate, useSearchParams } from 'react-router-dom';
import { CalendarDays, ChartBar, Info } from 'lucide-react';
import { Alert, AlertDescription } from '@/components/ui/alert';
import { Card } from '@/components/ui/card';
import { Skeleton } from '@/components/ui/skeleton';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table';
import { ChartCard } from '../../components/dashboard/ChartCard';
import { DataTable } from '../../components/dashboard/DataTable';
import { reportTypeColor } from '../../components/dashboard/constants';
import { CycleBadge, RankedBars, RcaFilterBar, Segmented, SourceValue, type BarRow } from '../../components/rca/RcaShared';
import { FILTER_KEYS, formatMin, shortProject, type FilterKey } from '../../lib/rca';
import { useApiQuery } from '../../hooks/useApiQuery';
import { formatDate, formatNumber } from '../../lib/format';
import { fetchRcaOptions, fetchRcaSummary, rcaCycleWorkbookUrl } from '../../services/api';
import type { RcaCircle, RcaCycle, RcaOptions, RcaRanked, RcaSummary } from '../../types/rca';
import { Field, SelectField } from '../../components/data/DataEntry';

type Measure = 'records' | 'minutes';
type CircleMeasure = 'records' | 'minutes' | 'rate';
type Network = 'all' | '4G Saturation' | 'LWE';

/** RCA Summary (Admin): one snapshot of the stored RCA records, by classification, circle and largest outages. */
export function RcaSummaryPage() {
  const [params, setParams] = useSearchParams();
  const navigate = useNavigate();
  const options = useApiQuery('rca-options', (signal) => fetchRcaOptions(signal));
  const query = new URLSearchParams();
  for (const key of FILTER_KEYS) {
    const v = params.get(key);
    if (v && key !== 'q' && key !== 'status') query.set(key, v);
  }
  const summary = useApiQuery(`rca-summary-${query}`, (signal) => fetchRcaSummary(query, signal));
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
      <Card className="gap-3 rounded-xl px-5 py-4">
        <div className="flex items-start gap-3">
          <span className="grid size-9 place-items-center rounded-lg bg-primary/10 text-primary"><ChartBar className="size-5" aria-hidden="true" /></span>
          <div>
            <h1 className="text-xl font-semibold tracking-tight">RCA Summary</h1>
            <p className="text-sm text-muted-foreground">RCA records stored in the database. Incident counts and outage minutes are shown separately: they rank causes differently.</p>
          </div>
        </div>
        {options.error && <Alert variant="destructive"><AlertDescription>{options.error.message}</AlertDescription></Alert>}
        {options.data && <ReportingDateSelect options={options.data} params={params} onChange={(from, to) => setParams((cur) => {
          const next = new URLSearchParams(cur);
          if (from) { next.set('date_from', from); next.set('date_to', to); } else { next.delete('date_from'); next.delete('date_to'); }
          return next;
        }, { replace: true })} />}
        {options.data && <RcaFilterBar options={options.data} params={params} onChange={onFilter} onReset={() => setParams(new URLSearchParams(), { replace: true })} />}
      </Card>

      {summary.error && <Alert variant="destructive"><AlertDescription>{summary.error.message}</AlertDescription></Alert>}
      {!s && !summary.error && <Skeleton className="h-96 w-full" />}
      {s && (
        <>
          {s.dates.length <= 1 && !query.get('date_from') && !query.get('date_to') && (
            <p className="flex items-center gap-2 rounded-lg border bg-muted/40 px-4 py-2 text-sm text-muted-foreground">
              <CalendarDays className="size-4 shrink-0" aria-hidden="true" />
              {s.dates.length ? `Single-date snapshot: ${formatDate(s.dates[0].date)}. Trends over time appear once RCA data for more reporting dates is imported.` : 'No RCA records match these filters.'}
            </p>
          )}
          {s.cycle && <CyclePanel cycle={s.cycle} />}
          <Kpis s={s} />
          {s.projects.length > 1 && <ProjectTable s={s} />}
          <div className="grid gap-5 xl:grid-cols-2">
            <ClassificationCard title="RCA classification: Final Bucket" items={s.final_buckets} field="final_bucket" onSelect={openRegister} />
            <ClassificationCard title="Secondary classification: Bucket - 2" items={s.bucket_2} field="bucket_2" onSelect={openRegister}
              scopeNote={s.kpis.rca_not_applicable.records ? `RCA-applicable records only: the ${formatNumber(s.kpis.rca_not_applicable.records)} ${s.kpis.rca_not_applicable.label} records are not included.` : undefined} />
          </div>
          <div className="grid gap-5 xl:grid-cols-2">
            <CircleCard circles={s.circles} populationSource={s.population_source} onSelect={(circle) => openRegister({ circle })} />
            <CategoryCard s={s} onSelect={(category) => openRegister({ category })} />
          </div>
          <TopRecords s={s} />
        </>
      )}
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
  const selected = options.months.find((m) => value === `month:${m.month}`);
  return (
    <div className="flex flex-wrap items-end gap-3">
      <Field id="rca-reporting-date" label="Reporting date" plain className="w-96 max-w-full">
        <SelectField id="rca-reporting-date" value={value} placeholder="Reporting date" options={choices} onChange={(v) => {
          if (v === 'all' || v === 'custom') onChange('', '');
          else if (v.startsWith('day:')) onChange(v.slice(4), v.slice(4));
          else onChange(...monthBounds(v.slice(6)));
        }} />
      </Field>
      <p className="pb-2 text-sm font-medium" aria-live="polite">
        {value === 'all' ? 'Showing every reporting date' : value.startsWith('day:') ? `Showing ${formatDate(from)}`
          : selected ? `Showing ${monthLabel(selected.month)}: the sum of ${selected.dates_with_records} reporting date${selected.dates_with_records === 1 ? '' : 's'} with records` : `Showing ${formatDate(from)} – ${formatDate(to)}`}
      </p>
    </div>
  );
}

/** The reporting period of the filtered dates (or the latest one): expected data received, pending, and its consolidated report. */
function CyclePanel({ cycle }: { cycle: RcaCycle & { matches_filter: boolean } }) {
  const st = cycle.status;
  const report = st.code === 'final' ? `Final report v${st.final_version}` : st.complete ? 'Draft report' : 'Partial report';
  return (
    <Card className="gap-1 rounded-xl px-4 py-3" aria-label="Reporting period">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <p className="flex flex-wrap items-center gap-2 text-sm font-medium">
          {cycle.matches_filter ? 'Reporting period' : 'Latest reporting period'} {cycle.period_label}{cycle.name ? ` · ${cycle.name}` : ''}
          <CycleBadge code={st.code} label={st.label} />
          {st.required > 0 && <span className="font-normal tabular-nums">{st.received} of {st.required} expected projects / circles have accepted data</span>}
        </p>
        <span className="flex gap-3 text-xs">
          <Link to={`/rca/submissions?cycle=${cycle.id}`} className="font-medium underline-offset-2 hover:underline">Open submissions →</Link>
          <a href={rcaCycleWorkbookUrl(cycle.id)} className="font-medium underline-offset-2 hover:underline">{report} (Excel)</a>
        </span>
      </div>
      {st.outstanding.length > 0 && (
        <p className="text-xs text-amber-800">Pending: {st.outstanding.map((o) => `${o.circle} ${shortProject(o.project)}`).join(', ')}. The figures cover the accepted records only.</p>
      )}
      {!cycle.matches_filter && <p className="text-xs text-muted-foreground">The figures below follow the filters above, not only this period.</p>}
    </Card>
  );
}

function ProjectTable({ s }: { s: RcaSummary }) {
  return (
    <Card className="gap-2 rounded-xl px-4 py-3" aria-label="Project-wise summary">
      <p className="text-sm font-medium">Project-wise</p>
      <Table>
        <TableHeader>
          <TableRow>{['Project', 'Records', 'Outage minutes', 'Affected sites', 'Other Media (RCA not applicable)', 'RCA required — missing information'].map((h) => <TableHead key={h}>{h}</TableHead>)}</TableRow>
        </TableHeader>
        <TableBody>
          {s.projects.map((p) => (
            <TableRow key={p.project}>
              <TableCell className="font-medium">{p.project}</TableCell>
              <TableCell className="tabular-nums">{formatNumber(p.records)}</TableCell>
              <TableCell className="tabular-nums">{formatMin(p.outage_minutes)}</TableCell>
              <TableCell className="tabular-nums">{formatNumber(p.affected_sites)}</TableCell>
              <TableCell className="tabular-nums">{formatNumber(p.rca_not_applicable)}</TableCell>
              <TableCell className="tabular-nums">{formatNumber(p.incomplete_records)}</TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </Card>
  );
}

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
  const na = k.rca_not_applicable;
  const incompleteParts = [
    k.incomplete_by_field.final_bucket && `Final Bucket ${formatNumber(k.incomplete_by_field.final_bucket)}`,
    k.incomplete_by_field.bucket_2 && `Bucket - 2 ${formatNumber(k.incomplete_by_field.bucket_2)}`,
    k.incomplete_by_field.rca && `RCA ${formatNumber(k.incomplete_by_field.rca)}`,
  ].filter(Boolean).join(' · ');
  return (
    <section className="grid gap-3 sm:grid-cols-2 xl:grid-cols-5" aria-label="RCA summary KPIs">
      {card('Total RCA records', formatNumber(k.records), 'Incidents with an RCA in the filter')}
      {card('Distinct affected sites', formatNumber(k.affected_sites), 'Sites with at least one RCA record')}
      {card('Total recorded outage', k.outage_minutes == null ? 'Not recorded' : `${formatNumber(Math.round(k.outage_minutes))} min`,
        k.records_with_minutes === k.records ? 'Outage Min. of every record' : `From ${formatNumber(k.records_with_minutes)} records with a value`)}
      {card(k.missing_label, formatNumber(k.incomplete_records),
        `Of ${formatNumber(k.rca_applicable_records)} RCA-applicable records${k.completeness_pct == null ? '' : ` · ${k.completeness_pct.toFixed(1)}% complete`}${incompleteParts ? ` · blank or "-": ${incompleteParts}` : ''}`,
        k.incomplete_records ? 'text-amber-700' : undefined, k.incomplete_records ? '/rca?rca=missing' : undefined)}
      {card(na.label, formatNumber(na.records),
        `Final Bucket "${na.final_buckets.join('", "')}": kept separate, not counted as missing${na.blank_bucket_2 ? ` (${formatNumber(na.blank_bucket_2)} have Bucket - 2 "-")` : ''}`,
        'text-muted-foreground', na.records ? '/rca?rca=not_applicable' : undefined)}
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
