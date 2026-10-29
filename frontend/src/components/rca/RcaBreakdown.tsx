import { Info } from 'lucide-react';
import { Card } from '@/components/ui/card';
import { cn } from '@/lib/utils';
import { formatDate, formatNumber } from '../../lib/format';
import type { RcaBreakdown } from '../../types/rca';

/** Whole percentages as in the workbook; a non-zero share below 0.5% reads "<1%" rather than a misleading 0%. */
const formatShare = (value: number | null) => {
  if (value === null) return '';
  if (value > 0 && value < 0.5) return '<1%';
  return `${Math.round(value)}%`;
};
const cell = (value: number | null | undefined) => (value === null || value === undefined ? '' : formatNumber(value));

/**
 * Circle-wise Root Cause Breakdown (the RCA workbook's "RCA Analysis - Updated" table), computed on the server from
 * the filtered RCA records. Empty cells mean "no data", never zero: circles without records, and BSNL-Link, which is
 * pending until the updated workbook defines it.
 */
export function RootCauseBreakdown({ data }: { data: RcaBreakdown }) {
  const { columns } = data;
  const sticky = 'sticky left-0 z-10';
  return (
    <Card className="gap-0 overflow-hidden p-0" role="region" aria-label="Circle-wise Root Cause Breakdown">
      <div className="border-b bg-[#1f3864] px-4 py-2.5 text-center text-white">
        <h2 className="text-base font-semibold">Circle-wise Root Cause Breakdown</h2>
        <p className="text-xs text-white/80">{data.through ? `Through ${formatDate(data.through)}` : 'No reporting date'} · Final Bucket, filtered as above</p>
      </div>
      {data.empty ? (
        <p className="px-4 py-8 text-center text-sm text-muted-foreground">No RCA records match these filters.</p>
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full min-w-[1400px] border-collapse text-xs tabular-nums" aria-label="Root cause breakdown by circle">
            <thead>
              <tr className="bg-[#2e75b6] text-white">
                <th scope="col" className={cn(sticky, 'min-w-28 border border-white/30 bg-[#2e75b6] px-2 py-2 text-left')}>Circle</th>
                {columns.map((c) => (
                  <th key={c.label} scope="col" title={c.pending ? 'Pending: to be defined by the updated RCA workbook' : `Final Bucket: ${c.final_buckets.join(', ')}`}
                    className={cn('border border-white/30 px-1.5 py-2 text-center leading-tight font-semibold', c.label.startsWith('BSNL') || c.label.startsWith('BBNL') ? 'bg-[#c55a11]' : '')}>
                    {c.label}{c.pending && <span className="block text-[10px] font-normal opacity-80">pending</span>}
                  </th>
                ))}
                <th scope="col" className="border border-white/30 bg-[#548235] px-2 py-2 text-center">Grand Total</th>
                <th scope="col" className="border border-white/30 bg-slate-500 px-2 py-2 text-center" title="Final Bucket values outside every column (not in the Grand Total)">Not mapped</th>
              </tr>
            </thead>
            <tbody>
              <tr className="bg-[#bf8f00] font-semibold text-white" aria-label="RCA % of Total">
                <th scope="row" className={cn(sticky, 'border border-white/30 bg-[#bf8f00] px-2 py-1.5 text-left')}>RCA % of Total</th>
                {columns.map((c) => <td key={c.label} className="border border-white/30 px-1.5 py-1.5 text-center">{formatShare(data.percent_of_total[c.label])}</td>)}
                <td className="border border-white/30 bg-[#548235] px-2 py-1.5 text-center">{data.grand_total ? '100%' : ''}</td>
                <td className="border border-white/30 bg-slate-500 px-2 py-1.5" />
              </tr>
              <tr className="bg-[#1f3864] font-semibold text-white" aria-label="Total">
                <th scope="row" className={cn(sticky, 'border border-white/30 bg-[#1f3864] px-2 py-1.5 text-left')}>Total</th>
                {columns.map((c) => <td key={c.label} className="border border-white/30 px-1.5 py-1.5 text-center">{cell(data.totals[c.label])}</td>)}
                <td className="border border-white/30 bg-[#548235] px-2 py-1.5 text-center">{formatNumber(data.grand_total)}</td>
                <td className="border border-white/30 bg-slate-500 px-2 py-1.5 text-center">{formatNumber(data.not_mapped.records)}</td>
              </tr>
              {data.rows.map((r) => (
                <tr key={r.circle} className="bg-amber-50/60 hover:bg-amber-100/60" aria-label={`Circle ${r.circle}`}>
                  <th scope="row" className={cn(sticky, 'border border-amber-200 bg-amber-50 px-2 py-1.5 text-left font-semibold')}>{r.circle}</th>
                  {columns.map((c) => <td key={c.label} className="border border-amber-200 px-1.5 py-1.5 text-center">{cell(r.counts[c.label])}</td>)}
                  <td className="border border-amber-200 bg-[#e2efda] px-2 py-1.5 text-center font-semibold">{cell(r.grand_total)}</td>
                  <td className="border border-amber-200 px-2 py-1.5 text-center text-muted-foreground">{cell(r.not_mapped)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {!data.empty && (
        <p className="flex items-start gap-1.5 border-t px-4 py-2 text-[11px] text-muted-foreground">
          <Info className="mt-px size-3.5 shrink-0" aria-hidden="true" />
          <span>
            Records per circle by Final Bucket; each record counted once. % = column total ÷ Grand Total.
            Empty cells: circles without records, and BSNL-Link (pending the updated workbook).
            {data.not_mapped.records > 0 && ` Not mapped (outside the Grand Total): ${data.not_mapped.values.map((v) => `${v.final_bucket} ${formatNumber(v.records)}`).join(', ')}.`}
          </span>
        </p>
      )}
    </Card>
  );
}
