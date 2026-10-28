import { Fragment } from 'react';
import { ChevronRight } from 'lucide-react';
import { cn } from '@/lib/utils';
import { formatPct } from '../../lib/format';
import { circleLabel, shortType } from '../../lib/circleSeries';
import type { CircleSeriesInfo } from '../../types';
import { BUCKET_COLORS, BUCKET_LABELS, BUCKET_ORDER, uptimeColor } from './constants';
import { DataTable } from './DataTable';

export interface HeatmapColumn {
  key: string;
  /** Short column label (e.g. "05" or "Wk-2"). */
  label: string;
  /** Full label for the hover text (e.g. "05 Oct 2026"). */
  title: string;
  /** Uptime % per circle key; null or missing = no data. */
  values: Record<string, number | null> | undefined;
}

const NO_DATA = 'repeating-linear-gradient(45deg, var(--muted), var(--muted) 3px, transparent 3px, transparent 6px)';

/** All circles (rows) by period (columns), coloured by the workbook's uptime buckets. Missing values are hatched, never 0. */
export function UptimeHeatmap({ circles, columns, onSelectCircle, caption }: {
  circles: CircleSeriesInfo[]; columns: HeatmapColumn[]; onSelectCircle?: (key: string) => void; caption: string;
}) {
  const types = [...new Set(circles.map((c) => c.report_type))];
  return (
    <>
      <div className="mb-2 flex flex-wrap items-center gap-x-3 gap-y-1 text-[11px] text-muted-foreground" aria-label="Colour scale">
        {[...BUCKET_ORDER].reverse().map((id) => (
          <span key={id} className="inline-flex items-center gap-1"><span className="size-2.5 rounded-sm" style={{ background: BUCKET_COLORS[id] }} aria-hidden="true" />{BUCKET_LABELS[id]}</span>
        ))}
        <span className="inline-flex items-center gap-1"><span className="size-2.5 rounded-sm border" style={{ background: NO_DATA }} aria-hidden="true" />No data</span>
      </div>
      <div className="overflow-x-auto rounded-md border" role="region" aria-label="Uptime heatmap" tabIndex={0}>
        <table className="border-separate border-spacing-0.5 text-[10px] tabular-nums">
          <caption className="sr-only">{caption}</caption>
          <thead>
            <tr>
              <th scope="col" className="sticky left-0 z-10 bg-card px-2 py-1 text-left text-[11px] font-medium text-muted-foreground">Circle</th>
              {columns.map((c) => <th key={c.key} scope="col" title={c.title} className="min-w-10 px-0.5 py-1 font-medium whitespace-nowrap text-muted-foreground">{c.label}</th>)}
            </tr>
          </thead>
          {types.map((type) => (
            <tbody key={type}>
              {types.length > 1 && (
                <tr><th colSpan={columns.length + 1} scope="rowgroup" className="sticky left-0 bg-card px-2 pt-1.5 text-left text-[10px] font-semibold tracking-wider text-muted-foreground uppercase">{shortType(type)}</th></tr>
              )}
              {circles.filter((c) => c.report_type === type).map((c, i) => (
                <Fragment key={c.key}>
                {/* A thin divider between circle rows (its own row, so it never overlaps the cells). */}
                {i > 0 && (
                  <tr aria-hidden="true">
                    <td colSpan={columns.length + 1} className="p-0"><div className="h-px bg-[#8b8c8e]" /></td>
                  </tr>
                )}
                <tr className={cn(onSelectCircle && 'group cursor-pointer')} onClick={() => onSelectCircle?.(c.key)}
                  tabIndex={onSelectCircle ? 0 : undefined} aria-label={onSelectCircle ? `${circleLabel(c.key)}: open its trend` : undefined}
                  onKeyDown={(e) => { if (onSelectCircle && (e.key === 'Enter' || e.key === ' ')) { e.preventDefault(); onSelectCircle(c.key); } }}>
                  <th scope="row" className="sticky left-0 z-10 bg-card px-2 py-0.5 text-left text-[11px] font-medium whitespace-nowrap group-hover:text-primary">
                    <span className="inline-flex items-center gap-1">{circleLabel(c.key)}{onSelectCircle && <ChevronRight className="size-3 opacity-0 group-hover:opacity-100" aria-hidden="true" />}</span>
                  </th>
                  {columns.map((col) => {
                    const v = col.values?.[c.key] ?? null;
                    return (
                      <td key={col.key} title={`${circleLabel(c.key)} · ${col.title}: ${v == null ? 'no data' : formatPct(v)}`}
                        className={cn('h-6 min-w-10 rounded-sm text-center', v == null ? 'text-muted-foreground' : 'font-medium text-white')}
                        style={{ background: v == null ? NO_DATA : uptimeColor(v) }}>
                        {v == null ? '' : v >= 99.95 ? '100' : v.toFixed(1)}
                      </td>
                    );
                  })}
                </tr>
                </Fragment>
              ))}
            </tbody>
          ))}
        </table>
      </div>
      <DataTable caption={caption} columns={['Circle', ...columns.map((c) => c.title)]}
        rows={circles.map((c) => [circleLabel(c.key), ...columns.map((col) => (col.values?.[c.key] == null ? 'No data' : formatPct(col.values[c.key])))])} />
    </>
  );
}
