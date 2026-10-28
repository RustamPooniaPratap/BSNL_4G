import { formatDate, formatNumber } from './format';

export const ALL = 'all';
/** URL parameters shared by the RCA Register and Summary (so a filtered view can be refreshed or shared). */
export const FILTER_KEYS = ['date_from', 'date_to', 'project', 'circle', 'final_bucket', 'bucket_2', 'category', 'rca', 'status', 'q'] as const;
export type FilterKey = (typeof FILTER_KEYS)[number];

export const NOT_RECORDED = 'Not recorded';
export const shortProject = (p: string) => (p === '4G Saturation' ? '4G' : p);
/** Outage minutes, or "Not recorded" when the source has no value (never 0). */
export const formatMin = (v: number | null | undefined) => (v == null ? NOT_RECORDED : `${formatNumber(Math.round(v))} min`);

/** A reporting period: one date, or "first – last". */
export const periodText = (start: string | null, end: string | null) =>
  !start ? '—' : !end || end === start ? formatDate(start) : `${formatDate(start)} – ${formatDate(end)}`;
