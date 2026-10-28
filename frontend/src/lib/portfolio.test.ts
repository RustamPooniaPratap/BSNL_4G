import { describe, expect, it } from 'vitest';
import { breakdown, summary } from '../test/fixtures';
import type { BreakdownResponse, SummaryResponse } from '../types';
import { buildExceptions, buildKpis, circleBreakdown, circleExtremes, delta, detailLink, previousReportingDate } from './portfolio';

const F = { reportType: '', circle: 'MP', date: '2026-10-03' };
const withMetrics = (changes: Partial<SummaryResponse['metrics']>): SummaryResponse => ({ ...summary, metrics: { ...summary.metrics, ...changes } });

describe('differences', () => {
  it('uses percentage points for percentages and absolute plus percent change for counts', () => {
    expect(delta(93.46, 93.5, 'pct')).toEqual({ absolute: -0.04, relativePct: null, unit: 'pct' });
    expect(delta(197, 203, 'sites')).toEqual({ absolute: -6, relativePct: -3, unit: 'sites' });
    expect(delta(3, 0, 'sites')).toEqual({ absolute: 3, relativePct: null, unit: 'sites' });  // no % change from zero
    expect(delta(null, 5, 'sites')).toBeNull();  // missing value: not available, not zero
  });

  it('compares with the previous reporting date that has data', () => {
    expect(previousReportingDate(['2026-10-01', '2026-10-02', '2026-10-03'], '2026-10-03')).toBe('2026-10-02');
    expect(previousReportingDate(['2026-10-01', '2026-10-03'], '2026-10-03')).toBe('2026-10-01');
    expect(previousReportingDate(['2026-10-01'], '2026-10-01')).toBeNull();
  });

  it('builds drill-down links that keep the filters', () => {
    expect(detailLink('/', F, { bucket: 'lt_60' })).toBe('/?circle=MP&date=2026-10-03&bucket=lt_60');
    expect(detailLink('/thresholds', { reportType: 'LWE', circle: '', date: '' })).toBe('/thresholds?report_type=LWE');
  });
});

describe('KPI cards', () => {
  const kpis = buildKpis({
    onAir: withMetrics({ sites_in_scope: 5, sites_total: 7, mtd_uptime_pct: 93.07, sites_below_60_mtd: 2 }),
    omStart: withMetrics({ sites_in_scope: 4, mtd_uptime_pct: 94 }),
    all: withMetrics({ sites_in_scope: 7, sites_total: 7 }),
    previous: withMetrics({ mtd_uptime_pct: 93.5, sites_below_60_mtd: 4 }),
  }, F, { day: 'On 03 Oct', mtd: 'MTD 01–03 Oct' });
  const byId = Object.fromEntries(kpis.map((k) => [k.id, k]));

  it('take every value from the API figures, without recalculating uptime', () => {
    expect(byId.total.value).toBe(7);
    expect(byId.on_air.value).toBe(5);
    expect(byId.not_on_air.value).toBe(2);
    expect(byId.om_start.value).toBe(4);
    expect(byId.mtd_uptime.value).toBe(93.07);
    expect(byId.om_mtd_uptime.value).toBe(94);
  });

  it('compare with the previous date in the right unit, and say when a rise is good', () => {
    expect(byId.mtd_uptime.delta).toEqual({ absolute: -0.43, relativePct: null, unit: 'pct' });
    expect(byId.lt_60.delta).toEqual({ absolute: -2, relativePct: -50, unit: 'sites' });
    expect([byId.mtd_uptime.higherIsBetter, byId.lt_60.higherIsBetter]).toEqual([true, false]);
    expect(byId.on_air.delta).toBeNull();  // On-Air flags have no history
  });

  it('link to the detail views with the filters applied', () => {
    expect(byId.lt_60.link).toBe('/?circle=MP&date=2026-10-03&bucket=lt_60');
    expect(byId.gte_98_5.link).toBe('/thresholds?circle=MP&date=2026-10-03');
    expect(byId.om_start.link).toBe('/?circle=MP&date=2026-10-03&scope=om_start');
  });

  it('show O&M Start as not available when the workbook has no such column', () => {
    const noOm = buildKpis({ onAir: summary, omStart: null, all: summary, previous: null }, F, { day: '', mtd: '' });
    expect(noOm.find((k) => k.id === 'om_start')!.value).toBeNull();
    expect(noOm.every((k) => k.delta === null)).toBe(true);  // no previous date, no comparison
  });
});

