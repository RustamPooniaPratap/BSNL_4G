/**
 * Client-side checks for the data-management forms (Add Row, Upload CSV, Add New Site).
 *
 * These are preliminary checks only: nothing here is saved, and passing them does not
 * guarantee uniqueness or correctness in the authoritative database.
 * Formats follow the Master workbook's Up-Time Report (see docs/data-entry.md).
 */

export const MINUTES_PER_DAY = 1440;

/** Confirmation messages: these workflows validate locally and never save. */
export const VALIDATED_MESSAGES = {
  row: 'Record validated locally. Backend integration is not enabled yet.',
  csv: 'CSV validated locally. Backend ingestion is not enabled yet.',
  site: 'Site details validated locally. Master DB integration is not enabled yet.',
} as const;

/** Props that tie an input to its Field's error or warning text for screen readers. */
export const fieldA11y = (id: string, error?: string | null, warning?: string | null) => ({
  id,
  'aria-invalid': error ? true : undefined,
  'aria-describedby': error ? `${id}-error` : warning ? `${id}-warning` : undefined,
});

/** btsIpId formats seen in the Master workbook, per report type. */
export const SITE_ID_PATTERNS: Record<string, { pattern: RegExp; example: string }> = {
  '4G Saturation': { pattern: /^UV[A-Z]{5}\d{5}$/, example: 'UVMPBPL00012' },
  LWE: { pattern: /^LWE[A-Z]{2,3}\d{4}$/, example: 'LWEBH0303' },
};

/** The workbook spells two LWE circles in full; everything else uses the circle code. */
const CIRCLE_ALIASES: Record<string, string> = { 'MADHYA PRADESH': 'MP', ODISHA: 'OD' };
const REPORT_TYPE_ALIASES: Record<string, string> = {
  '4G SATU.': '4G Saturation', '4G SATU': '4G Saturation', '4G SATURATION': '4G Saturation', '4G': '4G Saturation', LWE: 'LWE',
};

export const normaliseSiteId = (value: string) => value.trim().toUpperCase();
export const normaliseCircle = (value: string) => {
  const upper = value.trim().toUpperCase();
  return CIRCLE_ALIASES[upper] ?? upper;
};
export const normaliseReportType = (value: string) => REPORT_TYPE_ALIASES[value.trim().toUpperCase()] ?? value.trim();

/** Error message for a Site ID, or null when its format matches the report type. */
export function siteIdError(value: string, reportType: string): string | null {
  const id = normaliseSiteId(value);
  if (!id) return 'Site ID is required.';
  if (/\s/.test(value.trim())) return 'Site ID cannot contain spaces.';
  const rule = SITE_ID_PATTERNS[reportType];
  if (rule && !rule.pattern.test(id)) return `Not a ${reportType} Site ID format (expected like ${rule.example}).`;
  if (!rule && !/^[A-Z0-9_-]{4,20}$/.test(id)) return 'Site ID may contain only letters, digits, "-" and "_".';
  return null;
}

/**
 * Parse a date typed or found in a file. Accepts YYYY-MM-DD, DD-MM-YYYY and DD/MM/YYYY
 * (the sample file uses 16-10-2026). Returns an ISO date or null when invalid.
 */
export function parseDate(value: string): string | null {
  const text = value.trim();
  let year: number, month: number, day: number;
  let match = /^(\d{4})-(\d{1,2})-(\d{1,2})$/.exec(text);
  if (match) [year, month, day] = [Number(match[1]), Number(match[2]), Number(match[3])];
  else {
    match = /^(\d{1,2})[-/.](\d{1,2})[-/.](\d{4})$/.exec(text);
    if (!match) return null;
    [day, month, year] = [Number(match[1]), Number(match[2]), Number(match[3])];
  }
  const date = new Date(Date.UTC(year, month - 1, day));
  if (date.getUTCFullYear() !== year || date.getUTCMonth() !== month - 1 || date.getUTCDate() !== day) return null;
  return date.toISOString().slice(0, 10);
}

