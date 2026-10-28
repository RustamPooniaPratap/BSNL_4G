import { useState } from 'react';
import { Info } from 'lucide-react';
import { cn } from '@/lib/utils';
import { formatCompact, formatDate, formatMinutes, formatNumber, formatPct, formatShortDate } from '../../lib/format';
import type { BreakdownResponse } from '../../types';
import { ChartCard } from './ChartCard';
import { DataTable } from './DataTable';
import { reportTypeColor } from './constants';

interface CircleComparisonProps {
  breakdown: BreakdownResponse | null;
  loading: boolean;
  error: Error | null;
}

type Network = 'all' | '4G Saturation' | 'LWE';
type Metric = 'uptime' | 'outage';
const short = (t: string) => (t === '4G Saturation' ? '4G' : t);
const range = (start: string | null | undefined, end: string | null | undefined) => `${formatShortDate(start).slice(0, 2)}–${formatShortDate(end)}`;
const formatChange = (v: number | null) => (v == null ? '—' : `${v > 0 ? '+' : ''}${v.toFixed(2)} pts`);
const formatMinChange = (v: number | null) => (v == null ? '—' : `${v > 0 ? '+' : ''}${formatMinutes(v)}`);
/** Outage minutes per site in scope, so circles of different sizes compare fairly; null without data or sites. */
const perSite = (minutes: number | null | undefined, sites: number) => (minutes == null || sites <= 0 ? null : Math.round((minutes / sites) * 10) / 10);

/** 0 to a round maximum with four or five gridlines (steps of 1, 2 or 5 × 10^n). */
function outageTicks(max: number) {
  const top = Math.max(max, 1);
  const raw = top / 4;
  const magnitude = 10 ** Math.floor(Math.log10(raw));
  const step = [1, 2, 5, 10].map((m) => m * magnitude).find((s) => s >= raw)!;
  return Array.from({ length: Math.ceil(top / step) + 1 }, (_, i) => i * step);
}

/**
 * Month to date against the same elapsed days of the previous month, one row per circle (a dumbbell:
 * hollow dot = previous month, filled dot = this month), worst first.
 * - Uptime: MTD uptime, lowest first. The scale is at least 10 points wide with fixed 5-point gridlines,
 *   so a small change is not drawn as a large one.
 * - Outage: MTD outage minutes per site in scope, highest first, on a scale from 0.
 */
