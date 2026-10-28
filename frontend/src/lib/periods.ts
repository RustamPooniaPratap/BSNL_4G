/**
 * Reporting periods for the Site Portfolio time filters: days, the workbook's weeks
 * (days 1-7, 8-14, 15-21, 22-end of each month, as in metrics.WEEKS) and months.
 *
 * Everything is derived from what the workbook holds (filter options): daily columns for
 * the reporting month and any earlier months (`daily_history`), and full-month totals for
 * the history months. Nothing is assumed about periods the workbook does not cover.
 */
import type { FilterOptions } from '../types';

export type Granularity = 'day' | 'week' | 'month';
export type MonthBasis = 'mtd' | 'full';

export const GRANULARITIES: [Granularity, string][] = [['day', 'Daily'], ['week', 'Weekly'], ['month', 'Monthly']];

/** One period as requested from `period/`: explicit dates, or a whole month from its monthly total. */
export interface Period {
  id: string;
  kind: Granularity;
  /** Short name, e.g. "20 Oct 2026", "Wk-3 · 15–21 Oct 2026", "Oct-26 MTD · 1–20 Oct 2026". */
  label: string;
  start: string;
  end: string;
  /** Calendar days the period covers. */
  days: number;
  /** Days with reported data (dates periods only). */
  dates: string[];
  /** Set for a full month read from the workbook's monthly total. */
  monthKey?: string;
  available: boolean;
  /** Why the period cannot be computed, when unavailable. */
  reason?: string;
  /** Fewer days with data than calendar days (a week or month in progress, or missing days). */
  partial: boolean;
}

/** The workbook's week boundaries (metrics.WEEKS). */
export const WEEK_DAYS: [number, number][] = [[1, 7], [8, 14], [15, 21], [22, 31]];

