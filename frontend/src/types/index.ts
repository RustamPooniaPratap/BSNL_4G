export interface HealthStatus {
  status: string;
  service: string;
  version: string;
}

export interface CandidateColumns {
  site_id: string[];
  availability: string[];
  date: string[];
}

export interface UploadResponse {
  status: 'success' | 'partial_success' | 'error';
  message?: string;
  warning?: string;
  filename: string;
  size_bytes: number;
  row_count?: number;
  column_count?: number;
  columns?: string[];
  preview?: Record<string, string>[];
  candidate_columns?: CandidateColumns;
}

export interface RawFileInfo {
  name: string;
  size_bytes: number;
  modified_at: string;
  extension: string;
}

export interface RawFilesResponse {
  count: number;
  files: RawFileInfo[];
}

// ---------------------------------------------------------------------------
// Dashboard API (backend/apps/dashboard). Percentages are 0-100.
// ---------------------------------------------------------------------------

export type Scope = 'on_air' | 'om_start' | 'all';
export type BucketId = 'lt_60' | '60_90' | '90_97' | '97_98_5' | 'gte_98_5';

export interface SourceInfo {
  workbook: string;
  sheet: string;
  modified_at: string;
  loaded_at: string;
  uploaded_at?: string | null;
  latest_reporting_date: string | null;
}

export interface AppliedFilters {
  report_type: string | null;
  circle: string | null;
  scope: Scope;
}

export interface FilterOptions {
  report_types: { value: string; label: string; site_count: number }[];
  circles: { value: string; label: string; report_types: string[]; site_count: number }[];
  scopes: { value: Scope; label: string; available: boolean }[];
  default_scope: Scope;
  buckets: { id: BucketId; label: string; workbook_label: string }[];
  reporting_dates: string[];
  default_date: string | null;
  default_trend_range: { start: string | null; end: string | null };
  /** Months with uptime history, oldest first; the last is the current month to date. */
  months: { key: string; label: string }[];
  /** Earlier months whose daily columns are in the workbook, with their reported dates. */
  daily_history?: { key: string; label: string; dates: string[] }[];
  month: { label: string; start: string; end: string };
  source: SourceInfo;
}

export interface SummaryMetrics {
  sites_total: number;
  /** Sites with On-Air = Yes and O&M Start = Yes, over the filter whatever the scope. */
  sites_converted?: number;
  sites_in_scope: number;
  sites_reported: number;
  sites_missing: number;
  coverage_pct: number | null;
  daily_uptime_pct: number | null;
  daily_outage_minutes: number;
  sites_without_outage: number;
  sites_down_full_day: number;
  mtd_uptime_pct: number | null;
  mtd_outage_minutes: number;
  sites_below_60_mtd: number;
  sites_at_or_above_98_5_mtd: number;
  out_of_range_values: number;
}

export interface SummaryResponse {
  reporting_date: string;
  /** Sites converted with the previous month's O&M Start flag (On-Air has no history); null without that column. */
  previous_month_conversion?: { label: string; sites_converted: number } | null;
  mtd_window: { start: string; end: string; days_reported: number; days_missing: string[] };
  metrics: SummaryMetrics;
  filters: AppliedFilters;
  source: SourceInfo;
}

export interface TrendPoint {
  date: string;
  reported: boolean;
  sites_in_scope: number;
  sites_reported: number;
  coverage_pct: number | null;
  outage_minutes: number | null;
  uptime_pct: number | null;
  by_report_type: Record<string, number | null>;
  /** Outage minutes per report type; null when that type did not report. */
  outage_by_report_type: Record<string, number | null>;
  /** Per circle series, keyed "<report type>|<circle>"; null when that circle did not report. */
  by_circle?: Record<string, number | null>;
  outage_by_circle?: Record<string, number | null>;
}

/** One circle series: a circle within one network (MP 4G and MP LWE are separate). */
export interface CircleSeriesInfo {
  key: string;
  report_type: string;
  circle: string;
  sites: number;
}

