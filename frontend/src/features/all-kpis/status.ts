/**
 * Display-only status colours of the All KPI's page. They use the existing thresholds (98.5% SLA, the "Below 60%"
 * bucket) and never change a value: green = meets the threshold, amber = below 98.5%, red = below 60%, neutral = no value.
 */
export type Tone = 'good' | 'warn' | 'bad' | 'neutral';

export const availabilityTone = (v: number | null | undefined): Tone => (v == null ? 'neutral' : v >= 98.5 ? 'good' : v >= 60 ? 'warn' : 'bad');
/** Reporting coverage: anything below 100% needs attention (missing values), never "critical". */
export const coverageTone = (v: number | null | undefined): Tone => (v == null ? 'neutral' : v >= 100 ? 'good' : 'warn');
/** A count of problem sites (e.g. NSLA, below 60%): neutral when zero or not available. */
export const problemTone = (v: number | null | undefined, tone: Tone = 'warn'): Tone => (!v ? 'neutral' : tone);

/** Accent strip of a KPI card. */
export const TONE_ACCENT: Record<Tone, string> = { good: 'bg-emerald-600', warn: 'bg-amber-500', bad: 'bg-red-600', neutral: 'bg-transparent' };
/** Text of a table value: only attention and critical values are coloured, so tables stay calm. */
export const TONE_TEXT: Record<Tone, string> = { good: '', warn: 'text-amber-700 font-medium', bad: 'text-red-700 font-medium', neutral: '' };
