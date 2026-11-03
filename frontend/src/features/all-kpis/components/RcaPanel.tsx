import { Bar, BarChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts';
import { Card } from '@/components/ui/card';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table';
import { ChartCard } from '../../../components/dashboard/ChartCard';
import { AXIS_TICK, TOOLTIP_PROPS } from '../../../components/dashboard/constants';
import { useApiQuery } from '../../../hooks/useApiQuery';
import { fetchKpiRca } from '../api';
import { count, minutes } from '../format';

/** RCA: the ten approved Final Buckets (existing mapping), Not mapped values, and the ownership groups (not configured yet). */
export function RcaPanel({ query }: { query: URLSearchParams }) {
  const rca = useApiQuery(`allkpis-rca-${query}`, (signal) => fetchKpiRca(query, signal));
  const d = rca.data;
  const buckets = d?.buckets ?? [];
  return (
    <div className="space-y-4">
      <section aria-label="RCA ownership" className="space-y-2">
        <h2 className="text-xs font-semibold tracking-[0.14em] text-muted-foreground uppercase">RCA ownership</h2>
        <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
          {['Own', 'Customer', 'Third Party', 'Pending'].map((g) => (
            <Card key={g} role="group" aria-label={g} className="gap-1 px-4 py-3">
              <p className="text-xs font-medium text-muted-foreground">{g}</p>
              <p className="text-base font-medium text-muted-foreground">Not Configured</p>
            </Card>
          ))}
        </div>
        <p className="text-xs text-muted-foreground">{d?.ownership?.message ?? 'No approved mapping from Final Buckets to Own / Customer / Third Party / Pending yet.'}</p>
      </section>
      <ChartCard title="RCA Final Bucket distribution" loading={rca.loading} error={rca.error} empty={!d?.records}
        description={d ? `${count(d.records)} RCA records · ${d.period?.label ?? ''} · approved Final Bucket mapping` : undefined}>
        <div className="h-72">
          <ResponsiveContainer width="100%" height="100%">
            <BarChart data={buckets} layout="vertical" margin={{ top: 4, right: 16, bottom: 0, left: 8 }}>
              <CartesianGrid strokeDasharray="3 3" horizontal={false} />
              <XAxis type="number" tick={AXIS_TICK} />
              <YAxis type="category" dataKey="bucket" tick={AXIS_TICK} width={96} />
              <Tooltip {...TOOLTIP_PROPS} />
              <Bar dataKey="records" name="RCA records" fill="var(--primary)" radius={[0, 3, 3, 0]} />
            </BarChart>
          </ResponsiveContainer>
        </div>
        <div className="mt-3 overflow-x-auto">
          <Table className="text-xs">
            <TableHeader><TableRow><TableHead>Final Bucket</TableHead><TableHead className="text-right">Records</TableHead><TableHead className="text-right">Share</TableHead><TableHead className="text-right">Outage (RCA)</TableHead></TableRow></TableHeader>
            <TableBody>
              {buckets.map((b) => (
                <TableRow key={b.bucket}>
                  <TableCell>{b.bucket}</TableCell><TableCell className="text-right tabular-nums">{count(b.records)}</TableCell>
                  <TableCell className="text-right tabular-nums">{b.share_pct == null ? '—' : `${b.share_pct}%`}</TableCell>
                  <TableCell className="text-right tabular-nums">{minutes(b.outage_minutes)}</TableCell>
                </TableRow>
              ))}
              {!!d?.not_mapped?.records && (
                <TableRow>
                  <TableCell className="text-muted-foreground">Not mapped ({d.not_mapped.values.map((v) => v.final_bucket).join(', ')})</TableCell>
                  <TableCell className="text-right tabular-nums">{count(d.not_mapped.records)}</TableCell><TableCell /><TableCell />
                </TableRow>
              )}
            </TableBody>
          </Table>
        </div>
      </ChartCard>
      {!!d?.by_circle?.length && (
        <ChartCard title="RCA Final Buckets by circle">
          <div className="overflow-x-auto">
            <Table className="text-xs">
              <TableHeader>
                <TableRow><TableHead>Circle</TableHead><TableHead className="text-right">Records</TableHead>{buckets.map((b) => <TableHead key={b.bucket} className="text-right whitespace-nowrap">{b.bucket}</TableHead>)}</TableRow>
              </TableHeader>
              <TableBody>
                {d.by_circle.map((c) => (
                  <TableRow key={c.circle}>
                    <TableCell className="font-medium">{c.circle}</TableCell><TableCell className="text-right tabular-nums">{count(c.records)}</TableCell>
                    {buckets.map((b) => <TableCell key={b.bucket} className="text-right tabular-nums">{c.buckets[b.bucket] ? count(c.buckets[b.bucket]) : ''}</TableCell>)}
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </div>
        </ChartCard>
      )}
    </div>
  );
}