const pad = (n: number) => String(n).padStart(2, '0');
const iso = (y: number, m: number, d: number) => `${y}-${pad(m)}-${pad(d)}`;
const parts = (key: string) => key.split('-').map(Number) as [number, number];
export const daysInMonth = (key: string) => { const [y, m] = parts(key); return new Date(y, m, 0).getDate(); };
export const monthKeyOf = (date: string) => date.slice(0, 7);
export const shiftMonth = (key: string, by: number) => {
  const [y, m] = parts(key);
  const d = new Date(y, m - 1 + by, 1);
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}`;
};
// Fixed names, so labels match the workbook's "Sep-26" style whatever the browser locale.
const MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];
export const monthLabel = (key: string) => { const [y, m] = parts(key); return `${MONTHS[m - 1]}-${String(y).slice(2)}`; };
/** "20 Oct 2026". */
export const formatDate = (date: string) => { const [y, m, d] = date.split('-').map(Number); return `${pad(d)} ${MONTHS[m - 1]} ${y}`; };

/** "15–21 Oct 2026", or "28 Sep – 04 Oct 2026" across months. */
export function rangeLabel(start: string, end: string) {
  if (start === end) return formatDate(start);
  const [a, b] = [formatDate(start), formatDate(end)];
  if (start.slice(0, 7) === end.slice(0, 7)) return `${a.slice(0, 2)}–${b}`;
  return `${a.slice(0, 6)} – ${b}`;
}

export interface Availability {
  /** Every date with daily data, oldest first (reporting month and earlier months' daily columns). */
  dates: string[];
  dateSet: Set<string>;
  /** Months with daily columns, keyed 'YYYY-MM'. */
  dailyMonths: Map<string, string[]>;
  /** Months with a full-month total (the workbook's monthly outage columns). */
  fullMonths: Set<string>;
  currentMonth: string;
  /** Latest reporting date. */
  latest: string;
}

export function availability(options: FilterOptions): Availability {
  const current = monthKeyOf(options.month.start);
  const dailyMonths = new Map<string, string[]>();
  (options.daily_history ?? []).forEach((h) => dailyMonths.set(h.key, [...h.dates].sort()));
  dailyMonths.set(current, [...options.reporting_dates].sort());
  const dates = [...dailyMonths.values()].flat().sort();
  return {
    dates,
    dateSet: new Set(dates),
    dailyMonths,
    fullMonths: new Set(options.months.map((m) => m.key).filter((k) => k !== current)),
    currentMonth: current,
    latest: options.default_date ?? options.reporting_dates.at(-1) ?? options.month.start,
  };
}

// --- Days ------------------------------------------------------------------------------------

export function dayPeriod(date: string, av: Availability): Period {
  const available = av.dateSet.has(date);
  return {
    id: date, kind: 'day', label: formatDate(date), start: date, end: date, days: 1, dates: available ? [date] : [], available, partial: false,
    reason: available ? undefined : `No data for ${formatDate(date)} in the workbook.`,
  };
}

export const previousDate = (date: string, av: Availability) => [...av.dates].reverse().find((d) => d < date) ?? null;
export const nextDate = (date: string, av: Availability) => av.dates.find((d) => d > date) ?? null;

// --- Weeks -----------------------------------------------------------------------------------

export const weekId = (monthKey: string, n: number) => `${monthKey}-w${n}`;

export function weekPeriod(id: string, av: Availability): Period {
  const match = /^(\d{4}-\d{2})-w([1-4])$/.exec(id);
  if (!match) return { id, kind: 'week', label: id, start: '', end: '', days: 0, dates: [], available: false, partial: false, reason: 'Unknown week.' };
  const [, key, n] = match;
  const [y, m] = parts(key);
  const [first, last] = WEEK_DAYS[Number(n) - 1];
  const lastDay = Math.min(last, daysInMonth(key));
  const start = iso(y, m, first);
  const end = iso(y, m, lastDay);
  const dates = (av.dailyMonths.get(key) ?? []).filter((d) => d >= start && d <= end);
  const days = lastDay - first + 1;
  const reason = !av.dailyMonths.has(key) ? `${monthLabel(key)} has no daily data in the workbook.`
    : !dates.length ? 'No reported days in this week yet.' : undefined;
  return {
    id, kind: 'week', label: `Wk-${n} · ${rangeLabel(start, end)}`, start, end, days, dates, available: dates.length > 0, reason,
    partial: dates.length > 0 && dates.length < days,
  };
}

/** Weeks of every month with daily data, oldest first (including weeks with no data yet). */
export function weeksAvailable(av: Availability): Period[] {
  return [...av.dailyMonths.keys()].sort().flatMap((key) => [1, 2, 3, 4].map((n) => weekPeriod(weekId(key, n), av)));
}

export function shiftWeek(id: string, by: -1 | 1) {
  const match = /^(\d{4}-\d{2})-w([1-4])$/.exec(id);
  if (!match) return null;
  const n = Number(match[2]) + by;
  if (n < 1) return weekId(shiftMonth(match[1], -1), 4);
  if (n > 4) return weekId(shiftMonth(match[1], 1), 1);
  return weekId(match[1], n);
}

export const latestWeek = (av: Availability) => weeksAvailable(av).filter((w) => w.available).at(-1)?.id ?? weekId(av.currentMonth, 1);

// --- Months ----------------------------------------------------------------------------------

/** Day of the month reached by the reporting month's data: MTD periods run from the 1st to this day. */
export const elapsedDay = (av: Availability) => Number(av.latest.slice(8, 10));

export function monthPeriod(key: string, basis: MonthBasis, av: Availability, elapsed = elapsedDay(av)): Period {
  const [y, m] = parts(key);
  const monthDays = daysInMonth(key);
  const name = monthLabel(key);
  if (basis === 'full') {
    const start = iso(y, m, 1);
    const end = iso(y, m, monthDays);
    const inProgress = key === av.currentMonth;
    const available = av.fullMonths.has(key);
    return {
      id: key, kind: 'month', label: `${name} · full month (${rangeLabel(start, end)})`, start, end, days: monthDays, dates: [],
      monthKey: available ? key : undefined, available, partial: false,
      reason: available ? undefined : inProgress ? `${name} is in progress: data runs to ${formatDate(av.latest)}. Choose MTD.`
        : `${name} has no monthly total in the workbook.`,
    };
  }
  // MTD: the 1st to the elapsed day, shortened to the month's length (e.g. 1–28 Feb for 30 days elapsed).
  const lastDay = Math.min(elapsed, monthDays);
  const start = iso(y, m, 1);
  const end = iso(y, m, lastDay);
  const dates = (av.dailyMonths.get(key) ?? []).filter((d) => d <= end);
  const available = dates.length > 0;
  return {
    id: key, kind: 'month', label: `${name} MTD · ${rangeLabel(start, end)}`, start, end, days: lastDay, dates, available,
    partial: available && dates.length < lastDay,
    reason: available ? undefined : av.dailyMonths.has(key) ? `No reported days in ${rangeLabel(start, end)}.`
      : `${name} has no daily data in the workbook, so ${rangeLabel(start, end)} cannot be computed. Only its full-month total is available.`,
  };
}

/** Months the picker can show: every month with a total or daily data, oldest first. */
export const monthsAvailable = (av: Availability) => [...new Set([...av.fullMonths, ...av.dailyMonths.keys()])].sort();

export const defaultBasis = (key: string, av: Availability): MonthBasis => (key === av.currentMonth || !av.fullMonths.has(key) ? 'mtd' : 'full');

/** Query for the `period/` endpoint: explicit dates, or one month's total. */
export function periodQuery(p: Period): Record<string, string> {
  return p.monthKey ? { period: 'months', months: p.monthKey } : { period: 'days', days: p.dates.join(',') };
}

// --- Selection from the URL -------------------------------------------------------------------

export interface PeriodSelection {
  view: Granularity;
  /** Selected and comparison periods (comparison null = off). */
  selected: Period;
  comparison: Period | null;
  /** Raw choices, for the pickers. */
  date: string;
  vsDate: string | null;
  week: string;
  vsWeek: string | null;
  month: string;
  vsMonth: string | null;
  basis: MonthBasis;
}

export interface PeriodChange {
  view?: Granularity;
  date?: string;
  week?: string;
  month?: string;
  basis?: MonthBasis;
  /** A period id of the current granularity, or 'none'. */
  vs?: string;
}

/**
 * The selected and comparison periods from URL parameters, with defaults:
 * - day: the reporting date filter; compared with the previous date with data;
 * - week: the latest week with data; compared with the week before;
 * - month: the current month to date (or a full month); compared with the month before.
 * A comparison the workbook cannot supply stays selected and is reported as unavailable,
 * never silently replaced with another period.
 */
export function resolveSelection(params: URLSearchParams, av: Availability, reportingDates: string[], date: string): PeriodSelection {
  const raw = params.get('view');
  const view: Granularity = raw === 'week' || raw === 'month' ? raw : 'day';
  const vsParam = params.get('vs');
  const dayAv: Availability = { ...av, dates: reportingDates };

  const vsDate = view !== 'day' ? null : vsParam === 'none' ? null
    : vsParam && /^\d{4}-\d{2}-\d{2}$/.test(vsParam) && vsParam !== date ? vsParam : previousDate(date, dayAv);

  const weekParam = params.get('week');
  const week = weekParam && /^\d{4}-\d{2}-w[1-4]$/.test(weekParam) ? weekParam : latestWeek(av);
  const vsWeek = view !== 'week' ? null : vsParam === 'none' ? null
    : vsParam && /^\d{4}-\d{2}-w[1-4]$/.test(vsParam) && vsParam !== week ? vsParam : shiftWeek(week, -1);

  const monthParam = params.get('month');
  const month = monthParam && monthsAvailable(av).includes(monthParam) ? monthParam : av.currentMonth;
  const basisParam = params.get('basis');
  const fullOk = av.fullMonths.has(month);
  const mtdOk = av.dailyMonths.has(month);
  const basis: MonthBasis = basisParam === 'full' && fullOk ? 'full' : basisParam === 'mtd' && mtdOk ? 'mtd' : defaultBasis(month, av);
  const vsMonth = view !== 'month' ? null : vsParam === 'none' ? null
    : vsParam && /^\d{4}-\d{2}$/.test(vsParam) && vsParam !== month ? vsParam : shiftMonth(month, -1);

  const selected = view === 'day' ? dayPeriod(date, dayAv) : view === 'week' ? weekPeriod(week, av) : monthPeriod(month, basis, av);
  const comparison = view === 'day' ? (vsDate ? dayPeriod(vsDate, dayAv) : null)
    : view === 'week' ? (vsWeek ? weekPeriod(vsWeek, av) : null)
      : (vsMonth ? monthPeriod(vsMonth, basis, av) : null);
  return { view, selected, comparison, date, vsDate, week, vsWeek, month, vsMonth, basis };
}

/** Apply a change to the URL: a new granularity or period resets the comparison to its default. */
export function applyChange(current: URLSearchParams, change: PeriodChange): URLSearchParams {
  const next = new URLSearchParams(current);
  const set = (k: string, v: string | undefined | null) => (v ? next.set(k, v) : next.delete(k));
  if (change.view) {
    ['vs', 'week', 'month', 'basis'].forEach((k) => next.delete(k));
    set('view', change.view === 'day' ? null : change.view);
  }
  if (change.date) { set('date', change.date); next.delete('vs'); }
  if (change.week) { set('week', change.week); next.delete('vs'); }
  if (change.month) { set('month', change.month); next.delete('vs'); next.delete('basis'); }
  if (change.basis) set('basis', change.basis);
  if (change.vs) set('vs', change.vs);
  return next;
}
