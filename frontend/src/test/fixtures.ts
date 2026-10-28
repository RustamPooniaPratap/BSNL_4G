import type {
  ActiveWorkbook, BreakdownResponse, FilterOptions, MonthlyResponse, TeamsResponse, RecordsResponse, SiteRecord, SourceInfo, SourceStatusResponse, ThresholdChange, ThresholdCompared, ThresholdMonthlyColumn, ThresholdResponse, ThresholdRow, ThresholdValue, PeriodSummary,
  SummaryResponse, TrendResponse,
} from '../types';

export const source: SourceInfo = {
  workbook: 'master.xlsx',
  sheet: 'Up-Time Report',
  modified_at: '2026-10-19T18:00:32',
  loaded_at: '2026-10-22T10:00:00',
  latest_reporting_date: '2026-10-03',
};

export const filterOptions: FilterOptions = {
  report_types: [
    { value: '4G Saturation', label: '4G Saturation', site_count: 4 },
    { value: 'LWE', label: 'LWE', site_count: 3 },
  ],
  circles: [
    { value: 'BH', label: 'BH', report_types: ['LWE'], site_count: 1 },
    { value: 'MP', label: 'MP', report_types: ['4G Saturation', 'LWE'], site_count: 4 },
    { value: 'RJ', label: 'RJ', report_types: ['4G Saturation'], site_count: 1 },
  ],
  scopes: [
    { value: 'on_air', label: 'On-Air sites', available: true },
    { value: 'om_start', label: 'O&M Start sites', available: true },
    { value: 'all', label: 'All sites', available: true },
  ],
  default_scope: 'on_air',
  buckets: [],
  reporting_dates: ['2026-10-01', '2026-10-02', '2026-10-03'],
  default_date: '2026-10-03',
  default_trend_range: { start: '2026-10-01', end: '2026-10-03' },
  months: [{ key: '2026-08', label: 'Aug-26' }, { key: '2026-09', label: 'Sep-26' }, { key: '2026-10', label: 'Oct-26 MTD' }],
  month: { label: 'Oct-26', start: '2026-10-01', end: '2026-10-31' },
  source,
};

export const summary: SummaryResponse = {
  reporting_date: '2026-10-03',
  mtd_window: { start: '2026-10-01', end: '2026-10-03', days_reported: 3, days_missing: [] },
  metrics: {
    sites_total: 7, sites_in_scope: 5, sites_reported: 4, sites_missing: 1, coverage_pct: 80,
    daily_uptime_pct: 75, daily_outage_minutes: 1440, sites_without_outage: 3, sites_down_full_day: 1,
    mtd_uptime_pct: 93.0676, mtd_outage_minutes: 2000, sites_below_60_mtd: 2, sites_at_or_above_98_5_mtd: 3,
    out_of_range_values: 0,
  },
  filters: { report_type: null, circle: null, scope: 'on_air' },
  source,
};

export const trend: TrendResponse = {
  series: [
    { date: '2026-10-01', reported: true, sites_in_scope: 5, sites_reported: 5, coverage_pct: 100, outage_minutes: 360, uptime_pct: 95, by_report_type: { '4G Saturation': 94, LWE: 96 }, outage_by_report_type: { '4G Saturation': 250, LWE: 110 } },
    { date: '2026-10-02', reported: false, sites_in_scope: 5, sites_reported: 0, coverage_pct: null, outage_minutes: null, uptime_pct: null, by_report_type: { '4G Saturation': null, LWE: null }, outage_by_report_type: { '4G Saturation': null, LWE: null } },
  ],
  report_types: ['4G Saturation', 'LWE'],
  weeks: [
    { label: 'Week 1', start: '2026-10-01', end: '2026-10-07', days_in_week: 7, days_reported: 1, uptime_pct: 95, change_pts: null, by_report_type: { '4G Saturation': 94, LWE: 96 }, outage_minutes: 360, outage_by_report_type: { '4G Saturation': 250, LWE: 110 } },
    { label: 'Week 2', start: '2026-10-08', end: '2026-10-14', days_in_week: 7, days_reported: 0, uptime_pct: null, change_pts: null, by_report_type: { '4G Saturation': null, LWE: null }, outage_minutes: null, outage_by_report_type: { '4G Saturation': null, LWE: null } },
  ],
  filters: { report_type: null, circle: null, scope: 'on_air', start_date: '2026-10-01', end_date: '2026-10-02' },
  source,
};

