import { useMemo, useState } from 'react';
import { Link, useNavigate, useParams, useSearchParams } from 'react-router-dom';
import { ChevronRight, Users, Info } from 'lucide-react';
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
  getCisForOa,
  aggregateKpis,
} from '../../services/hierarchyMockData';
import { DemoDataBadge } from '../../components/hierarchy/DemoDataBadge';
import { HierarchyKpiCards } from '../../components/hierarchy/HierarchyKpiCards';
import { HierarchyBreadcrumbs } from '../../components/hierarchy/HierarchyBreadcrumbs';

const TH = 'border-b bg-muted/50 px-3 py-2 text-[11px] font-medium whitespace-nowrap text-muted-foreground';
const TD = 'border-b px-3 py-2 align-middle text-xs tabular-nums';

export function OaPerformancePage() {
  const { circleCode, oaId } = useParams<{ circleCode: string; oaId: string }>();
  const navigate = useNavigate();
  const workbook = useWorkbook();
  const { version } = workbook;
  const options = useApiQuery(workbook.active ? `${version}|filters` : null, fetchFilterOptions);
  const { filters, setFilters, reset, isDefault } = useDashboardFilters(options.data, { defaultScope: 'om_start' });
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

  const oa = useMemo(() => {
    if (!oaId) return undefined;
    return getOa(oaId);
  }, [oaId]);

  const cis = useMemo(() => {
    if (!oaId) return [];
    return getCisForOa(oaId);
  }, [oaId]);

  const filteredCis = useMemo(() => {
    if (!search.trim()) return cis;
    const term = search.toLowerCase().trim();
    return cis.filter(
      (ci) =>
        ci.ci_name.toLowerCase().includes(term) ||
        (ci.emp_code && ci.emp_code.includes(term))
    );
  }, [cis, search]);

  const oaKpis = useMemo(() => {
    if (oa) return oa;
    return aggregateKpis(cis);
  }, [oa, cis]);

  const months = options.data?.months ?? [];
  const latest = months[months.length - 1]?.key;
  const selectedMonth = month || latest || '2026-10';
  const monthLabel = months.find((m) => m.key === selectedMonth)?.label ?? 'Oct-26 MTD';
  const scopeLabel = options.data?.scopes.find((s) => s.value === filters?.scope)?.label ?? 'O&M Start';
  const circleName = circle?.circle_name ?? circleCode ?? '';
  const oaName = oa?.oa_name ?? oaId ?? '';
  const subtitle = `${oaName} · ${circleName} (${circleCode}) · ${filters?.reportType || 'All Projects'} · ${scopeLabel}`;

  if (!options.data || !filters) {
    return <Skeleton className="h-96 w-full" aria-label="Loading OA performance" />;
  }

  const handleCiClick = (ciId: string) => {
    const q = searchParams.toString();
    navigate(`/teams/hierarchy/circle/${encodeURIComponent(circleCode!)}/oa/${encodeURIComponent(oaId!)}/ci/${encodeURIComponent(ciId)}${q ? `?${q}` : ''}`);
  };

  const handleFilterChange = (changes: Partial<DashboardFilterState>) => {
    setFilters(changes);
  };

  return (
    <div className="space-y-4">
      {/* Top Heading */}
      <PageHeading title={`${oaName} OA Performance`} subtitle={subtitle} />

      {/* Demo data notice */}
      <DemoDataBadge />

      {/* Breadcrumb Trail */}
      <HierarchyBreadcrumbs
        items={[
          { label: 'Team Performance Hierarchy', to: '/teams/hierarchy' },
          { label: `${circleName} (${circleCode})`, to: `/teams/hierarchy/circle/${encodeURIComponent(circleCode!)}` },
          { label: oaName, current: true },
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
        title={`${oaName} OA Performance`}
        description="Cluster In-Charge (CI) assignments and metrics within this Operational Area."
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

      {/* OA Information & Context Card */}
      <div className="flex flex-wrap items-center justify-between gap-4 rounded-xl border bg-card p-4 shadow-xs">
        <div>
          <span className="text-xs font-medium text-muted-foreground">Operational Area Context</span>
          <div className="mt-0.5 flex items-center gap-2">
            <span className="text-base font-semibold text-foreground">{oaName}</span>
            <span className="rounded bg-muted px-2 py-0.5 text-xs text-muted-foreground">
              Circle: {circleName}
            </span>
          </div>
        </div>

        <div className="flex items-center gap-6 text-xs">
          <div>
            <span className="text-muted-foreground">Sites in OA:</span>{' '}
            <span className="font-semibold text-foreground">{formatNumber(oaKpis.assigned_sites)}</span>
          </div>
          <div>
            <span className="text-muted-foreground">Active CIs:</span>{' '}
            <span className="font-semibold text-foreground">{cis.length}</span>
          </div>
          <div>
            <span className="text-muted-foreground">Period:</span>{' '}
            <span className="font-semibold text-foreground">{monthLabel}</span>
          </div>
        </div>
      </div>

      {/* Cross-OA Relationship Explanatory Note */}
      <div className="flex items-start gap-2 rounded-lg border border-sky-200 bg-sky-50 p-3 text-xs text-sky-900">
        <Info className="size-4 shrink-0 text-sky-600 mt-0.5" aria-hidden="true" />
        <div>
          <span className="font-semibold">Many-to-Many Scoping Rule:</span> A Cluster In-Charge (CI) may cover multiple Operational Areas. The metrics below reflect only the sites assigned to the CI within <strong>{oaName}</strong>.
        </div>
      </div>

      {/* 5 KPI Cards */}
      <HierarchyKpiCards kpis={oaKpis} periodLabel={monthLabel} scopeLabel={scopeLabel} />

      {/* CI-wise Performance Table Card */}
      <Card className="rounded-xl border bg-card shadow-xs">
        <div className="flex flex-col gap-3 border-b p-4 sm:flex-row sm:items-center sm:justify-between">
          <div>
            <div className="flex items-center gap-2">
              <Users className="size-4 text-primary" aria-hidden="true" />
              <h2 className="text-sm font-semibold text-foreground">Cluster In-Charge (CI) Performance</h2>
              <span className="rounded-full bg-muted px-2 py-0.5 text-[11px] font-medium text-muted-foreground">
                {filteredCis.length} {filteredCis.length === 1 ? 'CI' : 'CIs'}
              </span>
            </div>
            <p className="mt-0.5 text-xs text-muted-foreground">
              Select any Cluster In-Charge to view assigned Integration Engineers (IEs) and complete site inventory
            </p>
          </div>

          <div className="w-48 sm:w-64">
            <Input
              type="search"
              placeholder="Search CI name or code..."
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              className="h-8 text-xs"
              aria-label="Search Cluster In-Charges"
            />
          </div>
        </div>

        <div className="overflow-x-auto">
          <table className="w-full min-w-[56rem] border-separate border-spacing-0">
            <thead>
              <tr>
                <th scope="col" className={cn(TH, 'w-12 text-center')}>Rank</th>
                <th scope="col" className={cn(TH, 'sticky left-0 z-10 w-48 text-left')}>Cluster In-Charge (CI)</th>
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
              {filteredCis.length === 0 ? (
                <tr>
                  <td colSpan={11} className="p-8 text-center text-xs text-muted-foreground">
                    No Cluster In-Charges found for this Operational Area.
                  </td>
                </tr>
              ) : (
                filteredCis.map((ci) => {
                  const q = searchParams.toString();
                  const targetUrl = `/teams/hierarchy/circle/${encodeURIComponent(circleCode!)}/oa/${encodeURIComponent(oaId!)}/ci/${encodeURIComponent(ci.ci_id)}${q ? `?${q}` : ''}`;
                  return (
                    <tr
                      key={ci.ci_id}
                      onClick={() => handleCiClick(ci.ci_id)}
                      className="group cursor-pointer hover:bg-muted/50 transition-colors"
                      tabIndex={0}
                      aria-label={`Open CI ${ci.ci_name}`}
                      onKeyDown={(e) => {
                        if (e.key === 'Enter' || e.key === ' ') {
                          e.preventDefault();
                          handleCiClick(ci.ci_id);
                        }
                      }}
                    >
                      <td className={cn(TD, 'text-center font-medium text-muted-foreground')}>
                        {ci.rank ?? '—'}
                      </td>
                      <th scope="row" className={cn(TD, 'sticky left-0 z-10 bg-card group-hover:bg-muted/50 transition-colors text-left')}>
                        <div className="flex items-center justify-between gap-1.5">
                          <Link
                            to={targetUrl}
                            onClick={(e) => e.stopPropagation()}
                            className="font-semibold text-foreground hover:text-primary hover:underline"
                          >
                            {ci.ci_name}
                          </Link>
                          <ChevronRight className="size-3.5 text-muted-foreground opacity-0 transition-opacity group-hover:opacity-100" aria-hidden="true" />
                        </div>
                        {ci.other_oas && ci.other_oas.length > 0 && (
                          <div className="text-[10px] text-muted-foreground mt-0.5">
                            Also in: {ci.other_oas.join(', ')}
                          </div>
                        )}
                      </th>
                      <td className={cn(TD, 'text-center font-mono')}>
                        {ci.emp_code ? (
                          <span className="text-foreground">{ci.emp_code}</span>
                        ) : (
                          <span className="text-muted-foreground italic">—</span>
                        )}
                      </td>
                      <td className={cn(TD, 'text-right font-medium text-foreground')}>
                        {formatNumber(ci.assigned_sites)}
                      </td>
                      <td className={cn(TD, 'text-right font-medium text-foreground')}>
                        {formatPct(ci.availability_pct, 1)}
                      </td>
                      <td className={cn(TD, 'text-right text-foreground')}>
                        {formatNumber(ci.nsla_sites)}
                      </td>
                      <td className={cn(TD, 'text-right font-medium')}>
                        <span className={cn('rounded px-1.5 py-0.5', ci.nsla_pct > 2 ? 'bg-amber-50 text-amber-800' : 'bg-emerald-50 text-emerald-800')}>
                          {formatPct(ci.nsla_pct, 1)}
                        </span>
                      </td>
                      <td className={cn(TD, 'text-right text-foreground')}>
                        {formatNumber(ci.usd)}
                      </td>
                      <td className={cn(TD, 'text-right text-foreground')}>
                        {formatNumber(ci.incidents)}
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
