import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table';
import { ChartCard } from '../../../components/dashboard/ChartCard';
import { change, count, hours, pct } from '../format';
import type { KpiSummary, KpiValues } from '../types';

type Row = [string, keyof KpiValues, (v: number | null) => string, 'pts' | '%'];
const ROWS: Row[] = [
  ['Availability', 'availability_pct', (v) => pct(v, 3), 'pts'],
  ['Outage hours', 'outage_hours', hours, '%'],
  ['USD sites (O&M Start)', 'usd_sites', count, '%'],
  ['NSLA sites (O&M Start, < 98.5% on a day)', 'nsla_sites', count, '%'],
  ['Sites ≥ 98.5% (period)', 'above_98_5_sites', count, '%'],
  ['Sites < 98.5% (period)', 'below_98_5_sites', count, '%'],
  ['Sites < 60% (period)', 'below_60_sites', count, '%'],
  ['Reporting coverage', 'coverage_pct', (v) => pct(v, 1), 'pts'],
  ['Missing site-days', 'missing_site_days', count, '%'],
];

/** KPI comparison: the selected period against the same number of days immediately before. */
export function ComparisonTable({ s, keys }: { s: KpiSummary; keys?: (keyof KpiValues)[] }) {
  const rows = keys ? ROWS.filter((r) => keys.includes(r[1])) : ROWS;
  const cur = s.current;
  const prev = s.previous;
  return (
    <ChartCard title="KPI comparison" description={`${s.period?.label} against ${s.previous_period?.label ?? 'the previous period'}`} empty={!cur}>
      <div className="overflow-x-auto">
        <Table className="text-xs">
          <TableHeader>
            <TableRow><TableHead>KPI</TableHead><TableHead className="text-right">Selected period</TableHead><TableHead className="text-right">Previous period</TableHead><TableHead className="text-right">Change</TableHead></TableRow>
          </TableHeader>
          <TableBody>
            {rows.map(([label, key, fmt, unit]) => {
              const a = (cur?.[key] as number | null) ?? null;
              const b = (prev?.[key] as number | null) ?? null;
              return (
                <TableRow key={key}>
                  <TableCell>{label}</TableCell>
                  <TableCell className="text-right tabular-nums">{fmt(a)}</TableCell>
                  <TableCell className="text-right tabular-nums">{prev ? fmt(b) : 'No data'}</TableCell>
                  <TableCell className="text-right tabular-nums">{change(a, b, unit)?.text ?? '—'}</TableCell>
                </TableRow>
              );
            })}
          </TableBody>
        </Table>
      </div>
    </ChartCard>
  );
}
