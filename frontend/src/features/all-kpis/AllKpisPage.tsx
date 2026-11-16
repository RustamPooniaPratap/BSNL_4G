import { ArrowRight, Info, TriangleAlert } from 'lucide-react';
import { hasPermission, useAuth } from '../../context/auth';
import { PageHeading } from '../../context/pageHeader';
import { usePopulation } from '../../context/population';
import { useApiQuery } from '../../hooks/useApiQuery';
import { fetchKpiFilters, fetchKpiSummary, fetchKpiTrends } from './api';
import './allkpis.css';
import { ComparisonTable } from './components/ComparisonTable';
import { DrillDown } from './components/DrillDown';
import { KpiFilters } from './components/KpiFilters';
import { KpiCard, type KpiCardSpec } from './components/KpiCards';
import { KpiView, LevelCard } from './components/KpiView';
import { RcaPanel } from './components/RcaPanel';
import { TrendPanel } from './components/TrendPanel';
import { TrendsView } from './components/TrendsView';
import { ChangeText, StatStrip } from './components/Ui';
import { count, minutes, NA, pct } from './format';
import { isKpiId, KPI_BY_ID } from './kpis';
import { availabilityTone, problemTone } from './status';
import type { KpiSummary } from './types';
import { TABS, useKpiFilters, type KpiTab } from './useKpiFilters';

const VIEW_TITLES: Record<KpiTab, string> = {
  overview: 'All KPIs – overview', trends: 'KPI trends', availability: 'Availability', outage: 'Outage minutes', usd: 'USD Sites', nsla: 'NSLA Sites',
  below_98_5: 'Sites < 98.5%', below_60: 'Sites < 60%', ranking: 'Ranking', rca: 'Root cause analysis', drilldown: 'Circle / CI / IE / Site',
};
/**
 * All KPI's: an optional, self-contained module (src/features/all-kpis, backend apps/allkpis; see README.md), laid out
 * as the reference report (sticky filters and KPI views without heading cards). Every figure comes from
 * /api/all-kpis/, computed on the server from the canonical daily records and the Site Master.
 */
export function AllKpisPage() {
  const f = useKpiFilters();
  const { sitesLabel } = usePopulation();
  const om = f.scope === 'om_start';
  const { user } = useAuth();
  const canRca = hasPermission(user, 'rca_summary.view');
  const options = useApiQuery(`allkpis-filters-${f.query}`, (signal) => fetchKpiFilters(f.query, signal));
  const summary = useApiQuery(`allkpis-summary-${f.query}`, (signal) => fetchKpiSummary(f.query, signal));
  const s = summary.data;
  const tabs = TABS.filter((t) => t !== 'rca' || canRca);
  const tab = tabs.includes(f.tab) ? f.tab : 'overview';
  const open = (t: KpiTab) => f.update({ tab: t === 'overview' ? null : t });
  // The RCA filter only applies to RCA data; other views ignore it.
  const query = new URLSearchParams(f.query);
  if (tab !== 'rca') query.delete('final_bucket');
  const kpi = isKpiId(tab) ? KPI_BY_ID[tab] : null;

  return (
    <div className="akp">
      <PageHeading title="All KPI's" subtitle={`Consolidated 4G & LWE Performance Overview · Population: ${sitesLabel}`} />
      <div className="akp-fbar">
        {options.data
          ? <KpiFilters f={f} options={options.data} showFinalBucket={tab === 'rca'} />
          : options.error
            ? <p role="alert" className="akp-fbar-in t-crit"><TriangleAlert className="size-4" aria-hidden="true" />{options.error.message}</p>
            : <div className="akp-fbar-in"><div className="akp-skel h-[58px] w-full" /></div>}
      </div>

      <div className="akp-layout">
        <main className="akp-main" aria-label={VIEW_TITLES[tab]}>
          {/* No heading card on any view (the filters show the period, population and scope); only the data checks remain. */}
          {s && <DataChecks s={s} om={om} />}
          {summary.error && <div role="alert" className="akp-card akp-pad t-crit flex items-center gap-2"><TriangleAlert className="size-4" aria-hidden="true" />{summary.error.message}</div>}
          {!s && !summary.error && (
            <div aria-label="Loading KPIs" aria-busy="true" className="akp-tiles">
              {Array.from({ length: 8 }, (_, i) => <div key={i} className="akp-skel h-24" />)}
            </div>
          )}
          {s && !s.current && <div className="akp-card akp-pad akp-note flex items-start gap-2"><Info className="mt-px size-4 shrink-0" aria-hidden="true" />{s.notes?.join(' ') ?? 'No data for these filters.'}</div>}
          {s?.current && (
            <>
              {tab === 'overview' && <Overview s={s} f={f} query={query} onOpen={open} canRca={canRca} sites={sitesLabel} om={om} />}
              {tab === 'trends' && (<><TrendsView query={query} /><ComparisonTable s={s} /></>)}
              {kpi && options.data && (
                <KpiView kpi={kpi} s={s} f={f} query={query} options={options.data} sites={sitesLabel}
                  reason={kpi.population ? populationReason(s, s.current[kpi.key] as number | null, om) : undefined} />
              )}
              {tab === 'ranking' && <Ranking s={s} f={f} query={query} />}
              {tab === 'rca' && canRca && <RcaPanel query={f.query} />}
              {tab === 'drilldown' && <DrillDown f={f} />}
            </>
          )}
        </main>
      </div>
    </div>
  );
}