export const breakdown: BreakdownResponse = {
  reporting_date: '2026-10-03',
  mtd_window: { start: '2026-10-01', end: '2026-10-03', days_reported: 3 },
  comparison: { key: '2026-09', label: 'Sep-26', available: false, start: null, end: null, days_reported: 0 },
  circles: [{
    report_type: '4G Saturation', circle: 'MP', sites_in_scope: 2, sites_reported: 2, daily_uptime_pct: 50, mtd_uptime_pct: 80,
    previous_uptime_pct: null, mtd_change_pts: null,
    buckets: { lt_60: 1, '60_90': 1, '90_97': 0, '97_98_5': 0, gte_98_5: 0 },
    daily_buckets: { lt_60: 1, '60_90': 0, '90_97': 0, '97_98_5': 0, gte_98_5: 1 },
  }],
  buckets: [
    { id: 'lt_60', label: 'Below 60%', workbook_label: '<60', count: 1 },
    { id: '60_90', label: '60% to <90%', workbook_label: '>60 To <90', count: 1 },
    { id: '90_97', label: '90% to <97%', workbook_label: '>90 To <97', count: 0 },
    { id: '97_98_5', label: '97% to <98.5%', workbook_label: '>97 To <98.5', count: 0 },
    { id: 'gte_98_5', label: '98.5% and above', workbook_label: '>98.5', count: 0 },
  ],
  daily_buckets: [
    { id: 'lt_60', label: 'Below 60%', workbook_label: '<60', count: 1 },
    { id: '60_90', label: '60% to <90%', workbook_label: '>60 To <90', count: 0 },
    { id: '90_97', label: '90% to <97%', workbook_label: '>90 To <97', count: 0 },
    { id: '97_98_5', label: '97% to <98.5%', workbook_label: '>97 To <98.5', count: 0 },
    { id: 'gte_98_5', label: '98.5% and above', workbook_label: '>98.5', count: 1 },
  ],
  filters: { report_type: null, circle: null, scope: 'on_air' },
  source,
};

export const site = (id: string, overrides: Partial<SiteRecord> = {}): SiteRecord => ({
  site_id: id, site_name: `Site ${id}`, report_type: '4G Saturation', circle: 'MP', oa: 'Bhopal', ba: 'Bhopal', eb: 'EB',
  on_air: true, om_start: true, outage_minutes: 144, daily_uptime_pct: 90, mtd_uptime_pct: 92.5, bucket: '90_97',
  ie_name: 'IE MP', ci_name: 'CI East',
  ...overrides,
});

export const records = (count: number, page = 1, pages = 1): RecordsResponse => ({
  reporting_date: '2026-10-03',
  count,
  page,
  page_size: 25,
  pages,
  records: Array.from({ length: Math.min(count, 3) }, (_, i) => site(`UVMP00${i + 1}`)),
  source,
});

export const sourceStatus: SourceStatusResponse = {
  status: 'ok',
  source,
  month: 'Oct-26',
  site_counts: { total: 7, by_report_type: { '4G Saturation': 4, LWE: 3 }, on_air: 5, om_start: 5 },
  reporting_dates: ['2026-10-01', '2026-10-02', '2026-10-03'],
  missing_dates: [],
  unreported_dates_in_month: [],
  warnings: [],
  sheets: [{ name: 'Up-Time Report', role: 'Source data' }, { name: 'Summ', role: 'Summary formulas' }],
  calculation_check: {
    checked: 12,
    sheets: ['Day wise Trend', 'Summ'],
    tolerance_pts: 0.5,
    difference_count: 2,
    differences: [
      { sheet: 'Summ', cell: 'D4', description: 'MP · 4G On-Air sites', unit: 'sites', workbook: 3, dashboard: 2, difference: -1, formula: null },
      { sheet: 'Summ', cell: 'E5', description: 'All circles · 4G On-Air MTD uptime', unit: 'pct', workbook: 99, dashboard: 87.22, difference: -11.78, formula: '=1-BL5/(1440*D5*14)' },
    ],
  },
};

