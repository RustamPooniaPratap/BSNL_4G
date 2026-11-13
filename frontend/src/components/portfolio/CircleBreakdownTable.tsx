import { useState } from 'react';
import { Check, Info, Pencil, X } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Popover, PopoverContent, PopoverTrigger } from '@/components/ui/popover';
import { cn } from '@/lib/utils';
import type { PortfolioNote } from '../../context/tracking';
import { formatNumber } from '../../lib/format';
import { reportTypeColor } from '../dashboard/constants';
import type { CircleBreakdownGroup, CircleBreakdownRow, PortfolioCounts, TeamFigures } from '../../lib/portfolio';

type Figures = PortfolioCounts & TeamFigures;
const NUMERIC: { key: keyof Figures; label: string; title?: string }[] = [
  { key: 'siteScope', label: 'Site Scope' },
  { key: 'onAir', label: 'On Air' },
  { key: 'omStart', label: 'O&M Start' },
  { key: 'gapTotal', label: 'Gap against Total Sites' },
  { key: 'gapOnAir', label: 'Gap against On Air Sites' },
  { key: 'ciCount', label: 'CIs', title: 'Distinct CI names assigned to sites in the selected population' },
  { key: 'ieCount', label: 'IEs', title: 'Distinct IE names assigned to sites in the selected population' },
  { key: 'sitesPerCi', label: 'Sites per CI', title: 'Selected-population site count ÷ CIs' },
  { key: 'sitesPerIe', label: 'Sites per IE', title: 'Selected-population site count ÷ IEs' },
];
const DECIMALS = new Set<keyof Figures>(['sitesPerCi', 'sitesPerIe']);
const client = (reportType: string) => (reportType === '4G Saturation' ? '4G' : reportType);
const num = (v: number | null, key?: keyof Figures) => (v == null ? '—'
  : key && DECIMALS.has(key) ? v.toLocaleString('en-IN', { minimumFractionDigits: 1, maximumFractionDigits: 1 }) : formatNumber(v));
// The gap columns and the team columns each start a new block, as in the Excel sheet.
const gapEdge = (key: keyof Figures) => (key === 'gapTotal' || key === 'ciCount') && 'border-l-2 border-l-primary/40';
const cell = 'border-b border-border/70 px-2.5 py-1 align-top';
// Column headers: compact 11 px labels that may wrap onto two lines, aligned to the bottom of the header row.
const head = 'px-2.5 py-1.5 align-bottom text-[11px] leading-tight font-semibold';

