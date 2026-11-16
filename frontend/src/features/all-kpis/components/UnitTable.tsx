import { useState, type ReactNode } from 'react';
import { TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table';
import { cn } from '@/lib/utils';
import { useApiQuery } from '../../../hooks/useApiQuery';
import { fetchKpiHierarchy } from '../api';
import { count, minutes, pct } from '../format';
import type { KpiDef } from '../kpis';
import { availabilityTone, problemTone, toneText } from '../status';
import type { HierarchyLevel, KpiGroupRow, KpiPeriod, KpiValues } from '../types';
import { KpiTable } from './KpiTable';
import { Bars, ChangeText, Panel, StatusPill } from './Ui';
import { AVAILABILITY_STATUS } from './theme';

const NAMES: Record<HierarchyLevel, string> = { circle: 'Circle', ci: 'CI / Cluster', ie: 'IE' };
const project = (p: string) => (p === '4G Saturation' ? '4G' : p);
const rowKey = (r: KpiGroupRow) => `${r.project}|${r.key}`;
const nameOf = (level: HierarchyLevel, r: KpiGroupRow) => (level === 'circle' ? r.circle : level === 'ci' ? r.ci ?? r.key : r.ie ?? r.key);
const subOf = (level: HierarchyLevel, r: KpiGroupRow) => (level === 'circle' ? project(r.project) : level === 'ci' ? `${r.circle} · ${project(r.project)}` : `CI ${r.ci} · ${r.circle}`);

/** Ranks by a value of the API (1 = best; rows without a value are not ranked). Ordering only: no value is computed. */
function ranks(rows: KpiGroupRow[], key: keyof KpiValues, higherIsBetter: boolean, level: HierarchyLevel) {
  const valued = rows.filter((r) => r[key] != null);
  valued.sort((a, b) => {
    const d = (a[key] as number) - (b[key] as number);
    return (higherIsBetter ? -d : d) || nameOf(level, a).localeCompare(nameOf(level, b));
  });
  return new Map(valued.map((r, i) => [rowKey(r), i + 1]));
}

/** Previous-period query: the same filters with the comparison period of the summary (the existing endpoint, other dates). */
function previousParams(params: URLSearchParams, previous?: KpiPeriod) {
  if (!previous) return null;
  const p = new URLSearchParams(params);
  p.set('date_from', previous.start);
  p.set('date_to', previous.end);
  return p;
}

interface Column { id: string; head: ReactNode; num?: boolean; sort?: (r: KpiGroupRow) => number | string | null; cell: (r: KpiGroupRow) => ReactNode }

/**
 * Units of one level (Circle-wise, CI-wise, IE-wise) from /hierarchy/, ranked as in the reference report: with `kpi`
 * one KPI (value, previous, change, bar); without it the overview matrix of every KPI and the rank change against the
 * previous period. The total row is the summary of the selected filters. The weakest units are shaded.
 */
export function UnitTable({ level, query, previous, kpi, total, onOpen, title, note, bare }: {
  level: HierarchyLevel; query: URLSearchParams; previous?: KpiPeriod; kpi: KpiDef | null;
  total: { current: KpiValues | null; previous: KpiValues | null }; onOpen: (row: KpiGroupRow) => void; title: string; note?: ReactNode; bare?: boolean;
}) {
  const params = new URLSearchParams(query);
  params.set('level', level);
  const cur = useApiQuery(`allkpis-hierarchy-${params}`, (signal) => fetchKpiHierarchy(params, signal));
  const pp = previousParams(params, previous);
  const prev = useApiQuery(pp ? `allkpis-hierarchy-${pp}` : null, (signal) => fetchKpiHierarchy(pp!, signal));
  const rows = cur.data?.rows ?? [];
  const prevRows = new Map((prev.data?.rows ?? []).map((r) => [rowKey(r), r]));
  const rankKey: keyof KpiValues = kpi?.key ?? 'availability_pct';
  const better = kpi?.higherIsBetter ?? true;
  const rank = ranks(rows, rankKey, better, level);
  const prevRank = ranks([...prevRows.values()], rankKey, better, level);
  const [sort, setSort] = useState<{ id: string; desc: boolean }>({ id: 'rank', desc: false });

  const fmt = kpi?.format ?? pct;
  const nameCell = (r: KpiGroupRow) => (
    <>
      <button type="button" className="akp-link" aria-label={`Open ${NAMES[level]} ${nameOf(level, r)} (${project(r.project)})`} onClick={() => onOpen(r)}>{nameOf(level, r)}</button>
      <span className="sub">{subOf(level, r)}</span>
    </>
  );
  const rankCell = (r: KpiGroupRow) => rank.get(rowKey(r)) ?? <span className="muted">—</span>;
  const columns: Column[] = kpi ? [
    { id: 'rank', head: 'Rank', num: true, sort: (r) => rank.get(rowKey(r)) ?? null, cell: rankCell },
    { id: 'name', head: NAMES[level], sort: (r) => nameOf(level, r), cell: nameCell },
    { id: 'sites', head: 'Sites', num: true, sort: (r) => r.total_sites, cell: (r) => count(r.total_sites) },
    { id: 'value', head: kpi.name, num: true, sort: (r) => r[kpi.key] as number | null,
      cell: (r) => <span className={cn('font-semibold', toneText(kpi.tone(r[kpi.key] as number | null)))}>{fmt(r[kpi.key] as number | null)}</span> },
    { id: 'previous', head: 'Previous', num: true, sort: (r) => (prevRows.get(rowKey(r))?.[kpi.key] as number | null) ?? null,
      cell: (r) => <span className="muted">{previous ? (prevRows.has(rowKey(r)) ? fmt(prevRows.get(rowKey(r))![kpi.key] as number | null) : 'No data') : '—'}</span> },
    { id: 'change', head: 'Change', num: true, cell: (r) => <ChangeText current={r[kpi.key] as number | null} previous={(prevRows.get(rowKey(r))?.[kpi.key] as number | null) ?? null} unit={kpi.unit} higherIsBetter={kpi.higherIsBetter} /> },
    ...(kpi.id === 'availability' ? [{ id: 'status', head: 'Status', cell: (r: KpiGroupRow) => { const t = availabilityTone(r.availability_pct); return <StatusPill tone={t}>{AVAILABILITY_STATUS[t]}</StatusPill>; } }] : []),
  ] : [
    { id: 'rank', head: 'Rank', num: true, sort: (r) => rank.get(rowKey(r)) ?? null, cell: rankCell },
    { id: 'delta', head: <span title="Rank change against the previous period">Δ</span>, num: true, cell: (r) => {
      const [a, b] = [rank.get(rowKey(r)), prevRank.get(rowKey(r))];
      if (a == null || b == null) return <span className="muted">—</span>;
      const d = b - a;
      return <span className={cn('num', d > 0 && 'up-good', d < 0 && 'up-bad')} title={`Rank ${b} in the previous period`}>{d > 0 ? `▲ ${d}` : d < 0 ? `▼ ${-d}` : '–'}</span>;
    } },
    { id: 'name', head: NAMES[level], sort: (r) => nameOf(level, r), cell: nameCell },
    { id: 'sites', head: 'Sites', num: true, sort: (r) => r.total_sites, cell: (r) => count(r.total_sites) },
    { id: 'availability', head: 'Availability', num: true, sort: (r) => r.availability_pct, cell: (r) => <span className={cn('font-semibold', toneText(availabilityTone(r.availability_pct)))}>{pct(r.availability_pct)}</span> },
    { id: 'status', head: 'Status', cell: (r) => { const t = availabilityTone(r.availability_pct); return <StatusPill tone={t}>{AVAILABILITY_STATUS[t]}</StatusPill>; } },
    { id: 'nsla', head: 'NSLA Sites', num: true, sort: (r) => r.nsla_sites, cell: (r) => count(r.nsla_sites) },
    { id: 'usd', head: 'USD Sites', num: true, sort: (r) => r.usd_sites, cell: (r) => count(r.usd_sites) },
    { id: 'outage', head: 'Outage (min)', num: true, sort: (r) => r.outage_minutes, cell: (r) => minutes(r.outage_minutes) },
    { id: 'b985', head: '< 98.5%', num: true, sort: (r) => r.below_98_5_sites, cell: (r) => count(r.below_98_5_sites) },
    { id: 'b60', head: '< 60%', num: true, sort: (r) => r.below_60_sites, cell: (r) => <span className={toneText(problemTone(r.below_60_sites, 'bad'))}>{count(r.below_60_sites)}</span> },
  ];

  const col = columns.find((c) => c.id === sort.id && c.sort) ?? columns[0];
  const sorted = [...rows].sort((a, b) => {
    const [x, y] = [col.sort!(a), col.sort!(b)];
    if (x == null || y == null) return x == null && y == null ? 0 : x == null ? 1 : -1;  // no value: always last
    const d = typeof x === 'string' ? x.localeCompare(String(y)) : x - (y as number);
    return sort.desc ? -d : d;
  });
  const ranked = rank.size;
  const byRank = sort.id === 'rank' && !sort.desc;
  const shaded = (r: KpiGroupRow) => byRank && ranked >= 6 && (rank.get(rowKey(r)) ?? 0) > ranked - 3;
  const toggle = (id: string) => setSort((s) => ({ id, desc: s.id === id ? !s.desc : false }));

  const totalCells = (): ReactNode[] => {
    const t = total.current;
    if (!t) return [];
    if (kpi) {
      const [a, b] = [t[kpi.key] as number | null, (total.previous?.[kpi.key] as number | null) ?? null];
      return [<TableCell key="s" className="r">{count(t.total_sites)}</TableCell>, <TableCell key="v" className="r">{fmt(a)}</TableCell>,
        <TableCell key="p" className="r">{total.previous ? fmt(b) : '—'}</TableCell>,
        <TableCell key="c" className="r"><ChangeText current={a} previous={b} unit={kpi.unit} higherIsBetter={kpi.higherIsBetter} /></TableCell>,
        ...(kpi.id === 'availability' ? [<TableCell key="st"><StatusPill tone={availabilityTone(a)}>{AVAILABILITY_STATUS[availabilityTone(a)]}</StatusPill></TableCell>] : [])];
    }
    return [<TableCell key="s" className="r">{count(t.total_sites)}</TableCell>, <TableCell key="a" className="r">{pct(t.availability_pct)}</TableCell>,
      <TableCell key="st"><StatusPill tone={availabilityTone(t.availability_pct)}>{AVAILABILITY_STATUS[availabilityTone(t.availability_pct)]}</StatusPill></TableCell>,
      <TableCell key="n" className="r">{count(t.nsla_sites)}</TableCell>, <TableCell key="u" className="r">{count(t.usd_sites)}</TableCell>,
      <TableCell key="o" className="r">{minutes(t.outage_minutes)}</TableCell>, <TableCell key="b" className="r">{count(t.below_98_5_sites)}</TableCell>,
      <TableCell key="b6" className="r">{count(t.below_60_sites)}</TableCell>];
  };
  const lead = kpi ? 2 : 3;

  return (
    <Panel title={title} note={note} loading={cur.loading} error={cur.error} empty={!rows.length} label={title} bare={bare}>
      <KpiTable label={`${title} table`}>
        <TableHeader>
          <TableRow>
            {columns.map((c) => (
              <TableHead key={c.id} className={cn(c.num && 'r', c.sort && 'sort')}
                aria-sort={sort.id === c.id && c.sort ? (sort.desc ? 'descending' : 'ascending') : undefined}>
                {c.sort ? <button type="button" className="uppercase" onClick={() => toggle(c.id)}>{c.head}{sort.id === c.id ? (sort.desc ? ' ↓' : ' ↑') : ''}</button> : c.head}
              </TableHead>
            ))}
          </TableRow>
        </TableHeader>
        <TableBody>
          {sorted.map((r) => (
            <TableRow key={rowKey(r)} className={cn(shaded(r) && 'bottom')}>
              {columns.map((c) => <TableCell key={c.id} className={cn(c.num && 'r', c.id === 'name' && 'font-medium')}>{c.cell(r)}</TableCell>)}
            </TableRow>
          ))}
          {total.current && (
            <TableRow className="tot" aria-label="Total of the selected filters">
              <TableCell colSpan={lead}>Total · selected filters</TableCell>
              {totalCells()}
            </TableRow>
          )}
        </TableBody>
      </KpiTable>
      {kpi && <WeakestBars rows={rows} kpi={kpi} level={level} />}
      {!kpi && ranked >= 6 && <p className="akp-note mt-2">Ranked by availability (best first); the three lowest are shaded. Δ = rank change against the previous period.</p>}
    </Panel>
  );
}

/** The 15 weakest units of a KPI as horizontal bars (reference "bars"): availability against the 98.5% tick. */
function WeakestBars({ rows, kpi, level }: { rows: KpiGroupRow[]; kpi: KpiDef; level: HierarchyLevel }) {
  const valued = rows.filter((r) => r[kpi.key] != null && (kpi.higherIsBetter || (r[kpi.key] as number) > 0));
  if (valued.length < 2) return null;
  const weakest = [...valued].sort((a, b) => ((a[kpi.key] as number) - (b[kpi.key] as number)) * (kpi.higherIsBetter ? 1 : -1)).slice(0, 15);
  const values = weakest.map((r) => r[kpi.key] as number);
  // Availability bars start below the lowest value (a 0–100 scale would hide the differences); counts start at 0.
  const min = kpi.higherIsBetter ? Math.max(0, Math.min(90, Math.floor(Math.min(...values) - 1))) : 0;
  const max = kpi.higherIsBetter ? 100 : Math.max(...values);
  return (
    <div className="mt-4">
      <h4 className="akp-note mb-2 font-semibold uppercase tracking-[0.04em]">{kpi.higherIsBetter ? 'Lowest' : 'Highest'} {weakest.length} · {kpi.name}</h4>
      <Bars label={`${kpi.name}: weakest ${weakest.length}`} min={min} max={max} target={kpi.target}
        rows={weakest.map((r) => ({ key: rowKey(r), name: `${nameOf(level, r)} · ${project(r.project)}`, value: r[kpi.key] as number, display: kpi.format(r[kpi.key] as number) }))} />
    </div>
  );
}

