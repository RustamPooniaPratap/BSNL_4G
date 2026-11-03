import { Info, TriangleAlert } from 'lucide-react';
import { Alert, AlertDescription } from '@/components/ui/alert';
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
import type { KpiSummary } from './types';
import { useKpiFilters, type KpiTab } from './useKpiFilters';

const TAB_LABELS: Record<KpiTab, string> = {
  overview: 'Overview', availability: 'Availability & Uptime', outage: 'Outage & SLA', rca: 'RCA', drilldown: 'Circle → CI → IE → Site', completeness: 'Data Completeness',
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

  return (
    <div className="space-y-4">
      <PageHeading title="All KPI's" subtitle="Consolidated 4G Saturation & LWE KPIs: portfolio, availability, outage, SLA thresholds, RCA and reporting completeness, with Circle → CI → IE → Site drill-down." />
      {options.error && <Alert variant="destructive"><AlertDescription>{options.error.message}</AlertDescription></Alert>}
      {options.data ? <KpiFilters f={f} options={options.data} showFinalBucket={tab === 'rca'} /> : !options.error && <Skeleton className="h-16 w-full" />}
      {s && <PeriodLine s={s} />}
      <nav aria-label="All KPI's sections" className="flex flex-wrap gap-1 rounded-xl border bg-card p-1 shadow-xs">
        {tabs.map((t) => (
          <button key={t} type="button" aria-current={t === tab ? 'page' : undefined} onClick={() => open(t)}
            className={cn('rounded-lg px-3 py-1.5 text-sm font-medium transition-colors', t === tab ? 'bg-primary text-primary-foreground' : 'text-muted-foreground hover:bg-muted hover:text-foreground')}>
            {TAB_LABELS[t]}
          </button>
        ))}
      </nav>
      {summary.error && <Alert variant="destructive" role="alert"><AlertDescription>{summary.error.message}</AlertDescription></Alert>}
      {!s && !summary.error && <Skeleton className="h-64 w-full" aria-label="Loading KPIs" />}
      {s && !s.current && <Alert><AlertDescription>{s.notes?.join(' ') ?? 'No data for these filters.'}</AlertDescription></Alert>}
      {s?.current && (
        <>
          {tab === 'overview' && <Overview s={s} query={query} onOpen={open} canRca={canRca} />}
          {tab === 'availability' && (
            <>
              <KpiGroup title="Availability & Uptime" period={s.period!.label} onOpen={open} cards={availabilityCards(s)} />
              <TrendPanel query={query} kind="availability" />
              <ComparisonTable s={s} keys={['availability_pct', 'coverage_pct', 'missing_site_days']} />
            </>
          )}
          {tab === 'outage' && (
            <>
              <KpiGroup title="Outage & SLA" period={s.period!.label} cards={[...outageCards(s), ...slaCards(s)]} />
              <TrendPanel query={query} kind="outage" />
              <ComparisonTable s={s} keys={['outage_hours', 'usd_sites', 'nsla_sites', 'above_98_5_sites', 'below_98_5_sites', 'below_60_sites']} />
            </>
          )}
          {tab === 'rca' && canRca && <RcaPanel query={f.query} />}
          {tab === 'drilldown' && <DrillDown f={f} />}
          {tab === 'completeness' && (
            <>
              <KpiGroup title="Reporting / Data Completeness" period={s.period!.label} cards={completenessCards(s)} />
              <p className="flex items-start gap-1.5 text-xs text-muted-foreground">
                <Info className="mt-px size-3.5 shrink-0" aria-hidden="true" />
                A site-day without a value is missing reporting, not low availability: it is left out of availability, outage, USD and NSLA (never counted as 0%).
              </p>
              <SitesTable key={`c-${query}`} query={query} defaultSort="days" title="Sites by reporting completeness (fewest days first)" />
            </>
          )}
        </>
      )}
    </div>
  );
}

function PeriodLine({ s }: { s: KpiSummary }) {
  if (!s.period) return null;
  const om = s.om_start;
  return (
    <div className="space-y-2">
      <p className="text-xs text-muted-foreground">
        Reporting period <span className="font-medium text-foreground">{s.period.label}</span> · {s.period.days_with_data} of {s.period.days_in_period} days with daily data
        {s.previous_period && ` · compared with ${s.previous_period.label}`}
      </p>
      {om && !om.complete && (
        <p role="status" className="flex items-start gap-1.5 rounded-md border border-amber-200 bg-amber-50 px-3 py-2 text-xs text-amber-900">
          <TriangleAlert className="mt-px size-3.5 shrink-0" aria-hidden="true" />
          {om.available
            ? `O&M Start data is not available for ${om.missing_months.join(', ')}: those days are left out of USD and NSLA (no other month's O&M Start is carried forward).`
            : `O&M Start data is not available for ${om.missing_months.join(', ')}: O&M Start sites, USD and NSLA show "Not available". No other month's O&M Start is carried forward.`}
        </p>
      )}
    </div>
  );
}

