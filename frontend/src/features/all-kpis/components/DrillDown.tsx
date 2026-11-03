import { useState } from 'react';
import { ChevronLeft, ChevronRight, Search } from 'lucide-react';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table';
import { ChartCard } from '../../../components/dashboard/ChartCard';
import { useApiQuery } from '../../../hooks/useApiQuery';
import { fetchKpiHierarchy, fetchKpiSites } from '../api';
import { count, hours, pct } from '../format';
import type { HierarchyLevel, KpiGroupRow } from '../types';
import type { useKpiFilters } from '../useKpiFilters';

type Level = HierarchyLevel | 'site';
const NAMES: Record<Level, string> = { circle: 'Circle', ci: 'CI / Cluster', ie: 'IE', site: 'Site' };
const project = (p: string) => (p === '4G Saturation' ? '4G' : p);

/**
 * Circle → CI/Cluster → IE → Site. A click narrows the filters to the row (so every tab follows) and opens the next
 * level; the breadcrumb goes back. An IE is always the IE of one CI (the same name can work under several CIs).
 */
export function DrillDown({ f }: { f: ReturnType<typeof useKpiFilters> }) {
  const level: Level = (['circle', 'ci', 'ie', 'site'] as const).find((l) => l === f.params.get('level')) ?? 'circle';
  const go = (next: Level, changes: Record<string, string | string[] | null> = {}) => f.update({ ...changes, level: next === 'circle' ? null : next });
  const open = (row: KpiGroupRow) => {
    if (level === 'circle') go('ci', { project: [row.project], circle: [row.circle], ci: null, ie: null, site: null });
    else if (level === 'ci') go('ie', { ci: [row.key], ie: null, site: null });
    else if (level === 'ie') go('site', { ie: [row.key], site: null });
  };
  const crumbs: { label: string; to: Level; clear: Record<string, null> }[] = [{ label: 'All circles', to: 'circle', clear: { project: null, circle: null, ci: null, ie: null, site: null } }];
  if (level !== 'circle' && f.values.circle.length) crumbs.push({ label: `${f.values.circle.join(', ')}${f.values.project.length ? ` (${f.values.project.map(project).join(', ')})` : ''}`, to: 'ci', clear: { ci: null, ie: null, site: null } as Record<string, null> });
  if ((level === 'ie' || level === 'site') && f.values.ci.length) crumbs.push({ label: f.values.ci.map((k) => k.split('::')[1]).join(', '), to: 'ie', clear: { ie: null, site: null } as Record<string, null> });
  if (level === 'site' && f.values.ie.length) crumbs.push({ label: f.values.ie.map((k) => k.split('::')[2]).join(', '), to: 'site', clear: {} as Record<string, null> });
  return (
    <div className="space-y-3">
      <nav aria-label="Drill-down" className="flex flex-wrap items-center gap-1 text-sm">
        {level !== 'circle' && (
          <Button size="sm" variant="outline" className="mr-2 h-7" onClick={() => {
            const back = crumbs[crumbs.length - 2];
            go(back.to, back.clear);
          }}><ChevronLeft /> Back</Button>
        )}
        {crumbs.map((c, i) => (
          <span key={c.label} className="inline-flex items-center gap-1">
            {i > 0 && <ChevronRight className="size-3.5 text-muted-foreground" aria-hidden="true" />}
            {i === crumbs.length - 1 ? <span className="font-semibold">{c.label}</span>
              : <button type="button" className="text-primary hover:underline" onClick={() => go(c.to, c.clear)}>{c.label}</button>}
          </span>
        ))}
        <Badge variant="outline" className="ml-2">{NAMES[level]}-wise</Badge>
      </nav>
      {level === 'site' ? <SitesTable key={f.query.toString()} query={f.query} /> : <GroupTable level={level} query={f.query} onOpen={open} />}
    </div>
  );
}

