import {
  Activity, Building2, CalendarDays, ClipboardCheck, Clock, Gauge, Info, LayoutGrid, ListTree, Network, RadioTower, ShieldAlert, ShieldCheck, Timer,
  TriangleAlert, Wrench, type LucideIcon,
} from 'lucide-react';
import { Alert, AlertDescription } from '@/components/ui/alert';
import { Button } from '@/components/ui/button';
import { Card } from '@/components/ui/card';
import { Skeleton } from '@/components/ui/skeleton';
import { cn } from '@/lib/utils';
import { hasPermission, useAuth } from '../../context/auth';
import { PageHeading } from '../../context/pageHeader';
import { useApiQuery } from '../../hooks/useApiQuery';
import { fetchKpiFilters, fetchKpiSummary, fetchKpiTrends } from './api';
import { ComparisonTable } from './components/ComparisonTable';
import { DrillDown, SitesTable } from './components/DrillDown';
import { KpiFilters } from './components/KpiFilters';
import { KpiGroup, type KpiCardSpec } from './components/KpiCards';
import { RcaPanel } from './components/RcaPanel';
import { TrendPanel } from './components/TrendPanel';
import { count, hours, NA, pct } from './format';
import { availabilityTone, coverageTone, problemTone } from './status';
import type { KpiSummary } from './types';
import { useKpiFilters, type KpiTab } from './useKpiFilters';

const TAB_LABELS: Record<KpiTab, string> = {
  overview: 'Overview', availability: 'Availability', outage: 'Outage & SLA', rca: 'RCA', drilldown: 'Circle / CI / IE / Site', completeness: 'Data Completeness',
};
const TAB_ICONS: Record<KpiTab, LucideIcon> = {
  overview: LayoutGrid, availability: Activity, outage: Timer, rca: ListTree, drilldown: Network, completeness: ClipboardCheck,
};

/**
 * All KPI's: an optional, self-contained module (src/features/all-kpis, backend apps/allkpis; see README.md). Every
 * figure comes from /api/all-kpis/, computed on the server from the canonical daily records and the Site Master.
 */
export function AllKpisPage() {
  const f = useKpiFilters();
  const { user } = useAuth();
  const canRca = hasPermission(user, 'rca_summary.view');
  const options = useApiQuery(`allkpis-filters-${f.query}`, (signal) => fetchKpiFilters(f.query, signal));
  const summary = useApiQuery(`allkpis-summary-${f.query}`, (signal) => fetchKpiSummary(f.query, signal));
  const s = summary.data;
  const tabs = (Object.keys(TAB_LABELS) as KpiTab[]).filter((t) => t !== 'rca' || canRca);
  const tab = tabs.includes(f.tab) ? f.tab : 'overview';
  const open = (t: KpiTab) => f.update({ tab: t === 'overview' ? null : t });
  // The RCA filter only applies to RCA data; other tabs ignore it.
  const query = new URLSearchParams(f.query);
  if (tab !== 'rca') query.delete('final_bucket');
  const period = s?.period?.label ?? '';
  const compareLabel = s?.previous_period?.label;

  return (
    <div className="space-y-4">
      <PageHeading title="All KPI's" subtitle="Consolidated 4G & LWE Performance Overview" />
      {options.error && <Alert variant="destructive"><TriangleAlert /><AlertDescription>{options.error.message}</AlertDescription></Alert>}
      {options.data
        ? <KpiFilters f={f} options={options.data} summary={s} showFinalBucket={tab === 'rca'} />
        : !options.error && <Skeleton className="h-36 w-full rounded-xl" />}
      {s && <OmNotice s={s} />}
      <nav aria-label="All KPI's sections" className="overflow-x-auto border-b">
        <div className="flex min-w-max gap-1">
          {tabs.map((t) => {
            const Icon = TAB_ICONS[t];
            return (
              <button key={t} type="button" aria-current={t === tab ? 'page' : undefined} onClick={() => open(t)}
                className={cn('-mb-px inline-flex h-10 items-center gap-1.5 border-b-2 px-3 text-sm font-medium whitespace-nowrap transition-colors',
                  t === tab ? 'border-primary text-foreground' : 'border-transparent text-muted-foreground hover:border-border hover:text-foreground')}>
                <Icon className="size-4" aria-hidden="true" />{TAB_LABELS[t]}
              </button>
            );
          })}
        </div>
      </nav>
      {summary.error && <Alert variant="destructive" role="alert"><TriangleAlert /><AlertDescription>{summary.error.message}</AlertDescription></Alert>}
      {!s && !summary.error && (
        <div aria-label="Loading KPIs" aria-busy="true" className="grid grid-cols-1 gap-3 sm:grid-cols-2 xl:grid-cols-4">
          {Array.from({ length: 8 }, (_, i) => <Skeleton key={i} className="h-28 rounded-xl" />)}
        </div>
      )}
      {s && !s.current && <Alert><Info /><AlertDescription>{s.notes?.join(' ') ?? 'No data for these filters.'}</AlertDescription></Alert>}
      {s?.current && (
        <div className="space-y-5">
          {tab === 'overview' && <Overview s={s} query={query} onOpen={open} canRca={canRca} />}
          {tab === 'availability' && (
            <>
              <KpiGroup title="Availability & Uptime" icon={Activity} period={period} compareLabel={compareLabel} onOpen={open} cards={availabilityCards(s)} />
              <TrendPanel query={query} kind="availability" period={period} />
              <ComparisonTable s={s} keys={['availability_pct', 'coverage_pct', 'missing_site_days']} />
            </>
          )}
          {tab === 'outage' && (
            <>
              <KpiGroup title="Outage Performance" icon={Timer} period={period} compareLabel={compareLabel} cards={outageCards(s)} />
              <KpiGroup title="SLA / Threshold Analysis" icon={ShieldCheck} period={period} compareLabel={compareLabel} cards={slaCards(s)} />
              <TrendPanel query={query} kind="outage" period={period} />
              <ComparisonTable s={s} keys={['outage_hours', 'usd_sites', 'nsla_sites', 'above_98_5_sites', 'below_98_5_sites', 'below_60_sites']} />
            </>
          )}
          {tab === 'rca' && canRca && <RcaPanel query={f.query} />}
          {tab === 'drilldown' && <DrillDown f={f} />}
          {tab === 'completeness' && (
            <>
              <KpiGroup title="Reporting / Data Completeness" icon={ClipboardCheck} period={period} compareLabel={compareLabel} cards={completenessCards(s)} />
              <CoverageBar s={s} />
              <SitesTable key={`c-${query}`} query={query} defaultSort="days" title="Sites by reporting completeness (fewest days first)" />
            </>
          )}
        </div>
      )}
    </div>
  );
}

