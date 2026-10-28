import type { ReactNode } from 'react';
import { Link } from 'react-router-dom';
import {
  Activity, ArrowDownRight, ArrowRight, ArrowUpRight, Award, Boxes, CircleGauge, ClipboardCheck,
  Info, Layers, Minus, ShieldCheck, Siren, TimerOff, TriangleAlert, type LucideIcon,
} from 'lucide-react';
import { Line, LineChart, ResponsiveContainer, YAxis } from 'recharts';
import { Card } from '@/components/ui/card';
import { Popover, PopoverContent, PopoverTrigger } from '@/components/ui/popover';
import { cn } from '@/lib/utils';
import { formatMinutes, formatNumber, formatPct } from '../../lib/format';
import type { Delta, Kpi } from '../../lib/portfolio';
import type { ConversionActivity } from '../../types';
import { reportTypeColor } from '../dashboard/constants';

/** Icon tile colours, one per card, as soft tinted squares. */
const TINT = {
  sky: 'bg-sky-100 text-sky-700',
  violet: 'bg-violet-100 text-violet-700',
  emerald: 'bg-emerald-100 text-emerald-700',
  teal: 'bg-teal-100 text-teal-700',
  red: 'bg-red-100 text-red-700',
  orange: 'bg-orange-100 text-orange-700',
  amber: 'bg-amber-100 text-amber-700',
  slate: 'bg-slate-100 text-slate-600',
} as const;
type Tint = keyof typeof TINT;

/** Presentation of each KPI from buildKpis: icon, colour and the "View …" link text. */
const LOOK: Record<string, { icon: LucideIcon; tint: Tint; view: string }> = {
  total: { icon: Layers, tint: 'sky', view: 'View all sites' },
  mtd_uptime: { icon: Activity, tint: 'emerald', view: 'Open Overview' },
  om_mtd_uptime: { icon: ShieldCheck, tint: 'teal', view: 'Open O&M Start view' },
  daily_uptime: { icon: CircleGauge, tint: 'sky', view: 'Open Overview' },
  gte_98_5: { icon: Award, tint: 'emerald', view: 'Open Threshold Analysis' },
  lt_60: { icon: Siren, tint: 'red', view: 'View sites below 60%' },
  down_all_day: { icon: TriangleAlert, tint: 'orange', view: 'View sites down all day' },
  period_uptime: { icon: Activity, tint: 'emerald', view: 'Open Overview' },
  period_om_uptime: { icon: ShieldCheck, tint: 'teal', view: 'Open O&M Start view' },
  period_outage: { icon: TimerOff, tint: 'orange', view: 'Open Overview' },
  period_reported: { icon: ClipboardCheck, tint: 'violet', view: 'Open data quality' },
};

const showValue = (value: number | null, unit: Kpi['unit']) =>
  (value == null ? 'Not available' : unit === 'pct' ? formatPct(value) : unit === 'minutes' ? formatMinutes(value) : formatNumber(value));
const share = (part: number, whole: number) => (whole ? (100 * part) / whole : null);

export function DeltaChip({ d, higherIsBetter }: { d: Delta | null; higherIsBetter: boolean | null }) {
  if (!d) return null;
  const Icon = d.absolute > 0 ? ArrowUpRight : d.absolute < 0 ? ArrowDownRight : Minus;
  const good = higherIsBetter == null || d.absolute === 0 ? null : (d.absolute > 0) === higherIsBetter;
  const text = d.unit === 'pct'
    ? `${d.absolute > 0 ? '+' : ''}${d.absolute.toFixed(2)} pts`
    : `${d.absolute > 0 ? '+' : ''}${formatNumber(d.absolute)}${d.relativePct != null ? ` (${d.relativePct > 0 ? '+' : ''}${d.relativePct}%)` : ''}`;
  return (
    <span className={cn('inline-flex items-center gap-0.5 text-xs font-medium', good === true && 'text-emerald-700', good === false && 'text-destructive', good == null && 'text-muted-foreground')}>
      <Icon className="size-3.5" aria-hidden="true" />{text}
    </span>
  );
}

function Definition({ label, text }: { label: string; text: string }) {
  return (
    <Popover>
      <PopoverTrigger className="relative z-10 rounded-full text-muted-foreground hover:text-foreground focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none"
        aria-label={`How ${label} is calculated`}>
        <Info className="size-3.5" />
      </PopoverTrigger>
      <PopoverContent className="w-72 text-xs">{text}</PopoverContent>
    </Popover>
  );
}