export const activeWorkbook: ActiveWorkbook = {
  ...source,
  uploaded_at: '2026-10-22T11:30:00',
  month: 'Oct-26',
  sites: 7,
  by_report_type: { '4G Saturation': 4, LWE: 3 },
  circles: ['BH', 'MP', 'OD', 'RJ'],
  reporting_dates: ['2026-10-01', '2026-10-02', '2026-10-03'],
  warning_count: 0,
  warnings: [],
  sheets: [{ name: 'Up-Time Report', role: 'Source data' }],
};

export const monthly: MonthlyResponse = {
  reporting_date: '2026-10-03',
  months: [
    { key: '2026-09', label: 'Sep-26', start: '2026-09-01', days: 30, partial: false, sites_in_scope: 5, sites_reported: 4, uptime_pct: 95, uptime_pct_blank_as_zero: 96, change_pts: null, by_report_type: { '4G Saturation': 94, LWE: 97 }, outage_minutes: 10800, outage_by_report_type: { '4G Saturation': 7800, LWE: 3000 } },
    { key: '2026-10', label: 'Oct-26 MTD', start: '2026-10-01', days: 3, partial: true, sites_in_scope: 5, sites_reported: 5, uptime_pct: 93, uptime_pct_blank_as_zero: 93, change_pts: -2, by_report_type: { '4G Saturation': 92, LWE: 95 }, outage_minutes: 1512, outage_by_report_type: { '4G Saturation': 1100, LWE: 412 } },
  ],
  report_types: ['4G Saturation', 'LWE'],
  overall: { start: '2026-09-01', end: '2026-10-03', months: 2, uptime_pct: 94.6, by_report_type: { '4G Saturation': 93.8, LWE: 96.4 } },
  source,
};

export const teams: TeamsResponse = {
  reporting_date: '2026-10-03',
  group: 'ci',
  totals: { teams: 2, teams_with_sites_below_60: 1, sites_in_scope: 3, sites_below_60_mtd: 1, unassigned_sites: 0, unassigned_sites_below_60_mtd: 0 },
  teams: [
    {
      report_type: '4G Saturation', circle: 'MP', name: 'CI East', sites_in_scope: 2, daily_uptime_pct: 0, mtd_uptime_pct: 31.67,
      sites_below_60_mtd: 1, daily_outage_minutes: 2880, mtd_outage_minutes: 5904,
      buckets: { lt_60: 1, '60_90': 1, '90_97': 0, '97_98_5': 0, gte_98_5: 0 }, linked_names: ['IE MP'],
    },
    {
      report_type: '4G Saturation', circle: 'MP', name: 'CI West', sites_in_scope: 1, daily_uptime_pct: 100, mtd_uptime_pct: 98.3,
      sites_below_60_mtd: 0, daily_outage_minutes: 0, mtd_outage_minutes: 72,
      buckets: { lt_60: 0, '60_90': 0, '90_97': 0, '97_98_5': 1, gte_98_5: 0 }, linked_names: ['IE MP'],
    },
  ],
  source,
};

const share = (count: number, sites: number) => ({ count, pct: Math.round((10000 * count) / sites) / 100 });
/** Reported sites not at the two ends are put in 60-90%, so every row adds up to sites_reported. */
const tv = (reported: number, high: number, low: number, sites: number): ThresholdValue => ({
  sites_reported: reported,
  gte_98_5: share(high, sites),
  lt_60: share(low, sites),
  '60_90': share(reported - high - low, sites),
  '90_97': share(0, sites),
  '97_98_5': share(0, sites),
  below_98_5: share(reported - high, sites),
  no_value: share(sites - reported, sites),
});

