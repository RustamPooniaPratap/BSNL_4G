import { useState } from 'react';
import { ChevronLeft, ChevronRight, Search } from 'lucide-react';
import { TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table';
import { cn } from '@/lib/utils';
import { usePopulation } from '../../../context/population';
import { useApiQuery } from '../../../hooks/useApiQuery';
import { fetchKpiHierarchy, fetchKpiSites } from '../api';
import { count, hours, pct } from '../format';
import { availabilityTone, problemTone, toneText } from '../status';
import type { HierarchyLevel, KpiGroupRow } from '../types';
import type { useKpiFilters } from '../useKpiFilters';
import { KpiTable, Pager } from './KpiTable';
import { Panel } from './Ui';

type Level = HierarchyLevel | 'site';
const LEVELS: Level[] = ['circle', 'ci', 'ie', 'site'];
const NAMES: Record<Level, string> = { circle: 'Circle', ci: 'CI / Cluster', ie: 'IE', site: 'Site' };
const project = (p: string) => (p === '4G Saturation' ? '4G' : p);

/**
 * Circle → CI/Cluster → IE → Site. A click narrows the filters to the row (so every view follows) and opens the next
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
    <>
      <section className="akp-card akp-pad flex flex-wrap items-center gap-x-4 gap-y-2" aria-label="Drill-down position">
        {level !== 'circle' && (
          <button type="button" className="akp-btn sm" onClick={() => {
            const back = crumbs[crumbs.length - 2];
            go(back.to, back.clear);
          }}><ChevronLeft className="size-3.5" aria-hidden="true" /> Back</button>
        )}
        <nav aria-label="Drill-down" className="akp-crumb min-w-0">
          {crumbs.map((c, i) => (
            <span key={c.label} className="inline-flex min-w-0 items-center gap-1">
              {i > 0 && <span aria-hidden="true">›</span>}
              {c.field && <span className="akp-note">{c.field}</span>}
              {i === crumbs.length - 1 ? <span className="truncate font-semibold" style={{ color: 'var(--akp-ink)' }} aria-current="location">{c.label}</span>
                : <button type="button" className="truncate" onClick={() => go(c.to, c.clear)}>{c.label}</button>}
            </span>
          ))}
        </nav>
        <ol aria-label="Hierarchy level" className="akp-tabs small sm:ml-auto" style={{ borderBottom: 0 }}>
          {LEVELS.map((l, i) => (
            <li key={l} aria-current={i === step ? 'step' : undefined}>
              <span className="inline-flex h-[34px] items-center px-2.5 text-[13px]"
                style={i === step ? { color: 'var(--akp-accent)', fontWeight: 650, borderBottom: '2px solid var(--akp-accent)' } : { color: i < step ? 'var(--akp-ink)' : 'var(--akp-ink2)' }}>
                {NAMES[l]}-wise
              </span>
            </li>
          ))}
        </ol>
      </section>
      {level === 'site' ? <SitesTable key={f.query.toString()} query={f.query} /> : <GroupTable level={level} query={f.query} onOpen={open} />}
    </>
  );
}

function GroupTable({ level, query, onOpen }: { level: HierarchyLevel; query: URLSearchParams; onOpen: (row: KpiGroupRow) => void }) {
  const params = new URLSearchParams(query);
  params.set('level', level);
  const data = useApiQuery(`allkpis-hierarchy-${params}`, (signal) => fetchKpiHierarchy(params, signal));
  const { sitesLabel } = usePopulation();
  const rows = data.data?.rows ?? [];
  const next = NAMES[LEVELS[LEVELS.indexOf(level) + 1]];
  return (
    <Panel title={`${NAMES[level]}-wise performance`} loading={data.loading} error={data.error} empty={!rows.length}
      note={`${count(rows.length)} ${rows.length === 1 ? 'row' : 'rows'} · select a ${NAMES[level]} to open its ${next} view. Population: ${sitesLabel}.`}>
      <KpiTable>
        <TableHeader>
          <TableRow>
            <TableHead>{NAMES[level]}</TableHead>{level !== 'circle' && <TableHead>Circle</TableHead>}<TableHead>Project</TableHead>
            <TableHead className="r">Availability</TableHead><TableHead className="r">Outage</TableHead><TableHead className="r">USD Sites</TableHead>
            <TableHead className="r">NSLA Sites</TableHead><TableHead className="r">&lt; 98.5%</TableHead><TableHead className="r">&lt; 60%</TableHead>
            <TableHead className="w-6" aria-hidden="true" />
          </TableRow>
        </TableHeader>
        <TableBody>
          {rows.map((r) => (
            <TableRow key={`${r.project}|${r.key}`} className="group/row cursor-pointer" onClick={() => onOpen(r)}>
              <TableCell className="font-medium">
                <button type="button" className="akp-link" aria-label={`Open ${NAMES[level]} ${r[level === 'circle' ? 'circle' : level] ?? ''} (${project(r.project)})`}
                  onClick={(e) => { e.stopPropagation(); onOpen(r); }}>{level === 'circle' ? r.circle : level === 'ci' ? r.ci : r.ie}</button>
                {level === 'ie' && <span className="sub">CI: {r.ci}</span>}
              </TableCell>
              {level !== 'circle' && <TableCell>{r.circle}</TableCell>}
              <TableCell>{project(r.project)}</TableCell>
              <TableCell className={cn('r', toneText(availabilityTone(r.availability_pct)))}>{pct(r.availability_pct)}</TableCell>
              <TableCell className="r">{hours(r.outage_hours)}</TableCell>
              <TableCell className="r">{count(r.usd_sites)}</TableCell>
              <TableCell className="r">{count(r.nsla_sites)}</TableCell>
              <TableCell className="r">{count(r.below_98_5_sites)}</TableCell>
              <TableCell className={cn('r', toneText(problemTone(r.below_60_sites, 'bad')))}>{count(r.below_60_sites)}</TableCell>
              <TableCell className="px-1 muted"><ChevronRight className="size-3.5 opacity-40 group-hover/row:opacity-100" aria-hidden="true" /></TableCell>
            </TableRow>
          ))}
        </TableBody>
      </KpiTable>
    </Panel>
  );
}

const SORTS: [string, string][] = [['availability', 'Lowest availability'], ['-outage', 'Most outage'], ['site_id', 'Site ID']];
const yesNo = (v: boolean | null, yesClass: string) => (v == null ? <span className="muted">—</span> : v ? <span className={yesClass}>Yes</span> : <span className="muted">No</span>);

/**
 * Site-wise table: server-side search, sort and paging. `buckets` limits it to availability buckets through the
 * existing `bucket` filter (e.g. the "Sites < 60%" list); an empty list means no bucket matches the page's filters.
 */
export function SitesTable({ query, defaultSort = 'availability', title = 'Site-wise performance', buckets = null, bare }: {
  query: URLSearchParams; defaultSort?: string; title?: string; buckets?: string[] | null; bare?: boolean;
}) {
  const [page, setPage] = useState(1);
  const [sort, setSort] = useState(defaultSort);
  const [q, setQ] = useState('');
  const params = new URLSearchParams(query);
  params.set('page', String(page));
  params.set('sort', sort);
  if (q.trim()) params.set('q', q.trim());
  if (buckets) params.set('bucket', buckets.join(','));
  const none = buckets != null && !buckets.length;
  const data = useApiQuery(none ? null : `allkpis-sites-${params}`, (signal) => fetchKpiSites(params, signal));
  const d = data.data;
  return (
    <Panel title={title} bare={bare} loading={data.loading} error={data.error} empty={none || !d?.rows.length}
      emptyMessage={none ? 'No site of the selected availability buckets falls in this list.' : q.trim() ? `No site matches "${q.trim()}".` : undefined}
      note={d && !none ? `${count(d.total)} sites · availability and outage over the selected period` : undefined}
      action={(
        <>
          <div className="relative">
            <Search className="absolute top-1/2 left-2.5 size-3.5 -translate-y-1/2" style={{ color: 'var(--akp-ink2)' }} aria-hidden="true" />
            <input aria-label="Search sites" placeholder="Site ID or name" value={q} onChange={(e) => { setQ(e.target.value); setPage(1); }} className="akp-input w-48 pl-8" />
          </div>
          <select aria-label="Sort sites" className="akp-input" value={sort} onChange={(e) => { setSort(e.target.value); setPage(1); }}>
            {SORTS.map(([v, l]) => <option key={v} value={v}>{l}</option>)}
          </select>
        </>
      )}>
      <KpiTable>
        <TableHeader>
          <TableRow>
            <TableHead>Site ID</TableHead><TableHead>Name</TableHead><TableHead>Circle</TableHead><TableHead>CI / Cluster</TableHead><TableHead>IE</TableHead>
            <TableHead className="r">Availability</TableHead><TableHead className="r">Outage</TableHead>
            <TableHead>SLA bucket</TableHead><TableHead>USD Site</TableHead><TableHead>NSLA Site</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {d?.rows.map((r) => (
            <TableRow key={`${r.project}|${r.site_id}`}>
              <TableCell className="font-medium">{r.site_id}</TableCell>
              <TableCell className="max-w-48 truncate" title={r.site_name || undefined}>{r.site_name || '—'}</TableCell>
              <TableCell>{r.circle} <span className="muted">· {project(r.project)}</span></TableCell>
              <TableCell className="max-w-40 truncate" title={r.ci}>{r.ci}</TableCell>
              <TableCell className="max-w-40 truncate" title={r.ie}>{r.ie}</TableCell>
              <TableCell className={cn('r', toneText(availabilityTone(r.availability_pct)))}>{r.availability_pct == null ? <span className="muted">No value</span> : pct(r.availability_pct)}</TableCell>
              <TableCell className="r">{hours(r.outage_hours)}</TableCell>
              <TableCell>{r.bucket_label ?? <span className="muted">No value</span>}</TableCell>
              <TableCell>{yesNo(r.usd, 't-warn')}</TableCell>
              <TableCell>{yesNo(r.nsla, 't-crit')}</TableCell>
            </TableRow>
          ))}
        </TableBody>
      </KpiTable>
      {d && !none && <Pager page={d.page} pages={d.pages} total={d.total} pageSize={d.page_size} onPage={setPage} noun="sites" />}
    </Panel>
  );
}
