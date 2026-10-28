import { ChevronRight } from 'lucide-react';

interface DataTableProps {
  caption: string;
  columns: string[];
  rows: (string | number)[][];
}

/** Collapsible plain table behind a chart, for screen readers and for checking values. */
export function DataTable({ caption, columns, rows }: DataTableProps) {
  if (!rows.length) return null;
  return (
    <details className="group mt-3 text-xs">
      <summary className="flex cursor-pointer items-center gap-1 text-muted-foreground select-none hover:text-foreground">
        <ChevronRight className="size-3.5 transition-transform group-open:rotate-90" aria-hidden="true" />
        Show data table
      </summary>
      <div className="mt-2 max-h-64 overflow-auto rounded-md border">
        <table className="w-full text-left tabular-nums">
          <caption className="sr-only">{caption}</caption>
          <thead className="sticky top-0 bg-muted">
            <tr>{columns.map((c) => <th key={c} scope="col" className="px-2.5 py-1.5 font-medium whitespace-nowrap">{c}</th>)}</tr>
          </thead>
          <tbody className="divide-y">
            {rows.map((row, i) => (
              <tr key={i}>{row.map((cell, j) => <td key={j} className="px-2.5 py-1.5 whitespace-nowrap">{cell}</td>)}</tr>
            ))}
          </tbody>
        </table>
      </div>
    </details>
  );
}
