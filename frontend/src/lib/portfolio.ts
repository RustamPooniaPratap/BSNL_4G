/**
 * Site Portfolio: management KPIs, comparisons and exceptions built from the verified API figures.
 *
 * No figure is calculated here from scratch. Uptime always comes from the API's pooled
 * (site-day weighted) calculation; this module only selects, compares and labels values.
 * Comparisons are labelled as counts, percentage points (pts) or percent change (%).
 */
import type { BreakdownResponse, DashboardAlert, PeriodSummary, SummaryResponse } from '../types';
import type { Submission } from './tracking';

export type Unit = 'sites' | 'pct' | 'minutes';

/** Change between two values: "pts" for percentages, a count plus % change for counts. */
export interface Delta {
  absolute: number;
  /** Percent change for counts; null for percentages (use points) or a zero base. */
  relativePct: number | null;
  unit: Unit;
}

export function delta(current: number | null | undefined, previous: number | null | undefined, unit: Unit): Delta | null {
  if (current == null || previous == null) return null;
  const absolute = Math.round((current - previous) * 100) / 100;
  const relativePct = unit === 'pct' || previous === 0 ? null : Math.round((1000 * (current - previous)) / previous) / 10;
  return { absolute, relativePct, unit };
}

/**
 * Opening the app at "/" with no filters lands on Site Portfolio. Links with filters
 * ("/?bucket=lt_60", "/?report_type=LWE") keep opening the Overview, so no deep link changes.
 */
export const landsOnPortfolio = (pathname: string, search: string) => pathname === '/' && !search;

/** The reporting date before ``date`` that has data, or null for the first one. */
export function previousReportingDate(dates: string[], date: string): string | null {
  const earlier = dates.filter((d) => d < date).sort();
  return earlier.at(-1) ?? null;
}

export interface PortfolioFilters {
  reportType: string;
  circle: string;
  date: string;
}

/** Link to a detail page with the portfolio's report type, circle and date applied. */
export function detailLink(path: string, f: PortfolioFilters, extra: Record<string, string> = {}) {
  const query = new URLSearchParams();
  if (f.reportType) query.set('report_type', f.reportType);
  if (f.circle) query.set('circle', f.circle);
  if (f.date) query.set('date', f.date);
  Object.entries(extra).forEach(([k, v]) => query.set(k, v));
  const text = query.toString();
  return text ? `${path}?${text}` : path;
}

export interface PortfolioData {
  onAir: SummaryResponse;
  omStart: SummaryResponse | null;
  all: SummaryResponse;
  previous: SummaryResponse | null;
}

export interface Kpi {
  id: string;
  group: 'Site portfolio' | 'Uptime and performance' | 'Reporting and operations';
  label: string;
  value: number | null;
  unit: Unit;
  /** Reporting period shown under the value, e.g. "On 14 Oct" or "MTD 1–14 Oct". */
  period: string;
  definition: string;
  delta: Delta | null;
  /** True when a rise is good (uptime) or bad (sites below 60%); null when neutral. */
  higherIsBetter: boolean | null;
  link: string;
  tone?: 'critical' | 'warning';
}

