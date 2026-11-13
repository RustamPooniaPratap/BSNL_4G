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

/**
 * Site Portfolio figures. ``selected`` and ``previous`` are summaries of the selected population (the global On-Air /
 * O&M Start selection); ``status`` holds the site status counts (total scope, On-Air, O&M Start), which are shown
 * side by side as status information only and never feed a performance figure.
 */
export interface PortfolioData {
  selected: SummaryResponse;
  previous: SummaryResponse | null;
  status: { total: number; onAir: number | null; omStart: number | null };
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

/**
 * Portfolio KPI cards. Status counts (total, On-Air, O&M Start) are labelled as such; every performance KPI is for the
 * selected population only (``sites``: "On-Air sites" / "O&M Start sites"), compared with the same population on the
 * previous reporting date. Links never set a population: the global selection applies on the target page too.
 */
export function buildKpis(d: PortfolioData, f: PortfolioFilters, labels: { day: string; mtd: string }, sites: string): Kpi[] {
  const { selected, previous, status } = d;
  const m = selected.metrics;
  const p = previous?.metrics;
  const kpis: Kpi[] = [
    {
      id: 'total', group: 'Site portfolio', label: 'Total sites (status)', value: status.total, unit: 'sites', period: 'In the Consolidation Matrix',
      definition: 'Site status: every dashboard site for the selected report type and circle (duplicates removed), whatever the population.',
      delta: null, higherIsBetter: null, link: detailLink('/', f),
    },
    {
      id: 'on_air', group: 'Site portfolio', label: 'On-Air sites (status)', value: status.onAir, unit: 'sites', period: 'Site On-Air Date',
      definition: 'Site status: sites with a Site On-Air Date on or before the end of the month. No previous-period comparison.',
      delta: null, higherIsBetter: null, link: detailLink('/', f),
    },
    {
      id: 'om_start', group: 'Site portfolio', label: 'O&M Start sites (status)', value: status.omStart, unit: 'sites', period: 'O&M Start Date',
      definition: 'Site status: sites with an O&M Start Date on or before the end of the month. Not available without O&M Start dates.',
      delta: null, higherIsBetter: null, link: detailLink('/', f),
    },
    {
      id: 'mtd_uptime', group: 'Uptime and performance', label: `MTD uptime (${sites})`, value: m.mtd_uptime_pct, unit: 'pct', period: labels.mtd,
      definition: `Outage-weighted uptime of ${sites} from the 1st to the reporting date: 1 − Σ outage ÷ (1,440 × site-days reported). Compared with the MTD to the previous reporting date.`,
      delta: delta(m.mtd_uptime_pct, p?.mtd_uptime_pct, 'pct'), higherIsBetter: true, link: detailLink('/', f),
    },
    {
      id: 'daily_uptime', group: 'Uptime and performance', label: `Daily uptime (${sites})`, value: m.daily_uptime_pct, unit: 'pct', period: labels.day,
      definition: `Outage-weighted uptime of ${sites} that reported on the reporting date. Compared with the previous reporting date.`,
      delta: delta(m.daily_uptime_pct, p?.daily_uptime_pct, 'pct'), higherIsBetter: true, link: detailLink('/', f),
    },
    {
      id: 'gte_98_5', group: 'Uptime and performance', label: 'Sites at 98.5% or above', value: m.sites_at_or_above_98_5_mtd, unit: 'sites', period: labels.mtd,
      definition: `${sites} whose own MTD uptime is at least 98.5% (workbook bucket ">98.5").`,
      delta: delta(m.sites_at_or_above_98_5_mtd, p?.sites_at_or_above_98_5_mtd, 'sites'), higherIsBetter: true, link: detailLink('/thresholds', f),
    },
    {
      id: 'lt_60', group: 'Uptime and performance', label: 'Sites below 60%', value: m.sites_below_60_mtd, unit: 'sites', period: labels.mtd,
      definition: `${sites} whose own MTD uptime is below 60% (workbook bucket "<60"). These need attention first.`,
      delta: delta(m.sites_below_60_mtd, p?.sites_below_60_mtd, 'sites'), higherIsBetter: false,
      link: detailLink('/', f, { bucket: 'lt_60' }), tone: m.sites_below_60_mtd ? 'critical' : undefined,
    },
    {
      id: 'down_all_day', group: 'Uptime and performance', label: 'Sites down all day', value: m.sites_down_full_day, unit: 'sites', period: labels.day,
      definition: `${sites} with 1,440 or more outage minutes on the reporting date.`,
      delta: delta(m.sites_down_full_day, p?.sites_down_full_day, 'sites'), higherIsBetter: false,
      link: detailLink('/', f, { bucket: 'lt_60', bucket_basis: 'daily' }), tone: m.sites_down_full_day ? 'critical' : undefined,
    },
    {
      id: 'coverage', group: 'Reporting and operations', label: 'Reporting completeness', value: m.coverage_pct, unit: 'pct', period: labels.day,
      definition: `${sites} with an outage value on the reporting date ÷ ${sites}. Missing values are not counted as 100%.`,
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
 * reported on the date, circles with no daily data or CSV past a configured deadline,
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
        id: `missing-${c.report_type}-${c.circle}`, circle: label(c.circle, c.report_type), type: 'Sites not reported on the date', count: missing,
        reportingDate: f.date, severity: 'warning', link: detailLink('/', { ...f, reportType: c.report_type, circle: c.circle }),
      });
    }
  }
  for (const s of arrivals) {
    if (s.status === 'late') {
      out.push({ id: `late-${s.key}`, circle: label(s.circle, s.reportType), type: 'No daily data or CSV past the configured deadline', count: null, reportingDate: s.reportingDate, severity: 'critical', link: '/daily-ingestion' });
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
  /** Distinct BSNL Site IDs in the full dashboard inventory for the circle. */
  siteScope: number;
  onAir: number;
  omStart: number | null;
  /** Site Scope − O&M Start */
  gapTotal: number | null;
  /** On Air − O&M Start */
  gapOnAir: number | null;
}

/** CIs and IEs named on the selected population, and its average sites per CI / IE (one decimal). */
export interface TeamFigures {
  ciCount: number;
  ieCount: number;
  sitesPerCi: number | null;
  sitesPerIe: number | null;
}

export interface CircleBreakdownRow extends PortfolioCounts, TeamFigures {
  circle: string;
  reportType: string;
  omHeads: string[];
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

const perPerson = (sites: number, people: number) => (people ? Math.round((10 * sites) / people) / 10 : null);
const teamFigures = (t: BreakdownResponse['team_totals'][string], sites: number): TeamFigures => ({
  ciCount: t.ci_count, ieCount: t.ie_count,
  sitesPerCi: perPerson(sites, t.ci_count), sitesPerIe: perPerson(sites, t.ie_count),
});

/**
 * Site Scope is the full dashboard inventory; status counts are from both population breakdowns. Team counts and ratios
 * follow the selected global population so their site numerator and distinct-person denominator use the same sites.
 */
export function circleBreakdown(onAir: BreakdownResponse, omStart: BreakdownResponse | null, selected: BreakdownResponse = onAir) {
  const key = (c: { report_type: string; circle: string }) => `${c.report_type}|${c.circle}`;
  const inScope = (b: BreakdownResponse | null) => new Map((b?.circles ?? []).map((c) => [key(c), c.sites_in_scope]));
  const onAirBy = inScope(onAir);
  const omBy = omStart ? inScope(omStart) : null;
  const rows: CircleBreakdownRow[] = selected.circles.map((c) => {
    const siteScope = c.sites_total;
    const selectedSites = c.sites_in_scope;
    return {
      circle: c.circle, reportType: c.report_type,
      omHeads: c.om_heads ?? [],
      ...counts(siteScope, onAirBy.get(key(c)) ?? 0, omBy ? omBy.get(key(c)) ?? 0 : null),
      ...teamFigures(c, selectedSites),
    };
  });
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
      const selectedSites = selected.circles
        .filter((circle) => circle.report_type === reportType)
        .reduce((n, circle) => n + circle.sites_in_scope, 0);
      // People are counted once per network (a CI on two circles is one CI), so use API totals rather than summing rows.
      return { reportType, rows: groupRows, subtotal: { ...subtotal, ...teamFigures(selected.team_totals[reportType], selectedSites) } };
    });
  const total = sum(rows);
  const selectedSites = selected.circles.reduce((n, circle) => n + circle.sites_in_scope, 0);
  return { groups, total: { ...total, ...teamFigures(selected.team_totals.all, selectedSites) } };
}