export interface WeekSummary {
  label: string;
  start: string;
  end: string;
  days_in_week: number;
  days_reported: number;
  uptime_pct: number | null;
  /** Percentage points versus the previous week with data. */
  change_pts: number | null;
  by_report_type: Record<string, number | null>;
  /** Total outage minutes in the week's reported days; null when none reported. */
  outage_minutes: number | null;
  outage_by_report_type: Record<string, number | null>;
  by_circle?: Record<string, number | null>;
  outage_by_circle?: Record<string, number | null>;
}

export interface TrendResponse {
  series: TrendPoint[];
  report_types: string[];
  weeks: WeekSummary[];
  circles?: CircleSeriesInfo[];
  filters: AppliedFilters & { start_date: string; end_date: string };
  source: SourceInfo;
}

export interface CircleBreakdown {
  report_type: string;
  circle: string;
  sites_in_scope: number;
  sites_reported: number;
  daily_uptime_pct: number | null;
  mtd_uptime_pct: number | null;
  /** Uptime over the same days of the previous month; null without that month's daily data. */
  previous_uptime_pct: number | null;
  /** MTD minus the previous month's same days, in percentage points. */
  mtd_change_pts: number | null;
  /** Outage minutes month to date and over the previous month's same days; null when nothing was reported. */
  mtd_outage_minutes?: number | null;
  previous_outage_minutes?: number | null;
  buckets: Record<BucketId, number>;
  daily_buckets: Record<BucketId, number>;
  /** Distinct CIs / IEs named on the circle's sites (case and spacing ignored), and sites with none. */
  ci_count?: number;
  ie_count?: number;
  sites_without_ci?: number;
  sites_without_ie?: number;
}

export interface TeamCounts {
  ci_count: number;
  ie_count: number;
  sites_without_ci: number;
  sites_without_ie: number;
}

/** The previous month's days 1..N compared with the current month to date. */
export interface SameDaysComparison {
  key: string;
  label: string;
  available: boolean;
  start: string | null;
  end: string | null;
  days_reported: number;
}

export interface BreakdownResponse {
  reporting_date: string;
  mtd_window: { start: string; end: string; days_reported: number };
  comparison: SameDaysComparison;
  circles: CircleBreakdown[];
  /** Distinct people over all circles ('all') and per report type: someone in two circles counts once. */
  team_totals?: Record<string, TeamCounts>;
  buckets: { id: BucketId; label: string; workbook_label: string; count: number }[];
  daily_buckets: { id: BucketId; label: string; workbook_label: string; count: number }[];
  filters: AppliedFilters;
  source: SourceInfo;
}

export interface SiteRecord {
  site_id: string;
  site_name: string;
  report_type: string;
  circle: string;
  oa: string;
  ba: string;
  eb: string;
  on_air: boolean;
  om_start: boolean;
  outage_minutes: number | null;
  daily_uptime_pct: number | null;
  mtd_uptime_pct: number | null;
  bucket: BucketId | null;
  /** Responsible IE and CI from the workbook ("Unassigned" when blank). */
  ie_name: string;
  ci_name: string;
}

export type SortField =
  | 'site_id' | 'site_name' | 'report_type' | 'circle' | 'oa'
  | 'outage_minutes' | 'daily_uptime_pct' | 'mtd_uptime_pct' | 'ie_name' | 'ci_name';

export interface RecordsResponse {
  reporting_date: string;
  count: number;
  page: number;
  page_size: number;
  pages: number;
  records: SiteRecord[];
  source: SourceInfo;
}

export interface SiteDetailResponse {
  site: {
    site_id: string;
    site_name: string;
    report_type: string;
    circle: string;
    circle_as_in_workbook: string;
    oa: string;
    ba: string;
    eb: string;
    on_air: boolean;
    om_start: boolean;
    ie_name: string;
    ci_name: string;
    source_row: number;
  };
  reporting_date: string;
  mtd_uptime_pct: number | null;
  mtd_bucket: BucketId | null;
  daily: { date: string; reported: boolean; outage_minutes: number | null; uptime_pct: number | null }[];
  source: SourceInfo;
}

export interface DataWarning {
  code: string;
  severity: 'warning' | 'info';
  message: string;
  count: number;
  examples: string[];
}

