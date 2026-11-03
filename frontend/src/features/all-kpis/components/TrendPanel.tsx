import { useState } from 'react';
import { Bar, CartesianGrid, ComposedChart, Legend, Line, ReferenceLine, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts';
import { TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table';
import { cn } from '@/lib/utils';
import { ChartCard } from '../../../components/dashboard/ChartCard';
import { AXIS_TICK, LEGEND_PROPS, TOOLTIP_PROPS } from '../../../components/dashboard/constants';
import { Segmented } from '../../../components/rca/RcaShared';
import { useApiQuery } from '../../../hooks/useApiQuery';
import { fetchKpiTrends } from '../api';
import { count, hours, NA, NUM, pct } from '../format';
import { availabilityTone, coverageTone, TONE_TEXT } from '../status';
import type { Granularity, KpiTrendPoint } from '../types';
import { KpiTable } from './KpiTable';

const VIEWS: [Granularity, string][] = [['day', 'Day-wise'], ['week', 'Week-wise'], ['month', 'Month-wise']];
const VIEW_NAMES: Record<Granularity, string> = { day: 'Day-wise', week: 'Week-wise', month: 'Month-wise' };
/** Series colours, the same on every All KPI's chart: availability = primary, USD = amber (attention), NSLA = red (below SLA). */
const SERIES = { availability: 'var(--primary)', coverage: 'var(--chart-2)', outage: 'var(--chart-1)', usd: '#d97706', nsla: '#dc2626' };
const GRID = 'var(--border)';

/** Tooltip values in the same format as the cards and tables. */
function formatSeries(key: string, value: unknown) {
  if (value == null) return NA;
  const v = Number(value);
  if (key === 'availability_pct') return pct(v, 3);
  if (key === 'coverage_pct') return pct(v, 1);
  if (key === 'outage_hours') return hours(v);
  return `${count(v)} sites`;
}

/**
 * Day-, week- and month-wise trend from the canonical daily records. Availability is outage-weighted over the site-days
 * reported in each period (never an average of daily percentages); USD / NSLA count distinct O&M Start sites.
 */
export function TrendPanel({ query, kind, period }: { query: URLSearchParams; kind: 'availability' | 'outage'; period?: string }) {
  const [view, setView] = useState<Granularity>('day');
  const params = new URLSearchParams(query);
  params.set('granularity', view);
  const trend = useApiQuery(`allkpis-trend-${params}`, (signal) => fetchKpiTrends(params, signal));
  const points = trend.data?.points ?? [];
  const title = kind === 'availability' ? 'Availability trend' : 'Outage, USD and NSLA trend';
  const range = points.length ? `${points[0].label} – ${points.at(-1)!.label}` : period;
  return (
    <ChartCard title={title} loading={trend.loading} error={trend.error} empty={!points.length}
      description={view === 'month'
        ? `${VIEW_NAMES[view]} · every month with daily data (the latest may be month to date)`
        : `${VIEW_NAMES[view]} · ${range ?? 'selected reporting period'}`}
      action={<Segmented label="Trend granularity" value={view} onChange={setView} options={VIEWS} />}>
      <div className="h-72">
        <ResponsiveContainer width="100%" height="100%">
          <ComposedChart data={points} margin={{ top: 4, right: 8, bottom: 0, left: 0 }}>
            <CartesianGrid stroke={GRID} strokeDasharray="3 3" vertical={false} />
            <XAxis dataKey="label" tick={AXIS_TICK} tickLine={false} axisLine={{ stroke: GRID }} interval="preserveStartEnd" minTickGap={16} />
            {kind === 'availability' ? (
              <>
                <YAxis yAxisId="a" tick={AXIS_TICK} tickLine={false} axisLine={false} domain={['auto', 100]} unit="%" width={52} />
                <YAxis yAxisId="c" orientation="right" tick={AXIS_TICK} tickLine={false} axisLine={false} domain={[0, 100]} unit="%" width={44} />
                <ReferenceLine yAxisId="a" y={98.5} stroke="#d97706" strokeDasharray="4 4" ifOverflow="extendDomain"
                  label={{ value: 'SLA 98.5%', position: 'insideTopLeft', fontSize: 10, fill: '#b45309' }} />
                <Line yAxisId="a" dataKey="availability_pct" name="Availability %" stroke={SERIES.availability} strokeWidth={2} dot={points.length < 20 ? { r: 2.5 } : false}
                  connectNulls={false} isAnimationActive={false} />
                <Line yAxisId="c" dataKey="coverage_pct" name="Reporting coverage %" stroke={SERIES.coverage} strokeDasharray="4 3" dot={false} isAnimationActive={false} />
              </>
            ) : (
              <>
                <YAxis yAxisId="h" tick={AXIS_TICK} tickLine={false} axisLine={false} unit=" h" width={60} />
                <YAxis yAxisId="s" orientation="right" tick={AXIS_TICK} tickLine={false} axisLine={false} allowDecimals={false} width={44} />
                <Bar yAxisId="h" dataKey="outage_hours" name="Outage hours" fill={SERIES.outage} fillOpacity={0.75} radius={[3, 3, 0, 0]} maxBarSize={28} isAnimationActive={false} />
                <Line yAxisId="s" dataKey="usd_sites" name="USD sites" stroke={SERIES.usd} strokeWidth={2} dot={false} isAnimationActive={false} />
                <Line yAxisId="s" dataKey="nsla_sites" name="NSLA sites" stroke={SERIES.nsla} strokeWidth={2} dot={false} isAnimationActive={false} />
              </>
            )}
            <Tooltip {...TOOLTIP_PROPS} cursor={{ fill: 'var(--muted)', opacity: 0.5 }}
              formatter={(value, name, item) => [formatSeries(String(item?.dataKey ?? ''), value), name]} />
            <Legend {...LEGEND_PROPS} />
          </ComposedChart>
        </ResponsiveContainer>
      </div>
      <TrendTable points={points} kind={kind} />
    </ChartCard>
  );
}

function TrendTable({ points, kind }: { points: KpiTrendPoint[]; kind: 'availability' | 'outage' }) {
  return (
    <KpiTable maxHeight="max-h-72" className="mt-4">
      <TableHeader>
        <TableRow>
          <TableHead>Period</TableHead><TableHead className={NUM}>Days</TableHead>
          {kind === 'availability'
            ? <><TableHead className={NUM}>Availability</TableHead><TableHead className={NUM}>Coverage</TableHead><TableHead className={NUM}>Missing site-days</TableHead></>
            : <><TableHead className={NUM}>Outage</TableHead><TableHead className={NUM}>USD sites</TableHead><TableHead className={NUM}>NSLA sites</TableHead><TableHead className={NUM}>Below 60%</TableHead></>}
        </TableRow>
      </TableHeader>
      <TableBody>
        {points.map((p) => (
          <TableRow key={p.key}>
            <TableCell className="font-medium">{p.label}</TableCell><TableCell className={NUM}>{p.days}</TableCell>
            {kind === 'availability' ? (
              <>
                <TableCell className={cn(NUM, TONE_TEXT[availabilityTone(p.availability_pct)])}>{pct(p.availability_pct, 3)}</TableCell>
                <TableCell className={cn(NUM, TONE_TEXT[coverageTone(p.coverage_pct)])}>{pct(p.coverage_pct, 1)}</TableCell>
                <TableCell className={NUM}>{count(p.missing_site_days)}</TableCell>
              </>
            ) : (
              <>
                <TableCell className={NUM}>{hours(p.outage_hours)}</TableCell><TableCell className={NUM}>{count(p.usd_sites)}</TableCell>
                <TableCell className={NUM}>{count(p.nsla_sites)}</TableCell><TableCell className={NUM}>{count(p.below_60_sites)}</TableCell>
              </>
            )}
          </TableRow>
        ))}
      </TableBody>
    </KpiTable>
  );
}
