import { TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table';
import { usePopulation } from '../../../context/population';
import { count, hours, pct } from '../format';
import type { KpiSummary, KpiValues } from '../types';
import { KpiTable } from './KpiTable';
import { ChangeText, Panel } from './Ui';

/** [label, key, format, change unit, whether a higher value is better] */
type Row = [string, keyof KpiValues, (v: number | null) => string, 'pts' | '%', boolean];
/** Labels name the selected population (``sites``: "On-Air sites" / "O&M Start sites"). */
const rowsFor = (sites: string): Row[] => [
  [`Availability (${sites})`, 'availability_pct', pct, 'pts', true],
  ['Outage hours', 'outage_hours', hours, '%', false],
  [`USD Sites (${sites})`, 'usd_sites', count, '%', false],
  [`NSLA Sites (${sites}, period uptime < 98.5%)`, 'nsla_sites', count, '%', false],
  ['Sites ≥ 98.5% (period)', 'above_98_5_sites', count, '%', true],
  ['Sites < 98.5% (period)', 'below_98_5_sites', count, '%', false],
  ['Sites < 60% (period)', 'below_60_sites', count, '%', false],
];

/** KPI comparison: the selected period against the same number of days immediately before. */
export function ComparisonTable({ s, keys }: { s: KpiSummary; keys?: (keyof KpiValues)[] }) {
  const { sitesLabel } = usePopulation();
  const all = rowsFor(sitesLabel);
  const rows = keys ? all.filter((r) => keys.includes(r[1])) : all;
  const cur = s.current;
  const prev = s.previous;
  return (
    <Panel title="KPI comparison" note={`${s.period?.label} against ${s.previous_period?.label ?? 'the previous period'} (same number of days)`} empty={!cur}>
      <KpiTable>
        <TableHeader>
          <TableRow>
            <TableHead>KPI</TableHead>
            <TableHead className="r">Selected period</TableHead>
            <TableHead className="r">Previous period</TableHead>
            <TableHead className="r">Change</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {rows.map(([label, key, fmt, unit, higherIsBetter]) => {
            const a = (cur?.[key] as number | null) ?? null;
            const b = (prev?.[key] as number | null) ?? null;
            return (
              <TableRow key={key}>
                <TableCell className="font-medium">{label}</TableCell>
                <TableCell className="r font-semibold">{fmt(a)}</TableCell>
                <TableCell className="r muted">{prev ? fmt(b) : 'No data'}</TableCell>
                <TableCell className="r"><ChangeText current={a} previous={b} unit={unit} higherIsBetter={higherIsBetter} /></TableCell>
              </TableRow>
            );
          })}
        </TableBody>
      </KpiTable>
    </Panel>
  );
}
