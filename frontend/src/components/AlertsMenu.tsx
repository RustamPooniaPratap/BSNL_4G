import { useState } from 'react';
import { Link } from 'react-router-dom';
import { AlertOctagon, AlertTriangle, Bell, ChevronRight, Info } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Popover, PopoverContent, PopoverTrigger } from '@/components/ui/popover';
import { cn } from '@/lib/utils';
import { useWorkbook } from '../context/workbook';
import { useApiQuery } from '../hooks/useApiQuery';
import { fetchAlerts } from '../services/api';
import type { AlertSeverity, DashboardAlert } from '../types';

// Highest priority first; the API already orders alerts within each level.
const SEVERITY_ORDER: AlertSeverity[] = ['critical', 'warning', 'info'];

const SEVERITY_STYLE: Record<AlertSeverity, { icon: typeof Info; className: string; label: string }> = {
  critical: { icon: AlertOctagon, className: 'text-destructive', label: 'Critical' },
  warning: { icon: AlertTriangle, className: 'text-amber-600', label: 'Warning' },
  info: { icon: Info, className: 'text-sky-700', label: 'Information' },
};

/** Header bell: the most important alerts for the active workbook, computed by the API. */
export function AlertsMenu() {
  const { active, version } = useWorkbook();
  const [open, setOpen] = useState(false);
  const { data, error, loading } = useApiQuery(active ? `${version}|alerts` : null, fetchAlerts);

  const alerts = data?.alerts ?? [];
  const groups = SEVERITY_ORDER
    .map((severity) => ({ severity, items: alerts.filter((a) => a.severity === severity) }))
    .filter((group) => group.items.length > 0);
  const urgent = (data?.counts.critical ?? 0) + (data?.counts.warning ?? 0);
  const hasCritical = (data?.counts.critical ?? 0) > 0;
  const label = active
    ? `Alerts: ${urgent} need${urgent === 1 ? 's' : ''} attention`
    : 'Alerts: no workbook loaded';

  return (
    <Popover open={open} onOpenChange={setOpen}>
      <PopoverTrigger asChild>
        <Button variant="ghost" size="icon" className="relative" aria-label={label}>
          <Bell />
          {urgent > 0 && (
            <span
              aria-hidden="true"
              className={cn(
                'absolute -top-0.5 -right-0.5 flex h-4 min-w-4 items-center justify-center rounded-full px-1 text-[10px] font-semibold text-white',
                hasCritical ? 'bg-destructive' : 'bg-amber-500',
              )}
            >
              {urgent > 9 ? '9+' : urgent}
            </span>
          )}
        </Button>
      </PopoverTrigger>
      <PopoverContent align="end" className="w-96 p-0">
        <div className="flex items-center justify-between border-b px-4 py-2.5">
          <p className="text-sm font-semibold">Alerts</p>
          {data && (
            <p className="text-xs text-muted-foreground">
              {urgent} need{urgent === 1 ? 's' : ''} attention · {alerts.length} total
            </p>
          )}
        </div>
        {!active ? (
          <Empty text="Upload the Master workbook to see alerts." link="/workbook" linkText="Upload workbook" onNavigate={() => setOpen(false)} />
        ) : error ? (
          <Empty text={error.message} />
        ) : loading && !data ? (
          <Empty text="Checking the latest data…" />
        ) : !alerts.length ? (
          <Empty text="No alerts. The latest data passed every check." />
        ) : (
          <div className="max-h-[28rem] overflow-y-auto">
            {groups.map(({ severity, items }) => (
              <section key={severity} aria-label={`${SEVERITY_STYLE[severity].label} alerts`}>
                <h3 className={cn('bg-muted/50 px-4 py-1.5 text-[11px] font-semibold tracking-wide uppercase', SEVERITY_STYLE[severity].className)}>
                  {SEVERITY_STYLE[severity].label} ({items.length})
                </h3>
                <ul className="divide-y">
                  {items.map((alert) => <AlertItem key={alert.id} alert={alert} onNavigate={() => setOpen(false)} />)}
                </ul>
              </section>
            ))}
          </div>
        )}
        {active && (
          <div className="flex items-center justify-between border-t px-4 py-2.5 text-xs text-muted-foreground">
            <span>Based on the latest reporting date</span>
            <Link to="/data-source" onClick={() => setOpen(false)} className="font-medium text-foreground underline-offset-4 hover:underline">
              Data quality details
            </Link>
          </div>
        )}
      </PopoverContent>
    </Popover>
  );
}

function AlertItem({ alert, onNavigate }: { alert: DashboardAlert; onNavigate: () => void }) {
  const style = SEVERITY_STYLE[alert.severity];
  const Icon = style.icon;
  return (
    <li>
      <Link
        to={alert.link}
        onClick={onNavigate}
        className="flex gap-3 px-4 py-3 transition-colors hover:bg-muted focus-visible:bg-muted focus-visible:outline-none"
      >
        <Icon className={cn('mt-0.5 size-4 shrink-0', style.className)} aria-label={style.label} />
        <span className="min-w-0 flex-1">
          <span className="block text-sm leading-snug font-medium">{alert.title}</span>
          <span className="mt-0.5 block text-xs leading-snug text-muted-foreground">{alert.detail}</span>
        </span>
        <ChevronRight className="mt-0.5 size-4 shrink-0 text-muted-foreground" aria-hidden="true" />
      </Link>
    </li>
  );
}

function Empty({ text, link, linkText, onNavigate }: { text: string; link?: string; linkText?: string; onNavigate?: () => void }) {
  return (
    <div className="px-4 py-6 text-center text-sm text-muted-foreground">
      <p>{text}</p>
      {link && <Link to={link} onClick={onNavigate} className="mt-2 inline-block font-medium text-foreground underline underline-offset-4">{linkText}</Link>}
    </div>
  );
}