function IconTile({ icon: Icon, tint }: { icon: LucideIcon; tint: Tint }) {
  return (
    <span className={cn('flex size-9 shrink-0 items-center justify-center rounded-lg', TINT[tint])} aria-hidden="true">
      <Icon className="size-4" />
    </span>
  );
}

function ViewLink({ to, children }: { to: string; children: ReactNode }) {
  return (
    <Link to={to} className="relative z-10 inline-flex items-center gap-1 text-xs font-semibold text-primary hover:underline focus-visible:underline focus-visible:outline-none">
      {children} <ArrowRight className="size-3.5" aria-hidden="true" />
    </Link>
  );
}

/** One KPI: title with its definition, icon tile, big value (optionally "of N"), a context line and a link. */
export function KpiTile({ kpi, of, sub, compareOn, sparkline, icon, tint, view, vsLabel = 'vs previous date' }: {
  kpi: Kpi; of?: string; sub?: ReactNode; compareOn: boolean; sparkline?: { v: number | null }[]; vsLabel?: string;
  /** null: no icon tile. */
  icon?: LucideIcon | null; tint?: Tint; view?: string;
}) {
  const look = LOOK[kpi.id];
  const critical = kpi.tone === 'critical' && Boolean(kpi.value);
  return (
    <Card className={cn('relative gap-0 rounded-xl px-4 py-3 shadow-xs transition-shadow hover:shadow-md', critical && 'border-red-200', kpi.tone === 'warning' && 'border-amber-200')}>
      <div className="flex items-start justify-between gap-3">
        <div className="flex min-w-0 items-center gap-1.5">
          <Link to={kpi.link} className="truncate text-sm font-medium text-foreground/80 hover:text-foreground focus-visible:underline focus-visible:outline-none">
            {kpi.label}
          </Link>
          <Definition label={kpi.label} text={kpi.definition} />
        </div>
        {icon !== null && <IconTile icon={icon ?? look?.icon ?? Boxes} tint={tint ?? look?.tint ?? 'slate'} />}
      </div>
      <p className={cn('flex items-baseline gap-1.5', icon === null ? 'mt-2' : '-mt-2')}>
        <span className={cn('text-2xl font-semibold tracking-tight tabular-nums', kpi.value == null && 'text-lg font-medium text-muted-foreground', critical && 'text-destructive')}>
          {showValue(kpi.value, kpi.unit)}
        </span>
        {of && kpi.value != null && <span className="text-sm text-muted-foreground">{of}</span>}
      </p>
      <p className="mt-0.5 text-[11px] text-muted-foreground">{kpi.period}</p>
      {sub && <p className="mt-1.5 text-xs text-muted-foreground">{sub}</p>}
      {compareOn && kpi.delta && (
        <p className="mt-1 text-xs"><DeltaChip d={kpi.delta} higherIsBetter={kpi.higherIsBetter} /> <span className="text-muted-foreground">{vsLabel}</span></p>
      )}
      {sparkline && (
        <div className="mt-2 h-8" aria-hidden="true">
          <ResponsiveContainer width="100%" height="100%">
            <LineChart data={sparkline}><YAxis hide domain={['dataMin - 1', 'dataMax + 1']} /><Line isAnimationActive={false} dataKey="v" stroke="var(--chart-1)" strokeWidth={1.5} dot={false} connectNulls={false} /></LineChart>
          </ResponsiveContainer>
        </div>
      )}
      <div className="mt-auto pt-2"><ViewLink to={kpi.link}>{view ?? look?.view ?? 'View details'}</ViewLink></div>
    </Card>
  );
}

export interface Segment {
  label: string;
  value: number;
  color: string;
  /** Full wording, shown on hover when the label is shortened. */
  title?: string;
  /** Change of the share in percentage points against `changeLabel`; null when it cannot be calculated. */
  change?: number | null;
  changeNote?: string;
  /** For follow-up groups a fall is the good direction. */
  lowerIsBetter?: boolean;
}

function ShareChange({ segment, against }: { segment: Segment; against?: string }) {
  const v = segment.change;
  if (v == null) return <span className="text-muted-foreground" title={segment.changeNote}>—</span>;
  const good = v === 0 ? null : segment.lowerIsBetter ? v < 0 : v > 0;
  return (
    <span className={cn(good === true ? 'text-emerald-700' : good === false ? 'text-destructive' : 'text-muted-foreground')}
      title={`${v > 0 ? '+' : ''}${v.toFixed(1)} pts${against ? ` vs ${against}` : ''}`}>
      {v > 0 ? '▲ +' : v < 0 ? '▼ −' : ''}{Math.abs(v).toFixed(1)}
    </span>
  );
}

