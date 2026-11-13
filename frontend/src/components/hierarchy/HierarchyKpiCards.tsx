import { Activity, ShieldAlert, WifiOff, AlertOctagon, Wrench, Trophy } from 'lucide-react';
import { Card } from '@/components/ui/card';
import { formatNumber, formatPct } from '../../lib/format';
import type { HierarchyKpis } from '../../types/hierarchy';

interface HierarchyKpiCardsProps {
  kpis: HierarchyKpis;
  periodLabel?: string;
  scopeLabel?: string;
}

export function HierarchyKpiCards({ kpis, periodLabel = 'Oct-26 MTD', scopeLabel = 'On-Air sites' }: HierarchyKpiCardsProps) {
  return (
    <div className="space-y-2.5">
      {/* 5 Standard KPI Cards Grid */}
      <section aria-label="Five Key Performance Indicators" className="grid grid-cols-1 gap-2.5 sm:grid-cols-2 lg:grid-cols-5">
        {/* 1. Availability % */}
        <Card className="flex flex-col justify-between px-3 py-2 shadow-xs">
          <div className="flex items-center justify-between text-muted-foreground">
            <span className="text-[11px] font-medium">Availability %</span>
            <Activity className="size-4 text-emerald-600" aria-hidden="true" />
          </div>
          <div className="my-1">
            <div className="text-[18px] leading-6 font-semibold tracking-tight text-foreground">
              {formatPct(kpis.availability_pct, 1)}
            </div>
            <div className="text-[11px] text-muted-foreground">
              Weighted pooled uptime · {scopeLabel}
            </div>
          </div>
          <div className="text-[10px] text-muted-foreground/80">
            Target: ≥ 98.5%
          </div>
        </Card>

        {/* 2. NSLA Sites */}
        <Card className="flex flex-col justify-between px-3 py-2 shadow-xs">
          <div className="flex items-center justify-between text-muted-foreground">
            <span className="text-[11px] font-medium">NSLA Sites</span>
            <ShieldAlert className="size-4 text-amber-600" aria-hidden="true" />
          </div>
          <div className="my-1">
            <div className="text-[18px] leading-6 font-semibold tracking-tight text-foreground">
              {formatNumber(kpis.nsla_sites)}
              <span className="ml-1.5 text-[11px] font-semibold text-muted-foreground">
                ({formatPct(kpis.nsla_pct, 1)})
              </span>
            </div>
            <div className="text-[11px] text-muted-foreground">
              Below 98.5% SLA · of {formatNumber(kpis.assigned_sites)} assigned sites
            </div>
          </div>
          <div className="text-[10px] text-muted-foreground/80">
            Lower is better
          </div>
        </Card>

        {/* 3. Unique Sites Down (USD) */}
        <Card className="flex flex-col justify-between px-3 py-2 shadow-xs">
          <div className="flex items-center justify-between text-muted-foreground">
            <span className="text-[11px] font-medium">Unique Sites Down</span>
            <WifiOff className="size-4 text-rose-600" aria-hidden="true" />
          </div>
          <div className="my-1">
            <div className="text-[18px] leading-6 font-semibold tracking-tight text-foreground">
              {formatNumber(kpis.usd)}
            </div>
            <div className="text-[11px] text-muted-foreground">
              Outage &gt; 0 during {periodLabel}
            </div>
          </div>
          <div className="text-[10px] text-muted-foreground/80">
            Lower is better
          </div>
        </Card>

        {/* 4. Incidents */}
        <Card className="flex flex-col justify-between px-3 py-2 shadow-xs">
          <div className="flex items-center justify-between text-muted-foreground">
            <span className="text-[11px] font-medium">Incidents</span>
            <AlertOctagon className="size-4 text-indigo-600" aria-hidden="true" />
          </div>
          <div className="my-1">
            <div className="text-[18px] leading-6 font-semibold tracking-tight text-foreground">
              {formatNumber(kpis.incidents)}
            </div>
            <div className="text-[11px] text-muted-foreground">
              Total RCA records matching sites in period
            </div>
          </div>
          <div className="text-[10px] text-muted-foreground/80">
            Counted per RCA record
          </div>
        </Card>

        {/* 5. L1 */}
        <Card className="flex flex-col justify-between border-dashed bg-muted/20 px-3 py-2 shadow-xs">
          <div className="flex items-center justify-between text-muted-foreground">
            <span className="text-[11px] font-medium">L1 Technician Visits</span>
            <Wrench className="size-4 text-muted-foreground/60" aria-hidden="true" />
          </div>
          <div className="my-1">
            <div className="text-[18px] leading-6 font-semibold tracking-tight text-muted-foreground">
              N/A
            </div>
            <div className="text-[11px] text-muted-foreground">
              Technician visit source data unavailable
            </div>
          </div>
          <div className="text-[10px] text-muted-foreground/80">
            20% weight preserved (not redistributed)
          </div>
        </Card>
      </section>

      {/* Overall Score Status Banner */}
      <div className="flex flex-wrap items-center justify-between gap-2.5 rounded-lg border bg-card px-3.5 py-2 text-[11px]">
        <div className="flex items-center gap-2">
          <Trophy className="size-3.5 text-muted-foreground/60" aria-hidden="true" />
          <span className="font-semibold text-foreground">Overall Performance Score:</span>
          <span className="rounded bg-muted px-2 py-0.5 font-bold text-muted-foreground">N/A</span>
        </div>
        <p className="text-[10.5px] text-muted-foreground">
          Score is withheld per business rule: composite percentile scoring requires all 5 inputs (Availability 25%, NSLA 30%, USD 20%, Incidents 5%, L1 20%). Unranked until valid L1 data is ingested.
        </p>
      </div>
    </div>
  );
}

