import { useMemo, useState } from 'react';
import { Link, useNavigate, useParams, useSearchParams } from 'react-router-dom';
import { ChevronRight, Users, Building, MapPin, UserCheck, Phone } from 'lucide-react';
import { Card } from '@/components/ui/card';
import { Input } from '@/components/ui/input';
import { Skeleton } from '@/components/ui/skeleton';
import { cn } from '@/lib/utils';
import { Field, FilterBar } from '../../components/dashboard/FilterBar';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import { PageHeading } from '../../context/pageHeader';
import { useWorkbook } from '../../context/workbook';
import { useApiQuery } from '../../hooks/useApiQuery';
import { useDashboardFilters, type DashboardFilterState } from '../../hooks/useDashboardFilters';
import { formatNumber, formatPct } from '../../lib/format';
import { fetchFilterOptions } from '../../services/api';
import {
  getCircle,
  getOa,
  getCi,
  getIesForCi,
  getSitesForCi,
  aggregateKpis,
} from '../../services/hierarchyMockData';
import { DemoDataBadge } from '../../components/hierarchy/DemoDataBadge';
import { HierarchyKpiCards } from '../../components/hierarchy/HierarchyKpiCards';
import { HierarchyBreadcrumbs } from '../../components/hierarchy/HierarchyBreadcrumbs';
import { AssignedSitesTable } from '../../components/hierarchy/AssignedSitesTable';

const TH = 'border-b bg-muted/50 px-3 py-2 text-[11px] font-medium whitespace-nowrap text-muted-foreground';
const TD = 'border-b px-3 py-2 align-middle text-xs tabular-nums';

