import { useMemo, useRef, useState } from 'react';
import { Link, useSearchParams } from 'react-router-dom';
import { ArrowDown, ArrowUp, ArrowUpDown, Database, FileUp, Search } from 'lucide-react';
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert';
import { buttonVariants } from '@/components/ui/button';
import { Card } from '@/components/ui/card';
import { Input } from '@/components/ui/input';
import { Skeleton } from '@/components/ui/skeleton';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table';
import { cn } from '@/lib/utils';
import { ChartCard } from '../components/dashboard/ChartCard';
import { BUCKET_COLORS, BUCKET_LABELS, BUCKET_ORDER } from '../components/dashboard/constants';
import { FilterBar } from '../components/dashboard/FilterBar';
import { SiteDetailSheet } from '../components/dashboard/SiteDetailSheet';
import { SiteTable } from '../components/dashboard/SiteTable';
import { useWorkbook } from '../context/workbook';
import { useApiQuery } from '../hooks/useApiQuery';
import { useFilterOptions } from '../hooks/useFilterOptions';
import { useDashboardFilters } from '../hooks/useDashboardFilters';
import { formatDate, formatMinutes, formatNumber, formatPct } from '../lib/format';
import { UNASSIGNED } from '../lib/teams';
import { fetchTeams } from '../services/api';
import type { BucketId, SiteRecord, TeamGroup, TeamRow, TeamsResponse } from '../types';
import { populationSites } from '../lib/population';

const GROUP_LABELS: Record<TeamGroup, { one: string; many: string; linked: string }> = {
  ci: { one: 'CI', many: 'CIs', linked: 'IEs' },
  ie: { one: 'IE', many: 'IEs', linked: 'Reports to (CI)' },
};

type SortKey = 'mtd_uptime_pct' | 'sites_below_60_mtd' | 'sites_in_scope' | 'name';
// The site list defaults to "below 60%" (who is responsible); "all" shows every bucket.
const ALL_BUCKETS = 'all';

