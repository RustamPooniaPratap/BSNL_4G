/**
 * Circle comparison on the uptime and outage charts.
 *
 * The API returns, beside the per-report-type values, one series per circle within a network
 * (`by_circle` / `outage_by_circle`, keyed "<report type>|<circle>"). These helpers pick the selected
 * series and reshape a response so the existing chart views draw one line per circle. Values the API
 * reports as null (no data) stay null and are drawn as gaps.
 */
import type { CircleSeriesInfo, MonthlyResponse, TrendResponse } from '../types';

/** Distinct, colour-blind-friendly series colours, assigned by a fixed order so a circle keeps its colour on every page. */
const PALETTE = ['#2563eb', '#dc2626', '#059669', '#d97706', '#7c3aed', '#0891b2', '#db2777', '#65a30d', '#ea580c', '#4f46e5', '#0d9488', '#a16207', '#475569'];

export const shortType = (type: string) => (type === '4G Saturation' ? '4G' : type);
export const circleKey = (reportType: string, circle: string) => `${reportType}|${circle}`;
export const circleLabel = (key: string) => {
  const [type, circle] = key.split('|');
  return `${circle} · ${shortType(type)}`;
};

/** Every circle series the workbook has, in a stable order (4G first), from the filter options. */
export function allCircleKeys(circles: { value: string; report_types: string[] }[]) {
  const order = ['4G Saturation', 'LWE'];
  return circles
    .flatMap((c) => c.report_types.map((t) => circleKey(t, c.value)))
    .sort((a, b) => {
      const [ta, ca] = a.split('|');
      const [tb, cb] = b.split('|');
      return ((order.indexOf(ta) + 1 || 9) - (order.indexOf(tb) + 1 || 9)) || ca.localeCompare(cb);
    });
}

export const circleColor = (key: string, allKeys: string[]) => {
  const i = allKeys.indexOf(key);
  return PALETTE[(i < 0 ? allKeys.length : i) % PALETTE.length];
};

export interface CircleSeries {
  /** Selected series keys, in display order. */
  keys: string[];
  label: (key: string) => string;
  color: (key: string) => string;
}

/** The selected circle series that exist in this response (filters may have removed some). */
export function selectedSeries(available: CircleSeriesInfo[] | undefined, selected: string[], allKeys: string[]): CircleSeries | null {
  const present = new Set((available ?? []).map((c) => c.key));
  const keys = selected.filter((k) => present.has(k));
  return keys.length ? { keys, label: circleLabel, color: (k) => circleColor(k, allKeys) } : null;
}

const pick = (values: Record<string, number | null> | undefined, keys: string[]) =>
  Object.fromEntries(keys.map((k) => [k, values?.[k] ?? null]));

/** The trend response with the selected circles in place of the report types. */
export function trendByCircle(trend: TrendResponse, keys: string[]): TrendResponse {
  return {
    ...trend,
    report_types: keys,
    series: trend.series.map((p) => ({ ...p, by_report_type: pick(p.by_circle, keys), outage_by_report_type: pick(p.outage_by_circle, keys) })),
    weeks: trend.weeks.map((w) => ({ ...w, by_report_type: pick(w.by_circle, keys), outage_by_report_type: pick(w.outage_by_circle, keys) })),
  };
}

export function monthlyByCircle(monthly: MonthlyResponse, keys: string[]): MonthlyResponse {
  return {
    ...monthly,
    report_types: keys,
    months: monthly.months.map((m) => ({ ...m, by_report_type: pick(m.by_circle, keys), outage_by_report_type: pick(m.outage_by_circle, keys) })),
    overall: { ...monthly.overall, by_report_type: {} },
  };
}

/** The starting choice draws this many circles; more can be chosen (a note then suggests the heatmap). */
export const MAX_CIRCLES = 4;

/**
 * The circles to draw from the URL (`series`), those present in the data. Without a choice in the
 * URL, ``fallback`` is used (at most MAX_CIRCLES, lowest month-to-date uptime first); never all circles.
 */
export function parseSelection(param: string | null, available: string[], fallback: string[] = []): string[] {
  if (param === 'none') return [];
  if (param) return param.split(',').filter((k) => available.includes(k));
  return fallback.filter((k) => available.includes(k)).slice(0, MAX_CIRCLES);
}

/** The circles with the lowest month-to-date uptime (circles without a value last), as a starting choice. */
export function lowestCircles(circles: { report_type: string; circle: string; mtd_uptime_pct: number | null }[], count = MAX_CIRCLES): string[] {
  return [...circles]
    .sort((a, b) => (a.mtd_uptime_pct ?? Infinity) - (b.mtd_uptime_pct ?? Infinity))
    .slice(0, count)
    .map((c) => circleKey(c.report_type, c.circle));
}