export function CiPerformancePage() {
  const { circleCode, oaId, ciId } = useParams<{ circleCode: string; oaId: string; ciId: string }>();
  const navigate = useNavigate();
  const workbook = useWorkbook();
  const { version } = workbook;
  const options = useApiQuery(workbook.active ? `${version}|filters` : null, fetchFilterOptions);
  const { filters, setFilters, reset, isDefault } = useDashboardFilters(options.data, { defaultScope: 'om_start' });
  const [searchParams, setSearchParams] = useSearchParams();
  const month = searchParams.get('month') ?? '';
  const [searchIe, setSearchIe] = useState('');

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

  const ies = useMemo(() => {
    if (!ciId) return [];
    return getIesForCi(ciId, oaId);
  }, [ciId, oaId]);

  const sites = useMemo(() => {
    if (!ciId) return [];
    return getSitesForCi(ciId, oaId);
  }, [ciId, oaId]);

  const filteredIes = useMemo(() => {
    if (!searchIe.trim()) return ies;
    const term = searchIe.toLowerCase().trim();
    return ies.filter(
      (ie) =>
        ie.ie_name.toLowerCase().includes(term) ||
        (ie.emp_code && ie.emp_code.includes(term))
    );
  }, [ies, searchIe]);

  const ciKpis = useMemo(() => {
    if (ci) return ci;
    return aggregateKpis(ies);
  }, [ci, ies]);

  const months = options.data?.months ?? [];
  const latest = months[months.length - 1]?.key;
  const selectedMonth = month || latest || '2026-10';
  const monthLabel = months.find((m) => m.key === selectedMonth)?.label ?? 'Oct-26 MTD';
  const scopeLabel = options.data?.scopes.find((s) => s.value === filters?.scope)?.label ?? 'O&M Start';
  const circleName = circle?.circle_name ?? circleCode ?? '';
  const oaName = oa?.oa_name ?? oaId ?? '';
  const ciName = ci?.ci_name ?? ciId ?? '';
  const subtitle = `${ciName} · ${oaName} · ${circleName} (${circleCode}) · ${filters?.reportType || 'All Projects'}`;

  if (!options.data || !filters) {
    return <Skeleton className="h-96 w-full" aria-label="Loading CI detail" />;
  }

  const handleIeClick = (ieId: string) => {
    const q = searchParams.toString();
    navigate(`/teams/hierarchy/circle/${encodeURIComponent(circleCode!)}/oa/${encodeURIComponent(oaId!)}/ci/${encodeURIComponent(ciId!)}/ie/${encodeURIComponent(ieId)}${q ? `?${q}` : ''}`);
  };

  const handleFilterChange = (changes: Partial<DashboardFilterState>) => {
    setFilters(changes);
  };

  return (
    <div className="space-y-5">
      {/* Top Heading */}
      <PageHeading title={`${ciName} · Cluster In-Charge Detail`} subtitle={subtitle} />

      {/* Demo data notice */}
      <DemoDataBadge />

      {/* Breadcrumb Trail */}
      <HierarchyBreadcrumbs
        items={[
          { label: 'Team Performance Hierarchy', to: '/teams/hierarchy' },
          { label: `${circleName} (${circleCode})`, to: `/teams/hierarchy/circle/${encodeURIComponent(circleCode!)}` },
          { label: oaName, to: `/teams/hierarchy/circle/${encodeURIComponent(circleCode!)}/oa/${encodeURIComponent(oaId!)}` },
          { label: ciName, current: true },
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
        title={`${ciName} Detail`}
        description="Assigned Integration Engineers and complete site portfolio under this cluster."
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

      {/* =========================================================================
          SECTION A: FIVE KPI CARDS
          ========================================================================= */}
      <div className="space-y-1.5">
        <h3 className="text-xs font-semibold uppercase tracking-wider text-muted-foreground">
          A. Cluster Performance Indicators
        </h3>
        <HierarchyKpiCards kpis={ciKpis} periodLabel={monthLabel} scopeLabel={scopeLabel} />
      </div>

      {/* =========================================================================
          SECTION B: CI INFORMATION
          ========================================================================= */}
      <div className="space-y-1.5">
        <h3 className="text-xs font-semibold uppercase tracking-wider text-muted-foreground">
          B. Cluster In-Charge (CI) Information
        </h3>
        <Card className="rounded-xl border bg-card p-4 shadow-xs">
          <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-6 text-xs">
            <div>
              <span className="text-muted-foreground flex items-center gap-1 font-medium">
                <UserCheck className="size-3.5 text-primary" /> CI Full Name
              </span>
              <div className="mt-1 text-sm font-semibold text-foreground">{ciName}</div>
            </div>

            <div>
              <span className="text-muted-foreground font-medium">Employee Code</span>
              <div className="mt-1 font-mono text-sm font-semibold text-foreground">
                {ci?.emp_code ? ci.emp_code : <span className="text-muted-foreground italic font-normal">—</span>}
              </div>
            </div>

            <div>
              <span className="text-muted-foreground flex items-center gap-1 font-medium">
                <Building className="size-3.5 text-muted-foreground/80" /> Circle
              </span>
              <div className="mt-1 font-semibold text-foreground">
                {circleName} <span className="text-muted-foreground font-normal">({circleCode})</span>
              </div>
            </div>

            <div>
              <span className="text-muted-foreground flex items-center gap-1 font-medium">
                <MapPin className="size-3.5 text-muted-foreground/80" /> OA Context
              </span>
              <div className="mt-1 font-semibold text-foreground">{oaName}</div>
              {ci?.other_oas && ci.other_oas.length > 0 && (
                <div className="text-[10px] text-muted-foreground mt-0.5">
                  Also covers: {ci.other_oas.join(', ')}
                </div>
              )}
            </div>

            <div>
              <span className="text-muted-foreground font-medium">Assigned Sites</span>
              <div className="mt-1 text-sm font-bold text-foreground">
                {formatNumber(ciKpis.assigned_sites)} sites
              </div>
            </div>

            <div>
              <span className="text-muted-foreground flex items-center gap-1 font-medium">
                <Phone className="size-3.5 text-muted-foreground/80" /> Contact Details
              </span>
              <div className="mt-1 font-medium text-foreground">
                {ci?.contact ?? '—'}
              </div>
            </div>
          </div>
        </Card>
      </div>

      {/* =========================================================================
          SECTION C: IE-WISE PERFORMANCE TABLE
          ========================================================================= */}
      <div className="space-y-1.5">
        <h3 className="text-xs font-semibold uppercase tracking-wider text-muted-foreground">
          C. Integration Engineer (IE) Performance
        </h3>
        <Card className="rounded-xl border bg-card shadow-xs">
          <div className="flex flex-col gap-3 border-b p-4 sm:flex-row sm:items-center sm:justify-between">
            <div>
              <div className="flex items-center gap-2">
                <Users className="size-4 text-primary" aria-hidden="true" />
                <h4 className="text-sm font-semibold text-foreground">Integration Engineers under {ciName}</h4>
                <span className="rounded-full bg-muted px-2 py-0.5 text-[11px] font-medium text-muted-foreground">
                  {filteredIes.length} {filteredIes.length === 1 ? 'IE' : 'IEs'}
                </span>
              </div>
              <p className="mt-0.5 text-xs text-muted-foreground">
                Ranked by Overall Performance Score. Select any IE to open their individual performance breakdown.
              </p>
            </div>

            <div className="w-48 sm:w-64">
              <Input
                type="search"
                placeholder="Search IE name or code..."
                value={searchIe}
                onChange={(e) => setSearchIe(e.target.value)}
                className="h-8 text-xs"
                aria-label="Search Integration Engineers"
              />
            </div>
          </div>

          <div className="overflow-x-auto">
            <table className="w-full min-w-[56rem] border-separate border-spacing-0">
              <thead>
                <tr>
                  <th scope="col" className={cn(TH, 'w-12 text-center')}>Rank</th>
                  <th scope="col" className={cn(TH, 'sticky left-0 z-10 w-48 text-left')}>Integration Engineer (IE)</th>
                  <th scope="col" className={cn(TH, 'text-center')}>Emp Code</th>
                  <th scope="col" className={cn(TH, 'text-right')}>Assigned Sites</th>
                  <th scope="col" className={cn(TH, 'text-right')}>Availability %</th>
                  <th scope="col" className={cn(TH, 'text-right')}>NSLA Sites</th>
                  <th scope="col" className={cn(TH, 'text-right')}>NSLA %</th>
                  <th scope="col" className={cn(TH, 'text-right')}>USD</th>
                  <th scope="col" className={cn(TH, 'text-right')}>Incidents</th>
                  <th scope="col" className={cn(TH, 'text-center')}>L1</th>
                  <th scope="col" className={cn(TH, 'text-center')}>Overall Score</th>
                </tr>
              </thead>
              <tbody>
                {filteredIes.length === 0 ? (
                  <tr>
                    <td colSpan={11} className="p-8 text-center text-xs text-muted-foreground">
                      No Integration Engineers found assigned under this cluster.
                    </td>
                  </tr>
                ) : (
                  filteredIes.map((ie) => {
                    const q = searchParams.toString();
                    const targetUrl = `/teams/hierarchy/circle/${encodeURIComponent(circleCode!)}/oa/${encodeURIComponent(oaId!)}/ci/${encodeURIComponent(ciId!)}/ie/${encodeURIComponent(ie.ie_id)}${q ? `?${q}` : ''}`;
                    return (
                      <tr
                        key={ie.ie_id}
                        onClick={() => handleIeClick(ie.ie_id)}
                        className="group cursor-pointer hover:bg-muted/50 transition-colors"
                        tabIndex={0}
                        aria-label={`Open IE ${ie.ie_name}`}
                        onKeyDown={(e) => {
                          if (e.key === 'Enter' || e.key === ' ') {
                            e.preventDefault();
                            handleIeClick(ie.ie_id);
                          }
                        }}
                      >
                        <td className={cn(TD, 'text-center font-medium text-muted-foreground')}>
                          {ie.rank ?? '—'}
                        </td>
                        <th scope="row" className={cn(TD, 'sticky left-0 z-10 bg-card group-hover:bg-muted/50 transition-colors text-left')}>
                          <div className="flex items-center justify-between gap-1.5">
                            <Link
                              to={targetUrl}
                              onClick={(e) => e.stopPropagation()}
                              className="font-semibold text-foreground hover:text-primary hover:underline"
                            >
                              {ie.ie_name}
                            </Link>
                            <ChevronRight className="size-3.5 text-muted-foreground opacity-0 transition-opacity group-hover:opacity-100" aria-hidden="true" />
                          </div>
                          {ie.other_cis && ie.other_cis.length > 0 && (
                            <div className="text-[10px] text-muted-foreground mt-0.5">
                              Also reports to: {ie.other_cis.join(', ')}
                            </div>
                          )}
                        </th>
                        <td className={cn(TD, 'text-center font-mono')}>
                          {ie.emp_code ? (
                            <span className="text-foreground">{ie.emp_code}</span>
                          ) : (
                            <span className="text-muted-foreground italic">—</span>
                          )}
                        </td>
                        <td className={cn(TD, 'text-right font-medium text-foreground')}>
                          {formatNumber(ie.assigned_sites)}
                        </td>
                        <td className={cn(TD, 'text-right font-medium text-foreground')}>
                          {formatPct(ie.availability_pct, 1)}
                        </td>
                        <td className={cn(TD, 'text-right text-foreground')}>
                          {formatNumber(ie.nsla_sites)}
                        </td>
                        <td className={cn(TD, 'text-right font-medium')}>
                          <span className={cn('rounded px-1.5 py-0.5', ie.nsla_pct > 2 ? 'bg-amber-50 text-amber-800' : 'bg-emerald-50 text-emerald-800')}>
                            {formatPct(ie.nsla_pct, 1)}
                          </span>
                        </td>
                        <td className={cn(TD, 'text-right text-foreground')}>
                          {formatNumber(ie.usd)}
                        </td>
                        <td className={cn(TD, 'text-right text-foreground')}>
                          {formatNumber(ie.incidents)}
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
                    );
                  })
                )}
              </tbody>
            </table>
          </div>
        </Card>
      </div>

      {/* =========================================================================
          SECTION D: COMPLETE CI ASSIGNED SITES TABLE
          ========================================================================= */}
      <div className="space-y-1.5">
        <h3 className="text-xs font-semibold uppercase tracking-wider text-muted-foreground">
          D. Complete Cluster Assigned Sites Inventory
        </h3>
        <AssignedSitesTable
          sites={sites}
          title={`All Physical Sites assigned to ${ciName}`}
          subtitle={`Complete inventory of ${sites.length} sites in ${oaName}. An IE is shown according to their specific site-level assignment.`}
        />
      </div>
    </div>
  );
}