const COMPARED: ThresholdCompared[] = ['lt_60', '60_90', '90_97', '97_98_5', 'gte_98_5', 'below_98_5', 'no_value'];
const KIND_ORDER = { mtd: 0, month: 1, week: 2, day: 3 } as const;

/** Stand-in for apps.dashboard.metrics.compare_values (tests only). */
function compareValues(now: ThresholdValue | undefined, before: ThresholdValue | undefined) {
  return Object.fromEntries(COMPARED.map((k) => {
    if (!now || !before) return [k, null];
    const a = now[k];
    const b = before[k];
    return [k, { count: a.count, pct: a.pct, compare_count: b.count, compare_pct: b.pct, change: a.count - b.count,
      change_pct: b.count ? Math.round((1000 * (a.count - b.count)) / b.count) / 10 : null,
      change_pts: a.pct != null && b.pct != null ? Math.round(100 * (a.pct - b.pct)) / 100 : null }];
  })) as Record<ThresholdCompared, ThresholdChange | null>;
}

/**
 * Stand-in for the backend's thresholds/ resolution in tests: the selectable periods, the selected one and its
 * comparison (same rules as apps.dashboard.metrics.resolve_periods), every change, and the monthly columns.
 */
export function asThresholdResponse(base: Omit<ThresholdResponse, 'selection' | 'monthly_comparison' | 'penalty'> & Partial<ThresholdResponse>,
  params: URLSearchParams = new URLSearchParams(), previousMtd: ThresholdValue = null): ThresholdResponse {
  const choices = base.periods.map((p, i) => ({ p, i })).filter(({ p }) => base.total.values[p.key])
    .sort((a, b) => KIND_ORDER[a.p.kind] - KIND_ORDER[b.p.kind] || b.i - a.i).map(({ p }) => p);
  const wanted = params.get('period');
  const selected = choices.find((p) => p.key === wanted) ?? choices.find((p) => p.kind === 'mtd') ?? choices[0] ?? null;
  const vs = params.get('vs');
  let compare: string | null = null;
  if (selected && vs !== 'none') {
    const kind = selected.kind === 'mtd' ? 'month' : selected.kind;
    compare = vs && vs !== selected.key && choices.some((p) => p.key === vs) ? vs
      : choices.find((p) => p.kind === kind && p.key !== selected.key && p.start < selected.start)?.key ?? null;
  }
  const changes = (row: ThresholdRow) => (selected && compare ? compareValues(row.values[selected.key], row.values[compare]) : null);
  const months = base.periods.filter((p) => p.kind === 'month' && base.total.values[p.key]).slice(-7);
  const mtd = base.periods.find((p) => p.kind === 'mtd');
  const day = Number(base.reporting_date.slice(8, 10));
  const prevKey = '2026-09';
  const column = (key: string, label: string, kind: ThresholdMonthlyColumn['kind'], start: string, end: string, values: ThresholdValue, reason: string) =>
    ({ key, label, kind, start, end, sites_in_scope: base.total.sites_in_scope, status: values ? 'available' as const : 'missing' as const, reason: values ? null : reason, values });
  return {
    ...base,
    rows: base.rows.map((r) => ({ ...r, comparison: changes(r) })),
    total: { ...base.total, comparison: changes(base.total) },
    selection: { choices: choices.map((p) => p.key), period: selected?.key ?? null, compare },
    penalty: { id: 'below_98_5', label: 'Below 98.5% — Total', threshold: 98.5, buckets: ['lt_60', '60_90', '90_97', '97_98_5'] },
    monthly_comparison: {
      elapsed_days: day,
      columns: [
        ...months.map((p) => column(p.key, p.label, 'month', p.start, p.end, base.total.values[p.key], '')),
        column(`${prevKey}-mtd`, 'Sep-26 MTD', 'previous_mtd', '2026-09-01', `2026-09-${String(day).padStart(2, '0')}`, previousMtd,
          `Sep-26 has no daily data in the source for days 1–${day}, so its MTD cannot be computed.`),
        ...(mtd ? [column('mtd', mtd.label, 'mtd', mtd.start, base.reporting_date, base.total.values.mtd, 'No site reported in the month to date.')] : []),
      ],
      mtd_comparison: (() => {
        const now = base.total.values.mtd ?? null;
        const values = compareValues(now, previousMtd);
        return { current: mtd ? 'mtd' : null, previous: `${prevKey}-mtd`, available: Boolean(now && previousMtd),
          sites_reported: { current: now?.sites_reported ?? null, previous: previousMtd?.sites_reported ?? null }, values };
      })(),
    },
  };
}

