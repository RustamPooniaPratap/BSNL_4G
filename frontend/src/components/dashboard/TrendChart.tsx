import { ArrowDownRight, ArrowUpRight, Minus } from 'lucide-react';
import {
  Bar, BarChart, CartesianGrid, Legend, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis,
} from 'recharts';
import { cn } from '@/lib/utils';
import { formatDate, formatNumber, formatPct, formatShortDate } from '../../lib/format';
import { selectDays, type TrendView } from '../../hooks/useDashboardFilters';
import { monthlyByCircle, trendByCircle, type CircleSeries } from '../../lib/circleSeries';
import type { CircleSeriesInfo, MonthlyResponse, TrendResponse } from '../../types';
import { UptimeHeatmap, type HeatmapColumn } from './UptimeHeatmap';
import { ChartCard } from './ChartCard';
import { DataTable } from './DataTable';
import { AXIS_TICK, DENSE_CARD, LEGEND_PROPS, OVERALL_COLOR, TOOLTIP_PROPS, reportTypeColor, type UptimeChartView } from './constants';
import { useSourceLabels } from '../../context/sourceLabels';
import { SOURCE_LABEL_MARGIN, SourceMarks, SourceNote } from './SourceMarks';
import { isCalculated, isHistorical, monthKind } from '../../lib/monthlyHistory';
import { PeriodStatusBadge } from '../reporting/ReportingStatus';
import { statusText } from '../../lib/reportingStatus';

const VIEWS: { value: TrendView; label: string }[] = [
  { value: 'daily', label: 'Daily' },
  { value: 'weekly', label: 'Weekly' },
  { value: 'monthly', label: 'Monthly' },
];
const COMBINED = 'Combined';
const shortType = (type: string) => (type === '4G Saturation' ? '4G' : type);

/** How each series is named and drawn: report types (default) or the circles chosen for comparison. */
interface SeriesStyle {
  name: (key: string) => string;
  color: (key: string) => string;
  /** Report-type lines are dashed under the solid combined line; circle lines are solid, told apart by colour. */
  dashed: boolean;
  circles: boolean;
}
const styleFor = (circles: CircleSeries | null | undefined): SeriesStyle => (circles
  ? { name: circles.label, color: circles.color, dashed: false, circles: true }
  : { name: (k) => k, color: (k) => (k === COMBINED ? OVERALL_COLOR : reportTypeColor(k)), dashed: true, circles: false });

interface TrendChartProps {
  trend: TrendResponse | null;
  monthly: MonthlyResponse | null;
  loading: boolean;
  monthlyLoading: boolean;
  error: Error | null;
  monthlyError: Error | null;
  scopeLabel: string;
  monthLabel: string;
  view: TrendView;
  onViewChange: (view: TrendView) => void;
  /** Specific dates picked in the trend period (empty = every day in the range). */
  dayList: string[];
  /** Weeks picked in the trend period (empty = every week). */
  weekList: number[];
  /** True when only some months were picked. */
  monthsFiltered: boolean;
  /** Circles to compare, one series each (null: the overall and per report type lines). */
  circles?: CircleSeries | null;
  /** Overall lines, chosen circles, or all circles as a heatmap. */
  chartView?: UptimeChartView;
  /** Controls shown above the chart (view switch, circle picker). */
  controls?: React.ReactNode;
  /** Chart view controls shown in the card header beside the period switch. */
  viewControls?: React.ReactNode;
  /** Every circle in the data (heatmap rows). */
  allCircles?: CircleSeriesInfo[];
  /** Heatmap row clicked: show that circle's trend. */
  onSelectCircle?: (key: string) => void;
}

/** A week without a value: not complete yet (in progress or ahead), or no data although it has passed. */
const weekStatus = (w: { complete?: boolean }) => (w.complete === false ? 'Not complete yet' : 'Not reported');

export type { UptimeChartView } from './constants';

