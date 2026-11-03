import { CheckCircle2, Info, ListTree } from 'lucide-react';
import { Bar, BarChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts';
import { Card } from '@/components/ui/card';
import { TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table';
import { cn } from '@/lib/utils';
import { ChartCard } from '../../../components/dashboard/ChartCard';
import { AXIS_TICK, TOOLTIP_PROPS } from '../../../components/dashboard/constants';
import { useApiQuery } from '../../../hooks/useApiQuery';
import { fetchKpiRca } from '../api';
import { count, minutes, NUM } from '../format';
import { KpiTable } from './KpiTable';

/** One colour for the Final Buckets in the chart and the share bars of the tables. */
const BUCKET_FILL = 'var(--chart-1)';

function Status({ configured }: { configured: boolean }) {
  return configured
    ? <span className="inline-flex items-center gap-1 rounded-md bg-emerald-50 px-1.5 py-0.5 text-[11px] font-medium text-emerald-700"><CheckCircle2 className="size-3" aria-hidden="true" />Configured · approved mapping</span>
    : <span className="inline-flex items-center gap-1 rounded-md bg-muted px-1.5 py-0.5 text-[11px] font-medium text-muted-foreground"><Info className="size-3" aria-hidden="true" />Not Configured</span>;
}

/** RCA: the ten approved Final Buckets (existing mapping), Not mapped values, and the ownership groups (not configured yet). */
export function RcaPanel({ query }: { query: URLSearchParams }) {
  const rca = useApiQuery(`allkpis-rca-${query}`, (signal) => fetchKpiRca(query, signal));
  const d = rca.data;
  const buckets = d?.buckets ?? [];
  const maxShare = Math.max(0, ...buckets.map((b) => b.share_pct ?? 0));
  return (
    <div className="space-y-4">
      <section aria-label="RCA ownership" className="space-y-2.5">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <h2 className="flex items-center gap-2 text-sm font-semibold"><ListTree className="size-4 text-muted-foreground" aria-hidden="true" />RCA ownership</h2>
          <Status configured={false} />
        </div>
        <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
          {['Own', 'Customer', 'Third Party', 'Pending'].map((g) => (
            <Card key={g} role="group" aria-label={g} className="min-h-24 gap-1.5 border border-dashed bg-muted/30 px-4 py-3 shadow-none ring-0">
              <div className="flex items-start justify-between gap-2">
                <p className="text-xs font-medium text-muted-foreground">{g}</p>
                <Info className="size-4 text-muted-foreground/70" aria-hidden="true" />
              </div>
              <p className="text-sm font-medium text-muted-foreground">Not Configured</p>
              <p className="mt-auto text-[11px] text-muted-foreground">No approved Final Bucket mapping</p>
            </Card>
          ))}
        </div>
        <p className="text-xs text-muted-foreground">{d?.ownership?.message ?? 'No approved mapping from Final Buckets to Own / Customer / Third Party / Pending yet.'}</p>
      </section>
      <ChartCard title="RCA Final Bucket distribution" loading={rca.loading} error={rca.error} empty={!d?.records}
        emptyMessage="No RCA records for the selected filters and period."
        description={d ? `${count(d.records)} RCA records · ${d.period?.label ?? ''}` : undefined}
        action={<Status configured />}>
        <div className="grid gap-4 xl:grid-cols-[minmax(0,5fr)_minmax(0,6fr)]">
          <div className="h-80">
            <ResponsiveContainer width="100%" height="100%">
              <BarChart data={buckets} layout="vertical" margin={{ top: 4, right: 16, bottom: 0, left: 4 }}>
                <CartesianGrid stroke="var(--border)" strokeDasharray="3 3" horizontal={false} />
                <XAxis type="number" tick={AXIS_TICK} tickLine={false} axisLine={false} allowDecimals={false} />
                <YAxis type="category" dataKey="bucket" tick={AXIS_TICK} tickLine={false} axisLine={false} width={112} interval={0} />
                <Tooltip {...TOOLTIP_PROPS} cursor={{ fill: 'var(--muted)', opacity: 0.6 }} formatter={(v) => [`${count(Number(v))} records`, 'RCA records']} />
                <Bar dataKey="records" name="RCA records" fill={BUCKET_FILL} radius={[0, 3, 3, 0]} maxBarSize={18} isAnimationActive={false} />
              </BarChart>
            </ResponsiveContainer>
          </div>
          <KpiTable maxHeight="max-h-80">
            <TableHeader>
              <TableRow><TableHead>Final Bucket</TableHead><TableHead className={NUM}>Records</TableHead><TableHead className="w-40">Share</TableHead><TableHead className={NUM}>Outage (RCA)</TableHead></TableRow>
            </TableHeader>
            <TableBody>
              {buckets.map((b) => (
                <TableRow key={b.bucket}>
                  <TableCell className="font-medium">{b.bucket}</TableCell>
                  <TableCell className={cn(NUM, !b.records && 'text-muted-foreground')}>{count(b.records)}</TableCell>
                  <TableCell>
                    {b.share_pct == null ? <span className="text-muted-foreground">—</span> : (
                      <span className="flex items-center gap-2">
                        <span className="h-1.5 w-20 overflow-hidden rounded-full bg-muted" aria-hidden="true">
                          <span className="block h-full rounded-full" style={{ width: `${maxShare ? (100 * b.share_pct) / maxShare : 0}%`, background: BUCKET_FILL }} />
                        </span>
                        <span className="tabular-nums">{b.share_pct}%</span>
                      </span>
                    )}
                  </TableCell>
                  <TableCell className={NUM}>{minutes(b.outage_minutes)}</TableCell>
                </TableRow>
              ))}
              {!!d?.not_mapped?.records && (
                <TableRow className="bg-amber-50/50">
                  <TableCell className="whitespace-normal text-amber-800">
                    <span className="font-medium">Not mapped</span>
                    <span className="block text-[11px]">{d.not_mapped.values.map((v) => v.final_bucket).join(', ')}</span>
                  </TableCell>
                  <TableCell className={NUM}>{count(d.not_mapped.records)}</TableCell><TableCell /><TableCell />
                </TableRow>
              )}
            </TableBody>
          </KpiTable>
        </div>
      </ChartCard>
      {!!d?.by_circle?.length && (
        <ChartCard title="RCA Final Buckets by circle" description="RCA records per circle and approved Final Bucket">
          <KpiTable>
            <TableHeader>
              <TableRow><TableHead>Circle</TableHead><TableHead className={NUM}>Records</TableHead>{buckets.map((b) => <TableHead key={b.bucket} className={NUM}>{b.bucket}</TableHead>)}</TableRow>
            </TableHeader>
            <TableBody>
              {d.by_circle.map((c) => (
                <TableRow key={c.circle}>
                  <TableCell className="font-medium">{c.circle}</TableCell><TableCell className={cn(NUM, 'font-medium')}>{count(c.records)}</TableCell>
                  {buckets.map((b) => (
                    <TableCell key={b.bucket} className={NUM}>{c.buckets[b.bucket] ? count(c.buckets[b.bucket]) : <span className="text-muted-foreground/60">–</span>}</TableCell>
                  ))}
                </TableRow>
              ))}
            </TableBody>
          </KpiTable>
        </ChartCard>
      )}
    </div>
  );
}