/** Portfolio KPI cards from the summary snapshots (current and previous reporting date). */
export function buildKpis(d: PortfolioData, f: PortfolioFilters, labels: { day: string; mtd: string }): Kpi[] {
  const { onAir, omStart, all, previous } = d;
  const m = onAir.metrics;
  const p = previous?.metrics;
  const total = all.metrics.sites_total;
  const onAirSites = m.sites_in_scope;
  const kpis: Kpi[] = [
    {
      id: 'total', group: 'Site portfolio', label: 'Total sites', value: total, unit: 'sites', period: 'In the Master workbook',
      definition: 'Every site row in Up-Time Report for the selected report type and circle (duplicates removed).',
      delta: null, higherIsBetter: null, link: detailLink('/', f, { scope: 'all' }),
    },
    {
      id: 'on_air', group: 'Site portfolio', label: 'On-Air sites', value: onAirSites, unit: 'sites', period: 'Current On-Air flag',
      definition: 'Sites with On-Air = "Yes". The flag has no history, so no previous-period comparison is possible.',
      delta: null, higherIsBetter: null, link: detailLink('/', f, { scope: 'on_air' }),
    },
    {
      id: 'not_on_air', group: 'Site portfolio', label: 'Sites not yet On-Air', value: total - onAirSites, unit: 'sites', period: 'Current On-Air flag',
      definition: 'Total sites minus On-Air sites (On-Air blank, "No" or any value other than "Yes").',
      delta: null, higherIsBetter: null, link: detailLink('/', f, { scope: 'all' }),
    },
    {
      id: 'om_start', group: 'Site portfolio', label: 'Sites in O&M Start', value: omStart ? omStart.metrics.sites_in_scope : null, unit: 'sites',
      period: 'Current month flag',
      definition: 'Sites with "O&M Start - <month>" = "Yes" for the reporting month. Not available when the workbook has no such column.',
      delta: null, higherIsBetter: null, link: detailLink('/', f, { scope: 'om_start' }),
    },
    {
      id: 'mtd_uptime', group: 'Uptime and performance', label: 'On-Air MTD uptime', value: m.mtd_uptime_pct, unit: 'pct', period: labels.mtd,
      definition: 'Outage-weighted uptime of On-Air sites from the 1st to the reporting date: 1 − Σ outage ÷ (1,440 × site-days reported). Compared with the MTD to the previous reporting date.',
      delta: delta(m.mtd_uptime_pct, p?.mtd_uptime_pct, 'pct'), higherIsBetter: true, link: detailLink('/', f),
    },
    {
      id: 'om_mtd_uptime', group: 'Uptime and performance', label: 'O&M Start MTD uptime', value: omStart?.metrics.mtd_uptime_pct ?? null, unit: 'pct',
      period: labels.mtd, definition: 'The same MTD uptime for O&M Start sites (the population of the workbook\'s threshold sheets).',
      delta: null, higherIsBetter: true, link: detailLink('/', f, { scope: 'om_start' }),
    },
    {
      id: 'daily_uptime', group: 'Uptime and performance', label: 'On-Air daily uptime', value: m.daily_uptime_pct, unit: 'pct', period: labels.day,
      definition: 'Outage-weighted uptime of On-Air sites that reported on the reporting date. Compared with the previous reporting date.',
      delta: delta(m.daily_uptime_pct, p?.daily_uptime_pct, 'pct'), higherIsBetter: true, link: detailLink('/', f),
    },
    {
      id: 'gte_98_5', group: 'Uptime and performance', label: 'Sites at 98.5% or above', value: m.sites_at_or_above_98_5_mtd, unit: 'sites', period: labels.mtd,
      definition: 'On-Air sites whose own MTD uptime is at least 98.5% (workbook bucket ">98.5").',
      delta: delta(m.sites_at_or_above_98_5_mtd, p?.sites_at_or_above_98_5_mtd, 'sites'), higherIsBetter: true, link: detailLink('/thresholds', f),
    },
    {
      id: 'lt_60', group: 'Uptime and performance', label: 'Sites below 60%', value: m.sites_below_60_mtd, unit: 'sites', period: labels.mtd,
      definition: 'On-Air sites whose own MTD uptime is below 60% (workbook bucket "<60"). These need attention first.',
      delta: delta(m.sites_below_60_mtd, p?.sites_below_60_mtd, 'sites'), higherIsBetter: false,
      link: detailLink('/', f, { bucket: 'lt_60' }), tone: m.sites_below_60_mtd ? 'critical' : undefined,
    },
    {
      id: 'down_all_day', group: 'Uptime and performance', label: 'Sites down all day', value: m.sites_down_full_day, unit: 'sites', period: labels.day,
      definition: 'On-Air sites with 1,440 or more outage minutes on the reporting date.',
      delta: delta(m.sites_down_full_day, p?.sites_down_full_day, 'sites'), higherIsBetter: false,
      link: detailLink('/', f, { bucket: 'lt_60', bucket_basis: 'daily' }), tone: m.sites_down_full_day ? 'critical' : undefined,
    },
    {
      id: 'coverage', group: 'Reporting and operations', label: 'Reporting completeness', value: m.coverage_pct, unit: 'pct', period: labels.day,
      definition: 'On-Air sites with an outage value on the reporting date ÷ On-Air sites. Missing values are not counted as 100%.',
      delta: delta(m.coverage_pct, p?.coverage_pct, 'pct'), higherIsBetter: true, link: '/data-source',
      tone: m.sites_missing ? 'warning' : undefined,
    },
  ];
  return kpis;
}