/** O&M Start is read per month (no carry-forward): a month without it makes O&M Start sites, USD and NSLA unavailable. */
function OmNotice({ s }: { s: KpiSummary }) {
  const om = s.om_start;
  if (!s.period || !om || om.complete) return null;
  return (
    <p role="status" className="flex items-start gap-2 rounded-lg border border-amber-200 bg-amber-50/70 px-3 py-2 text-xs text-amber-900">
      <TriangleAlert className="mt-px size-3.5 shrink-0 text-amber-600" aria-hidden="true" />
      {om.available
        ? `O&M Start data is not available for ${om.missing_months.join(', ')}: those days are left out of USD and NSLA (no other month's O&M Start is carried forward).`
        : `O&M Start data is not available for ${om.missing_months.join(', ')}: O&M Start sites, USD and NSLA show "Not available". No other month's O&M Start is carried forward.`}
    </p>
  );
}

/** Why an O&M Start-based value is unavailable (shown on its card instead of a misleading 0). */
const omReason = (s: KpiSummary, v: number | null | undefined) =>
  v == null ? `No O&M Start data for ${s.om_start?.missing_months.join(', ') || 'this period'}` : undefined;

const portfolioCards = (s: KpiSummary): KpiCardSpec[] => [
  { label: 'Total sites', icon: Building2, value: count(s.current!.total_sites), current: s.current!.total_sites, previous: s.previous?.total_sites, higherIsBetter: null, tab: 'drilldown', note: 'In the Site Master, selected scope' },
  { label: 'On-Air sites', icon: RadioTower, value: count(s.current!.on_air_sites), current: s.current!.on_air_sites, previous: s.previous?.on_air_sites, higherIsBetter: null, tab: 'drilldown', note: 'Basis of availability and thresholds' },
  { label: 'O&M Start sites', icon: Wrench, value: count(s.current!.om_start_sites), current: s.current!.om_start_sites, previous: s.previous?.om_start_sites, higherIsBetter: null, tab: 'drilldown',
    note: omReason(s, s.current!.om_start_sites) ?? 'Latest month in the period; basis of USD and NSLA' },
  { label: 'Site Handover Status', value: 'Pending clarification', muted: true, note: 'Definition not confirmed yet' },
];
const availabilityCards = (s: KpiSummary): KpiCardSpec[] => [
  { label: 'Availability (selected period)', icon: Gauge, value: pct(s.current!.availability_pct, 3), current: s.current!.availability_pct, previous: s.previous?.availability_pct, unit: 'pts',
    higherIsBetter: true, tone: availabilityTone(s.current!.availability_pct), tab: 'availability',
    note: s.current!.availability_pct == null ? 'No reported values in this period' : 'Outage-weighted, On-Air sites' },
];
const outageCards = (s: KpiSummary): KpiCardSpec[] => [
  { label: 'Outage minutes', icon: Clock, value: count(s.current!.outage_minutes == null ? null : Math.round(s.current!.outage_minutes)), current: s.current!.outage_minutes, previous: s.previous?.outage_minutes, higherIsBetter: false, tab: 'outage' },
  { label: 'Outage hours', icon: Timer, value: hours(s.current!.outage_hours), current: s.current!.outage_hours, previous: s.previous?.outage_hours, higherIsBetter: false, tab: 'outage' },
  { label: 'USD sites', icon: TriangleAlert, value: count(s.current!.usd_sites), current: s.current!.usd_sites, previous: s.previous?.usd_sites, higherIsBetter: false, tone: problemTone(s.current!.usd_sites), tab: 'outage',
    note: omReason(s, s.current!.usd_sites) ?? 'O&M Start sites with outage > 0 on a day' },
];
const slaCards = (s: KpiSummary): KpiCardSpec[] => [
  { label: 'NSLA sites (< 98.5%)', icon: ShieldAlert, value: count(s.current!.nsla_sites), current: s.current!.nsla_sites, previous: s.previous?.nsla_sites, higherIsBetter: false, tone: problemTone(s.current!.nsla_sites, 'bad'), tab: 'outage',
    note: omReason(s, s.current!.nsla_sites) ?? 'O&M Start sites below 98.5% on at least one day' },
  { label: 'Sites ≥ 98.5% (period)', icon: ShieldCheck, value: count(s.current!.above_98_5_sites), current: s.current!.above_98_5_sites, previous: s.previous?.above_98_5_sites, higherIsBetter: true,
    tone: s.current!.above_98_5_sites ? 'good' : 'neutral', tab: 'drilldown' },
  { label: 'Sites < 98.5% (period)', value: count(s.current!.below_98_5_sites), current: s.current!.below_98_5_sites, previous: s.previous?.below_98_5_sites, higherIsBetter: false, tone: problemTone(s.current!.below_98_5_sites), tab: 'drilldown' },
  { label: 'Sites < 60% (period)', value: count(s.current!.below_60_sites), current: s.current!.below_60_sites, previous: s.previous?.below_60_sites, higherIsBetter: false, tone: problemTone(s.current!.below_60_sites, 'bad'), tab: 'drilldown' },
];
const completenessCards = (s: KpiSummary): KpiCardSpec[] => [
  { label: 'Reporting coverage', icon: ClipboardCheck, value: pct(s.current!.coverage_pct, 1), current: s.current!.coverage_pct, previous: s.previous?.coverage_pct, unit: 'pts', higherIsBetter: true,
    tone: coverageTone(s.current!.coverage_pct), tab: 'completeness', note: `${count(s.current!.reported_site_days)} of ${count(s.current!.expected_site_days)} site-days` },
  { label: 'Missing availability (site-days)', value: count(s.current!.missing_site_days), current: s.current!.missing_site_days, previous: s.previous?.missing_site_days, higherIsBetter: false, tone: problemTone(s.current!.missing_site_days), tab: 'completeness',
    note: 'Not reported; not counted as 0%' },
  { label: 'Sites missing a day', value: count(s.current!.sites_missing_any_day), current: s.current!.sites_missing_any_day, previous: s.previous?.sites_missing_any_day, higherIsBetter: false, tone: problemTone(s.current!.sites_missing_any_day), tab: 'completeness' },
  { label: 'Sites without any value', value: count(s.current!.sites_without_any_value), current: s.current!.sites_without_any_value, previous: s.previous?.sites_without_any_value, higherIsBetter: false, tone: problemTone(s.current!.sites_without_any_value), tab: 'completeness' },
];

