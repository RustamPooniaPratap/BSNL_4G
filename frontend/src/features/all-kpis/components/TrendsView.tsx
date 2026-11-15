import { useState } from 'react';
import { Bar, BarChart, CartesianGrid, Cell, Line, LineChart, ReferenceLine, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts';
import { TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table';
import { cn } from '@/lib/utils';
import { useApiQuery } from '../../../hooks/useApiQuery';
import { fetchKpiTrends } from '../api';
import { count, hours, pct } from '../format';
import { availabilityTone, toneText } from '../status';
import type { Granularity, KpiTrendPoint } from '../types';
import { KpiTable } from './KpiTable';
import { ChangeText, Panel, Spark, Tabs } from './Ui';
import { CHART } from './theme';

type Key = 'availability_pct' | 'outage_hours' | 'usd_sites' | 'nsla_sites' | 'below_98_5_sites' | 'below_60_sites';
/** [label, field of the trend point, format, higher is better, change unit] — fields of /trends/, unchanged. */
const ROWS: [string, Key, (v: number | null) => string, boolean, 'pts' | '%'][] = [
  ['Availability', 'availability_pct', pct, true, 'pts'],
  ['Outage hours', 'outage_hours', hours, false, '%'],
  ['USD Sites', 'usd_sites', count, false, '%'],
  ['NSLA Sites', 'nsla_sites', count, false, '%'],
  ['Sites < 98.5%', 'below_98_5_sites', count, false, '%'],
  ['Sites < 60%', 'below_60_sites', count, false, '%'],
];
const LIMIT: Record<'month' | 'week', number> = { month: 12, week: 13 };
const provisional = (p: KpiTrendPoint) => p.status === 'Provisional';

/**
 * KPI trends (reference "KPI trends (month / week)"): every KPI by month or week from /trends/ (derived from the daily
 * records on the server), the latest change and a sparkline; then one chart per KPI. Provisional periods are marked *.
 */
export function TrendsView({ query }: { query: URLSearchParams }) {
  const [view, setView] = useState<'month' | 'week'>('month');
  const params = new URLSearchParams(query);
  params.set('granularity', view satisfies Granularity);
  const trend = useApiQuery(`allkpis-trend-${params}`, (signal) => fetchKpiTrends(params, signal));
  const points = (trend.data?.points ?? []).slice(-LIMIT[view]);
  const value = (p: KpiTrendPoint, key: Key) => (p[key] as number | null) ?? null;
  return (
    <>
      <Panel title={`${view === 'month' ? 'Month' : 'Week'}-wise KPI trend`} loading={trend.loading} error={trend.error} empty={!points.length}
        note={view === 'month'
          ? `Last ${points.length} months with daily data; the latest may be month to date. * = provisional (not every reporting unit reported).`
          : `Weeks of the selected period (workbook weeks 1–7, 8–14, 15–21, 22–end). * = provisional.`}
        action={<Tabs small label="Trend period" items={[['month', 'Month-wise'], ['week', 'Week-wise']]} value={view} onChange={setView} />}>
        <KpiTable label="KPI trend table">
          <TableHeader>
            <TableRow>
              <TableHead>KPI</TableHead>
              {points.map((p) => <TableHead key={p.key} className="r" title={`${p.start} – ${p.end}${provisional(p) ? ' · provisional' : ''}`}>{p.label}{provisional(p) ? '*' : ''}</TableHead>)}
              <TableHead className="r">Latest vs prev</TableHead>
              <TableHead>Trend</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {ROWS.map(([label, key, fmt, higherIsBetter, unit]) => {
              const series = points.map((p) => value(p, key));
              const [last, prev] = [series.at(-1) ?? null, series.at(-2) ?? null];
              return (
                <TableRow key={key}>
                  <TableCell className="font-medium">{label}</TableCell>
                  {points.map((p) => {
                    const v = value(p, key);
                    const tone = key === 'availability_pct' ? availabilityTone(v) : 'neutral';
                    return <TableCell key={p.key} className={cn('r', toneText(tone))}>{fmt(v)}</TableCell>;
                  })}
                  <TableCell className="r"><ChangeText current={last} previous={prev} unit={unit} higherIsBetter={higherIsBetter} /></TableCell>
                  <TableCell><Spark values={series} higherIsBetter={higherIsBetter} /></TableCell>
                </TableRow>
              );
            })}
            <TableRow className="tot">
              <TableCell>SLA threshold</TableCell>
              <TableCell colSpan={points.length + 2} className="muted">Availability 98.5% (existing threshold; exactly 98.5% meets it)</TableCell>
            </TableRow>
          </TableBody>
        </KpiTable>
      </Panel>
      {points.length > 0 && (
        <div className="akp-row">
          <MiniChart title="Availability" points={points} dataKey="availability_pct" line format={pct} />
          <MiniChart title="Outage hours" points={points} dataKey="outage_hours" format={hours} />
          <MiniChart title="USD Sites" points={points} dataKey="usd_sites" format={count} />
          <MiniChart title="NSLA Sites" points={points} dataKey="nsla_sites" format={count} />
        </div>
      )}
    </>
  );
}

/** One KPI over the periods: a line with the 98.5% SLA line (availability), bars otherwise; provisional bars lighter. */
function MiniChart({ title, points, dataKey, format, line }: {
  title: string; points: KpiTrendPoint[]; dataKey: Key; format: (v: number | null) => string; line?: boolean;
}) {
  const data = points.map((p) => ({ label: p.label, value: (p[dataKey] as number | null) ?? null, provisional: provisional(p) }));
  if (!data.some((d) => d.value != null)) return <Panel title={title} empty emptyMessage="Not available for these periods." />;
  const tip = <Tooltip {...CHART.tooltip} cursor={{ fill: 'var(--akp-hover)' }} formatter={(v) => [format(v == null ? null : Number(v)), title]} />;
  return (
    <Panel title={title}>
      <div className="h-[200px]" role="img" aria-label={`${title} by period`}>
        <ResponsiveContainer width="100%" height="100%">
          {line ? (
            <LineChart data={data} margin={{ top: 8, right: 8, bottom: 0, left: 0 }}>
              <CartesianGrid stroke={CHART.grid} vertical={false} />
              <XAxis dataKey="label" tick={CHART.tick} tickLine={false} axisLine={{ stroke: 'var(--akp-axis)' }} interval="preserveStartEnd" minTickGap={12} />
              <YAxis tick={CHART.tick} tickLine={false} axisLine={false} domain={['auto', 100]} unit="%" width={52} />
              <ReferenceLine y={98.5} stroke={CHART.ink2} strokeDasharray="5 4" ifOverflow="extendDomain" />
              {tip}
              <Line dataKey="value" stroke={CHART.accent} strokeWidth={2} connectNulls={false} isAnimationActive={false}
                dot={(p: { cx?: number; cy?: number; value?: number | null; index?: number }) => (p.cx == null || p.cy == null || p.value == null
                  ? <g key={p.index} />
                  : <circle key={p.index} cx={p.cx} cy={p.cy} r={p.value < 98.5 ? 4 : 2.5} fill={p.value < 98.5 ? 'var(--akp-crit)' : 'var(--akp-accent)'} />)} />
            </LineChart>
          ) : (
            <BarChart data={data} margin={{ top: 8, right: 8, bottom: 0, left: 0 }}>
              <CartesianGrid stroke={CHART.grid} vertical={false} />
              <XAxis dataKey="label" tick={CHART.tick} tickLine={false} axisLine={{ stroke: 'var(--akp-axis)' }} interval="preserveStartEnd" minTickGap={12} />
              <YAxis tick={CHART.tick} tickLine={false} axisLine={false} allowDecimals={false} width={52} />
              {tip}
              <Bar dataKey="value" radius={[3, 3, 0, 0]} maxBarSize={36} isAnimationActive={false}>
                {data.map((d) => <Cell key={d.label} fill="var(--akp-accent)" fillOpacity={d.provisional ? 0.45 : 1} />)}
              </Bar>
            </BarChart>
          )}
        </ResponsiveContainer>
      </div>
    </Panel>
  );
}
