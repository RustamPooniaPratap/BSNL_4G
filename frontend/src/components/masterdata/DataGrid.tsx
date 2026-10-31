import { useRef, useState, type MouseEvent } from 'react';
import { ArrowDown, ArrowUp, ChevronLeft, ChevronRight, Columns3 } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Card } from '@/components/ui/card';
import { Popover, PopoverContent, PopoverTrigger } from '@/components/ui/popover';
import { Sheet, SheetContent, SheetDescription, SheetHeader, SheetTitle } from '@/components/ui/sheet';
import { Skeleton } from '@/components/ui/skeleton';
import { cn } from '@/lib/utils';
import { SelectField } from '../data/DataEntry';
import { formatDate, formatDateTime, formatMinutes, formatNumber, formatPct } from '../../lib/format';
import type { MasterColumn, MasterPage, MasterRow } from '../../types/masterData';

/** A cell as the column's kind says; blank (null) is shown as "—", never as 0. */
function formatCell(value: MasterRow[string], kind: MasterColumn['kind']) {
  if (value === null || value === '' || value === undefined) return '—';
  switch (kind) {
    case 'date': return formatDate(String(value));
    case 'datetime': return formatDateTime(String(value));
    case 'month': return new Date(`${String(value).slice(0, 7)}-01T00:00:00Z`).toLocaleDateString('en-IN', { month: 'short', year: 'numeric', timeZone: 'UTC' });
    case 'pct': return formatPct(Number(value));
    case 'minutes': return formatMinutes(Number(value));
    case 'number': return formatNumber(Number(value));
    case 'bool': return value ? 'Yes' : 'No';
    default: return String(value);
  }
}

/**
 * An Excel-like worksheet of one page of server records: sticky header, horizontal scroll, sorting by a header click,
 * resizable columns, column visibility and a detail panel with every field of a row. Sorting and paging are done by
 * the server (``onSort`` / ``onPage``); nothing is loaded beyond the page shown.
 */