export interface SourceStatusResponse {
  status: 'ok' | 'warning';
  source: SourceInfo;
  month: string;
  site_counts: {
    total: number;
    by_report_type: Record<string, number>;
    on_air: number;
    om_start: number | null;
  };
  reporting_dates: string[];
  missing_dates: string[];
  unreported_dates_in_month: string[];
  warnings: DataWarning[];
  sheets: SheetInfo[];
  calculation_check: CalculationCheck;
}

/** Workbook summary figures recalculated by the dashboard; only major differences are listed. */
export interface CalculationCheck {
  checked: number;
  sheets: string[];
  tolerance_pts: number;
  difference_count: number;
  differences: CalculationDifference[];
}

export interface CalculationDifference {
  sheet: string;
  cell: string;
  description: string;
  unit: 'pct' | 'sites';
  workbook: number;
  dashboard: number;
  difference: number;
  /** The workbook cell's formula, when it has one (e.g. "=1-BL15/(1440*$D33*14)"). */
  formula: string | null;
}

export interface SheetInfo {
  name: string;
  role: string;
}

export interface ActiveWorkbook extends SourceInfo {
  /** Which source the dashboard reads: the Excel workbook or the PostgreSQL import. */
  data_source?: 'excel' | 'database';
  uploaded_at: string | null;
  month: string;
  sites: number;
  by_report_type: Record<string, number>;
  circles: string[];
  reporting_dates: string[];
  warning_count: number;
  warnings: DataWarning[];
  sheets: SheetInfo[];
}

export interface WorkbookStatus {
  active: ActiveWorkbook | null;
  message?: string;
  code?: string;
}

export interface WorkbookUploadResult extends WorkbookStatus {
  status: 'accepted';
}

export interface MonthPoint {
  /** 'YYYY-MM' */
  key: string;
  label: string;
  start: string;
  days: number;
  partial: boolean;
  sites_in_scope: number;
  sites_reported: number;
  uptime_pct: number | null;
  uptime_pct_blank_as_zero: number | null;
  /** Percentage points versus the previous month with data. */
  change_pts: number | null;
  by_report_type: Record<string, number | null>;
  /** Total outage minutes in the month (to date for the current month); null when not reported. */
  outage_minutes: number | null;
  outage_by_report_type: Record<string, number | null>;
  by_circle?: Record<string, number | null>;
  outage_by_circle?: Record<string, number | null>;
}

export interface MonthlyResponse {
  circles?: CircleSeriesInfo[];
  reporting_date: string;
  report_types: string[];
  months: MonthPoint[];
  overall: {
    start: string | null;
    end: string;
    months: number;
    uptime_pct: number | null;
    by_report_type: Record<string, number | null>;
  };
  source: SourceInfo;
}

export type TeamGroup = 'ci' | 'ie';

export interface TeamRow {
  report_type: string;
  circle: string;
  name: string;
  sites_in_scope: number;
  daily_uptime_pct: number | null;
  mtd_uptime_pct: number | null;
  sites_below_60_mtd: number;
  daily_outage_minutes: number;
  mtd_outage_minutes: number;
  buckets: Record<BucketId, number>;
  /** For a CI, the IEs under it; for an IE, the CI(s) it reports to. */
  linked_names: string[];
}

export interface TeamTotals {
  teams: number;
  teams_with_sites_below_60: number;
  sites_in_scope: number;
  sites_below_60_mtd: number;
  unassigned_sites: number;
  unassigned_sites_below_60_mtd: number;
}

export interface TeamsResponse {
  reporting_date: string;
  group: TeamGroup;
  totals: TeamTotals;
  teams: TeamRow[];
  source: SourceInfo;
}

/** NSLA (uptime below 98.5%) of one person's sites in one month; null when none of them reported. */
export interface NslaValue {
  sites_reported: number;
  nsla_sites: number;
  /** Share of the assigned sites in scope (not only those reported). */
  nsla_pct: number | null;
  no_value: number;
}

export interface TeamMonth {
  key: string;
  label: string;
  /** "mtd": the current month to the reporting date. */
  kind: 'month' | 'mtd';
  start: string;
  end: string;
}

