import { useState } from 'react';
import { Bar, BarChart, CartesianGrid, Cell, LabelList, Legend, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts';
import { cn } from '@/lib/utils';
import { pickWeeks, type TrendView } from '../../hooks/useDashboardFilters';
import { circleLabel } from '../../lib/circleSeries';
import { formatCompact, formatDate, formatMinutes, formatNumber, formatShortDate } from '../../lib/format';
import type { MonthlyResponse, TrendResponse } from '../../types';
import { ChartCard } from './ChartCard';
import { DataTable } from './DataTable';
import { AXIS_TICK, DENSE_CARD, LEGEND_PROPS, OVERALL_COLOR, TOOLTIP_PROPS, reportTypeColor } from './constants';
import { useSourceLabels } from '../../context/sourceLabels';
import { SOURCE_LABEL_MARGIN, SourceMarks, SourceNote } from './SourceMarks';
import { isHistorical, monthKind, type MonthKind } from '../../lib/monthlyHistory';
import { TrendViewSwitch } from './TrendChart';

const COMBINED = 'Combined';
export type OutageChartView = 'overall' | 'circles';

interface OutageChartProps {
  /** Daily series (already limited to picked dates) and the workbook weeks. */
  trend: TrendResponse | null;
  monthly: MonthlyResponse | null;
  loading: boolean;
  monthlyLoading: boolean;
  error: Error | null;
  monthlyError: Error | null;
  view: TrendView;
  onViewChange: (view: TrendView) => void;
  weekList: number[];
  /** Hand-picked dates need not be consecutive: draw straight segments between them. */
  picked?: boolean;
  scopeLabel: string;
  /** Overall trend lines, or circles ranked by outage per site. */
  outageView?: OutageChartView;
  onOutageViewChange?: (view: OutageChartView) => void;
}

interface Point {
  label: string;
  tooltip: string;
  /** Monthly view: a month of imported historical totals (Excel source). */
  historical?: boolean;
  /** Monthly view: historical, calculated from daily records, or an empty gap month. */
  kind?: MonthKind;
  total: number | null;
  byType: Record<string, number | null>;
  byCircle: Record<string, number | null> | undefined;
}

/** Outage minutes for the same period as the uptime trend: per network over time, or circles ranked per site. */
export function OutageChart(props: OutageChartProps) {
  const { trend, monthly, view, scopeLabel, outageView = 'overall' } = props;
  const [showCombined, setShowCombined] = useState(false);
  const isMonthly = view === 'monthly';
  const sourceLabels = useSourceLabels();
  const types = (isMonthly ? monthly?.report_types : trend?.report_types) ?? [];

  let points: Point[];
  if (view === 'daily') {
    points = (trend?.series ?? []).map((p) => ({
      label: formatShortDate(p.date), tooltip: formatDate(p.date), total: p.outage_minutes, byType: p.outage_by_report_type, byCircle: p.outage_by_circle,
    }));
  } else if (view === 'weekly') {
    points = pickWeeks(trend?.weeks ?? [], props.weekList).map((w) => ({
      label: w.label,
      tooltip: `${w.label} (${formatShortDate(w.start)}–${formatShortDate(w.end)})` + (w.days_reported && w.days_reported < w.days_in_week ? `, ${w.days_reported} of ${w.days_in_week} days` : ''),
      total: w.outage_minutes, byType: w.outage_by_report_type, byCircle: w.outage_by_circle,
    }));
  } else {
    points = (monthly?.months ?? []).map((m) => ({
      label: m.label, tooltip: m.partial ? `${m.label} (${m.days} days)` : m.gap ? `${m.label} · No data` : isHistorical(m) ? `${m.label} · ${sourceLabels.history}` : m.label,
      historical: isHistorical(m), kind: monthKind(m), total: m.outage_minutes, byType: m.outage_by_report_type, byCircle: m.outage_by_circle,
    }));
  }
  const period = points.length ? `${points[0].tooltip} – ${points.at(-1)!.tooltip}` : '';

  const controls = (
    <div className="flex flex-wrap items-center justify-end gap-2">
      {props.onOutageViewChange && (
        <Segmented label="Outage chart" value={outageView} onChange={props.onOutageViewChange}
          options={[['overall', 'Overall'], ['circles', 'By circle']]} />
      )}
      <TrendViewSwitch view={view} onChange={props.onViewChange} label="Outage period" />
    </div>
  );

  return (
    <ChartCard className={DENSE_CARD}
      title="Outage minutes"
      description={outageView === 'circles'
        ? `${scopeLabel}: outage minutes per site in scope, ${period}, highest first. Per site, so circles of different sizes compare fairly.`
        : `${scopeLabel}, outage minutes per ${isMonthly ? 'month (the last point is the month to date)' : view === 'weekly' ? 'workbook week (reported days only)' : 'reporting date'}.`}
      action={controls}
      loading={isMonthly ? props.monthlyLoading : props.loading}
      error={isMonthly ? props.monthlyError : props.error}
      empty={!points.some((p) => p.total != null)}
      emptyMessage="No outage data reported for this period."
    >
      {outageView === 'circles'
        // Per site of today's scope: only the months calculated from daily records (historical totals cover other site sets).
        ? <CircleOutage points={points.filter((p) => !p.historical && p.kind !== 'gap')} circles={(isMonthly ? monthly?.circles : trend?.circles) ?? []} period={period} />
        : <OverallOutage points={points} types={types} view={view} picked={props.picked} showCombined={showCombined} onShowCombined={setShowCombined} />}
    </ChartCard>
  );
}

function OverallOutage({ points, types, view, picked, showCombined, onShowCombined }: {
  points: Point[]; types: string[]; view: TrendView; picked?: boolean; showCombined: boolean; onShowCombined: (v: boolean) => void;
}) {
  const { annotate } = useSourceLabels();
  const isMonthly = view === 'monthly';
  const split = types.length > 1;
  // 4G and LWE always; the combined total only when asked for (it dwarfs the two networks).
  const keys = split && showCombined ? [COMBINED, ...types] : types;
  const data = points.map((p) => ({
    label: p.label, tooltip: p.tooltip, [COMBINED]: round(p.total), ...Object.fromEntries(types.map((t) => [t, round(p.byType?.[t])])),
  }));
  const curve = picked && view === 'daily' ? 'linear' : 'monotone';
  return (
    <>
      {split && (
        <label className="mb-1 inline-flex items-center gap-1.5 text-xs text-muted-foreground">
          <input type="checkbox" className="size-3.5 accent-primary" checked={showCombined} onChange={(e) => onShowCombined(e.target.checked)} />
          Show combined total
        </label>
      )}
      <div className="h-[clamp(208px,28vh,256px)]" role="img" aria-label={`Line chart of ${view} outage minutes`}>
        <ResponsiveContainer width="100%" height="100%">
          <LineChart data={data} margin={{ top: isMonthly && annotate && points.some((p) => p.historical) ? SOURCE_LABEL_MARGIN : 4, right: 12, bottom: 0, left: -4 }}>
            <CartesianGrid strokeDasharray="3 3" vertical={false} stroke="var(--border)" />
            <XAxis dataKey="label" tick={AXIS_TICK} tickLine={false} axisLine={false}
              minTickGap={isMonthly ? 0 : 16} interval={isMonthly ? 0 : undefined}
              angle={isMonthly ? -30 : 0} textAnchor={isMonthly ? 'end' : 'middle'} height={isMonthly ? 52 : 24} />
            <YAxis tick={AXIS_TICK} tickLine={false} axisLine={false} width={48} tickFormatter={(v: number) => formatCompact(v)} />
            <Tooltip {...TOOLTIP_PROPS} labelFormatter={(_label, payload) => String(payload?.[0]?.payload?.tooltip ?? '')}
              formatter={(value) => (value == null ? 'Not reported' : formatMinutes(Number(value)))} />
            <Legend itemSorter={null} {...LEGEND_PROPS} />
            {isMonthly && <SourceMarks labels={data.map((d) => d.label)} kinds={points.map((p) => p.kind ?? 'daily')} />}
            {keys.map((key) => (
              <Line isAnimationActive={false} key={key} type={curve} dataKey={key} connectNulls={false}
                stroke={key === COMBINED ? OVERALL_COLOR : reportTypeColor(key)} strokeWidth={2}
                strokeDasharray={key === COMBINED ? '5 3' : undefined} dot={{ r: 2 }} />
            ))}
          </LineChart>
        </ResponsiveContainer>
      </div>
      {isMonthly && <SourceNote months={points.map((p) => ({ label: p.label, source: p.kind === 'gap' ? 'gap' : p.historical ? 'historical_import' : 'daily_derived' }))} />}
      <DataTable caption={`${view} outage minutes`} columns={[isMonthly ? 'Month' : view === 'weekly' ? 'Week' : 'Date', ...(split ? [COMBINED, ...types] : types)]}
        rows={points.map((p) => [p.tooltip, ...(split ? [COMBINED, ...types] : types).map((k) => show(k === COMBINED ? p.total : p.byType?.[k]))])} />
    </>
  );
}

/** Circles ranked by outage minutes per site in scope over the shown period (total ÷ the circle's sites in scope). */
function CircleOutage({ points, circles, period }: { points: Point[]; circles: { key: string; report_type: string; sites: number }[]; period: string }) {
  const rows = circles.map((c) => {
    const values = points.map((p) => p.byCircle?.[c.key] ?? null);
    const present = values.filter((v): v is number => v != null);
    const total = present.length ? present.reduce((a, b) => a + b, 0) : null;
    return {
      key: c.key, name: circleLabel(c.key), type: c.report_type, sites: c.sites, total,
      // Only with a valid denominator: the circle's sites in scope (from the API).
      perSite: total != null && c.sites > 0 ? Math.round((total / c.sites) * 10) / 10 : null,
      missing: values.length - present.length,
    };
  });
  const ranked = rows.filter((r) => r.perSite != null).sort((a, b) => b.perSite! - a.perSite!);
  const noData = rows.filter((r) => r.perSite == null);
  return (
    <>
      <div style={{ height: Math.max(160, ranked.length * 24 + 30) }} role="img" aria-label="Bar chart of outage minutes per site by circle">
        <ResponsiveContainer width="100%" height="100%">
          <BarChart data={ranked} layout="vertical" margin={{ top: 0, right: 52, bottom: 0, left: 4 }}>
            <CartesianGrid strokeDasharray="3 3" horizontal={false} stroke="var(--border)" />
            <XAxis type="number" tick={AXIS_TICK} tickLine={false} axisLine={false} tickFormatter={(v: number) => formatCompact(v)} />
            <YAxis type="category" dataKey="name" tick={AXIS_TICK} tickLine={false} axisLine={false} width={78} interval={0} />
            <Tooltip {...TOOLTIP_PROPS} cursor={{ fill: 'var(--muted)' }}
              formatter={(value, _name, item) => {
                const r = item?.payload as (typeof ranked)[number];
                return [`${formatMinutes(Number(value))} per site (${formatMinutes(r.total)} over ${formatNumber(r.sites)} sites)${r.missing ? `; ${r.missing} periods without data` : ''}`, 'Outage'];
              }} />
            <Bar isAnimationActive={false} dataKey="perSite" radius={[0, 3, 3, 0]} maxBarSize={14}>
              {ranked.map((r) => <Cell key={r.key} fill={reportTypeColor(r.type)} />)}
              <LabelList dataKey="perSite" position="right" fontSize={10} fill="var(--muted-foreground)" formatter={(v: unknown) => formatNumber(Number(v))} />
            </Bar>
          </BarChart>
        </ResponsiveContainer>
      </div>
      <p className="mt-1 flex flex-wrap gap-x-3 text-[11px] text-muted-foreground">
        <span className="inline-flex items-center gap-1"><span className="size-2.5 rounded-sm" style={{ background: reportTypeColor('4G Saturation') }} aria-hidden="true" />4G</span>
        <span className="inline-flex items-center gap-1"><span className="size-2.5 rounded-sm" style={{ background: reportTypeColor('LWE') }} aria-hidden="true" />LWE</span>
        {noData.length > 0 && <span>No outage data: {noData.map((r) => r.name).join(', ')}</span>}
      </p>
      <DataTable caption={`Outage per site by circle, ${period}`} columns={['Circle', 'Sites in scope', 'Outage minutes', 'Per site', 'Periods without data']}
        rows={[...ranked, ...noData].map((r) => [r.name, formatNumber(r.sites), show(r.total), r.perSite == null ? 'No data' : formatMinutes(r.perSite), r.missing])} />
    </>
  );
}

function Segmented<T extends string>({ value, onChange, options, label }: { value: T; onChange: (v: T) => void; options: [T, string][]; label: string }) {
  return (
    <div className="inline-flex rounded-lg border p-0.5" role="group" aria-label={label}>
      {options.map(([v, text]) => (
        <button key={v} type="button" aria-pressed={value === v} onClick={() => onChange(v)}
          className={cn('rounded-md px-2.5 py-1 text-xs font-medium transition-colors focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none',
            value === v ? 'bg-primary text-primary-foreground' : 'text-muted-foreground hover:text-foreground')}>
          {text}
        </button>
      ))}
    </div>
  );
}

const round = (v: number | null | undefined) => (v == null ? null : Math.round(v));
const show = (v: number | null | undefined) => (v == null ? 'Not reported' : formatMinutes(v));
