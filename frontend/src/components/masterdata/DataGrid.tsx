import { useRef, useState, type KeyboardEvent, type MouseEvent } from 'react';
import { ArrowDown, ArrowUp, ChevronLeft, ChevronRight, Columns3, X } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Card } from '@/components/ui/card';
import { Popover, PopoverContent, PopoverTrigger } from '@/components/ui/popover';
import { Sheet, SheetContent, SheetDescription, SheetHeader, SheetTitle } from '@/components/ui/sheet';
import { Skeleton } from '@/components/ui/skeleton';
import { cn } from '@/lib/utils';
import { SelectField } from '../data/DataEntry';
import { formatDate, formatDateTime, formatMinutes, formatNumber, formatPct } from '../../lib/format';
import type { MasterColumn, MasterPage, MasterRow } from '../../types/masterData';
import { cellText, type DataEdits } from './useDataEdits';

/** Editing mode of the grid (Data Panel Add / Edit permissions); absent: the read-only worksheet. */
export interface GridEditing {
  edits: DataEdits;
  /** Columns editable on stored rows, and fillable on new rows. */
  editable: string[];
  addable: string[];
  required: string[];
}

const NUMERIC = ['number', 'pct', 'minutes'];

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

type Move = 'down' | 'up' | 'next' | 'prev' | 'left' | 'right';

/** Moves the focus to another editable cell of the same table (Enter / arrows: same column; Tab: next cell). */
function moveFocus(from: HTMLElement, how: Move) {
  const table = from.closest('table');
  if (!table) return;
  const cells = [...table.querySelectorAll<HTMLElement>('[data-cell]')];
  const [row, col] = (from.dataset.cell ?? '0:0').split(':').map(Number);
  let target: HTMLElement | undefined;
  if (how === 'next' || how === 'prev') target = cells[cells.indexOf(from) + (how === 'next' ? 1 : -1)];
  else if (how === 'left' || how === 'right') {
    const same = cells.filter((c) => c.dataset.cell!.startsWith(`${row}:`));
    target = same[same.indexOf(from) + (how === 'right' ? 1 : -1)];
  } else {
    target = cells.find((c) => c.dataset.cell === `${row + (how === 'down' ? 1 : -1)}:${col}`);
  }
  target?.focus();
}

/** One editable cell: Enter, F2, a double click or typing opens the editor; Enter / Tab commit and move on, Esc cancels. */
function EditableCell({ value, display, kind, label, cellId, changed, error, required, onCommit, width }: {
  value: string; display: string; kind: MasterColumn['kind']; label: string; cellId: string; changed: boolean; error?: string;
  required?: boolean; onCommit: (value: string) => void; width?: number;
}) {
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState('');
  const cellRef = useRef<HTMLTableCellElement>(null);
  const start = (initial?: string) => { setDraft(initial ?? value); setEditing(true); };
  const finish = (save: boolean, then?: Move) => {
    if (save && draft !== value) onCommit(draft);
    setEditing(false);
    requestAnimationFrame(() => {
      if (!cellRef.current) return;
      if (then) moveFocus(cellRef.current, then);
      else cellRef.current.focus();
    });
  };
  const onCellKey = (e: KeyboardEvent<HTMLTableCellElement>) => {
    if (editing || e.target !== e.currentTarget) return;
    const moves: Record<string, Move> = { ArrowDown: 'down', ArrowUp: 'up', ArrowLeft: 'left', ArrowRight: 'right' };
    if (moves[e.key]) { e.preventDefault(); moveFocus(e.currentTarget, moves[e.key]); }
    else if (e.key === 'Enter' || e.key === 'F2') { e.preventDefault(); start(); }
    else if (e.key === 'Delete' || e.key === 'Backspace') { e.preventDefault(); onCommit(''); }  // empties the cell, never a record
    else if (e.key.length === 1 && !e.ctrlKey && !e.metaKey && !['bool', 'date', 'month'].includes(kind)) { e.preventDefault(); start(e.key); }
  };
  const onInputKey = (e: KeyboardEvent<HTMLInputElement | HTMLSelectElement>) => {
    if (e.key === 'Enter') { e.preventDefault(); finish(true, 'down'); }
    else if (e.key === 'Tab') { e.preventDefault(); finish(true, e.shiftKey ? 'prev' : 'next'); }
    else if (e.key === 'Escape') { e.preventDefault(); finish(false); }
  };
  const common = {
    autoFocus: true, 'aria-label': label, onKeyDown: onInputKey, onBlur: () => { if (editing) finish(true); },
    className: 'h-6 w-full min-w-24 rounded border border-primary bg-background px-1 text-xs outline-none',
  };
  return (
    <td ref={cellRef} data-cell={cellId} tabIndex={0} onKeyDown={onCellKey} onDoubleClick={() => { if (!editing) start(); }}
      title={error ?? (changed ? 'Changed: not saved yet' : 'Double-click, Enter or type to edit')} aria-invalid={error ? true : undefined}
      aria-label={editing ? undefined : `${label}: ${display}`} style={width ? { maxWidth: width } : undefined}
      className={cn('max-w-72 truncate border-r border-b px-2.5 py-1 outline-none focus:ring-2 focus:ring-primary focus:ring-inset',
        NUMERIC.includes(kind) && 'text-right', changed && 'bg-amber-100 font-medium', error && 'bg-red-50 ring-1 ring-destructive ring-inset',
        required && !value && !error && 'bg-emerald-100/70')}>
      {editing ? (
        kind === 'bool' ? (
          <select {...common} value={draft} onChange={(e) => setDraft(e.target.value)}>
            <option value="">—</option><option value="Yes">Yes</option><option value="No">No</option>
          </select>
        ) : (
          <input {...common} type={kind === 'date' || kind === 'month' ? 'date' : 'text'} inputMode={NUMERIC.includes(kind) ? 'decimal' : undefined}
            value={draft} onChange={(e) => setDraft(e.target.value)} />
        )
      ) : display}
    </td>
  );
}

