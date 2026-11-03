import { useState } from 'react';
import { Bar, CartesianGrid, ComposedChart, Legend, Line, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table';
import { ChartCard } from '../../../components/dashboard/ChartCard';
import { AXIS_TICK, LEGEND_PROPS, TOOLTIP_PROPS } from '../../../components/dashboard/constants';
import { Segmented } from '../../../components/rca/RcaShared';
import { useApiQuery } from '../../../hooks/useApiQuery';
import { fetchKpiTrends } from '../api';
import { count, hours, pct } from '../format';
import type { Granularity, KpiTrendPoint } from '../types';

const VIEWS: [Granularity, string][] = [['day', 'Day-wise'], ['week', 'Week-wise'], ['month', 'Month-wise']];

/**
 * Day-, week- and month-wise trend from the canonical daily records. Availability is outage-weighted over the site-days
 * reported in each period (never an average of daily percentages); USD / NSLA count distinct O&M Start sites.
 */
export function TrendPanel({ query, kind }: { query: URLSearchParams; kind: 'availability' | 'outage' }) {
  const [view, setView] = useState<Granularity>('day');
  const params = new URLSearchParams(query);
  params.set('granularity', view);
  const trend = useApiQuery(`allkpis-trend-${params}`, (signal) => fetchKpiTrends(params, signal));
  const points = trend.data?.points ?? [];
  const title = kind === 'availability' ? 'Availability trend' : 'Outage, USD and NSLA trend';
  return (
    <ChartCard title={title} loading={trend.loading} error={trend.error} empty={!points.length}
      description={view === 'month' ? 'Every month with daily data (the latest may be month to date).' : 'Within the selected reporting period.'}
      action={<Segmented label="Trend granularity" value={view} onChange={setView} options={VIEWS} />}>
      <div className="h-72">
        <ResponsiveContainer width="100%" height="100%">
          <ComposedChart data={points} margin={{ top: 8, right: 8, bottom: 0, left: 0 }}>
            <CartesianGrid strokeDasharray="3 3" vertical={false} />
            <XAxis dataKey="label" tick={AXIS_TICK} interval="preserveStartEnd" />
            {kind === 'availability' ? (
              <>
                <YAxis yAxisId="a" tick={AXIS_TICK} domain={['auto', 100]} unit="%" width={48} />
                <YAxis yAxisId="c" orientation="right" tick={AXIS_TICK} domain={[0, 100]} unit="%" width={44} />
                <Line yAxisId="a" dataKey="availability_pct" name="Availability %" stroke="var(--primary)" strokeWidth={2} dot={false} connectNulls={false} />
                <Line yAxisId="c" dataKey="coverage_pct" name="Reporting coverage %" stroke="var(--chart-3)" strokeDasharray="4 3" dot={false} />
              </>
            ) : (
              <>
                <YAxis yAxisId="h" tick={AXIS_TICK} width={56} />
                <YAxis yAxisId="s" orientation="right" tick={AXIS_TICK} width={44} />
                <Bar yAxisId="h" dataKey="outage_hours" name="Outage hours" fill="var(--chart-2)" radius={[3, 3, 0, 0]} />
                <Line yAxisId="s" dataKey="usd_sites" name="USD sites" stroke="var(--destructive)" strokeWidth={2} dot={false} />
                <Line yAxisId="s" dataKey="nsla_sites" name="NSLA sites" stroke="var(--chart-4)" strokeWidth={2} dot={false} />
              </>
            )}
            <Tooltip {...TOOLTIP_PROPS} />
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
    <div className="mt-3 max-h-72 overflow-auto">
      <Table className="text-xs">
        <TableHeader>
          <TableRow>
            <TableHead>Period</TableHead><TableHead className="text-right">Days</TableHead>
            {kind === 'availability'
              ? <><TableHead className="text-right">Availability</TableHead><TableHead className="text-right">Coverage</TableHead><TableHead className="text-right">Missing site-days</TableHead></>
              : <><TableHead className="text-right">Outage</TableHead><TableHead className="text-right">USD sites</TableHead><TableHead className="text-right">NSLA sites</TableHead><TableHead className="text-right">Below 60%</TableHead></>}
          </TableRow>
        </TableHeader>
        <TableBody>
          {points.map((p) => (
            <TableRow key={p.key}>
              <TableCell>{p.label}</TableCell><TableCell className="text-right tabular-nums">{p.days}</TableCell>
              {kind === 'availability' ? (
                <><TableCell className="text-right tabular-nums">{pct(p.availability_pct, 3)}</TableCell><TableCell className="text-right tabular-nums">{pct(p.coverage_pct, 1)}</TableCell>
                  <TableCell className="text-right tabular-nums">{count(p.missing_site_days)}</TableCell></>
              ) : (
                <><TableCell className="text-right tabular-nums">{hours(p.outage_hours)}</TableCell><TableCell className="text-right tabular-nums">{count(p.usd_sites)}</TableCell>
                  <TableCell className="text-right tabular-nums">{count(p.nsla_sites)}</TableCell><TableCell className="text-right tabular-nums">{count(p.below_60_sites)}</TableCell></>
              )}
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </div>
  );
}