/** A finite number, or null. Thousands separators are not accepted, to avoid misreading. */
export function parseNumber(value: string): number | null {
  const text = value.trim();
  if (!/^-?\d+(\.\d+)?$/.test(text)) return null;
  return Number(text);
}

export function outageError(value: string): string | null {
  if (!value.trim()) return 'Outage minutes are required (enter 0 for no outage).';
  const minutes = parseNumber(value);
  if (minutes == null) return 'Enter a number of minutes, e.g. 0, 45 or 1440.';
  if (minutes < 0) return 'Outage minutes cannot be negative.';
  return null;
}

/** Outage above a full day is accepted by the workbook but flagged (business rule pending). */
export const outageWarning = (value: string) => {
  const minutes = parseNumber(value);
  return minutes != null && minutes > MINUTES_PER_DAY
    ? `More than ${MINUTES_PER_DAY.toLocaleString('en-IN')} minutes (a full day). The workbook flags such values; the rule is still open.`
    : null;
};

// --- CSV ---------------------------------------------------------------------------------

export interface ParsedCsv {
  headers: string[];
  rows: string[][];
  /** 1-based line number in the file of each data row. */
  lines: number[];
}

/** RFC 4180 CSV parsing (quoted fields, escaped quotes, CRLF), without a library. */
export function parseCsv(text: string): ParsedCsv {
  const records: { cells: string[]; line: number }[] = [];
  let cells: string[] = [];
  let cell = '';
  let quoted = false;
  let line = 1;
  let recordLine = 1;
  const source = text.replace(/^﻿/, '');
  for (let i = 0; i < source.length; i += 1) {
    const char = source[i];
    if (quoted) {
      if (char === '"' && source[i + 1] === '"') { cell += '"'; i += 1; }
      else if (char === '"') quoted = false;
      else { if (char === '\n') line += 1; cell += char; }
    } else if (char === '"' && cell === '') quoted = true;
    else if (char === ',') { cells.push(cell); cell = ''; }
    else if (char === '\n' || char === '\r') {
      if (char === '\r' && source[i + 1] === '\n') i += 1;
      cells.push(cell);
      records.push({ cells, line: recordLine });
      cells = []; cell = ''; line += 1; recordLine = line;
    } else cell += char;
  }
  if (cell !== '' || cells.length) { cells.push(cell); records.push({ cells, line: recordLine }); }
  const nonEmpty = records.filter((r) => r.cells.some((c) => c.trim() !== ''));
  const [header, ...data] = nonEmpty;
  return {
    headers: (header?.cells ?? []).map((h) => h.trim()),
    rows: data.map((r) => r.cells),
    lines: data.map((r) => r.line),
  };
}

export type ColumnRole = 'site_id' | 'outage_minutes' | 'availability_pct' | 'circle' | 'date' | 'site_name' | 'report_type';

/** Accepted header names per role (compared case-insensitively, ignoring spaces, dots and underscores). */
export const COLUMN_ALIASES: Record<ColumnRole, string[]> = {
  site_id: ['btsIpId', 'BTS IP ID', 'Site ID', 'site_id'],
  outage_minutes: ['Outage Minutes', 'Outage Min.', 'Outage', 'outage_minutes'],
  availability_pct: ['Nw Avail (4G TCS)', 'Nw Avail', 'Availability', 'Availability %', 'Uptime %'],
  circle: ['Circle'],
  date: ['Report Date', 'Reporting Date', 'Date'],
  site_name: ['Site name', 'Site Name'],
  report_type: ['Project', 'Report type', 'Report Type'],
};
const key = (header: string) => header.toLowerCase().replace(/[\s._%()-]/g, '');

