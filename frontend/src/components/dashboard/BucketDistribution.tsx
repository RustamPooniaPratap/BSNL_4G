import { useState } from 'react';
import { Bar, BarChart, CartesianGrid, Legend, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts';
import { cn } from '@/lib/utils';
import { formatDate, formatNumber } from '../../lib/format';
import type { BreakdownResponse, BucketId } from '../../types';
import { ChartCard } from './ChartCard';
import { DataTable } from './DataTable';
import { AXIS_TICK, BUCKET_COLORS, BUCKET_LABELS, BUCKET_ORDER } from './constants';

interface BucketDistributionProps {
  breakdown: BreakdownResponse | null;
  loading: boolean;
  error: Error | null;
  onSelectBucket: (bucket: BucketId) => void;
}

type Mode = 'mtd' | 'day';

export function BucketDistribution({ breakdown, loading, error, onSelectBucket }: BucketDistributionProps) {
  const [mode, setMode] = useState<Mode>('mtd');
  const circles = breakdown?.circles ?? [];
  const split = new Set(circles.map((c) => c.report_type)).size > 1;
  const countsFor = (c: (typeof circles)[number]) => (mode === 'mtd' ? c.buckets : c.daily_buckets);
  const data = circles.map((c) => ({
    name: split ? `${c.circle} · ${c.report_type === '4G Saturation' ? '4G' : c.report_type}` : c.circle,
    ...Object.fromEntries(BUCKET_ORDER.map((b) => [BUCKET_LABELS[b], countsFor(c)[b]])),
  }));
  const totals = (mode === 'mtd' ? breakdown?.buckets : breakdown?.daily_buckets) ?? [];
  const total = totals.reduce((sum, b) => sum + b.count, 0);

  return (
    <ChartCard
      title="Site uptime buckets"
      description={mode === 'mtd'
        ? "Sites grouped by month-to-date uptime, using the workbook's bucket thresholds. Select a bucket to list its sites."
        : `Sites grouped by their uptime on ${formatDate(breakdown?.reporting_date)}, using the same thresholds.`}
      action={
        <div className="inline-flex rounded-lg border p-0.5" role="group" aria-label="Bucket period">
          {(['mtd', 'day'] as Mode[]).map((m) => (
            <button key={m} type="button" aria-pressed={mode === m} onClick={() => setMode(m)}
              className={cn('rounded-md px-2.5 py-1 text-xs font-medium transition-colors focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none',
                mode === m ? 'bg-primary text-primary-foreground' : 'text-muted-foreground hover:text-foreground')}>
              {m === 'mtd' ? 'Month to date' : 'Selected day'}
            </button>
          ))}
        </div>
      }
      loading={loading}
      error={error}
      empty={!total}
    >
      <ul className="mb-3 grid grid-cols-5 gap-1.5" aria-label="Sites per bucket">
        {totals.map((b) => (
          <li key={b.id}>
            <button
              type="button"
              onClick={() => onSelectBucket(b.id)}
              disabled={mode !== 'mtd'}
              className="w-full rounded-md border px-2 py-1.5 text-left transition-colors enabled:hover:bg-muted focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none disabled:cursor-default"
              title={mode === 'mtd' ? `Show ${BUCKET_LABELS[b.id]} sites in the table` : undefined}
            >
              <span className="flex items-center gap-1.5 text-[11px] text-muted-foreground">
                <span className="size-2 shrink-0 rounded-full" style={{ background: BUCKET_COLORS[b.id] }} aria-hidden="true" />
                <span className="truncate">{BUCKET_LABELS[b.id]}</span>
              </span>
              <span className="block text-sm font-semibold tabular-nums">{formatNumber(b.count)}</span>
            </button>
          </li>
        ))}
      </ul>
      <div className="w-full" style={{ height: Math.max(160, data.length * 28 + 56) }} role="img" aria-label="Stacked bar chart of site uptime buckets by circle">
        <ResponsiveContainer width="100%" height="100%">
          <BarChart data={data} layout="vertical" stackOffset="expand" margin={{ top: 0, right: 12, bottom: 0, left: 4 }}>
            <CartesianGrid strokeDasharray="3 3" horizontal={false} stroke="var(--border)" />
            <XAxis type="number" tickFormatter={(v: number) => `${Math.round(v * 100)}%`} tick={AXIS_TICK} tickLine={false} axisLine={false} />
            <YAxis type="category" dataKey="name" tick={AXIS_TICK} tickLine={false} axisLine={false} width={split ? 72 : 36} />
            <Tooltip formatter={(value) => `${formatNumber(Number(value))} sites`} contentStyle={{ fontSize: 12, borderRadius: 8 }} cursor={{ fill: 'var(--muted)' }} />
            <Legend itemSorter={null} wrapperStyle={{ fontSize: 11 }} />
            {BUCKET_ORDER.map((b) => (
              <Bar isAnimationActive={false} key={b} dataKey={BUCKET_LABELS[b]} stackId="buckets" fill={BUCKET_COLORS[b]} barSize={14} />
            ))}
          </BarChart>
        </ResponsiveContainer>
      </div>
      <DataTable
        caption="Sites per uptime bucket by circle"
        columns={['Circle', ...BUCKET_ORDER.map((b) => BUCKET_LABELS[b])]}
        rows={circles.map((c, i) => [data[i].name, ...BUCKET_ORDER.map((b) => formatNumber(countsFor(c)[b]))])}
      />
    </ChartCard>
  );
}
