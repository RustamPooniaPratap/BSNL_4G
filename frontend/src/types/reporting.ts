/**
 * Reporting configuration and reporting status of the data layer (backend apps/sitedata: reporting units, coverage
 * threshold, month finalization, Complete / Provisional status of dates and periods).
 */

/** Status of a date or period: Complete when every expected reporting unit is covered, otherwise Provisional. */
export type ReportingStatus = 'Complete' | 'Provisional';

/** A date with the reporting units (e.g. "LWE OD") still missing on it. */
export interface MissingUnits { date: string; units: string[] }

/** Status fields a period (week, month, trend period) may carry; absent in responses of older backends. */
export interface PeriodStatusFields {
  status?: ReportingStatus | null;
  missing?: MissingUnits[] | null;
}

/** Continuity of the reporting month (``source.continuity`` of the dashboard and Site Portfolio endpoints). */
export interface Continuity {
  dates_with_data: string[];
  /** The latest date with data. */
  continuous_until: string | null;
  /** Always empty now: dates are no longer dropped after a gap. Kept for older responses. */
  excluded_after_gap: string[];
  /** Provisional dates. */
  incomplete_dates?: string[];
  date_status?: { date: string; status: ReportingStatus; missing_units: string[] }[];
  mtd_status?: ReportingStatus | null;
  missing?: MissingUnits[];
}

// --- Reporting units (Admin) -------------------------------------------------------------------

export type ReportingUnitAction = 'created' | 'corrected' | 'deactivated' | 'reactivated';

export interface ReportingUnitState {
  technology?: string;
  circle?: string;
  active_from?: string;
  active_until?: string | null;
  notes?: string;
}

export interface ReportingUnitChange {
  action: ReportingUnitAction;
  before: ReportingUnitState;
  after: ReportingUnitState;
  reason: string;
  user: string | null;
  at: string;
}

/** A circle + technology expected to report from ``active_from`` until ``active_until`` (null = still active). */
export interface ReportingUnit {
  id: number;
  technology: string;
  circle: string;
  active_from: string;
  active_until: string | null;
  notes: string;
  /** Newest first. */
  changes: ReportingUnitChange[];
}

export interface ReportingUnitInput {
  technology: string;
  circle: string;
  active_from: string;
  reason: string;
  notes?: string;
}

export interface ReportingUnitPatch {
  active_from?: string;
  active_until?: string | null;
  notes?: string;
  reason: string;
}

// --- Coverage threshold (Admin) ----------------------------------------------------------------

export interface CoverageThresholdChange {
  value_pct: number;
  previous_value_pct: number | null;
  effective_from: string;
  reason: string;
  changed_by: string | null;
  changed_at: string;
}

export interface CoverageThresholdResponse {
  current_pct: number;
  /** The site availability threshold (98.5 %): a different rule, shown for reference only. */
  availability_threshold_pct: number;
  history: CoverageThresholdChange[];
}

export interface CoverageThresholdInput {
  value_pct: number;
  effective_from: string;
  reason: string;
  confirm_retroactive?: boolean;
}

export interface CoverageThresholdResult {
  value_pct: number;
  previous_value_pct: number | null;
  effective_from: string;
}

// --- Month finalization (Admin) ----------------------------------------------------------------

export type FinalizationStatus = 'open' | 'complete' | 'incomplete_missing_data' | 'reopened';

export interface MonthFinalization {
  revision: number;
  status: 'complete' | 'incomplete_missing_data' | string;
  status_label: string;
  missing: { technology: string; circle: string; dates: string[] }[];
  finalized_at: string;
  finalized_by: string | null;
  reopened_at: string | null;
  reopened_by: string | null;
  reopen_reason: string | null;
}

export interface FinalizeMonthResult {
  month: string;
  finalized_records: number;
  finalization?: MonthFinalization | null;
}

export interface ReopenMonthResult {
  month: string;
  finalization: MonthFinalization | null;
}
