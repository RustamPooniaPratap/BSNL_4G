import { useMemo } from 'react';
import { useParams, useSearchParams } from 'react-router-dom';
import { UserCheck, MapPin, Phone, Users, History } from 'lucide-react';
import { Card } from '@/components/ui/card';
import { Skeleton } from '@/components/ui/skeleton';
import { cn } from '@/lib/utils';
import { Field, FilterBar } from '../../components/dashboard/FilterBar';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import { PageHeading } from '../../context/pageHeader';
import { useFilterOptions } from '../../hooks/useFilterOptions';
import { usePopulation } from '../../context/population';
import { useDashboardFilters, type DashboardFilterState } from '../../hooks/useDashboardFilters';
import { formatNumber, formatPct } from '../../lib/format';
import {
  getCircle,
  getOa,
  getCi,
  getIe,
  getSitesForIe,
  MOCK_HISTORICAL_MONTHS,
} from '../../services/hierarchyMockData';
import { DemoDataBadge } from '../../components/hierarchy/DemoDataBadge';
import { HierarchyKpiCards } from '../../components/hierarchy/HierarchyKpiCards';
import { HierarchyBreadcrumbs } from '../../components/hierarchy/HierarchyBreadcrumbs';
import { AssignedSitesTable } from '../../components/hierarchy/AssignedSitesTable';

const TH = 'border-b bg-muted/50 px-3 py-2 text-[11px] font-medium whitespace-nowrap text-muted-foreground';
const TD = 'border-b px-3 py-2 align-middle text-xs tabular-nums';

