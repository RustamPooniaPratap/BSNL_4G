import { CalendarRange } from 'lucide-react';
import { Card } from '@/components/ui/card';
import { Skeleton } from '@/components/ui/skeleton';
import { cn } from '@/lib/utils';
import { formatMinutes, formatNumber, formatPct, formatShortDate } from '../../lib/format';
import type { PeriodSummary } from '../../types';

interface PeriodKpiProps {
  period: PeriodSummary | null;
  loading: boolean;
  error: Error | null;
}

/** KPI for the Trend period in the filter bar; the cards above stay on the reporting date. */
export function PeriodKpi({ period, loading, error }: PeriodKpiProps) {
  if (error) {
    return (
      <Card className="flex-row items-center gap-2 px-4 py-3 text-sm text-destructive" role="alert">
        Trend period figures are unavailable: {error.message}
      </Card>
    );
  }
  if (!period) return <Skeleton className="h-20 w-full rounded-xl" aria-label="Loading trend period figures" />;

  const covered = period.kind === 'months'
    ? `${period.months} month${period.months === 1 ? '' : 's'} with data${period.days_reported ? `, incl. ${period.days_reported} days of the current month` : ''}`
    : period.days_reported
      ? `${period.days_reported} reported day${period.days_reported === 1 ? '' : 's'} (${formatShortDate(period.first_date)}–${formatShortDate(period.last_date)})`
      : 'No reported days in this period';
  const stats = [
    { label: 'Uptime', value: formatPct(period.uptime_pct) },
    { label: 'Outage minutes', value: formatMinutes(period.outage_minutes) },
    { label: 'Sites below 60%', value: formatNumber(period.sites_below_60), critical: period.sites_below_60 > 0 },
    { label: 'Sites at 98.5% or above', value: formatNumber(period.sites_at_or_above_98_5) },
  ];

  return (
    <Card
      className={cn('gap-0 border-primary/20 bg-primary/[0.03] px-4 py-3', loading && 'opacity-60')}
      role="region"
      aria-label="Trend period indicators"
    >
      <div className="flex flex-wrap items-center gap-x-6 gap-y-3">
        <div className="min-w-48">
          <p className="flex items-center gap-1.5 text-xs font-medium text-muted-foreground">
            <CalendarRange className="size-3.5" aria-hidden="true" /> Trend period
          </p>
          <p className="mt-0.5 text-sm font-semibold">{period.label}</p>
          <p className="text-xs text-muted-foreground">{covered}</p>
        </div>
        <dl className="grid flex-1 grid-cols-2 gap-x-6 gap-y-2 sm:grid-cols-4">
          {stats.map((stat) => (
            <div key={stat.label}>
              <dt className="text-xs text-muted-foreground">{stat.label}</dt>
              <dd className={cn('text-lg font-semibold tabular-nums', stat.critical && 'text-destructive')}>{stat.value}</dd>
            </div>
          ))}
        </dl>
      </div>
      <p className="mt-2 text-[11px] text-muted-foreground">
        Changes with the Trend period. Each site's uptime over the whole period decides whether it is below 60% or at 98.5%;
        the cards above are for the reporting date.
      </p>
    </Card>
  );
}