/** Highest and lowest circle MTD uptime, compared only within one report type (different networks). */
export function circleExtremes(b: BreakdownResponse | null) {
  const byType = new Map<string, BreakdownResponse['circles']>();
  (b?.circles ?? []).filter((c) => c.mtd_uptime_pct != null).forEach((c) => byType.set(c.report_type, [...(byType.get(c.report_type) ?? []), c]));
  return [...byType].filter(([, circles]) => circles.length > 1).map(([reportType, circles]) => {
    const sorted = [...circles].sort((x, y) => (y.mtd_uptime_pct ?? 0) - (x.mtd_uptime_pct ?? 0));
    const best = sorted[0];
    const worst = sorted.at(-1)!;
    return { reportType, best, worst, gapPts: Math.round(((best.mtd_uptime_pct ?? 0) - (worst.mtd_uptime_pct ?? 0)) * 100) / 100 };
  });
}

export type Severity = 'critical' | 'warning' | 'info';

export interface PortfolioException {
  id: string;
  circle: string;
  type: string;
  count: number | null;
  reportingDate: string;
  severity: Severity;
  link: string;
}

const RANK: Record<Severity, number> = { critical: 0, warning: 1, info: 2 };

/**
 * Actionable exceptions: circles with sites below 60% MTD (workbook threshold), sites not
 * reported on the date, CSV arrivals late against a configured deadline or still pending,
 * and the data-quality alerts. Nothing is "late" without a configured deadline.
 */
export function buildExceptions(b: BreakdownResponse | null, alerts: DashboardAlert[], arrivals: Submission[], f: PortfolioFilters): PortfolioException[] {
  const out: PortfolioException[] = [];
  const label = (circle: string, reportType: string) => `${circle} · ${reportType === '4G Saturation' ? '4G' : reportType}`;
  for (const c of b?.circles ?? []) {
    const below = c.buckets.lt_60;
    if (below > 0) {
      out.push({
        id: `lt60-${c.report_type}-${c.circle}`, circle: label(c.circle, c.report_type), type: 'Sites below 60% uptime (MTD)', count: below,
        reportingDate: f.date, severity: 'critical', link: detailLink('/', { ...f, reportType: c.report_type, circle: c.circle }, { bucket: 'lt_60' }),
      });
    }
    const missing = c.sites_in_scope - c.sites_reported;
    if (missing > 0) {
      out.push({
        id: `missing-${c.report_type}-${c.circle}`, circle: label(c.circle, c.report_type), type: 'On-Air sites not reported on the date', count: missing,
        reportingDate: f.date, severity: 'warning', link: detailLink('/', { ...f, reportType: c.report_type, circle: c.circle }),
      });
    }
  }
  for (const s of arrivals) {
    if (s.status === 'late') {
      out.push({ id: `late-${s.key}`, circle: label(s.circle, s.reportType), type: 'CSV late (past the configured deadline)', count: null, reportingDate: s.reportingDate, severity: 'critical', link: '/daily-ingestion' });
    } else if (s.status === 'needs_review') {
      out.push({ id: `review-${s.key}`, circle: label(s.circle, s.reportType), type: 'CSV arrival needs review', count: null, reportingDate: s.reportingDate, severity: 'warning', link: '/daily-ingestion' });
    }
  }
  for (const a of alerts) {
    if (a.id === 'calculation_mismatch' || a.id.startsWith('data_') || a.id === 'stale_data') {
      out.push({ id: `alert-${a.id}`, circle: 'All circles', type: a.title, count: null, reportingDate: f.date, severity: a.severity, link: a.link });
    }
  }
  return out.sort((x, y) => RANK[x.severity] - RANK[y.severity] || (y.count ?? 0) - (x.count ?? 0));
}