/** Which column holds which field; unrecognised headers are reported, never guessed. */
export function detectColumns(headers: string[]) {
  const roles: Partial<Record<ColumnRole, number>> = {};
  const unknown: string[] = [];
  const duplicates: string[] = [];
  const seen = new Set<string>();
  headers.forEach((header, index) => {
    // Any header repeated (ignoring case and spaces), or two headers meaning the same field.
    const name = header.trim().toLowerCase();
    const role = (Object.keys(COLUMN_ALIASES) as ColumnRole[]).find((r) => COLUMN_ALIASES[r].some((a) => key(a) === key(header)));
    if (name && seen.has(name)) duplicates.push(header);
    else if (role && roles[role] != null) duplicates.push(header);
    else if (!role) unknown.push(header || `(column ${index + 1} has no name)`);
    else roles[role] = index;
    if (name) seen.add(name);
  });
  return { roles, unknown: unknown.filter((h) => !duplicates.includes(h)), duplicates };
}

export interface CsvMetadata {
  reportType: string;
  circle: string;
  date: string;
}

export interface CsvIssue {
  /** File line number; 1 is the header row, null for file-level issues. */
  line: number | null;
  severity: 'error' | 'warning';
  message: string;
  siteId?: string;
  /** Set for Site IDs missing from the master data, so the page can offer "Add new site". */
  unknownSite?: boolean;
}

/** The file-level reporting date check: every row must carry the selected date. */
export interface DateCheck {
  /** pending: no date selected yet or no rows to check. */
  status: 'passed' | 'failed' | 'pending';
  expected: string | null;
  /** The CSV column read for the date, or null when the file has none. */
  column: string | null;
  /** Each valid date found (YYYY-MM-DD) with its line numbers, sorted. */
  detected: { date: string; lines: number[] }[];
  /** Empty or unreadable date values with their line numbers. */
  invalid: { value: string; lines: number[] }[];
  mixed: boolean;
  message: string;
}

export interface CsvValidation {
  headers: string[];
  dateCheck: DateCheck;
  roles: Partial<Record<ColumnRole, number>>;
  measure: 'outage_minutes' | 'availability_pct' | null;
  rowCount: number;
  validRows: number;
  siteIds: string[];
  issues: CsvIssue[];
  errorCount: number;
  warningCount: number;
}

/**
 * Validate a parsed CSV against the selected upload metadata. ``knownSites`` is the set of
 * Site IDs in the master data for the selected report type and circle (null while loading).
 */