/** Circle-wise Site Scope / On Air / O&M Start, grouped 4G then LWE, laid out like the "first page" sheet. */
export function CircleBreakdownTable({ groups, total, notes, onSaveNote, periodNote, loading }: {
  groups: CircleBreakdownGroup[]; total: Figures; notes: Record<string, PortfolioNote>;
  onSaveNote: (key: string, note: PortfolioNote) => void; periodNote: string; loading?: boolean;
}) {
  const [editing, setEditing] = useState<string | null>(null);
  const [draft, setDraft] = useState<PortfolioNote>({ remarks: '' });
  const keyOf = (r: CircleBreakdownRow) => `${r.reportType}|${r.circle}`;
  const startEdit = (r: CircleBreakdownRow) => {
    setEditing(keyOf(r));
    const note = notes[keyOf(r)];
    setDraft({ remarks: note?.remarks ?? '' });
  };
  const save = () => { if (editing) onSaveNote(editing, { remarks: draft.remarks.trim() }); setEditing(null); };

  return (
    <Card role="region" aria-label="Circle-wise Site Portfolio Breakdown" className={cn('gap-2.5 [--card-spacing:--spacing(3)]', loading && 'opacity-60')}>
      <CardHeader>
        <CardTitle className="flex items-center gap-1.5 text-sm font-semibold">
          Circle-wise Site Portfolio Breakdown
          <Popover>
            <PopoverTrigger className="rounded-full text-muted-foreground hover:text-foreground focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none"
              aria-label="How the breakdown is calculated">
              <Info className="size-3.5" />
            </PopoverTrigger>
            <PopoverContent className="w-80 space-y-1.5 text-xs font-normal">
              <p>{periodNote}</p>
              <p>O&amp;M Head: active Users &amp; Roles assignments for this project and circle.</p>
              <p>Gap against Total Sites = Site Scope − O&amp;M Start; Gap against On Air Sites = On Air − O&amp;M Start.</p>
              <p>CIs and IEs are the distinct names assigned to sites in the selected On-Air / O&amp;M Start population. In subtotals and the total a person in several circles counts once, so they are not sums of the rows. Sites per CI / IE = selected-population site count ÷ CIs / IEs.</p>
            </PopoverContent>
          </Popover>
        </CardTitle>
        <CardDescription className="text-xs">Current flags, not daily figures. Remarks are held in this browser only.</CardDescription>
      </CardHeader>
      <CardContent className="px-0">
        <div className="overflow-x-auto">
          <table className="w-full min-w-[68rem] border-collapse text-xs tabular-nums">
            <caption className="sr-only">Site Scope, On Air and O&amp;M Start by circle with gaps</caption>
            <thead>
              <tr aria-label="Portfolio totals" className="bg-primary text-primary-foreground">
                <td colSpan={3} className="px-2.5 py-1" />
                {NUMERIC.map((n) => (
                  <td key={n.key} className={cn('px-2.5 py-1 text-right text-[13px] font-semibold', gapEdge(n.key))} data-testid={`strip-${n.key}`}>
                    {num(total[n.key], n.key)}
                  </td>
                ))}
                <td className="px-2.5 py-1" />
              </tr>
              <tr className="bg-primary/85 text-primary-foreground">
                {['Circle', 'Client', 'O&M Head'].map((h) => <th key={h} scope="col" className={cn(head, 'text-left')}>{h}</th>)}
                {NUMERIC.map((n) => (
                  <th key={n.key} scope="col" title={n.title} className={cn(head, 'text-right', gapEdge(n.key))}>{n.label}</th>
                ))}
                <th scope="col" className={cn(head, 'w-[24%] text-left')}>Remarks</th>
              </tr>
            </thead>
            {groups.map((g) => (
              <tbody key={g.reportType} aria-label={`${g.reportType} circles`}>
                {g.rows.map((r) => {
                  const note = notes[keyOf(r)];
                  const isEditing = editing === keyOf(r);
                  return (
                    <tr key={keyOf(r)} className="hover:bg-muted/40">
                      <th scope="row" className={cn(cell, 'text-left font-medium')}>{r.circle}</th>
                      <td className={cell}>
                        <span className="inline-flex items-center gap-1.5 whitespace-nowrap">
                          <span className="size-2 shrink-0 rounded-full" style={{ background: reportTypeColor(r.reportType) }} aria-hidden="true" />{client(r.reportType)}
                        </span>
                      </td>
                      <td className={cn(cell, 'whitespace-nowrap')}>
                        {r.omHeads.length ? r.omHeads.join(', ') : <span className="text-muted-foreground">—</span>}
                      </td>
                      {NUMERIC.map((n) => (
                        <td key={n.key} className={cn(cell, 'text-right', gapEdge(n.key), (n.key === 'gapTotal' || n.key === 'gapOnAir') && (r[n.key] ?? 0) > 0 && 'font-medium')}>
                          {num(r[n.key], n.key)}
                        </td>
                      ))}
                      <td className={cn(cell, 'whitespace-normal')}>
                        {isEditing ? (
                          <div className="flex items-start gap-1">
                            <textarea aria-label={`Remarks for ${r.circle} ${client(r.reportType)}`} value={draft.remarks} maxLength={300} rows={2}
                              className="min-h-7 w-full rounded-md border border-input bg-transparent px-2 py-1 text-xs"
                              onChange={(e) => setDraft((d) => ({ ...d, remarks: e.target.value }))} />
                            <Button size="icon" variant="ghost" className="size-7" aria-label="Save" onClick={save}><Check /></Button>
                            <Button size="icon" variant="ghost" className="size-7" aria-label="Cancel" onClick={() => setEditing(null)}><X /></Button>
                          </div>
                        ) : (
                          <div className="flex items-start justify-between gap-2">
                            <span className="break-words">{note?.remarks || <span className="text-muted-foreground">—</span>}</span>
                            <Button size="icon" variant="ghost" className="size-6 shrink-0" aria-label={`Edit Remarks for ${r.circle} ${client(r.reportType)}`}
                              onClick={() => startEdit(r)}><Pencil className="size-3" /></Button>
                          </div>
                        )}
                      </td>
                    </tr>
                  );
                })}
                <tr className="bg-muted/70 font-semibold" aria-label={`${client(g.reportType)} subtotal`}>
                  <th scope="row" colSpan={3} className="border-b px-2.5 py-1 text-left">{client(g.reportType)} subtotal</th>
                  {NUMERIC.map((n) => <td key={n.key} className={cn('border-b px-2.5 py-1 text-right', gapEdge(n.key))}>{num(g.subtotal[n.key], n.key)}</td>)}
                  <td className="border-b" />
                </tr>
              </tbody>
            ))}
            <tfoot>
              <tr className="bg-primary/10 text-[13px] font-semibold" aria-label="Overall total">
                <th scope="row" colSpan={3} className="px-2.5 py-1.5 text-left">Overall total</th>
                {NUMERIC.map((n) => <td key={n.key} className={cn('px-2.5 py-1.5 text-right', gapEdge(n.key))}>{num(total[n.key], n.key)}</td>)}
                <td />
              </tr>
            </tfoot>
          </table>
        </div>
      </CardContent>
    </Card>
  );
}
