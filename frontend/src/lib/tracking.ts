/**
 * CSV arrival tracking: per project and circle, whether the stored daily data for a reporting date is complete, and
 * separately whether a raw CSV upload was recorded for it.
 *
 * Both facts come from the server (GET /api/arrival-tracker/, computed from PostgreSQL on every request). Contacts,
 * follow-ups, deadlines and manual arrival notes are still held in this browser only and never change the data status.
 */
import type { TrackerItem, UploadState } from '../types/rawUpload';

/**
 * Status of a project/circle on the reporting date:
 * - complete / partial: stored daily data covers all / some of the master's On-Air sites (whatever imported it).
 * - file_received: no usable data, but a raw CSV upload is recorded for the date (validated, blocked, failed or imported).
 * - late: no usable data and no upload, and a configured deadline has passed.
 * - no_data: no usable data and no upload, and no deadline has passed (or none is configured).
 */
export type ArrivalStatus = 'complete' | 'partial' | 'file_received' | 'no_data' | 'late';

export const STATUS_LABELS: Record<ArrivalStatus, string> = {
  complete: 'Data complete',
  partial: 'Partial data',
  file_received: 'File received · no usable data',
  no_data: 'No data available',
  late: 'No data · past deadline',
};

export const UPLOAD_LABELS: Record<UploadState, string> = {
  imported: 'CSV imported',
  awaiting_confirmation: 'Validated · awaiting confirmation',
  nothing_to_import: 'Validated · nothing new to import',
  blocked: 'CSV blocked',
  failed: 'CSV could not be read',
  discarded: 'CSV discarded',
  none: 'No CSV upload recorded',
};

/** Upload states that show a file was received (a discarded upload was withdrawn by the user). */
const RECEIVED_UPLOADS = new Set<UploadState>(['imported', 'awaiting_confirmation', 'nothing_to_import', 'blocked', 'failed']);

/** One circle that must send one report type's CSV (taken from the master data). */
export interface Requirement {
  circle: string;
  reportType: string;
}

export interface ArrivalRecord {
  id: string;
  circle: string;
  reportType: string;
  /** The date the CSV covers (YYYY-MM-DD). */
  reportingDate: string;
  /** When the CSV actually arrived, as entered by the user. */
  arrivalDate: string;
  arrivalTime: string;
  fileName: string;
  receivedBy: string;
  notes: string;
  /** True when the user chose "now" as the arrival time; shown as the time of entry. */
  timeIsEntryTime: boolean;
  /** When the record was entered in this browser (ISO). */
  enteredAt: string;
}

export interface Contact {
  name: string;
  designation: string;
  phone: string;
  email: string;
  backup: string;
  notes: string;
}

export type FollowUpMethod = 'call' | 'email' | 'message' | 'other';
export const FOLLOW_UP_METHODS: Record<FollowUpMethod, string> = { call: 'Call', email: 'Email', message: 'Message', other: 'Other' };

export interface FollowUp {
  id: string;
  circle: string;
  reportType: string;
  reportingDate: string;
  /** When the follow-up happened (YYYY-MM-DDTHH:MM, local). */
  at: string;
  contactPerson: string;
  method: FollowUpMethod;
  outcome: string;
  expectedAt: string;
  nextFollowUp: string;
  enteredAt: string;
}

/** Deadline per report type: the CSV for date D is due on D + dayOffset at time (local). */
export interface Deadline {
  dayOffset: number;
  time: string;
}
export type DeadlineConfig = Record<string, Deadline | null>;

export const EMPTY_CONTACT: Contact = { name: '', designation: '', phone: '', email: '', backup: '', notes: '' };
export const requirementKey = (r: Requirement) => `${r.reportType}|${r.circle}`;
export const submissionKey = (r: Requirement, reportingDate: string) => `${r.reportType}|${r.circle}|${reportingDate}`;
export const shortType = (reportType: string) => (reportType === '4G Saturation' ? '4G' : reportType);

/** The requirements: each project and circle of the site master that the server returned (within the user's circles). */
export function requirementsFrom(items: { project: string; circle: string }[]): Requirement[] {
  return items
    .map((i) => ({ circle: i.circle, reportType: i.project }))
    .sort((a, b) => a.reportType.localeCompare(b.reportType) || a.circle.localeCompare(b.circle));
}

