/** BSNL Module (Auto Email Reports, BSNL Letters): response shapes of /api/bsnl/ (apps/bsnl/views.py). */

export type ReportType = 'D-1' | 'Weekly';
export type RecipientReportType = ReportType | 'All India' | 'BSNL letter';
export type LetterStatus = 'Draft' | 'Approved' | 'Sent' | 'Acknowledged' | 'Exclusion accepted' | 'Exclusion rejected';
export type LetterPeriodKind = 'd1' | 'week' | 'period';
export type Bucket = 'Own' | 'Customer' | 'Third party' | 'Pending' | 'Unclassified';

export interface DataStatus { status: 'Complete' | 'Provisional' | null; missing: { date: string; units: string[] }[] }
export interface Period { start: string; end: string; label: string }
export interface Recipients { to: string[]; cc: string[] }

export interface ReportOptions {
  projects: string[];
  schedule: { daily: boolean; weekly: boolean; daily_time: string; weekly_time: string };
  sending_enabled: boolean;
  recipients_loaded: number;
  permissions: { send: boolean; manage: boolean; all_india: boolean };
  target_pct: number;
  population: string;
}

export interface Kpis {
  sites: number;
  sites_reported: number;
  uptime_pct: number | null;
  target_pct: number;
  status: string;
  not_meeting_sla: number | null;
  usd_sites: number | null;
  outage_minutes: number;
  customer_minutes: number;
  outage_hours?: number;
  customer_hours?: number;
}

export interface CircleRow extends Kpis, Recipients {
  circle: string;
  name: string;
  complete: boolean;
  can_send: boolean;
  data_status: DataStatus;
}

export interface ReportOverview {
  period: Period;
  latest_date: string;
  circles: CircleRow[];
  all_india: Recipients;
  data_status: DataStatus;
}

export interface ReportPreview extends Recipients {
  title: string;
  subject: string;
  html: string;
  period: Period;
  kpis: Kpis;
  report_type: ReportType;
  circle: string;
  project: string;
  attachment: string;
  sheet_count: number;
  sheets: string[];
  data_status: DataStatus;
}

export interface ReportRun extends Recipients {
  id: number;
  report_type: ReportType;
  circle: string;
  circle_name: string;
  project: string;
  period_start: string;
  period_end: string;
  trigger: 'schedule' | 'manual';
  status: 'processing' | 'sent' | 'failed' | 'skipped';
  subject: string;
  attachment: string;
  error: string;
  smtp_response: string;
  created_by: string;
  created_at: string;
  finished_at: string | null;
}

export interface Recipient {
  id: number;
  circle: string;
  circle_name: string;
  report_type: RecipientReportType;
  name: string;
  designation: string;
  email: string;
  kind: 'To' | 'Cc';
  is_active: boolean;
  updated_at: string;
}

export interface LetterOptions {
  projects: string[];
  latest_rca_date: string | null;
  permissions: { edit: boolean; approve: boolean; send: boolean; manage: boolean };
  statuses: LetterStatus[];
  max_period_days: number;
}

export interface LetterSummary {
  id: number;
  reference: string;
  circle: string;
  circle_name: string;
  project: string;
  period_kind: LetterPeriodKind;
  period_start: string;
  period_end: string;
  period_label: string;
  outage_count: number;
  site_count: number;
  total_minutes: number;
  total_hours?: number;
  status: LetterStatus;
  prepared_by: string;
  created_at: string;
  updated_at: string;
  approved_by: string;
  approved_at: string | null;
  sent_at: string | null;
  send_status: '' | 'sent' | 'failed';
  send_error: string;
  edited: boolean;
  recipients: Partial<Recipients>;
}

export interface AnnexureRow {
  site_id: string;
  site_name: string;
  circle: string;
  project: string;
  cluster: string;
  ne: string;
  date: string;
  start: string;
  end: string;
  outage_minutes: number;
  hours?: number;
  rca: string;
  cause: string;
  final_bucket: string;
  bucket: Bucket;
  ticket: string;
}

export interface LetterDetail extends LetterSummary {
  html: string;
  generated_html: string;
  annexure: AnnexureRow[];
  causes: { cause: string; outages: number; outage_minutes: number; hours?: number }[];
  letter_date: string;
  subject: string;
  events: { action: string; status_before: string; status_after: string; note: string; actor: string; created_at: string }[];
  current_recipients: Recipients;
  permissions: { edit: boolean; approve: boolean; send: boolean };
  transitions: LetterStatus[];
  sending_enabled: boolean;
}

export interface LetterCircleRow extends Recipients {
  circle: string;
  name: string;
  outages: number;
  sites: number;
  outage_minutes: number;
  hours?: number;
  complete: boolean;
  letter: { id: number; reference: string; status: LetterStatus } | null;
}

export interface LetterOverview {
  period: { kind: LetterPeriodKind; start: string; end: string; label: string };
  circles: LetterCircleRow[];
  register: LetterSummary[];
}

export interface CircleProfile {
  circle: string;
  name: string;
  bsnl_designation: string;
  bsnl_address: string;
  sender_name: string;
  sender_designation: string;
  company: string;
}

export interface BucketMapping {
  mapping: { final_bucket: string; bucket: Bucket }[];
  buckets: Bucket[];
  can_manage: boolean;
  rule: string;
}
