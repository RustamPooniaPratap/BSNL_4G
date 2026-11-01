import { Info } from 'lucide-react';
import { Card } from '@/components/ui/card';
import { cn } from '@/lib/utils';
import { formatDate, formatNumber } from '../../lib/format';
import type { RcaBreakdown, RcaSiteMetrics } from '../../types/rca';

/** Whole percentages as in the workbook; a non-zero share below 0.5% reads "<1%" rather than a misleading 0%. */
const formatShare = (value: number | null) => {
  if (value === null) return '';
  if (value > 0 && value < 0.5) return '<1%';
  return `${Math.round(value)}%`;
};
const cell = (value: number | null | undefined) => (value === null || value === undefined ? '' : formatNumber(value));

/**
 * Circle-wise Root Cause Breakdown (the RCA workbook's "RCA Analysis - Updated" table), computed on the server from
 * the filtered RCA records. Empty cells mean "no data", never zero: circles without records.
 */
const SITE_COLUMNS = [
  { key: 'total_sites', label: 'Total Sites', title: 'Active sites (On-Air = Yes) in the Site Master' },
  { key: 'usd_sites', label: 'USD Sites', title: 'Unique Sites Down: outage above 0 minutes at least once in the period (as the Overview KPI)' },
  { key: 'nsla_sites', label: 'NSLA Sites (<98.5%)', title: 'Sites whose uptime over the period is below 98.5%' },
] as const;

export function RootCauseBreakdown({ data }: { data: RcaBreakdown }) {
  const { columns } = data;
  const sticky = 'sticky left-0 z-10';
  const sites = data.sites ?? null;
  // Site Master and performance figures (not RCA records); empty when the dashboard has no data.
  const siteCells = (m: RcaSiteMetrics | undefined, cls: string) => SITE_COLUMNS.map((c) => (
    <td key={c.key} className={cn(cls, 'px-2 py-1.5 text-center')}>{m ? cell(m[c.key]) : ''}</td>
  ));
  return (
    <Card className="gap-0 overflow-hidden p-0" role="region" aria-label="Circle-wise Root Cause Breakdown">
      {/* Title bands as in the workbook ("RCA Analysis - Updated"): navy title, green "Root Cause Breakdown | Through …". */}
      <div className="bg-[#1f3864] px-4 py-2 text-center text-white">
        <h2 className="text-base font-semibold">Circle-wise Root Cause Breakdown</h2>
      </div>
      <p className="border-b bg-[#548235] px-4 py-1 text-center text-xs font-semibold text-white">
        <span>Root Cause Breakdown | </span><span>{data.through ? `Through ${formatDate(data.through)}` : 'No reporting date'} · Final Bucket, filtered as above</span>
      </p>
      {data.empty ? (
        <p className="px-4 py-8 text-center text-sm text-muted-foreground">No RCA records match these filters.</p>
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full min-w-[1400px] border-collapse text-xs tabular-nums" aria-label="Root cause breakdown by circle">
            <thead>
              <tr className="bg-[#2e75b6] text-white">
                <th scope="col" className={cn(sticky, 'min-w-28 border border-white/30 bg-[#2e75b6] px-2 py-2 text-left')}>Circle</th>
                {SITE_COLUMNS.map((c) => (
                  <th key={c.key} scope="col" title={c.title} className="min-w-20 border border-white/30 bg-[#305496] px-1.5 py-2 text-center leading-tight font-semibold">{c.label}</th>
                ))}
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
                {SITE_COLUMNS.map((c) => <td key={c.key} className="border border-white/30 bg-[#bf8f00] px-2 py-1.5" />)}
                {columns.map((c) => <td key={c.label} className="border border-white/30 px-1.5 py-1.5 text-center">{formatShare(data.percent_of_total[c.label])}</td>)}
                <td className="border border-white/30 bg-[#548235] px-2 py-1.5 text-center">{data.grand_total ? '100%' : ''}</td>
                <td className="border border-white/30 bg-slate-500 px-2 py-1.5" />
              </tr>
              <tr className="bg-[#1f3864] font-semibold text-white" aria-label="Total">
                <th scope="row" className={cn(sticky, 'border border-white/30 bg-[#1f3864] px-2 py-1.5 text-left')}>Total</th>
                {siteCells(sites?.total, 'border border-white/30 bg-[#305496]')}
                {columns.map((c) => <td key={c.label} className="border border-white/30 px-1.5 py-1.5 text-center">{cell(data.totals[c.label])}</td>)}
                <td className="border border-white/30 bg-[#548235] px-2 py-1.5 text-center">{formatNumber(data.grand_total)}</td>
                <td className="border border-white/30 bg-slate-500 px-2 py-1.5 text-center">{formatNumber(data.not_mapped.records)}</td>
              </tr>
              {data.rows.map((r) => (
                <tr key={r.circle} className="bg-amber-50/60 hover:bg-amber-100/60" aria-label={`Circle ${r.circle}`}>
                  <th scope="row" className={cn(sticky, 'border border-amber-200 bg-amber-50 px-2 py-1.5 text-left font-semibold')}>{r.circle}</th>
                  {siteCells(sites?.rows[r.circle], 'border border-amber-200 bg-[#ddebf7] font-medium')}
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
            Empty cells: circles without records.
            {sites && ` Total, USD and NSLA Sites: active sites of the Site Master and their daily performance for ${sites.period.label}
              (${sites.period.days_reported} day${sites.period.days_reported === 1 ? '' : 's'} with data), by project, circle and reporting date only: the
              Final Bucket, Bucket - 2, category and RCA filters apply to RCA records, not to sites.`}
            {data.not_mapped.records > 0 && ` Not mapped (outside the Grand Total): ${data.not_mapped.values.map((v) => `${v.final_bucket} ${formatNumber(v.records)}`).join(', ')}.`}
          </span>
        </p>
      )}
    </Card>
  );
}
