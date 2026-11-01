/** RCA register API types (backend: apps/rca). Source facts are as written in the RCA workbook. */

export type RcaStatus = 'investigation' | 'rca_review' | 'action_pending' | 'action_completed' | 'closed';
export type RcaReview = 'pending' | 'confirmed' | 'needs_revision';
export type RcaVerification = 'effective' | 'not_effective' | 'not_verifiable';

export interface RcaRecord {
  id: number;
  reporting_date: string;
  project: string;
  /** As written in the source, e.g. "4G Satu". */
  project_raw: string;
  circle: string;
  circle_raw: string;
  site_id: string;
  site_name: string;
  oa: string;
  ba: string;
  om_start_raw: string;
  om_start: boolean | null;
  outage_minutes: number | null;
  final_bucket: string;
  final_bucket_unclassified: boolean;
  bucket_2: string;
  bucket_2_unclassified: boolean;
  rca_text: string;
  rca_unclassified: boolean;
  /** False for Other Media (Final Bucket): RCA recording is not applicable. */
  rca_applicable: boolean;
  /** Admin-approved canonical category; null = description not reviewed yet. */
  category: { id: number; name: string } | null;
  source: 'import' | 'manual';
  status: RcaStatus | null;
  status_label: string | null;
}

export interface RcaWorkflow {
  status: RcaStatus | null;
  status_label: string | null;
  review_status: RcaReview | null;
  review_status_label: string | null;
  corrective_action: string | null;
  owner: string | null;
  target_date: string | null;
  completed_date: string | null;
  verification: RcaVerification | null;
  verification_label: string | null;
  reviewer: string | null;
  reviewed_at: string | null;
  updated_by: string | null;
  updated_at: string;
}

export interface RcaRecordDetail extends RcaRecord {
  source_file: string | null;
  source_row: number | null;
  batch: number | null;
  created_by: string | null;
  created_at: string;
  workflow: RcaWorkflow | null;
  comments: { id: number; author: string | null; text: string; evidence: string | null; created_at: string }[];
  history: { action: string; user: string | null; at: string; changes: Record<string, unknown> }[];
  other_records: { id: number; reporting_date: string; outage_minutes: number | null; rca_text: string }[];
  warning?: string | null;
}

export interface RcaPage {
  count: number;
  page: number;
  page_size: number;
  pages: number;
  results: RcaRecord[];
}

export interface RcaOption {
  value: string; label: string; unclassified?: boolean;
  /** In the approved bucketization (Final Bucket and Bucket - 2 filter options only). */
  approved?: boolean;
}

/** Approved-classification status of records: approved pair, approved Final Bucket only, not approved, blank. */
export type RcaClassificationCounts = Record<'approved' | 'final_only' | 'unapproved' | 'blank', number>;

export interface RcaOptions {
  dates: string[];
  /** Months with records and how many of their days have records. */
  months: { month: string; dates_with_records: number }[];
  projects: string[];
  circles: { project: string; circle: string; circle_raw: string }[];
  final_buckets: RcaOption[];
  bucket_2: RcaOption[];
  categories: RcaOption[];
  statuses: RcaOption[];
  total_records: number;
  /** The approved bucketization (from the server; the pages keep no list of their own). */
  classification?: { final_bucket: string; bucket_2: string[] }[];
}

export interface RcaRanked {
  key: string;
  label: string;
  unclassified: boolean;
  /** Final Bucket for which RCA is not applicable (Other Media): shown, but not as a technical cause. */
  rca_not_applicable: boolean;
  records: number;
  outage_minutes: number | null;
  /** Source spellings grouped under this label (case and spaces ignored). */
  variants: string[];
  /** In the approved bucketization (a Final Bucket; for Bucket - 2, the pair with its Final Bucket). */
  approved?: boolean;
  /** Bucket - 2 groups: the pair's filter (Final Bucket and Bucket - 2 together). */
  filter?: { final_bucket: string; bucket_2: string };
}