/** The data checks of every view: nothing at all when there is nothing to report. */
function DataChecks({ s, om }: { s: KpiSummary; om: boolean }) {
  const checks = dataChecks(s, om);
  if (!checks.length) return null;
  return <div className="akp-warnbox" role="status"><b>Data checks: </b>{checks.join(' ')}</div>;
}

/**
 * Data checks. O&M Start is read per month (no carry-forward): with the O&M
 * Start population selected, a month without it leaves USD Sites and NSLA Sites out or Not available.
 */
function dataChecks(s: KpiSummary, omPopulation: boolean): string[] {
  const out: string[] = [];
  const om = s.om_start;
  if (s.period && om && !om.complete && omPopulation) {
    const months = om.missing_months.join(', ');
    out.push(om.available
        ? `O&M Start data is not available for ${months}: those days are left out of USD Sites and NSLA Sites (no other month's O&M Start is carried forward).`
        : `O&M Start data is not available for ${months}: O&M Start sites, USD Sites and NSLA Sites show "Not available". No other month's O&M Start is carried forward.`);
  }
  if (s.current && s.notes?.length) out.push(...s.notes);
  return out;
}

/** Why an O&M Start-based value is unavailable (shown on its tile instead of a misleading 0). */
const omReason = (s: KpiSummary, v: number | null | undefined) =>
  v == null ? `No O&M Start data for ${s.om_start?.missing_months.join(', ') || 'this period'}` : undefined;
/** Why a population value (USD Sites, NSLA Sites) is unavailable: missing O&M Start data matters only for the O&M Start population. */
const populationReason = (s: KpiSummary, v: number | null | undefined, om: boolean) =>
  v == null ? (om ? omReason(s, v) : 'Not available for this period') : undefined;

/** Previous value in the value's own format (tile "Prev …"). */
const prevOf = (s: KpiSummary, key: keyof NonNullable<KpiSummary['previous']>, fmt: (v: number | null) => string) =>
  (s.previous ? fmt((s.previous[key] as number | null) ?? null) : undefined);

const availabilityCards = (s: KpiSummary, sites: string): KpiCardSpec[] => [
  { label: 'Availability (selected period)', value: pct(s.current!.availability_pct), current: s.current!.availability_pct, previous: s.previous?.availability_pct, unit: 'pts', availability: true,
    higherIsBetter: true, tone: availabilityTone(s.current!.availability_pct), tab: 'availability',
    note: s.current!.availability_pct == null ? 'No reported values in this period' : `${s.period?.label ?? 'Selected period'} · outage-weighted, ${sites}` },
];
const outageCards = (s: KpiSummary, sites: string, om: boolean): KpiCardSpec[] => [
  { label: 'Outage minutes', value: minutes(s.current!.outage_minutes), current: s.current!.outage_minutes, previous: s.previous?.outage_minutes,
    prev: prevOf(s, 'outage_minutes', minutes), higherIsBetter: false, tab: 'outage' },
  { label: 'USD Sites', value: count(s.current!.usd_sites), current: s.current!.usd_sites, previous: s.previous?.usd_sites, prev: prevOf(s, 'usd_sites', count), higherIsBetter: false, tone: problemTone(s.current!.usd_sites), tab: 'usd',
    note: populationReason(s, s.current!.usd_sites, om) ?? `${sites} with outage > 0 on a day (sites, not outage events)` },
];
const slaCards = (s: KpiSummary, sites: string, om: boolean): KpiCardSpec[] => [
  { label: 'NSLA Sites (< 98.5%)', value: count(s.current!.nsla_sites), current: s.current!.nsla_sites, previous: s.previous?.nsla_sites, prev: prevOf(s, 'nsla_sites', count), higherIsBetter: false, tone: problemTone(s.current!.nsla_sites, 'bad'), tab: 'nsla',
    note: populationReason(s, s.current!.nsla_sites, om) ?? `${sites} with uptime over ${s.period?.label ?? 'the period'} below 98.5%` },
  { label: 'Sites ≥ 98.5% (period)', value: count(s.current!.above_98_5_sites), current: s.current!.above_98_5_sites, previous: s.previous?.above_98_5_sites, prev: prevOf(s, 'above_98_5_sites', count), higherIsBetter: true,
    tone: s.current!.above_98_5_sites ? 'good' : 'neutral', tab: 'below_98_5' },
  { label: 'Sites < 60% (period)', value: count(s.current!.below_60_sites), current: s.current!.below_60_sites, previous: s.previous?.below_60_sites, prev: prevOf(s, 'below_60_sites', count), higherIsBetter: false, tone: problemTone(s.current!.below_60_sites, 'bad'), tab: 'below_60' },
];
/**
 * Daily / weekly / monthly availability: the latest point of each trend (all derived from daily records). Days and weeks
 * stay within the selected period; months are whole calendar months (the trend API lists every month with data), so
 * Monthly availability is the latest month, not the selected period. Sites < 98.5% is not a tile: it is the same count
 * as NSLA Sites, site for site.
 */
