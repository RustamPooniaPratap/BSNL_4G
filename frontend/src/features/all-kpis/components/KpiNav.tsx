import { useEffect, useRef } from 'react';
import { cn } from '@/lib/utils';
import type { Tone } from '../status';
import type { KpiTab } from '../useKpiFilters';

export interface NavItem { id: KpiTab; label: string; value?: string; tone?: Tone; group: 'reports' | 'kpi' | 'analysis' }

const TONE_CLASS: Record<Tone, string> = { good: 'good', warn: 'warn', bad: 'crit', neutral: '' };
const GROUPS: [NavItem['group'], string][] = [['reports', 'Overview & Reports'], ['kpi', 'Performance KPIs'], ['analysis', 'Analysis']];

/**
 * The All KPI's menu: one horizontal tab bar in three groups (Overview & Reports, Performance KPIs, Analysis) under the
 * filter bar, sticky below it. Each KPI shows
 * its current value as a small badge; the active view is underlined and highlighted. It scrolls sideways (never
 * vertically) when the tabs do not fit, and keeps the active tab in view.
 */
export function KpiNav({ items, active, onOpen }: { items: NavItem[]; active: KpiTab; onOpen: (t: KpiTab) => void }) {
  const bar = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const el = bar.current?.querySelector<HTMLElement>('[aria-current="page"]');
    if (el && typeof el.scrollIntoView === 'function') el.scrollIntoView({ block: 'nearest', inline: 'nearest' });
  }, [active]);
  return (
    <nav aria-label="All KPI's sections" className="akp-topnav">
      <div className="akp-topnav-in" ref={bar}>
        {GROUPS.map(([group, label], g) => (
          <div key={group} className="grp" role="group" aria-label={label}>
            {g > 0 && <span className="divider" aria-hidden="true" />}
            <span className="glabel" aria-hidden="true">{label}</span>
            {items.filter((i) => i.group === group).map((i) => (
              <button key={i.id} type="button" className="akp-ntab" aria-current={i.id === active ? 'page' : undefined} onClick={() => onOpen(i.id)}>
                <span>{i.label}</span>
                {i.value && <span className={cn('kv', TONE_CLASS[i.tone ?? 'neutral'])}>{i.value}</span>}
              </button>
            ))}
          </div>
        ))}
      </div>
    </nav>
  );
}