/** Wide card: a total on the left; a stacked bar with a legend of counts and shares on the right. */
export function CompositeTile({ label, definition, icon, tint, headline, value, share: valueShare, unit, sub, segments, extra, note, link, view, changeLabel }: {
  label: string; definition: string; icon?: LucideIcon; tint?: Tint;
  /** Names the big number when it is one part of the bar (e.g. "Sites Converted"); its share is shown beside it. */
  headline?: string; value: number | null; share?: number | null; unit: string; sub?: ReactNode;
  /** Parts of the total, drawn as one bar; shares are of their sum. */
  segments: Segment[] | null; extra?: { label: string; value: number | null }[]; note?: string; link?: string; view?: string;
  /** With segment changes: what they are compared with (e.g. "Sep-26"); adds a change column. */
  changeLabel?: string;
}) {
  const whole = (segments ?? []).reduce((sum, s) => sum + s.value, 0);
  const changes = Boolean(changeLabel && segments?.some((s) => 'change' in s));
  const cols = 'grid-cols-[minmax(0,1fr)_auto_3.5rem]';
  if (changes && segments && whole > 0) {
    // Hero + follow-ups: the first part (e.g. Sites Converted) large on the left, the other parts as stat
    // columns beside it (as in the On-Air vs O&M Start card); one bar below shows the split.
    const [hero, ...rest] = segments;
    return (
      <Card role="region" aria-label={label} className="relative gap-0 rounded-xl px-4 py-3 shadow-xs transition-shadow hover:shadow-md md:col-span-2 xl:col-span-1">
        <p className="flex items-center gap-1.5 text-sm font-medium text-foreground/80">{label} <Definition label={label} text={definition} /></p>
        <dl className="mt-2 grid divide-x" style={{ gridTemplateColumns: `minmax(0, 1.3fr) repeat(${rest.length}, minmax(0, 1fr))` }}>
          <div className="min-w-0 pr-3" title={hero.title}>
            <dt className="truncate text-[11px] font-semibold tracking-wide text-emerald-700 uppercase">{headline ?? hero.label}</dt>
            <dd className="mt-0.5 inline text-2xl font-semibold tracking-tight tabular-nums">{formatNumber(hero.value)}</dd>
            <dd className="ml-1.5 inline text-base font-semibold text-emerald-700 tabular-nums">{formatPct(valueShare ?? share(hero.value, whole), 1)}</dd>
            <dd className="text-[11px] text-muted-foreground tabular-nums">{unit}</dd>
            <dd className="text-[11px] text-muted-foreground tabular-nums"><ShareChange segment={hero} against={changeLabel} /> vs {changeLabel}</dd>
          </div>
          {rest.map((s) => (
            <div key={s.label} className="min-w-0 px-3 last:pr-0" title={s.title}>
              <dt className="flex min-w-0 items-start gap-1.5 text-xs leading-tight text-muted-foreground">
                <span className="mt-1 size-2 shrink-0 rounded-full" style={{ background: s.color }} aria-hidden="true" />
                <span className="min-w-0">{s.label}</span>
              </dt>
              <dd className="mt-0.5 text-xl font-semibold tracking-tight tabular-nums">{formatNumber(s.value)}</dd>
              <dd className="text-[11px] text-muted-foreground tabular-nums">
                {formatPct(share(s.value, whole), 1)} · <ShareChange segment={s} against={changeLabel} />
              </dd>
            </div>
          ))}
        </dl>
        <div className="mt-2.5 flex h-1.5 w-full gap-0.5 overflow-hidden rounded-full bg-muted" role="img"
          aria-label={segments.map((s) => `${s.label} ${formatNumber(s.value)}`).join(', ')}>
          {segments.filter((s) => s.value > 0).map((s) => (
            <span key={s.label} className="h-full first:rounded-l-full last:rounded-r-full" style={{ width: `${(100 * s.value) / whole}%`, background: s.color }} />
          ))}
        </div>
        {note && <p className="mt-1.5 text-xs text-muted-foreground">{note}</p>}
        {link && <div className="mt-auto pt-2"><ViewLink to={link}>{view ?? 'View details'}</ViewLink></div>}
      </Card>
    );
  }
  return (
    <Card role="region" aria-label={label} className="relative gap-0 rounded-xl px-4 py-3 shadow-xs transition-shadow hover:shadow-md md:col-span-2 xl:col-span-1">
      <div className={cn('grid grid-cols-1 gap-4 sm:items-center', icon ? 'sm:grid-cols-[minmax(0,0.9fr)_minmax(0,1.2fr)_auto]' : 'sm:grid-cols-[minmax(0,0.8fr)_minmax(0,1.4fr)]')}>
        <div className="min-w-0">
          <p className="flex items-center gap-1.5 text-sm font-medium text-foreground/80">{label} <Definition label={label} text={definition} /></p>
          {headline && <p className="mt-2 text-xs font-semibold tracking-wide text-emerald-700 uppercase">{headline}</p>}
          <p className={cn('flex flex-wrap items-baseline gap-x-1.5', headline ? 'mt-0.5' : 'mt-2')}>
            <span className={cn('text-2xl font-semibold tracking-tight tabular-nums', value == null && 'text-lg font-medium text-muted-foreground')}>
              {value == null ? 'Not available' : formatNumber(value)}
            </span>
            {value != null && valueShare != null && <span className="text-lg font-semibold text-emerald-700 tabular-nums">{formatPct(valueShare, 1)}</span>}
            {value != null && <span className="text-sm text-muted-foreground">{unit}</span>}
          </p>
          {sub && <p className="mt-1.5 text-xs text-muted-foreground">{sub}</p>}
          {link && <div className="mt-3"><ViewLink to={link}>{view ?? 'View details'}</ViewLink></div>}
        </div>
        <div className="min-w-0 space-y-2">
          {segments && whole > 0 ? (
            <>
              <div className="flex h-2.5 w-full gap-0.5 overflow-hidden rounded-full bg-muted" role="img"
                aria-label={segments.map((s) => `${s.label} ${formatNumber(s.value)}`).join(', ')}>
                {segments.filter((s) => s.value > 0).map((s) => (
                  <span key={s.label} className="h-full first:rounded-l-full last:rounded-r-full" style={{ width: `${(100 * s.value) / whole}%`, background: s.color }} />
                ))}
              </div>
              <dl className="space-y-1.5 text-sm">
                {segments.map((s) => (
                  <div key={s.label} className={cn('grid items-center gap-2', cols)} title={s.title}>
                    <dt className="flex min-w-0 items-center gap-2 text-foreground/80">
                      <span className="size-2.5 shrink-0 rounded-full" style={{ background: s.color }} aria-hidden="true" />
                      <span className="min-w-0 truncate">{s.label}</span>
                    </dt>
                    <dd className="text-right font-semibold tabular-nums">{formatNumber(s.value)}</dd>
                    <dd className="text-right text-xs text-muted-foreground tabular-nums">{formatPct(share(s.value, whole), 1)}</dd>
                  </div>
                ))}
                {extra?.map((e) => (
                  <div key={e.label} className="grid grid-cols-[minmax(0,1fr)_auto_3.5rem] items-center gap-2">
                    <dt className="flex min-w-0 items-center gap-2 text-foreground/80">
                      <span className="size-2.5 shrink-0 rounded-full border border-muted-foreground/50" aria-hidden="true" />
                      <span className="truncate">{e.label}</span>
                    </dt>
                    <dd className="text-right font-semibold tabular-nums">{e.value == null ? '—' : formatNumber(e.value)}</dd>
                    <dd />
                  </div>
                ))}
              </dl>
            </>
          ) : <p className="text-sm text-muted-foreground">{note ?? 'Not available for these filters.'}</p>}
          {segments && whole > 0 && note && <p className="text-xs text-muted-foreground">{note}</p>}
        </div>
        {icon && <div className="hidden self-start sm:block"><IconTile icon={icon} tint={tint ?? 'slate'} /></div>}
      </div>
    </Card>
  );
}

