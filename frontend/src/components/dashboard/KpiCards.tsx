import { useState, type ReactNode } from 'react';
import { AlertOctagon, ArrowDownRight, ArrowUpRight, CalendarRange, Clock, Minus, ShieldAlert, WifiOff } from 'lucide-react';
import { Card } from '@/components/ui/card';
import { Skeleton } from '@/components/ui/skeleton';
import { cn } from '@/lib/utils';
import { formatMinutes, formatNumber, formatPct, formatShortDate } from '../../lib/format';
import type { OutagePeriod, SummaryResponse } from '../../types';

interface KpiCardsProps {
  summary: SummaryResponse | null;
  loading: boolean;
  onShowBelow60: () => void;
}

/** Share of ``of`` (one decimal); null without a denominator. */
const share = (count: number | undefined, of: number | undefined) => (count != null && of ? (100 * count) / of : null);

/**
 * The five Overview KPIs (Overall, 4G Saturation and LWE all use this component with the page's filters). Every value
 * comes from /api/dashboard/summary/ for the active data source; nothing is computed or estimated here.
 */
export function KpiCards({ summary, loading, onShowBelow60 }: KpiCardsProps) {
  if (!summary) {
    return (
      <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-5" aria-busy="true">
        {Array.from({ length: 5 }, (_, i) => <Skeleton key={i} className="h-28 rounded-xl" />)}
      </div>
    );
  }

  const m = summary.metrics;
  const mtd = summary.mtd_window;
  const day = formatShortDate(summary.reporting_date);
  const withValue = m.sites_with_mtd_value;

  return (
    <section aria-label="Key indicators" className={cn('grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-5', loading && 'opacity-60')}>
      <Kpi
        icon={<CalendarRange />}
        label="MTD uptime"
        value={formatPct(m.mtd_uptime_pct)}
        detail={`${formatShortDate(mtd.start)} – ${formatShortDate(mtd.end)} · ${mtd.days_reported} days`}
        emphasis
      />
      <Kpi icon={<ShieldAlert />} label="Not meeting SLA" value={formatNumber(m.sites_not_meeting_sla_mtd ?? null)}
        share={share(m.sites_not_meeting_sla_mtd, withValue)} tone={m.sites_not_meeting_sla_mtd ? 'warning' : undefined}
        detail={`MTD uptime below 98.5% · of ${formatNumber(withValue ?? null)} sites with MTD data`} />
      <Kpi icon={<WifiOff />} label="Unique sites down" value={formatNumber(m.sites_down_full_day)}
        share={share(m.sites_down_full_day, m.sites_reported)} tone={m.sites_down_full_day ? 'critical' : undefined}
        detail={`Down all day (1,440 min) on ${day} · of ${formatNumber(m.sites_reported)} sites reported`} />
      <Kpi icon={<AlertOctagon />} label="Below 60% MTD" value={formatNumber(m.sites_below_60_mtd)}
        share={share(m.sites_below_60_mtd, withValue)} tone={m.sites_below_60_mtd ? 'critical' : undefined}
        detail={`of ${formatNumber(withValue ?? null)} sites with MTD data`}
        action={m.sites_below_60_mtd ? { label: 'List sites', onClick: onShowBelow60 } : undefined} />
      <OutageKpi summary={summary} />
    </section>
  );
}

const PERIODS: [OutagePeriod, string][] = [['day', 'Day'], ['mtd', 'MTD'], ['month', 'Month']];

/** Outage minutes of the day, month to date or full month, against the previous comparable period. */
function OutageKpi({ summary }: { summary: SummaryResponse }) {
  const [period, setPeriod] = useState<OutagePeriod>('mtd');
  const c = summary.outage_comparison?.[period];
  const fallback = period === 'day' ? summary.metrics.daily_outage_minutes : period === 'mtd' ? summary.metrics.mtd_outage_minutes : null;
  const value = c ? c.current : fallback;
  const Arrow = c?.direction === 'up' ? ArrowUpRight : c?.direction === 'down' ? ArrowDownRight : Minus;
  return (
    <Kpi icon={<Clock />} label="Outage minutes" value={value == null ? 'Not available' : formatMinutes(value)}
      header={(
        <div role="group" aria-label="Outage period" className="inline-flex rounded-md border p-px text-[10px]">
          {PERIODS.map(([v, l]) => (
            <button key={v} type="button" aria-pressed={v === period} onClick={() => setPeriod(v)}
              className={cn('rounded px-1.5 py-px font-medium', v === period ? 'bg-primary text-primary-foreground' : 'text-muted-foreground hover:text-foreground')}>{l}</button>
          ))}
        </div>
      )}
      detail={c ? (c.direction ? (
        <span className="inline-flex flex-wrap items-center gap-x-1" aria-label="Change against the previous period">
          <span className={cn('inline-flex items-center font-medium', c.direction === 'down' && 'text-emerald-700', c.direction === 'up' && 'text-destructive')}>
            <Arrow className="size-3.5" aria-hidden="true" />{c.change_pct == null ? '' : `${c.change_pct > 0 ? '+' : ''}${c.change_pct}%`}
            {c.direction === 'same' && 'No change'}
          </span>
          <span>vs {c.previous_period} ({formatMinutes(c.previous)})</span>
        </span>
      ) : <>{c.period} · {c.note}</>) : 'No comparison available'} />
  );
}

interface KpiProps {
  icon: ReactNode;
  label: string;
  value: string;
  detail: ReactNode;
  /** Share of the denominator named in ``detail``. */
  share?: number | null;
  header?: ReactNode;
  emphasis?: boolean;
  tone?: 'warning' | 'critical';
  action?: { label: string; onClick: () => void };
}

function Kpi({ icon, label, value, detail, share: pct, header, emphasis, tone, action }: KpiProps) {
  return (
    <Card role="group" aria-label={label} className={cn('gap-1.5 px-4 py-3.5', emphasis && 'ring-2 ring-primary/15')}>
      <div className="flex items-center justify-between gap-2 text-xs font-medium text-muted-foreground [&_svg]:size-3.5">
        <span>{label}</span>
        {header ?? <span aria-hidden="true" className={cn(tone === 'critical' && 'text-destructive', tone === 'warning' && 'text-amber-600')}>{icon}</span>}
      </div>
      <p className="flex items-baseline gap-2">
        <span className={cn('text-2xl font-semibold tabular-nums tracking-tight', tone === 'critical' && 'text-destructive')}>{value}</span>
        {pct != null && <span className="text-sm font-medium text-muted-foreground tabular-nums">{formatPct(pct, 1)}</span>}
      </p>
      <p className="text-xs leading-snug text-muted-foreground">{detail}</p>
      {action && (
        <button type="button" onClick={action.onClick}
          className="mt-0.5 self-start rounded text-xs font-medium text-primary underline-offset-4 hover:underline focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none">
          {action.label}
        </button>
      )}
    </Card>
  );
}
