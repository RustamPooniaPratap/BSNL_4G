import type { ReactNode } from 'react';
import { AlertTriangle, Inbox } from 'lucide-react';
import { cn } from '@/lib/utils';
import { change } from '../format';
import type { Tone } from '../status';

/**
 * All KPI's page building blocks in the reference report's style (allkpis.css, scoped under `.akp`). They only lay out
 * values computed by the server; nothing here calculates a KPI.
 */

/** A card; with a title (15 px) and an optional note and action. */
export function Panel({ title, note, action, children, className, loading, error, empty, emptyMessage = 'No data for the selected filters.', label, bare }: {
  title?: ReactNode; note?: ReactNode; action?: ReactNode; children?: ReactNode; className?: string;
  /** Inside another card (no border of its own). */
  bare?: boolean;
  loading?: boolean; error?: Error | null; empty?: boolean; emptyMessage?: string; label?: string;
}) {
  return (
    <section className={cn('akp-card akp-pad', bare && 'bare', className)} aria-label={label ?? (typeof title === 'string' ? title : undefined)} aria-busy={loading || undefined}>
      {(title || action) && (
        <div className="mb-2 flex flex-wrap items-start justify-between gap-x-4 gap-y-2">
          <div className="min-w-0">
            {title && <h3 className="akp-h" style={{ marginBottom: note ? 2 : 0 }}>{title}</h3>}
            {note && <p className="akp-note">{note}</p>}
          </div>
          {action && <div className="flex flex-wrap items-center gap-2">{action}</div>}
        </div>
      )}
      {error ? (
        <div role="status" className="akp-state"><AlertTriangle className="size-5" style={{ color: 'var(--akp-crit)' }} aria-hidden="true" />
          <p className="font-medium" style={{ color: 'var(--akp-ink)' }}>Could not load this panel</p><p>{error.message}</p></div>
      ) : loading && empty ? (
        <div className="akp-skel h-48" aria-label="Loading" />
      ) : empty ? (
        <div role="status" className="akp-state"><Inbox className="size-5" aria-hidden="true" /><p className="font-medium" style={{ color: 'var(--akp-ink)' }}>Nothing to show</p><p>{emptyMessage}</p></div>
      ) : (
        <div className={cn('transition-opacity', loading && 'opacity-60')}>{children}</div>
      )}
    </section>
  );
}

/** Underline tabs (role tab); `small` for the level tabs inside a card. */
export function Tabs<T extends string>({ items, value, onChange, label, small }: {
  items: [T, string][]; value: T; onChange: (v: T) => void; label: string; small?: boolean;
}) {
  return (
    <div role="tablist" aria-label={label} className={cn('akp-tabs', small && 'small')}>
      {items.map(([v, text]) => (
        <button key={v} type="button" role="tab" aria-selected={v === value} onClick={() => onChange(v)}>{text}</button>
      ))}
    </div>
  );
}

const STATUS_CLASS: Record<Tone, string> = { good: 's-good', warn: 's-warn', bad: 's-crit', neutral: 's-none' };

export function StatusPill({ tone, children }: { tone: Tone; children: ReactNode }) {
  return <span className={cn('akp-status', STATUS_CLASS[tone])}><i aria-hidden="true" />{children}</span>;
}

/**
 * Change against the previous period as "▲ +1.2%" / "▼ −0.40 pts", green when better and red when worse (more outage
 * or more problem sites is worse); nothing when either value is missing.
 */
export function ChangeText({ current, previous, unit = '%', higherIsBetter }: {
  current: number | null | undefined; previous: number | null | undefined; unit?: 'pts' | '%'; higherIsBetter: boolean | null;
}) {
  const c = change(current, previous, unit);
  if (!c) return <span className="muted">—</span>;
  const good = higherIsBetter == null || c.diff === 0 ? null : (c.diff > 0) === higherIsBetter;
  return (
    <span className={cn('num', good === true && 'up-good', good === false && 'up-bad')}>
      {c.diff > 0 ? '▲ ' : c.diff < 0 ? '▼ ' : ''}{c.text}
    </span>
  );
}

/** Stat strip: a row of labelled values with thin separators. */
export function StatStrip({ items, label }: { items: { label: string; value: ReactNode; sub?: ReactNode }[]; label: string }) {
  return (
    <div className="akp-stat" role="group" aria-label={label}>
      {items.map((i) => (
        <div key={i.label}>
          <div className="l">{i.label}</div>
          <div className="v">{i.value}</div>
          {i.sub && <div className="s">{i.sub}</div>}
        </div>
      ))}
    </div>
  );
}

/**
 * Horizontal bars of the weakest units (reference "bars"): `target` draws a tick (availability at 98.5%); values below
 * it are red. Values are shown as given.
 */
export function Bars({ rows, min = 0, max, target, label }: {
  rows: { key: string; name: string; value: number; display: string; title?: string }[]; min?: number; max: number; target?: number; label: string;
}) {
  const span = Math.max(max - min, 1e-9);
  const at = (v: number) => Math.max(0, Math.min(100, (100 * (v - min)) / span));
  return (
    <div className="akp-bars" role="img" aria-label={label}>
      {rows.map((r) => (
        <div key={r.key} className="row" title={r.title ?? `${r.name}: ${r.display}`}>
          <span className="name">{r.name}</span>
          <span className="track">
            <span className={cn('fill', target != null && r.value < target && 'crit')} style={{ width: `${at(r.value)}%` }} />
            {target != null && <span className="tick" style={{ left: `calc(${at(target)}% - 1px)` }} aria-hidden="true" />}
          </span>
          <span className="val">{r.display}</span>
        </div>
      ))}
    </div>
  );
}

/** Sparkline (reference "spark", 96 × 26): the last point green when it improved, red when it got worse. */
export function Spark({ values, higherIsBetter }: { values: (number | null)[]; higherIsBetter: boolean }) {
  const pts = values.map((v, i) => [i, v] as const).filter((p): p is readonly [number, number] => p[1] != null);
  if (pts.length < 2) return <span className="muted">—</span>;
  const [w, h, pad] = [96, 26, 3];
  const vs = pts.map((p) => p[1]);
  const lo = Math.min(...vs);
  const hi = Math.max(...vs);
  const x = (i: number) => pad + ((w - 2 * pad) * i) / Math.max(1, values.length - 1);
  const y = (v: number) => (hi === lo ? h / 2 : h - pad - ((h - 2 * pad) * (v - lo)) / (hi - lo));
  const [last, prev] = [pts.at(-1)!, pts.at(-2)!];
  const better = last[1] === prev[1] ? null : (last[1] > prev[1]) === higherIsBetter;
  return (
    <svg width={w} height={h} viewBox={`0 0 ${w} ${h}`} aria-hidden="true">
      <polyline fill="none" stroke="var(--akp-accent)" strokeWidth="1.5" points={pts.map(([i, v]) => `${x(i)},${y(v)}`).join(' ')} />
      <circle cx={x(last[0])} cy={y(last[1])} r="2.5" fill={better === false ? 'var(--akp-crit)' : better === true ? 'var(--akp-good)' : 'var(--akp-ink2)'} />
    </svg>
  );
}
