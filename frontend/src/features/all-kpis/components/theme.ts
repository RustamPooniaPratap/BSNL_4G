import type { Tone } from '../status';

/** Availability status against the existing thresholds (status.ts): the label names the threshold, nothing else. */
export const AVAILABILITY_STATUS: Record<Tone, string> = { good: 'Meets 98.5%', warn: 'Below 98.5%', bad: 'Below 60%', neutral: 'No value' };

/** Recharts styling of the reference (flat, ink tooltip, light grid). */
export const CHART = {
  accent: 'var(--akp-accent)', crit: 'var(--akp-crit)', warn: 'var(--akp-warn)', grid: 'var(--akp-grid)', ink2: 'var(--akp-ink2)',
  tick: { fontSize: 11, fill: 'var(--akp-ink2)' },
  tooltip: {
    offset: 16,
    wrapperStyle: { zIndex: 20, outline: 'none' },
    contentStyle: { background: 'var(--akp-ink)', border: 0, borderRadius: 6, padding: '6px 9px', fontSize: 12, lineHeight: 1.4 },
    labelStyle: { color: 'var(--akp-surface)', fontWeight: 600, marginBottom: 2 },
    itemStyle: { color: 'var(--akp-surface)', padding: 0 },
  },
  legend: { verticalAlign: 'top' as const, align: 'right' as const, height: 26, iconSize: 9, wrapperStyle: { fontSize: 11.5, color: 'var(--akp-ink2)' } },
};