export interface TeamMonthlyRow {
  report_type: string;
  circle: string;
  name: string;
  sites_in_scope: number;
  months: Record<string, NslaValue | null>;
}

export interface TeamMonthlyResponse {
  group: TeamGroup;
  reporting_date: string;
  /** Months with data, oldest first (the reporting month filter). */
  months_available: TeamMonth[];
  reporting_month: string | null;
  /** Columns: oldest first, the last is the reporting month. */
  months: TeamMonth[];
  totals: { people: number; sites_in_scope: number; months: Record<string, NslaValue | null> };
  /** Name order from the backend; no ranking. */
  rows: TeamMonthlyRow[];
  unsupported: { field: string; reason: string }[];
  source: SourceInfo;
}

export interface RankedPerson {
  name: string;
  sites_in_scope: number;
  sites_reported: number;
  nsla_sites: number | null;
  nsla_pct: number | null;
  /** Only eligible people are ranked; the others carry the reason. */
  eligible: boolean;
  reason: string | null;
  /** Competition ranking (1, 1, 3): equal NSLA shares tie. */
  rank: number | null;
  /** The same person's assignments in other circles / projects, e.g. "OD LWE". */
  other_assignments: string[] | null;
}

export interface GroupRanking {
  /** ranked: one best; tie: several share the best; insufficient: fewer than the minimum eligible people; none: no one assigned. */
  status: 'ranked' | 'tie' | 'insufficient' | 'none';
  reason: string | null;
  top: string[];
  people_total: number;
  people_eligible: number;
  /** Eligible people best first, then the ineligible ones (unranked). */
  ranking: RankedPerson[];
}

export interface TopPerformerCircle {
  report_type: string;
  circle: string;
  sites_in_scope: number;
  /** Circle-wise NSLA per month key; null when no site reported in that month. */
  nsla: Record<string, NslaValue | null>;
  /** Rank within the project by the reporting month's NSLA % (ties share a rank); null without a value. */
  nsla_rank: number | null;
  ci: GroupRanking;
  ie: GroupRanking;
}

export interface TopPerformersResponse {
  reporting_date: string;
  months_available: TeamMonth[];
  reporting_month: string | null;
  month: TeamMonth | null;
  /** Monthly columns, oldest first; the last is the reporting month. */
  months: TeamMonth[];
  rules: { min_sites: number; min_people: number; nsla_threshold_pct: number };
  circles: TopPerformerCircle[];
  projects: { report_type: string; sites_in_scope: number; nsla: Record<string, NslaValue | null> }[];
  source: SourceInfo;
}

export type AlertSeverity = 'critical' | 'warning' | 'info';

export interface DashboardAlert {
  id: string;
  severity: AlertSeverity;
  title: string;
  detail: string;
  /** In-app route, e.g. "/?bucket=lt_60". */
  link: string;
}

export interface AlertsResponse {
  alerts: DashboardAlert[];
  counts: Record<AlertSeverity, number>;
  source: SourceInfo;
}

export type ThresholdId = 'gte_98_5' | 'lt_60';

/** One uptime bucket: lower bound inclusive, upper bound exclusive (workbook Bucket formula). */
export interface ThresholdBucket {
  id: BucketId;
  label: string;
  workbook_label: string;
  lower: number | null;
  upper: number | null;
}
export type PeriodKind = 'month' | 'mtd' | 'week' | 'day';

export interface ThresholdPeriod {
  /** 'YYYY-MM' for months, 'mtd', 'w1'..'w4', or the ISO date for days. */
  key: string;
  label: string;
  kind: PeriodKind;
  start: string;
  end: string;
  days: number;
  days_reported: number;
  /** Still in progress on the reporting date (MTD, current week). */
  partial: boolean;
}

export interface ThresholdCount {
  count: number;
  /** Percentage of all sites in scope. */
  pct: number;
}

/**
 * Counts for every bucket, the below-98.5% aggregate (sum of the buckets below it) and the sites with no value,
 * all computed by the backend; null when no site in the row reported in the period.
 */
