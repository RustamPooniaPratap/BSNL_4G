import type {
  AlertsResponse,
  BreakdownResponse,
  FilterOptions,
  HealthStatus,
  MonthlyResponse,
  RawFilesResponse,
  RecordsResponse,
  SiteDetailResponse,
  SourceStatusResponse,
  SummaryResponse,
  TeamMonthlyResponse,
  TopPerformersResponse,
  TeamsResponse,
  ThresholdResponse,
  PeriodSummary,
  TrendResponse,
  UploadResponse,
  WorkbookStatus,
  WorkbookUploadResult,
  EmailStatus,
  EmailResult,
  ReminderRequest,
  ReminderTemplate,
  AuthUser,
  OmHeadsResponse,
  ConversionActivity,
  DataSourceKind,
  DataSourceState,
  DatabaseCompleteness,
  ImportBatch,
  PortalUser,
  Role,
} from '../types';
import type {
  RcaCauses, RcaCycleDetail, RcaCycleList, RcaImportBatch, RcaOptions, RcaPage, RcaRecordDetail, RcaRecordInput, RcaReportVersion,
  RcaSummary, RcaUploadDetails, RcaWorkflowInput,
} from '../types/rca';
import type { ArrivalTracker, RawRowsPage, RawUpload, RawUploadDetails, RawUploadOptions } from '../types/rawUpload';

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL || 'http://localhost:8000/api';

/** Error raised for non-2xx responses; carries the backend's message and field details. */
export class ApiError extends Error {
  readonly status: number;
  readonly details: Record<string, unknown>;

  constructor(message: string, status: number, details: Record<string, unknown> = {}) {
    super(message);
    this.name = 'ApiError';
    this.status = status;
    this.details = details;
  }
}

async function parseError(response: Response): Promise<ApiError> {
  let message = `Request failed with status ${response.status}`;
  let details: Record<string, unknown> = {};
  try {
    const body = await response.json();
    if (typeof body?.error === 'string') message = body.error;
    if (body?.details && typeof body.details === 'object') details = body.details;
  } catch {
    // Non-JSON error body (e.g. a proxy error page); keep the generic message.
  }
  return new ApiError(message, response.status, details);
}

// --- Session and CSRF -------------------------------------------------------------------------
// The session cookie is HttpOnly and set by Django; the CSRF token is kept in memory only
// (never in localStorage or sessionStorage) and sent in the X-CSRFToken header.
let csrfToken: string | null = null;
export const setCsrfToken = (token: string | null) => { csrfToken = token; };

export type AuthEvent = 'expired' | 'password_change_required';
/** Broadcast when the server says the session ended (401) or a temporary password must be changed. */
export const AUTH_EVENT = 'portal-auth';
const notify = (event: AuthEvent) => window.dispatchEvent(new CustomEvent<AuthEvent>(AUTH_EVENT, { detail: event }));

const UNSAFE = new Set(['POST', 'PUT', 'PATCH', 'DELETE']);
const unreachable = () => new ApiError('The reporting API could not be reached. Check that the backend server is running.', 0);

async function ensureCsrf(): Promise<string> {
  if (!csrfToken) {
    let response: Response;
    try {
      response = await fetch(`${API_BASE_URL}/auth/csrf/`, { credentials: 'include' });
    } catch {
      throw unreachable();
    }
    if (!response.ok) throw await parseError(response);
    csrfToken = ((await response.json()) as { csrf_token: string }).csrf_token;
  }
  return csrfToken;
}

async function request<T>(path: string, params?: URLSearchParams, init?: RequestInit, retried = false): Promise<T> {
  const query = params && params.toString() ? `?${params}` : '';
  const method = (init?.method ?? 'GET').toUpperCase();
  const headers = new Headers(init?.headers);
  if (UNSAFE.has(method)) headers.set('X-CSRFToken', await ensureCsrf());
  let response: Response;
  try {
    response = await fetch(`${API_BASE_URL}${path}${query}`, { ...init, headers, credentials: 'include' });
  } catch (error) {
    if (error instanceof DOMException && error.name === 'AbortError') throw error;
    throw unreachable();
  }
  if (!response.ok) {
    const error = await parseError(response);
    // A rotated or missing CSRF token: fetch a fresh one and try once more.
    if (response.status === 403 && UNSAFE.has(method) && !retried && /CSRF/i.test(error.message)) {
      csrfToken = null;
      return request<T>(path, params, init, true);
    }
    if (response.status === 401 && !path.startsWith('/auth/')) notify('expired');
    if (response.status === 403 && error.details.code === 'password_change_required') notify('password_change_required');
    throw error;
  }
  return response.json() as Promise<T>;
}