/** Section heading in small spaced capitals, as in the reference design. */
export function KpiSection({ label, columns = 'wide', children }: { label: string; columns?: 'wide' | 'four' | 'portfolio'; children: ReactNode }) {
  return (
    <section aria-label={label} className="space-y-2">
      <h2 className="text-xs font-semibold tracking-[0.14em] text-muted-foreground uppercase">{label}</h2>
      <div className={cn('grid grid-cols-1 gap-3 md:grid-cols-2',
        columns === 'wide' ? 'xl:grid-cols-[repeat(2,minmax(0,1fr))_minmax(0,1.6fr)]'
          : columns === 'portfolio' ? 'xl:grid-cols-[minmax(0,1.25fr)_minmax(0,1fr)]' : 'xl:grid-cols-4')}>
        {children}
      </div>
    </section>
  );
}

/** Tone of a summary metric: neutral scope, blue On-Air, green O&M Start, red outstanding gap. */
export type MetricTone = 'neutral' | 'onAir' | 'omStart' | 'gap';
const TONES: Record<MetricTone, { dot: string; value: string; pct: string; bar?: string }> = {
  neutral: { dot: 'bg-slate-400', value: 'text-foreground', pct: 'text-foreground' },
  onAir: { dot: 'bg-sky-600', value: 'text-foreground', pct: 'text-sky-700', bar: 'bg-sky-600' },
  omStart: { dot: 'bg-emerald-600', value: 'text-foreground', pct: 'text-emerald-700', bar: 'bg-emerald-600' },
  gap: { dot: 'bg-red-500', value: 'text-red-600', pct: 'text-red-600' },
};

