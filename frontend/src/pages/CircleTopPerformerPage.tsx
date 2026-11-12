import { useEffect, useMemo } from 'react';
import { Link, useNavigate, useParams, useSearchParams } from 'react-router-dom';
import { ChevronRight, Database, FileUp, Info } from 'lucide-react';
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert';
import { Button, buttonVariants } from '@/components/ui/button';
import { Card } from '@/components/ui/card';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import { Skeleton } from '@/components/ui/skeleton';
import { CircleRankings } from '../components/dashboard/CircleRankings';
import { Field, FilterBar } from '../components/dashboard/FilterBar';
import { PageHeading } from '../context/pageHeader';
import { useWorkbook } from '../context/workbook';
import { useApiQuery } from '../hooks/useApiQuery';
import { useFilterOptions } from '../hooks/useFilterOptions';
import { useDashboardFilters, type DashboardFilterState } from '../hooks/useDashboardFilters';
import { formatDate } from '../lib/format';
import { fetchTeamTop } from '../services/api';
import type { TeamGroup, TopPerformerCircle } from '../types';
import { populationSites } from '../lib/population';

export function CircleTopPerformerPage() {
  const { circleId } = useParams<{ circleId: string }>();
  const navigate = useNavigate();
  const workbook = useWorkbook();
  const { version } = workbook;
  const options = useFilterOptions();
  const { filters, setFilters, reset, isDefault } = useDashboardFilters(options.data);
  const [searchParams, setSearchParams] = useSearchParams();
  const month = searchParams.get('month') ?? '';

  const setParam = (key: string, value: string | null) => setSearchParams((current) => {
    const next = new URLSearchParams(current);
    if (value) next.set(key, value);
    else next.delete(key);
    return next;
  }, { replace: true });

  // Resolve circle from URL param or query param using filter options
  const circleOption = useMemo(() => {
    if (!options.data) return null;
    const fromParam = circleId ? decodeURIComponent(circleId).trim() : '';
    const fromQuery = searchParams.get('circle')?.trim() ?? '';

    // First try circleId param
    if (fromParam) {
      const matchParam = options.data.circles.find(
        (c) => c.value.toLowerCase() === fromParam.toLowerCase() || c.label.toLowerCase() === fromParam.toLowerCase()
      );
      if (matchParam) return matchParam;
    }

    // Fall back to query param "circle" if route param was truncated or invalid
    if (fromQuery) {
      const matchQuery = options.data.circles.find(
        (c) => c.value.toLowerCase() === fromQuery.toLowerCase() || c.label.toLowerCase() === fromQuery.toLowerCase()
      );
      if (matchQuery) return matchQuery;
    }

    return null;
  }, [options.data, circleId, searchParams]);

  const circleCode = circleOption?.value ?? (circleId ? decodeURIComponent(circleId) : (searchParams.get('circle') ?? ''));
  const circleName = circleOption?.label ?? circleCode;

  // Normalize URL if circleId in path was invalid or truncated (e.g. /teams/top/circle/R?circle=RJ -> /teams/top/circle/RJ)
  useEffect(() => {
    if (circleOption && circleId && circleOption.value.toLowerCase() !== decodeURIComponent(circleId).toLowerCase()) {
      const q = searchParams.toString();
      navigate(`/teams/top/circle/${encodeURIComponent(circleOption.value)}${q ? `?${q}` : ''}`, { replace: true });
    }
  }, [circleOption, circleId, navigate, searchParams]);

  // Automatically synchronize Circle filter to the resolved circle
  useEffect(() => {
    if (!circleOption || !filters) return;
    if (filters.circle !== circleOption.value) {
      setFilters({ circle: circleOption.value });
    }
  }, [circleOption, filters, setFilters]);

  // Back URL for breadcrumb navigation, preserving other global filters but clearing circle filter
  const backUrl = useMemo(() => {
    const backQuery = new URLSearchParams(searchParams);
    backQuery.delete('circle');
    const qs = backQuery.toString();
    return `/teams/top${qs ? `?${qs}` : ''}`;
  }, [searchParams]);

  // Build query for top performers API
  let topQuery: URLSearchParams | null = null;
  if (filters && circleCode) {
    topQuery = new URLSearchParams(filters.snapshotParams);
    topQuery.delete('reporting_date');
    topQuery.set('circle', circleCode);
    if (month) topQuery.set('month', month);
  }
  const topResult = useApiQuery(
    topQuery ? `${version}|teams-top|${topQuery.toString()}` : null,
    (signal) => fetchTeamTop(topQuery!, signal)
  );

  if (!workbook.loading && !workbook.error && !workbook.active) {
    return (
      <Card className="mx-auto mt-10 max-w-xl items-center gap-3 px-8 py-10 text-center">
        <FileUp className="size-8 text-muted-foreground" aria-hidden="true" />
        <h1 className="text-lg font-semibold">No reporting data loaded</h1>
        <p className="text-sm text-muted-foreground">Import the reporting data (Data Source page) to see circle details.</p>
        <Link to="/workbook" className={buttonVariants({ size: 'sm' })}><FileUp /> Import data</Link>
      </Card>
    );
  }

  const fatal = workbook.error ?? options.error;
  if (fatal) {
    return (
      <Alert variant="destructive" className="mx-auto mt-10 max-w-2xl">
        <Database />
        <AlertTitle>Reporting data is unavailable</AlertTitle>
        <AlertDescription>{fatal.message}</AlertDescription>
      </Alert>
    );
  }

  if (!options.data || !filters) {
    return <Skeleton className="h-96 w-full" aria-label="Loading circle details" />;
  }

  // Check if circle is outside active project's available circles
  const isProjectMismatch = Boolean(
    filters.reportType && circleOption && !circleOption.report_types.includes(filters.reportType)
  );

  const topData = topResult.data;
  const months = topData?.months_available ?? options.data.months ?? [];
  const latest = months[months.length - 1]?.key;
  const selectedMonth = month || topData?.reporting_month || latest || '';
  const scopeLabel = populationSites(filters.scope);
  const subtitle = `${filters.reportType || 'All projects'} · Population: ${scopeLabel}`;
  const period = topData?.month
    ? `${topData.month.label}${topData.month.kind === 'mtd' ? ` to ${formatDate(topData.reporting_date)}` : ''}`
    : '';

  // Filter circles from response matching this circle and active project filter
  const matchingCircles = (topData?.circles ?? []).filter(
    (c) => c.circle.toLowerCase() === circleCode.toLowerCase() &&
           (!filters.reportType || c.report_type === filters.reportType)
  );

  // Opens the person on CI & IE Performance with the same project, circle, scope and month.
  const personLink = (group: TeamGroup, c: TopPerformerCircle, name: string) => {
    const q = new URLSearchParams({ report_type: c.report_type, circle: c.circle, scope: filters.scope, q: name });
    if (group === 'ie') q.set('group', 'ie');
    if (month) q.set('month', month);
    return `/teams/ci-ie?${q.toString()}`;
  };

  const handleFilterChange = (changes: Partial<DashboardFilterState>) => {
    // If the circle filter is explicitly changed from the dropdown, navigate to the selected circle's page
    if (changes.circle && changes.circle !== circleCode) {
      const nextParams = new URLSearchParams(searchParams);
      nextParams.set('circle', changes.circle);
      navigate(`/teams/top/circle/${encodeURIComponent(changes.circle)}?${nextParams.toString()}`);
      return;
    }
    setFilters(changes);
  };

  return (
    <div className="space-y-4">
      {/* Set top app navigation bar heading */}
      <PageHeading title={circleName} subtitle={subtitle} />

      {/* Breadcrumb: Circle-wise Top Performers -> Selected Circle */}
      <nav aria-label="Breadcrumb" className="flex items-center gap-1.5 text-xs text-muted-foreground">
        <Link
          to={backUrl}
          className="font-medium hover:text-foreground hover:underline transition-colors"
        >
          Circle-wise Top Performers
        </Link>
        <ChevronRight className="size-3.5 shrink-0 text-muted-foreground/60" aria-hidden="true" />
        <span className="font-semibold text-foreground" aria-current="page">
          {circleName}
        </span>
      </nav>

      {/* Global Filter Bar */}
      <FilterBar
        options={options.data}
        filters={filters}
        onChange={handleFilterChange}
        canReset={!isDefault || !!month}
        onReset={reset}
        showTrendRange={false}
        showDate={false}
        title={circleName}
        description={subtitle}
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

      {isProjectMismatch ? (
        <Alert variant="destructive">
          <Info className="size-4" />
          <AlertTitle>Circle unavailable under selected project</AlertTitle>
          <AlertDescription className="flex flex-wrap items-center gap-3">
            <span>
              Circle <strong>{circleName}</strong> is not part of project <strong>{filters.reportType}</strong>.
            </span>
            <Button size="sm" variant="outline" onClick={() => navigate(backUrl)}>
              Back to Circle-wise Top Performers
            </Button>
          </AlertDescription>
        </Alert>
      ) : topResult.error && month ? (
        <Alert variant="destructive">
          <Database />
          <AlertTitle>No data for this month in the selection</AlertTitle>
          <AlertDescription className="flex flex-wrap items-center gap-3">
            {topResult.error.message}
            <Button size="sm" variant="outline" onClick={() => setParam('month', null)}>Show the latest month</Button>
          </AlertDescription>
        </Alert>
      ) : topResult.error ? (
        <Alert variant="destructive">
          <Database />
          <AlertTitle>Performance data unavailable</AlertTitle>
          <AlertDescription>{topResult.error.message}</AlertDescription>
        </Alert>
      ) : topResult.loading && !topData ? (
        <Skeleton className="h-96 w-full" aria-label="Loading circle performance" />
      ) : matchingCircles.length > 0 ? (
        <div className="space-y-6">
          {matchingCircles.map((c) => (
            <CircleRankings
              key={`${c.report_type}|${c.circle}`}
              circle={c}
              period={period}
              link={personLink}
            />
          ))}
        </div>
      ) : (
        <Card className="mx-auto max-w-xl p-8 text-center text-muted-foreground">
          <Info className="mx-auto mb-2 size-8 text-muted-foreground/60" aria-hidden="true" />
          <h2 className="text-base font-semibold text-foreground">No Performance Rankings</h2>
          <p className="mt-1 text-sm">
            No CI or IE performance records found for {circleName} under the selected filters.
          </p>
        </Card>
      )}
    </div>
  );
}