export const fetchHealthStatus = () => request<HealthStatus>('/health/');

export const fetchRawFiles = () => request<RawFilesResponse>('/raw-files/');

export async function uploadDataFile(file: File): Promise<UploadResponse> {
  const formData = new FormData();
  formData.append('file', file);
  return request<UploadResponse>('/upload/', undefined, { method: 'POST', body: formData });
}

type Fetcher<T> = (params: URLSearchParams, signal?: AbortSignal) => Promise<T>;

const dashboard = <T,>(path: string): Fetcher<T> =>
  (params, signal) => request<T>(`/dashboard/${path}`, params, { signal });

export const fetchFilterOptions = (signal?: AbortSignal) =>
  request<FilterOptions>('/dashboard/filters/', undefined, { signal });
export const fetchSummary = dashboard<SummaryResponse>('summary/');
export const fetchTrends = dashboard<TrendResponse>('trends/');
export const fetchBreakdowns = dashboard<BreakdownResponse>('breakdowns/');
export const fetchRecords = dashboard<RecordsResponse>('records/');
export const fetchMonthly = dashboard<MonthlyResponse>('monthly/');
export const fetchTeams = dashboard<TeamsResponse>('teams/');
export const fetchTeamMonthly = dashboard<TeamMonthlyResponse>('teams/monthly/');
export const fetchTeamTop = dashboard<TopPerformersResponse>('teams/top/');
export const fetchThresholds = dashboard<ThresholdResponse>('thresholds/');
export const fetchPeriod = dashboard<PeriodSummary>('period/');
export const fetchSiteDetail = (siteId: string, reportType: string, signal?: AbortSignal) =>
  request<SiteDetailResponse>(
    `/dashboard/records/${encodeURIComponent(siteId)}/`,
    new URLSearchParams({ report_type: reportType }),
    { signal },
  );
export const fetchSourceStatus = (signal?: AbortSignal) =>
  request<SourceStatusResponse>('/dashboard/source/', undefined, { signal });

export const fetchAlerts = (signal?: AbortSignal) =>
  request<AlertsResponse>('/dashboard/alerts/', undefined, { signal });

export const fetchWorkbookStatus = (signal?: AbortSignal) =>
  request<WorkbookStatus>('/dashboard/workbook/', undefined, { signal });

/**
 * Upload the Master workbook. Uses XMLHttpRequest because fetch cannot report upload
 * progress. `onProgress` receives 0-1 while bytes are sent; the server then validates.
 */
export async function uploadWorkbook(file: File, onProgress?: (fraction: number) => void): Promise<WorkbookUploadResult> {
  const token = await ensureCsrf();
  return new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest();
    xhr.open('POST', `${API_BASE_URL}/dashboard/workbook/`);
    xhr.withCredentials = true;
    xhr.setRequestHeader('X-CSRFToken', token);
    xhr.responseType = 'json';
    xhr.upload.onprogress = (event) => {
      if (event.lengthComputable) onProgress?.(event.loaded / event.total);
    };
    xhr.onload = () => {
      const body = xhr.response ?? {};
      if (xhr.status >= 200 && xhr.status < 300) resolve(body as WorkbookUploadResult);
      else reject(new ApiError(body.error || `Upload failed with status ${xhr.status}`, xhr.status, body.details ?? {}));
    };
    xhr.onerror = () => reject(new ApiError('The reporting API could not be reached. Check that the backend server is running.', 0));
    const form = new FormData();
    form.append('file', file);
    xhr.send(form);
  });
}

// --- Email (CSV arrival reminders and personal emails) ---------------------------------------

