import { Bar, BarChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts';
import { TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table';
import { useApiQuery } from '../../../hooks/useApiQuery';
import { useRcaBucketMappingRevision } from '../../../lib/rcaBucketMapping';
import { fetchKpiRca } from '../api';
import { count, minutes } from '../format';
import { KpiTable } from './KpiTable';
import { Panel, StatusPill } from './Ui';
import { CHART } from './theme';

/**
 * Root cause analysis: current Final Bucket responsibility mapping, approved Final Bucket distribution and circle × Final Bucket table.
 */
export function RcaPanel({ query }: { query: URLSearchParams }) {
  const mappingRevision = useRcaBucketMappingRevision();
  const rca = useApiQuery(`allkpis-rca-${query}-${mappingRevision}`, (signal) => fetchKpiRca(query, signal));
  const d = rca.data;
  const buckets = d?.buckets ?? [];
  const ownership = d?.ownership;
  const maxShare = Math.max(0, ...buckets.map((b) => b.share_pct ?? 0));
  return (
    <>
      <section aria-label="RCA ownership" className="akp-card akp-pad">
        <div className="mb-2 flex flex-wrap items-center justify-between gap-2">
          <h3 className="akp-h" style={{ margin: 0 }}>RCA responsibility</h3>
          <StatusPill tone={ownership?.configured ? 'good' : 'neutral'}>{ownership?.configured ? 'Configured' : 'No mappings'}</StatusPill>
        </div>
        <div className="akp-tiles">
          {(ownership?.buckets ?? []).map((bucket) => (
            <div key={bucket.bucket} role="group" aria-label={bucket.label} className="akp-tile">
              <span className="l">{bucket.label}</span>
              <span className="v">{count(bucket.records)}</span>
              <span className="s">{bucket.share_pct == null ? '—' : `${bucket.share_pct}%`} of records · {minutes(bucket.outage_minutes)}</span>
            </div>
          ))}
        </div>
        <p className="akp-note mt-2">{ownership?.message ?? 'Loading the current Final Bucket mapping.'}</p>
      </section>

      <Panel title="RCA Final Bucket distribution" loading={rca.loading} error={rca.error} empty={!d?.records}
        emptyMessage="No RCA records for the selected filters and period."
        note={d ? `${count(d.records)} RCA records · ${d.period?.label ?? ''} · approved Final Bucket mapping` : undefined}>
        <div className="akp-tiles mb-4" aria-label="Final Buckets">
          {buckets.filter((b) => b.records).map((b) => (
            <div key={b.bucket} role="group" aria-label={`Final Bucket ${b.bucket}`} className="akp-tile" style={{ borderTop: '4px solid var(--akp-accent)' }}>
              <span className="l">{b.bucket}</span>
              <span className="v">{count(b.records)}</span>
              <span className="s">{b.share_pct == null ? '—' : `${b.share_pct}%`} of records · {minutes(b.outage_minutes)}</span>
            </div>
          ))}
        </div>
        <div className="akp-row">
          <div className="h-80" role="img" aria-label="RCA records by Final Bucket">
            <ResponsiveContainer width="100%" height="100%">
              <BarChart data={buckets} layout="vertical" margin={{ top: 4, right: 16, bottom: 0, left: 4 }}>
                <CartesianGrid stroke={CHART.grid} horizontal={false} />
                <XAxis type="number" tick={CHART.tick} tickLine={false} axisLine={false} allowDecimals={false} />
                <YAxis type="category" dataKey="bucket" tick={CHART.tick} tickLine={false} axisLine={false} width={112} interval={0} />
                <Tooltip {...CHART.tooltip} cursor={{ fill: 'var(--akp-hover)' }} formatter={(v) => [`${count(Number(v))} records`, 'RCA records']} />
                <Bar dataKey="records" name="RCA records" fill={CHART.accent} radius={[0, 4, 4, 0]} maxBarSize={18} isAnimationActive={false} />
              </BarChart>
            </ResponsiveContainer>
          </div>
          <KpiTable maxHeight={320}>
            <TableHeader>
              <TableRow><TableHead>Final Bucket</TableHead><TableHead className="r">Records</TableHead><TableHead>Share</TableHead><TableHead className="r">Outage (RCA)</TableHead></TableRow>
            </TableHeader>
            <TableBody>
              {buckets.map((b) => (
                <TableRow key={b.bucket}>
                  <TableCell className="font-medium">{b.bucket}</TableCell>
                  <TableCell className={b.records ? 'r' : 'r muted'}>{count(b.records)}</TableCell>
                  <TableCell>
                    {b.share_pct == null ? <span className="muted">—</span> : (
                      <span className="flex items-center gap-2">
                        <span className="akp-hb" style={{ minWidth: 80 }} aria-hidden="true"><b style={{ width: `${maxShare ? (100 * b.share_pct) / maxShare : 0}%` }} /></span>
                        <span className="num">{b.share_pct}%</span>
                      </span>
                    )}
                  </TableCell>
                  <TableCell className="r">{minutes(b.outage_minutes)}</TableCell>
                </TableRow>
              ))}
              {!!d?.not_mapped?.records && (
                <TableRow className="bottom">
                  <TableCell className="whitespace-normal">
                    <span className="font-medium">Not mapped</span>
                    <span className="sub">{d.not_mapped.values.map((v) => v.final_bucket).join(', ')}</span>
                  </TableCell>
                  <TableCell className="r">{count(d.not_mapped.records)}</TableCell><TableCell /><TableCell />
                </TableRow>
              )}
            </TableBody>
          </KpiTable>
        </div>
      </Panel>

      {!!d?.by_circle?.length && (
        <Panel title="RCA Final Buckets by circle" note="RCA records per circle and approved Final Bucket">
          <KpiTable>
            <TableHeader>
              <TableRow><TableHead>Circle</TableHead><TableHead className="r">Records</TableHead>{buckets.map((b) => <TableHead key={b.bucket} className="r">{b.bucket}</TableHead>)}</TableRow>
            </TableHeader>
            <TableBody>
              {d.by_circle.map((c) => (
                <TableRow key={c.circle}>
                  <TableCell className="font-medium">{c.circle}</TableCell><TableCell className="r font-semibold">{count(c.records)}</TableCell>
                  {buckets.map((b) => (
                    <TableCell key={b.bucket} className="r">{c.buckets[b.bucket] ? count(c.buckets[b.bucket]) : <span className="muted">–</span>}</TableCell>
                  ))}
                </TableRow>
              ))}
            </TableBody>
          </KpiTable>
        </Panel>
      )}
    </>
  );
}
