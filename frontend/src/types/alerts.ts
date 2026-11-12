/** Administration › Alert: email account, automations and email history (all from /api/alerts/). */
export interface AlertAccount {
  id: number; name: string; host: string; port: number; security: 'starttls' | 'ssl' | 'none'; auth: 'password' | 'none'; username: string;
  /** A password is stored (it is never returned). */
  password_set: boolean;
  from_email: string; from_name: string; reply_to: string; timeout: number; is_active: boolean; tested_ok_at: string | null; last_test: string; updated_at: string;
}
export interface AlertWorker { last_seen: string | null; running: boolean }

export type AlertKind = 'csv_reminder' | 'rca_reminder' | 'uptime_report' | 'upload_failure' | 'custom';
export type AlertFrequency = 'once' | 'daily' | 'weekly' | 'monthly' | 'event';
export interface AlertAttachment { report: string; format: string }

export interface AlertAutomationInput {
  name: string; kind: AlertKind; frequency: AlertFrequency; run_time: string; timezone: string; weekday: number; month_day: number;
  start_date: string | null; end_date: string | null; project: string; circles: string[]; report_day: 'today' | 'yesterday' | 'latest';
  to_users: number[]; to_emails: string[]; cc: string[]; bcc: string[]; include_responsible: boolean; attachments: AlertAttachment[];
  extra_file: number | null; distribution: 'same' | 'per_recipient'; template: 'reminder' | 'report'; subject: string; message: string;
  /** Site population of the reports and figures of the email (On-Air or O&M Start); the API defaults to On-Air. */
  population: AlertPopulation;
}
export type AlertPopulation = 'on_air' | 'om_start';
export interface AlertAutomation extends AlertAutomationInput {
  id: number; kind_label: string; enabled: boolean; next_run_at: string | null; last_run_at: string | null; extra_file_name: string | null; updated_at: string;
}

export interface AlertOptions {
  kinds: { value: AlertKind; label: string; description: string; template: string; frequency: AlertFrequency; report_day: string }[];
  reports: { value: string; label: string; formats: string[]; scoped: boolean; description: string }[];
  templates: { value: 'reminder' | 'report'; label: string; subject: string; message: string }[];
  placeholders: string[];
  users: { id: number; username: string; name: string; email: string; role: string }[];
  timezone: string; max_file_bytes: number; file_types: string[]; account_active: boolean; worker: AlertWorker;
}
export interface AlertPreview { subject: string; text: string; html: string; attachments: { name: string; format: string; period: string }[]; next_run_at: string | null }

export interface AlertMessage {
  id: number; created_at: string; sent_at: string | null; automation: string; automation_id: number | null; trigger: string; execution: number;
  to: string[]; cc: string[]; bcc: string[]; subject: string; attachments: { name: string; format?: string; period?: string; size?: number }[];
  status: 'queued' | 'processing' | 'accepted' | 'failed'; status_label: string; attempts: number; error: string; smtp_response: string; resend_of: number | null;
  html?: string; text?: string; execution_status?: string; execution_detail?: string;
  attempt_log?: { at: string; ok: boolean; detail: string; by: string }[]; resends?: number[];
}
export interface AlertHistory {
  total: number; page: number; pages: number; messages: AlertMessage[]; queued_runs: number; worker: AlertWorker;
  runs_without_email: { id: number; automation: string; status: string; detail: string; created_at: string }[];
}