const postJson = <T,>(path: string, body: unknown) =>
  request<T>(path, undefined, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) });

export const fetchEmailStatus = (signal?: AbortSignal) => request<EmailStatus>('/email/status/', undefined, { signal });

export const fetchReminderTemplate = (reminder: ReminderRequest, signal?: AbortSignal) =>
  request<ReminderTemplate>('/email/reminder-template/', new URLSearchParams(
    Object.entries(reminder).filter(([, v]) => v) as [string, string][],
  ), { signal });

/** The backend builds the reminder text itself; only the event and recipients are sent. */
export const sendReminder = (reminder: ReminderRequest & { to: string; cc: string }) => postJson<EmailResult>('/email/reminder/', reminder);

export const sendPersonalEmail = (message: { to: string; cc: string; subject: string; body: string }) => postJson<EmailResult>('/email/send/', message);

// --- Accounts ----------------------------------------------------------------------------------

type JsonBody = Record<string, unknown>;
const send = <T,>(path: string, body: JsonBody = {}, method = 'POST') =>
  request<T>(path, undefined, { method, headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) });

export const fetchMe = (signal?: AbortSignal) => request<{ user: AuthUser }>('/auth/me/', undefined, { signal });

export async function signIn(username: string, password: string, remember = false) {
  await ensureCsrf();
  const result = await send<{ user: AuthUser; csrf_token: string }>('/auth/login/', { username, password, remember });
  setCsrfToken(result.csrf_token);  // Django rotates the token at sign-in
  return result.user;
}

/** Development bypass: the account it would sign in as, or null when the backend does not allow it here. */
export async function fetchDevLogin(signal?: AbortSignal) {
  try {
    return await request<{ enabled: boolean; username: string; role: Role }>('/auth/dev-login/', undefined, { signal });
  } catch (error) {
    if (error instanceof ApiError && error.status === 404) return null;
    throw error;
  }
}

export async function devSignIn() {
  await ensureCsrf();
  const result = await send<{ user: AuthUser; csrf_token: string }>('/auth/dev-login/');
  setCsrfToken(result.csrf_token);
  return result.user;
}

export async function signOut() {
  try {
    await send('/auth/logout/');
  } finally {
    setCsrfToken(null);
  }
}

export async function changePassword(currentPassword: string, newPassword: string) {
  const result = await send<{ user: AuthUser; csrf_token: string }>('/auth/password/', { current_password: currentPassword, new_password: newPassword });
  setCsrfToken(result.csrf_token);
  return result.user;
}

export const fetchUsers = (signal?: AbortSignal) => request<{ users: PortalUser[] }>('/auth/users/', undefined, { signal });
export const createUser = (user: { username: string; first_name: string; last_name: string; email: string; role: Role }) =>
  send<{ user: PortalUser; temporary_password: string }>('/auth/users/', user);
export const updateUser = (id: number, changes: { role?: Role; is_active?: boolean; circles?: string[] }) => send<{ user: PortalUser }>(`/auth/users/${id}/`, changes, 'PATCH');
export const resetUserPassword = (id: number) => send<{ user: PortalUser; temporary_password: string }>(`/auth/users/${id}/reset-password/`);
export const revokeUserSessions = (id: number) => send<{ sessions_revoked: number }>(`/auth/users/${id}/revoke-sessions/`);

// --- PostgreSQL import and dashboard data source ---------------------------------------------

export const fetchDataSource = (signal?: AbortSignal) => request<DataSourceState>('/data-source/', undefined, { signal });
export const setDataSource = (source: DataSourceKind, acknowledgeWarnings: boolean) =>
  send<DataSourceState>('/data-source/', { source, confirm: true, acknowledge_warnings: acknowledgeWarnings }, 'PUT');