function useLatest(query: URLSearchParams, granularity: 'day' | 'week' | 'month') {
  const params = new URLSearchParams(query);
  params.set('granularity', granularity);
  const t = useApiQuery(`allkpis-trend-${params}`, (signal) => fetchKpiTrends(params, signal));
  return t.data?.points.at(-1) ?? null;
}

function Overview({ s, f, query, onOpen, canRca, sites, om }: {
  s: KpiSummary; f: ReturnType<typeof useKpiFilters>; query: URLSearchParams; onOpen: (t: KpiTab) => void; canRca: boolean; sites: string; om: boolean;
}) {
  const day = useLatest(query, 'day');
  const week = useLatest(query, 'week');
  const month = useLatest(query, 'month');
  const p = s.period?.label ?? '';
  const compareLabel = s.previous_period?.label;
  const latestCard = (label: string, point: typeof day, note: string): KpiCardSpec => ({
    label, value: point ? pct(point.availability_pct) : NA, tone: availabilityTone(point?.availability_pct), availability: Boolean(point), note: point ? note : undefined, tab: 'availability',
  });
  return (
    <>
      {/* Every overview KPI in one grid (reference tile grid): five per row on desktop, equal width and height. */}
      <section aria-label="Key indicators">
        <div className="akp-tiles akp-tiles5">
          {[...availabilityCards(s, sites), latestCard('Daily availability', day, `Latest day of the selected period: ${day?.label}`),
            latestCard('Weekly availability', week, `Latest week of the selected period: ${week?.label}`),
            latestCard('Monthly availability', month, `Latest month with data: ${month?.label}, a calendar month (not limited to the selected period)`),
            ...outageCards(s, sites, om), ...slaCards(s, sites, om)].map((c) => <KpiCard key={c.label} spec={c} onOpen={onOpen} />)}
        </div>
      </section>
      <LevelCard f={f} query={query} s={s} kpi={null} title={(level) => `Ranking · ${level}`}
        note={`${p}${compareLabel ? ` vs ${compareLabel}` : ''} · ranked by availability; select a name to open its next level`} />
      <TrendPanel query={query} kind="availability" period={p} />
      {canRca && (
        <section className="akp-card akp-pad flex flex-wrap items-center gap-3" aria-label="RCA Performance">
          <div className="min-w-0 flex-1">
            <h3 className="akp-h" style={{ marginBottom: 2 }}>RCA Performance</h3>
            <p className="akp-note">Final Bucket distribution and circle-wise RCA. Own / Customer / Third Party / Pending are not configured yet.</p>
          </div>
          <button type="button" className="akp-btn" onClick={() => onOpen('rca')}>Open RCA <ArrowRight className="size-3.5" aria-hidden="true" /></button>
        </section>
      )}
    </>
  );
}

/** Ranking (reference "Ranking & score"): availability of the period against the previous, then the ranked units. */
function Ranking({ s, f, query }: { s: KpiSummary; f: ReturnType<typeof useKpiFilters>; query: URLSearchParams }) {
  const [a, b] = [s.current?.availability_pct ?? null, s.previous?.availability_pct ?? null];
  return (
    <>
      <StatStrip label="Availability: this period against the previous" items={[
        { label: 'Availability', value: pct(a), sub: s.period?.label },
        { label: 'Previous period', value: s.previous ? pct(b) : NA, sub: s.previous_period?.label ?? 'No comparison period' },
        { label: 'Change', value: <ChangeText current={a} previous={b} unit="pts" higherIsBetter />, sub: 'percentage points' },
        { label: 'NSLA Sites', value: count(s.current?.nsla_sites), sub: 'period uptime < 98.5%' },
        { label: 'Sites < 60%', value: count(s.current?.below_60_sites), sub: 'this period' },
      ]} />
      <LevelCard f={f} query={query} s={s} kpi={null} title={(level) => `Ranking · ${level}`}
        note={`${s.period?.label ?? ''}${s.previous_period ? ` vs ${s.previous_period.label}` : ''} · rank 1 = highest availability · Δ = rank change`} />
    </>
  );
}

