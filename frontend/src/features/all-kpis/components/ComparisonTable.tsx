import { TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table';
import { cn } from '@/lib/utils';
import { ChartCard } from '../../../components/dashboard/ChartCard';
import { change, count, hours, NUM, pct } from '../format';
import type { KpiSummary, KpiValues } from '../types';
import { KpiTable } from './KpiTable';

/** [label, key, format, change unit, whether a higher value is better] */
type Row = [string, keyof KpiValues, (v: number | null) => string, 'pts' | '%', boolean];
const ROWS: Row[] = [
  ['Availability', 'availability_pct', (v) => pct(v, 3), 'pts', true],
  ['Outage hours', 'outage_hours', hours, '%', false],
  ['USD sites (O&M Start)', 'usd_sites', count, '%', false],
  ['NSLA sites (O&M Start, < 98.5% on a day)', 'nsla_sites', count, '%', false],
  ['Sites ≥ 98.5% (period)', 'above_98_5_sites', count, '%', true],
  ['Sites < 98.5% (period)', 'below_98_5_sites', count, '%', false],
  ['Sites < 60% (period)', 'below_60_sites', count, '%', false],
  ['Reporting coverage', 'coverage_pct', (v) => pct(v, 1), 'pts', true],
  ['Missing site-days', 'missing_site_days', count, '%', false],
];

/** KPI comparison: the selected period against the same number of days immediately before. */
export function ComparisonTable({ s, keys }: { s: KpiSummary; keys?: (keyof KpiValues)[] }) {
  const rows = keys ? ROWS.filter((r) => keys.includes(r[1])) : ROWS;
  const cur = s.current;
  const prev = s.previous;
  return (
    <ChartCard title="KPI comparison" description={`${s.period?.label} against ${s.previous_period?.label ?? 'the previous period'} (same number of days)`} empty={!cur}>
      <KpiTable>
        <TableHeader>
          <TableRow>
            <TableHead>KPI</TableHead>
            <TableHead className={NUM}>Selected period</TableHead>
            <TableHead className={NUM}>Previous period</TableHead>
            <TableHead className={NUM}>Change</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {rows.map(([label, key, fmt, unit, higherIsBetter]) => {
            const a = (cur?.[key] as number | null) ?? null;
            const b = (prev?.[key] as number | null) ?? null;
            const c = change(a, b, unit);
            const better = c && c.diff !== 0 ? (c.diff > 0) === higherIsBetter : null;
            return (
              <TableRow key={key}>
                <TableCell className="font-medium">{label}</TableCell>
                <TableCell className={cn(NUM, 'font-medium')}>{fmt(a)}</TableCell>
                <TableCell className={cn(NUM, 'text-muted-foreground')}>{prev ? fmt(b) : 'No data'}</TableCell>
                <TableCell className={cn(NUM, better === true && 'text-emerald-700', better === false && 'text-red-700')}>{c?.text ?? '—'}</TableCell>
              </TableRow>
            );
          })}
        </TableBody>
      </KpiTable>
    </ChartCard>
  );
}