/** Uptime over time at three granularities: days in the trend range, workbook weeks, and months. */
export function TrendChart(props: TrendChartProps) {
  // The view and period live in the URL (?trend=weekly&weeks=1,2) via the filter bar's trend period.
  const { scopeLabel, view, onViewChange: setView, dayList, weekList, chartView = 'overall', controls } = props;
  const circles = chartView === 'circles' ? props.circles : null;
  const trend = props.trend && circles ? trendByCircle(props.trend, circles.keys) : props.trend;
  const monthly = props.monthly && circles ? monthlyByCircle(props.monthly, circles.keys) : props.monthly;
  const style = styleFor(circles);
  const sourceLabels = useSourceLabels();

  const switcher = <TrendViewSwitch view={view} onChange={setView} />;
  // Header controls: the chart view switch (when the page gives one) and the period switch, on one row.
  const actions = props.viewControls
    ? <div className="flex flex-wrap items-center justify-end gap-2">{props.viewControls}{switcher}</div> : switcher;

  if (chartView === 'heatmap') {
    const isMonthly = view === 'monthly';
    const columns: HeatmapColumn[] = isMonthly
      ? (props.monthly?.months ?? []).map((m) => ({ key: m.key, label: m.partial ? `${m.label.replace(' MTD', '')}*` : m.label,
          title: m.partial ? `${m.label} (${m.days} days)` : m.gap ? `${m.label} · No data` : isHistorical(m) ? `${m.label} · ${sourceLabels.history}` : m.label, values: m.by_circle }))
      : view === 'weekly'
        ? selectWeeks(props.trend?.weeks ?? [], weekList).map((w) => ({ key: w.label, label: w.label.replace('Week ', 'Wk-'), title: `${w.label} (${formatShortDate(w.start)}–${formatShortDate(w.end)})`, values: w.by_circle }))
        : selectDays(props.trend?.series ?? [], dayList).filter((p) => p.reported).map((p) => ({ key: p.date, label: p.date.slice(8), title: formatDate(p.date), values: p.by_circle }));
    const rows = props.allCircles ?? [];
    return (
      <ChartCard className={DENSE_CARD}
        title="Uptime trend"
        description={`${scopeLabel}, every circle by ${isMonthly ? 'month (* = month to date)' : view === 'weekly' ? 'workbook week' : 'reporting date'}: uptime %, coloured by the workbook buckets. Hatched = no data. Select a circle to see its trend.`}
        action={actions}
        loading={isMonthly ? props.monthlyLoading : props.loading}
        error={isMonthly ? props.monthlyError : props.error}
        empty={!columns.length || !rows.length}
        emptyMessage="No reporting days fall in the selected trend range."
      >
        {controls}
        <UptimeHeatmap circles={rows} columns={columns} onSelectCircle={props.onSelectCircle}
          caption={`Uptime by circle and ${isMonthly ? 'month' : view === 'weekly' ? 'week' : 'date'}`} />
      </ChartCard>
    );
  }

  if (view === 'monthly') {
    const months = monthly?.months ?? [];
    return (
      <ChartCard className={DENSE_CARD}
        title="Uptime trend"
        description={months.some(isHistorical)
          ? sourceLabels.description(scopeLabel, months.find(isCalculated)?.label)
          : `${scopeLabel}, by ${props.monthsFiltered ? 'selected' : ''} month. Recomputed from each site's monthly outage with today's On-Air / O&M flags; months reported earlier in the workbook's Summ sheet can differ slightly.`}
        action={actions}
        loading={props.monthlyLoading}
        error={props.monthlyError}
        empty={!months.some((m) => m.uptime_pct != null)}
        emptyMessage="The workbook has no monthly outage history."
      >
        {controls}
        {monthly && <MonthlyView monthly={monthly} style={style} />}
      </ChartCard>
    );
  }

  if (view === 'weekly') {
    const weeks = selectWeeks(trend?.weeks ?? [], weekList);
    return (
      <ChartCard className={DENSE_CARD}
        title="Uptime trend"
        description={`${scopeLabel}, ${weekList.length ? `weeks ${weekList.join(', ')}` : 'by workbook week'} of ${props.monthLabel} (days 1–7, 8–14, 15–21, 22–end). Daily values exist only for the reporting month, so earlier months' weeks cannot be compared.`}
        action={actions}
        loading={props.loading}
        error={props.error}
        empty={!weeks.some((w) => w.uptime_pct != null)}
      >
        {controls}
        {trend && <WeeklyView trend={trend} weeks={weeks} style={style} />}
      </ChartCard>
    );
  }

  const series = selectDays(trend?.series ?? [], dayList);
  const reported = series.filter((p) => p.reported);
  const missing = series.length - reported.length;
  return (
    <ChartCard className={DENSE_CARD}
      title="Uptime trend"
      description={
        <>
          {dayList.length
            ? `${scopeLabel}, on ${dayList.length} selected date${dayList.length > 1 ? 's' : ''}.`
            : `${scopeLabel}, by day for the trend period (${formatShortDate(series[0]?.date)}–${formatShortDate(series.at(-1)?.date)}).`}
          {missing > 0 && ` ${missing} day${missing > 1 ? 's' : ''} not reported (shown as gaps).`}
        </>
      }
      action={actions}
      loading={props.loading}
      error={props.error}
      empty={!reported.length}
      emptyMessage="No reporting days fall in the selected trend range."
    >
      {controls}
      {trend && <DailyView trend={{ ...trend, series }} picked={dayList.length > 0} style={style} />}
    </ChartCard>
  );
}