export function DataGrid({ title, columns, visible, onVisible, page, loading, error, sort, onSort, pageSizes, onPage, onPageSize, actions }: {
  title: string; columns: MasterColumn[]; visible: string[]; onVisible: (keys: string[]) => void; page: MasterPage | null; loading: boolean;
  error: Error | null; sort: string; onSort: (sort: string) => void; pageSizes: number[]; onPage: (page: number) => void; onPageSize: (size: number) => void;
  actions?: React.ReactNode;
}) {
  const [detail, setDetail] = useState<MasterRow | null>(null);
  const [widths, setWidths] = useState<Record<string, number>>({});
  const drag = useRef<{ key: string; x: number; w: number } | null>(null);
  const shown = columns.filter((c) => visible.includes(c.key));
  const sortKey = sort.replace(/^-/, '');
  const startResize = (e: MouseEvent, key: string) => {
    e.preventDefault();
    e.stopPropagation();
    const th = (e.currentTarget as HTMLElement).parentElement!;
    drag.current = { key, x: e.clientX, w: th.getBoundingClientRect().width };
    const move = (ev: globalThis.MouseEvent) => drag.current && setWidths((w) => ({ ...w, [drag.current!.key]: Math.max(60, drag.current!.w + ev.clientX - drag.current!.x) }));
    const up = () => { drag.current = null; window.removeEventListener('mousemove', move); window.removeEventListener('mouseup', up); };
    window.addEventListener('mousemove', move);
    window.addEventListener('mouseup', up);
  };
  return (
    <Card className="gap-0 overflow-hidden p-0" role="region" aria-label={title}>
      <div className="flex flex-wrap items-center gap-2 border-b px-4 py-2.5">
        <h2 className="text-sm font-semibold">{title}</h2>
        <span className="text-xs text-muted-foreground" aria-live="polite">{page ? `${formatNumber(page.total)} matching records` : ''}</span>
        <div className="ml-auto flex flex-wrap items-center gap-2">
          {actions}
          <Popover>
            <PopoverTrigger asChild><Button size="sm" variant="outline" className="h-8"><Columns3 /> Columns ({shown.length}/{columns.length})</Button></PopoverTrigger>
            <PopoverContent align="end" className="max-h-80 w-64 overflow-y-auto text-xs">
              <div className="mb-2 flex justify-between">
                <button type="button" className="font-medium text-primary" onClick={() => onVisible(columns.map((c) => c.key))}>Show all</button>
                <button type="button" className="font-medium text-primary" onClick={() => onVisible(columns.filter((c) => !c.hidden).map((c) => c.key))}>Default</button>
              </div>
              {columns.map((c) => (
                <label key={c.key} className="flex items-center gap-2 py-0.5">
                  <input type="checkbox" checked={visible.includes(c.key)}
                    onChange={() => onVisible(visible.includes(c.key) ? visible.filter((k) => k !== c.key) : columns.filter((x) => x.key === c.key || visible.includes(x.key)).map((x) => x.key))} />
                  {c.label}
                </label>
              ))}
            </PopoverContent>
          </Popover>
        </div>
      </div>
      {error ? <p className="px-4 py-6 text-sm text-destructive" role="alert">{error.message}</p> : !page ? <Skeleton className="m-4 h-64" /> : (
        <div className={cn('max-h-[65vh] overflow-auto', loading && 'opacity-60')}>
          <table className="w-max min-w-full border-collapse text-xs tabular-nums" aria-label={`${title} records`}>
            <thead className="sticky top-0 z-10 bg-muted">
              <tr>
                {shown.map((c) => {
                  const active = sortKey === c.key;
                  const desc = active && sort.startsWith('-');
                  return (
                    <th key={c.key} scope="col" style={widths[c.key] ? { width: widths[c.key], minWidth: widths[c.key] } : undefined}
                      aria-sort={active ? (desc ? 'descending' : 'ascending') : undefined}
                      className="relative border-r border-b px-2.5 py-2 text-left font-semibold whitespace-nowrap">
                      {c.sortable === false ? c.label : (
                        <button type="button" className="inline-flex items-center gap-1 hover:text-primary" onClick={() => onSort(active && !desc ? `-${c.key}` : c.key)}>
                          {c.label}{active && (desc ? <ArrowDown className="size-3" /> : <ArrowUp className="size-3" />)}
                        </button>
                      )}
                      <span role="separator" aria-hidden="true" onMouseDown={(e) => startResize(e, c.key)} className="absolute top-0 right-0 h-full w-1.5 cursor-col-resize hover:bg-primary/40" />
                    </th>
                  );
                })}
              </tr>
            </thead>
            <tbody>
              {page.rows.map((r) => (
                <tr key={r._id} className="cursor-pointer odd:bg-card even:bg-muted/30 hover:bg-primary/5" onClick={() => setDetail(r)}
                  tabIndex={0} onKeyDown={(e) => { if (e.key === 'Enter') setDetail(r); }} aria-label={`Open record ${r._id}`}>
                  {shown.map((c) => (
                    <td key={c.key} title={String(r[c.key] ?? '')} style={widths[c.key] ? { maxWidth: widths[c.key] } : undefined}
                      className={cn('max-w-72 truncate border-r border-b px-2.5 py-1.5', ['number', 'pct', 'minutes'].includes(c.kind) && 'text-right')}>
                      {formatCell(r[c.key], c.kind)}
                    </td>
                  ))}
                </tr>
              ))}
              {!page.rows.length && <tr><td colSpan={shown.length} className="px-4 py-8 text-center text-muted-foreground">No records match these filters.</td></tr>}
            </tbody>
          </table>
        </div>
      )}
      {page && (
        <nav aria-label="Pages" className="flex flex-wrap items-center gap-3 border-t px-4 py-2 text-xs">
          <span className="text-muted-foreground">Rows per page</span>
          <div className="w-20"><SelectField id="master-page-size" value={String(page.page_size)} placeholder="Rows" options={pageSizes.map((n) => ({ value: String(n), label: String(n) }))}
            onChange={(v) => onPageSize(Number(v))} /></div>
          <span className="ml-auto tabular-nums">Page {formatNumber(page.page)} of {formatNumber(page.pages)}</span>
          <Button size="icon" variant="outline" className="size-7" aria-label="Previous page" disabled={page.page <= 1} onClick={() => onPage(page.page - 1)}><ChevronLeft /></Button>
          <Button size="icon" variant="outline" className="size-7" aria-label="Next page" disabled={page.page >= page.pages} onClick={() => onPage(page.page + 1)}><ChevronRight /></Button>
        </nav>
      )}
      <Sheet open={!!detail} onOpenChange={(o) => { if (!o) setDetail(null); }}>
        <SheetContent className="w-full overflow-y-auto sm:max-w-md">
          <SheetHeader>
            <SheetTitle>Record details</SheetTitle>
            <SheetDescription>Every field of this record, as stored.</SheetDescription>
          </SheetHeader>
          {detail && (
            <dl className="grid grid-cols-[minmax(0,10rem)_1fr] gap-x-3 gap-y-1.5 px-4 pb-6 text-xs">
              {columns.map((c) => (
                <div key={c.key} className="contents">
                  <dt className="text-muted-foreground">{c.label}</dt>
                  <dd className="break-words">{formatCell(detail[c.key], c.kind)}</dd>
                </div>
              ))}
            </dl>
          )}
        </SheetContent>
      </Sheet>
    </Card>
  );
}
