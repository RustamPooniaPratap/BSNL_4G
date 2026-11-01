import { useMemo, useState } from 'react';
import { Link, useLocation, useSearchParams } from 'react-router-dom';
import { ArrowDown, ArrowUp, ArrowUpDown, Database, FileUp, Info, Search } from 'lucide-react';
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert';
import { Button, buttonVariants } from '@/components/ui/button';
import { Card } from '@/components/ui/card';
import { Input } from '@/components/ui/input';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import { Skeleton } from '@/components/ui/skeleton';
import { cn } from '@/lib/utils';
import { ChartCard } from '../components/dashboard/ChartCard';
import { Field, FilterBar } from '../components/dashboard/FilterBar';
import { useWorkbook } from '../context/workbook';
import { useApiQuery } from '../hooks/useApiQuery';
import { useDashboardFilters } from '../hooks/useDashboardFilters';
import { formatDate, formatNumber, formatPct } from '../lib/format';
import { teamSitesLink, UNASSIGNED } from '../lib/teams';
import { fetchFilterOptions, fetchTeamMonthly } from '../services/api';
import type { NslaValue, TeamGroup, TeamMonthlyResponse, TeamMonthlyRow } from '../types';

const GROUP_LABELS: Record<TeamGroup, { one: string; many: string }> = {
  ci: { one: 'CI', many: 'CIs' },
  ie: { one: 'IE', many: 'IEs' },
};

/** Sort by name (default, A–Z), assigned sites, or a month's NSLA sites / %. Never a ranking by default. */
type SortKey = 'name' | 'sites' | `${string}:nsla_sites` | `${string}:nsla_pct`;

const projectLabel = (type: string) => (type === '4G Saturation' ? '4G' : type);

