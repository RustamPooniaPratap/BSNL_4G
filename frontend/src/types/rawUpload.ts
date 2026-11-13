/** Raw daily CSV upload (Uptime Data -> Uptime Data Upload). Every count, status and value comes from the API. */

/** A project key of the Organization (e.g. "4G Saturation"); projects are not fixed in the frontend. */
export type RawProject = string;

export interface RawUploadOptions {
  /** Active projects of the Organization; per project its active circles within the user's scope and their master size. */
  projects: { value: RawProject; configured: boolean; availability_column: string | null; circles: string[]; site_counts?: Record<string, number> }[];
  /** null: every circle (Admin, NOC Lead); otherwise the circles assigned to the account (possibly none). */
  assigned_circles: string[] | null;
  /** The same as project/circle pairs: null = not limited. */
  access?: { project: string; circle: string }[] | null;
  max_bytes: number;
  formula: string;
}

export type RawRowStatus = 'ready' | 'identical' | 'duplicate' | 'out_of_scope' | 'scope_mismatch' | 'unresolved' | 'availability' | 'date' | 'other';

/** Programme classification of a row: every row is in exactly one category (their counts add up to the rows). */
export type RawRowCategory = 'matched' | 'unmatched_programme' | 'outside_programme' | 'invalid';

export interface RawClassification {
  matched: number;
  /** In the programme (Consolidation Matrix) but not yet resolved to a master site: kept pending. */
  unmatched_programme: number;
  /** Not in the Consolidation Matrix: outside the programme scope, not counted as unmatched. */
  outside_programme: number;
  invalid: number;
}

export interface RawRow {
  line: number;
  raw_id: string;
  site_id: string | null;
  site_name: string;
  circle: string;
  report_date: string;
  raw_availability: string;
  availability: number | null;
  outage_minutes: number | null;
  /** A status group; a newer backend may send groups this frontend does not know yet. */
  status: RawRowStatus;
  category?: RawRowCategory;
  code: string;
  label: string;
  message: string;
  note: string;
}

export interface RawRowsPage { count: number; page: number; pages: number; rows: RawRow[] }

export interface RawSummary {
  total_rows: number;
  valid_in_scope: number;
  ready_to_import: number;
  identical_skipped: number;
  out_of_scope: number;
  unresolved_or_ambiguous: number;
  availability_problems: number;
  duplicates_or_conflicts: number;
  date_mismatches: number;
  project_or_circle_mismatches: number;
  other_invalid: number;
  by_code: Record<string, number>;
  /** Rows per status group (the row filter's counts). */
  by_status: Partial<Record<RawRowStatus, number>>;
  /** Rows per programme category (sum = rows); absent in older responses. */
  classification?: RawClassification;
}

export interface RawUpload {
  id: number;
  status: 'previewed' | 'committed' | 'failed' | 'rejected' | 'discarded';
  status_label: string;
  file: string;
  checksum: string;
  project: RawProject;
  circle: string;
  reporting_date: string | null;
  remarks: string | null;
  uploaded_by: string | null;
  uploaded_at: string;
  committed_at: string | null;
  error: string | null;
  summary: RawSummary | null;
  /** After the import: what was written. */
  daily: { inserted: number; filled: number; skipped_identical: number; skipped_repeats: number; rejected: number; conflicts: number; pending: number } | null;
  rejected_count: number;
  skipped_count: number;
  // Detail only.
  file_issues?: { code: string; message: string }[];
  blocked?: boolean;
  file_info?: { encoding: string; header_line: number; preamble: string[]; blank_lines: number; columns: Record<string, string>;
    unused_columns: number; report_dates: string[]; circles_in_file: Record<string, number> } | null;
  availability_rule?: { column: string; confirmed: boolean; formula: string };
  resolver?: { project: RawProject; configured: boolean };
  master_scope?: { sites: number; sites_in_file: number; missing_from_file: number; missing_examples: string[] };
  already_imported?: { batch: number; committed_at: string } | null;
  /** Genuine unmatched programme raw IDs: their rows are kept pending (no site is created). Outside-programme IDs are not listed. */
  pending_sites?: string[];
  rows?: RawRowsPage | null;
}

export interface RawUploadDetails {
  project: RawProject;
  circle: string;
  reporting_date: string;
  remarks: string;
}

// --- CSV arrival tracking (/daily-ingestion) -------------------------------------------------

/** Stored daily data for a project/circle on a date, against the master's On-Air sites. */
export type DataState = 'complete' | 'partial' | 'none' | 'no_scope';
/** The raw CSV upload lifecycle for the date (the most advanced upload when there are several). */
export type UploadState = 'imported' | 'awaiting_confirmation' | 'nothing_to_import' | 'blocked' | 'failed' | 'discarded' | 'none';

export interface TrackerUpload {
  id: number;
  state: Exclude<UploadState, 'none'>;
  status_label: string;
  file: string;
  uploaded_at: string;
  committed_at: string | null;
  uploaded_by: string | null;
  ready_to_import: number | null;
  rejected_count: number;
  /** Records written by the import (null until imported). */
  imported: number | null;
  error: string | null;
}

export interface TrackerItem {
  project: RawProject;
  circle: string;
  sites_total: number;
  sites_expected: number;
  sites_with_data: number;
  sites_invalid: number;
  sites_missing: number;
  records_observed: number;
  coverage_pct: number | null;
  /** The coverage threshold applied on the date (null/absent in older responses). */
  coverage_threshold_pct?: number | null;
  /** False when the reporting unit is not expected on the date (inactive); absent in older responses. */
  active?: boolean;
  /** 'no_scope': no On-Air sites in the master, or the unit is not expected on this date (inactive). */
  data_state: DataState;
  /** Usable records per origin: the Uptime Master import, raw daily CSV uploads and Admin corrections. */
  data_source: { master_workbook: number; raw_daily_csv: number; correction: number };
  latest_data_date: string | null;
  latest_complete_date: string | null;
  latest_upload_date: string | null;
  latest_import_date: string | null;
  upload_state: UploadState;
  uploads: TrackerUpload[];
  range: { date: string; sites_with_data: number; state: DataState }[];
}

export interface ArrivalTracker {
  reporting_date: string;
  range: { start: string; end: string };
  scope_rule: string;
  usable_rule: string;
  notes: string[];
  items: TrackerItem[];
}
