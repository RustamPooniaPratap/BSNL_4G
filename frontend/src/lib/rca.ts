import { formatDate, formatNumber } from './format';

export const ALL = 'all';
/** URL parameters shared by the RCA Register and Summary (so a filtered view can be refreshed or shared). */
export const FILTER_KEYS = ['date_from', 'date_to', 'project', 'circle', 'site_scope', 'final_bucket', 'bucket_2', 'responsibility', 'category', 'rca', 'status', 'q', 'rca_scope'] as const;
/** Site Scope (backend: apps/rca/sitescope.py): by the Site Master O&M Start of each record's site for its reporting month. */
export const SITE_SCOPES = [
  { value: 'all', label: 'All Sites' }, { value: 'om_start', label: 'O&M Start Sites' }, { value: 'om_not_started', label: 'O&M Not Started Sites' },
] as const;
export const siteScopeLabel = (value: string | null) => SITE_SCOPES.find((s) => s.value === value)?.label ?? 'All Sites';
export type FilterKey = (typeof FILTER_KEYS)[number];

export const NOT_RECORDED = 'Not recorded';
export const shortProject = (p: string) => (p === '4G Saturation' ? '4G' : p);
/** Outage minutes, or "Not recorded" when the source has no value (never 0). */
export const formatMin = (v: number | null | undefined) => (v == null ? NOT_RECORDED : `${formatNumber(Math.round(v))} min`);

/** A reporting period: one date, or "first – last". */
export const periodText = (start: string | null, end: string | null) =>
  !start ? '—' : !end || end === start ? formatDate(start) : `${formatDate(start)} – ${formatDate(end)}`;

/** Which reporting dates the stored RCA records cover (the page context shown in the top bar). */
export function rcaCoverageText(dates: string[]): string {
  if (!dates.length) return 'No RCA records imported yet';
  if (dates.length === 1) return `RCA data for ${formatDate(dates[0])}`;
  return `RCA data covers ${dates.length} reporting dates, ${formatDate(dates[0])} to ${formatDate(dates.at(-1))}`;
}
