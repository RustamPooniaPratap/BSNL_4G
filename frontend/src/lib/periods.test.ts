import { describe, expect, it } from 'vitest';
import { filterOptions } from '../test/fixtures';
import type { FilterOptions } from '../types';
import {
  availability, dayPeriod, defaultBasis, latestWeek, monthPeriod, monthsAvailable, nextDate, periodQuery, previousDate, shiftWeek,
  weekPeriod, weeksAvailable,
} from './periods';

const oct = (d: number) => `2026-10-${String(d).padStart(2, '0')}`;
/** Data like the live workbook: 1–20 Oct daily, monthly totals Feb–Sep 2026, no earlier daily columns. */
const options: FilterOptions = {
  ...filterOptions,
  reporting_dates: Array.from({ length: 20 }, (_, i) => oct(i + 1)).filter((d) => d !== oct(5)),  // 5 Oct missing
  default_date: oct(20),
  month: { label: 'Oct-26', start: oct(1), end: oct(31) },
  months: [...['02', '03', '04', '05', '06', '07', '08', '09'].map((m) => ({ key: `2026-${m}`, label: m })), { key: '2026-10', label: 'Oct-26 MTD' }],
  daily_history: [],
};
const av = availability(options);
const withSeptember = availability({ ...options, daily_history: [{ key: '2026-09', label: 'Sep-26', dates: Array.from({ length: 30 }, (_, i) => `2026-09-${String(i + 1).padStart(2, '0')}`) }] });

describe('days', () => {
  it('steps through dates with data only and flags dates without data', () => {
    expect(previousDate(oct(6), av)).toBe(oct(4));  // skips the missing 5 Oct
    expect(nextDate(oct(4), av)).toBe(oct(6));
    expect(previousDate(oct(1), av)).toBeNull();     // nothing earlier: no comparison is invented
    expect(dayPeriod(oct(5), av)).toMatchObject({ available: false, reason: 'No data for 05 Oct 2026 in the workbook.' });
    expect(periodQuery(dayPeriod(oct(20), av))).toEqual({ period: 'days', days: oct(20) });
  });
});

describe('weeks', () => {
  it('use the workbook weeks (1–7, 8–14, 15–21, 22–end), with the days actually reported', () => {
    expect(weeksAvailable(av).map((w) => [w.id, w.available])).toEqual([
      ['2026-10-w1', true], ['2026-10-w2', true], ['2026-10-w3', true], ['2026-10-w4', false],
    ]);
    const w3 = weekPeriod('2026-10-w3', av);
    expect(w3).toMatchObject({ label: 'Wk-3 · 15–21 Oct 2026', days: 7, partial: true });
    expect(w3.dates).toEqual([15, 16, 17, 18, 19, 20].map(oct));
    expect(weekPeriod('2026-10-w1', av).dates).toHaveLength(6);  // 5 Oct missing
    expect(weekPeriod('2026-10-w4', av)).toMatchObject({ label: 'Wk-4 · 22–31 Oct 2026', days: 10, reason: 'No reported days in this week yet.' });
    expect(latestWeek(av)).toBe('2026-10-w3');
  });

  it('compares week 1 with the last week of the previous month only when its daily data exists', () => {
    expect(shiftWeek('2026-10-w1', -1)).toBe('2026-09-w4');
    expect(weekPeriod('2026-09-w4', av)).toMatchObject({ available: false, reason: 'Sep-26 has no daily data in the workbook.' });
    expect(weekPeriod('2026-09-w4', withSeptember)).toMatchObject({ available: true, label: 'Wk-4 · 22–30 Sep 2026', days: 9 });
  });
});

describe('months', () => {
  it('offer MTD for the month in progress and full months from the monthly totals', () => {
    expect(monthsAvailable(av)).toEqual(['2026-02', '2026-03', '2026-04', '2026-05', '2026-06', '2026-07', '2026-08', '2026-09', '2026-10']);
    expect(defaultBasis('2026-10', av)).toBe('mtd');
    expect(defaultBasis('2026-09', av)).toBe('full');
    expect(monthPeriod('2026-10', 'mtd', av)).toMatchObject({ label: 'Oct-26 MTD · 01–20 Oct 2026', days: 20, available: true, partial: true });  // 19 of 20 days
    expect(monthPeriod('2026-10', 'full', av)).toMatchObject({ available: false, reason: 'Oct-26 is in progress: data runs to 20 Oct 2026. Choose MTD.' });
    expect(periodQuery(monthPeriod('2026-09', 'full', av))).toEqual({ period: 'months', months: '2026-09' });
  });

  it('compare MTD with the same elapsed days of another month, never from its monthly total', () => {
    expect(monthPeriod('2026-09', 'mtd', av)).toMatchObject({
      available: false, label: 'Sep-26 MTD · 01–20 Sep 2026',
      reason: 'Sep-26 has no daily data in the workbook, so 01–20 Sep 2026 cannot be computed. Only its full-month total is available.',
    });
    const sep = monthPeriod('2026-09', 'mtd', withSeptember);
    expect([sep.available, sep.start, sep.end, sep.dates.length]).toEqual([true, '2026-09-01', '2026-09-20', 20]);
  });

  it('shorten MTD to the length of a short month and give a full month its own number of days', () => {
    expect(monthPeriod('2026-02', 'mtd', av, 30)).toMatchObject({ start: '2026-02-01', end: '2026-02-28', days: 28 });
    expect(monthPeriod('2026-02', 'full', av)).toMatchObject({ label: 'Feb-26 · full month (01–28 Feb 2026)', days: 28, available: true });
    expect(monthPeriod('2025-01', 'full', av)).toMatchObject({ available: false, reason: 'Jan-25 has no monthly total in the workbook.' });
  });
});
