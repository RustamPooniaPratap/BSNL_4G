import { formatNumber } from '../../lib/format';

/** Formatting of All KPI's values: null is "Not available", never 0. */
export const NA = 'Not available';
export const pct = (v: number | null | undefined, digits = 2) => (v == null ? NA : `${v.toFixed(digits)}%`);
export const count = (v: number | null | undefined) => (v == null ? NA : formatNumber(v));
export const hours = (v: number | null | undefined) => (v == null ? NA : `${formatNumber(Math.round(v * 10) / 10)} h`);
export const minutes = (v: number | null | undefined) => (v == null ? NA : `${formatNumber(Math.round(v))} min`);

/** Class of a numeric table cell or header: right-aligned, tabular figures. */
export const NUM = 'text-right tabular-nums';

/** Change against the previous period: an arrow direction and text; null when either value is missing. */
export function change(current: number | null | undefined, previous: number | null | undefined, unit: 'pts' | '%' = '%') {
  if (current == null || previous == null) return null;
  const diff = current - previous;
  if (unit === 'pts') return { diff, text: `${diff > 0 ? '+' : ''}${diff.toFixed(2)} pts` };
  if (!previous) return { diff, text: diff ? `${diff > 0 ? '+' : ''}${formatNumber(diff)}` : 'No change' };
  return { diff, text: `${diff > 0 ? '+' : ''}${((100 * diff) / previous).toFixed(1)}%` };
}
