import type { ReactNode } from 'react';
import { Activity, AlertOctagon, CalendarRange, Clock, RadioTower } from 'lucide-react';
import { Card } from '@/components/ui/card';
import { Skeleton } from '@/components/ui/skeleton';
import { cn } from '@/lib/utils';
import { formatMinutes, formatNumber, formatPct, formatShortDate } from '../../lib/format';
import type { SummaryResponse } from '../../types';

interface KpiCardsProps {
  summary: SummaryResponse | null;
  loading: boolean;
  scopeLabel: string;
  onShowBelow60: () => void;
}

export function KpiCards({ summary, loading, scopeLabel, onShowBelow60 }: KpiCardsProps) {
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

  return (
    <section aria-label="Key indicators" className={cn('grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-5', loading && 'opacity-60')}>
      <Kpi
        icon={<CalendarRange />}
        label="MTD uptime"
        value={formatPct(m.mtd_uptime_pct)}
        detail={`${formatShortDate(mtd.start)} – ${formatShortDate(mtd.end)} · ${mtd.days_reported} days`}
        emphasis
      />
      <Kpi icon={<Activity />} label="Daily uptime" value={formatPct(m.daily_uptime_pct)} detail={`On ${day}`} />
      <Kpi
        icon={<RadioTower />}
        label="Sites in scope"
        value={formatNumber(m.sites_in_scope)}
        detail={`${scopeLabel} · ${formatNumber(m.sites_total)} sites in total`}
      />
      <Kpi
        icon={<AlertOctagon />}
        label="Sites below 60% MTD"
        value={formatNumber(m.sites_below_60_mtd)}
        detail={`${formatNumber(m.sites_at_or_above_98_5_mtd)} sites at 98.5% or above`}
        tone={m.sites_below_60_mtd ? 'critical' : undefined}
        action={m.sites_below_60_mtd ? { label: 'List sites', onClick: onShowBelow60 } : undefined}
      />
      <Kpi
        icon={<Clock />}
        label="Outage minutes on date"
        value={formatMinutes(m.daily_outage_minutes)}
        detail={`MTD ${formatMinutes(m.mtd_outage_minutes)} · ${formatNumber(m.sites_down_full_day)} sites down all day`}
      />
    </section>
  );
}

interface KpiProps {
  icon: ReactNode;
  label: string;
  value: string;
  detail: string;
  emphasis?: boolean;
  tone?: 'warning' | 'critical';
  action?: { label: string; onClick: () => void };
}

function Kpi({ icon, label, value, detail, emphasis, tone, action }: KpiProps) {
  return (
    <Card className={cn('gap-1.5 px-4 py-3.5', emphasis && 'ring-2 ring-primary/15')}>
      <div className="flex items-center justify-between text-xs font-medium text-muted-foreground [&_svg]:size-3.5">
        <span>{label}</span>
        <span aria-hidden="true" className={cn(tone === 'critical' && 'text-destructive', tone === 'warning' && 'text-amber-600')}>{icon}</span>
      </div>
      <p className={cn('text-2xl font-semibold tabular-nums tracking-tight', tone === 'critical' && 'text-destructive')}>{value}</p>
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