/** Reported against missing site-days: missing values are a reporting gap, never low availability. */
function CoverageBar({ s }: { s: KpiSummary }) {
  const v = s.current!;
  if (!v.expected_site_days) return null;
  const reported = (100 * v.reported_site_days) / v.expected_site_days;
  const missing = (100 * v.missing_site_days) / v.expected_site_days;
  return (
    <Card className="gap-2.5 px-4 py-3 shadow-xs">
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <h3 className="text-sm font-semibold">Reporting coverage</h3>
        <p className="text-xs text-muted-foreground tabular-nums">{count(v.reported_site_days)} of {count(v.expected_site_days)} On-Air site-days reported · {period(s)}</p>
      </div>
      <div className="flex h-2.5 overflow-hidden rounded-full bg-muted" role="img" aria-label={`${pct(v.coverage_pct, 1)} of site-days reported`}>
        <div className="bg-emerald-600" style={{ width: `${reported}%` }} />
        <div className="bg-amber-400" style={{ width: `${missing}%` }} />
      </div>
      <div className="flex flex-wrap gap-x-5 gap-y-1 text-[11px] text-muted-foreground">
        <span className="inline-flex items-center gap-1.5"><span className="size-2 rounded-full bg-emerald-600" aria-hidden="true" />Reported: {count(v.reported_site_days)} site-days, included in every KPI</span>
        <span className="inline-flex items-center gap-1.5"><span className="size-2 rounded-full bg-amber-400" aria-hidden="true" />Missing: {count(v.missing_site_days)} site-days, left out of availability, outage, USD and NSLA</span>
      </div>
      <p className="flex items-start gap-1.5 rounded-md bg-muted/50 px-2.5 py-1.5 text-[11px] text-muted-foreground">
        <Info className="mt-px size-3.5 shrink-0" aria-hidden="true" />
        Missing availability is a reporting gap, not low availability: a site-day without a value is never counted as 0%.
        Low availability is shown on the Availability and Outage &amp; SLA tabs.
      </p>
    </Card>
  );
}
const period = (s: KpiSummary) => s.period?.label ?? '';

