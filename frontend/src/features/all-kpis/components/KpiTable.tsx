import type { ReactNode } from 'react';
import { ChevronLeft, ChevronRight } from 'lucide-react';
import { cn } from '@/lib/utils';

/**
 * The table style of the All KPI's page (reference report): one scroll box with a sticky upper-case header, 13 px rows
 * and thin separators (allkpis.css `.akp-tbox`). Cells may use the shadcn TableRow / TableHead / TableCell.
 */
export function KpiTable({ children, maxHeight = 620, className, label }: { children: ReactNode; maxHeight?: number; className?: string; label?: string }) {
  return (
    <div className={cn('akp-tbox', className)} style={{ maxHeight }} role={label ? 'region' : undefined} aria-label={label} tabIndex={label ? 0 : undefined}>
      <table>{children}</table>
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
    <div className="akp-note mt-3 flex flex-wrap items-center justify-between gap-2">
      <span className="num">{from != null && total ? `Showing ${from.toLocaleString('en-IN')}–${to!.toLocaleString('en-IN')} of ${total.toLocaleString('en-IN')} ${noun}` : `${total.toLocaleString('en-IN')} ${noun}`}</span>
      {pages > 1 && (
        <div className="flex items-center gap-2">
          <button type="button" className="akp-btn sm" disabled={page <= 1} onClick={() => onPage(page - 1)}><ChevronLeft className="size-3.5" aria-hidden="true" /> Previous</button>
          <span className="num">Page {page} of {pages}</span>
          <button type="button" className="akp-btn sm" disabled={page >= pages} onClick={() => onPage(page + 1)}>Next <ChevronRight className="size-3.5" aria-hidden="true" /></button>
        </div>
      )}
    </div>
  );
}
