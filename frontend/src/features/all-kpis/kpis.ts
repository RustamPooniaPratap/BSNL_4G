import { count, hours, pct } from './format';
import { availabilityTone, problemTone, type Tone } from './status';
import type { HierarchyLevel, KpiFilterOptions, KpiValues } from './types';

/**
 * The KPI pages of the All KPI's menu (presentation only). Each KPI is one existing field of the API response
 * (apps/allkpis/services.py), shown with its existing definition; no value is calculated here.
 */
export type KpiId = 'availability' | 'outage' | 'usd' | 'nsla' | 'below_98_5' | 'below_60';

export interface KpiDef {
  id: KpiId;
  name: string;
  /** The response field. */
  key: keyof KpiValues;
  format: (v: number | null | undefined) => string;
  /** Whether a higher value is better (ranking and change colours). */
  higherIsBetter: boolean;
  /** Change unit: percentage points for a percentage, otherwise a relative change. */
  unit: 'pts' | '%';
  tone: (v: number | null | undefined) => Tone;
  /** The existing definition (README / services), with the selected population. */
  definition: (sites: string) => string;
  /** Which trend chart of TrendPanel shows it. */
  trend: 'availability' | 'outage';
  /** Default sort of its site list (an existing sort of /sites/). */
  siteSort: string;
  /** Site list limited to these availability buckets (existing bucket filter); null = every site. */
  siteBuckets?: (options: KpiFilterOptions) => string[] | null;
  /** A value that depends on O&M Start data (Not available without it for the O&M Start population). */
  population?: boolean;
  /** Threshold drawn on its bars. */
  target?: number;
}

const counts = { format: count, unit: '%' as const, higherIsBetter: false };

export const KPIS: KpiDef[] = [
  { id: 'availability', name: 'Availability', key: 'availability_pct', format: (v) => pct(v, 3), higherIsBetter: true, unit: 'pts', tone: availabilityTone, trend: 'availability',
    siteSort: 'availability', target: 98.5,
    definition: (sites) => `Outage-weighted availability of ${sites} over the period: 100 × (1 − outage ÷ (1,440 min × reported site-days)); never an average of daily percentages. Missing values are left out, never 0%.` },
  { id: 'outage', name: 'Outage hours', key: 'outage_hours', format: hours, higherIsBetter: false, unit: '%', tone: () => 'neutral', trend: 'outage', siteSort: '-outage',
    definition: (sites) => `Outage of ${sites} over the reported site-days of the period (hours = outage minutes ÷ 60).` },
  { id: 'usd', name: 'USD Sites', key: 'usd_sites', ...counts, tone: (v) => problemTone(v), trend: 'outage', siteSort: '-outage', population: true,
    definition: (sites) => `USD Sites: distinct ${sites} with outage > 0 on at least one reported day of the period. A count of sites, not of outage events.` },
  { id: 'nsla', name: 'NSLA Sites', key: 'nsla_sites', ...counts, tone: (v) => problemTone(v, 'bad'), trend: 'outage', siteSort: 'availability', population: true,
    definition: (sites) => `NSLA Sites: ${sites} whose uptime over the period, pooled over their reported days, is below 98.5%. Exactly 98.5% does not qualify; a site without a value never does.` },
  { id: 'below_98_5', name: 'Sites < 98.5%', key: 'below_98_5_sites', ...counts, tone: (v) => problemTone(v), trend: 'availability', siteSort: 'availability',
    siteBuckets: (o) => o.buckets.map((b) => b.key).filter((k) => k !== 'gte_98_5'),
    definition: (sites) => `${sites} whose own availability over the period is below 98.5% (exactly 98.5% counts as 98.5% and above).` },
  { id: 'below_60', name: 'Sites < 60%', key: 'below_60_sites', ...counts, tone: (v) => problemTone(v, 'bad'), trend: 'availability', siteSort: 'availability',
    siteBuckets: (o) => o.buckets.map((b) => b.key).filter((k) => k === 'lt_60'),
    definition: (sites) => `${sites} whose own availability over the period is below 60% (the "Below 60%" bucket).` },
];
export const KPI_BY_ID = Object.fromEntries(KPIS.map((k) => [k.id, k])) as Record<KpiId, KpiDef>;
export const isKpiId = (v: string): v is KpiId => v in KPI_BY_ID;

/** Level tabs of the unit tables (reference: Circle-wise, CI-wise, NE-wise → IE-wise, Site-wise). */
export const LEVEL_TABS: [HierarchyLevel | 'site', string][] = [['circle', 'Circle-wise'], ['ci', 'CI-wise'], ['ie', 'IE-wise'], ['site', 'Site-wise']];
