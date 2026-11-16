import { ReferenceArea, ReferenceLine } from 'recharts';
import type { MonthKind } from '../../lib/monthlyHistory';
import { useSourceLabels } from '../../context/sourceLabels';
import { DAILY_LABEL } from './constants';

/** Top margin of a monthly chart whose source marks are labelled: the labels sit above the plot, never on the data. */
export const SOURCE_LABEL_MARGIN = 18;
const LABEL = { fontSize: 10, fill: 'var(--muted-foreground)' } as const;

/**
 * Shading over the imported historical months and a line where the calculated months start (categorical x axis). Empty
 * gap months belong to neither: they are outside the shading and before the line. Labels are drawn above the plot area.
 */
export function SourceMarks({ labels, kinds }: { labels: string[]; kinds: MonthKind[] }) {
  const labels_ = useSourceLabels();
  const first = kinds.indexOf('historical');
  const last = kinds.lastIndexOf('historical');
  if (first < 0) return null;
  const daily = kinds.indexOf('daily', last);
  return (
    <>
      <ReferenceArea x1={labels[first]} x2={labels[last]} fill="var(--muted-foreground)" fillOpacity={0.07} ifOverflow="extendDomain"
        label={labels_.annotate ? { value: labels_.history, position: 'top', offset: 4, ...LABEL } : undefined} />
      {/* The line where the calculated months start, and both labels, only where the page annotates the sources. */}
      {labels_.annotate && daily > last && (
        <ReferenceLine x={labels[daily]} stroke="var(--muted-foreground)" strokeDasharray="2 3"
          label={{ value: DAILY_LABEL, position: 'top', offset: 4, ...LABEL }} />
      )}
    </>
  );
}

/** One line under a chart saying which months come from which source. */
export function SourceNote({ months }: { months: { label: string; source?: string }[] }) {
  const labels = useSourceLabels();
  const hist = months.filter((m) => m.source === 'historical_import');
  if (!hist.length) return null;
  const daily = months.filter((m) => m.source !== 'historical_import' && m.source !== 'gap');
  return (
    <p className="mt-1 flex flex-wrap items-center gap-x-3 gap-y-1 text-[11px] text-muted-foreground">
      <span className="inline-flex items-center gap-1.5"><span className="size-2.5 rounded-sm bg-muted-foreground/20" aria-hidden="true" />
        {labels.history}: {hist[0].label}{hist.length > 1 ? `–${hist.at(-1)!.label}` : ''} ({labels.noteDetail})</span>
      {daily.length > 0 && <span className="inline-flex items-center gap-1.5"><span className="h-px w-3 border-t border-dashed border-muted-foreground" aria-hidden="true" />
        {DAILY_LABEL}: {daily[0].label}{daily.length > 1 ? `–${daily.at(-1)!.label}` : ''}</span>}
    </p>
  );
}
