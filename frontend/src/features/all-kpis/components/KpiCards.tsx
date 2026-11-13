import { type LucideIcon } from 'lucide-react';
import { cn } from '@/lib/utils';
import { NA } from '../format';
import type { Tone } from '../status';
import type { KpiTab } from '../useKpiFilters';
import { ChangeText, StatusPill } from './Ui';
import { AVAILABILITY_STATUS } from './theme';

export interface KpiCardSpec {
  label: string;
  value: string;
  /** Raw values for the comparison with the previous period (no comparison when either is missing). */
  current?: number | null;
  previous?: number | null;
  /** The previous value, formatted as the value ("Prev …"). */
  prev?: string;
  unit?: 'pts' | '%';
  /** Whether a higher value is better (colours the change); null: neutral. */
  higherIsBetter?: boolean | null;
  /** Short context under the value; for an unavailable value, why it is unavailable. */
  note?: string;
  /** Informational value (e.g. not configured): shown in the neutral style. */
  muted?: boolean;
  /** Status of the value (status.ts); neutral when omitted. */
  tone?: Tone;
  /** An availability value: shows its status pill against the existing 98.5% / 60% thresholds. */
  availability?: boolean;
  icon?: LucideIcon;
  /** The view with the detailed analysis of this KPI. */
  tab?: KpiTab;
}

/** The value with its unit set smaller ("98.745" + "%", "409.6" + " h"); text values are shown as they are. */
function Value({ value }: { value: string }) {
  const m = /^(-?[\d,.]+)(\s?)(%|h|min)$/.exec(value);
  return <span className="v">{m ? <>{m[1]}<small>{m[2]}{m[3]}</small></> : value}</span>;
}

/**
 * One KPI tile (reference style): label, value, then either the availability status or "Prev … · ▲ change" (only when
 * both periods have a value; green when better, red when worse), and its context. A click opens its view.
 */
export function KpiCard({ spec, onOpen }: { spec: KpiCardSpec; period?: string; compareLabel?: string; onOpen?: (tab: KpiTab) => void }) {
  const unavailable = !!spec.muted || spec.value === NA;
  const hasChange = !unavailable && spec.current != null && spec.previous != null;
  const top = !unavailable && spec.tone && spec.tone !== 'neutral' ? `top-${spec.tone === 'bad' ? 'crit' : spec.tone}` : null;
  const body = (
    <>
      <span className="l">{spec.label}</span>
      <Value value={spec.value} />
      {!unavailable && spec.availability && spec.tone && (
        <span className="s flex flex-wrap items-center gap-1.5"><StatusPill tone={spec.tone}>{AVAILABILITY_STATUS[spec.tone]}</StatusPill>
          {hasChange && <ChangeText current={spec.current} previous={spec.previous} unit={spec.unit} higherIsBetter={spec.higherIsBetter ?? null} />}</span>
      )}
      {!unavailable && !spec.availability && hasChange && (
        <span className="s">Prev {spec.prev ?? '—'} · <ChangeText current={spec.current} previous={spec.previous} unit={spec.unit} higherIsBetter={spec.higherIsBetter ?? null} /></span>
      )}
      {spec.note && <span className="s">{spec.note}</span>}
    </>
  );
  const cls = cn('akp-tile h-full w-full', unavailable && 'na', top);
  return (
    <div role="group" aria-label={spec.label} className="h-full">
      {spec.tab && onOpen
        ? <button type="button" className={cls} onClick={() => onOpen(spec.tab!)} aria-label={`${spec.label}: open details`}>{body}</button>
        : <div className={cls}>{body}</div>}
    </div>
  );
}