/** The picked weeks, with the change re-measured against the previous week shown. */
function selectWeeks(weeks: TrendResponse['weeks'], picked: number[]) {
  if (!picked.length) return weeks;
  let previous: number | null = null;
  return weeks
    .filter((_, i) => picked.includes(i + 1))
    .map((w) => {
      const change = w.uptime_pct != null && previous != null ? Math.round((w.uptime_pct - previous) * 100) / 100 : null;
      if (w.uptime_pct != null) previous = w.uptime_pct;
      return { ...w, change_pts: change };
    });
}

/** Daily / Weekly / Monthly switch shared by the uptime and outage charts (one setting for both). */
export function TrendViewSwitch({ view, onChange, label = 'Trend period' }: { view: TrendView; onChange: (view: TrendView) => void; label?: string }) {
  return (
    <div className="inline-flex rounded-lg border p-0.5" role="group" aria-label={label}>
      {VIEWS.map((v) => (
        <button
          key={v.value}
          type="button"
          aria-pressed={view === v.value}
          onClick={() => onChange(v.value)}
          className={cn(
            'rounded-md px-2.5 py-1 text-xs font-medium transition-colors focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none',
            view === v.value ? 'bg-primary text-primary-foreground' : 'text-muted-foreground hover:text-foreground',
          )}
        >
          {v.label}
        </button>
      ))}
    </div>
  );
}


function DailyView({ trend, picked, style }: { trend: TrendResponse; picked: boolean; style: SeriesStyle }) {
  const types = trend.report_types;
  // With circles chosen only their lines are drawn; otherwise the combined line goes over the report types.
  const combined = types.length > 1 && !style.circles;
  const split = combined || style.circles;
  const data = trend.series.map((p) => ({ date: p.date, [COMBINED]: p.uptime_pct, ...p.by_report_type }));
  const lower = lowerBound(trend.series.flatMap((p) => [...(style.circles ? [] : [p.uptime_pct]), ...Object.values(p.by_report_type)]));
  // Picked dates need not be consecutive: straight segments avoid implying values in between.
  const curve = picked ? 'linear' : 'monotone';

  return (
    <>
      <div className="h-[clamp(240px,34vh,304px)]" role="img" aria-label="Line chart of daily uptime">
        <ResponsiveContainer width="100%" height="100%">
          <LineChart data={data} margin={{ top: 8, right: 12, bottom: 0, left: -8 }}>
            <CartesianGrid strokeDasharray="3 3" vertical={false} stroke="var(--border)" />
            <XAxis dataKey="date" tickFormatter={formatShortDate} tick={AXIS_TICK} tickLine={false} axisLine={false} minTickGap={picked ? 0 : 16} />
            <YAxis domain={[lower, 100]} tickFormatter={(v: number) => `${v}%`} tick={AXIS_TICK} tickLine={false} axisLine={false} width={48} />
            <Tooltip
              labelFormatter={(label) => formatDate(String(label))}
              formatter={(value) => (value == null ? 'Not reported' : formatPct(Number(value)))}
              {...TOOLTIP_PROPS}
            />
            <Legend itemSorter={null} {...LEGEND_PROPS} />
            {combined && <Line isAnimationActive={false} type={curve} dataKey={COMBINED} name={style.name(COMBINED)} stroke={OVERALL_COLOR}
              strokeWidth={2} dot={{ r: 2 }} connectNulls={false} />}
            {types.map((type) => (
              <Line isAnimationActive={false} key={type} type={curve} dataKey={type} name={style.name(type)} stroke={style.color(type)}
                strokeWidth={split ? 1.75 : 2.25} strokeDasharray={split && style.dashed ? '4 3' : undefined} dot={{ r: 2 }} connectNulls={false} />
            ))}
          </LineChart>
        </ResponsiveContainer>
      </div>
      <DataTable
        caption="Daily uptime data"
        columns={['Date', ...(combined ? [COMBINED, ...types] : style.circles ? types : ['Uptime']).map(style.name), 'Sites reported']}
        rows={trend.series.map((p) => [
          formatDate(p.date),
          ...(combined ? [p.uptime_pct, ...types.map((t) => p.by_report_type[t])] : style.circles ? types.map((t) => p.by_report_type[t]) : [p.uptime_pct])
            .map((v) => (p.reported ? formatPct(v) : 'Not reported')),
          `${formatNumber(p.sites_reported)} / ${formatNumber(p.sites_in_scope)}`,
        ])}
      />
    </>
  );
}