export interface SummaryMetric {
  label: string;
  value: number | null;
  tone: MetricTone;
  /** Share of total scope (0-100), shown in the supporting line and as a thin bar; omit for none. */
  pct?: number | null;
  /** Short supporting line under the value. */
  note?: ReactNode;
  /** Shown instead of the value when it is null. */
  missing?: string;
  /** Project-wise counts under the value (e.g. 4G Saturation / LWE); omitted when not available. */
  split?: { project: string; value: number }[] | null;
}

/**
 * Compact summary of related counts (e.g. Total sites, On-Air, O&M Start, Difference): four columns on desktop,
 * two by two on medium screens, stacked on mobile, with the links in a footer right under the metrics.
 */
export function SummaryMetricsTile({ label, definition, metrics, links }: {
  label: string; definition: string; metrics: SummaryMetric[]; links: { to: string; view: string }[];
}) {
  return (
    <Card role="region" aria-label={label} className="h-full gap-0 rounded-xl px-4 py-3 shadow-xs transition-shadow hover:shadow-md md:col-span-2 xl:col-span-1">
      <p className="flex items-center gap-1.5 text-sm font-medium text-foreground/80">{label} <Definition label={label} text={definition} /></p>
      <dl className="mt-2 grid grid-cols-1 gap-y-3 sm:grid-cols-2 lg:grid-cols-4 lg:divide-x">
        {metrics.map((m) => {
          const tone = TONES[m.tone];
          return (
            <div key={m.label} className="min-w-0 sm:pr-3 lg:px-3 lg:first:pl-0 lg:last:pr-0">
              <dt className="flex items-center gap-1.5 text-xs font-medium text-muted-foreground">
                <span className={cn('size-2 shrink-0 rounded-full', tone.dot)} aria-hidden="true" />
                <span className="truncate" title={m.label}>{m.label}</span>
              </dt>
              <dd className={cn('mt-0.5 text-2xl leading-none font-semibold tracking-tight tabular-nums', tone.value,
                m.value == null && 'text-base font-medium text-muted-foreground')}>
                {m.value == null ? (m.missing ?? 'Not available') : formatNumber(m.value)}
              </dd>
              {m.split && m.split.length > 0 && (
                <dd className="mt-1 space-y-px text-xs" aria-label={`${m.label} by project`}>
                  {m.split.map((s) => (
                    <div key={s.project} className="flex items-center justify-between gap-2">
                      <span className="flex min-w-0 items-center gap-1.5 text-muted-foreground">
                        <span className="size-1.5 shrink-0 rounded-full" style={{ background: reportTypeColor(s.project) }} aria-hidden="true" />
                        <span className="truncate">{s.project}</span>
                      </span>
                      <span className={cn('font-semibold tabular-nums', m.tone === 'gap' ? 'text-red-600' : 'text-foreground/90')}>{formatNumber(s.value)}</span>
                    </div>
                  ))}
                </dd>
              )}
              {m.pct != null && tone.bar && (
                <dd className="mt-1.5 h-1 w-full overflow-hidden rounded-full bg-red-400" aria-hidden="true">
                  <div className={cn('h-full rounded-l-full', tone.bar)} style={{ width: `${Math.min(100, Math.max(0, m.pct))}%` }} />
                </dd>
              )}
              {(m.note || m.pct != null) && (
                <dd className="mt-1 text-xs leading-snug text-muted-foreground">
                  {m.pct != null && <span className={cn('font-semibold', tone.pct)}>{formatPct(m.pct, 1)}</span>}
                  {m.pct != null && m.note ? ' ' : ''}{m.note}
                </dd>
              )}
            </div>
          );
        })}
      </dl>
      {links.length > 0 && (
        <div className="mt-2.5 flex flex-wrap items-center gap-x-6 gap-y-2 border-t pt-2">
          {links.map((l) => <ViewLink key={l.to} to={l.to}>{l.view}</ViewLink>)}
        </div>
      )}
    </Card>
  );
}