export function TeamsPage() {
  const workbook = useWorkbook();
  const { version } = workbook;
  const options = useFilterOptions();
  const { filters, setFilters, reset, isDefault } = useDashboardFilters(options.data);
  const [searchParams, setSearchParams] = useSearchParams();

  const group: TeamGroup = searchParams.get('group') === 'ie' ? 'ie' : 'ci';
  const team = searchParams.get('team') ?? '';
  const bucketParam = searchParams.get('bucket') ?? 'lt_60';
  const bucket: BucketId | '' = (BUCKET_ORDER as string[]).includes(bucketParam) ? (bucketParam as BucketId) : '';
  const setParams = (changes: Record<string, string | null>) => setSearchParams((current) => {
    const next = new URLSearchParams(current);
    for (const [key, value] of Object.entries(changes)) {
      if (value) next.set(key, value);
      else next.delete(key);
    }
    return next;
  }, { replace: true });

  const [selectedSite, setSelectedSite] = useState<SiteRecord | null>(null);
  const sitesRef = useRef<HTMLDivElement>(null);
  const selectTeam = (name: string) => {
    setParams({ team: name === team ? null : name });
    if (name !== team) sitesRef.current?.scrollIntoView({ behavior: 'smooth', block: 'start' });
  };

  const query = useMemo(() => {
    if (!filters) return null;
    const q = new URLSearchParams(filters.snapshotParams);
    q.set('group', group);
    return q;
  }, [filters, group]);
  const teams = useApiQuery(query ? `${version}|teams|${query}` : null, (signal) => fetchTeams(query!, signal));

  if (!workbook.loading && !workbook.error && !workbook.active) {
    return (
      <Card className="mx-auto mt-10 max-w-xl items-center gap-3 px-8 py-10 text-center">
        <FileUp className="size-8 text-muted-foreground" aria-hidden="true" />
        <h1 className="text-lg font-semibold">No reporting data loaded</h1>
        <p className="text-sm text-muted-foreground">Import the reporting data (Data Source page) to see team performance.</p>
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
  if (!options.data || !filters) {
    return <Skeleton className="h-96 w-full" aria-label="Loading team performance" />;
  }

  const labels = GROUP_LABELS[group];
  const scopeLabel = populationSites(filters.scope);
  const siteTitle = team
    ? `Sites of ${labels.one} ${team}`
    : bucket === 'lt_60' ? 'Sites below 60% MTD and who is responsible' : 'Sites and who is responsible';

  return (
    <div className="space-y-3">

      <FilterBar options={options.data} filters={filters} onChange={setFilters} canReset={!isDefault}
        onReset={reset} showTrendRange={false}
        title="Team performance"
        description={<>
          {options.data.month.label} · {[filters.reportType || 'All projects', filters.circle ? `Circle ${filters.circle}` : 'All circles', `Population: ${scopeLabel}`].join(' · ')}
          {' '}· each site is the responsibility of the CI and IE named on its row in the workbook
        </>}
        actions={(
        <div className="inline-flex rounded-lg border p-0.5" role="group" aria-label="Group by">
          {(['ci', 'ie'] as TeamGroup[]).map((g) => (
            <button
              key={g}
              type="button"
              aria-pressed={group === g}
              onClick={() => setParams({ group: g === 'ci' ? null : g, team: null })}
              className={cn('rounded-md px-3 py-1 text-xs font-medium transition-colors focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none',
                group === g ? 'bg-primary text-primary-foreground' : 'text-muted-foreground hover:text-foreground')}
            >
              By {GROUP_LABELS[g].one}
            </button>
          ))}
        </div>
        )} />

      {teams.error ? (
        <Alert variant="destructive"><Database /><AlertTitle>Team performance unavailable</AlertTitle><AlertDescription>{teams.error.message}</AlertDescription></Alert>
      ) : (
        <TeamKpis data={teams.data} loading={teams.loading} group={group} onSelectTeam={selectTeam} />
      )}

      <TeamRanking key={group} data={teams.data} loading={teams.loading} error={teams.error} group={group} selected={team} onSelect={selectTeam} />

      <div ref={sitesRef} className="scroll-mt-20">
        <SiteTable
          params={filters.snapshotParams}
          version={version}
          bucket={bucket}
          onBucketChange={(id) => setParams({ bucket: id || ALL_BUCKETS })}
          onSelectSite={setSelectedSite}
          team={team ? { group, name: team } : null}
          onClearTeam={() => setParams({ team: null })}
          title={siteTitle}
        />
      </div>

      <SiteDetailSheet site={selectedSite} onClose={() => setSelectedSite(null)} />
    </div>
  );
}

function TeamKpis({ data, loading, group, onSelectTeam }: {
  data: TeamsResponse | null; loading: boolean; group: TeamGroup; onSelectTeam: (name: string) => void;
}) {
  if (loading && !data) {
    return <div className="grid grid-cols-2 gap-2.5 xl:grid-cols-5">{Array.from({ length: 5 }, (_, i) => <Skeleton key={i} className="h-20" />)}</div>;
  }
  if (!data) return null;
  const labels = GROUP_LABELS[group];
  const t = data.totals;
  const ranked = data.teams.filter((row) => row.name !== UNASSIGNED && row.mtd_uptime_pct != null);
  const worst = ranked[0];
  const share = t.sites_in_scope ? (100 * t.sites_below_60_mtd) / t.sites_in_scope : 0;
  return (
    <div className="grid grid-cols-2 gap-2.5 xl:grid-cols-5">
      <Kpi label={labels.many} value={formatNumber(t.teams)} detail={`${formatNumber(t.sites_in_scope)} sites in scope`} />
      <Kpi label={`${labels.many} with sites below 60%`} value={formatNumber(t.teams_with_sites_below_60)}
        detail={t.teams ? `${((100 * t.teams_with_sites_below_60) / t.teams).toFixed(0)}% of ${labels.many}` : '—'} tone={t.teams_with_sites_below_60 ? 'bad' : undefined} />
      <Kpi label="Sites below 60% MTD" value={formatNumber(t.sites_below_60_mtd)} detail={`${share.toFixed(1)}% of sites in scope`} tone={t.sites_below_60_mtd ? 'bad' : undefined} />
      <Kpi label={`Lowest MTD ${labels.one}`} value={worst ? formatPct(worst.mtd_uptime_pct) : '—'}
        detail={worst ? `${worst.name} · ${worst.circle}` : 'No data'} onClick={worst ? () => onSelectTeam(worst.name) : undefined} />
      <Kpi label={`Sites without a ${labels.one}`} value={formatNumber(t.unassigned_sites)}
        detail={`${formatNumber(t.unassigned_sites_below_60_mtd)} of them below 60%`} tone={t.unassigned_sites_below_60_mtd ? 'bad' : undefined} />
    </div>
  );
}

function Kpi({ label, value, detail, tone, onClick }: { label: string; value: string; detail: string; tone?: 'bad'; onClick?: () => void }) {
  const body = (
    <>
      <p className="text-[11px] font-medium text-muted-foreground">{label}</p>
      <p className={cn('mt-0.5 text-[18px] leading-6 font-semibold tabular-nums', tone === 'bad' && 'text-destructive')}>{value}</p>
      <p className="truncate text-[11px] text-muted-foreground" title={detail}>{detail}</p>
    </>
  );
  return (
    <Card className="gap-0 px-3 py-2">
      {onClick ? (
        <button type="button" onClick={onClick} className="rounded text-left focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none">{body}</button>
      ) : body}
    </Card>
  );
}

function TeamRanking({ data, loading, error, group, selected, onSelect }: {
  data: TeamsResponse | null; loading: boolean; error: Error | null; group: TeamGroup; selected: string; onSelect: (name: string) => void;
}) {
  const [search, setSearch] = useState('');
  const [onlyBelow60, setOnlyBelow60] = useState(false);
  const [sort, setSort] = useState<{ key: SortKey; desc: boolean }>({ key: 'mtd_uptime_pct', desc: false });
  const labels = GROUP_LABELS[group];

  const needle = search.trim().toLowerCase();
  const rows = useMemo(() => {
    const list = (data?.teams ?? []).filter((t) =>
      (!onlyBelow60 || t.sites_below_60_mtd > 0)
      && (!needle || [t.name, t.circle, ...t.linked_names].some((v) => v.toLowerCase().includes(needle))));
    const value = (t: TeamRow) => (sort.key === 'name' ? t.name.toLowerCase() : t[sort.key] ?? Number.POSITIVE_INFINITY);
    return [...list].sort((a, b) => {
      const [x, y] = [value(a), value(b)];
      const order = x < y ? -1 : x > y ? 1 : 0;
      return sort.desc ? -order : order;
    });
  }, [data, onlyBelow60, needle, sort]);
  const split = new Set((data?.teams ?? []).map((t) => t.report_type)).size > 1;

  const header = (key: SortKey, label: string, right = true) => {
    const active = sort.key === key;
    return (
      <TableHead className={right ? 'text-right' : undefined} aria-sort={active ? (sort.desc ? 'descending' : 'ascending') : undefined}>
        <button type="button" onClick={() => setSort((s) => ({ key, desc: s.key === key ? !s.desc : key !== 'mtd_uptime_pct' && key !== 'name' }))}
          className="inline-flex items-center gap-1 rounded font-medium hover:text-foreground focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none">
          {label}
          {active ? (sort.desc ? <ArrowDown className="size-3" /> : <ArrowUp className="size-3" />) : <ArrowUpDown className="size-3 opacity-40" />}
        </button>
      </TableHead>
    );
  };

  return (
    <ChartCard
      title={`${labels.one} ranking`}
      description={data
        ? `MTD to ${formatDate(data.reporting_date)}, lowest uptime first. Select a ${labels.one} to list its sites below.`
        : `Uptime of the sites assigned to each ${labels.one}`}
      action={
        <div className="flex flex-wrap items-center justify-end gap-3">
          <label className="flex items-center gap-1.5 text-xs text-muted-foreground">
            <input type="checkbox" checked={onlyBelow60} onChange={(e) => setOnlyBelow60(e.target.checked)} className="size-3.5 accent-primary" />
            Only with sites below 60%
          </label>
          <div className="relative">
            <Search className="pointer-events-none absolute top-1/2 left-2.5 size-3.5 -translate-y-1/2 text-muted-foreground" aria-hidden="true" />
            <Input type="search" value={search} onChange={(e) => setSearch(e.target.value)} placeholder={`${labels.one}, IE/CI or circle`}
              aria-label={`Search ${labels.many}`} className="h-8 w-52 pl-8" maxLength={60} />
          </div>
        </div>
      }
      loading={loading && !data}
      error={error}
      empty={!rows.length}
      emptyMessage={needle ? `No ${labels.one} matches “${search}”.` : `No ${labels.many} for the selected filters.`}
      bodyClassName="px-0"
    >
      <div className="max-h-[32rem] overflow-auto">
        <Table className="text-xs">
          <TableHeader className="sticky top-0 z-10 bg-card">
            <TableRow className="bg-muted/50 hover:bg-muted/50">
              <TableHead className="w-10 text-right">#</TableHead>
              {header('name', labels.one, false)}
              <TableHead>{labels.linked}</TableHead>
              <TableHead>Circle</TableHead>
              {header('sites_in_scope', 'Sites')}
              {header('mtd_uptime_pct', 'MTD uptime')}
              <TableHead className="text-right">Daily uptime</TableHead>
              <TableHead className="text-right">MTD outage</TableHead>
              <TableHead className="w-40">MTD bucket mix</TableHead>
              {header('sites_below_60_mtd', 'Sites <60%')}
            </TableRow>
          </TableHeader>
          <TableBody>
            {rows.map((t, i) => {
              const isSelected = t.name === selected;
              return (
                <TableRow
                  key={`${t.report_type}-${t.circle}-${t.name}`}
                  className={cn('cursor-pointer', isSelected && 'bg-primary/5 hover:bg-primary/10')}
                  tabIndex={0}
                  aria-selected={isSelected}
                  onClick={() => onSelect(t.name)}
                  onKeyDown={(e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); onSelect(t.name); } }}
                  aria-label={`${t.name}: show sites`}
                >
                  <TableCell className="text-right text-muted-foreground tabular-nums">{i + 1}</TableCell>
                  <TableCell className={cn('max-w-52 truncate font-medium', t.name === UNASSIGNED && 'text-muted-foreground italic')} title={t.name}>{t.name}</TableCell>
                  <TableCell className="max-w-56 truncate text-muted-foreground" title={t.linked_names.join(', ')}>
                    {group === 'ci' ? `${formatNumber(t.linked_names.length)} IE${t.linked_names.length === 1 ? '' : 's'}` : t.linked_names.join(', ') || '—'}
                  </TableCell>
                  <TableCell>{split ? `${t.circle} · ${t.report_type === '4G Saturation' ? '4G' : t.report_type}` : t.circle}</TableCell>
                  <TableCell className="text-right tabular-nums">{formatNumber(t.sites_in_scope)}</TableCell>
                  <TableCell className="text-right font-medium tabular-nums">{formatPct(t.mtd_uptime_pct)}</TableCell>
                  <TableCell className="text-right tabular-nums">{formatPct(t.daily_uptime_pct)}</TableCell>
                  <TableCell className="text-right tabular-nums">{formatMinutes(t.mtd_outage_minutes)}</TableCell>
                  <TableCell><BucketMix buckets={t.buckets} /></TableCell>
                  <TableCell className={cn('text-right tabular-nums', t.sites_below_60_mtd > 0 && 'font-semibold text-destructive')}>
                    {formatNumber(t.sites_below_60_mtd)}
                  </TableCell>
                </TableRow>
              );
            })}
          </TableBody>
        </Table>
      </div>
      <p className="border-t px-4 pt-2.5 text-xs text-muted-foreground">
        {formatNumber(rows.length)} of {formatNumber(data?.teams.length ?? 0)} rows · a {labels.one} working in two circles appears once per circle
      </p>
    </ChartCard>
  );
}

function BucketMix({ buckets }: { buckets: Record<BucketId, number> }) {
  const total = BUCKET_ORDER.reduce((sum, id) => sum + buckets[id], 0);
  if (!total) return <span className="text-muted-foreground">—</span>;
  const summary = BUCKET_ORDER.filter((id) => buckets[id]).map((id) => `${BUCKET_LABELS[id]}: ${buckets[id]}`).join(', ');
  return (
    <div className="flex h-2.5 w-36 overflow-hidden rounded-full bg-muted" role="img" aria-label={summary} title={summary}>
      {BUCKET_ORDER.map((id) => buckets[id] > 0 && (
        <span key={id} style={{ width: `${(100 * buckets[id]) / total}%`, background: BUCKET_COLORS[id] }} />
      ))}
    </div>
  );
}