function WeeklyView({ trend, weeks, style }: { trend: TrendResponse; weeks: TrendResponse['weeks']; style: SeriesStyle }) {
  const types = trend.report_types;
  const combined = types.length > 1 && !style.circles;
  const data = weeks.map((w) => ({
    name: `${w.label} (${formatShortDate(w.start)}–${formatShortDate(w.end)})`,
    short: w.label,
    [COMBINED]: w.uptime_pct,
    ...w.by_report_type,
  }));
  const lower = lowerBound(weeks.flatMap((w) => [...(style.circles ? [] : [w.uptime_pct]), ...Object.values(w.by_report_type)]));
  const keys = combined ? [COMBINED, ...types] : types;
  // The Status column only with a backend that sends the Complete / Provisional status.
  const weekStatuses = weeks.some((w) => w.status);

  return (
    <>
      <div className="h-[clamp(224px,30vh,280px)]" role="img" aria-label="Bar chart comparing weekly uptime">
        <ResponsiveContainer width="100%" height="100%">
          <BarChart data={data} margin={{ top: 8, right: 12, bottom: 0, left: -8 }} barGap={2}>
            <CartesianGrid strokeDasharray="3 3" vertical={false} stroke="var(--border)" />
            <XAxis dataKey="short" tick={AXIS_TICK} tickLine={false} axisLine={false} />
            <YAxis domain={[lower, 100]} tickFormatter={(v: number) => `${v}%`} tick={AXIS_TICK} tickLine={false} axisLine={false} width={48} />
            <Tooltip
              labelFormatter={(_label, payload) => String(payload?.[0]?.payload?.name ?? '')}
              formatter={(value) => (value == null ? 'Not reported' : formatPct(Number(value)))}
              {...TOOLTIP_PROPS}
              cursor={{ fill: 'var(--muted)' }}
            />
            <Legend itemSorter={null} {...LEGEND_PROPS} />
            {keys.map((key) => (
              <Bar isAnimationActive={false} key={key} dataKey={key} name={style.name(key)} fill={style.color(key)}
                radius={[3, 3, 0, 0]} maxBarSize={28} />
            ))}
          </BarChart>
        </ResponsiveContainer>
      </div>
      <dl className="mt-2 grid grid-cols-2 gap-2 sm:grid-cols-4" aria-label="Weekly uptime and change">
        {weeks.map((w) => (
          <div key={w.label} className="rounded-lg bg-muted/60 px-3 py-2">
            <dt className="text-[11px] text-muted-foreground">{w.label} · {formatShortDate(w.start)}–{formatShortDate(w.end)}</dt>
            <dd className="flex items-baseline gap-2 text-sm font-semibold tabular-nums">
              {w.days_reported ? formatPct(w.uptime_pct) : <span className="font-normal text-muted-foreground">{weekStatus(w)}</span>}
              <Change value={w.change_pts} unit="vs previous week shown" />
              {w.days_reported > 0 && <PeriodStatusBadge status={w.status} missing={w.missing} />}
            </dd>
          </div>
        ))}
      </dl>
      <DataTable
        caption="Weekly uptime"
        columns={['Week', ...keys.map(style.name), 'Change', 'Days reported', ...(weekStatuses ? ['Status'] : [])]}
        rows={weeks.map((w) => [
          `${w.label} (${formatShortDate(w.start)}–${formatShortDate(w.end)})`,
          ...keys.map((k) => (w.days_reported ? formatPct(k === COMBINED ? w.uptime_pct : w.by_report_type[k]) : weekStatus(w))),
          formatChange(w.change_pts),
          `${w.days_reported} / ${w.days_in_week}`,
          ...(weekStatuses ? [statusText(w)] : []),
        ])}
      />
    </>
  );
}