describe('comparisons and exceptions', () => {
  const circles: BreakdownResponse = {
    ...breakdown,
    circles: [
      { ...breakdown.circles[0], circle: 'MP', report_type: '4G Saturation', mtd_uptime_pct: 93, sites_in_scope: 10, sites_reported: 8, buckets: { ...breakdown.circles[0].buckets, lt_60: 3 } },
      { ...breakdown.circles[0], circle: 'RJ', report_type: '4G Saturation', mtd_uptime_pct: 95.5, sites_in_scope: 4, sites_reported: 4, buckets: { ...breakdown.circles[0].buckets, lt_60: 0 } },
      { ...breakdown.circles[0], circle: 'BH', report_type: 'LWE', mtd_uptime_pct: 99, sites_in_scope: 2, sites_reported: 2, buckets: { ...breakdown.circles[0].buckets, lt_60: 0 } },
    ],
  };

  it('ranks circles only within one network', () => {
    expect(circleExtremes(circles)).toEqual([expect.objectContaining({ reportType: '4G Saturation', gapPts: 2.5 })]);
    expect(circleExtremes(circles)[0].best.circle).toBe('RJ');
  });

  it('lists actionable exceptions, most severe first, never "late" without a deadline', () => {
    const exceptions = buildExceptions(circles, [
      { id: 'calculation_mismatch', severity: 'critical', title: '1 workbook figure differs', detail: '', link: '/data-source#calculation-check' },
      { id: 'sites_below_60', severity: 'critical', title: 'duplicate of the circle rows', detail: '', link: '/' },
      { id: 'data_outage_out_of_range', severity: 'warning', title: '2 values out of range', detail: '', link: '/data-source' },
    ], [], F);
    expect(exceptions.map((e) => `${e.severity} ${e.circle}: ${e.type} (${e.count ?? '—'})`)).toEqual([
      'critical MP · 4G: Sites below 60% uptime (MTD) (3)',
      'critical All circles: 1 workbook figure differs (—)',
      'warning MP · 4G: On-Air sites not reported on the date (2)',
      'warning All circles: 2 values out of range (—)',
    ]);
    expect(exceptions[0].link).toBe('/?report_type=4G+Saturation&circle=MP&date=2026-10-03&bucket=lt_60');
  });
});

describe('circle-wise breakdown', () => {
  const circle = (report_type: string, c: string, sites: number) => ({ ...breakdown.circles[0], report_type, circle: c, sites_in_scope: sites });
  const scope = (rows: [string, string, number][]): BreakdownResponse => ({ ...breakdown, circles: rows.map(([t, c, n]) => circle(t, c, n)) });
  const all = scope([['LWE', 'CG', 364], ['4G Saturation', 'RJ', 1458], ['4G Saturation', 'MP', 1483], ['LWE', 'MP', 22]]);
  const onAir = scope([['LWE', 'CG', 357], ['4G Saturation', 'RJ', 1362], ['4G Saturation', 'MP', 1351], ['LWE', 'MP', 20]]);
  const om = scope([['LWE', 'CG', 357], ['4G Saturation', 'RJ', 1316], ['4G Saturation', 'MP', 1332], ['LWE', 'MP', 19]]);

  it('groups 4G before LWE, keeps the same circle separate per network, and derives both gaps', () => {
    const { groups } = circleBreakdown(all, onAir, om);
    expect(groups.map((g) => [g.reportType, g.rows.map((r) => r.circle)])).toEqual([
      ['4G Saturation', ['MP', 'RJ']], ['LWE', ['CG', 'MP']],
    ]);
    expect(groups[0].rows[0]).toMatchObject({ siteScope: 1483, onAir: 1351, omStart: 1332, gapTotal: 151, gapOnAir: 19 });
    expect(groups[1].rows[1]).toMatchObject({ circle: 'MP', siteScope: 22, onAir: 20, omStart: 19, gapTotal: 3, gapOnAir: 1 });
  });

  it('adds subtotals and the total from the circle rows once, with gaps from the summed counts', () => {
    const { groups, total } = circleBreakdown(all, onAir, om);
    expect(groups[0].subtotal).toMatchObject({ siteScope: 2941, onAir: 2713, omStart: 2648, gapTotal: 293, gapOnAir: 65 });
    expect(groups[1].subtotal).toMatchObject({ siteScope: 386, onAir: 377, omStart: 376, gapTotal: 10, gapOnAir: 1 });
    expect(total).toMatchObject({ siteScope: 3327, onAir: 3090, omStart: 3024, gapTotal: 303, gapOnAir: 66 });
  });

  it('adds CIs, IEs and sites per person; subtotals and the total count each person once', () => {
    const teams = (ci: number, ie: number) => ({ ci_count: ci, ie_count: ie, sites_without_ci: 0, sites_without_ie: 0 });
    const withTeams: BreakdownResponse = {
      ...all,
      circles: all.circles.map((c) => ({ ...c, ...(c.circle === 'MP' && c.report_type === '4G Saturation' ? teams(10, 91) : c.circle === 'RJ' ? teams(12, 89) : teams(1, 4)) })),
      // MP 4G and RJ share 2 CIs, so the network has 20 CIs, not 22.
      team_totals: { all: teams(21, 180), '4G Saturation': teams(20, 178), LWE: teams(1, 4) },
    };
    const { groups, total } = circleBreakdown(withTeams, onAir, om);
    expect(groups[0].rows[0]).toMatchObject({ circle: 'MP', ciCount: 10, ieCount: 91, sitesPerCi: 148.3, sitesPerIe: 16.3 });  // 1,483 sites
    expect(groups[0].subtotal).toMatchObject({ ciCount: 20, ieCount: 178, sitesPerCi: 147.1 });  // 2,941 ÷ 20, from team_totals
    expect(total).toMatchObject({ ciCount: 21, ieCount: 180, sitesPerCi: 158.4 });
    expect(circleBreakdown(all, onAir, om).total).toMatchObject({ ciCount: null, sitesPerCi: null });  // not in the response: not invented
  });

  it('shows O&M Start and both gaps as not available when the workbook has no O&M Start column', () => {
    const { groups, total } = circleBreakdown(all, onAir, null);
    expect(groups[0].rows[0]).toMatchObject({ omStart: null, gapTotal: null, gapOnAir: null });
    expect(total).toMatchObject({ siteScope: 3327, onAir: 3090, omStart: null, gapTotal: null });
  });
});