/**
 * Uptime and bucket KPI cards for a week or a month (Site Portfolio, Weekly and Monthly views), for the selected
 * population only (``sites``). Every value comes from `period/`; changes are against the comparison period of the same
 * kind. Totals (outage minutes) are compared only when both periods have the same number of days with data.
 */
export function buildPeriodKpis(a: PeriodSummary, b: PeriodSummary | null, f: PortfolioFilters, label: string, thresholdsPeriod: string | null,
  /** Both periods cover the same number of days (calendar days for months, days with data otherwise). */
  sameLength: boolean, sites: string): Kpi[] {
  const thresholds = detailLink('/thresholds', f, thresholdsPeriod ? { period: thresholdsPeriod } : {});
  return [
    {
      id: 'period_uptime', group: 'Uptime and performance', label: `Uptime (${sites})`, value: a.uptime_pct, unit: 'pct', period: label,
      definition: `Outage-weighted uptime of ${sites} over the period: 1 − Σ outage ÷ (1,440 × site-days reported). A full month uses the workbook monthly total.`,
      delta: delta(a.uptime_pct, b?.uptime_pct, 'pct'), higherIsBetter: true, link: detailLink('/', f),
    },
    {
      id: 'period_outage', group: 'Uptime and performance', label: 'Outage minutes', value: a.days_reported || a.kind === 'months' ? a.outage_minutes : null, unit: 'minutes', period: label,
      definition: `Total outage minutes of ${sites} in the period. Compared only when both periods have the same number of days with data.`,
      delta: sameLength && b ? delta(a.outage_minutes, b.outage_minutes, 'minutes') : null, higherIsBetter: false, link: detailLink('/', f),
    },
    {
      id: 'period_reported', group: 'Uptime and performance', label: 'Sites with data', value: a.sites_reported, unit: 'sites', period: label,
      definition: `${sites} with at least one outage value in the period. Sites without a value are not counted as 100%.`,
      delta: delta(a.sites_reported, b?.sites_reported, 'sites'), higherIsBetter: true, link: '/data-source',
    },
    {
      id: 'gte_98_5', group: 'Uptime and performance', label: 'Sites at 98.5% or above', value: a.sites_at_or_above_98_5, unit: 'sites', period: label,
      definition: `${sites} whose own uptime over the period is at least 98.5% (workbook bucket ">98.5").`,
      delta: delta(a.sites_at_or_above_98_5, b?.sites_at_or_above_98_5, 'sites'), higherIsBetter: true, link: thresholds,
    },
    {
      id: 'lt_60', group: 'Uptime and performance', label: 'Sites below 60%', value: a.sites_below_60, unit: 'sites', period: label,
      definition: `${sites} whose own uptime over the period is below 60% (workbook bucket "<60").`,
      delta: delta(a.sites_below_60, b?.sites_below_60, 'sites'), higherIsBetter: false, link: thresholds, tone: a.sites_below_60 ? 'critical' : undefined,
    },
  ];
}