const ON_AIR_COLOR = '#0284c7';
const OM_START_COLOR = '#059669';

export function ConversionActivityTile({ total, onAir, omStart, activity, link, view, definition }: {
  total: number; onAir: number; omStart: number | null; activity: ConversionActivity | null;
  link?: string; view?: string; definition: string;
}) {
  const label = 'Site Conversion Progress';
  const bars: { name: string; value: number | null; gapLabel: string; color: string }[] = [
    { name: 'On-Air', value: onAir, gapLabel: 'not On-Air', color: ON_AIR_COLOR },
    { name: 'O&M Start', value: omStart, gapLabel: 'remaining', color: OM_START_COLOR },
  ];
  const months = activity ? [activity.previous_month, activity.month] : [];
  const cell = (n: number | null) => (n == null ? <span className="text-muted-foreground">—</span> : formatNumber(n));
  return (
    <Card role="region" aria-label={label} className="relative gap-0 rounded-xl px-4 py-3 shadow-xs transition-shadow hover:shadow-md md:col-span-2 xl:col-span-1">
      <div className="flex items-baseline justify-between gap-3">
        <p className="flex items-center gap-1.5 text-sm font-medium text-foreground/80">{label} <Definition label={label} text={definition} /></p>
        <p className="text-xs text-muted-foreground">Total site scope <span className="text-base font-semibold text-foreground tabular-nums">{formatNumber(total)}</span></p>
      </div>
      <dl className="mt-2 space-y-2">
        {bars.map((b) => {
          const pct = b.value != null && total ? (100 * b.value) / total : null;
          return (
            <div key={b.name}>
              <div className="flex items-baseline justify-between gap-2 text-sm">
                <dt className="font-medium">{b.name}</dt>
                <dd className="tabular-nums">
                  {b.value == null ? <span className="text-muted-foreground">Not available</span> : (
                    <><span className="font-semibold">{formatNumber(b.value)}</span>
                      <span className="ml-1.5 font-semibold" style={{ color: b.color }}>{formatPct(pct, 1)}</span>
                      <span className="ml-1.5 text-xs text-muted-foreground">· <span className="text-red-600"><span className="font-semibold">{formatNumber(total - b.value)}</span> {b.gapLabel}</span></span></>
                  )}
                </dd>
              </div>
              <div className={cn('mt-1 h-2 w-full overflow-hidden rounded-full', pct == null ? 'bg-muted' : 'bg-red-400')} role="img" aria-label={`${b.name}: ${pct == null ? 'not available' : `${formatPct(pct, 1)} of total site scope`}`}>
                {pct != null && <div className="h-full rounded-l-full" style={{ width: `${pct}%`, background: b.color }} />}
              </div>
            </div>
          );
        })}
      </dl>
      {activity && (
        <table className="mt-2.5 w-full border-t text-xs" aria-label="Monthly additions">
          <thead>
            <tr className="text-[11px] text-muted-foreground">
              <th className="pt-1.5 text-left font-normal">Added in month</th>
              {months.map((m) => <th key={m.key} className="pt-1.5 text-right font-normal">{m.label}</th>)}
            </tr>
          </thead>
          <tbody>
            {([['On-Air', activity.on_air], ['O&M Start', activity.om_start]] as const).map(([name, a]) => (
              <tr key={name}>
                <th scope="row" className="text-left font-normal text-foreground/80">{name}</th>
                <td className="text-right font-semibold tabular-nums">{cell(a.last_month.count)}</td>
                <td className="text-right font-semibold tabular-nums">{cell(a.this_month.count)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
      {link && <div className="mt-auto pt-2"><ViewLink to={link}>{view ?? 'View details'}</ViewLink></div>}
    </Card>
  );
}
