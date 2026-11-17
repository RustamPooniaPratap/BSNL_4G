import { useCallback, useMemo } from 'react';
import { useSearchParams } from 'react-router-dom';
import { usePopulation } from '../../context/population';

/** Filters of the All KPI's page, kept in the URL so tabs, drill-down and reloads keep them. Multi-values are comma-separated. */
export const MULTI_KEYS = ['project', 'circle', 'ci', 'ie', 'site', 'bucket', 'final_bucket', 'responsibility'] as const;
export type MultiKey = (typeof MULTI_KEYS)[number];
/** The views of the KPI menu (the `tab` URL parameter; an unknown or removed view, e.g. `completeness`, opens the overview). */
export const TABS = ['overview', 'trends', 'availability', 'outage', 'usd', 'nsla', 'below_98_5', 'below_60', 'ranking', 'rca', 'drilldown'] as const;
export type KpiTab = (typeof TABS)[number];

const split = (v: string | null) => (v ? v.split(',').filter(Boolean) : []);

export function useKpiFilters() {
  const [params, setParams] = useSearchParams();
  // The global population (On-Air / O&M Start): sent with every All KPI's request, so a change refetches everything.
  const { scope } = usePopulation();
  const tab: KpiTab = (TABS as readonly string[]).includes(params.get('tab') ?? '') ? (params.get('tab') as KpiTab) : 'overview';
  const values = useMemo(() => Object.fromEntries(MULTI_KEYS.map((k) => [k, split(params.get(k))])) as Record<MultiKey, string[]>, [params]);
  const dateFrom = params.get('date_from') ?? '';
  const dateTo = params.get('date_to') ?? '';

  /** Query of the API: the population and the filters (not the tab or drill-down state). */
  const query = useMemo(() => {
    const q = new URLSearchParams({ scope });
    if (dateFrom) q.set('date_from', dateFrom);
    if (dateTo) q.set('date_to', dateTo);
    for (const k of MULTI_KEYS) if (values[k].length) q.set(k, values[k].join(','));
    return q;
  }, [dateFrom, dateTo, values, scope]);

  const update = useCallback((changes: Record<string, string | string[] | null>) => setParams((cur) => {
    const next = new URLSearchParams(cur);
    for (const [k, v] of Object.entries(changes)) {
      const text = Array.isArray(v) ? v.join(',') : v;
      if (text) next.set(k, text); else next.delete(k);
    }
    return next;
  }, { replace: true }), [setParams]);

  /** A parent filter changed: its children are cleared (Circle → CI/Cluster → IE → Site). */
  const setMulti = useCallback((key: MultiKey, v: string[]) => {
    const children: Record<string, MultiKey[]> = { project: ['ci', 'ie', 'site'], circle: ['ci', 'ie', 'site'], ci: ['ie', 'site'], ie: ['site'] };
    update({ [key]: v, ...Object.fromEntries((children[key] ?? []).map((c) => [c, null])) });
  }, [update]);

  const reset = useCallback(() => setParams(new URLSearchParams(tab === 'overview' ? {} : { tab }), { replace: true }), [setParams, tab]);
  const active = !!dateFrom || !!dateTo || MULTI_KEYS.some((k) => values[k].length);
  return { params, tab, values, dateFrom, dateTo, query, update, setMulti, reset, active, scope };
}