export interface RcaCircle {
  project: string;
  circle: string;
  records: number;
  outage_minutes: number | null;
  affected_sites: number;
  /** Sites in the dashboard's current Master data; null when unavailable. */
  portfolio_sites: number | null;
  records_per_100_sites: number | null;
  minutes_per_portfolio_site: number | null;
}

/** Circle-wise Root Cause Breakdown: RCA records per circle and Final Bucket reporting column (null = empty cell). */
export interface RcaBreakdown {
  /** Last reporting date included (the selected end date, or the latest record date). */
  through: string | null;
  columns: { label: string; pending: boolean; final_buckets: string[] }[];
  rows: { circle: string; has_records: boolean; counts: Record<string, number | null>; grand_total: number | null; not_mapped: number | null }[];
  totals: Record<string, number | null>;
  grand_total: number;
  percent_of_total: Record<string, number | null>;
  not_mapped: { records: number; values: { final_bucket: string; records: number }[] };
  records: number;
  empty: boolean;
  /**
   * Site Master and daily performance per circle (not RCA records): active sites, Unique Sites Down (outage > 0 at least
   * once) and NSLA sites (period uptime below 98.5%), for the reporting-date filter. null: no dashboard data.
   * usd_sites / nsla_sites are null when no day of the period has performance data.
   */
  sites?: {
    period: { label: string; first: string | null; last: string | null; days_reported: number };
    rows: Record<string, RcaSiteMetrics>;
    total: RcaSiteMetrics;
  } | null;
}

export interface RcaSiteMetrics { total_sites: number; usd_sites: number | null; nsla_sites: number | null; days_reported: number }

export interface RcaSummary {
  breakdown: RcaBreakdown;
  kpis: {
    records: number;
    affected_sites: number;
    outage_minutes: number | null;
    records_with_minutes: number;
    /** RCA-applicable records with a blank or "-" cause field ("RCA Required — Missing Information"). */
    incomplete_records: number;
    incomplete_by_field: { final_bucket: number; bucket_2: number; rca: number };
    missing_label: string;
    rca_applicable_records: number;
    completeness_pct: number | null;
    rca_not_applicable: { label: string; final_buckets: string[]; records: number; outage_minutes: number | null; blank_bucket_2: number };
  };
  dates: { date: string; records: number }[];
  final_buckets: RcaRanked[];
  /** Per Final Bucket and Bucket - 2 pair: a sub-bucket is never grouped by its name alone. */
  bucket_2: RcaRanked[];
  /** Records of the filter by approved-classification status. */
  classification?: RcaClassificationCounts;
  circles: RcaCircle[];
  projects: { project: string; records: number; outage_minutes: number | null; affected_sites: number; rca_not_applicable: number; incomplete_records: number }[];
  /** The reporting period matching the date filter, or the latest period when no dates are filtered. */
  cycle?: (RcaCycle & { matches_filter: boolean }) | null;
  population_source: string | null;
  categories: {
    mapped: { id: number; name: string; records: number; outage_minutes: number | null }[];
    unreviewed: { records: number; outage_minutes: number | null; descriptions: number };
    no_description: { records: number; outage_minutes: number | null };
  };
  top_records: RcaRecord[];
}

export interface RcaCauseItem {
  key: string;
  text: string;
  spellings: string[];
  records: number;
  outage_minutes: number | null;
  category: { id: number; name: string } | null;
  reviewed_by: string | null;
  reviewed_at: string | null;
}

export interface RcaCauses {
  categories: { id: number; name: string; description: string; descriptions: number }[];
  queue: RcaCauseItem[];
  mapped: RcaCauseItem[];
  stats: { descriptions: number; mapped_descriptions: number; records: number; mapped_records: number; no_description_records: number };
}

export interface RcaIssue { severity: 'error' | 'warning' | 'info'; code: string; row: number | null; site_id: string; message: string }