/**
 * An Excel-like worksheet of one page of server records: sticky header, horizontal scroll, sorting by a header click,
 * resizable columns, column visibility and a detail panel with every field of a row. Sorting and paging are done by
 * the server (``onSort`` / ``onPage``); nothing is loaded beyond the page shown. With ``editing`` (Data Panel Add / Edit
 * permissions) cells can be changed in place and new rows filled in; changes stay in the browser until saved.
 */
export function DataGrid({ title, columns, visible, onVisible, page, loading, error, sort, onSort, pageSizes, onPage, onPageSize, actions, editing, toolbar }: {
  title: string; columns: MasterColumn[]; visible: string[]; onVisible: (keys: string[]) => void; page: MasterPage | null; loading: boolean;
  error: Error | null; sort: string; onSort: (sort: string) => void; pageSizes: number[]; onPage: (page: number) => void; onPageSize: (size: number) => void;
  actions?: React.ReactNode;
  /** Data Panel editing (cells, new rows); the read-only worksheet without it. */
  editing?: GridEditing | null;
  /** Shown under the title bar (e.g. the unsaved-changes bar). */
  toolbar?: React.ReactNode;
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
  const additions = editing?.edits.additions ?? [];
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
      {toolbar}
      {error ? <p className="px-4 py-6 text-sm text-destructive" role="alert">{error.message}</p> : !page ? <Skeleton className="m-4 h-64" /> : (
        <div className={cn('max-h-[65vh] overflow-auto', loading && 'opacity-60')}>
          <table className="w-max min-w-full border-collapse text-xs tabular-nums" aria-label={`${title} records`}>
            <thead className="sticky top-0 z-10 bg-muted">
              <tr>
                {editing && <th scope="col" className="w-10 border-r border-b px-1.5 py-2 text-center font-semibold">#</th>}
                {shown.map((c) => {
                  const active = sortKey === c.key;
                  const desc = active && sort.startsWith('-');
                  return (
                    <th key={c.key} scope="col" style={widths[c.key] ? { width: widths[c.key], minWidth: widths[c.key] } : undefined}
                      aria-sort={active ? (desc ? 'descending' : 'ascending') : undefined}
                      className="relative border-r border-b px-2.5 py-2 text-left font-semibold whitespace-nowrap">
                      {c.sortable === false ? c.label : (
                        <button type="button" className="inline-flex items-center gap-1 hover:text-primary" onClick={() => onSort(active && !desc ? `-${c.key}` : c.key)}>
                          {c.label}{editing?.required.includes(c.key) && additions.length > 0 && <span className="text-destructive" aria-hidden="true">*</span>}
                          {active && (desc ? <ArrowDown className="size-3" /> : <ArrowUp className="size-3" />)}
                        </button>
                      )}
                      <span role="separator" aria-hidden="true" onMouseDown={(e) => startResize(e, c.key)} className="absolute top-0 right-0 h-full w-1.5 cursor-col-resize hover:bg-primary/40" />
                    </th>
                  );
                })}
              </tr>
            </thead>
            <tbody>
              {editing && additions.map((n, i) => {
                const errs = editing.edits.errors?.additions[String(editing.edits.additionIndex(n.tmp))];
                return (
                  <tr key={`new-${n.tmp}`} className="bg-emerald-50/70" aria-label={`New record ${i + 1}`}>
                    <td className={cn('border-r border-b px-1 text-center', errs?._row && 'bg-red-50')} title={errs?._row ?? 'New record: not saved yet'}>
                      <button type="button" className="rounded p-0.5 text-muted-foreground hover:text-destructive" aria-label={`Remove new record ${i + 1}`}
                        title="Remove this unsaved row" onClick={() => editing.edits.removeNew(n.tmp)}><X className="size-3.5" /></button>
                    </td>
                    {shown.map((c, ci) => (editing.addable.includes(c.key) ? (
                      <EditableCell key={c.key} cellId={`${i}:${ci}`} value={n.values[c.key] ?? ''} display={n.values[c.key] ?? ''} kind={c.kind}
                        label={`New record ${i + 1}: ${c.label}`} changed={!!n.values[c.key]} error={errs?.[c.key]} required={editing.required.includes(c.key)}
                        onCommit={(v) => editing.edits.setNewCell(n.tmp, c.key, v)} width={widths[c.key]} />
                    ) : <td key={c.key} className="border-r border-b px-2.5 py-1 text-muted-foreground">—</td>))}
                  </tr>
                );
              })}
              {page.rows.map((r, ri) => {
                const rowEdits = editing?.edits.changes[r._id];
                const errs = editing?.edits.errors?.changes[String(r._id)];
                const rowIndex = additions.length + ri;
                return (
                  <tr key={r._id} className={cn('odd:bg-card even:bg-muted/30', !editing && 'cursor-pointer hover:bg-primary/5')}
                    onClick={editing ? undefined : () => setDetail(r)} tabIndex={editing ? undefined : 0}
                    onKeyDown={editing ? undefined : (e) => { if (e.key === 'Enter') setDetail(r); }} aria-label={`Open record ${r._id}`}>
                    {editing && (
                      <td className={cn('border-r border-b px-1 text-center', errs?._row && 'bg-red-50 text-destructive')} title={errs?._row ?? (rowEdits ? 'Changed: not saved yet' : undefined)}>
                        <button type="button" className="text-muted-foreground hover:text-primary" aria-label={`Details of record ${r._id}`} onClick={() => setDetail(r)}>
                          {rowEdits ? '●' : '⋯'}
                        </button>
                      </td>
                    )}
                    {shown.map((c, ci) => {
                      if (editing && editing.editable.includes(c.key)) {
                        const pending = rowEdits?.[c.key];
                        return (
                          <EditableCell key={c.key} cellId={`${rowIndex}:${ci}`} value={pending ?? cellText(r[c.key], c.kind)}
                            display={pending !== undefined ? (pending || '—') : formatCell(r[c.key], c.kind)} kind={c.kind} label={`${c.label} of record ${r._id}`}
                            changed={pending !== undefined} error={errs?.[c.key]} onCommit={(v) => editing.edits.setCell(r, c, v)} width={widths[c.key]} />
                        );
                      }
                      return (
                        <td key={c.key} title={String(r[c.key] ?? '')} style={widths[c.key] ? { maxWidth: widths[c.key] } : undefined}
                          className={cn('max-w-72 truncate border-r border-b px-2.5 py-1.5', NUMERIC.includes(c.kind) && 'text-right', editing && 'text-muted-foreground')}>
                          {formatCell(r[c.key], c.kind)}
                        </td>
                      );
                    })}
                  </tr>
                );
              })}
              {!page.rows.length && !additions.length && (
                <tr><td colSpan={shown.length + (editing ? 1 : 0)} className="px-4 py-8 text-center text-muted-foreground">No records match these filters.</td></tr>
              )}
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
