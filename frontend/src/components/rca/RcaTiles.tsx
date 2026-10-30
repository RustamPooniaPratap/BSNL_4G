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
    <Card role="group" aria-label={label} className="relative h-full gap-0 rounded-xl px-4 py-3 shadow-xs transition-shadow hover:shadow-md">
      <div className="flex items-start justify-between gap-3">
        <p className="flex min-w-0 items-center gap-1.5 text-sm font-medium text-foreground/80">
          <span className="truncate">{label}</span><Definition label={label} text={definition} />
        </p>
        <IconTile icon={icon} tint={tint} />
      </div>
      <p className="-mt-2 flex items-baseline gap-1.5">
        <span className={cn('text-2xl font-semibold tracking-tight tabular-nums', value == null && 'text-lg font-medium text-muted-foreground')}>
          {value ?? missing ?? 'Not available'}
        </span>
        {unit && value != null && <span className="text-sm text-muted-foreground">{unit}</span>}
      </p>
      <p className="mt-0.5 text-[11px] text-muted-foreground">{context}</p>
      {link && <div className="mt-auto pt-2"><ViewLink to={link}>{view ?? 'View details'}</ViewLink></div>}
    </Card>
  );
}

/** One RCA analysis page on the Overview: what it holds, one figure from the same response, and the way in. */
export function RcaAnalysisTile({ label, description, icon, tint, headline, detail, to }: {
  label: string; description: string; icon: LucideIcon; tint: Tint; headline: ReactNode; detail: ReactNode; to: To;
}) {
  return (
    <Card role="group" aria-label={label} className="relative h-full gap-0 rounded-xl px-4 py-3 shadow-xs transition-shadow hover:shadow-md">
      <div className="flex items-start justify-between gap-3">
        <p className="text-sm font-medium text-foreground/80">{label}</p>
        <IconTile icon={icon} tint={tint} />
      </div>
      <p className="-mt-2 truncate text-xl font-semibold tracking-tight tabular-nums">{headline}</p>
      <p className="mt-0.5 text-[11px] text-muted-foreground">{detail}</p>
      <p className="mt-1.5 text-xs text-muted-foreground">{description}</p>
      <div className="mt-auto pt-2"><ViewLink to={to}>Open {label}</ViewLink></div>
    </Card>
  );
}

/** A group of tiles under a heading in small spaced capitals, as on Site Portfolio (KpiSection), with its own region name. */
export function RcaSection({ heading, label, columns, children }: { heading: string; label: string; columns: 3 | 4; children: ReactNode }) {
  return (
    <section aria-label={label} className="space-y-2">
      <h2 className="text-xs font-semibold tracking-[0.14em] text-muted-foreground uppercase">{heading}</h2>
      <div className={cn('grid grid-cols-1 gap-3', columns === 3 ? 'md:grid-cols-3' : 'md:grid-cols-2 xl:grid-cols-4')}>{children}</div>
    </section>
  );
}
