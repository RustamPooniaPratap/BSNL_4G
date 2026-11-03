import { ArrowDownRight, ArrowUpRight, ChevronRight, Info, Minus, type LucideIcon } from 'lucide-react';
import { Card } from '@/components/ui/card';
import { cn } from '@/lib/utils';
import { change, NA } from '../format';
import { TONE_ACCENT, type Tone } from '../status';
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
  /** Short context under the value; for an unavailable value, why it is unavailable. */
  note?: string;
  /** Informational value (e.g. pending clarification): shown in the neutral style. */
  muted?: boolean;
  /** Status of the value (status.ts); neutral when omitted. */
  tone?: Tone;
  icon?: LucideIcon;
  /** The tab with the detailed analysis of this KPI. */
  tab?: KpiTab;
}

/** The value with its unit set smaller ("98.745" + "%", "409.6" + " h"); text values are shown as they are. */
function Value({ value, unavailable }: { value: string; unavailable: boolean }) {
  if (unavailable) return <p className="text-sm font-medium text-muted-foreground">{value}</p>;
  const m = /^(-?[\d,.]+)(\s?)(%|h|min)$/.exec(value);
  return (
    <p className="text-2xl leading-none font-semibold tracking-tight tabular-nums">
      {m ? <>{m[1]}<span className="text-sm font-medium text-muted-foreground">{m[2]}{m[3]}</span></> : value}
    </p>
  );
}

/**
 * One KPI card: title and icon, the value, a short context and, only when both periods have a value, the change against
 * the previous period (green when better, red when worse: a higher outage is worse). A click opens its detailed analysis.
 */
export function KpiCard({ spec, period, compareLabel, onOpen }: { spec: KpiCardSpec; period: string; compareLabel?: string; onOpen?: (tab: KpiTab) => void }) {
  const unavailable = !!spec.muted || spec.value === NA;
  const c = unavailable ? null : change(spec.current, spec.previous, spec.unit);
  const good = c && spec.higherIsBetter != null && c.diff !== 0 ? (c.diff > 0) === spec.higherIsBetter : null;
  const Arrow = !c || c.diff === 0 ? Minus : c.diff > 0 ? ArrowUpRight : ArrowDownRight;
  const Icon = unavailable ? Info : spec.icon;
  const clickable = !!(spec.tab && onOpen);
  const body = (
    <>
      <span aria-hidden="true" className={cn('absolute inset-y-0 left-0 w-[3px]', TONE_ACCENT[unavailable ? 'neutral' : spec.tone ?? 'neutral'])} />
      <div className="flex items-start justify-between gap-2">
        <p className="text-xs leading-snug font-medium text-muted-foreground">{spec.label}</p>
        {Icon && <Icon className="size-4 shrink-0 text-muted-foreground/70" aria-hidden="true" />}
      </div>
      <div className="flex min-h-8 items-end">
        <Value value={spec.value} unavailable={unavailable} />
      </div>
      <div className="mt-auto flex flex-wrap items-center gap-x-2 gap-y-1 pt-1 text-[11px] text-muted-foreground">
        {c && (
          <span title={compareLabel ? `Change against ${compareLabel}` : 'Change against the previous period'}
            className={cn('inline-flex items-center gap-0.5 rounded px-1 py-px font-medium tabular-nums',
              good === true ? 'bg-emerald-50 text-emerald-700' : good === false ? 'bg-red-50 text-red-700' : 'bg-muted text-muted-foreground')}>
            <Arrow className="size-3" aria-hidden="true" />{c.text}
          </span>
        )}
        <span className="min-w-0">{spec.note ?? (c && compareLabel ? `vs ${compareLabel}` : period)}</span>
        {clickable && <ChevronRight className="ml-auto size-3.5 opacity-0 transition-opacity group-hover/kpi:opacity-60" aria-hidden="true" />}
      </div>
    </>
  );
  const cls = cn('group/kpi relative h-full min-h-28 gap-1.5 px-4 py-3 shadow-xs', unavailable && 'border border-dashed bg-muted/30 shadow-none ring-0');
  return clickable ? (
    <Card role="group" aria-label={spec.label} className={cn(cls, 'p-0 transition-shadow hover:shadow-sm hover:ring-primary/25 focus-within:ring-2 focus-within:ring-ring/50')}>
      <button type="button" className="flex h-full flex-col gap-1.5 px-4 py-3 text-left focus-visible:outline-none" onClick={() => onOpen!(spec.tab!)} aria-label={`${spec.label}: open details`}>
        {body}
      </button>
    </Card>
  ) : <Card role="group" aria-label={spec.label} className={cls}>{body}</Card>;
}

/** A titled group of KPI cards: equal-height cards in a responsive grid. */
export function KpiGroup({ title, icon: Icon, cards, period, compareLabel, onOpen }: {
  title: string; icon?: LucideIcon; cards: KpiCardSpec[]; period: string; compareLabel?: string; onOpen?: (tab: KpiTab) => void;
}) {
  return (
    <section aria-label={title} className="space-y-2.5">
      <div className="flex flex-wrap items-baseline justify-between gap-x-3 gap-y-0.5">
        <h2 className="flex items-center gap-2 text-sm font-semibold">
          {Icon && <Icon className="size-4 text-muted-foreground" aria-hidden="true" />}{title}
        </h2>
        <p className="text-[11px] text-muted-foreground">{period}</p>
      </div>
      <div className="grid auto-rows-fr grid-cols-1 gap-3 sm:grid-cols-2 xl:grid-cols-4">
        {cards.map((c) => <KpiCard key={c.label} spec={c} period={period} compareLabel={compareLabel} onOpen={onOpen} />)}
      </div>
    </section>
  );
}