export interface PortfolioCounts {
  siteScope: number;
  onAir: number;
  omStart: number | null;
  /** Site Scope − O&M Start */
  gapTotal: number | null;
  /** On Air − O&M Start */
  gapOnAir: number | null;
}

/** CIs and IEs named on the sites, and the average Site Scope per CI / IE (one decimal). */
export interface TeamFigures {
  ciCount: number | null;
  ieCount: number | null;
  sitesPerCi: number | null;
  sitesPerIe: number | null;
}

export interface CircleBreakdownRow extends PortfolioCounts, TeamFigures {
  circle: string;
  reportType: string;
}

export interface CircleBreakdownGroup {
  reportType: string;
  rows: CircleBreakdownRow[];
  subtotal: PortfolioCounts & TeamFigures;
}

const counts = (siteScope: number, onAir: number, omStart: number | null): PortfolioCounts => ({
  siteScope, onAir, omStart,
  gapTotal: omStart == null ? null : siteScope - omStart,
  gapOnAir: omStart == null ? null : onAir - omStart,
});

const perPerson = (sites: number, people: number | null | undefined) => (people ? Math.round((10 * sites) / people) / 10 : null);
const teamFigures = (t: { ci_count?: number; ie_count?: number } | undefined, siteScope: number): TeamFigures => ({
  ciCount: t?.ci_count ?? null, ieCount: t?.ie_count ?? null,
  sitesPerCi: perPerson(siteScope, t?.ci_count), sitesPerIe: perPerson(siteScope, t?.ie_count),
});

/**
 * Circle-wise Site Scope / On Air / O&M Start from the per-circle site counts of the three scopes
 * (breakdowns with scope all, on_air and om_start). Subtotals and the total add the detail rows once
 * and derive their gaps from the summed counts. ``omStart`` is null when the workbook has no
 * O&M Start column. CI / IE counts come from the all-sites breakdown; averages are Site Scope per person.
 */
export function circleBreakdown(all: BreakdownResponse, onAir: BreakdownResponse, omStart: BreakdownResponse | null) {
  const key = (c: { report_type: string; circle: string }) => `${c.report_type}|${c.circle}`;
  const inScope = (b: BreakdownResponse | null) => new Map((b?.circles ?? []).map((c) => [key(c), c.sites_in_scope]));
  const onAirBy = inScope(onAir);
  const omBy = omStart ? inScope(omStart) : null;
  const rows: CircleBreakdownRow[] = all.circles.map((c) => ({
    circle: c.circle, reportType: c.report_type,
    ...counts(c.sites_in_scope, onAirBy.get(key(c)) ?? 0, omBy ? omBy.get(key(c)) ?? 0 : null),
    ...teamFigures(c, c.sites_in_scope),
  }));
  const sum = (items: PortfolioCounts[]) => counts(
    items.reduce((n, r) => n + r.siteScope, 0),
    items.reduce((n, r) => n + r.onAir, 0),
    omBy ? items.reduce((n, r) => n + (r.omStart ?? 0), 0) : null,
  );
  const order = ['4G Saturation', 'LWE'];
  const groups: CircleBreakdownGroup[] = [...new Set(rows.map((r) => r.reportType))]
    .sort((a, b) => (order.indexOf(a) + 1 || 99) - (order.indexOf(b) + 1 || 99) || a.localeCompare(b))
    .map((reportType) => {
      const groupRows = rows.filter((r) => r.reportType === reportType).sort((a, b) => a.circle.localeCompare(b.circle));
      const subtotal = sum(groupRows);
      // People are counted once per network (a CI on two circles is one CI), so these are not sums of the rows.
      return { reportType, rows: groupRows, subtotal: { ...subtotal, ...teamFigures(all.team_totals?.[reportType], subtotal.siteScope) } };
    });
  const total = sum(rows);
  return { groups, total: { ...total, ...teamFigures(all.team_totals?.all, total.siteScope) } };
}

