import { useState } from 'react';
import { ChevronLeft, ChevronRight, Search } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Card } from '@/components/ui/card';
import { Input } from '@/components/ui/input';
import { TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table';
import { cn } from '@/lib/utils';
import { ChartCard } from '../../../components/dashboard/ChartCard';
import { useApiQuery } from '../../../hooks/useApiQuery';
import { fetchKpiHierarchy, fetchKpiSites } from '../api';
import { count, hours, NUM, pct } from '../format';
import { availabilityTone, coverageTone, problemTone, TONE_TEXT } from '../status';
import type { HierarchyLevel, KpiGroupRow } from '../types';
import type { useKpiFilters } from '../useKpiFilters';
import { KpiTable, Pager } from './KpiTable';

type Level = HierarchyLevel | 'site';
const LEVELS: Level[] = ['circle', 'ci', 'ie', 'site'];
const NAMES: Record<Level, string> = { circle: 'Circle', ci: 'CI / Cluster', ie: 'IE', site: 'Site' };
const project = (p: string) => (p === '4G Saturation' ? '4G' : p);

/**
 * Circle → CI/Cluster → IE → Site. A click narrows the filters to the row (so every tab follows) and opens the next
 * level; the breadcrumb goes back. An IE is always the IE of one CI (the same name can work under several CIs).
 */
export function DrillDown({ f }: { f: ReturnType<typeof useKpiFilters> }) {
  const level: Level = LEVELS.find((l) => l === f.params.get('level')) ?? 'circle';
  const go = (next: Level, changes: Record<string, string | string[] | null> = {}) => f.update({ ...changes, level: next === 'circle' ? null : next });
  const open = (row: KpiGroupRow) => {
    if (level === 'circle') go('ci', { project: [row.project], circle: [row.circle], ci: null, ie: null, site: null });
    else if (level === 'ci') go('ie', { ci: [row.key], ie: null, site: null });
    else if (level === 'ie') go('site', { ie: [row.key], site: null });
  };
  const crumbs: { field?: string; label: string; to: Level; clear: Record<string, null> }[] = [{ label: 'All circles', to: 'circle', clear: { project: null, circle: null, ci: null, ie: null, site: null } }];
  if (level !== 'circle' && f.values.circle.length) crumbs.push({ field: 'Circle', label: `${f.values.circle.join(', ')}${f.values.project.length ? ` (${f.values.project.map(project).join(', ')})` : ''}`, to: 'ci', clear: { ci: null, ie: null, site: null } });
  if ((level === 'ie' || level === 'site') && f.values.ci.length) crumbs.push({ field: 'CI', label: f.values.ci.map((k) => k.split('::')[1]).join(', '), to: 'ie', clear: { ie: null, site: null } });
  if (level === 'site' && f.values.ie.length) crumbs.push({ field: 'IE', label: f.values.ie.map((k) => k.split('::')[2]).join(', '), to: 'site', clear: {} });
  const step = LEVELS.indexOf(level);
  return (
    <div className="space-y-3">
      <Card className="gap-0 px-4 py-2.5 shadow-xs">
        <div className="flex flex-wrap items-center gap-x-3 gap-y-2">
          {level !== 'circle' && (
            <Button size="sm" variant="outline" className="h-8" onClick={() => {
              const back = crumbs[crumbs.length - 2];
              go(back.to, back.clear);
            }}><ChevronLeft /> Back</Button>
          )}
          <nav aria-label="Drill-down" className="flex min-w-0 flex-wrap items-center gap-1 text-sm">
            {crumbs.map((c, i) => (
              <span key={c.label} className="inline-flex min-w-0 items-center gap-1">
                {i > 0 && <ChevronRight className="size-3.5 shrink-0 text-muted-foreground" aria-hidden="true" />}
                {c.field && <span className="text-xs text-muted-foreground">{c.field}</span>}
                {i === crumbs.length - 1 ? <span className="truncate font-semibold" aria-current="location">{c.label}</span>
                  : <button type="button" className="truncate font-medium text-primary hover:underline" onClick={() => go(c.to, c.clear)}>{c.label}</button>}
              </span>
            ))}
          </nav>
          <ol aria-label="Hierarchy level" className="flex items-center gap-1 text-[11px] sm:ml-auto">
            {LEVELS.map((l, i) => (
              <li key={l} aria-current={i === step ? 'step' : undefined} className="inline-flex items-center gap-1">
                {i > 0 && <span className={cn('h-px w-3', i <= step ? 'bg-primary/50' : 'bg-border')} aria-hidden="true" />}
                <span className={cn('rounded-full px-2 py-0.5 font-medium whitespace-nowrap',
                  i === step ? 'bg-primary text-primary-foreground' : i < step ? 'bg-primary/10 text-primary' : 'bg-muted text-muted-foreground')}>
                  {NAMES[l]}
                </span>
              </li>
            ))}
          </ol>
        </div>
      </Card>
      {level === 'site' ? <SitesTable key={f.query.toString()} query={f.query} /> : <GroupTable level={level} query={f.query} onOpen={open} />}
    </div>
  );
}

function GroupTable({ level, query, onOpen }: { level: HierarchyLevel; query: URLSearchParams; onOpen: (row: KpiGroupRow) => void }) {
  const params = new URLSearchParams(query);
  params.set('level', level);
  const data = useApiQuery(`allkpis-hierarchy-${params}`, (signal) => fetchKpiHierarchy(params, signal));
  const rows = data.data?.rows ?? [];
  const next = NAMES[LEVELS[LEVELS.indexOf(level) + 1]];
  return (
    <ChartCard title={`${NAMES[level]}-wise performance`} loading={data.loading} error={data.error} empty={!rows.length}
      description={`${count(rows.length)} ${rows.length === 1 ? 'row' : 'rows'} · select a ${NAMES[level]} to open its ${next} view. USD and NSLA: O&M Start sites; availability and thresholds: On-Air sites.`}>
      <KpiTable>
        <TableHeader>
          <TableRow>
            <TableHead>{NAMES[level]}</TableHead>{level !== 'circle' && <TableHead>Circle</TableHead>}<TableHead>Project</TableHead>
            <TableHead className={NUM}>Total sites</TableHead><TableHead className={NUM}>On-Air</TableHead><TableHead className={NUM}>O&amp;M Start</TableHead>
            <TableHead className={NUM}>Availability</TableHead><TableHead className={NUM}>Outage</TableHead><TableHead className={NUM}>USD</TableHead>
            <TableHead className={NUM}>NSLA</TableHead><TableHead className={NUM}>&lt; 98.5%</TableHead><TableHead className={NUM}>&lt; 60%</TableHead>
            <TableHead className={NUM}>Coverage</TableHead><TableHead className="w-6" aria-hidden="true" />
          </TableRow>
        </TableHeader>
        <TableBody>
          {rows.map((r) => (
            <TableRow key={`${r.project}|${r.key}`} className="group/row cursor-pointer hover:bg-muted/50" onClick={() => onOpen(r)}>
              <TableCell className="font-medium">
                <button type="button" className="text-left text-primary hover:underline" aria-label={`Open ${NAMES[level]} ${r[level === 'circle' ? 'circle' : level] ?? ''} (${project(r.project)})`}
                  onClick={(e) => { e.stopPropagation(); onOpen(r); }}>{level === 'circle' ? r.circle : level === 'ci' ? r.ci : r.ie}</button>
                {level === 'ie' && <span className="block text-[11px] font-normal text-muted-foreground">CI: {r.ci}</span>}
              </TableCell>
              {level !== 'circle' && <TableCell>{r.circle}</TableCell>}
              <TableCell>{project(r.project)}</TableCell>
              <TableCell className={NUM}>{count(r.total_sites)}</TableCell>
              <TableCell className={NUM}>{count(r.on_air_sites)}</TableCell>
              <TableCell className={NUM}>{count(r.om_start_sites)}</TableCell>
              <TableCell className={cn(NUM, TONE_TEXT[availabilityTone(r.availability_pct)])}>{pct(r.availability_pct, 3)}</TableCell>
              <TableCell className={NUM}>{hours(r.outage_hours)}</TableCell>
              <TableCell className={NUM}>{count(r.usd_sites)}</TableCell>
              <TableCell className={NUM}>{count(r.nsla_sites)}</TableCell>
              <TableCell className={NUM}>{count(r.below_98_5_sites)}</TableCell>
              <TableCell className={cn(NUM, TONE_TEXT[problemTone(r.below_60_sites, 'bad')])}>{count(r.below_60_sites)}</TableCell>
              <TableCell className={cn(NUM, TONE_TEXT[coverageTone(r.coverage_pct)])}>{pct(r.coverage_pct, 1)}</TableCell>
              <TableCell className="px-1 text-muted-foreground"><ChevronRight className="size-3.5 opacity-40 group-hover/row:opacity-100" aria-hidden="true" /></TableCell>
            </TableRow>
          ))}
        </TableBody>
      </KpiTable>
    </ChartCard>
  );
}

const SORTS: [string, string][] = [['availability', 'Lowest availability'], ['-outage', 'Most outage'], ['days', 'Fewest days reported'], ['site_id', 'Site ID']];
const yesNo = (v: boolean | null, yesClass: string) => (v == null ? <span className="text-muted-foreground">—</span> : v ? <span className={yesClass}>Yes</span> : <span className="text-muted-foreground">No</span>);

/** Site-wise table: server-side search, sort and paging. */
export function SitesTable({ query, defaultSort = 'availability', title = 'Site-wise performance' }: { query: URLSearchParams; defaultSort?: string; title?: string }) {
  const [page, setPage] = useState(1);
  const [sort, setSort] = useState(defaultSort);
  const [q, setQ] = useState('');
  const params = new URLSearchParams(query);
  params.set('page', String(page));
  params.set('sort', sort);
  if (q.trim()) params.set('q', q.trim());
  const data = useApiQuery(`allkpis-sites-${params}`, (signal) => fetchKpiSites(params, signal));
  const d = data.data;
  return (
    <ChartCard title={title} loading={data.loading} error={data.error} empty={!d?.rows.length}
      emptyMessage={q.trim() ? `No site matches "${q.trim()}".` : undefined}
      description={d ? `${count(d.total)} sites · availability and outage over the selected period` : undefined}
      action={(
        <div className="flex flex-wrap items-center gap-2">
          <div className="relative">
            <Search className="absolute top-1/2 left-2.5 size-3.5 -translate-y-1/2 text-muted-foreground" aria-hidden="true" />
            <Input aria-label="Search sites" placeholder="Site ID or name" value={q} onChange={(e) => { setQ(e.target.value); setPage(1); }} className="h-8 w-48 pl-8 text-xs" />
          </div>
          <select aria-label="Sort sites" className="h-8 rounded-md border bg-background px-2 text-xs shadow-xs" value={sort} onChange={(e) => { setSort(e.target.value); setPage(1); }}>
            {SORTS.map(([v, l]) => <option key={v} value={v}>{l}</option>)}
          </select>
        </div>
      )}>
      <KpiTable>
        <TableHeader>
          <TableRow>
            <TableHead>Site ID</TableHead><TableHead>Name</TableHead><TableHead>Circle</TableHead><TableHead>CI / Cluster</TableHead><TableHead>IE</TableHead>
            <TableHead>On-Air</TableHead><TableHead>O&amp;M Start</TableHead><TableHead className={NUM}>Availability</TableHead><TableHead className={NUM}>Outage</TableHead>
            <TableHead>SLA bucket</TableHead><TableHead>USD</TableHead><TableHead>NSLA</TableHead><TableHead className={NUM}>Days reported</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {d?.rows.map((r) => (
            <TableRow key={`${r.project}|${r.site_id}`}>
              <TableCell className="font-medium">{r.site_id}</TableCell>
              <TableCell className="max-w-48 truncate" title={r.site_name || undefined}>{r.site_name || '—'}</TableCell>
              <TableCell>{r.circle} <span className="text-muted-foreground">· {project(r.project)}</span></TableCell>
              <TableCell className="max-w-40 truncate" title={r.ci}>{r.ci}</TableCell>
              <TableCell className="max-w-40 truncate" title={r.ie}>{r.ie}</TableCell>
              <TableCell>{r.on_air ? 'Yes' : <span className="text-muted-foreground">No</span>}</TableCell>
              <TableCell>{r.om_start == null ? <span className="text-muted-foreground">Not available</span> : r.om_start ? 'Yes' : <span className="text-muted-foreground">No</span>}</TableCell>
              <TableCell className={cn(NUM, TONE_TEXT[availabilityTone(r.availability_pct)])}>{r.availability_pct == null ? <span className="text-muted-foreground">No value</span> : pct(r.availability_pct, 3)}</TableCell>
              <TableCell className={NUM}>{hours(r.outage_hours)}</TableCell>
              <TableCell>{r.bucket_label ?? <span className="text-muted-foreground">No value</span>}</TableCell>
              <TableCell>{yesNo(r.usd, 'font-medium text-amber-700')}</TableCell>
              <TableCell>{yesNo(r.nsla, 'font-medium text-red-700')}</TableCell>
              <TableCell className={cn(NUM, r.days_reported < r.days_expected && 'font-medium text-amber-700')}>{r.days_reported} / {r.days_expected}</TableCell>
            </TableRow>
          ))}
        </TableBody>
      </KpiTable>
      {d && <Pager page={d.page} pages={d.pages} total={d.total} pageSize={d.page_size} onPage={setPage} noun="sites" />}
    </ChartCard>
  );
}