export function CiIePerformancePage() {
  const workbook = useWorkbook();
  const { version } = workbook;
  const options = useApiQuery(workbook.active ? `${version}|filters` : null, fetchFilterOptions);
  // NSLA is the O&M Start penalty threshold, so this page starts on the O&M Start scope (as Threshold Analysis).
  const { filters, setFilters, reset, isDefault } = useDashboardFilters(options.data, { defaultScope: 'om_start' });
  const [searchParams, setSearchParams] = useSearchParams();
  const location = useLocation();
  const group: TeamGroup = searchParams.get('group') === 'ie' ? 'ie' : 'ci';
  const month = searchParams.get('month') ?? '';
  const setParam = (key: string, value: string | null) => setSearchParams((current) => {
    const next = new URLSearchParams(current);
    if (value) next.set(key, value);
    else next.delete(key);
    return next;
  }, { replace: true });

  const query = useMemo(() => {
    if (!filters) return null;
    // The month is the period: the backend uses the latest reported date for the current month to date.
    const q = new URLSearchParams(filters.snapshotParams);
    q.delete('reporting_date');
    q.set('group', group);
    if (month) q.set('month', month);
    return q;
  }, [filters, group, month]);
  const result = useApiQuery(query ? `${version}|teams-monthly|${query}` : null, (signal) => fetchTeamMonthly(query!, signal));
  // Months with data for this selection (the query keeps the previous answer while a new one loads).
  const months = result.data?.months_available ?? [];

  if (!workbook.loading && !workbook.error && !workbook.active) {
    return (
      <Card className="mx-auto mt-10 max-w-xl items-center gap-3 px-8 py-10 text-center">
        <FileUp className="size-8 text-muted-foreground" aria-hidden="true" />
        <h1 className="text-lg font-semibold">No Master workbook loaded</h1>
        <p className="text-sm text-muted-foreground">Upload the consolidated workbook to see CI and IE performance.</p>
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
        <AlertDescription>{fatal.message}</AlertDescription>
      </Alert>
    );
  }
  if (!options.data || !filters) {
    return <Skeleton className="h-96 w-full" aria-label="Loading CI and IE performance" />;
  }

  const latest = months[months.length - 1]?.key;
  const selectedMonth = month || result.data?.reporting_month || latest || '';

  return (
    <div className="space-y-4">
      <FilterBar options={options.data} filters={filters} onChange={setFilters}
        canReset={!isDefault || !!month || group !== 'ci'} onReset={reset} showTrendRange={false} showDate={false}
        title="CI & IE Performance"
        description="Review assigned-site NSLA performance and RCA-wise data for CI and IE personnel."
        extra={(
          <>
            <Field id="filter-view-by" label="View by" className="w-28">
              <Select value={group} onValueChange={(v) => setParam('group', v === 'ci' ? null : v)}>
                <SelectTrigger id="filter-view-by" className="h-9 w-full"><SelectValue /></SelectTrigger>
                <SelectContent>
                  <SelectItem value="ci">CI</SelectItem>
                  <SelectItem value="ie">IE</SelectItem>
                </SelectContent>
              </Select>
            </Field>
            <Field id="filter-month" label="Reporting month" className="w-48">
              <Select value={selectedMonth} onValueChange={(v) => setParam('month', v === latest ? null : v)} disabled={!months.length}>
                <SelectTrigger id="filter-month" className="h-9 w-full"><SelectValue placeholder="No months" /></SelectTrigger>
                <SelectContent>
                  {[...months].reverse().map((m) => (
                    <SelectItem key={m.key} value={m.key}>{m.label}{m.key === latest ? ' (latest)' : ''}</SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </Field>
          </>
        )} />

      {result.error && month ? (
        <Alert variant="destructive">
          <Database />
          <AlertTitle>No data for this month in the selection</AlertTitle>
          <AlertDescription className="flex flex-wrap items-center gap-3">
            {result.error.message}
            <Button size="sm" variant="outline" onClick={() => setParam('month', null)}>Show the latest month</Button>
          </AlertDescription>
        </Alert>
      ) : (
        <NslaTable key={group} data={result.data} loading={result.loading} error={result.error} group={group}
          initialSearch={searchParams.get('q') ?? ''}
          sitesLink={(r) => teamSitesLink(group, r, { scope: filters.scope, back: `${location.pathname}${location.search}`,
            month: result.data?.reporting_month && result.data.reporting_month !== latest ? result.data.reporting_month : undefined })} />
      )}
    </div>
  );
}

function NslaTable({ data, loading, error, group, initialSearch = '', sitesLink }: {
  data: TeamMonthlyResponse | null; loading: boolean; error: Error | null; group: TeamGroup; initialSearch?: string;
  /** The person's assigned sites on Uptime Buckets & Site Details. */
  sitesLink: (row: TeamMonthlyRow) => string;
}) {
  const [search, setSearch] = useState(initialSearch);
  const [sort, setSort] = useState<{ key: SortKey; desc: boolean }>({ key: 'name', desc: false });
  const labels = GROUP_LABELS[group];
  const months = data?.months ?? [];
  const current = months[months.length - 1];
  const history = months.slice(0, -1);

  const needle = search.trim().toLowerCase();
  const rows = useMemo(() => {
    const list = (data?.rows ?? []).filter((r) => !needle || r.name.toLowerCase().includes(needle));
    if (sort.key === 'name') return sort.desc ? [...list].reverse() : list;  // the backend's name order
    const [monthKey, field] = sort.key.split(':') as [string, keyof NslaValue | undefined];
    const value = (r: TeamMonthlyRow) => (field ? r.months[monthKey]?.[field] ?? null : r.sites_in_scope);
    return [...list].sort((a, b) => {
      const [x, y] = [value(a), value(b)];
      if (x == null || y == null) return x == null ? (y == null ? 0 : 1) : -1;  // no value always last
      return sort.desc ? y - x : x - y;
    });
  }, [data, needle, sort]);

  const header = (key: SortKey, label: React.ReactNode, className?: string, title?: string) => {
    const active = sort.key === key;
    return (
      <th key={key} scope="col" className={cn('px-2.5 py-2 text-right font-medium whitespace-nowrap', className)} title={title}
        aria-sort={active ? (sort.desc ? 'descending' : 'ascending') : undefined}>
        <button type="button" onClick={() => setSort((s) => ({ key, desc: s.key === key ? !s.desc : key !== 'name' }))}
          className="inline-flex items-center gap-1 rounded hover:text-foreground focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none">
          {label}
          {active ? (sort.desc ? <ArrowDown className="size-3" /> : <ArrowUp className="size-3" />) : <ArrowUpDown className="size-3 opacity-40" />}
        </button>
      </th>
    );
  };
  const noValueNote = (v: NslaValue | null) => (v == null ? 'No site reported' : v.no_value ? `${formatNumber(v.no_value)} site(s) with no value` : undefined);
  const sticky = 'sticky left-0 z-10 bg-card';

  return (
    <ChartCard
      title={`${labels.one}-wise NSLA`}
      description={data && current
        ? `NSLA = sites below 98.5% uptime; % of the assigned sites in scope. ${current.kind === 'mtd'
          ? `${current.label} to ${formatDate(data.reporting_date)}` : current.label}; earlier months from the source's monthly outage.`
        : `Sites below 98.5% uptime among those assigned to each ${labels.one}`}
      action={(
        <div className="relative">
          <Search className="pointer-events-none absolute top-1/2 left-2.5 size-3.5 -translate-y-1/2 text-muted-foreground" aria-hidden="true" />
          <Input type="search" value={search} onChange={(e) => setSearch(e.target.value)} placeholder={`Search ${labels.one} name`}
            aria-label={`Search ${labels.many} by name`} className="h-8 w-52 pl-8" maxLength={60} />
        </div>
      )}
      loading={loading && !data}
      error={error}
      empty={!rows.length || !current}
      emptyMessage={!current ? 'No month with reported data for the selected filters.'
        : needle ? `No ${labels.one} matches “${search}”.` : `No ${labels.many} are assigned to sites in the selected filters.`}
      bodyClassName="px-0"
    >
      {current && (
        <div className="max-h-[36rem] overflow-auto" role="region" aria-label={`${labels.one}-wise NSLA table`} tabIndex={0}>
          <table className="w-full border-separate border-spacing-0 text-xs tabular-nums">
            <thead className="sticky top-0 z-20 bg-card text-muted-foreground [&_th]:border-b [&_th]:bg-muted/50">
              <tr>
                {header('name', labels.one, cn(sticky, 'z-30 min-w-44 text-left'))}
                <th scope="col" className="px-2.5 py-2 text-left font-medium">Circle</th>
                <th scope="col" className="px-2.5 py-2 text-left font-medium">Project</th>
                {header('sites', 'Assigned sites', undefined, 'Sites in scope with this person named on the Up-Time Report')}
                {header(`${current.key}:nsla_sites`, <>NSLA sites <span className="font-normal">· {current.label}</span></>, 'border-l')}
                {header(`${current.key}:nsla_pct`, 'NSLA %')}
                {history.map((m) => header(`${m.key}:nsla_sites`, m.label, m === history[0] ? 'border-l' : undefined, `${m.label}: NSLA sites (NSLA %)`))}
              </tr>
            </thead>
            <tbody>
              {rows.map((r) => (
                <tr key={`${r.report_type}|${r.circle}|${r.name}`} className="hover:bg-muted/40 [&_td]:border-b [&_th]:border-b">
                  <th scope="row" className={cn(sticky, 'max-w-56 truncate px-2.5 py-1.5 text-left font-medium', r.name === UNASSIGNED && 'text-muted-foreground italic')} title={r.name}>
                    {r.name === UNASSIGNED ? r.name : (
                      <Link to={sitesLink(r)} className="text-primary underline-offset-4 hover:underline focus-visible:underline"
                        aria-label={`Sites of ${r.name} (${projectLabel(r.report_type)} ${r.circle})`}>{r.name}</Link>
                    )}
                  </th>
                  <td className="px-2.5 py-1.5">{r.circle}</td>
                  <td className="px-2.5 py-1.5">{projectLabel(r.report_type)}</td>
                  <td className="px-2.5 py-1.5 text-right">{formatNumber(r.sites_in_scope)}</td>
                  <td className="border-l px-2.5 py-1.5 text-right font-medium" title={noValueNote(r.months[current.key])}>
                    {formatNumber(r.months[current.key]?.nsla_sites)}
                  </td>
                  <td className="px-2.5 py-1.5 text-right" title={noValueNote(r.months[current.key])}>{formatPct(r.months[current.key]?.nsla_pct, 1)}</td>
                  {history.map((m) => {
                    const v = r.months[m.key];
                    return (
                      <td key={m.key} className={cn('px-2.5 py-1.5 text-right whitespace-nowrap', m === history[0] && 'border-l')} title={noValueNote(v)}>
                        {v == null ? '—' : <>{formatNumber(v.nsla_sites)} <span className="text-muted-foreground">({formatPct(v.nsla_pct, 1)})</span></>}
                      </td>
                    );
                  })}
                </tr>
              ))}
            </tbody>
            {data && (
              <tfoot className="font-semibold [&_td]:bg-muted/50 [&_th]:bg-muted/50">
                <tr>
                  <th scope="row" className={cn(sticky, 'px-2.5 py-1.5 text-left')}>All sites in selection</th>
                  <td className="px-2.5 py-1.5" colSpan={2} />
                  <td className="px-2.5 py-1.5 text-right">{formatNumber(data.totals.sites_in_scope)}</td>
                  <td className="border-l px-2.5 py-1.5 text-right">{formatNumber(data.totals.months[current.key]?.nsla_sites)}</td>
                  <td className="px-2.5 py-1.5 text-right">{formatPct(data.totals.months[current.key]?.nsla_pct, 1)}</td>
                  {history.map((m) => {
                    const v = data.totals.months[m.key];
                    return (
                      <td key={m.key} className={cn('px-2.5 py-1.5 text-right whitespace-nowrap', m === history[0] && 'border-l')} title={noValueNote(v)}>
                        {v == null ? '—' : <>{formatNumber(v.nsla_sites)} <span className="font-normal text-muted-foreground">({formatPct(v.nsla_pct, 1)})</span></>}
                      </td>
                    );
                  })}
                </tr>
              </tfoot>
            )}
          </table>
        </div>
      )}
      <div className="space-y-1 border-t px-4 pt-2.5 text-xs text-muted-foreground">
        <p>
          {formatNumber(rows.length)} of {formatNumber(data?.rows.length ?? 0)} rows, in name order · a {labels.one} working in two circles or
          projects appears once for each · “—” means no site reported (not zero)
        </p>
        {data?.unsupported.map((u) => (
          <p key={u.field} className="flex items-start gap-1.5"><Info className="mt-px size-3.5 shrink-0" aria-hidden="true" />
            <span><span className="font-medium text-foreground">{u.field}</span> are not shown: {u.reason}</span></p>
        ))}
      </div>
    </ChartCard>
  );
}
