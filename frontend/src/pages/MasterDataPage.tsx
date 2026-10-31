import { useEffect, useState } from 'react';
import { Link, Navigate, useLocation, useSearchParams } from 'react-router-dom';
import { Download, RotateCcw, Search } from 'lucide-react';
import { Alert, AlertDescription } from '@/components/ui/alert';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Skeleton } from '@/components/ui/skeleton';
import { cn } from '@/lib/utils';
import { SelectField } from '../components/data/DataEntry';
import { Field, FilterCard } from '../components/dashboard/FilterBar';
import { DataGrid } from '../components/masterdata/DataGrid';
import { Segmented } from '../components/rca/RcaShared';
import { PageHeading } from '../context/pageHeader';
import { useApiQuery } from '../hooks/useApiQuery';
import { formatDate } from '../lib/format';
import { fetchMasterDatasets, fetchMasterOptions, fetchMasterRecords, masterExportUrl } from '../services/api';
import type { MasterDataset, MasterDatasets, MasterOptions } from '../types/masterData';

/** The tabs: one sidebar entry (Master Data), one URL per tab. A new dataset is a new tab here plus its server registration. */
const TABS = [
  { path: '/master-data', label: 'Uptime Master' },
  { path: '/master-data/escalation', label: 'CI-wise Consolidation & Escalation Matrix' },
  { path: '/master-data/rca', label: 'RCA Data' },
];
type Period = 'daily' | 'weekly' | 'monthly' | 'overall';
const PERIODS: [Period, string][] = [['daily', 'Daily'], ['weekly', 'Weekly'], ['monthly', 'Monthly'], ['overall', 'Overall']];
const ALL = '__all__';
const MONTHS = Array.from({ length: 12 }, (_, i) => ({ value: String(i + 1), label: new Date(2000, i, 1).toLocaleDateString('en-IN', { month: 'long' }) }));
/** Query keys that only shape the view (not filters): kept apart when resetting. */
const VIEW_KEYS = ['view'];

/** The dataset shown: the tab, and for Uptime Master the view (Site Master or Daily Performance; Monthly reads the monthly records). */
function datasetKey(path: string, params: URLSearchParams) {
  if (path === '/master-data/escalation') return 'escalation';
  if (path === '/master-data/rca') return 'rca';
  if (params.get('view') !== 'performance') return 'uptime_sites';
  return params.get('period') === 'monthly' ? 'uptime_monthly' : 'uptime_daily';
}

/**
 * Master Data: the central, read-only explorer of the business datasets stored in PostgreSQL. Filters sit in the
 * portal's filter card, kept in the URL (so they survive navigation); records are filtered, sorted and paged by the
 * server, which also limits CI users to their projects and circles and hides phone numbers from non-Admins.
 */
export function MasterDataPage() {
  const location = useLocation();
  const [params, setParams] = useSearchParams();
  const path = location.pathname.replace(/\/+$/, '') || '/master-data';
  const tab = TABS.find((t) => t.path === path);
  const meta = useApiQuery('master-datasets', fetchMasterDatasets);
  const key = datasetKey(path, params);
  const ds = meta.data?.datasets.find((d) => d.key === key);
  const options = useApiQuery(ds ? `master-options|${key}|${params.get('project') ?? ''}` : null,
    (signal) => fetchMasterOptions(key, new URLSearchParams(params.get('project') ? { project: params.get('project')! } : {}), signal));
  if (!tab) return <Navigate to="/master-data" replace />;

  const set = (changes: Record<string, string | null>) => setParams((cur) => {
    const next = new URLSearchParams(cur);
    for (const [k, v] of Object.entries(changes)) { if (v) next.set(k, v); else next.delete(k); }
    if (!('page' in changes)) next.delete('page');  // a new filter starts at page 1
    return next;
  }, { replace: true });

  return (
    <div className="space-y-4">
      <PageHeading title="Master Data" subtitle="Central database explorer: the business data stored in PostgreSQL, read only. Search, filter and export each dataset." />
      <nav aria-label="Master Data datasets" className="flex flex-wrap gap-1 rounded-xl border bg-card p-1 shadow-xs">
        {TABS.map((t) => (
          <Link key={t.path} to={t.path} aria-current={t === tab ? 'page' : undefined}
            className={cn('rounded-lg px-3 py-1.5 text-sm font-medium transition-colors focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none',
              t === tab ? 'bg-primary text-primary-foreground' : 'text-muted-foreground hover:bg-muted hover:text-foreground')}>
            {t.label}
          </Link>
        ))}
      </nav>
      {meta.error && <Alert variant="destructive"><AlertDescription>{meta.error.message}</AlertDescription></Alert>}
      {!ds || !meta.data ? !meta.error && <Skeleton className="h-96 w-full" /> : (
        <DatasetView key={key} ds={ds} meta={meta.data} options={options.data} params={params} set={set}
          showView={path === '/master-data'} reset={() => setParams(new URLSearchParams(VIEW_KEYS.flatMap((k) => (params.get(k) ? [[k, params.get(k)!]] : []))), { replace: true })} />
      )}
    </div>
  );
}