function MonthlyView({ monthly, style }: { monthly: MonthlyResponse; style: SeriesStyle }) {
  const sourceLabels = useSourceLabels();
  const types = monthly.report_types;
  const split = types.length > 1 || style.circles;
  const keys = types.length > 1 && !style.circles ? [COMBINED, ...types] : types;
  const months = monthly.months;
  const data = months.map((m) => ({ label: m.label, source: m.source, [COMBINED]: m.uptime_pct, ...m.by_report_type }));
  // The summary tiles describe the months calculated from daily records (the response's overall figure).
  const calculated = months.filter(isCalculated);
  const marked = months.some(isHistorical);
  const lower = lowerBound(months.flatMap((m) => [...(style.circles ? [] : [m.uptime_pct]), ...Object.values(m.by_report_type)]));
  const latest = months.at(-1);
  const incomplete = calculated.filter((m) => !m.partial && m.sites_reported < m.sites_in_scope).length;
  const { overall } = monthly;
  const firstLabel = calculated.find((m) => m.uptime_pct != null)?.label ?? '—';
  const monthStatuses = months.some((m) => m.status || m.finalization_status);

  return (
    <>
      <dl className="mb-2 grid grid-cols-1 gap-2 sm:grid-cols-3">
        <div className="rounded-lg bg-muted/60 px-3 py-2">
          <dt className="text-[11px] text-muted-foreground">
            Overall · {firstLabel} to {formatDate(overall.end)} · {overall.months} months{calculated.length < months.length ? ' (calculated)' : ''}
          </dt>
          <dd className="text-lg font-semibold tabular-nums">{formatPct(overall.uptime_pct)}</dd>
          {split && !style.circles && (
            <dd className="text-[11px] text-muted-foreground">
              {types.map((t) => `${shortType(t)} ${formatPct(overall.by_report_type[t])}`).join(' · ')}
            </dd>
          )}
        </div>
        {latest && (
          <div className="rounded-lg bg-muted/60 px-3 py-2">
            <dt className="text-[11px] text-muted-foreground">{latest.label} ({latest.days} days)</dt>
            <dd className="flex items-baseline gap-2 text-lg font-semibold tabular-nums">
              {formatPct(latest.uptime_pct)} <Change value={latest.change_pts} unit="vs previous month" />
              <PeriodStatusBadge status={latest.status} finalizationStatus={latest.finalization_status} missing={latest.missing} />
            </dd>
          </div>
        )}
        <BestWorst months={months} />
      </dl>
      <div className="h-[clamp(224px,30vh,280px)]" role="img" aria-label="Line chart of monthly uptime">
        <ResponsiveContainer width="100%" height="100%">
          <LineChart data={data} margin={{ top: marked && sourceLabels.annotate ? SOURCE_LABEL_MARGIN : 8, right: 12, bottom: 0, left: -8 }}>
            <CartesianGrid strokeDasharray="3 3" vertical={false} stroke="var(--border)" />
            {/* Height for the longest angled label ("Nov-26 MTD"), so its start is not cut off below the axis. */}
            <XAxis dataKey="label" tick={AXIS_TICK} tickLine={false} axisLine={false} interval={0} angle={-30} textAnchor="end" height={52} />
            <YAxis domain={[lower, 100]} tickFormatter={(v: number) => `${v}%`} tick={AXIS_TICK} tickLine={false} axisLine={false} width={48} />
            <Tooltip formatter={(value) => (value == null ? 'No data' : formatPct(Number(value)))} {...TOOLTIP_PROPS}
              labelFormatter={(label, payload) => (payload?.[0]?.payload?.source === 'historical_import' ? `${label} · ${sourceLabels.history}` : String(label))} />
            <Legend itemSorter={null} {...LEGEND_PROPS} />
            <SourceMarks labels={data.map((d) => d.label)} kinds={months.map(monthKind)} />
            {keys.map((key) => (
              <Line isAnimationActive={false} key={key} type="monotone" dataKey={key} name={style.name(key)} stroke={style.color(key)}
                strokeWidth={key === COMBINED ? 2.25 : 1.75}
                strokeDasharray={split && style.dashed && key !== COMBINED ? '4 3' : undefined}
                dot={{ r: 2.5 }} connectNulls={false} />
            ))}
          </LineChart>
        </ResponsiveContainer>
      </div>
      <SourceNote months={months.map((m) => ({ label: m.label, source: m.gap ? 'gap' : m.source }))} />
      {incomplete > 0 && (
        <p className="mt-2 text-xs text-muted-foreground">
          In {incomplete} of {calculated.length - 1} months some sites in scope have no value and are excluded; the workbook counts them
          as 100% up. The data table shows both figures.
        </p>
      )}
      <DataTable
        caption="Monthly uptime"
        columns={['Month', ...keys.map(style.name), 'Change', 'Workbook method (blank = 100%)', 'Sites reported', ...(monthStatuses ? ['Status'] : []), 'Source']}
        rows={months.map((m) => [
          m.partial ? `${m.label} (${m.days} days)` : m.label,
          ...keys.map((k) => formatPct(k === COMBINED ? m.uptime_pct : m.by_report_type[k])),
          formatChange(m.change_pts),
          formatPct(m.uptime_pct_blank_as_zero),
          m.gap ? '—' : isHistorical(m) ? `${formatNumber(m.sites_reported)} with a value` : `${formatNumber(m.sites_reported)} / ${formatNumber(m.sites_in_scope)}`,
          ...(monthStatuses ? [statusText(m)] : []),
          m.gap ? 'No data' : isHistorical(m) ? sourceLabels.history : 'Calculated from daily records',
        ])}
      />
    </>
  );
}