export const fetchImports = (signal?: AbortSignal) => request<{ imports: ImportBatch[]; database: DatabaseCompleteness }>('/imports/', undefined, { signal });
export async function previewImport(file: File, reconciliation: File | null, options: { project?: string; dailyOnly?: boolean } = {}) {
  const form = new FormData();
  form.append('file', file);
  if (reconciliation) form.append('reconciliation_file', reconciliation);
  if (options.project) form.append('project', options.project);
  if (options.dailyOnly) form.append('daily_only', 'true');
  return request<ImportBatch>('/imports/preview/', undefined, { method: 'POST', body: form });
}
export const commitImport = (id: number, conflictSource: 'primary' | 'reconciliation' | '') =>
  send<ImportBatch & { database: DatabaseCompleteness }>(`/imports/${id}/commit/`, { conflict_source: conflictSource });
export const discardImport = (id: number) => send<ImportBatch>(`/imports/${id}/discard/`);
export const importIssuesUrl = (id: number) => `${API_BASE_URL}/imports/${id}/issues.csv`;

export const fetchConversionActivity = (params: URLSearchParams, signal?: AbortSignal) =>
  request<ConversionActivity>('/dashboard/conversion-activity/', params, { signal });
export const fetchOmHeads = (signal?: AbortSignal) => request<OmHeadsResponse>('/dashboard/om-heads/', undefined, { signal });

// --- RCA register ------------------------------------------------------------------------------

export const fetchRcaOptions = (signal?: AbortSignal) => request<RcaOptions>('/rca/options/', undefined, { signal });
export const fetchRcaRecords = (params: URLSearchParams, signal?: AbortSignal) => request<RcaPage>('/rca/records/', params, { signal });
export const fetchRcaRecord = (id: number, signal?: AbortSignal) => request<RcaRecordDetail>(`/rca/records/${id}/`, undefined, { signal });
export const createRcaRecord = (record: RcaRecordInput) => send<RcaRecordDetail>('/rca/records/', { ...record });
export const updateRcaWorkflow = (id: number, workflow: RcaWorkflowInput) => send<RcaRecordDetail>(`/rca/records/${id}/workflow/`, { ...workflow }, 'PUT');
export const addRcaComment = (id: number, text: string, evidence: string) => send<RcaRecordDetail>(`/rca/records/${id}/comments/`, { text, evidence });
export const fetchRcaSummary = (params: URLSearchParams, signal?: AbortSignal) => request<RcaSummary>('/rca/summary/', params, { signal });
/** The signed-in user's uploads; an Admin may ask for every upload. */
export const fetchRcaImports = (signal?: AbortSignal, all = false) =>
  request<{ imports: RcaImportBatch[]; records: number; all: boolean }>('/rca/imports/', all ? new URLSearchParams({ all: '1' }) : undefined, { signal });
export const fetchRcaImport = (id: number, signal?: AbortSignal) => request<RcaImportBatch>(`/rca/imports/${id}/`, undefined, { signal });
export async function previewRcaImport(file: File, details: RcaUploadDetails) {
  const form = new FormData();
  form.append('file', file);
  for (const [key, value] of Object.entries(details)) form.append(key, value);
  return request<RcaImportBatch>('/rca/imports/preview/', undefined, { method: 'POST', body: form });
}
export const commitRcaImport = (id: number, choices: { conflict_action?: '' | 'skip' | 'overwrite'; missing_action?: '' | 'keep' | 'withdraw'; accept_rejected?: boolean } = {}) =>
  send<RcaImportBatch & { records: number; final_report: RcaReportVersion | null }>(`/rca/imports/${id}/commit/`, { ...choices });
export const discardRcaImport = (id: number) => send<RcaImportBatch>(`/rca/imports/${id}/discard/`);
export const rcaIssuesUrl = (id: number) => `${API_BASE_URL}/rca/imports/${id}/issues.csv`;
export const rcaImportWorkbookUrl = (id: number) => `${API_BASE_URL}/rca/imports/${id}/report.xlsx`;
export const fetchRcaCycles = (signal?: AbortSignal) => request<RcaCycleList>('/rca/cycles/', undefined, { signal });
export const fetchRcaCycle = (id: number, signal?: AbortSignal) => request<RcaCycleDetail>(`/rca/cycles/${id}/`, undefined, { signal });
export const startRcaCycle = (period: { name: string; period_start: string; period_end: string; notes: string }, units: [string, string][]) =>
  send<RcaCycleDetail>('/rca/cycles/', { ...period, units });