export interface RcaImportReport {
  filename: string;
  sheet: string;
  rows_read: number;
  valid_rows: number;
  rejected_rows: number;
  blank_rows: number;
  unknown_columns: string[];
  dates: Record<string, number>;
  projects: Record<string, number>;
  projects_raw: Record<string, number>;
  circles: Record<string, number>;
  circle_names: Record<string, number>;
  distinct_sites: number;
  outage_minutes: number;
  final_buckets: Record<string, number>;
  bucket_2: Record<string, number>;
  distinct_rca: number;
  label_variants: Record<string, string[][]>;
  severity_counts: { error: number; warning: number; info: number };
  issue_counts: Record<string, number>;
  issues: RcaIssue[];
  new_rows: number;
  unchanged_rows: number;
  conflict_rows: number;
  conflicts: { row: number; site_id: string; record_id: number; differences: Record<string, { database: unknown; file: unknown }> }[];
  already_imported: { batch: number; committed_at: string } | null;
  /** Withdrawn records listed again (restored with this file's values). */
  restored_rows?: number;
  /** The period already had accepted uploads and this workbook changes or drops some of their records. */
  is_correction?: boolean;
  /** Final Bucket labels (as written) found in no stored record, with their row counts. */
  new_final_buckets?: Record<string, number>;
  /** The data sheet found by its header, its header row, and the sites with more than one row on a date. */
  header_row?: number;
  sites_with_several_rows?: number;
  /** Per reporting date in the workbook: rows against stored records; earlier dates are history of a cumulative workbook. */
  by_date?: RcaDateBreakdown[];
  earlier_date_rows?: number;
  /** Expected projects / circles of the reporting date against those the workbook has rows for on it. */
  coverage?: { source: 'period' | 'previous period' | null; expected: [string, string][]; present: [string, string][]; missing: [string, string][] } | null;
  earlier_uploads_for_period?: number;
  /** Stored records of the submission's units that a corrected file no longer lists (cycle submissions). */
  missing_rows?: number;
  missing?: RcaMissingRecord[];
  rca_not_applicable_rows?: number;
  missing_rca_rows?: number;
}

export interface RcaMissingRecord {
  record_id: number; site_id: string; project: string; circle: string; outage_minutes: number | null; final_bucket: string; source_file: string;
}

export type RcaProjectScope = '4G Saturation' | 'LWE' | 'both';

/** One uploaded RCA workbook: its report details, validation and import result. */
export interface RcaImportBatch {
  id: number;
  status: 'previewed' | 'committed' | 'failed' | 'rejected' | 'discarded';
  /** circle, consolidated, or legacy (uploaded before upload types existed; never a circle submission). */
  upload_type?: RcaUploadType | 'legacy';
  upload_type_label?: string;
  /** The circle of a circle upload. */
  circle?: string | null;
  /** Shown to users: e.g. "Validated — awaiting confirmation", "Imported with rejected rows". */
  status_label: string;
  file: string;
  checksum: string;
  sheet: string;
  uploaded_at: string;
  committed_at: string | null;
  imported_by: string | null;
  report_name: string | null;
  project_scope: RcaProjectScope | null;
  remarks: string | null;
  period_start: string | null;
  period_end: string | null;
  /** The reporting period the upload was accepted into. */
  cycle: number | null;
  /** Projects and circles represented in the valid rows. */
  units: [string, string][];
  /** total, valid, rejected; after import also inserted, updated, skipped, unchanged, withdrawn... */
  counts: Record<string, number | boolean>;
  correction: boolean;
  conflict_action: string | null;
  missing_action: string | null;
  error: string | null;
  file_kept: boolean;
  report?: RcaImportReport;
}

export interface RcaDateBreakdown {
  date: string; rows: number; new: number; unchanged: number; changed: number; missing: number; earlier_date: boolean;
  /** e.g. "reporting date: new", "earlier date: repeated", "earlier date: corrected". */
  kind: string;
}

export interface RcaUploadsSummary {
  total: number; imported: number; with_rejected_rows: number; awaiting_confirmation: number; validation_failed: number;
  corrections: number; last_upload_at: string | null;
}

