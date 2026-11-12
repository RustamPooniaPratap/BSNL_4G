import { Label } from '@/components/ui/label';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import { cn } from '@/lib/utils';
import { usePopulation } from '../context/population';
import { POPULATIONS, isPopulation, populationLabel } from '../lib/population';

/**
 * The global population selector (On-Air / O&M Start), in the compact labelled style of the filter bars. Every
 * instance on every page is bound to the same PopulationProvider selection.
 * ``unavailable``: populations the data cannot serve (e.g. no O&M Start dates), shown disabled.
 */
export function PopulationSelect({ id = 'filter-population', className, unavailable = [] }: {
  id?: string; className?: string; unavailable?: string[];
}) {
  const { scope, setScope } = usePopulation();
  return (
    <div className={cn('flex min-w-0 flex-col gap-1', className ?? 'w-36')}>
      <Label htmlFor={id} className="text-[11px] font-medium text-muted-foreground">Population</Label>
      <Select value={scope} onValueChange={(v) => { if (isPopulation(v)) setScope(v); }}>
        <SelectTrigger id={id} className="h-9 w-full" title="Site population of every figure on every page"><SelectValue /></SelectTrigger>
        <SelectContent>
          {POPULATIONS.map((p) => (
            <SelectItem key={p} value={p} disabled={unavailable.includes(p) && p !== scope}>{populationLabel(p)}</SelectItem>
          ))}
        </SelectContent>
      </Select>
    </div>
  );
}

/** "Population: On-Air sites" for headings, notes and export buttons. */
export function PopulationNote({ className }: { className?: string }) {
  const { sitesLabel } = usePopulation();
  return <span className={cn('text-xs text-muted-foreground', className)} aria-label="Active population">Population: {sitesLabel}</span>;
}