export function IePerformancePage() {
  const { circleCode, oaId, ciId, ieId } = useParams<{
    circleCode: string;
    oaId: string;
    ciId: string;
    ieId: string;
  }>();

  const options = useFilterOptions();
  const { sitesLabel } = usePopulation();
  const { filters, setFilters, reset, isDefault } = useDashboardFilters(options.data);
  const [searchParams, setSearchParams] = useSearchParams();
  const month = searchParams.get('month') ?? '';

  const setParam = (key: string, value: string | null) => setSearchParams((current) => {
    const next = new URLSearchParams(current);
    if (value) next.set(key, value);
    else next.delete(key);
    return next;
  }, { replace: true });

  const circle = useMemo(() => {
    if (!circleCode) return undefined;
    return getCircle(circleCode);
  }, [circleCode]);

  const oa = useMemo(() => {
    if (!oaId) return undefined;
    return getOa(oaId);
  }, [oaId]);

  const ci = useMemo(() => {
    if (!ciId) return undefined;
    return getCi(ciId, oaId);
  }, [ciId, oaId]);

  const ie = useMemo(() => {
    if (!ieId) return undefined;
    return getIe(ieId, ciId);
  }, [ieId, ciId]);

  const sites = useMemo(() => {
    if (!ieId) return [];
    return getSitesForIe(ieId, ciId);
  }, [ieId, ciId]);

  const months = options.data?.months ?? [];
  const latest = months[months.length - 1]?.key;
  const selectedMonth = month || latest || '2026-10';
  const monthLabel = months.find((m) => m.key === selectedMonth)?.label ?? 'Oct-26 MTD';
  const scopeLabel = sitesLabel;
  const circleName = circle?.circle_name ?? circleCode ?? '';
  const oaName = oa?.oa_name ?? oaId ?? '';
  const ciName = ci?.ci_name ?? ciId ?? '';
  const ieName = ie?.ie_name ?? ieId ?? '';
  const subtitle = `${ieName} · ${ciName} · ${oaName} · ${circleName} (${circleCode}) · ${filters?.reportType || 'All Projects'} · Population: ${scopeLabel}`;

  if (!options.data || !filters || !ie) {
    return <Skeleton className="h-96 w-full" aria-label="Loading IE detail" />;
  }

  const handleFilterChange = (changes: Partial<DashboardFilterState>) => {
    setFilters(changes);
  };

  return (
    <div className="space-y-4">
      {/* Top Heading */}
      <PageHeading title={`${ieName} · Integration Engineer Detail`} subtitle={subtitle} />

      {/* Demo data notice */}
      <DemoDataBadge />

      {/* Breadcrumb Trail */}
      <HierarchyBreadcrumbs
        items={[
          { label: 'Team Performance Hierarchy', to: '/teams/hierarchy' },
          { label: `${circleName} (${circleCode})`, to: `/teams/hierarchy/circle/${encodeURIComponent(circleCode!)}` },
          { label: oaName, to: `/teams/hierarchy/circle/${encodeURIComponent(circleCode!)}/oa/${encodeURIComponent(oaId!)}` },
          { label: ciName, to: `/teams/hierarchy/circle/${encodeURIComponent(circleCode!)}/oa/${encodeURIComponent(oaId!)}/ci/${encodeURIComponent(ciId!)}` },
          { label: ieName, current: true },
        ]}
      />

      {/* Global Filter Bar */}
      <FilterBar
        options={options.data}
        filters={{ ...filters, circle: circleCode || filters.circle }}
        onChange={handleFilterChange}
        canReset={!isDefault || !!month}
        onReset={reset}
        showTrendRange={false}
        showDate={false}
        title={`${ieName} Detail`}
        description="Individual performance cards, historical trend matrix, and assigned site inventory."
        extra={(
          <Field id="filter-month" label="Reporting month" className="w-48">
            <Select value={selectedMonth} onValueChange={(v) => setParam('month', v === latest ? null : v)} disabled={!months.length}>
              <SelectTrigger id="filter-month" className="h-9 w-full"><SelectValue placeholder="No months" /></SelectTrigger>
              <SelectContent>
                {[...months].reverse().map((m) => (
                  <SelectItem key={m.key} value={m.key}>{m.label}{m.key === latest ? ' (latest)' : ''}</SelectItem>
                ))}
              </SelectContent>
            </Select>
          </Field>
        )}
      />

      {/* 5 KPI Cards */}
      <HierarchyKpiCards kpis={ie} periodLabel={monthLabel} scopeLabel={scopeLabel} />

      {/* IE Information Card */}
      <Card className="rounded-xl border bg-card p-3 shadow-xs">
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-6 text-xs">
          <div>
            <span className="text-muted-foreground flex items-center gap-1 font-medium">
              <UserCheck className="size-3.5 text-primary" /> IE Full Name
            </span>
            <div className="mt-1 text-sm font-semibold text-foreground">{ieName}</div>
          </div>

          <div>
            <span className="text-muted-foreground font-medium">Employee Code</span>
            <div className="mt-1 font-mono text-sm font-semibold text-foreground">
              {ie.emp_code ? ie.emp_code : <span className="text-muted-foreground italic font-normal">—</span>}
            </div>
          </div>

          <div>
            <span className="text-muted-foreground flex items-center gap-1 font-medium">
              <Users className="size-3.5 text-muted-foreground/80" /> Reporting CI
            </span>
            <div className="mt-1 font-semibold text-foreground">{ciName}</div>
            {ie.other_cis && ie.other_cis.length > 0 && (
              <div className="text-[10px] text-muted-foreground mt-0.5">
                Also reports to: {ie.other_cis.join(', ')}
              </div>
            )}
          </div>

          <div>
            <span className="text-muted-foreground flex items-center gap-1 font-medium">
              <MapPin className="size-3.5 text-muted-foreground/80" /> Operational Area
            </span>
            <div className="mt-1 font-semibold text-foreground">{oaName}</div>
            <div className="text-[10px] text-muted-foreground mt-0.5">Circle: {circleName}</div>
          </div>

          <div>
            <span className="text-muted-foreground font-medium">Assigned Sites</span>
            <div className="mt-1 text-sm font-bold text-foreground">
              {formatNumber(ie.assigned_sites)} sites
            </div>
          </div>

          <div>
            <span className="text-muted-foreground flex items-center gap-1 font-medium">
              <Phone className="size-3.5 text-muted-foreground/80" /> Contact
            </span>
            <div className="mt-1 font-medium text-foreground">{ie.contact ?? '—'}</div>
          </div>
        </div>
      </Card>

      {/* Historical Monthly Performance Table (Last 5 Months + Current MTD) */}
      <Card className="rounded-xl border bg-card shadow-xs">
        <div className="flex flex-col gap-1 border-b p-3">
          <div className="flex items-center gap-2">
            <History className="size-4 text-primary" aria-hidden="true" />
            <h3 className="text-sm font-semibold text-foreground">Historical Monthly Performance</h3>
            <span className="rounded-full bg-muted px-2 py-0.5 text-[11px] font-medium text-muted-foreground">
              Last 5 Months + Current MTD
            </span>
          </div>
          <p className="text-xs text-muted-foreground">
            Complete monthly KPI groups for {ieName}. Availability, NSLA, USD, Incidents, L1, and Overall Score per period.
          </p>
        </div>

        <div className="overflow-x-auto">
          <table className="w-full min-w-[56rem] border-separate border-spacing-0">
            <thead>
              <tr>
                <th scope="col" className={cn(TH, 'sticky left-0 z-10 w-28 text-left')}>Reporting Month</th>
                <th scope="col" className={cn(TH, 'text-right')}>Availability %</th>
                <th scope="col" className={cn(TH, 'text-right')}>NSLA Sites</th>
                <th scope="col" className={cn(TH, 'text-right')}>NSLA %</th>
                <th scope="col" className={cn(TH, 'text-right')}>USD</th>
                <th scope="col" className={cn(TH, 'text-right')}>Incidents</th>
                <th scope="col" className={cn(TH, 'text-center')}>L1 Visits</th>
                <th scope="col" className={cn(TH, 'text-center')}>Overall Score</th>
              </tr>
            </thead>
            <tbody>
              {MOCK_HISTORICAL_MONTHS.map((m) => (
                <tr key={m.month_key} className={cn('hover:bg-muted/40 transition-colors', m.kind === 'mtd' && 'bg-primary/5 font-medium')}>
                  <th scope="row" className={cn(TD, 'sticky left-0 z-10 bg-card font-semibold text-left', m.kind === 'mtd' && 'text-primary')}>
                    {m.month_label}
                    {m.kind === 'mtd' && (
                      <span className="ml-1.5 rounded bg-primary/10 px-1.5 py-0.2 text-[10px] font-semibold text-primary">
                        Latest
                      </span>
                    )}
                  </th>
                  <td className={cn(TD, 'text-right font-medium text-foreground')}>
                    {formatPct(m.availability_pct, 2)}
                  </td>
                  <td className={cn(TD, 'text-right text-foreground')}>
                    {formatNumber(m.nsla_sites)}
                  </td>
                  <td className={cn(TD, 'text-right font-medium')}>
                    <span className={cn('rounded px-1.5 py-0.5', m.nsla_pct > 2 ? 'bg-amber-50 text-amber-800' : 'bg-emerald-50 text-emerald-800')}>
                      {formatPct(m.nsla_pct, 1)}
                    </span>
                  </td>
                  <td className={cn(TD, 'text-right text-foreground')}>
                    {formatNumber(m.usd)}
                  </td>
                  <td className={cn(TD, 'text-right text-foreground')}>
                    {formatNumber(m.incidents)}
                  </td>
                  <td className={cn(TD, 'text-center font-medium text-muted-foreground')}>
                    N/A
                  </td>
                  <td className={cn(TD, 'text-center')}>
                    <span className="rounded bg-muted px-2 py-0.5 font-bold text-muted-foreground">
                      N/A
                    </span>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Card>

      {/* Complete Assigned Sites Table */}
      <AssignedSitesTable
        sites={sites}
        title={`Assigned Physical Sites for ${ieName}`}
        subtitle={`All sites assigned to ${ieName} under ${ciName} in ${oaName}.`}
      />
    </div>
  );
}
