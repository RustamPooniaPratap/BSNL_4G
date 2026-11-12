import { useMemo, useState } from 'react';
import { Link, useNavigate, useParams, useSearchParams } from 'react-router-dom';
import { ChevronRight, MapPin, UserX, AlertTriangle } from 'lucide-react';
import { Card } from '@/components/ui/card';
import { Input } from '@/components/ui/input';
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
  getOasForCircle,
  aggregateKpis,
} from '../../services/hierarchyMockData';
import { DemoDataBadge } from '../../components/hierarchy/DemoDataBadge';
import { HierarchyKpiCards } from '../../components/hierarchy/HierarchyKpiCards';
import { HierarchyBreadcrumbs } from '../../components/hierarchy/HierarchyBreadcrumbs';

const TH = 'border-b bg-muted/50 px-3 py-2 text-[11px] font-medium whitespace-nowrap text-muted-foreground';
const TD = 'border-b px-3 py-2 align-middle text-xs tabular-nums';

export function CirclePerformancePage() {
  const { circleCode } = useParams<{ circleCode: string }>();
  const navigate = useNavigate();
  const options = useFilterOptions();
  const { sitesLabel } = usePopulation();
  const { filters, setFilters, reset, isDefault } = useDashboardFilters(options.data);
  const [searchParams, setSearchParams] = useSearchParams();
  const month = searchParams.get('month') ?? '';
  const [search, setSearch] = useState('');

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

  const oas = useMemo(() => {
    if (!circleCode) return [];
    return getOasForCircle(circleCode);
  }, [circleCode]);

  const filteredOas = useMemo(() => {
    if (!search.trim()) return oas;
    const term = search.toLowerCase().trim();
    return oas.filter((oa) => oa.oa_name.toLowerCase().includes(term));
  }, [oas, search]);

  const circleKpis = useMemo(() => {
    if (circle) return circle;
    return aggregateKpis(oas);
  }, [circle, oas]);

  const months = options.data?.months ?? [];
  const latest = months[months.length - 1]?.key;
  const selectedMonth = month || latest || '2026-10';
  const monthLabel = months.find((m) => m.key === selectedMonth)?.label ?? 'Oct-26 MTD';
  const scopeLabel = sitesLabel;
  const circleName = circle?.circle_name ?? circleCode ?? '';
  const subtitle = `${circleName} (${circleCode}) · ${filters?.reportType || 'All Projects'} · Population: ${scopeLabel}`;

  if (!options.data || !filters) {
    return <Skeleton className="h-96 w-full" aria-label="Loading circle performance" />;
  }

  const handleOaClick = (oaId: string) => {
    const q = searchParams.toString();
    navigate(`/teams/hierarchy/circle/${encodeURIComponent(circleCode!)}/oa/${encodeURIComponent(oaId)}${q ? `?${q}` : ''}`);
  };

  const handleFilterChange = (changes: Partial<DashboardFilterState>) => {
    // If circle filter changed from dropdown, navigate to that circle
    if (changes.circle && changes.circle.toUpperCase() !== circleCode?.toUpperCase()) {
      const nextParams = new URLSearchParams(searchParams);
      nextParams.set('circle', changes.circle);
      navigate(`/teams/hierarchy/circle/${encodeURIComponent(changes.circle)}?${nextParams.toString()}`);
      return;
    }
    setFilters(changes);
  };

  return (
    <div className="space-y-4">
      {/* Top Heading */}
      <PageHeading title={`${circleName} Performance`} subtitle={subtitle} />

      {/* Demo data notice */}
      <DemoDataBadge />

      {/* Breadcrumb Trail */}
      <HierarchyBreadcrumbs
        items={[
          { label: 'Team Performance Hierarchy', to: '/teams/hierarchy' },
          { label: `${circleName} (${circleCode})`, current: true },
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
        title={`${circleName} Circle Performance`}
        description="Operational Area breakdown and cluster assignments across the circle."
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

      {/* Circle Info Banner */}
      <div className="flex flex-wrap items-center justify-between gap-4 rounded-xl border bg-card p-4 shadow-xs">
        <div>
          <span className="text-xs font-medium text-muted-foreground">O&M Manager</span>
          <div className="mt-0.5 flex items-center gap-2">
            {circle?.is_vacant ? (
              <span className="inline-flex items-center gap-1 rounded bg-amber-50 px-2 py-0.5 text-xs font-semibold text-amber-800 border border-amber-200">
                <UserX className="size-3.5" aria-hidden="true" />
                [VACANT POST]
              </span>
            ) : (
              <span className="text-base font-semibold text-foreground">
                {circle?.om_manager}
                {circle?.emp_code && (
                  <span className="ml-2 text-xs font-normal text-muted-foreground">
                    (Emp Code: {circle.emp_code} · {circle.contact})
                  </span>
                )}
              </span>
            )}
          </div>
        </div>

        <div className="flex items-center gap-6 text-xs">
          <div>
            <span className="text-muted-foreground">Total Circle Sites:</span>{' '}
            <span className="font-semibold text-foreground">{formatNumber(circleKpis.assigned_sites)}</span>
          </div>
          <div>
            <span className="text-muted-foreground">Operational Areas:</span>{' '}
            <span className="font-semibold text-foreground">{oas.length}</span>
          </div>
          <div>
            <span className="text-muted-foreground">Effective Period:</span>{' '}
            <span className="font-semibold text-foreground">{monthLabel}</span>
          </div>
        </div>
      </div>

      {/* 5 KPI Cards */}
      <HierarchyKpiCards kpis={circleKpis} periodLabel={monthLabel} scopeLabel={scopeLabel} />

      {/* OA-wise Performance Table Card */}
      <Card className="rounded-xl border bg-card shadow-xs">
        <div className="flex flex-col gap-3 border-b p-4 sm:flex-row sm:items-center sm:justify-between">
          <div>
            <div className="flex items-center gap-2">
              <MapPin className="size-4 text-primary" aria-hidden="true" />
              <h2 className="text-sm font-semibold text-foreground">Operational Area (OA) Performance</h2>
              <span className="rounded-full bg-muted px-2 py-0.5 text-[11px] font-medium text-muted-foreground">
                {filteredOas.length} {filteredOas.length === 1 ? 'OA' : 'OAs'}
              </span>
            </div>
            <p className="mt-0.5 text-xs text-muted-foreground">
              Select any Operational Area to view its assigned Cluster In-Charges (CIs)
            </p>
          </div>

          <div className="w-48 sm:w-64">
            <Input
              type="search"
              placeholder="Search OA name..."
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              className="h-8 text-xs"
              aria-label="Search operational areas"
            />
          </div>
        </div>

        <div className="overflow-x-auto">
          <table className="w-full min-w-[56rem] border-separate border-spacing-0">
            <thead>
              <tr>
                <th scope="col" className={cn(TH, 'w-12 text-center')}>Rank</th>
                <th scope="col" className={cn(TH, 'sticky left-0 z-10 w-48 text-left')}>Operational Area (OA)</th>
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
              {filteredOas.length === 0 ? (
                <tr>
                  <td colSpan={10} className="p-8 text-center text-xs text-muted-foreground">
                    No operational areas found for this circle.
                  </td>
                </tr>
              ) : (
                filteredOas.map((oa) => {
                  const q = searchParams.toString();
                  const targetUrl = `/teams/hierarchy/circle/${encodeURIComponent(circleCode!)}/oa/${encodeURIComponent(oa.oa_id)}${q ? `?${q}` : ''}`;
                  return (
                    <tr
                      key={oa.oa_id}
                      onClick={() => handleOaClick(oa.oa_id)}
                      className="group cursor-pointer hover:bg-muted/50 transition-colors"
                      tabIndex={0}
                      aria-label={`Open OA ${oa.oa_name}`}
                      onKeyDown={(e) => {
                        if (e.key === 'Enter' || e.key === ' ') {
                          e.preventDefault();
                          handleOaClick(oa.oa_id);
                        }
                      }}
                    >
                      <td className={cn(TD, 'text-center font-medium text-muted-foreground')}>
                        {oa.rank ?? '—'}
                      </td>
                      <th scope="row" className={cn(TD, 'sticky left-0 z-10 bg-card group-hover:bg-muted/50 transition-colors text-left')}>
                        <div className="flex items-center justify-between gap-1.5">
                          <Link
                            to={targetUrl}
                            onClick={(e) => e.stopPropagation()}
                            className="font-semibold text-foreground hover:text-primary hover:underline flex items-center gap-1.5"
                          >
                            {oa.oa_name}
                            {oa.is_unassigned && (
                              <span className="rounded bg-amber-50 px-1.5 py-0.5 text-[10px] font-semibold text-amber-800 border border-amber-200 inline-flex items-center gap-1">
                                <AlertTriangle className="size-2.5" />
                                Unassigned OA
                              </span>
                            )}
                          </Link>
                          <ChevronRight className="size-3.5 text-muted-foreground opacity-0 transition-opacity group-hover:opacity-100" aria-hidden="true" />
                        </div>
                      </th>
                      <td className={cn(TD, 'text-right font-medium text-foreground')}>
                        {formatNumber(oa.assigned_sites)}
                      </td>
                      <td className={cn(TD, 'text-right font-medium text-foreground')}>
                        {formatPct(oa.availability_pct, 1)}
                      </td>
                      <td className={cn(TD, 'text-right text-foreground')}>
                        {formatNumber(oa.nsla_sites)}
                      </td>
                      <td className={cn(TD, 'text-right font-medium')}>
                        <span className={cn('rounded px-1.5 py-0.5', oa.nsla_pct > 2 ? 'bg-amber-50 text-amber-800' : 'bg-emerald-50 text-emerald-800')}>
                          {formatPct(oa.nsla_pct, 1)}
                        </span>
                      </td>
                      <td className={cn(TD, 'text-right text-foreground')}>
                        {formatNumber(oa.usd)}
                      </td>
                      <td className={cn(TD, 'text-right text-foreground')}>
                        {formatNumber(oa.incidents)}
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
  );
}

