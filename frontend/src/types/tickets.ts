export interface TicketCounts {
  total_rows: number;
  blank_rows: number;
  sample_rows_skipped: number;
  invalid_rows: number;
  valid_rows: number;
  new_tickets: number;
  existing_tickets_updated: number;
  tickets_closed: number;
  tickets_reopened: number;
  closed_rows_skipped: number;
  notifications_attempted: number;
  notifications_failed: number;
}

export interface TicketImportRow {
  excel_row: number;
  outcome: string;
  preview_outcome: string;
  values?: Record<string, string | number | null>;
  source_values: Record<string, string>;
  errors: { field: string; message: string }[];
  portal_ticket_id: string | null;
  notification_id: number | null;
}

export interface TicketImportBatch {
  id: number;
  filename: string;
  checksum_sha256: string;
  status: 'previewed' | 'committed' | 'failed' | 'discarded';
  uploaded_at: string;
  committed_at: string | null;
  uploaded_by: string;
  counts: TicketCounts;
  duplicate_of: number | null;
  error: string;
  rows: TicketImportRow[];
}

export interface TicketOptions {
  circles: string[];
  vendors: string[];
  statuses: string[];
  can_upload: boolean;
  max_upload_bytes: number;
}

export interface TicketDashboardResponse {
  kpis: {
    total: number;
    open: number;
    closed: number;
    created_today: number;
    notifications_accepted: number;
    notifications_failed: number;
  };
  status: { status: string; count: number }[];
  circles: { circle: string; count: number }[];
  vendors: { vendor_name: string; count: number }[];
  buckets: { outage_bucket: string; count: number }[];
  monthly: { month: string; count: number }[];
}

export interface TicketListItem {
  id: number;
  portal_ticket_id: string;
  outage_date: string;
  circle: string;
  site_id: string;
  site_name: string;
  vendor_name: string;
  outage_minutes: string | null;
  status: 'Open' | 'Closed';
  email_id: string;
  created_at: string;
  updated_at: string;
  /** Whether the signed-in user may close this ticket (the API enforces the same rule on closing). */
  can_close?: boolean;
}

/** Ticket table status filter. The API lists Open tickets when no status is sent. */
export type TicketStatusFilter = 'Open' | 'Closed' | 'All';

export interface TicketPage {
  total: number;
  page: number;
  page_size: number;
  pages: number;
  status?: TicketStatusFilter;
  tickets: TicketListItem[];
}

export interface TicketEvent {
  id: number;
  action: string;
  source: string;
  actor: string;
  status_before: string;
  status_after: string;
  remarks: string;
  changes: Record<string, unknown>;
  batch_id: number | null;
  created_at: string;
}

export interface TicketNotificationAttempt {
  number: number;
  attempted_by: string;
  attempted_at: string;
  accepted_at: string | null;
  accepted: boolean;
  detail: string;
}

export interface TicketNotification {
  id: number;
  kind: string;
  recipient: string;
  status: string;
  attempts: number;
  sent_at: string | null;
  created_at: string;
  error: string;
  smtp_response: string;
  attempt_log: TicketNotificationAttempt[];
}

export interface TicketDetail {
  id: number;
  portal_ticket_id: string;
  source_serial: string;
  outage_date: string;
  project: string;
  circle: string;
  site_id: string;
  site_name: string;
  oa: string;
  ba: string;
  actual_down_time: string;
  reporting_time_to_partner: string | null;
  restoration_time: string | null;
  outage_minutes: string | null;
  mttr_hours: string | null;
  vendor_name: string;
  outage_bucket: string;
  detail_rca: string;
  status: 'Open' | 'Closed';
  email_id: string;
  created_by: string;
  created_at: string;
  updated_at: string;
  last_uploaded_at: string;
  created_batch: number | null;
  last_batch: number | null;
  closure_remarks: string;
  closed_by: string;
  closed_at: string | null;
  closure_source: string;
  source_values: Record<string, string>;
  events: TicketEvent[];
  notifications: TicketNotification[];
}

export interface TicketDetailResponse {
  ticket: TicketDetail;
  permissions: { close: boolean; reopen: boolean; retry: boolean };
}
