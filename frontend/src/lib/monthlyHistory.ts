import type { MonthlyResponse, MonthPoint } from '../types';

/** True for a month of imported historical totals (Excel source), false for one calculated from daily records. */
export const isHistorical = (m: Pick<MonthPoint, 'source'>) => m.source === 'historical_import';

/** A month calculated from daily records (not historical, not an empty gap month). */
export const isCalculated = (m: Pick<MonthPoint, 'source' | 'gap'>) => !m.gap && !isHistorical(m);

/** Where each month of a chart comes from: imported historical totals, the daily records, or neither (an empty gap). */
export type MonthKind = 'historical' | 'daily' | 'gap';
export const monthKind = (m: Pick<MonthPoint, 'source' | 'gap'>): MonthKind => (m.gap ? 'gap' : isHistorical(m) ? 'historical' : 'daily');

const nextKey = (key: string) => {
  const [y, m] = key.split('-').map(Number);
  return m === 12 ? `${y + 1}-01` : `${y}-${String(m + 1).padStart(2, '0')}`;
};
const labelOf = (key: string) => {
  const [y, m] = key.split('-').map(Number);
  return `${new Date(y, m - 1, 1).toLocaleString('en-US', { month: 'short' })}-${String(y).slice(2)}`;
};

/** An empty point for a month without data: every value null (a break in the line, never zero). */
function gapMonth(key: string): MonthPoint {
  const [y, m] = key.split('-').map(Number);
  return {
    key, label: labelOf(key), start: `${key}-01`, days: new Date(y, m, 0).getDate(), partial: false, sites_in_scope: 0, sites_reported: 0,
    uptime_pct: null, uptime_pct_blank_as_zero: null, change_pts: null, by_report_type: {}, outage_minutes: null, outage_by_report_type: {},
    by_circle: {}, outage_by_circle: {}, gap: true,
  };
}

/**
 * The monthly trend with the imported historical months in front of the calculated ones, oldest first, limited to the
 * picked months (``selected``; empty: every month). Without a pick, a calendar month missing between the first and last
 * month shown (e.g. LWE Jul-Aug 26, held) becomes an empty point, so the chart shows the gap instead of joining across
 * it. Nothing is invented: a gap point has no value. The response's ``overall`` stays the calculated months' figure.
 */
export function withHistory(monthly: MonthlyResponse | null, selected: string[]): MonthlyResponse | null {
  if (!monthly) return monthly;
  const months = [...(monthly.historical_months ?? []), ...monthly.months];
  if (selected.length) return { ...monthly, months: months.filter((m) => selected.includes(m.key)) };
  const filled: MonthPoint[] = [];
  for (const m of months) {
    const previous = filled.at(-1);
    if (previous) {
      for (let key = nextKey(previous.key); key < m.key; key = nextKey(key)) filled.push(gapMonth(key));
    }
    filled.push(m);
  }
  return { ...monthly, months: filled };
}