export const thresholds: ThresholdResponse = asThresholdResponse({
  reporting_date: '2026-10-02',
  thresholds: [
    { id: 'lt_60', label: 'Below 60%', workbook_label: '<60' },
    { id: 'gte_98_5', label: '98.5% and above', workbook_label: '>98.5' },
  ],
  buckets: [
    { id: 'lt_60', label: 'Below 60%', workbook_label: '<60', lower: null, upper: 60 },
    { id: '60_90', label: '60% to <90%', workbook_label: '>60 To <90', lower: 60, upper: 90 },
    { id: '90_97', label: '90% to <97%', workbook_label: '>90 To <97', lower: 90, upper: 97 },
    { id: '97_98_5', label: '97% to <98.5%', workbook_label: '>97 To <98.5', lower: 97, upper: 98.5 },
    { id: 'gte_98_5', label: '98.5% and above', workbook_label: '>98.5', lower: 98.5, upper: null },
  ],
  periods: [
    { key: '2026-09', label: 'Sep-26', kind: 'month', start: '2026-09-01', end: '2026-09-30', days: 30, days_reported: 30, partial: false },
    { key: 'mtd', label: 'Oct-26 MTD', kind: 'mtd', start: '2026-10-01', end: '2026-10-02', days: 2, days_reported: 2, partial: true },
    { key: 'w1', label: 'Wk-1', kind: 'week', start: '2026-10-01', end: '2026-10-07', days: 7, days_reported: 2, partial: true },
    { key: 'w2', label: 'Wk-2', kind: 'week', start: '2026-10-08', end: '2026-10-14', days: 7, days_reported: 0, partial: false },
    { key: '2026-10-01', label: '01 Oct', kind: 'day', start: '2026-10-01', end: '2026-10-01', days: 1, days_reported: 1, partial: false },
    { key: '2026-10-02', label: '02 Oct', kind: 'day', start: '2026-10-02', end: '2026-10-02', days: 1, days_reported: 1, partial: false },
  ],
  rows: [
    {
      report_type: '4G Saturation', circle: 'MP', sites_in_scope: 4,
      values: { '2026-09': tv(4, 1, 2, 4), mtd: tv(4, 2, 1, 4), w1: tv(4, 2, 1, 4), w2: null, '2026-10-01': tv(4, 3, 1, 4), '2026-10-02': tv(3, 2, 0, 4) },
    },
    {
      report_type: 'LWE', circle: 'OD', sites_in_scope: 1,
      values: { '2026-09': null, mtd: tv(1, 1, 0, 1), w1: tv(1, 1, 0, 1), w2: null, '2026-10-01': tv(1, 1, 0, 1), '2026-10-02': tv(1, 1, 0, 1) },
    },
  ],
  total: {
    report_type: null, circle: null, sites_in_scope: 5,
    values: { '2026-09': tv(4, 1, 2, 5), mtd: tv(5, 3, 1, 5), w1: tv(5, 3, 1, 5), w2: null, '2026-10-01': tv(5, 4, 1, 5), '2026-10-02': tv(4, 3, 0, 5) },
  },
  filters: { report_type: null, circle: null, scope: 'om_start' },
  source,
});

export const period: PeriodSummary = {
  label: '01 Oct – 03 Oct', kind: 'dates', days_reported: 3, months: null, first_date: '2026-10-01', last_date: '2026-10-03',
  sites_in_scope: 5, sites_reported: 5, uptime_pct: 94.1, outage_minutes: 2880, sites_below_60: 1, sites_at_or_above_98_5: 3,
  filters: { report_type: null, circle: null, scope: 'on_air' }, source,
};
