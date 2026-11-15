import type { ReactNode } from 'react';
import { ArrowDown, ArrowUp, ArrowUpDown, Inbox } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { TableHead } from '@/components/ui/table';
import { cn } from '@/lib/utils';
import { formatNumber } from '../../lib/format';

/**
 * Building blocks of the submission trackers, with the exact look of the Data Arrival & Follow-up (Uptime CSV) tracker:
 * clickable summary tiles, sortable table headings, the empty state and the pager.
 */

export type Sort<K extends string> = { key: K; desc: boolean };

export function SortHead<K extends string>({ sortKey, label, sort, onSort, className }: {
  sortKey: K; label: string; sort: Sort<K>; onSort: (key: K) => void; className?: string;
}) {
  const active = sort.key === sortKey;
  return (
    <TableHead className={className} aria-sort={active ? (sort.desc ? 'descending' : 'ascending') : undefined}>
      <button type="button" onClick={() => onSort(sortKey)} className="inline-flex items-center gap-1 rounded font-medium hover:text-foreground focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none">
        {label}
        {active ? (sort.desc ? <ArrowDown className="size-3" /> : <ArrowUp className="size-3" />) : <ArrowUpDown className="size-3 opacity-40" />}
      </button>
    </TableHead>
  );
}

export interface Tile<Id extends string> { id: Id; label: string; value: number; icon: ReactNode; tone?: string; hint?: string }

/** Summary tiles; selecting one filters the table it names, selecting it again clears the filter. */
export function SummaryTiles<Id extends string>({ label, tiles, active, onSelect, allId }: {
  label: string; tiles: Tile<Id>[]; active: Id; onSelect: (id: Id) => void; allId: Id;
}) {
  return (
    <section aria-label={label} className="grid grid-cols-2 gap-2.5 md:grid-cols-4 xl:grid-cols-7">
      {tiles.map((tile) => {
        const on = active === tile.id && tile.id !== allId;
        return (
          <button key={tile.id} type="button" aria-pressed={on} onClick={() => onSelect(on ? allId : tile.id)}
            className={cn('rounded-xl border bg-card px-3 py-2 text-left shadow-xs transition-colors hover:bg-muted/50 focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none',
              on && 'border-primary ring-2 ring-primary/20')}>
            <span className="flex items-center justify-between text-[11px] font-medium text-muted-foreground [&_svg]:size-3.5">{tile.label}{tile.icon}</span>
            <span className={cn('mt-0.5 block text-[18px] leading-6 font-semibold tabular-nums', tile.tone)}>{formatNumber(tile.value)}</span>
            <span className="text-[10.5px] text-muted-foreground">{on ? 'Showing these · select to clear' : tile.hint ?? 'Select to filter the table'}</span>
          </button>
        );
      })}
    </section>
  );
}

export function EmptyRows({ children, action }: { children: ReactNode; action?: ReactNode }) {
  return (
    <div className="flex flex-col items-center gap-2 px-4 py-10 text-center text-sm text-muted-foreground">
      <Inbox className="size-6" aria-hidden="true" />
      <p>{children}</p>
      {action}
    </div>
  );
}

export function Pager({ page, pages, onPage, label = 'Table pagination' }: { page: number; pages: number; onPage: (page: number) => void; label?: string }) {
  if (pages <= 1) return null;
  return (
    <nav className="flex items-center justify-between px-4 text-xs text-muted-foreground" aria-label={label}>
      <span>Page {page} of {pages}</span>
      <div className="flex gap-1.5">
        <Button size="sm" variant="outline" disabled={page <= 1} onClick={() => onPage(page - 1)}>Previous</Button>
        <Button size="sm" variant="outline" disabled={page >= pages} onClick={() => onPage(page + 1)}>Next</Button>
      </div>
    </nav>
  );
}
