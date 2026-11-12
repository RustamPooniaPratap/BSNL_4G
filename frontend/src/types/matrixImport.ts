import type { FinalizationStatus, MonthFinalization } from './reporting';

/** Consolidation Matrix import into the new data layer (/api/sitedata/matrix/). */

export interface MatrixRejectedRow {
  row: number | null;
  site_id: string;
  entity: string;
  circle: string;
  code: string;
  reason: string;
}

export interface MatrixPreviewCounts {
  total_rows: number;
  new_sites: number;
  updated_sites: number;
  unchanged_sites: number;
  rejected_rows: number;
  duplicate_site_ids: number;
  conflicting_mappings: number;
  missing_mandatory: number;
  invalid_circle_or_technology: number;
  effective_date_issues: number;
  effective_date_changes: number;
  blank_values_kept: number;
  sites_not_in_file: number;
}

export interface MatrixReport {
  error?: string;
  sheet?: string;
  columns_found?: string[];
  /** Known columns this file does not have: their stored values stay unchanged. */
  columns_not_in_file?: string[];
  preview?: MatrixPreviewCounts;
  rejected_by_reason?: Record<string, { rows: number; reason: string }>;
  rejected?: MatrixRejectedRow[];
  duplicates?: { site_id: string; rows: number[]; identical: boolean }[];
  identity_conflicts?: MatrixRejectedRow[];
  identifier_conflicts?: { kind: string; value: string; sites: string[] }[];
  effective_date_review?: Record<string, number>;
  effective_date_review_rows?: { row: number | null; site_id: string; code: string; value: string; message: string }[];
  effective_date_changes?: { site_id: string; field: string; from: string | null; to: string | null; row: number }[];
  blank_values_kept?: Record<string, number>;
  changed_fields?: Record<string, number>;
  by_technology_circle?: Record<string, number>;
  warnings?: string[];
  committed?: { inserted: number; updated: number; unchanged: number; no_longer_in_matrix: number };
}

export interface MatrixImportBatch {
  id: number;
  kind: 'consolidation_matrix';
  file: string;
  status: 'previewed' | 'committed' | 'failed' | 'discarded';
  validation_status: 'pending' | 'passed' | 'passed_with_warnings' | 'failed';
  uploaded_at: string | null;
  committed_at: string | null;
  uploaded_by: string | null;
  error: string | null;
  can_commit: boolean;
  report: MatrixReport;
}

/** Up-Time Report import into the new data layer (/api/sitedata/uptime/). Counts are site-days. */
export interface UptimeImportBatch {
  id: number;
  kind: 'uptime_master';
  technology: string | null;
  file: string;
  status: 'previewed' | 'committed' | 'failed' | 'discarded';
  validation_status: 'pending' | 'passed' | 'passed_with_warnings' | 'failed';
  uploaded_at: string | null;
  committed_at: string | null;
  uploaded_by: string | null;
  error: string | null;
  can_commit: boolean;
  counts: { received: number; accepted: number; rejected: number; duplicate: number; unmatched: number; conflict: number; superseded: number };
  report: {
    error?: string;
    format?: string;
    sheet?: string;
    months_in_scope?: string[];
    months_in_file?: string[];
    rows_read?: number;
    rejected_rows_count?: number;
    not_reported_site_days?: number;
    sites_not_in_site_master_count?: number;
    sites_not_in_site_master?: string[];
    warnings?: string[];
    /** A committed import of this exact file into the new data layer (this destination only). */
    already_imported?: { batch: number; committed_at: string } | null;
  };
}

/** LWE Band ID mapping import (/api/sitedata/lwe-mapping/): raw LWE band IDs (2100 / 700 MHz, BTS IP ID) -> master sites. */
export interface LweMappingReport {
  error?: string;
  sheet?: string;
  rows?: number;
  rejected_by_reason?: Record<string, number>;
  changes?: { added: number; changed: number; unchanged: number; kept_new_row_rejected: number; not_in_this_workbook_kept: number };
  kept_new_row_rejected?: string[];
  not_in_this_workbook_kept?: string[];
  lwe_sites_mapped_after_import?: number;
  lwe_sites_without_mapping?: number;
  quality?: Record<string, unknown>;
  warnings?: string[];
  identifiers_created?: number;
}

export interface LweMappingBatch {
  id: number;
  kind: 'lwe_band_mapping';
  technology: string | null;
  file: string;
  checksum?: string;
  status: 'previewed' | 'committed' | 'failed' | 'discarded';
  validation_status: 'pending' | 'passed' | 'passed_with_warnings' | 'failed';
  uploaded_at: string | null;
  committed_at: string | null;
  uploaded_by: string | null;
  error: string | null;
  can_commit: boolean;
  counts: { received: number; accepted: number; rejected: number; duplicate: number; unmatched: number; conflict: number; superseded: number };
  report: LweMappingReport;
}

/** Monthly results of the data layer (/api/sitedata/months/); month is 'YYYY-MM-01'. */
export interface MonthlyResult {
  month: string;
  records: number;
  finalized: boolean;
  calculated_at: string | null;
  /** Finalization state (absent in older responses): open, complete, incomplete_missing_data or reopened. */
  finalization_status?: FinalizationStatus;
  finalization_label?: string;
  /** The latest finalization record (also when reopened), or null when never finalized. */
  finalization?: MonthFinalization | null;
}
export interface MonthlyResultsResponse { months: MonthlyResult[] }

/** One upload of the new data layer in the import history (any workbook type). */
export interface NewLayerUpload {
  id: number;
  kind: 'uptime_master' | 'consolidation_matrix' | 'lwe_band_mapping';
  technology: string | null;
  file: string;
  status: 'previewed' | 'committed' | 'failed' | 'discarded';
  uploaded_at: string | null;
  committed_at: string | null;
  uploaded_by: string | null;
  counts: { received: number; accepted: number; rejected: number; duplicate: number; unmatched: number; conflict: number; superseded: number };
}

/** An Up-Time Report site that is not in the Consolidation Matrix site master (data-quality report). */
export interface UnmatchedSite {
  site_id: string;
  project: string | null;
  circle: string | null;
  uploads: number[];
  first_date: string | null;
  last_date: string | null;
  /** Site-days waiting for the site's identity; null until the details of an older upload are refreshed. */
  pending_site_days: number | null;
  processed_site_days: number;
  reason: string;
  /** pending: no master site; ready: resolved (matrix or alternate identifier), not processed yet; processed. */
  status: 'pending' | 'ready' | 'processed';
  resolved_to: string | null;
  resolved_by: 'master' | 'alternate_identifier' | null;
}

export interface UnmatchedReport {
  sites: UnmatchedSite[];
  uploads_without_detail: number[];
  pending_sites: number;
  ready_sites: number;
}
