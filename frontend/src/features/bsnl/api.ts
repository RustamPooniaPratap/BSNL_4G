import { fetchFile, request } from '../../services/api';
import type {
  BucketMapping, CircleProfile, LetterDetail, LetterOptions, LetterOverview, LetterStatus, Recipient, RecipientReportType,
  ReportOptions, ReportOverview, ReportPreview, ReportRun, ReportType,
} from './types';

/** BSNL Module API calls (/api/bsnl/). The server checks every permission again; downloads never send email. */
const get = <T,>(path: string, params?: URLSearchParams, signal?: AbortSignal) => request<T>(`/bsnl/${path}`, params, { signal });
const write = <T,>(path: string, body: unknown = {}, method = 'POST') =>
  request<T>(`/bsnl/${path}`, undefined, { method, headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) });
const params = (values: Record<string, string>) => new URLSearchParams(Object.entries(values).filter(([, v]) => v !== ''));

// --- Auto Email Reports
export const fetchReportOptions = (signal?: AbortSignal) => get<ReportOptions>('reports/options/', undefined, signal);
export const fetchReportOverview = (type: ReportType, project: string, signal?: AbortSignal) =>
  get<ReportOverview>('reports/overview/', params({ type, project }), signal);
export const fetchReportPreview = (type: ReportType, circle: string, project: string, signal?: AbortSignal) =>
  get<ReportPreview>('reports/preview/', params({ type, circle, project }), signal);
export const downloadReportFile = (type: ReportType, circle: string, project: string, file: 'eml' | 'xlsx') =>
  fetchFile('/bsnl/reports/download/', params({ type, circle, project, file }));
export const downloadAllCircleEmails = (type: ReportType, project: string) => fetchFile('/bsnl/reports/download-all/', params({ type, project }));
export const sendReport = (type: ReportType, circle: string, project: string) => write<{ run: ReportRun }>('reports/send/', { type, circle, project });
export const fetchReportRuns = (signal?: AbortSignal) => get<{ runs: ReportRun[] }>('reports/runs/', undefined, signal);
export const saveSchedule = (schedule: { daily: boolean; weekly: boolean }) =>
  write<{ daily: boolean; weekly: boolean; sending_enabled: boolean }>('reports/schedule/', schedule, 'PUT');

// --- Distribution Master
export type RecipientInput = Omit<Recipient, 'id' | 'circle_name' | 'updated_at'>;
export const fetchRecipients = (reportType?: RecipientReportType, signal?: AbortSignal) =>
  get<{ recipients: Recipient[]; can_manage: Record<RecipientReportType, boolean> }>('recipients/', params({ report_type: reportType ?? '' }), signal);
export const createRecipient = (row: RecipientInput) => write<{ recipient: Recipient }>('recipients/', row);
export const updateRecipient = (id: number, row: RecipientInput) => write<{ recipient: Recipient }>(`recipients/${id}/`, row, 'PUT');

// --- BSNL Letters
export interface LetterPeriodQuery { period: string; date_from: string; date_to: string; project: string }
export const fetchLetterOptions = (signal?: AbortSignal) => get<LetterOptions>('letters/options/', undefined, signal);
export const fetchLetterOverview = (q: LetterPeriodQuery, signal?: AbortSignal) =>
  get<LetterOverview>('letters/overview/', params({ ...q }), signal);
export const openLetter = (circle: string, q: LetterPeriodQuery) => write<{ letter: LetterDetail; created: boolean }>('letters/open/', { circle, ...q });
export const fetchLetter = (id: number, signal?: AbortSignal) => get<{ letter: LetterDetail }>(`letters/${id}/`, undefined, signal);
export const saveLetterContent = (id: number, html: string) => write<{ letter: LetterDetail }>(`letters/${id}/content/`, { html }, 'PUT');
export const regenerateLetter = (id: number) => write<{ letter: LetterDetail }>(`letters/${id}/regenerate/`);
export const approveLetter = (id: number) => write<{ letter: LetterDetail }>(`letters/${id}/approve/`);
export const sendLetter = (id: number) => write<{ letter: LetterDetail }>(`letters/${id}/send/`);
export const setLetterStatus = (id: number, status: LetterStatus, note: string) => write<{ letter: LetterDetail }>(`letters/${id}/status/`, { status, note });
export const downloadLetterFile = (id: number, kind: 'doc' | 'xlsx' | 'eml' | 'html') => fetchFile(`/bsnl/letters/${id}/download/${kind}/`);
export const downloadLetterRegister = () => fetchFile('/bsnl/letters/register.xlsx');
export const fetchProfiles = (signal?: AbortSignal) => get<{ profiles: CircleProfile[]; can_manage: boolean }>('letters/profiles/', undefined, signal);
export const saveProfile = (profile: CircleProfile) => write<{ profile: CircleProfile }>(`letters/profiles/${profile.circle}/`, profile, 'PUT');
export const fetchBucketMapping = (signal?: AbortSignal) => get<BucketMapping>('letters/bucket-mapping/', undefined, signal);
export const saveBucketMapping = (mapping: BucketMapping['mapping']) => write<BucketMapping>('letters/bucket-mapping/', { mapping }, 'PUT');
