import { useState, type ReactNode } from 'react';
import { count, NA } from '../format';
import { LEVEL_TABS, type KpiDef } from '../kpis';
import { availabilityTone } from '../status';
import type { HierarchyLevel, KpiFilterOptions, KpiGroupRow, KpiSummary } from '../types';
import type { useKpiFilters } from '../useKpiFilters';
import { SitesTable } from './DrillDown';
import { TrendPanel } from './TrendPanel';
import { ChangeText, StatusPill, StatStrip, Tabs } from './Ui';
import { AVAILABILITY_STATUS } from './theme';
import { UnitTable } from './UnitTable';

type Level = HierarchyLevel | 'site';
type Filters = ReturnType<typeof useKpiFilters>;

/**
 * Circle-wise / CI-wise / IE-wise / Site-wise in one card (reference level tabs). A unit opens the next level with the
 * filters narrowed to it (as the drill-down does), so every view follows.
 */
export function LevelCard({ f, query, s, kpi, title, note, siteSort = 'availability', siteBuckets = null }: {
  f: Filters; query: URLSearchParams; s: KpiSummary; kpi: KpiDef | null; title: (level: string) => string; note?: ReactNode; siteSort?: string; siteBuckets?: string[] | null;
}) {
  const [level, setLevel] = useState<Level>('circle');
  const open = (row: KpiGroupRow) => {
    if (level === 'circle') { f.update({ project: [row.project], circle: [row.circle], ci: null, ie: null, site: null }); setLevel('ci'); }
    else if (level === 'ci') { f.update({ ci: [row.key], ie: null, site: null }); setLevel('ie'); }
    else if (level === 'ie') { f.update({ ie: [row.key], site: null }); setLevel('site'); }
  };
  const name = LEVEL_TABS.find(([l]) => l === level)![1];
  return (
    <section className="akp-card akp-pad" aria-label={title(name)}>
      <Tabs small label="Level" items={LEVEL_TABS} value={level} onChange={setLevel} />
      {level === 'site'
        ? <SitesTable bare key={`${query}`} query={query} defaultSort={siteSort} buckets={siteBuckets} title={title(name)} />
        : <UnitTable bare level={level} query={query} previous={s.previous_period} kpi={kpi} total={{ current: s.current, previous: s.previous }} onOpen={open}
            title={title(name)} note={note} />}
    </section>
  );
}

/** Buckets of a KPI's site list within the page's bucket filter (both existing); null = no limit. */
function listBuckets(kpi: KpiDef, options: KpiFilterOptions, chosen: string[]) {
  const own = kpi.siteBuckets?.(options);
  if (!own) return null;
  return chosen.length ? own.filter((b) => chosen.includes(b)) : own;
}

/**
 * One KPI (reference KPI page): this period against the previous one, the units ranked by it with their previous value
 * and change and the weakest as bars, its trend, and (for the threshold KPIs) its site list.
 */
export function KpiView({ kpi, s, f, query, options, sites, reason }: {
  kpi: KpiDef; s: KpiSummary; f: Filters; query: URLSearchParams; options: KpiFilterOptions; sites: string; reason?: string;
}) {
  const cur = (s.current?.[kpi.key] as number | null) ?? null;
  const prev = (s.previous?.[kpi.key] as number | null) ?? null;
  const items: { label: string; value: ReactNode; sub?: ReactNode }[] = [
    { label: 'This period', value: kpi.format(cur), sub: cur == null ? reason ?? 'Not available for this period' : s.period?.label },
    { label: 'Previous period', value: s.previous ? kpi.format(prev) : NA, sub: s.previous_period?.label ?? 'No comparison period' },
    { label: 'Change', value: <ChangeText current={cur} previous={prev} unit={kpi.unit} higherIsBetter={kpi.higherIsBetter} />, sub: kpi.unit === 'pts' ? 'percentage points' : 'relative change' },
  ];
  if (kpi.id === 'availability') {
    const tone = availabilityTone(cur);
    items.push({ label: 'SLA threshold', value: '98.5%', sub: 'existing threshold' }, { label: 'Status', value: <StatusPill tone={tone}>{AVAILABILITY_STATUS[tone]}</StatusPill> });
  } else if (kpi.id === 'outage') {
    items.push({ label: 'Outage minutes', value: count(s.current?.outage_minutes == null ? null : Math.round(s.current.outage_minutes)), sub: 'this period' });
  } else {
    items.push({ label: `${sites} with a value`, value: count(s.current?.sites_with_values), sub: 'sites with availability in the period' });
  }
  const buckets = listBuckets(kpi, options, f.values.bucket);
  return (
    <>
      <StatStrip label={`${kpi.name}: this period against the previous`} items={items} />
      <p className="akp-note" aria-label={`How ${kpi.name} is calculated`}>{kpi.definition(sites)}</p>
      <LevelCard f={f} query={query} s={s} kpi={kpi} siteSort={kpi.siteSort} title={(level) => `${level} · ${kpi.name}`}
        note={`${s.period?.label ?? ''}${s.previous_period ? ` vs ${s.previous_period.label}` : ''} · rank 1 = ${kpi.higherIsBetter ? 'highest' : 'lowest'} value`} />
      <TrendPanel query={query} kind={kpi.trend} period={s.period?.label} title={`${kpi.name} trend`} />
      {buckets && <SitesTable key={`list-${query}`} query={query} defaultSort={kpi.siteSort} buckets={buckets} title={`Site list – ${kpi.name}`} />}
    </>
  );
}