/** Figures for one week or month from `period/`, for On-Air and O&M Start sites. */
export interface PeriodFigures {
  onAir: PeriodSummary;
  omStart: PeriodSummary | null;
}

/**
 * Uptime and bucket KPI cards for a week or a month (Site Portfolio, Weekly and Monthly views).
 * Every value comes from `period/`; changes are against the comparison period of the same kind.
 * Totals (outage minutes) are compared only when both periods have the same number of days with data.
 */
export function buildPeriodKpis(sel: PeriodFigures, cmp: PeriodFigures | null, f: PortfolioFilters, label: string, thresholdsPeriod: string | null,
  /** Both periods cover the same number of days (calendar days for months, days with data otherwise). */
  sameLength: boolean): Kpi[] {
  const a = sel.onAir;
  const b = cmp?.onAir;
  const thresholds = detailLink('/thresholds', f, thresholdsPeriod ? { period: thresholdsPeriod } : {});
  return [
    {
      id: 'period_uptime', group: 'Uptime and performance', label: 'On-Air uptime', value: a.uptime_pct, unit: 'pct', period: label,
      definition: 'Outage-weighted uptime of On-Air sites over the period: 1 − Σ outage ÷ (1,440 × site-days reported). A full month uses the workbook monthly total.',
      delta: delta(a.uptime_pct, b?.uptime_pct, 'pct'), higherIsBetter: true, link: detailLink('/', f),
    },
    {
      id: 'period_om_uptime', group: 'Uptime and performance', label: 'O&M Start uptime', value: sel.omStart?.uptime_pct ?? null, unit: 'pct', period: label,
      definition: 'The same uptime for O&M Start sites (the population of the workbook threshold sheets).',
      delta: delta(sel.omStart?.uptime_pct, cmp?.omStart?.uptime_pct, 'pct'), higherIsBetter: true, link: detailLink('/', f, { scope: 'om_start' }),
    },
    {
      id: 'period_outage', group: 'Uptime and performance', label: 'Outage minutes', value: a.days_reported || a.kind === 'months' ? a.outage_minutes : null, unit: 'minutes', period: label,
      definition: 'Total outage minutes of On-Air sites in the period. Compared only when both periods have the same number of days with data.',
      delta: sameLength && b ? delta(a.outage_minutes, b.outage_minutes, 'minutes') : null, higherIsBetter: false, link: detailLink('/', f),
    },
    {
      id: 'period_reported', group: 'Uptime and performance', label: 'Sites with data', value: a.sites_reported, unit: 'sites', period: label,
      definition: 'On-Air sites with at least one outage value in the period. Sites without a value are not counted as 100%.',
      delta: delta(a.sites_reported, b?.sites_reported, 'sites'), higherIsBetter: true, link: '/data-source',
    },
    {
      id: 'gte_98_5', group: 'Uptime and performance', label: 'Sites at 98.5% or above', value: a.sites_at_or_above_98_5, unit: 'sites', period: label,
      definition: 'On-Air sites whose own uptime over the period is at least 98.5% (workbook bucket ">98.5").',
      delta: delta(a.sites_at_or_above_98_5, b?.sites_at_or_above_98_5, 'sites'), higherIsBetter: true, link: thresholds,
    },
    {
      id: 'lt_60', group: 'Uptime and performance', label: 'Sites below 60%', value: a.sites_below_60, unit: 'sites', period: label,
      definition: 'On-Air sites whose own uptime over the period is below 60% (workbook bucket "<60").',
      delta: delta(a.sites_below_60, b?.sites_below_60, 'sites'), higherIsBetter: false, link: thresholds, tone: a.sites_below_60 ? 'critical' : undefined,
    },
  ];
}