function BestWorst({ months }: { months: MonthlyResponse['months'] }) {
  const { tag: sourceTag } = useSourceLabels();
  const complete = months.filter((m) => !m.partial && m.uptime_pct != null);
  if (complete.length < 2) return null;
  const tag = (m: MonthlyResponse['months'][number]) => (isHistorical(m) ? sourceTag : '');
  const best = complete.reduce((a, b) => ((b.uptime_pct ?? 0) > (a.uptime_pct ?? 0) ? b : a));
  const worst = complete.reduce((a, b) => ((b.uptime_pct ?? 0) < (a.uptime_pct ?? 0) ? b : a));
  return (
    <div className="rounded-lg bg-muted/60 px-3 py-2">
      <dt className="text-[11px] text-muted-foreground">Best / worst complete month</dt>
      <dd className="text-sm font-semibold tabular-nums">{best.label}{tag(best)} {formatPct(best.uptime_pct)}</dd>
      <dd className="text-sm font-semibold tabular-nums text-destructive">{worst.label}{tag(worst)} {formatPct(worst.uptime_pct)}</dd>
    </div>
  );
}

function Change({ value, unit }: { value: number | null; unit: string }) {
  if (value == null) return null;
  const Icon = value > 0 ? ArrowUpRight : value < 0 ? ArrowDownRight : Minus;
  return (
    <span
      className={cn('inline-flex items-center text-xs font-medium', value > 0 ? 'text-emerald-700' : value < 0 ? 'text-destructive' : 'text-muted-foreground')}
      title={`${formatChange(value)} ${unit}`}
    >
      <Icon className="size-3.5" aria-hidden="true" />
      {Math.abs(value).toFixed(2)} pts
      <span className="sr-only"> {value >= 0 ? 'up' : 'down'} {unit}</span>
    </span>
  );
}

const formatChange = (value: number | null) => (value == null ? '—' : `${value > 0 ? '+' : ''}${value.toFixed(2)} pts`);

function lowerBound(values: (number | null | undefined)[]) {
  const present = values.filter((v): v is number => v != null);
  return present.length ? Math.max(0, Math.floor(Math.min(...present) - 2)) : 0;
}