const pad = (n: number) => String(n).padStart(2, '0');
export const localDate = (d: Date) => `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;
export const localTime = (d: Date) => `${pad(d.getHours())}:${pad(d.getMinutes())}`;
const at = (date: string, time: string) => new Date(`${date}T${time}:00`);

/** The configured deadline for a requirement and date, or null when none is configured. */
export function deadlineFor(reportType: string, reportingDate: string, config: DeadlineConfig): Date | null {
  const rule = config[reportType];
  if (!rule || !reportingDate) return null;
  const due = new Date(`${reportingDate}T00:00:00`);
  due.setDate(due.getDate() + rule.dayOffset);
  return at(localDate(due), rule.time);
}

/** Problems shown with a manual arrival note (incomplete or inconsistent details). */
export function arrivalProblems(record: ArrivalRecord, now: Date): string[] {
  const problems: string[] = [];
  if (!record.arrivalDate || !record.arrivalTime) problems.push('Arrival date or time is missing.');
  if (!record.fileName.trim()) problems.push('File name is not recorded.');
  else if (!record.fileName.trim().toLowerCase().endsWith('.csv')) problems.push('The file name does not end in .csv.');
  if (record.arrivalDate && record.arrivalTime) {
    const arrived = at(record.arrivalDate, record.arrivalTime);
    if (arrived > now) problems.push('The arrival time is in the future.');
    if (record.arrivalDate < record.reportingDate) problems.push('It arrived before the reporting date it covers.');
  }
  return problems;
}

export interface Submission extends Requirement {
  key: string;
  reportingDate: string;
  status: ArrivalStatus;
  /** What the server found for this project, circle and date. */
  server: TrackerItem;
  deadline: Date | null;
  /** A manual arrival note entered in this browser (does not change the status). */
  arrival: ArrivalRecord | null;
  /** The manual note says the file arrived after the configured deadline. */
  arrivedLate: boolean;
  problems: string[];
  contact: Contact | null;
  contactComplete: boolean;
  followUps: FollowUp[];
}

/** A contact is complete with a name and at least one way to reach them. */
export const isContactComplete = (c: Contact | null | undefined) => Boolean(c && c.name.trim() && (c.phone.trim() || c.email.trim()));

/** The status from the server's data and upload facts; a deadline only matters when there is neither. */
export function trackStatus(item: TrackerItem, deadline: Date | null, now: Date): ArrivalStatus {
  if (item.data_state === 'complete') return 'complete';
  if (item.data_state === 'partial') return 'partial';
  if (RECEIVED_UPLOADS.has(item.upload_state)) return 'file_received';
  return deadline && now > deadline ? 'late' : 'no_data';
}

/** One row per server item. Contacts, follow-ups and manual notes come from the browser state; they never change the status. */
export function buildSubmissions(items: TrackerItem[], reportingDate: string, state: {
  arrivals: Record<string, ArrivalRecord>; contacts: Record<string, Contact>; followUps: FollowUp[]; deadlines: DeadlineConfig;
}, now: Date): Submission[] {
  return items.map((server) => {
    const requirement = { circle: server.circle, reportType: server.project };
    const key = submissionKey(requirement, reportingDate);
    const arrival = state.arrivals[key] ?? null;
    const deadline = deadlineFor(requirement.reportType, reportingDate, state.deadlines);
    const problems = arrival ? arrivalProblems(arrival, now) : [];
    const arrivedLate = Boolean(arrival && deadline && arrival.arrivalDate && arrival.arrivalTime && at(arrival.arrivalDate, arrival.arrivalTime) > deadline);
    const contact = state.contacts[requirementKey(requirement)] ?? null;
    const followUps = state.followUps
      .filter((f) => f.circle === requirement.circle && f.reportType === requirement.reportType && f.reportingDate === reportingDate)
      .sort((a, b) => b.at.localeCompare(a.at));
    return {
      ...requirement, key, reportingDate, status: trackStatus(server, deadline, now), server, deadline, arrival, arrivedLate, problems,
      contact, contactComplete: isContactComplete(contact), followUps,
    };
  });
}

export type CardFilter = 'all' | 'complete' | 'partial' | 'no_data' | 'csv_recorded' | 'late' | 'missing_contact';

export interface TrackingFilters {
  circle: string;
  reportType: string;
  status: ArrivalStatus | '';
  contact: 'all' | 'complete' | 'missing';
  openOnly: boolean;
  search: string;
  card: CardFilter;
}
export const DEFAULT_FILTERS: TrackingFilters = { circle: '', reportType: '', status: '', contact: 'all', openOnly: false, search: '', card: 'all' };

/** No usable stored data for the date, whatever the upload state. */
export const lacksData = (s: Submission) => s.status === 'no_data' || s.status === 'late' || s.status === 'file_received';
/** A raw CSV upload is recorded for the date (any state, including blocked or discarded). */
export const hasUpload = (s: Submission) => s.server.upload_state !== 'none';

const matchesCard = (s: Submission, card: CardFilter) => {
  switch (card) {
    case 'complete': return s.status === 'complete';
    case 'partial': return s.status === 'partial';
    case 'no_data': return lacksData(s);
    case 'csv_recorded': return hasUpload(s);
    case 'late': return s.status === 'late';
    case 'missing_contact': return !s.contactComplete;
    default: return true;
  }
};

/** The table filters except the KPI card (cards are counted over these). */
export function applyFilters(rows: Submission[], f: TrackingFilters): Submission[] {
  const needle = f.search.trim().toLowerCase();
  return rows.filter((s) => {
    if (f.circle && s.circle !== f.circle) return false;
    if (f.reportType && s.reportType !== f.reportType) return false;
    if (f.status && s.status !== f.status) return false;
    if (f.contact === 'complete' && !s.contactComplete) return false;
    if (f.contact === 'missing' && s.contactComplete) return false;
    if (f.openOnly && s.status === 'complete') return false;
    if (needle) {
      const hay = [s.circle, s.reportType, shortType(s.reportType), s.contact?.name, s.contact?.phone, s.contact?.email, s.contact?.backup, s.arrival?.fileName,
        ...s.server.uploads.flatMap((u) => [u.file, u.uploaded_by])]
        .filter(Boolean).join(' ').toLowerCase();
      if (!hay.includes(needle)) return false;
    }
    return true;
  });
}

export const applyCard = (rows: Submission[], card: CardFilter) => rows.filter((s) => matchesCard(s, card));

export function kpis(rows: Submission[]) {
  return {
    total: rows.length,
    complete: rows.filter((s) => s.status === 'complete').length,
    partial: rows.filter((s) => s.status === 'partial').length,
    noData: rows.filter(lacksData).length,
    csvRecorded: rows.filter(hasUpload).length,
    late: rows.filter((s) => s.status === 'late').length,
    missingContact: rows.filter((s) => !s.contactComplete).length,
  };
}

// --- Form validation ----------------------------------------------------------------------

export interface ArrivalDraft {
  circle: string;
  reportType: string;
  reportingDate: string;
  arrivalDate: string;
  arrivalTime: string;
  fileName: string;
  receivedBy: string;
  notes: string;
  timeIsEntryTime: boolean;
}

/** Blocking errors for the Record Arrival form; ``existing`` is the record being edited, if any. */
export function arrivalErrors(draft: ArrivalDraft, arrivals: Record<string, ArrivalRecord>, now: Date, editingId?: string) {
  const e: Partial<Record<keyof ArrivalDraft, string>> = {};
  if (!draft.circle) e.circle = 'Choose the circle.';
  if (!draft.reportType) e.reportType = 'Choose the report type.';
  if (!draft.reportingDate) e.reportingDate = 'Choose the reporting date.';
  if (!draft.arrivalDate) e.arrivalDate = 'Enter the date the CSV arrived.';
  if (!draft.arrivalTime) e.arrivalTime = 'Enter the time the CSV arrived.';
  if (draft.arrivalDate && draft.arrivalTime && at(draft.arrivalDate, draft.arrivalTime) > now) {
    e.arrivalTime = 'The arrival time cannot be in the future.';
  }
  if (draft.fileName.trim() && !/\.csv$/i.test(draft.fileName.trim())) e.fileName = 'The file name should end in .csv.';
  if (draft.circle && draft.reportType && draft.reportingDate) {
    const existing = arrivals[submissionKey(draft, draft.reportingDate)];
    if (existing && existing.id !== editingId) {
      e.circle = `An arrival is already recorded for ${draft.circle} · ${shortType(draft.reportType)} on this date. Edit that record instead.`;
    }
  }
  return e;
}

/** Non-blocking notes shown with the saved note (they never change the data status). */
export function arrivalWarnings(draft: ArrivalDraft) {
  const w: string[] = [];
  if (!draft.fileName.trim()) w.push('No file name: the note will be flagged for review until it is added.');
  if (draft.arrivalDate && draft.reportingDate && draft.arrivalDate < draft.reportingDate) {
    w.push('The arrival date is before the reporting date it covers: the note will be flagged for review.');
  }
  return w;
}

const PHONE_RE = /^\+?[\d\s-]{10,15}$/;
const EMAIL_RE = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;

export function contactErrors(c: Contact) {
  const e: Partial<Record<keyof Contact, string>> = {};
  if (c.phone.trim() && !PHONE_RE.test(c.phone.trim())) e.phone = 'Enter 10 to 15 digits (spaces, "-" and a leading + are allowed).';
  if (c.email.trim() && !EMAIL_RE.test(c.email.trim())) e.email = 'Enter a valid email address.';
  if (!c.name.trim() && (c.phone.trim() || c.email.trim() || c.designation.trim())) e.name = 'Add the contact person\'s name with their details.';
  return e;
}

export interface FollowUpDraft {
  at: string;
  contactPerson: string;
  method: FollowUpMethod | '';
  outcome: string;
  expectedAt: string;
  nextFollowUp: string;
}

export function followUpErrors(d: FollowUpDraft, now: Date) {
  const e: Partial<Record<keyof FollowUpDraft, string>> = {};
  if (!d.at) e.at = 'Enter when the follow-up happened.';
  else if (new Date(d.at) > now) e.at = 'A follow-up cannot be recorded in the future; use "Next follow-up" for plans.';
  if (!d.method) e.method = 'Choose how you followed up.';
  if (!d.outcome.trim()) e.outcome = 'Add a short note on the outcome.';
  if (d.nextFollowUp && d.at && d.nextFollowUp <= d.at) e.nextFollowUp = 'The next follow-up should be after this one.';
  return e;
}

let counter = 0;
export const newId = (prefix: string) => `${prefix}-${Date.now().toString(36)}-${(counter += 1)}`;

// --- Email ---------------------------------------------------------------------------------

export interface EmailDraft {
  to: string;
  cc: string;
  subject: string;
  body: string;
}
export const EMPTY_EMAIL: EmailDraft = { to: '', cc: '', subject: '', body: '' };

/** Addresses separated by commas or semicolons (the backend accepts the same). */
export const splitAddresses = (value: string) => value.split(/[,;]/).map((a) => a.trim()).filter(Boolean);

function addressError(value: string, required: boolean) {
  const list = splitAddresses(value);
  if (!list.length) return required ? 'Enter at least one recipient.' : undefined;
  const invalid = list.filter((a) => !EMAIL_RE.test(a));
  if (invalid.length) return `Not a valid email address: ${invalid.join(', ')}.`;
  if (list.length > 20) return 'At most 20 addresses.';
  return undefined;
}

/** Same rules as the backend (apps/common/email.py); the backend checks again before sending. */
export function emailErrors(d: EmailDraft) {
  const e: Partial<Record<keyof EmailDraft, string>> = {};
  const to = addressError(d.to, true);
  const cc = addressError(d.cc, false);
  if (to) e.to = to;
  if (cc) e.cc = cc;
  if (!d.subject.trim()) e.subject = 'Enter a subject.';
  else if (d.subject.length > 200) e.subject = 'At most 200 characters.';
  else if (/[\r\n]/.test(d.subject)) e.subject = 'The subject must be a single line.';
  if (!d.body.trim()) e.body = 'Enter a message.';
  else if (d.body.length > 20000) e.body = 'At most 20,000 characters.';
  return e;
}

/** A configured deadline as the backend expects it (local YYYY-MM-DDTHH:MM), or undefined. */
export const deadlineParam = (deadline: Date | null) => (deadline ? `${localDate(deadline)}T${localTime(deadline)}` : undefined);
