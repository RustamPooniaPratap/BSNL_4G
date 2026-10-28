import { useState } from 'react';
import { ArrowDownRight, ArrowUpRight, ChevronRight, Minus, TriangleAlert } from 'lucide-react';
import { CartesianGrid, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table';
import { cn } from '@/lib/utils';
import { formatNumber, formatPct, formatShortDate } from '../../lib/format';
import { rangeLabel } from '../../lib/periods';
import type { BucketId, ThresholdBucket, ThresholdCompared, ThresholdMonthlyColumn, ThresholdResponse } from '../../types';
import { AXIS_TICK, BELOW_985_COLOR, BUCKET_COLORS } from './constants';

type Mode = 'count' | 'pct';
const BELOW = 'below_98_5' as const;
type RowId = ThresholdCompared;

/** Whether a rise is good (true), bad (false) or neither (null) — for colouring changes only. */
const RISE_IS_GOOD: Record<RowId, boolean | null> = {
  below_98_5: false, lt_60: false, '60_90': null, '90_97': null, '97_98_5': null, gte_98_5: true, no_value: null,
};

/** The exact rule, from the workbook's Bucket formula: lower bound inclusive, upper bound exclusive. */
const rangeText = (b: ThresholdBucket) => (b.lower == null ? `uptime < ${b.upper}%`
  : b.upper == null ? `uptime ≥ ${b.lower}%` : `${b.lower}% ≤ uptime < ${b.upper}%`);

/** The column's count or share for a row, as returned by the API; null when the column has no data. */
const value = (column: ThresholdMonthlyColumn, id: RowId, mode: Mode) =>
  (column.values ? column.values[id][mode === 'count' ? 'count' : 'pct'] : null);
const show = (v: number | null, mode: Mode) => (v == null ? '—' : mode === 'count' ? formatNumber(v) : formatPct(v, 1));
const dates = (c: ThresholdMonthlyColumn) => (c.kind === 'month' ? 'full month'
  : c.kind === 'mtd' ? `${formatShortDate(c.start)}–${formatShortDate(c.end)}` : rangeLabel(c.start, c.end).replace(/ \d{4}$/, ''));

function Change({ value: v, unit, good }: { value: number | null | undefined; unit: 'sites' | 'pts'; good: boolean | null }) {
  if (v == null) return <span className="text-muted-foreground">—</span>;
  const Icon = v > 0 ? ArrowUpRight : v < 0 ? ArrowDownRight : Minus;
  const better = good == null || v === 0 ? null : (v > 0) === good;
  return (
    <span className={cn('inline-flex items-center justify-end gap-0.5 tabular-nums', better === true && 'text-emerald-700', better === false && 'text-destructive')}>
      <Icon className="size-3.5" aria-hidden="true" />
      {v > 0 ? '+' : ''}{unit === 'pts' ? `${v.toFixed(2)} pts` : formatNumber(v)}
    </span>
  );
}

/**
 * Uptime Threshold Analysis & Monthly Comparison: one table with, per bucket, the full months found in the source,
 * the previous month's matching elapsed days, the month to date, both MTD shares and the MTD-vs-MTD change, and an
 * Analyse action. Every figure (including the aggregate, the no-value counts and the changes) comes from the backend
 * (`thresholds/` → monthly_comparison); a period the source cannot provide is shown as not available, never estimated.
 * Selecting a row draws its line chart; Analyse opens the bucket's detailed analysis.
 */
export function UnifiedThresholdTable({ data, mode, scopeLabel, onAnalyse }: {
  data: ThresholdResponse; mode: Mode; scopeLabel: string; onAnalyse: (id: BucketId) => void;
}) {
  const [selected, setSelected] = useState<RowId | null>(null);
  const { columns, mtd_comparison: compared, elapsed_days: elapsed } = data.monthly_comparison;
  const months = columns.filter((c) => c.kind === 'month');
  const previous = columns.find((c) => c.kind === 'previous_mtd') ?? null;
  const current = columns.find((c) => c.kind === 'mtd') ?? null;
  const periodColumns = [...months, ...(previous ? [previous] : []), ...(current ? [current] : [])];
  const unavailable = columns.filter((c) => c.status === 'missing');
  const reported = compared.sites_reported;
  const populationsDiffer = compared.available && reported.current != null && reported.previous != null && reported.current !== reported.previous;
  const unit = mode === 'count' ? 'Sites' : '% of sites in scope';
  // The threshold rule of each row is its tooltip (no separate description column).
  const rows: { id: RowId; label: string; description: string; color: string; bucket?: ThresholdBucket }[] = [
    { id: BELOW, label: data.penalty.label, description: 'Sum of the four buckets below 98.5% (not a separate bucket)', color: BELOW_985_COLOR },
    ...data.buckets.map((b) => ({ id: b.id, label: b.label, description: rangeText(b), color: BUCKET_COLORS[b.id], bucket: b })),
  ];
  const chartRow = rows.find((r) => r.id === selected) ?? null;
  const points = periodColumns.map((c) => ({ label: c.label, range: rangeLabel(c.start, c.end), value: selected ? value(c, selected, mode) : null }));
  const prevLabel = previous ? `${previous.label} ${dates(previous)}` : 'previous month';
  const curLabel = current ? `${current.label} ${dates(current)}` : 'month to date';
  const sticky = 'sticky left-0 z-10 bg-card';

  const periodCells = (id: RowId, emphasis?: string) => periodColumns.map((c) => (
    <TableCell key={c.key} className={cn('text-right tabular-nums', c.kind === 'mtd' && 'bg-primary/5 font-semibold', c.kind === 'previous_mtd' && 'border-l', emphasis)}
      title={c.values ? rangeLabel(c.start, c.end) : c.reason ?? undefined}>
      {show(value(c, id, mode), mode)}
    </TableCell>
  ));
  const comparisonCells = (id: RowId, emphasis?: string) => {
    const c = compared.values[id];
    return (
      <>
        <TableCell className={cn('border-l text-right tabular-nums', emphasis)}>{c ? formatPct(c.pct, 2) : '—'}</TableCell>
        <TableCell className="text-right tabular-nums text-muted-foreground">{c ? formatPct(c.compare_pct, 2) : '—'}</TableCell>
        <TableCell className="text-right"><Change value={c?.change} unit="sites" good={RISE_IS_GOOD[id]} /></TableCell>
      </>
    );
  };

  return (
    <Card role="region" aria-label="Uptime threshold analysis and monthly comparison">
      <CardHeader>
        <CardTitle className="text-sm font-semibold">Uptime Threshold Analysis &amp; Monthly Comparison</CardTitle>
        <CardDescription className="text-[11px]">
          Full months: monthly totals · MTD: days 1–{elapsed} of each month · % of {formatNumber(data.total.sites_in_scope)} {scopeLabel}
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-3 px-0">
        {populationsDiffer && (
          <p className="mx-4 flex items-start gap-1.5 rounded-md bg-amber-50 px-3 py-2 text-xs text-amber-900" role="note">
            <TriangleAlert className="mt-px size-3.5 shrink-0" aria-hidden="true" />
            {formatNumber(reported.current!)} sites reported in {curLabel} but {formatNumber(reported.previous!)} in {prevLabel} (no daily data for the
            others), so the MTD change covers different populations. Filter by project to compare like with like.
          </p>
        )}
        <div className="overflow-x-auto">
          <Table className="text-xs">
            <TableHeader>
              <TableRow className="bg-muted/50 hover:bg-muted/50">
                <TableHead className={cn(sticky, 'bg-muted pl-4')}>Uptime bucket</TableHead>
                {periodColumns.map((c) => (
                  <TableHead key={c.key} className={cn('text-right', c.kind === 'mtd' && 'bg-primary/5', c.kind === 'previous_mtd' && 'border-l')} title={rangeLabel(c.start, c.end)}>
                    <span className="block font-semibold text-foreground">{c.label}</span>
                    <span className="block text-[10px] font-normal">{dates(c)}</span>
                  </TableHead>
                ))}
                <TableHead className="border-l text-right"><span className="block font-semibold text-foreground">% · {current?.label ?? 'MTD'}</span><span className="block text-[10px] font-normal">of sites in scope</span></TableHead>
                <TableHead className="text-right"><span className="block font-semibold text-foreground">% · {previous?.label ?? 'previous MTD'}</span><span className="block text-[10px] font-normal">of sites in scope</span></TableHead>
                <TableHead className="text-right"><span className="block font-semibold text-foreground">Change</span><span className="block text-[10px] font-normal">sites, MTD vs MTD</span></TableHead>
                <TableHead className="w-8 pr-3"><span className="sr-only">Analyse</span></TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {rows.map((r) => {
                const aggregate = r.id === BELOW;
                const critical = r.id === 'lt_60';
                const red = aggregate ? 'text-red-700' : undefined;
                return (
                  <TableRow key={r.id} tabIndex={0} aria-selected={selected === r.id} aria-label={`${r.label}: show line chart`}
                    className={cn('cursor-pointer', aggregate && 'border-b-2 bg-red-50/70 hover:bg-red-50', selected === r.id && (aggregate ? 'bg-red-100/70' : 'bg-primary/5'))}
                    onClick={() => setSelected(r.id)}
                    onKeyDown={(e) => { if (e.target === e.currentTarget && (e.key === 'Enter' || e.key === ' ')) { e.preventDefault(); setSelected(r.id); } }}>
                    <TableCell className={cn(sticky, 'pl-4', aggregate && 'bg-red-50')} title={r.description}>
                      <span className="flex items-center gap-2 whitespace-nowrap">
                        <span className={cn('size-2.5 shrink-0', aggregate ? 'rounded-sm' : 'rounded-full')} style={{ background: r.color }} aria-hidden="true" />
                        <span className={cn('font-medium', (aggregate || critical) && 'font-semibold text-red-700')}>{r.label}</span>
                      </span>
                    </TableCell>
                    {periodCells(r.id, cn(red, aggregate && 'font-semibold'))}
                    {comparisonCells(r.id, cn(red, aggregate && 'font-semibold'))}
                    <TableCell className="w-8 py-1 pr-3 text-right">
                      {r.bucket && (
                        <button type="button" title={`Analyse ${r.label}`} aria-label={`Analyse ${r.label}`}
                          className="inline-flex size-6 items-center justify-center rounded-md text-primary hover:bg-primary/10 focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none"
                          onClick={(e) => { e.stopPropagation(); onAnalyse(r.bucket!.id); }}>
                          <ChevronRight className="size-4" aria-hidden="true" />
                        </button>
                      )}
                    </TableCell>
                  </TableRow>
                );
              })}
            </TableBody>
          </Table>
        </div>
        {unavailable.length > 0 && (
          <ul className="px-4 text-xs text-muted-foreground" aria-label="Unavailable columns">
            {unavailable.map((c) => <li key={c.key}><strong className="font-medium text-foreground">{c.label}:</strong> {c.reason}</li>)}
          </ul>
        )}
        {chartRow ? (
          <div className="px-4" role="region" aria-label={`${chartRow.label} by month`}>
            <p className="mb-2 text-xs font-medium">{chartRow.label} · {unit}</p>
            <div className="h-56" role="img" aria-label={`Line chart of ${chartRow.label}, ${unit.toLowerCase()}, by month`}>
              <ResponsiveContainer width="100%" height="100%">
                <LineChart data={points} margin={{ top: 8, right: 16, bottom: 0, left: 0 }}>
                  <CartesianGrid strokeDasharray="3 3" vertical={false} stroke="var(--border)" />
                  <XAxis dataKey="label" tick={AXIS_TICK} tickLine={false} axisLine={false} />
                  <YAxis tick={AXIS_TICK} tickLine={false} axisLine={false} width={56}
                    tickFormatter={(v: number) => (mode === 'count' ? formatNumber(v) : `${v}%`)}
                    label={{ value: unit, angle: -90, position: 'insideLeft', style: { fontSize: 11, fill: 'var(--muted-foreground)' } }} />
                  <Tooltip contentStyle={{ fontSize: 12, borderRadius: 8 }}
                    labelFormatter={(_, payload) => { const p = payload?.[0]?.payload as { label: string; range: string } | undefined; return p ? `${p.label} · ${p.range}` : ''; }}
                    formatter={(v) => [v == null ? 'Not available' : show(Number(v), mode), chartRow.label]} />
                  <Line isAnimationActive={false} type="linear" dataKey="value" stroke={chartRow.color} strokeWidth={2.25} dot={{ r: 3 }} connectNulls={false} />
                </LineChart>
              </ResponsiveContainer>
            </div>
            {points.some((p) => p.value == null) && <p className="mt-1 text-[11px] text-muted-foreground">Gaps are periods without data; they are not drawn as zero.</p>}
          </div>
        ) : <p className="px-4 text-xs text-muted-foreground">Select an uptime bucket above to see its line chart.</p>}
      </CardContent>
    </Card>
  );
}