/** Daily / weekly / monthly availability: the latest point of each trend (all derived from daily records). */
function useLatest(query: URLSearchParams, granularity: 'day' | 'week' | 'month') {
  const params = new URLSearchParams(query);
  params.set('granularity', granularity);
  const t = useApiQuery(`allkpis-trend-${params}`, (signal) => fetchKpiTrends(params, signal));
  return t.data?.points.at(-1) ?? null;
}

function Overview({ s, query, onOpen, canRca }: { s: KpiSummary; query: URLSearchParams; onOpen: (t: KpiTab) => void; canRca: boolean }) {
  const day = useLatest(query, 'day');
  const week = useLatest(query, 'week');
  const month = useLatest(query, 'month');
  const p = period(s);
  const compareLabel = s.previous_period?.label;
  return (
    <div className="space-y-6">
      <KpiGroup title="Site Portfolio" icon={Building2} period={p} compareLabel={compareLabel} onOpen={onOpen} cards={portfolioCards(s)} />
      <KpiGroup title="Availability & Uptime" icon={Activity} period={p} compareLabel={compareLabel} onOpen={onOpen} cards={[
        ...availabilityCards(s),
        { label: 'Daily availability', icon: CalendarDays, value: day ? pct(day.availability_pct, 3) : NA, tone: availabilityTone(day?.availability_pct), note: day ? `Latest day: ${day.label}` : undefined, tab: 'availability' },
        { label: 'Weekly availability', icon: CalendarDays, value: week ? pct(week.availability_pct, 3) : NA, tone: availabilityTone(week?.availability_pct), note: week ? `Latest week: ${week.label}` : undefined, tab: 'availability' },
        { label: 'Monthly availability', icon: CalendarDays, value: month ? pct(month.availability_pct, 3) : NA, tone: availabilityTone(month?.availability_pct), note: month ? `Latest month: ${month.label}` : undefined, tab: 'availability' },
      ]} />
      <KpiGroup title="Outage Performance" icon={Timer} period={p} compareLabel={compareLabel} onOpen={onOpen} cards={outageCards(s)} />
      <KpiGroup title="SLA / Threshold Analysis" icon={ShieldCheck} period={p} compareLabel={compareLabel} onOpen={onOpen} cards={slaCards(s)} />
      <KpiGroup title="Reporting / Data Completeness" icon={ClipboardCheck} period={p} compareLabel={compareLabel} onOpen={onOpen} cards={completenessCards(s)} />
      {canRca && (
        <Card className="flex-row flex-wrap items-center gap-3 px-4 py-3 shadow-xs">
          <ListTree className="size-4 text-muted-foreground" aria-hidden="true" />
          <div className="min-w-0 flex-1">
            <p className="text-sm font-semibold">RCA Performance</p>
            <p className="text-xs text-muted-foreground">Final Bucket distribution and circle-wise RCA. Own / Customer / Third Party / Pending are not configured yet.</p>
          </div>
          <Button size="sm" variant="outline" className="h-8" onClick={() => onOpen('rca')}>Open RCA</Button>
        </Card>
      )}
    </div>
  );
}
