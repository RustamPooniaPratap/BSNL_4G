import { useMemo, useState } from 'react';
import { Link, useNavigate, useSearchParams } from 'react-router-dom';
import { ChevronRight, Building2, UserX } from 'lucide-react';
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
  MOCK_CIRCLES,
  aggregateKpis,
} from '../../services/hierarchyMockData';
import { DemoDataBadge } from '../../components/hierarchy/DemoDataBadge';
import { HierarchyKpiCards } from '../../components/hierarchy/HierarchyKpiCards';

const TH = 'border-b bg-muted/50 px-3 py-2 text-[11px] font-medium whitespace-nowrap text-muted-foreground';
const TD = 'border-b px-3 py-2 align-middle text-xs tabular-nums';

export function OmOverviewPage() {
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

  const months = options.data?.months ?? [];
  const latest = months[months.length - 1]?.key;
  const selectedMonth = month || latest || '2026-10';
  const monthLabel = months.find((m) => m.key === selectedMonth)?.label ?? 'Oct-26 MTD';
  const scopeLabel = sitesLabel;
  const subtitle = `${filters?.reportType || 'All Projects'} · Population: ${scopeLabel} · ${monthLabel}`;

  // Filter circles by global filter and search term
  const displayedCircles = useMemo(() => {
    let list = MOCK_CIRCLES;
    if (filters?.circle) {
      list = list.filter((c) => c.circle.toUpperCase() === filters.circle.toUpperCase());
    }
    if (search.trim()) {
      const term = search.toLowerCase().trim();
      list = list.filter(
        (c) =>
          c.circle.toLowerCase().includes(term) ||
          c.circle_name.toLowerCase().includes(term) ||
          c.om_manager.toLowerCase().includes(term)
      );
    }
    return list;
  }, [filters?.circle, search]);

  // Aggregate 5 KPIs across all displayed circles
  const summaryKpis = useMemo(() => aggregateKpis(displayedCircles), [displayedCircles]);

  if (!options.data || !filters) {
    return <Skeleton className="h-96 w-full" aria-label="Loading O&M overview" />;
  }

  const handleFilterChange = (changes: Partial<DashboardFilterState>) => {
    setFilters(changes);
  };

  const handleCircleClick = (circleCode: string) => {
    const q = searchParams.toString();
    navigate(`/teams/hierarchy/circle/${encodeURIComponent(circleCode)}${q ? `?${q}` : ''}`);
  };

  return (
    <div className="space-y-4">
      {/* Top Heading */}
      <PageHeading title="Team Performance Hierarchy" subtitle={subtitle} />

      {/* Demo data notice */}
      <DemoDataBadge />

      {/* Filter Bar */}
      <FilterBar
        options={options.data}
        filters={filters}
        onChange={handleFilterChange}
        canReset={!isDefault || !!month}
        onReset={reset}
        showTrendRange={false}
        showDate={false}
        title="O&M Manager Overview"
        description="Circle-wise performance, assigned managers and active vacancies across the network."
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
      <HierarchyKpiCards kpis={summaryKpis} periodLabel={monthLabel} scopeLabel={scopeLabel} />

      {/* Circle-wise Performance Table Card */}
      <Card className="rounded-xl border bg-card shadow-xs">
        <div className="flex flex-col gap-3 border-b p-4 sm:flex-row sm:items-center sm:justify-between">
          <div>
            <div className="flex items-center gap-2">
              <Building2 className="size-4 text-primary" aria-hidden="true" />
              <h2 className="text-sm font-semibold text-foreground">Circle Performance Overview</h2>
              <span className="rounded-full bg-muted px-2 py-0.5 text-[11px] font-medium text-muted-foreground">
                {displayedCircles.length} Circles
              </span>
            </div>
            <p className="mt-0.5 text-xs text-muted-foreground">
              Select any Circle to drill down into its Operational Areas (OAs)
            </p>
          </div>

          <div className="w-48 sm:w-64">
            <Input
              type="search"
              placeholder="Search circle or manager..."
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              className="h-8 text-xs"
              aria-label="Search circles or managers"
            />
          </div>
        </div>

        <div className="overflow-x-auto">
          <table className="w-full min-w-[58rem] border-separate border-spacing-0">
            <thead>
              <tr>
                <th scope="col" className={cn(TH, 'w-12 text-center')}>Rank</th>
                <th scope="col" className={cn(TH, 'sticky left-0 z-10 w-32 text-left')}>Circle</th>
                <th scope="col" className={cn(TH, 'text-left')}>O&M Manager</th>
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
              {displayedCircles.length === 0 ? (
                <tr>
                  <td colSpan={11} className="p-8 text-center text-xs text-muted-foreground">
                    No circles match the search filter.
                  </td>
                </tr>
              ) : (
                displayedCircles.map((circle) => {
                  const q = searchParams.toString();
                  const targetUrl = `/teams/hierarchy/circle/${encodeURIComponent(circle.circle)}${q ? `?${q}` : ''}`;
                  return (
                    <tr
                      key={circle.circle}
                      onClick={() => handleCircleClick(circle.circle)}
                      className="group cursor-pointer hover:bg-muted/50 transition-colors"
                      tabIndex={0}
                      aria-label={`Open circle ${circle.circle_name}`}
                      onKeyDown={(e) => {
                        if (e.key === 'Enter' || e.key === ' ') {
                          e.preventDefault();
                          handleCircleClick(circle.circle);
                        }
                      }}
                    >
                      <td className={cn(TD, 'text-center font-medium text-muted-foreground')}>
                        {circle.rank ?? '—'}
                      </td>
                      <th scope="row" className={cn(TD, 'sticky left-0 z-10 bg-card group-hover:bg-muted/50 transition-colors text-left')}>
                        <div className="flex items-center justify-between gap-1.5">
                          <Link
                            to={targetUrl}
                            onClick={(e) => e.stopPropagation()}
                            className="font-semibold text-foreground hover:text-primary hover:underline"
                          >
                            {circle.circle}{' '}
                            <span className="font-normal text-muted-foreground">({circle.circle_name})</span>
                          </Link>
                          <ChevronRight className="size-3.5 text-muted-foreground opacity-0 transition-opacity group-hover:opacity-100" aria-hidden="true" />
                        </div>
                      </th>
                      <td className={cn(TD, 'font-medium')}>
                        {circle.is_vacant ? (
                          <span className="inline-flex items-center gap-1 rounded bg-amber-50 px-2 py-0.5 text-[11px] font-semibold text-amber-800 border border-amber-200">
                            <UserX className="size-3 shrink-0" aria-hidden="true" />
                            [VACANT POST]
                          </span>
                        ) : (
                          <div>
                            <span className="text-foreground">{circle.om_manager}</span>
                            {circle.emp_code && (
                              <span className="ml-1.5 text-[10px] text-muted-foreground">
                                ({circle.emp_code})
                              </span>
                            )}
                          </div>
                        )}
                      </td>
                      <td className={cn(TD, 'text-right font-medium text-foreground')}>
                        {formatNumber(circle.assigned_sites)}
                      </td>
                      <td className={cn(TD, 'text-right font-medium text-foreground')}>
                        {formatPct(circle.availability_pct, 1)}
                      </td>
                      <td className={cn(TD, 'text-right text-foreground')}>
                        {formatNumber(circle.nsla_sites)}
                      </td>
                      <td className={cn(TD, 'text-right font-medium')}>
                        <span className={cn('rounded px-1.5 py-0.5', circle.nsla_pct > 2 ? 'bg-amber-50 text-amber-800' : 'bg-emerald-50 text-emerald-800')}>
                          {formatPct(circle.nsla_pct, 1)}
                        </span>
                      </td>
                      <td className={cn(TD, 'text-right text-foreground')}>
                        {formatNumber(circle.usd)}
                      </td>
                      <td className={cn(TD, 'text-right text-foreground')}>
                        {formatNumber(circle.incidents)}
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