export function CircleComparison({ breakdown, loading, error }: CircleComparisonProps) {
  const [network, setNetwork] = useState<Network>('all');
  const [metric, setMetric] = useState<Metric>('uptime');
  const isOutage = metric === 'outage';
  const all = breakdown?.circles ?? [];
  const types = [...new Set(all.map((c) => c.report_type))];
  const circles = network === 'all' ? all : all.filter((c) => c.report_type === network);
  const comparison = breakdown?.comparison;
  const compare = Boolean(comparison?.available);
  const mtdLabel = breakdown ? `MTD ${range(breakdown.mtd_window.start, breakdown.mtd_window.end)}` : 'MTD';
  const prevLabel = compare && comparison ? `${comparison.label} ${range(comparison.start, comparison.end)}` : 'Same days last month';
  const rows = circles.map((c) => {
    const mtd = isOutage ? perSite(c.mtd_outage_minutes, c.sites_in_scope) : c.mtd_uptime_pct;
    const prev = !compare ? null : isOutage ? perSite(c.previous_outage_minutes, c.sites_in_scope) : c.previous_uptime_pct;
    const change = !compare ? null : isOutage ? (mtd != null && prev != null ? Math.round((mtd - prev) * 10) / 10 : null) : c.mtd_change_pts;
    return { key: `${c.report_type}|${c.circle}`, name: types.length > 1 ? `${c.circle} · ${short(c.report_type)}` : c.circle, type: c.report_type,
      mtd, prev, change, daily: c.daily_uptime_pct, sites: c.sites_in_scope, minutes: c.mtd_outage_minutes ?? null };
  });
  // Worst first; circles without a value go last.
  rows.sort((a, b) => (a.mtd == null ? 1 : 0) - (b.mtd == null ? 1 : 0)
    || (a.mtd == null || b.mtd == null ? 0 : isOutage ? b.mtd - a.mtd : a.mtd - b.mtd));
  const values = rows.flatMap((r) => [r.mtd, r.prev]).filter((v): v is number => v != null);
  let ticks: number[];
  let x: (v: number) => string;
  if (isOutage) {
    ticks = outageTicks(values.length ? Math.max(...values) : 0);
    const top = ticks.at(-1)!;
    x = (v) => `${(Math.min(Math.max(v, 0), top) / top) * 100}%`;
  } else {
    const min = values.length ? Math.min(...values) : 90;
    const lower = Math.min(90, Math.floor((min - 1) / 5) * 5);
    ticks = Array.from({ length: (100 - lower) / 5 + 1 }, (_, i) => lower + i * 5);
    x = (v) => `${((Math.max(lower, v) - lower) / (100 - lower)) * 100}%`;
  }
  const show = (v: number | null) => (isOutage ? formatMinutes(v) : formatPct(v));
  const tick = (v: number) => (isOutage ? formatCompact(v) : `${v}%`);
  const what = isOutage ? 'MTD outage minutes per site' : 'MTD uptime';
  const order = isOutage ? 'highest first' : 'lowest first';

  return (
    <ChartCard
      title="Circle comparison"
      description={compare && comparison
        ? `${what} against the same days of ${comparison.label} (${prevLabel}), ${order}.`
        : `${what} by circle, ${order} (${formatDate(breakdown?.reporting_date)}).`}
      action={(
        <div className="flex flex-wrap items-center justify-end gap-2">
          <Segmented label="Measure" value={metric} onChange={setMetric} options={[['uptime', 'Uptime'], ['outage', 'Outage']]} />
          {types.length > 1 && (
            <Segmented label="Network" value={network} onChange={setNetwork}
              options={(['all', ...types] as Network[]).map((n): [Network, string] => [n, n === 'all' ? 'All' : short(n)])} />
          )}
        </div>
      )}
      loading={loading}
      error={error}
      empty={!rows.length}
    >
      {!compare && comparison && (
        <p className="mb-3 flex items-start gap-1.5 rounded-md bg-muted/60 px-3 py-2 text-xs text-muted-foreground">
          <Info className="mt-px size-3.5 shrink-0" aria-hidden="true" />
          The comparison with the same days of {comparison.label} appears once its daily outage values are available in the data source.
        </p>
      )}
      <div className="mb-1 flex items-center gap-3 text-[11px] text-muted-foreground" aria-hidden="true">
        {compare && <span className="inline-flex items-center gap-1"><span className="size-2.5 rounded-full border-2 border-muted-foreground bg-card" />{prevLabel}</span>}
        <span className="inline-flex items-center gap-1"><span className="size-2.5 rounded-full bg-foreground" />{mtdLabel}</span>
      </div>
      <div role="img" aria-label={`Dot chart of ${what} by circle${compare ? ` against the same days of ${comparison?.label}` : ''}`}>
        <div className="grid grid-cols-[4.5rem_1fr_5.5rem] items-center gap-x-2 text-[10px] text-muted-foreground">
          <span />
          <div className="relative h-4">
            {ticks.map((t) => <span key={t} className="absolute -translate-x-1/2" style={{ left: x(t) }}>{tick(t)}</span>)}
          </div>
          <span />
        </div>
        {rows.map((r) => {
          const color = reportTypeColor(r.type);
          const title = `${r.name}: MTD ${show(r.mtd)}${isOutage ? ' per site' : ''}${compare ? `, ${comparison?.label} ${show(r.prev)}, change ${isOutage ? formatMinChange(r.change) : formatChange(r.change)}` : ''} · ${formatNumber(r.sites)} sites`;
          // Better is up for uptime, down for outage.
          const better = r.change == null || r.change === 0 ? null : isOutage ? r.change < 0 : r.change > 0;
          return (
            <div key={r.key} className="grid grid-cols-[4.5rem_1fr_5.5rem] items-center gap-x-2 py-0.5 hover:bg-muted/40" title={title}>
              <span className="truncate text-xs font-medium">{r.name}</span>
              <div className="relative h-5">
                {ticks.map((t) => <span key={t} className="absolute inset-y-0 border-l border-dashed border-border" style={{ left: x(t) }} aria-hidden="true" />)}
                {r.mtd != null && r.prev != null && (
                  <span className="absolute top-1/2 h-0.5 -translate-y-1/2 rounded bg-muted-foreground/40"
                    style={{ left: x(Math.min(r.mtd, r.prev)), width: `calc(${x(Math.max(r.mtd, r.prev))} - ${x(Math.min(r.mtd, r.prev))})` }} />
                )}
                {r.prev != null && <span className="absolute top-1/2 size-2.5 -translate-x-1/2 -translate-y-1/2 rounded-full border-2 border-muted-foreground bg-card" style={{ left: x(r.prev) }} />}
                {r.mtd != null && <span className="absolute top-1/2 size-3 -translate-x-1/2 -translate-y-1/2 rounded-full ring-2 ring-card" style={{ left: x(r.mtd), background: color }} />}
              </div>
              <span className="text-right text-xs tabular-nums">
                {r.mtd == null ? <span className="text-muted-foreground">No data</span> : show(r.mtd)}
                {r.change != null && (
                  <span className={cn('ml-1 text-[10px]', better === true ? 'text-emerald-700' : better === false ? 'text-destructive' : 'text-muted-foreground')}>
                    {r.change > 0 ? '▲' : r.change < 0 ? '▼' : ''}{isOutage ? formatNumber(Math.abs(r.change)) : Math.abs(r.change).toFixed(1)}
                  </span>
                )}
              </span>
            </div>
          );
        })}
      </div>
      {isOutage ? (
        <DataTable
          caption="Outage minutes by circle"
          columns={['Circle', 'Sites in scope', `Outage ${mtdLabel}`, `Per site ${mtdLabel}`, ...(compare ? [`Per site ${prevLabel}`, 'Change'] : [])]}
          rows={rows.map((r) => [r.name, formatNumber(r.sites), formatMinutes(r.minutes), formatMinutes(r.mtd),
            ...(compare ? [formatMinutes(r.prev), formatMinChange(r.change)] : [])])}
        />
      ) : (
        <DataTable
          caption="Uptime by circle"
          columns={compare ? ['Circle', 'Sites in scope', mtdLabel, prevLabel, 'Change', 'Daily uptime'] : ['Circle', 'Sites in scope', mtdLabel, 'Daily uptime']}
          rows={rows.map((r) => (compare
            ? [r.name, formatNumber(r.sites), formatPct(r.mtd), formatPct(r.prev), formatChange(r.change), formatPct(r.daily)]
            : [r.name, formatNumber(r.sites), formatPct(r.mtd), formatPct(r.daily)]))}
        />
      )}
    </ChartCard>
  );
}

function Segmented<T extends string>({ value, onChange, options, label }: { value: T; onChange: (v: T) => void; options: [T, string][]; label: string }) {
  return (
    <div className="inline-flex rounded-lg border p-0.5" role="group" aria-label={label}>
      {options.map(([v, text]) => (
        <button key={v} type="button" aria-pressed={value === v} onClick={() => onChange(v)}
          className={cn('rounded-md px-2.5 py-1 text-xs font-medium', value === v ? 'bg-primary text-primary-foreground' : 'text-muted-foreground hover:text-foreground')}>
          {text}
        </button>
      ))}
    </div>
  );
}
