import type { ReactNode } from 'react';
import { ChevronLeft, ChevronRight } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { cn } from '@/lib/utils';

/**
 * The table style of the All KPI's page: one scroll container (so the header stays visible while scrolling), a muted
 * sticky header, compact rows, subtle separators and no wrapping. Cells use the shadcn TableRow / TableHead / TableCell.
 */
export function KpiTable({ children, maxHeight = 'max-h-[32rem]', className }: { children: ReactNode; maxHeight?: string; className?: string }) {
  return (
    <div className={cn('overflow-auto rounded-lg border', maxHeight, className)}>
      <table className={cn(
        'w-full border-collapse text-xs',
        '[&_thead]:sticky [&_thead]:top-0 [&_thead]:z-10 [&_thead]:bg-muted [&_thead_tr]:border-b [&_thead_tr]:hover:bg-muted',
        '[&_th]:h-9 [&_th]:px-3 [&_th]:text-[11px] [&_th]:font-semibold [&_th]:whitespace-nowrap [&_th]:text-muted-foreground',
        '[&_td]:h-9 [&_td]:px-3 [&_td]:py-1.5 [&_td]:whitespace-nowrap [&_tbody_tr]:border-b [&_tbody_tr]:border-border/70 [&_tbody_tr:last-child]:border-0',
      )}>
        {children}
      </table>
    </div>
  );
}

/** Pagination footer of a paged table. */
export function Pager({ page, pages, total, pageSize, onPage, noun = 'rows' }: {
  page: number; pages: number; total: number; pageSize?: number; onPage: (page: number) => void; noun?: string;
}) {
  const from = pageSize ? (page - 1) * pageSize + 1 : null;
  const to = pageSize ? Math.min(total, page * pageSize) : null;
  return (
    <div className="mt-3 flex flex-wrap items-center justify-between gap-2 text-xs text-muted-foreground">
      <span className="tabular-nums">{from != null && total ? `Showing ${from.toLocaleString('en-IN')}–${to!.toLocaleString('en-IN')} of ${total.toLocaleString('en-IN')} ${noun}` : `${total.toLocaleString('en-IN')} ${noun}`}</span>
      {pages > 1 && (
        <div className="flex items-center gap-2">
          <Button size="sm" variant="outline" className="h-8" disabled={page <= 1} onClick={() => onPage(page - 1)}><ChevronLeft /> Previous</Button>
          <span className="tabular-nums">Page {page} of {pages}</span>
          <Button size="sm" variant="outline" className="h-8" disabled={page >= pages} onClick={() => onPage(page + 1)}>Next <ChevronRight /></Button>
        </div>
      )}
    </div>
  );
}
