import { Link, useSearchParams } from 'react-router-dom';
import { ChevronRight, Database, FileUp, Info, Trophy } from 'lucide-react';
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert';
import { Button, buttonVariants } from '@/components/ui/button';
import { Card } from '@/components/ui/card';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import { Skeleton } from '@/components/ui/skeleton';
import { cn } from '@/lib/utils';
import { ChartCard } from '../components/dashboard/ChartCard';
import { Field, FilterBar } from '../components/dashboard/FilterBar';
import { useWorkbook } from '../context/workbook';
import { useApiQuery } from '../hooks/useApiQuery';
import { useDashboardFilters } from '../hooks/useDashboardFilters';
import { formatDate, formatNumber, formatPct } from '../lib/format';
import { fetchFilterOptions, fetchTeamTop } from '../services/api';
import type { GroupRanking, NslaValue, RankedPerson, TeamGroup, TopPerformerCircle, TopPerformersResponse } from '../types';

const GROUP_LABELS: Record<TeamGroup, string> = { ci: 'CI', ie: 'IE' };
const PROJECT_ORDER = ['4G Saturation', 'LWE'];
const projectLabel = (type: string) => (type === '4G Saturation' ? '4G' : type);
const circleKey = (c: { report_type: string; circle: string }) => `${c.report_type}|${c.circle}`;
/** Tied leaders named in the circle table; the rest are counted (all are listed in the circle's ranking). */
const TIES_SHOWN = 2;

// Cell styles are set per cell (not through parent selectors) so padding and borders always apply.
const TH = 'border-b bg-muted/50 px-3 py-2 text-[11px] font-medium whitespace-nowrap text-muted-foreground';
const TD = 'border-b px-3 py-2 align-middle';