/** The request parameters of a dataset: the URL's filters plus the period defaults (the latest month with data). */
function effectiveParams(ds: MasterDataset, options: MasterOptions | null, params: URLSearchParams) {
  const out = new URLSearchParams();
  for (const [k, v] of params) if (!VIEW_KEYS.includes(k) && k !== 'cols') out.set(k, v);
  if (ds.time) {
    const period = (params.get('period') as Period) || 'daily';
    out.set('period', period);
    const latest = options?.months?.at(-1);
    if (period !== 'overall' && !params.get('year') && latest) out.set('year', String(latest.year));
    if ((period === 'daily' || period === 'weekly') && !params.get('month') && latest) out.set('month', String(latest.month));
  } else {
    for (const k of ['period', 'year', 'month', 'date', 'week', 'month_from', 'month_to', 'date_from', 'date_to']) out.delete(k);
  }
  return out;
}

function DatasetView({ ds, meta, options, params, set, reset, showView }: {
  ds: MasterDataset; meta: MasterDatasets; options: MasterOptions | null; params: URLSearchParams; showView: boolean;
  set: (changes: Record<string, string | null>) => void; reset: () => void;
}) {
  const query = effectiveParams(ds, options, params);
  const records = useApiQuery(options || !ds.time ? `master-records|${ds.key}|${query}` : null, (signal) => fetchMasterRecords(ds.key, query, signal));
  const [visible, setVisible] = useState(() => ds.columns.filter((c) => !c.hidden).map((c) => c.key));
  const [resets, setResets] = useState(0);  // remounts the text filters after a reset (they keep their own typing state)
  const exportParams = new URLSearchParams(query);
  exportParams.set('columns', visible.join(','));
  const period = (query.get('period') as Period) || 'daily';
  const years = [...new Set((options?.months ?? []).map((m) => m.year))].sort();
  const monthsOfYear = (options?.months ?? []).filter((m) => String(m.year) === query.get('year')).map((m) => MONTHS[m.month - 1]);
  const ym = `${query.get('year')}-${String(query.get('month')).padStart(2, '0')}`;
  const datesOfMonth = (options?.dates ?? []).filter((d) => d.startsWith(ym));
  const active = [...params.keys()].some((k) => !VIEW_KEYS.includes(k) && !['page', 'page_size', 'sort'].includes(k));
  const select = (k: string, label: string, all: string, items: { value: string; label: string }[], width = 'w-36') => (
    <Field key={k} id={`md-${k}`} label={label} className={width}>
      <SelectField id={`md-${k}`} value={params.get(k) || ALL} placeholder={all} options={[{ value: ALL, label: all }, ...items]}
        onChange={(v) => set({ [k]: v === ALL ? null : v, ...(k === 'project' ? { circle: null } : {}) })} />
    </Field>
  );
  return (
    <>
      <FilterCard label="Master Data filters"
        actions={<Button type="button" variant="ghost" size="icon" className="size-9" aria-label="Reset filters" title="Reset filters" disabled={!active} onClick={() => { reset(); setResets((n) => n + 1); }}><RotateCcw /></Button>}
        footer={ds.description}>
        {showView && (
          <Field id="md-view" label="View" className="w-auto">
            <Segmented label="Uptime Master view" value={params.get('view') === 'performance' ? 'performance' : 'sites'}
              onChange={(v) => set({ view: v === 'sites' ? null : v, period: null })} options={[['sites', 'Site Master'], ['performance', 'Daily Performance']]} />
          </Field>
        )}
        {ds.time ? (
          <Field id="md-period" label="Period" className="w-auto">
            <Segmented label="Period" value={period} onChange={(v) => set({ period: v, date: null, week: null })} options={PERIODS} />
          </Field>
        ) : null}
        {(ds.time && period !== 'overall') && select('year', 'Year', 'Latest', years.map((y) => ({ value: String(y), label: String(y) })), 'w-28')}
        {ds.time && (period === 'daily' || period === 'weekly') && select('month', 'Month', 'Latest', monthsOfYear, 'w-36')}
        {ds.time && period === 'daily' && datesOfMonth.length > 0 && select('date', 'Date', 'Every date', datesOfMonth.map((d) => ({ value: d, label: formatDate(d) })), 'w-36')}
        {ds.time && period === 'weekly' && select('week', 'Week', 'Week 1', meta.weeks.map((w) => ({ value: String(w.value), label: w.label })), 'w-52')}
        {ds.time && period === 'monthly' && select('month_from', 'From month', 'January', MONTHS, 'w-32')}
        {ds.time && period === 'monthly' && select('month_to', 'To month', 'December', MONTHS, 'w-32')}
        {ds.time && period === 'overall' && ['date_from', 'date_to'].map((k) => (
          <Field key={k} id={`md-${k}`} label={k === 'date_from' ? 'From' : 'To'} className="w-36">
            <Input id={`md-${k}`} type="date" className="h-9" value={params.get(k) ?? ''} onChange={(e) => set({ [k]: e.target.value || null })} />
          </Field>
        ))}
        {select('project', 'Project', 'All projects', (options?.projects ?? []).map((p) => ({ value: p, label: p })), 'w-36')}
        {select('circle', 'Circle', 'All circles', (options?.circles ?? []).map((c) => ({ value: c, label: c })), 'w-32')}
        {ds.filters.choices.map((c) => select(c.key, c.label, `All`, (options?.choices[c.key] ?? []).map((v) => ({ value: v, label: v === 'True' ? 'Yes' : v === 'False' ? 'No' : v })), 'w-40'))}
        {ds.filters.site && <TextFilter key={`site_id${resets}`} id="site_id" label="Site ID" value={params.get('site_id')} onChange={(v) => set({ site_id: v })} />}
        {ds.filters.site && <TextFilter key={`site_name${resets}`} id="site_name" label="Site name" value={params.get('site_name')} onChange={(v) => set({ site_name: v })} />}
        <TextFilter key={`q${resets}`} id="q" label="Search" value={params.get('q')} onChange={(v) => set({ q: v })} search />
      </FilterCard>
      <DataGrid title={ds.label} columns={ds.columns} visible={visible} onVisible={setVisible} page={records.data} loading={records.loading} error={records.error}
        sort={params.get('sort') ?? ''} onSort={(s) => set({ sort: s })} pageSizes={meta.page_sizes}
        onPage={(p) => set({ page: String(p) })} onPageSize={(n) => set({ page_size: String(n) })}
        actions={(
          <>
            <Button asChild size="sm" variant="outline" className="h-8"><a href={masterExportUrl(ds.key, new URLSearchParams([...exportParams, ['file', 'csv']]))}><Download /> CSV</a></Button>
            <Button asChild size="sm" variant="outline" className="h-8"><a href={masterExportUrl(ds.key, new URLSearchParams([...exportParams, ['file', 'xlsx']]))}><Download /> Excel</a></Button>
          </>
        )} />
    </>
  );
}

/** A text filter applied after a short pause in typing (one request, not one per key). */
function TextFilter({ id, label, value, onChange, search }: { id: string; label: string; value: string | null; onChange: (v: string | null) => void; search?: boolean }) {
  const [text, setText] = useState(value ?? '');
  useEffect(() => {
    if (text === (value ?? '')) return undefined;
    const t = setTimeout(() => onChange(text.trim() || null), 400);
    return () => clearTimeout(t);
  }, [text]);  // eslint-disable-line react-hooks/exhaustive-deps
  return (
    <Field id={`md-${id}`} label={label} className={search ? 'w-56' : 'w-36'}>
      <div className="relative">
        {search && <Search className="absolute top-1/2 left-2.5 size-4 -translate-y-1/2 text-muted-foreground" aria-hidden="true" />}
        <Input id={`md-${id}`} value={text} onChange={(e) => setText(e.target.value)} className={cn('h-9', search && 'pl-8')} placeholder={search ? 'Search the records' : ''} />
      </div>
    </Field>
  );
}
