import { useState } from 'react';
import { Bar, CartesianGrid, ComposedChart, Legend, Line, ReferenceLine, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts';
import { TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table';
import { cn } from '@/lib/utils';
import { PeriodStatusBadge } from '../../../components/reporting/ReportingStatus';
import { useApiQuery } from '../../../hooks/useApiQuery';
import { fetchKpiTrends } from '../api';
import { count, hours, NA, pct } from '../format';
import { availabilityTone, toneText } from '../status';
import type { Granularity, KpiTrendPoint } from '../types';
import { KpiTable } from './KpiTable';
import { Panel, Tabs } from './Ui';
import { CHART } from './theme';

const VIEWS: [Granularity, string][] = [['day', 'Day-wise'], ['week', 'Week-wise'], ['month', 'Month-wise']];
const VIEW_NAMES: Record<Granularity, string> = { day: 'Day-wise', week: 'Week-wise', month: 'Month-wise' };
const SLA = 98.5;

/** Tooltip values in the same format as the tiles and tables. */
function formatSeries(key: string, value: unknown) {
  if (value == null) return NA;
  const v = Number(value);
  if (key === 'availability_pct') return pct(v, 3);
  if (key === 'outage_hours') return hours(v);
  return `${count(v)} sites`;
}

/** Availability point: red below the 98.5% SLA line (reference style), accent otherwise. */
function SlaDot(props: { cx?: number; cy?: number; value?: number | null; index?: number }) {
  const { cx, cy, value } = props;
  if (cx == null || cy == null || value == null) return <g key={props.index} />;
  const below = value < SLA;
  return <circle key={props.index} cx={cx} cy={cy} r={below ? 4 : 2.5} fill={below ? 'var(--akp-crit)' : 'var(--akp-accent)'} stroke="var(--akp-surface)" strokeWidth={1} />;
}

/**
 * Day-, week- and month-wise trend from the canonical daily records. Availability is outage-weighted over the site-days
 * reported in each period (never an average of daily percentages); USD Sites / NSLA Sites count distinct sites of the
 * selected population.
 */
export function TrendPanel({ query, kind, period, initial = 'day', title: heading }: {
  query: URLSearchParams; kind: 'availability' | 'outage'; period?: string; initial?: Granularity; title?: string;
}) {
  const [view, setView] = useState<Granularity>(initial);
  const params = new URLSearchParams(query);
  params.set('granularity', view);
  const trend = useApiQuery(`allkpis-trend-${params}`, (signal) => fetchKpiTrends(params, signal));
  const points = trend.data?.points ?? [];
  const title = heading ?? (kind === 'availability' ? 'Availability trend' : 'Outage, USD Sites and NSLA Sites trend');
  const range = points.length ? `${points[0].label} – ${points.at(-1)!.label}` : period;
  return (
    <Panel title={title} loading={trend.loading} error={trend.error} empty={!points.length}
      note={view === 'month'
        ? `${VIEW_NAMES[view]} · every month with daily data (the latest may be month to date)`
        : `${VIEW_NAMES[view]} · ${range ?? 'selected reporting period'}`}
      action={<Tabs small label="Trend granularity" items={VIEWS} value={view} onChange={setView} />}>
      <div className="h-[230px]">
        <ResponsiveContainer width="100%" height="100%">
          <ComposedChart data={points} margin={{ top: 4, right: 8, bottom: 0, left: 0 }}>
            <CartesianGrid stroke={CHART.grid} vertical={false} />
            <XAxis dataKey="label" tick={CHART.tick} tickLine={false} axisLine={{ stroke: 'var(--akp-axis)' }} interval="preserveStartEnd" minTickGap={16} />
            {kind === 'availability' ? (
              <>
                <YAxis yAxisId="a" tick={CHART.tick} tickLine={false} axisLine={false} domain={['auto', 100]} unit="%" width={52} />
                <ReferenceLine yAxisId="a" y={SLA} stroke={CHART.ink2} strokeDasharray="5 4" ifOverflow="extendDomain"
                  label={{ value: 'SLA 98.5%', position: 'insideTopLeft', fontSize: 11, fill: 'var(--akp-ink2)' }} />
                <Line yAxisId="a" dataKey="availability_pct" name="Availability %" stroke={CHART.accent} strokeWidth={2}
                  dot={points.length <= 40 ? <SlaDot /> : false} connectNulls={false} isAnimationActive={false} />
              </>
            ) : (
              <>
                <YAxis yAxisId="h" tick={CHART.tick} tickLine={false} axisLine={false} unit=" h" width={60} />
                <YAxis yAxisId="s" orientation="right" tick={CHART.tick} tickLine={false} axisLine={false} allowDecimals={false} width={44} />
                <Bar yAxisId="h" dataKey="outage_hours" name="Outage hours" fill={CHART.accent} radius={[2, 2, 0, 0]} maxBarSize={36} isAnimationActive={false} />
                <Line yAxisId="s" dataKey="usd_sites" name="USD Sites" stroke="var(--akp-warn)" strokeWidth={2} dot={false} isAnimationActive={false} />
                <Line yAxisId="s" dataKey="nsla_sites" name="NSLA Sites" stroke={CHART.crit} strokeWidth={2} dot={false} isAnimationActive={false} />
              </>
            )}
            <Tooltip {...CHART.tooltip} cursor={{ fill: 'var(--akp-hover)' }}
              formatter={(value, name, item) => [formatSeries(String(item?.dataKey ?? ''), value), name]} />
            <Legend {...CHART.legend} />
          </ComposedChart>
        </ResponsiveContainer>
      </div>
      <TrendTable points={points} kind={kind} />
    </Panel>
  );
}

function TrendTable({ points, kind }: { points: KpiTrendPoint[]; kind: 'availability' | 'outage' }) {
  return (
    <KpiTable maxHeight={288} className="mt-3">
      <TableHeader>
        <TableRow>
          <TableHead>Period</TableHead><TableHead className="r">Days</TableHead>
          {kind === 'availability'
            ? <TableHead className="r">Availability</TableHead>
            : <><TableHead className="r">Outage</TableHead><TableHead className="r">USD Sites</TableHead><TableHead className="r">NSLA Sites</TableHead><TableHead className="r">Below 60%</TableHead></>}
        </TableRow>
      </TableHeader>
      <TableBody>
        {points.map((p) => (
          <TableRow key={p.key}>
            <TableCell className="font-medium">
              <span className="inline-flex flex-wrap items-center gap-1.5">{p.label} <PeriodStatusBadge status={p.status} missing={p.missing} /></span>
            </TableCell><TableCell className="r">{p.days}</TableCell>
            {kind === 'availability' ? (
              <TableCell className={cn('r', toneText(availabilityTone(p.availability_pct)))}>{pct(p.availability_pct, 3)}</TableCell>
            ) : (
              <>
                <TableCell className="r">{hours(p.outage_hours)}</TableCell><TableCell className="r">{count(p.usd_sites)}</TableCell>
                <TableCell className="r">{count(p.nsla_sites)}</TableCell><TableCell className="r">{count(p.below_60_sites)}</TableCell>
              </>
            )}
          </TableRow>
        ))}
      </TableBody>
    </KpiTable>
  );
}