function GroupTable({ level, query, onOpen }: { level: HierarchyLevel; query: URLSearchParams; onOpen: (row: KpiGroupRow) => void }) {
  const params = new URLSearchParams(query);
  params.set('level', level);
  const data = useApiQuery(`allkpis-hierarchy-${params}`, (signal) => fetchKpiHierarchy(params, signal));
  const rows = data.data?.rows ?? [];
  return (
    <ChartCard title={`${NAMES[level]}-wise performance`} loading={data.loading} error={data.error} empty={!rows.length}
      description="Select a row for the next level. USD and NSLA: O&M Start sites; availability and thresholds: On-Air sites.">
      <div className="overflow-x-auto">
        <Table className="text-xs">
          <TableHeader>
            <TableRow>
              <TableHead>{NAMES[level]}</TableHead>{level !== 'circle' && <TableHead>Circle</TableHead>}<TableHead>Project</TableHead>
              <TableHead className="text-right">Total sites</TableHead><TableHead className="text-right">On-Air</TableHead><TableHead className="text-right">O&amp;M Start</TableHead>
              <TableHead className="text-right">Availability</TableHead><TableHead className="text-right">Outage</TableHead><TableHead className="text-right">USD</TableHead>
              <TableHead className="text-right">NSLA</TableHead><TableHead className="text-right">&lt; 98.5%</TableHead><TableHead className="text-right">&lt; 60%</TableHead>
              <TableHead className="text-right">Coverage</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {rows.map((r) => (
              <TableRow key={`${r.project}|${r.key}`} className="cursor-pointer hover:bg-muted/40" onClick={() => onOpen(r)}>
                <TableCell className="font-medium">
                  <button type="button" className="text-left text-primary hover:underline" aria-label={`Open ${NAMES[level]} ${r[level === 'circle' ? 'circle' : level] ?? ''} (${project(r.project)})`}
                    onClick={(e) => { e.stopPropagation(); onOpen(r); }}>{level === 'circle' ? r.circle : level === 'ci' ? r.ci : r.ie}</button>
                  {level === 'ie' && <span className="block text-[11px] text-muted-foreground">CI: {r.ci}</span>}
                </TableCell>
                {level !== 'circle' && <TableCell>{r.circle}</TableCell>}
                <TableCell>{project(r.project)}</TableCell>
                <TableCell className="text-right tabular-nums">{count(r.total_sites)}</TableCell>
                <TableCell className="text-right tabular-nums">{count(r.on_air_sites)}</TableCell>
                <TableCell className="text-right tabular-nums">{count(r.om_start_sites)}</TableCell>
                <TableCell className="text-right tabular-nums">{pct(r.availability_pct, 3)}</TableCell>
                <TableCell className="text-right tabular-nums">{hours(r.outage_hours)}</TableCell>
                <TableCell className="text-right tabular-nums">{count(r.usd_sites)}</TableCell>
                <TableCell className="text-right tabular-nums">{count(r.nsla_sites)}</TableCell>
                <TableCell className="text-right tabular-nums">{count(r.below_98_5_sites)}</TableCell>
                <TableCell className="text-right tabular-nums">{count(r.below_60_sites)}</TableCell>
                <TableCell className="text-right tabular-nums">{pct(r.coverage_pct, 1)}</TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </div>
    </ChartCard>
  );
}

const SORTS: [string, string][] = [['availability', 'Lowest availability'], ['-outage', 'Most outage'], ['days', 'Fewest days reported'], ['site_id', 'Site ID']];

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
      description={d ? `${count(d.total)} sites · page ${d.page} of ${d.pages}` : undefined}
      action={(
        <div className="flex flex-wrap items-center gap-2">
          <div className="relative">
            <Search className="absolute top-1/2 left-2 size-3.5 -translate-y-1/2 text-muted-foreground" aria-hidden="true" />
            <Input aria-label="Search sites" placeholder="Site ID or name" value={q} onChange={(e) => { setQ(e.target.value); setPage(1); }} className="h-8 w-44 pl-7 text-xs" />
          </div>
          <select aria-label="Sort sites" className="h-8 rounded-md border bg-background px-2 text-xs" value={sort} onChange={(e) => { setSort(e.target.value); setPage(1); }}>
            {SORTS.map(([v, l]) => <option key={v} value={v}>{l}</option>)}
          </select>
        </div>
      )}>
      <div className="overflow-x-auto">
        <Table className="text-xs">
          <TableHeader>
            <TableRow>
              <TableHead>Site ID</TableHead><TableHead>Name</TableHead><TableHead>Circle</TableHead><TableHead>CI / Cluster</TableHead><TableHead>IE</TableHead>
              <TableHead>On-Air</TableHead><TableHead>O&amp;M Start</TableHead><TableHead className="text-right">Availability</TableHead><TableHead className="text-right">Outage</TableHead>
              <TableHead>SLA bucket</TableHead><TableHead>USD</TableHead><TableHead>NSLA</TableHead><TableHead className="text-right">Days reported</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {d?.rows.map((r) => (
              <TableRow key={`${r.project}|${r.site_id}`}>
                <TableCell className="font-medium">{r.site_id}</TableCell><TableCell className="max-w-40 truncate">{r.site_name || '—'}</TableCell>
                <TableCell>{r.circle} · {project(r.project)}</TableCell><TableCell>{r.ci}</TableCell><TableCell>{r.ie}</TableCell>
                <TableCell>{r.on_air ? 'Yes' : 'No'}</TableCell><TableCell>{r.om_start == null ? 'Not available' : r.om_start ? 'Yes' : 'No'}</TableCell>
                <TableCell className="text-right tabular-nums">{pct(r.availability_pct, 3)}</TableCell><TableCell className="text-right tabular-nums">{hours(r.outage_hours)}</TableCell>
                <TableCell>{r.bucket_label ?? 'No value'}</TableCell>
                <TableCell>{r.usd == null ? '—' : r.usd ? 'Yes' : 'No'}</TableCell><TableCell>{r.nsla == null ? '—' : r.nsla ? 'Yes' : 'No'}</TableCell>
                <TableCell className={`text-right tabular-nums ${r.days_reported < r.days_expected ? 'text-amber-700' : ''}`}>{r.days_reported} / {r.days_expected}</TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </div>
      {d && d.pages > 1 && (
        <div className="mt-2 flex items-center justify-end gap-2 text-xs">
          <Button size="sm" variant="outline" className="h-7" disabled={page <= 1} onClick={() => setPage((p) => p - 1)}>Previous</Button>
          <span>Page {d.page} of {d.pages}</span>
          <Button size="sm" variant="outline" className="h-7" disabled={page >= d.pages} onClick={() => setPage((p) => p + 1)}>Next</Button>
        </div>
      )}
    </ChartCard>
  );
}
