import { ArrowDownRight, ArrowUpRight, Minus } from 'lucide-react';
import { Card } from '@/components/ui/card';
import { cn } from '@/lib/utils';
import { change } from '../format';
import type { KpiTab } from '../useKpiFilters';

export interface KpiCardSpec {
  label: string;
  value: string;
  /** Raw values for the comparison with the previous period (no comparison when either is missing). */
  current?: number | null;
  previous?: number | null;
  unit?: 'pts' | '%';
  /** Whether a higher value is better (colours the change); null: neutral. */
  higherIsBetter?: boolean | null;
  note?: string;
  muted?: boolean;
  /** The tab with the detailed analysis of this KPI. */
  tab?: KpiTab;
}

/** One KPI card: value, change against the previous period, and the period; a click opens its detailed analysis. */
export function KpiCard({ spec, period, onOpen }: { spec: KpiCardSpec; period: string; onOpen?: (tab: KpiTab) => void }) {
  const c = change(spec.current, spec.previous, spec.unit);
  const good = c && spec.higherIsBetter != null && c.diff !== 0 ? (c.diff > 0) === spec.higherIsBetter : null;
  const Arrow = !c || c.diff === 0 ? Minus : c.diff > 0 ? ArrowUpRight : ArrowDownRight;
  const body = (
    <>
      <p className="text-xs font-medium text-muted-foreground">{spec.label}</p>
      <p className={cn('text-2xl font-semibold tabular-nums tracking-tight', spec.muted && 'text-base font-medium text-muted-foreground')}>{spec.value}</p>
      <p className="flex flex-wrap items-center gap-x-1.5 text-[11px] text-muted-foreground">
        {c && (
          <span className={cn('inline-flex items-center font-medium', good === true && 'text-emerald-700', good === false && 'text-destructive')}>
            <Arrow className="size-3.5" aria-hidden="true" />{c.text}
          </span>
        )}
        <span>{spec.note ?? period}</span>
      </p>
    </>
  );
  return spec.tab && onOpen ? (
    <Card role="group" aria-label={spec.label} className="gap-1 px-4 py-3 transition-colors hover:bg-muted/40">
      <button type="button" className="flex flex-col gap-1 text-left focus-visible:outline-none" onClick={() => onOpen(spec.tab!)} aria-label={`${spec.label}: open details`}>
        {body}
      </button>
    </Card>
  ) : <Card role="group" aria-label={spec.label} className="gap-1 px-4 py-3">{body}</Card>;
}

/** A titled group of KPI cards (responsive grid). */
export function KpiGroup({ title, cards, period, onOpen }: { title: string; cards: KpiCardSpec[]; period: string; onOpen?: (tab: KpiTab) => void }) {
  return (
    <section aria-label={title} className="space-y-2">
      <h2 className="text-xs font-semibold tracking-[0.14em] text-muted-foreground uppercase">{title}</h2>
      <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-4">
        {cards.map((c) => <KpiCard key={c.label} spec={c} period={period} onOpen={onOpen} />)}
      </div>
    </section>
  );
}