export function validateCsv(csv: ParsedCsv, meta: CsvMetadata, knownSites: Set<string> | null): CsvValidation {
  const issues: CsvIssue[] = [];
  const add = (line: number | null, severity: CsvIssue['severity'], message: string, siteId?: string) =>
    issues.push({ line, severity, message, siteId });
  const { roles, unknown, duplicates } = detectColumns(csv.headers);
  let measure: CsvValidation['measure'] = null;

  if (!csv.headers.length) add(null, 'error', 'The file is empty.');
  else if (!csv.rows.length) add(null, 'error', 'The file has a header row but no data rows.');
  if (csv.headers.length && roles.site_id == null) add(1, 'error', `Missing the Site ID column (one of: ${COLUMN_ALIASES.site_id.join(', ')}).`);
  if (roles.outage_minutes != null && roles.availability_pct != null) {
    add(1, 'error', 'The file has both an outage-minutes and an availability column; keep only one.');
  } else if (roles.outage_minutes != null) measure = 'outage_minutes';
  else if (roles.availability_pct != null) {
    measure = 'availability_pct';
    add(1, 'warning', 'Values are availability %, not outage minutes. The conversion to outage minutes is not confirmed yet.');
  } else if (csv.headers.length) {
    add(1, 'error', `Missing the value column: outage minutes (${COLUMN_ALIASES.outage_minutes.join(', ')}) or availability % (${COLUMN_ALIASES.availability_pct.join(', ')}).`);
  }
  if (csv.headers.length && roles.date == null) {
    add(1, 'error', `Missing the reporting-date column (one of: ${COLUMN_ALIASES.date.join(', ')}). Every row must state its reporting date.`);
  }
  duplicates.forEach((h) => add(1, 'error', `Column "${h}" appears more than once.`));
  if (unknown.length) add(1, 'warning', `Columns not used and not checked: ${unknown.join(', ')}.`);

  const seen = new Map<string, number>();
  const siteIds: string[] = [];
  const datesFound = new Map<string, number[]>();
  const badDates = new Map<string, number[]>();
  const note = (map: Map<string, number[]>, k: string, line: number) => map.set(k, [...(map.get(k) ?? []), line]);
  let validRows = 0;
  const canCheckRows = roles.site_id != null && measure != null && !duplicates.length;

  csv.rows.forEach((row, i) => {
    const line = csv.lines[i];
    if (!canCheckRows) return;
    let rowOk = true;
    const fail = (message: string, siteId?: string, unknownSite = false) => {
      rowOk = false;
      issues.push({ line, severity: 'error', message, siteId, unknownSite: unknownSite || undefined });
    };
    if (row.length !== csv.headers.length) {
      fail(`Has ${row.length} value${row.length === 1 ? '' : 's'} but the header has ${csv.headers.length} columns.`);
      return;
    }
    const value = (role: ColumnRole) => (roles[role] == null ? '' : row[roles[role]!].trim());
    const siteId = normaliseSiteId(value('site_id'));
    if (!siteId) fail('Site ID is empty.');
    else {
      const formatError = siteIdError(siteId, meta.reportType);
      if (formatError) fail(formatError, siteId);
      siteIds.push(siteId);
      // A file covers one reporting date, so a Site ID may appear only once.
      const first = seen.get(siteId);
      if (first != null) fail(`Duplicate Site ID ${siteId} (first on line ${first}).`, siteId);
      else seen.set(siteId, line);
      if (knownSites && !formatError && !knownSites.has(siteId)) {
        fail(`Site ${siteId} is not in the ${meta.reportType} · ${meta.circle} master data.`, siteId, true);
      }
    }

    const raw = value(measure!);
    if (!raw) fail(measure === 'outage_minutes' ? 'Outage minutes are empty.' : 'Availability is empty.', siteId);
    else if (measure === 'outage_minutes') {
      const minutes = parseNumber(raw);
      if (minutes == null) fail(`Outage "${raw}" is not a number.`, siteId);
      else if (minutes < 0) fail('Outage minutes cannot be negative.', siteId);
      else if (minutes > MINUTES_PER_DAY) add(line, 'warning', `Outage ${raw} min is more than a full day.`, siteId);
    } else {
      const pct = parseNumber(raw.replace(/%$/, ''));
      if (pct == null) fail(`Availability "${raw}" is not a number.`, siteId);
      else if (pct < 0 || pct > 100) fail(`Availability ${raw} is outside 0–100%.`, siteId);
    }

    if (roles.date != null) {
      // Normalised to YYYY-MM-DD before comparing; never compared as raw text.
      const raw = value('date');
      const date = parseDate(raw);
      if (!raw) { note(badDates, '', line); fail('Reporting date is empty.', siteId); }
      else if (!date) { note(badDates, raw, line); fail(`Date "${raw}" is not a valid date (use YYYY-MM-DD or DD-MM-YYYY).`, siteId); }
      else {
        note(datesFound, date, line);
        if (meta.date && date !== meta.date) fail(`Date ${date} does not match the selected reporting date ${meta.date}.`, siteId);
      }
    }
    if (roles.circle != null && value('circle') && meta.circle && normaliseCircle(value('circle')) !== meta.circle) {
      fail(`Circle "${value('circle')}" does not match the selected circle ${meta.circle}.`, siteId);
    }
    if (roles.report_type != null && value('report_type') && normaliseReportType(value('report_type')) !== meta.reportType) {
      fail(`Report type "${value('report_type')}" does not match the selected ${meta.reportType}.`, siteId);
    }
    if (rowOk) validRows += 1;
  });

  const detected = [...datesFound].map(([date, lines]) => ({ date, lines })).sort((a, b) => a.date.localeCompare(b.date));
  const invalid = [...badDates].map(([value, lines]) => ({ value, lines }));
  const mixed = detected.length > 1;
  if (mixed) {
    add(null, 'error', `The file contains ${detected.length} different reporting dates (${detected.map((d) => `${d.date}: ${d.lines.length} row${d.lines.length === 1 ? '' : 's'}`).join(', ')}). A file must cover one date.`);
  }
  const dateCheck = summariseDates(meta.date || null, roles.date == null ? null : csv.headers[roles.date], detected, invalid, mixed, csv.rows.length > 0 && canCheckRows);

  // Rows that are exact copies of each other are reported once more, explicitly.
  const exact = new Map<string, number>();
  csv.rows.forEach((row, i) => {
    const signature = row.map((c) => c.trim()).join('\u0001');
    const first = exact.get(signature);
    if (first != null) add(csv.lines[i], 'warning', `Exact copy of line ${first}.`);
    else exact.set(signature, csv.lines[i]);
  });

  // By line; on a line, errors before warnings, otherwise in the order found (Array.sort is stable).
  const rank = (issue: CsvIssue) => (issue.severity === 'error' ? 0 : 1);
  issues.sort((a, b) => (a.line ?? 0) - (b.line ?? 0) || rank(a) - rank(b));
  return {
    headers: csv.headers,
    dateCheck,
    roles,
    measure,
    rowCount: csv.rows.length,
    validRows,
    siteIds,
    issues,
    errorCount: issues.filter((x) => x.severity === 'error').length,
    warningCount: issues.filter((x) => x.severity === 'warning').length,
  };
}

