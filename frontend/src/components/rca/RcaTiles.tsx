import type { ReactNode } from 'react';
import type { LucideIcon } from 'lucide-react';
import { Card } from '@/components/ui/card';
import { cn } from '@/lib/utils';
import { Definition, IconTile, ViewLink, type Tint } from '../portfolio/PortfolioKpis';

type To = string | { pathname: string; search: string };

/**
 * An RCA headline figure in the dashboard's KPI tile style (Site Portfolio, Overview): title with its definition,
 * tinted icon tile, large value with an optional unit, a context line and a link. Presentation only: the value and
 * the wording come from the RCA Summary response.
 */
export function RcaKpiTile({ label, definition, icon, tint, value, unit, missing, context, link, view }: {
  label: string; definition: string; icon: LucideIcon; tint: Tint; value: string | null; unit?: string; missing?: string;
  context: ReactNode; link?: To; view?: string;
}) {
  return (
    <Card role="group" aria-label={label} className="relative h-full gap-0 rounded-xl px-3 py-2 shadow-xs transition-shadow hover:shadow-sm">
      <div className="flex items-start justify-between gap-2.5">
        <p className="flex min-w-0 items-center gap-1.5 text-[11px] font-medium text-foreground/80">
          <span className="truncate">{label}</span><Definition label={label} text={definition} />
        </p>
        <IconTile size="sm" icon={icon} tint={tint} />
      </div>
      <p className="-mt-1 flex items-baseline gap-1.5">
        <span className={cn('text-[18px] leading-6 font-semibold tracking-tight tabular-nums', value == null && 'text-lg font-medium text-muted-foreground')}>
          {value ?? missing ?? 'Not available'}
        </span>
        {unit && value != null && <span className="text-[13px] text-muted-foreground">{unit}</span>}
      </p>
      <p className="mt-0.5 text-[10.5px] text-muted-foreground">{context}</p>
      {link && <div className="mt-auto pt-2"><ViewLink to={link}>{view ?? 'View details'}</ViewLink></div>}
    </Card>
  );
}

/** One RCA analysis page on the Overview: what it holds, one figure from the same response, and the way in. */
export function RcaAnalysisTile({ label, description, icon, tint, headline, headlineIsMetric = false, detail, to }: {
  label: string; description: string; icon: LucideIcon; tint: Tint; headline: ReactNode; headlineIsMetric?: boolean; detail: ReactNode; to: To;
}) {
  return (
    <Card role="group" aria-label={label} className="relative h-full gap-0 rounded-xl px-3 py-2 shadow-xs transition-shadow hover:shadow-sm">
      <div className="flex items-start justify-between gap-2.5">
        <p className="text-[13px] font-medium text-foreground/80">{label}</p>
        <IconTile icon={icon} tint={tint} />
      </div>
      <p className={cn('-mt-2 truncate font-semibold tracking-tight tabular-nums', headlineIsMetric ? 'text-[18px]' : 'text-[19px]')}>{headline}</p>
      <p className="mt-0.5 text-[11px] text-muted-foreground">{detail}</p>
      <p className="mt-1.5 text-[11px] text-muted-foreground">{description}</p>
      <div className="mt-auto pt-2"><ViewLink to={to}>Open {label}</ViewLink></div>
    </Card>
  );
}

/** A group of tiles under a heading in small spaced capitals, as on Site Portfolio (KpiSection), with its own region name. */
export function RcaSection({ heading, label, columns, children }: { heading: string; label: string; columns: 3 | 4; children: ReactNode }) {
  return (
    <section aria-label={label} className="space-y-2">
      <h2 className="text-xs font-semibold tracking-[0.14em] text-muted-foreground uppercase">{heading}</h2>
      <div className={cn('grid grid-cols-1 gap-2.5', columns === 3 ? 'md:grid-cols-3' : 'md:grid-cols-2 xl:grid-cols-4')}>{children}</div>
    </section>
  );
}