const portfolioCards = (s: KpiSummary): KpiCardSpec[] => [
  { label: 'Total sites', value: count(s.current!.total_sites), current: s.current!.total_sites, previous: s.previous?.total_sites, higherIsBetter: null, tab: 'drilldown' },
  { label: 'On-Air sites', value: count(s.current!.on_air_sites), current: s.current!.on_air_sites, previous: s.previous?.on_air_sites, higherIsBetter: null, tab: 'drilldown' },
  { label: 'O&M Start sites', value: count(s.current!.om_start_sites), current: s.current!.om_start_sites, previous: s.previous?.om_start_sites, higherIsBetter: null, tab: 'drilldown' },
  { label: 'Site Handover Status', value: 'Pending clarification', muted: true, note: 'Not defined yet' },
];
const availabilityCards = (s: KpiSummary): KpiCardSpec[] => [
  { label: 'Availability (selected period)', value: pct(s.current!.availability_pct, 3), current: s.current!.availability_pct, previous: s.previous?.availability_pct, unit: 'pts', higherIsBetter: true, tab: 'availability',
    note: `${s.period!.label} · outage-weighted, On-Air sites` },
];
const outageCards = (s: KpiSummary): KpiCardSpec[] => [
  { label: 'Outage minutes', value: count(s.current!.outage_minutes == null ? null : Math.round(s.current!.outage_minutes)), current: s.current!.outage_minutes, previous: s.previous?.outage_minutes, higherIsBetter: false, tab: 'outage' },
  { label: 'Outage hours', value: hours(s.current!.outage_hours), current: s.current!.outage_hours, previous: s.previous?.outage_hours, higherIsBetter: false, tab: 'outage' },
  { label: 'USD sites', value: count(s.current!.usd_sites), current: s.current!.usd_sites, previous: s.previous?.usd_sites, higherIsBetter: false, tab: 'outage',
    note: 'O&M Start sites with outage > 0 on a day' },
];
const slaCards = (s: KpiSummary): KpiCardSpec[] => [
  { label: 'NSLA sites (< 98.5%)', value: count(s.current!.nsla_sites), current: s.current!.nsla_sites, previous: s.previous?.nsla_sites, higherIsBetter: false, tab: 'outage',
    note: 'O&M Start sites below 98.5% on at least one day' },
  { label: 'Sites ≥ 98.5% (period)', value: count(s.current!.above_98_5_sites), current: s.current!.above_98_5_sites, previous: s.previous?.above_98_5_sites, higherIsBetter: true, tab: 'drilldown' },
  { label: 'Sites < 98.5% (period)', value: count(s.current!.below_98_5_sites), current: s.current!.below_98_5_sites, previous: s.previous?.below_98_5_sites, higherIsBetter: false, tab: 'drilldown' },
  { label: 'Sites < 60% (period)', value: count(s.current!.below_60_sites), current: s.current!.below_60_sites, previous: s.previous?.below_60_sites, higherIsBetter: false, tab: 'drilldown' },
];
const completenessCards = (s: KpiSummary): KpiCardSpec[] => [
  { label: 'Reporting coverage', value: pct(s.current!.coverage_pct, 1), current: s.current!.coverage_pct, previous: s.previous?.coverage_pct, unit: 'pts', higherIsBetter: true, tab: 'completeness',
    note: `${count(s.current!.reported_site_days)} of ${count(s.current!.expected_site_days)} site-days` },
  { label: 'Missing availability (site-days)', value: count(s.current!.missing_site_days), current: s.current!.missing_site_days, previous: s.previous?.missing_site_days, higherIsBetter: false, tab: 'completeness' },
  { label: 'Sites missing a day', value: count(s.current!.sites_missing_any_day), current: s.current!.sites_missing_any_day, previous: s.previous?.sites_missing_any_day, higherIsBetter: false, tab: 'completeness' },
  { label: 'Sites without any value', value: count(s.current!.sites_without_any_value), current: s.current!.sites_without_any_value, previous: s.previous?.sites_without_any_value, higherIsBetter: false, tab: 'completeness' },
];

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
  const period = s.period!.label;
  return (
    <div className="space-y-5">
      <KpiGroup title="Site Portfolio" period={period} onOpen={onOpen} cards={portfolioCards(s)} />
      <KpiGroup title="Availability & Uptime" period={period} onOpen={onOpen} cards={[
        ...availabilityCards(s),
        { label: 'Daily availability', value: day ? pct(day.availability_pct, 3) : NA, note: day ? `Latest day: ${day.label}` : undefined, tab: 'availability' },
        { label: 'Weekly availability', value: week ? pct(week.availability_pct, 3) : NA, note: week ? `Latest week: ${week.label}` : undefined, tab: 'availability' },
        { label: 'Monthly availability', value: month ? pct(month.availability_pct, 3) : NA, note: month ? `Latest month: ${month.label}` : undefined, tab: 'availability' },
      ]} />
      <KpiGroup title="Outage Performance" period={period} onOpen={onOpen} cards={outageCards(s)} />
      <KpiGroup title="SLA / Threshold Analysis" period={period} onOpen={onOpen} cards={slaCards(s)} />
      <KpiGroup title="Reporting / Data Completeness" period={period} onOpen={onOpen} cards={completenessCards(s)} />
      {canRca && (
        <p className="text-xs text-muted-foreground">
          RCA Performance and Final Buckets: see the <button type="button" className="text-primary underline" onClick={() => onOpen('rca')}>RCA</button> tab
          (Own / Customer / Third Party / Pending are not configured yet).
        </p>
      )}
    </div>
  );
}