export function TopPerformersPage() {
  const workbook = useWorkbook();
  const { version } = workbook;
  const options = useApiQuery(workbook.active ? `${version}|filters` : null, fetchFilterOptions);
  // Same scope default as CI & IE Performance (NSLA is the O&M Start penalty threshold), so the figures match.
  const { filters, setFilters, reset, isDefault } = useDashboardFilters(options.data, { defaultScope: 'om_start' });
  const [searchParams, setSearchParams] = useSearchParams();
  const month = searchParams.get('month') ?? '';
  const focus = searchParams.get('focus') ?? '';
  const setParam = (key: string, value: string | null) => setSearchParams((current) => {
    const next = new URLSearchParams(current);
    if (value) next.set(key, value);
    else next.delete(key);
    return next;
  }, { replace: true });

  let query: URLSearchParams | null = null;
  if (filters) {
    query = new URLSearchParams(filters.snapshotParams);
    query.delete('reporting_date');
    if (month) query.set('month', month);
  }
  const result = useApiQuery(query ? `${version}|teams-top|${query}` : null, (signal) => fetchTeamTop(query!, signal));

  if (!workbook.loading && !workbook.error && !workbook.active) {
    return (
      <Card className="mx-auto mt-10 max-w-xl items-center gap-3 px-8 py-10 text-center">
        <FileUp className="size-8 text-muted-foreground" aria-hidden="true" />
        <h1 className="text-lg font-semibold">No Master workbook loaded</h1>
        <p className="text-sm text-muted-foreground">Upload the consolidated workbook to see circle-wise top performers.</p>
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
    return <Skeleton className="h-96 w-full" aria-label="Loading circle-wise top performers" />;
  }

  const data = result.data;
  const months = data?.months_available ?? [];
  const latest = months[months.length - 1]?.key;
  const selectedMonth = month || data?.reporting_month || latest || '';
  const circles = data?.circles ?? [];
  const selected = circles.find((c) => circleKey(c) === focus) ?? circles[0];
  const period = data?.month ? `${data.month.label}${data.month.kind === 'mtd' ? ` to ${formatDate(data.reporting_date)}` : ''}` : '';
  const projects = PROJECT_ORDER.filter((p) => circles.some((c) => c.report_type === p))
    .concat([...new Set(circles.map((c) => c.report_type))].filter((p) => !PROJECT_ORDER.includes(p)));
  // Opens the person on CI & IE Performance with the same project, circle, scope and month.
  const personLink = (group: TeamGroup, c: TopPerformerCircle, name: string) => {
    const q = new URLSearchParams({ report_type: c.report_type, circle: c.circle, scope: filters.scope, q: name });
    if (group === 'ie') q.set('group', 'ie');
    if (month) q.set('month', month);
    return `/teams/ci-ie?${q}`;
  };
  const named = (g: TeamGroup) => circles.filter((c) => c[g].top.length).length;
  const ties = circles.filter((c) => c.ci.status === 'tie' || c.ie.status === 'tie').length;
  const insufficient = circles.filter((c) => !c.ci.top.length || !c.ie.top.length).length;

  return (
    <div className="space-y-4">
      <FilterBar options={options.data} filters={filters} onChange={setFilters}
        canReset={!isDefault || !!month || !!focus} onReset={reset} showTrendRange={false} showDate={false}
        title="Circle-wise Top Performers"
        description="The CI and the IE with the lowest NSLA % in each circle, ranked separately within the same project and period."
        extra={(
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
        <>
        <CircleNslaTable data={data} loading={result.loading} error={result.error} period={period}
          selected={selected ? circleKey(selected) : ''} onSelect={(key) => setParam('focus', key)} />
        <div className="grid items-start gap-4 2xl:grid-cols-[minmax(0,7fr)_minmax(0,5fr)]">
          <ChartCard
            title="Top CI and IE by circle"
            description={data ? `${period} · lower NSLA % is better · select a circle to see its full rankings` : 'Lower NSLA % is better'}
            action={data && circles.length ? (
              <dl className="flex flex-wrap gap-x-4 gap-y-1 text-xs" aria-label="Summary">
                <Stat label="Circles" value={circles.length} />
                <Stat label="Top CI named" value={named('ci')} />
                <Stat label="Top IE named" value={named('ie')} />
                <Stat label="With a tie" value={ties} />
                <Stat label="Insufficient data" value={insufficient} muted />
              </dl>
            ) : undefined}
            loading={result.loading && !data}
            error={result.error}
            empty={!circles.length}
            emptyMessage="No circle has sites assigned to a CI or IE for the selected filters."
            bodyClassName="px-0"
          >
            <div className="overflow-x-auto" role="region" aria-label="Top performers by circle" tabIndex={0}>
              <table className="w-full min-w-[44rem] border-separate border-spacing-0 text-xs tabular-nums">
                <thead>
                  <tr>
                    <th scope="col" className={cn(TH, 'sticky left-0 z-10 w-24 text-left')}>Circle</th>
                    <th scope="col" className={cn(TH, 'text-right')} title="Sites in scope in this circle and project">Sites</th>
                    <th scope="col" className={cn(TH, 'border-l text-left')}>Top-performing CI</th>
                    <th scope="col" className={cn(TH, 'text-right')}>CI NSLA %</th>
                    <th scope="col" className={cn(TH, 'border-l text-left')}>Top-performing IE</th>
                    <th scope="col" className={cn(TH, 'text-right')}>IE NSLA %</th>
                    <th scope="col" className={cn(TH, 'w-8')}><span className="sr-only">Rankings</span></th>
                  </tr>
                </thead>
                {projects.map((project) => (
                  <tbody key={project}>
                    {projects.length > 1 && (
                      <tr>
                        <th colSpan={7} scope="rowgroup" className="sticky left-0 border-b bg-card px-3 pt-3 pb-1 text-left text-[10px] font-semibold tracking-wider text-muted-foreground uppercase">
                          {project} · {circles.filter((c) => c.report_type === project).length} circles
                        </th>
                      </tr>
                    )}
                    {circles.filter((c) => c.report_type === project).map((c) => {
                      const isSelected = !!selected && circleKey(c) === circleKey(selected);
                      const bg = isSelected ? 'bg-sky-50' : 'bg-card group-hover:bg-muted/40';
                      return (
                        <tr key={circleKey(c)} aria-selected={isSelected} className="group cursor-pointer" onClick={() => setParam('focus', circleKey(c))}>
                          <th scope="row" className={cn(TD, bg, 'sticky left-0 z-10 text-left font-semibold', isSelected && 'shadow-[inset_3px_0_0_#0284c7]')}>
                            {c.circle}{' '}<span className="ml-1 font-normal text-muted-foreground">{projectLabel(c.report_type)}</span>
                          </th>
                          <td className={cn(TD, bg, 'text-right text-muted-foreground')}>{formatNumber(c.sites_in_scope)}</td>
                          <WinnerCells ranking={c.ci} group="ci" bg={bg} link={(name) => personLink('ci', c, name)} />
                          <WinnerCells ranking={c.ie} group="ie" bg={bg} link={(name) => personLink('ie', c, name)} />
                          <td className={cn(TD, bg, 'px-1 text-right')}>
                            <Button variant="ghost" size="icon" className="size-6" aria-pressed={isSelected}
                              aria-label={`Show ${c.circle} ${projectLabel(c.report_type)} rankings`}
                              onClick={(e) => { e.stopPropagation(); setParam('focus', circleKey(c)); }}>
                              <ChevronRight className={cn('size-3.5', isSelected ? 'text-primary' : 'text-muted-foreground')} />
                            </Button>
                          </td>
                        </tr>
                      );
                    })}
                  </tbody>
                ))}
              </table>
            </div>
            {data && (
              <p className="flex items-start gap-1.5 px-4 pt-3 text-[11px] leading-relaxed text-muted-foreground">
                <Info className="mt-px size-3.5 shrink-0" aria-hidden="true" />
                <span>
                  NSLA % = assigned sites below {data.rules.nsla_threshold_pct}% uptime ÷ assigned sites. A person is ranked only with at
                  least {data.rules.min_sites} assigned sites, all reported in the period; a top performer is named only when at
                  least {data.rules.min_people} people qualify. Equal shares are ties. Someone assigned in several circles or projects is
                  ranked separately in each.
                </span>
              </p>
            )}
          </ChartCard>

          {selected && data && <CircleRankings key={circleKey(selected)} circle={selected} period={period} link={personLink} />}
        </div>
        </>
      )}
    </div>
  );
}

function Stat({ label, value, muted }: { label: string; value: number; muted?: boolean }) {
  return (
    <div className="flex items-baseline gap-1">
      <dt className="text-muted-foreground">{label}</dt>
      <dd className={cn('font-semibold tabular-nums', muted && value > 0 && 'text-amber-700')}>{formatNumber(value)}</dd>
    </div>
  );
}

/** Leader name with its basis (NSLA sites of assigned sites) and NSLA %; tied leaders together; "Insufficient data" otherwise. */
function WinnerCells({ ranking, group, bg, link }: { ranking: GroupRanking; group: TeamGroup; bg: string; link: (name: string) => string }) {
  const best = ranking.ranking.filter((p) => ranking.top.includes(p.name));
  if (!best.length) {
    return (
      <td className={cn(TD, bg, 'border-l')} colSpan={2} title={ranking.reason ?? undefined}>
        <span className="inline-flex items-center gap-1 text-muted-foreground">
          <Info className="size-3" aria-hidden="true" />Insufficient data
        </span>
        {ranking.reason && <span className="sr-only">: {ranking.reason}</span>}
      </td>
    );
  }
  const shown = best.slice(0, TIES_SHOWN);
  const more = best.length - shown.length;
  const lead = best[0];
  return (
    <>
      <td className={cn(TD, bg, 'border-l')}>
        <div className="flex min-w-0 items-start gap-1.5">
          <Trophy className="mt-0.5 size-3 shrink-0 text-amber-500" aria-hidden="true" />
          <div className="min-w-0">
            <div className="flex flex-wrap items-center gap-x-1">
              {shown.map((p, i) => (
                <span key={p.name} className="inline-flex max-w-full min-w-0">
                  <Link to={link(p.name)} onClick={(e) => e.stopPropagation()} title={`${p.name}: open on CI & IE Performance`}
                    className="max-w-48 truncate font-medium text-foreground hover:text-primary hover:underline">{p.name}</Link>
                  {i < shown.length - 1 && <span className="text-muted-foreground">,&nbsp;</span>}
                </span>
              ))}
              {more > 0 && (
                <span className="ml-1 text-muted-foreground" title={best.slice(TIES_SHOWN).map((p) => p.name).join(', ')}>+{more} more</span>
              )}
            </div>
            <div className="text-[11px] text-muted-foreground">
              {ranking.status === 'tie' && <span className="mr-1 rounded bg-muted px-1 font-medium text-foreground">Tie · {best.length}</span>}
              {best.length === 1
                ? `${formatNumber(lead.nsla_sites)} of ${formatNumber(lead.sites_in_scope)} sites NSLA`
                : `each ${formatNumber(lead.nsla_sites)} NSLA · ${best.map((p) => formatNumber(p.sites_in_scope)).join(' / ')} sites`}
              <span className="sr-only"> ({GROUP_LABELS[group]})</span>
            </div>
          </div>
        </div>
      </td>
      <td className={cn(TD, bg, 'text-right')}>
        <span className="rounded bg-emerald-50 px-1.5 py-0.5 font-semibold text-emerald-800">{formatPct(lead.nsla_pct, 1)}</span>
      </td>
    </>
  );
}

function CircleRankings({ circle, period, link }: {
  circle: TopPerformerCircle; period: string; link: (group: TeamGroup, c: TopPerformerCircle, name: string) => string;
}) {
  return (
    <section className="grid items-start gap-4 lg:grid-cols-2 2xl:grid-cols-1" aria-label={`${circle.circle} ${projectLabel(circle.report_type)} rankings`}>
      {(['ci', 'ie'] as TeamGroup[]).map((group) => (
        <RankingTable key={group} title={`${circle.circle} · ${projectLabel(circle.report_type)} — ${GROUP_LABELS[group]} ranking`}
          group={group} ranking={circle[group]} period={period} link={(name) => link(group, circle, name)} />
      ))}
    </section>
  );
}

function RankingTable({ title, group, ranking, period, link }: {
  title: string; group: TeamGroup; ranking: GroupRanking; period: string; link: (name: string) => string;
}) {
  const label = GROUP_LABELS[group];
  const ranked = ranking.ranking.filter((p) => p.rank != null);
  const unranked = ranking.ranking.filter((p) => p.rank == null);
  return (
    <ChartCard
      title={title}
      description={`${period} · ${formatNumber(ranking.people_eligible)} of ${formatNumber(ranking.people_total)} ${label}s eligible · lowest NSLA % first`}
      empty={!ranking.ranking.length}
      emptyMessage={`No ${label} is assigned in this circle.`}
      bodyClassName="px-0"
    >
      {ranking.status === 'insufficient' && (
        <p className="mx-4 mb-1 flex items-start gap-1.5 rounded-md border border-amber-200 bg-amber-50 px-2.5 py-1.5 text-xs text-amber-900">
          <Info className="mt-px size-3.5 shrink-0" aria-hidden="true" />
          <span>Insufficient data to name a top {label}: {ranking.reason}</span>
        </p>
      )}
      <div className="max-h-[26rem] overflow-auto" role="region" aria-label={`${title} table`} tabIndex={0}>
        <table className="w-full border-separate border-spacing-0 text-xs tabular-nums">
          <thead className="sticky top-0 z-10">
            <tr>
              <th scope="col" className={cn(TH, 'w-12 text-center')}>Rank</th>
              <th scope="col" className={cn(TH, 'text-left')}>{label}</th>
              <th scope="col" className={cn(TH, 'text-right')}>Assigned</th>
              <th scope="col" className={cn(TH, 'text-right')}>NSLA sites</th>
              <th scope="col" className={cn(TH, 'w-32 text-right')}>NSLA %</th>
              <th scope="col" className={cn(TH, 'text-right')} title="Assigned sites with a value in the period">Reported</th>
            </tr>
          </thead>
          <tbody>
            {ranked.map((p) => <PersonRow key={p.name} person={p} top={ranking.top.includes(p.name)}
              unnamed={!ranking.top.length && p.rank === 1} label={label} link={link} />)}
          </tbody>
          {unranked.length > 0 && (
            <tbody>
              <tr>
                <th colSpan={6} scope="rowgroup" className="border-b bg-card px-3 pt-3 pb-1 text-left text-[10px] font-semibold tracking-wider text-muted-foreground uppercase">
                  Not ranked · {unranked.length}
                </th>
              </tr>
              {unranked.map((p) => <PersonRow key={p.name} person={p} top={false} unnamed={false} label={label} link={link} />)}
            </tbody>
          )}
        </table>
      </div>
    </ChartCard>
  );
}

function PersonRow({ person: p, top, unnamed, label, link }: {
  person: RankedPerson; top: boolean; unnamed: boolean; label: string; link: (name: string) => string;
}) {
  const complete = p.sites_reported === p.sites_in_scope;
  return (
    <tr className={cn(top ? 'bg-emerald-50/60' : 'hover:bg-muted/40', p.rank == null && 'text-muted-foreground')}>
      <td className={cn(TD, 'text-center')}>
        {p.rank == null ? '—' : (
          <span className={cn('inline-flex size-5 items-center justify-center rounded-full text-[11px] font-semibold',
            top ? 'bg-emerald-600 text-white' : 'bg-muted text-foreground')}>{p.rank}</span>
        )}
      </td>
      <td className={cn(TD, 'max-w-64')}>
        <Link to={link(p.name)} className={cn('block truncate hover:text-primary hover:underline', top ? 'font-semibold text-emerald-900' : 'font-medium')} title={p.name}>{p.name}</Link>
        {p.reason && <span className="block text-[11px]">{p.reason}</span>}
        {unnamed && <span className="block text-[11px] text-muted-foreground">Not named top: too few eligible {label}s to compare</span>}
        {!!p.other_assignments?.length && <span className="block text-[11px] text-muted-foreground">Also assigned: {p.other_assignments.join(', ')}</span>}
      </td>
      <td className={cn(TD, 'text-right')}>{formatNumber(p.sites_in_scope)}</td>
      <td className={cn(TD, 'text-right')}>{formatNumber(p.nsla_sites)}</td>
      <td className={cn(TD, 'text-right')}>
        <div className="flex items-center justify-end gap-2">
          {p.nsla_pct != null && (
            <span className="h-1.5 w-14 overflow-hidden rounded-full bg-muted" aria-hidden="true">
              <span className={cn('block h-full rounded-full', top ? 'bg-emerald-500' : 'bg-slate-400')} style={{ width: `${Math.min(100, p.nsla_pct)}%` }} />
            </span>
          )}
          <span className="w-12 font-medium">{formatPct(p.nsla_pct, 1)}</span>
        </div>
      </td>
      <td className={cn(TD, 'text-right', !complete && 'text-amber-700')} title={complete ? 'Every assigned site reported' : 'Some assigned sites have no value'}>
        {formatNumber(p.sites_reported)} / {formatNumber(p.sites_in_scope)}
      </td>
    </tr>
  );
}

/** Circle-wise NSLA by month, as the workbook's "NSLA Sites" sheet: the reporting month's NSLA sites, % and rank
 * (within the project, lowest % first), then the earlier months, newest first. Totals per project. */
function CircleNslaTable({ data, loading, error, period, selected, onSelect }: {
  data: TopPerformersResponse | null; loading: boolean; error: Error | null; period: string;
  selected: string; onSelect: (key: string) => void;
}) {
  const months = data?.months ?? [];
  const current = months[months.length - 1];
  const earlier = months.slice(0, -1).reverse();
  const circles = data?.circles ?? [];
  const projects = (data?.projects ?? []).slice().sort((a, b) => PROJECT_ORDER.indexOf(a.report_type) - PROJECT_ORDER.indexOf(b.report_type));
  const byRank = (a: TopPerformerCircle, b: TopPerformerCircle) => (a.nsla_rank ?? Infinity) - (b.nsla_rank ?? Infinity) || a.circle.localeCompare(b.circle);
  const note = (v: NslaValue | null | undefined) => (v == null ? 'No site reported' : v.no_value ? `${formatNumber(v.no_value)} site(s) with no value` : undefined);
  const monthCell = (v: NslaValue | null | undefined, strong = false) => (
    v == null ? <span className="text-muted-foreground">—</span> : (
      <>
        <span className={strong ? 'font-semibold' : undefined}>{formatNumber(v.nsla_sites)}</span>
        <span className="block text-[10px] text-muted-foreground">{formatPct(v.nsla_pct, 0)}</span>
      </>
    )
  );

  return (
    <ChartCard
      title="Circle-wise NSLA by month"
      description={current
        ? `NSLA sites (below ${data?.rules.nsla_threshold_pct}% uptime) per circle · ${period} ranked within each project, lowest NSLA % first · earlier months from the monthly outage in the source`
        : 'NSLA sites per circle and month'}
      loading={loading && !data}
      error={error}
      empty={!circles.length || !current}
      emptyMessage="No circle has data for the selected filters."
      bodyClassName="px-0"
    >
      {current && (
        <div className="overflow-x-auto" role="region" aria-label="Circle-wise NSLA by month" tabIndex={0}>
          <table className="w-full min-w-[40rem] border-separate border-spacing-0 text-xs tabular-nums">
            <thead>
              <tr>
                <th scope="col" className={cn(TH, 'sticky left-0 z-10 text-left')}>Circle</th>
                <th scope="col" className={cn(TH, 'text-right')}>Scope</th>
                <th scope="col" className={cn(TH, 'border-l text-right')}>NSLA · {current.label}</th>
                <th scope="col" className={cn(TH, 'text-right')}>NSLA %</th>
                <th scope="col" className={cn(TH, 'text-center')}>Rank</th>
                {earlier.map((m, i) => (
                  <th key={m.key} scope="col" className={cn(TH, 'text-right', i === 0 && 'border-l')}>{m.label}</th>
                ))}
              </tr>
            </thead>
            {projects.map((project) => {
              const rows = circles.filter((c) => c.report_type === project.report_type).sort(byRank);
              const total = project.nsla[current.key];
              return (
                <tbody key={project.report_type}>
                  <tr className="bg-muted/30 font-semibold">
                    <th scope="row" className={cn(TD, 'sticky left-0 z-10 bg-muted/30 text-left')}>{project.report_type} total</th>
                    <td className={cn(TD, 'text-right')}>{formatNumber(project.sites_in_scope)}</td>
                    <td className={cn(TD, 'border-l text-right')} title={note(total)}>{formatNumber(total?.nsla_sites)}</td>
                    <td className={cn(TD, 'text-right')}>{formatPct(total?.nsla_pct, 1)}</td>
                    <td className={TD} />
                    {earlier.map((m, i) => (
                      <td key={m.key} className={cn(TD, 'text-right', i === 0 && 'border-l')} title={note(project.nsla[m.key])}>{monthCell(project.nsla[m.key], true)}</td>
                    ))}
                  </tr>
                  {rows.map((c) => {
                    const key = circleKey(c);
                    const v = c.nsla[current.key];
                    const isSelected = key === selected;
                    return (
                      <tr key={key} aria-selected={isSelected} onClick={() => onSelect(key)}
                        className={cn('cursor-pointer', isSelected ? 'bg-sky-50' : 'hover:bg-muted/40')}>
                        <th scope="row" className={cn(TD, 'sticky left-0 z-10 text-left font-medium', isSelected ? 'bg-sky-50' : 'bg-card')}>
                          {c.circle}{' '}<span className="ml-1 font-normal text-muted-foreground">{projectLabel(c.report_type)}</span>
                        </th>
                        <td className={cn(TD, 'text-right')}>{formatNumber(c.sites_in_scope)}</td>
                        <td className={cn(TD, 'border-l text-right font-medium')} title={note(v)}>{formatNumber(v?.nsla_sites)}</td>
                        <td className={cn(TD, 'text-right')} title={note(v)}>
                          {v == null ? <span className="text-muted-foreground">—</span> : (
                            <span className={cn('rounded px-1.5 py-0.5 font-semibold', c.nsla_rank === 1 ? 'bg-emerald-50 text-emerald-800' : 'bg-rose-50 text-rose-800')}>
                              {formatPct(v.nsla_pct, 1)}
                            </span>
                          )}
                        </td>
                        <td className={cn(TD, 'text-center')}>
                          {c.nsla_rank == null ? <span className="text-muted-foreground">—</span> : (
                            <span className={cn('inline-flex size-5 items-center justify-center rounded-full text-[11px] font-semibold',
                              c.nsla_rank === 1 ? 'bg-emerald-600 text-white' : 'bg-muted text-foreground')}>{c.nsla_rank}</span>
                          )}
                        </td>
                        {earlier.map((m, i) => (
                          <td key={m.key} className={cn(TD, 'text-right', i === 0 && 'border-l')} title={note(c.nsla[m.key])}>{monthCell(c.nsla[m.key])}</td>
                        ))}
                      </tr>
                    );
                  })}
                </tbody>
              );
            })}
          </table>
        </div>
      )}
      {current && (
        <p className="flex items-start gap-1.5 px-4 pt-3 text-[11px] leading-relaxed text-muted-foreground">
          <Info className="mt-px size-3.5 shrink-0" aria-hidden="true" />
          <span>
            NSLA % = NSLA sites ÷ scope (all sites in scope, including any without a value). Circles are ranked only against circles of
            the same project. RCA-wise columns (PTPL / BSNL) are not shown: the source has no RCA per site and month in these categories.
          </span>
        </p>
      )}
    </ChartCard>
  );
}