function summariseDates(expected: string | null, column: string | null, detected: DateCheck['detected'],
  invalid: DateCheck['invalid'], mixed: boolean, checkable: boolean): DateCheck {
  const base = { expected, column, detected, invalid, mixed };
  if (column == null) {
    return { ...base, status: checkable || expected ? 'failed' : 'pending', message: 'The file has no reporting-date column.' };
  }
  if (!expected || !checkable) return { ...base, status: 'pending', message: 'Choose the reporting date and a valid file to check dates.' };
  const blank = invalid.find((i) => i.value === '')?.lines.length ?? 0;
  const unreadable = invalid.filter((i) => i.value !== '').reduce((n, i) => n + i.lines.length, 0);
  const wrong = detected.filter((d) => d.date !== expected).reduce((n, d) => n + d.lines.length, 0);
  if (!blank && !unreadable && !wrong && !mixed) return { ...base, status: 'passed', message: `Every row is dated ${expected}.` };
  const parts = [
    mixed ? `${detected.length} different dates` : null,
    wrong ? `${wrong} row${wrong === 1 ? '' : 's'} with another date` : null,
    blank ? `${blank} row${blank === 1 ? '' : 's'} without a date` : null,
    unreadable ? `${unreadable} row${unreadable === 1 ? '' : 's'} with an unreadable date` : null,
  ].filter(Boolean);
  return { ...base, status: 'failed', message: `Expected ${expected} on every row; found ${parts.join(', ')}.` };
}

/** Link to the Add New Site form, pre-filled from a daily record. */
export function newSiteLink(siteId: string, reportType?: string, circle?: string) {
  const query = new URLSearchParams();
  if (siteId) query.set('site_id', normaliseSiteId(siteId));
  if (reportType) query.set('report_type', reportType);
  if (circle) query.set('circle', circle);
  return `/data/new-site?${query}`;
}

export const formatBytes = (bytes: number) =>
  (bytes < 1024 ? `${bytes} B` : bytes < 1024 ** 2 ? `${(bytes / 1024).toFixed(1)} KB` : `${(bytes / 1024 ** 2).toFixed(1)} MB`);