export const setRcaRequired = (id: number, units: [string, string][]) => send<RcaCycleDetail>(`/rca/cycles/${id}/required/`, { units }, 'PUT');
export const finalizeRcaCycle = (id: number) =>
  send<RcaCycleDetail & { created: boolean; report: RcaReportVersion }>(`/rca/cycles/${id}/finalize/`);
export const rcaCycleWorkbookUrl = (id: number) => `${API_BASE_URL}/rca/cycles/${id}/report.xlsx`;
export const rcaReportFileUrl = (cycle: number, report: number) => `${API_BASE_URL}/rca/cycles/${cycle}/reports/${report}.xlsx`;
export const fetchRcaCauses = (signal?: AbortSignal) => request<RcaCauses>('/rca/causes/', undefined, { signal });
export const createRcaCategory = (name: string, description = '') => send<{ id: number; name: string }>('/rca/causes/categories/', { name, description });
export const mapRcaCauses = (keys: string[], category: number) => send<RcaCauses>('/rca/causes/mappings/', { keys, category });
export const unmapRcaCauses = (keys: string[]) => send<RcaCauses>('/rca/causes/mappings/', { keys }, 'DELETE');

// --- Raw daily CSV uploads (Data Entry -> Upload CSV) ------------------------------------------

export const fetchRawUploadOptions = (signal?: AbortSignal) => request<RawUploadOptions>('/raw-uploads/options/', undefined, { signal });
export const fetchRawUploads = (signal?: AbortSignal) => request<{ uploads: RawUpload[] }>('/raw-uploads/', undefined, { signal });
export const fetchRawUpload = (id: number, signal?: AbortSignal) => request<RawUpload>(`/raw-uploads/${id}/`, undefined, { signal });
export const fetchRawUploadRows = (id: number, status: string, page: number, signal?: AbortSignal) =>
  request<RawRowsPage>(`/raw-uploads/${id}/rows/`, new URLSearchParams({ ...(status ? { status } : {}), page: String(page) }), { signal });
export async function previewRawUpload(file: File, details: RawUploadDetails) {
  const form = new FormData();
  form.append('file', file);
  for (const [key, value] of Object.entries(details)) form.append(key, value);
  return request<RawUpload>('/raw-uploads/preview/', undefined, { method: 'POST', body: form });
}
export const commitRawUpload = (id: number) => send<RawUpload>(`/raw-uploads/${id}/commit/`, { confirm: true });
export const discardRawUpload = (id: number) => send<RawUpload>(`/raw-uploads/${id}/discard/`);
export const rawUploadIssuesUrl = (id: number) => `${API_BASE_URL}/raw-uploads/${id}/issues.csv`;

// --- CSV arrival tracking ------------------------------------------------------------------------

/** Stored daily-data coverage and raw CSV uploads per project/circle for a date, plus a daily range (Admins). */
export const fetchArrivalTracker = (params: { date: string; start: string; end: string }, signal?: AbortSignal) =>
  request<ArrivalTracker>('/arrival-tracker/', new URLSearchParams(params), { signal });

// --- Excel report downloads (Daily Uptime Report, Full Consolidated Report) -------------------------------------

export type ReportKind = 'daily' | 'consolidated';

/** Fetch a report from the active data source; the server's message is thrown as an ApiError, never a broken file. */
export async function downloadReport(kind: ReportKind, params: Record<string, string>, signal?: AbortSignal) {
  const query = new URLSearchParams(Object.entries(params).filter(([, value]) => value));
  let response: Response;
  try {
    response = await fetch(`${API_BASE_URL}/dashboard/export/${kind}/?${query}`, { credentials: 'include', signal });
  } catch (error) {
    if (error instanceof DOMException && error.name === 'AbortError') throw error;
    throw unreachable();
  }
  if (!response.ok) throw await parseError(response);
  const disposition = response.headers.get('Content-Disposition') ?? '';
  const filename = /filename="([^"]+)"/.exec(disposition)?.[1] ?? `${kind}_report.xlsx`;
  return { blob: await response.blob(), filename };
}