export type ThresholdValue = ({ sites_reported: number; below_98_5: ThresholdCount; no_value: ThresholdCount }
  & Record<BucketId, ThresholdCount>) | null;

/** Change between the selected period and its comparison, computed by the backend. */
export interface ThresholdChange {
  count: number;
  pct: number | null;
  compare_count: number;
  compare_pct: number | null;
  change: number;
  /** Relative change of the count, %; null when the comparison count is 0. */
  change_pct: number | null;
  change_pts: number | null;
}
export type ThresholdCompared = BucketId | 'below_98_5' | 'no_value';

export interface ThresholdRow {
  report_type: string | null;
  circle: string | null;
  sites_in_scope: number;
  values: Record<string, ThresholdValue>;
  /** Per bucket, aggregate and no-value; null without a comparison; an entry is null when either period has no data. */
  comparison?: Record<ThresholdCompared, ThresholdChange | null> | null;
}

/** A Monthly comparison column: a full month, the previous month's same elapsed days, or the month to date. */
export interface ThresholdMonthlyColumn {
  key: string;
  label: string;
  kind: 'month' | 'previous_mtd' | 'mtd';
  start: string;
  end: string;
  sites_in_scope: number;
  status: 'available' | 'missing';
  reason: string | null;
  values: ThresholdValue;
}

export interface ThresholdResponse {
  reporting_date: string;
  thresholds: { id: ThresholdId; label: string; workbook_label: string }[];
  buckets: ThresholdBucket[];
  periods: ThresholdPeriod[];
  rows: ThresholdRow[];
  total: ThresholdRow;
  /** The selectable periods, the selected one and its comparison, as resolved by the backend. */
  selection: { choices: string[]; period: string | null; compare: string | null };
  /** The penalty threshold and the buckets summed into its aggregate. */
  penalty: { id: 'below_98_5'; label: string; threshold: number; buckets: BucketId[] };
  monthly_comparison: {
    elapsed_days: number;
    columns: ThresholdMonthlyColumn[];
    /** Month to date against the previous month's same elapsed days; entries are null when either has no data. */
    mtd_comparison: {
      current: string | null;
      previous: string | null;
      available: boolean;
      /** Sites with a value in each period (they differ when part of the scope has no daily data for the days). */
      sites_reported: { current: number | null; previous: number | null };
      values: Record<ThresholdCompared, ThresholdChange | null>;
    };
  };
  filters: AppliedFilters;
  source: SourceInfo;
}

/** KPI for the trend period picked in the filter bar. */
export interface PeriodSummary {
  label: string;
  kind: 'dates' | 'months';
  days_reported: number;
  months: number | null;
  first_date: string | null;
  last_date: string | null;
  sites_in_scope: number;
  sites_reported: number;
  uptime_pct: number | null;
  outage_minutes: number;
  sites_below_60: number;
  sites_at_or_above_98_5: number;
  /** Sites in each bucket by their own uptime over the period. */
  buckets?: Record<BucketId, number>;
  filters: AppliedFilters;
  source: SourceInfo;
}

// --- Email -------------------------------------------------------------------------------

export interface EmailStatus {
  /** True with the console (or another local) backend: emails are printed, never delivered. */
  test_mode: boolean;
  transport: string;
  from_email: string;
  automatic_reminders: boolean;
}

export interface ReminderRequest {
  circle: string;
  report_type: string;
  reporting_date: string;
  /** Only when a deadline is configured (YYYY-MM-DDTHH:MM). */
  deadline?: string;
}

export interface ReminderTemplate extends EmailStatus {
  subject: string;
  body: string;
}

export interface EmailResult {
  /** "printed" in test mode; "accepted" when a real mail server took it. */
  status: 'printed' | 'accepted';
  test_mode: boolean;
  kind: 'reminder' | 'personal';
  to: string[];
  cc: string[];
  subject: string;
  message: string;
}

// --- Accounts ------------------------------------------------------------------------------

export type Role = 'admin' | 'ci';

/** The signed-in user, from /auth/me/ (the role is decided by the server). */
export interface AuthUser {
  username: string;
  name: string;
  role: Role | null;
  role_label: string;
  must_change_password: boolean;
}