export type RcaCycleCode = 'unconfigured' | 'awaiting' | 'review' | 'partial' | 'ready' | 'final' | 'revised';
export type RcaUnitCode = 'received' | 'pending';

/** An expected project / circle of a period and the evidence: accepted records and the files they came from. */
export interface RcaUnitState {
  project: string;
  circle: string;
  status: RcaUnitCode;
  status_label: string;
  records: number;
  outage_minutes: number | null;
  source_files: string[];
  /** RCA data availability (records of the unit in the period, from any upload): "Data available" / "No data". */
  data_label?: string;
  /** Circle submission: a committed circle upload of the unit and date (never a consolidated or legacy upload). */
  submission_status?: 'received' | 'not_received';
  submission_label?: string;
  submission?: { batch: number; file: string; reporting_date: string; uploaded_at: string; committed_at: string | null; uploaded_by: string | null } | null;
  submissions?: number;
}

export interface RcaCycleStatus {
  code: RcaCycleCode;
  label: string;
  required: number;
  received: number;
  complete: boolean;
  outstanding: { project: string; circle: string; status: RcaUnitCode; status_label: string }[];
  final_version: number | null;
  upload_awaiting_confirmation: boolean;
  can_finalize: boolean;
  records_checksum: string;
}

export interface RcaReportVersion {
  id: number;
  version: number;
  filename: string;
  generated_at: string;
  generated_by: string | null;
  automatic: boolean;
  record_count: number;
  superseded_at: string | null;
  current: boolean;
  available: boolean;
}

/** A reporting period: one date or a date range. */
export interface RcaCycle {
  id: number;
  name: string | null;
  period_start: string;
  period_end: string;
  period_label: string;
  notes: string | null;
  created_by: string | null;
  created_at: string;
  status: RcaCycleStatus;
  records: number;
  uploads_summary: RcaUploadsSummary;
}

export interface RcaCycleDetail extends RcaCycle {
  units: RcaUnitState[];
  /** Data present for projects / circles outside the expected scope (never counted as coverage). */
  unexpected: { project: string; circle: string; records: number }[];
  uploads: RcaImportBatch[];
  reports: RcaReportVersion[];
  available_units: [string, string][];
  locked: boolean;
}

export interface RcaCycleList {
  cycles: RcaCycle[];
  default_units: [string, string][];
  available_units: [string, string][];
}

/** Upload Circle RCA (one project, circle and date) or Upload Consolidated RCA (several circles and dates). */
export type RcaUploadType = 'circle' | 'consolidated';

export interface RcaUploadDetails {
  upload_type: RcaUploadType;
  /** Required for a consolidated upload; generated from project, circle and date for a circle upload. */
  report_name: string;
  /** The reporting date. Optional for a consolidated upload: the latest date in the workbook. */
  period_start: string;
  /** Consolidated uploads. */
  project_scope: RcaProjectScope;
  /** Circle uploads. */
  project: string;
  circle: string;
  remarks: string;
}

/** What the upload pages may offer the signed-in user (the server checks every upload again). */
export interface RcaUploadRights {
  circle: boolean;
  consolidated: boolean;
  /** Project/circle pairs a CI user may upload circle files for; null = every pair (Admin, NOC Lead). */
  access: { project: string; circle: string }[] | null;
}

export interface RcaWorkflowInput {
  status?: RcaStatus | '';
  review_status?: RcaReview | '';
  corrective_action?: string;
  owner?: string;
  target_date?: string;
  completed_date?: string;
  verification?: RcaVerification | '';
}

export interface RcaRecordInput {
  reporting_date: string;
  project: string;
  circle: string;
  site_id: string;
  site_name?: string;
  oa?: string;
  ba?: string;
  om_start_raw?: string;
  outage_minutes?: number | string | null;
  final_bucket?: string;
  bucket_2?: string;
  rca_text: string;
}
