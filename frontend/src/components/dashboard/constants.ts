import type { BucketId } from '../../types';

/** Ordered worst to best, matching the workbook's Uptime Bucketization columns. */
export const BUCKET_ORDER: BucketId[] = ['lt_60', '60_90', '90_97', '97_98_5', 'gte_98_5'];

export const BUCKET_LABELS: Record<BucketId, string> = {
  lt_60: 'Below 60%',
  '60_90': '60% to <90%',
  '90_97': '90% to <97%',
  '97_98_5': '97% to <98.5%',
  gte_98_5: '98.5% and above',
};

// Sequential red to green so severity reads without the legend.
/** Colour of the "Below 98.5% — Total" aggregate (its buckets, counts and label come from the API). */
export const BELOW_985_COLOR = '#dc2626';

export const BUCKET_COLORS: Record<BucketId, string> = {
  lt_60: '#b91c1c',
  '60_90': '#ea580c',
  '90_97': '#ca8a04',
  '97_98_5': '#65a30d',
  gte_98_5: '#15803d',
};

export const REPORT_TYPE_COLORS: Record<string, string> = {
  '4G Saturation': 'var(--chart-1)',
  LWE: 'var(--chart-2)',
};

export const OVERALL_COLOR = 'var(--primary)';

export const reportTypeColor = (reportType: string) => REPORT_TYPE_COLORS[reportType] ?? 'var(--chart-4)';

export const AXIS_TICK = { fontSize: 11, fill: 'var(--muted-foreground)' };

/** Compact legend above the plot, so it never overlaps the lines. */
export const LEGEND_PROPS = { verticalAlign: 'top' as const, align: 'right' as const, height: 26, iconSize: 9, wrapperStyle: { fontSize: 11 } };
/** Small tooltip, offset from the cursor so it does not hide the hovered point. */
export const TOOLTIP_PROPS = {
  offset: 18,
  wrapperStyle: { zIndex: 20, outline: 'none' },
  contentStyle: { fontSize: 11, borderRadius: 6, padding: '4px 8px', lineHeight: 1.35 },
  itemStyle: { padding: 0 },
};
/** Colour of an uptime value: the workbook's bucket colour (same scale as the bucket charts). */
export function uptimeColor(pct: number): string {
  return pct >= 98.5 ? BUCKET_COLORS.gte_98_5 : pct >= 97 ? BUCKET_COLORS['97_98_5'] : pct >= 90 ? BUCKET_COLORS['90_97'] : pct >= 60 ? BUCKET_COLORS['60_90'] : BUCKET_COLORS.lt_60;
}

/** Uptime trend views on the Overview page. */
export type UptimeChartView = 'overall' | 'circles' | 'heatmap';
export const UPTIME_VIEWS: { value: UptimeChartView; label: string }[] = [
  { value: 'overall', label: 'Overall' },
  { value: 'circles', label: 'By circle' },
  { value: 'heatmap', label: 'Heatmap' },
];

/** Main Dashboard chart cards (via ChartCard's className): 12 px card padding and a tighter header gap than the shared default. */
/** Label of the months calculated from daily records (the other source's wording: context/sourceLabels). */
export const DAILY_LABEL = 'Calculated from daily records';

export const DENSE_CARD = 'gap-2.5 [--card-spacing:--spacing(3)]';