/** An account as listed for Admins. Passwords are never returned, except a new temporary one once. */
export interface PortalUser {
  id: number;
  username: string;
  name: string;
  email: string;
  role: Role | null;
  is_active: boolean;
  is_superuser: boolean;
  must_change_password: boolean;
  last_login: string | null;
  date_joined: string;
}

// --- PostgreSQL import and dashboard data source ---------------------------------------------

export type DataSourceKind = 'excel' | 'database';

export interface DatabaseCompleteness {
  sites: number;
  monthly_records: number;
  daily_records: number;
  months: string[];
  daily_months: Record<string, { label: string; first: string; last: string; days: number; gaps: string[] }>;
  previous_month_daily: boolean;
  last_import: { batch: number; file: string; committed_at: string } | null;
  empty: boolean;
  warnings: string[];
}

export interface DataSourceState {
  active: DataSourceKind;
  label: string;
  options: { value: DataSourceKind; label: string }[];
  database: DatabaseCompleteness;
}

export interface ImportFileSummary {
  filename: string;
  checksum: string;
  sheet: string;
  has_project_column: boolean;
  data_rows: number;
  sites: number;
  distinct_site_ids: number;
  by_project: Record<string, number>;
  by_circle: Record<string, number>;
  months: Record<string, { label: string; sites_with_values: number }>;
  daily: Record<string, { outage_columns: string; uptime_columns: string | null; dates: string[]; reported_dates: string[]; missing_values: Record<string, number>; site_day_values: number }>;
  skipped: Record<string, number>;
  rejected: number;
  flagged: number;
  issues: Record<string, { severity: 'rejected' | 'flagged'; count: number; examples: { row: number | null; site_id: string; message: string }[] }>;
}

export interface ImportComparison {
  primary: string;
  reconciliation: string;
  overlapping_sites: number;
  only_in_primary: number;
  only_in_reconciliation: number;
  sites_with_differences: number;
  differences: Record<string, { count: number; examples: { circle: string; site_id: string; where: string; primary: unknown; reconciliation: unknown }[] }>;
  dates_only_in_reconciliation: string[];
}

export interface ImportBatch {
  id: number;
  status: 'previewed' | 'committed' | 'failed' | 'discarded';
  file: string;
  checksum: string;
  sheet: string;
  reconciliation_file: string | null;
  conflict_source: 'primary' | 'reconciliation' | null;
  uploaded_at: string;
  committed_at: string | null;
  imported_by: string | null;
  via: string;
  counts: Record<string, { inserted: number; updated: number; unchanged: number } | number>;
  rejected: number;
  skipped: number;
  error: string | null;
  report?: {
    primary: ImportFileSummary;
    reconciliation?: ImportFileSummary;
    comparison?: ImportComparison;
    database_effect: { sites_in_database: number; new_sites: number; existing_sites: number; database_sites_not_in_file: number };
    options?: { project: string | null; daily_only: boolean };
    /** Daily-values-only import: sites that can receive values, and whether the days add up to the monthly totals. */
    daily_effect?: {
      months: string[]; sites_in_file: number; sites_in_database: number; sites_not_in_database: number;
      monthly_total_checks: Record<string, { sites_compared: number; file_monthly_total_differs: number; database_monthly_total_differs: number }>;
    };
    already_imported?: { batch: number; committed_at: string };
  };
}

/** O&M Head per circle from the reference sheet in Data/reference (null = no name given). */
/** One month of On-Air / O&M Start activity from the escalation matrix; count is null when the file does not cover the month yet. */
export interface ActivityPeriod { count: number | null; covered_to: string | null; complete: boolean }
export interface ActivityKind { this_month: ActivityPeriod; last_month: ActivityPeriod; change: number | null; latest_date: string | null }
export interface ConversionActivity {
  source: string;
  sites: number;
  month: { key: string; label: string };
  previous_month: { key: string; label: string };
  on_air: ActivityKind;
  om_start: ActivityKind;
}

export interface OmHeadsResponse {
  source: string | null;
  heads: { report_type: string; circle: string; circle_in_sheet: string; om_head: string | null }[];
  message: string | null;
}
