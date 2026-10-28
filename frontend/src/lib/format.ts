const dateFormatter = new Intl.DateTimeFormat('en-IN', { day: '2-digit', month: 'short', year: 'numeric' });
const shortDateFormatter = new Intl.DateTimeFormat('en-IN', { day: '2-digit', month: 'short' });
const dateTimeFormatter = new Intl.DateTimeFormat('en-IN', {
  day: '2-digit', month: 'short', year: 'numeric', hour: '2-digit', minute: '2-digit',
});
const integerFormatter = new Intl.NumberFormat('en-IN', { maximumFractionDigits: 0 });
// Indian compact notation for chart axes, e.g. 6,56,925 -> "6.6L".
const compactFormatter = new Intl.NumberFormat('en-IN', { notation: 'compact', maximumFractionDigits: 1 });

/** Parse an ISO date (YYYY-MM-DD) as a local calendar date, avoiding UTC shifts. */
const toDate = (iso: string) => new Date(`${iso.slice(0, 10)}T00:00:00`);

export const formatPct = (value: number | null | undefined, digits = 2) =>
  value == null ? '—' : `${value.toFixed(digits)}%`;

export const formatNumber = (value: number | null | undefined) =>
  value == null ? '—' : integerFormatter.format(value);

export const formatDate = (iso: string | null | undefined) => (iso ? dateFormatter.format(toDate(iso)) : '—');

export const formatShortDate = (iso: string | null | undefined) => (iso ? shortDateFormatter.format(toDate(iso)) : '—');

export const formatDateTime = (iso: string | null | undefined) => (iso ? dateTimeFormatter.format(new Date(iso)) : '—');

export const formatMinutes = (minutes: number | null | undefined) =>
  minutes == null ? '—' : `${integerFormatter.format(minutes)} min`;

export const formatCompact = (value: number | null | undefined) => (value == null ? '—' : compactFormatter.format(value));
