import { useCallback, useMemo } from 'react';
import { useSearchParams } from 'react-router-dom';
import type { FilterOptions, Scope } from '../types';

export type TrendView = 'daily' | 'weekly' | 'monthly';
export const TREND_VIEWS: TrendView[] = ['daily', 'weekly', 'monthly'];

/** The workbook's weeks of the reporting month (Week 4 runs to the month end). */
export const WEEK_RANGES = [
  { week: 1, first: 1, last: 7 },
  { week: 2, first: 8, last: 14 },
  { week: 3, first: 15, last: 21 },
  { week: 4, first: 22, last: 31 },
] as const;

/** Dashboard filters as stored in the URL. Empty strings mean "use the default". */
export interface DashboardFilterState {
  reportType: string;
  circle: string;
  scope: Scope;
  date: string;
  from: string;
  to: string;
  /** Trend chart view; empty means daily. */
  trend: string;
  /** Specific dates for the daily trend, comma-separated (empty = the from/to range). */
  days: string;
  /** Weeks for the weekly trend, e.g. "1,3" (empty = all). */
  weeks: string;
  /** Months for the monthly trend as 'YYYY-MM' keys (empty = all). */
  months: string;
}

const KEYS: Record<keyof DashboardFilterState, string> = {
  reportType: 'report_type',
  circle: 'circle',
  scope: 'scope',
  date: 'date',
  from: 'from',
  to: 'to',
  trend: 'trend',
  days: 'days',
  weeks: 'weeks',
  months: 'months',
};

export interface ResolvedFilters extends DashboardFilterState {
  trendView: TrendView;
  /** Valid specific dates, sorted; empty means the from/to range is used. */
  dayList: string[];
  /** Selected week numbers, sorted; empty means every week. */
  weekList: number[];
  /** Selected month keys in calendar order; empty means every month. */
  monthList: string[];
  /** Query parameters for snapshot endpoints (summary, breakdowns, records). */
  snapshotParams: URLSearchParams;
  /** Query parameters for the trend endpoint. */
  trendParams: URLSearchParams;
  /** Query parameters for the monthly endpoint. */
  monthlyParams: URLSearchParams;
  /** Query parameters for the trend-period KPI (period endpoint). */
  periodParams: URLSearchParams;
}

/** Trend points for the picked dates only (all points when none are picked). */
export function selectDays<T extends { date: string }>(series: T[], days: string[]) {
  return days.length ? series.filter((p) => days.includes(p.date)) : series;
}

/** The weeks picked in the trend period (all when none are picked); weeks are in workbook order. */
export function pickWeeks<T>(weeks: T[], picked: number[]) {
  return picked.length ? weeks.filter((_, i) => picked.includes(i + 1)) : weeks;
}

const list = (value: string) => value.split(',').map((v) => v.trim()).filter(Boolean);

/**
 * Filter state backed by the URL so views are shareable and survive reloads.
 * Values that are not offered by the workbook are ignored rather than sent to the API.
 */
export function useDashboardFilters(options: FilterOptions | null, { defaultScope }: { defaultScope?: Scope } = {}) {
  const [searchParams, setSearchParams] = useSearchParams();

  const resolved = useMemo<ResolvedFilters | null>(() => {
    if (!options) return null;
    const read = (key: keyof DashboardFilterState) => searchParams.get(KEYS[key]) ?? '';
    const dates = options.reporting_dates;

    const reportType = options.report_types.some((t) => t.value === read('reportType')) ? read('reportType') : '';
    const circleOption = options.circles.find((c) => c.value === read('circle'));
    const circle = circleOption && (!reportType || circleOption.report_types.includes(reportType)) ? circleOption.value : '';
    const scopeOption = options.scopes.find((s) => s.value === read('scope') && s.available);
    // A page may default to another scope (Threshold Analysis uses O&M Start, like its workbook sheets).
    const pageDefault = options.scopes.find((s) => s.value === defaultScope && s.available)?.value;
    const scope = scopeOption?.value ?? pageDefault ?? options.default_scope;
    const date = dates.includes(read('date')) ? read('date') : options.default_date ?? '';
    let from = dates.includes(read('from')) ? read('from') : options.default_trend_range.start ?? '';
    let to = dates.includes(read('to')) ? read('to') : options.default_trend_range.end ?? '';
    if (from && to && from > to) [from, to] = [to, from];

    const trendView = (TREND_VIEWS as string[]).includes(read('trend')) ? (read('trend') as TrendView) : 'daily';
    const dayList = [...new Set(list(read('days')).filter((d) => dates.includes(d)))].sort();
    const weekList = [...new Set(list(read('weeks')).map(Number).filter((w) => WEEK_RANGES.some((r) => r.week === w)))].sort((a, b) => a - b);
    const selectedMonths = new Set(list(read('months')));
    const monthList = (options.months ?? []).map((m) => m.key).filter((key) => selectedMonths.has(key));

    const base = new URLSearchParams({ scope });
    if (reportType) base.set('report_type', reportType);
    if (circle) base.set('circle', circle);
    const snapshotParams = new URLSearchParams(base);
    if (date) snapshotParams.set('reporting_date', date);
    const trendParams = new URLSearchParams(base);
    // Specific dates: request the span they cover; the chart shows only the chosen days.
    const start = dayList[0] ?? from;
    const end = dayList.at(-1) ?? to;
    if (start) trendParams.set('start_date', start);
    if (end) trendParams.set('end_date', end);
    const monthlyParams = new URLSearchParams(snapshotParams);
    if (monthList.length) monthlyParams.set('months', monthList.join(','));
    // The trend period KPI covers exactly what the trend chart shows.
    const periodParams = new URLSearchParams(base);
    if (trendView === 'monthly') {
      periodParams.set('period', 'months');
      if (monthList.length) periodParams.set('months', monthList.join(','));
    } else if (trendView === 'weekly') {
      periodParams.set('period', 'weeks');
      if (weekList.length) periodParams.set('weeks', weekList.join(','));
    } else if (dayList.length) {
      periodParams.set('period', 'days');
      periodParams.set('days', dayList.join(','));
    } else {
      periodParams.set('period', 'range');
      if (from) periodParams.set('start_date', from);
      if (to) periodParams.set('end_date', to);
    }

    return {
      reportType, circle, scope, date, from, to,
      trend: read('trend'), days: dayList.join(','), weeks: weekList.join(','), months: monthList.join(','),
      trendView, dayList, weekList, monthList, snapshotParams, trendParams, monthlyParams, periodParams,
    };
  }, [options, searchParams, defaultScope]);

  const setFilters = useCallback((changes: Partial<DashboardFilterState>) => {
    setSearchParams((current) => {
      const next = new URLSearchParams(current);
      for (const [key, value] of Object.entries(changes) as [keyof DashboardFilterState, string][]) {
        if (value) next.set(KEYS[key], value);
        else next.delete(KEYS[key]);
      }
      return next;
    }, { replace: true });
  }, [setSearchParams]);

  const reset = useCallback(() => setSearchParams(new URLSearchParams(), { replace: true }), [setSearchParams]);

  const isDefault = useMemo(
    () => Object.values(KEYS).every((key) => !searchParams.get(key)),
    [searchParams],
  );

  return { filters: resolved, setFilters, reset, isDefault };
}
