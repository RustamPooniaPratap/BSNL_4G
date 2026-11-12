import { useEffect, useRef, useState } from 'react';
import { Link, useSearchParams } from 'react-router-dom';
import { ArrowLeft, Database, FileUp, UserRound } from 'lucide-react';
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert';
import { buttonVariants } from '@/components/ui/button';
import { Card } from '@/components/ui/card';
import { Skeleton } from '@/components/ui/skeleton';
import { BucketDistribution } from '../components/dashboard/BucketDistribution';
import { BUCKET_ORDER } from '../components/dashboard/constants';
import { FilterBar } from '../components/dashboard/FilterBar';
import { SiteDetailSheet } from '../components/dashboard/SiteDetailSheet';
import { SiteTable } from '../components/dashboard/SiteTable';
import { useWorkbook } from '../context/workbook';
import { useApiQuery } from '../hooks/useApiQuery';
import { useFilterOptions } from '../hooks/useFilterOptions';
import { useDashboardFilters } from '../hooks/useDashboardFilters';
import { TEAM_SITES_PARAMS } from '../lib/teams';
import { cn } from '@/lib/utils';
import { fetchBreakdowns } from '../services/api';
import type { BucketId, SiteRecord, TeamGroup } from '../types';
import { populationSites } from '../lib/population';

/** A CI / IE opened from CI & IE Performance (Flow B): all four values identify the person; otherwise null (Flow A). */
function teamFrom(params: URLSearchParams) {
  const group = params.get('team_group');
  const [name, project, circle] = ['team', 'team_project', 'team_circle'].map((k) => params.get(k)?.trim() ?? '');
  if ((group !== 'ci' && group !== 'ie') || !name || !project || !circle) return null;
  const back = params.get('back') ?? '';
  return { group: group as TeamGroup, name, project, circle, back: back.startsWith('/teams/ci-ie') ? back : '/teams/ci-ie' };
}

/**
 * Threshold Analysis › Uptime Buckets & Site Details: the site uptime bucket chart and the site table,
 * moved here from the Overview / 4G / LWE pages. Same components, endpoints and URL parameters
 * (report_type, circle, scope, date, bucket, bucket_basis), so links and filters carry over.
 *
 * Opened from CI & IE Performance (team_group, team, team_project, team_circle in the URL), the same page shows only
 * that person's sites: the server restricts the chart and the table, the page's filters still apply within them, and
 * an NSLA switch lists the sites below 98.5% MTD. Without those parameters nothing differs from the normal page.
 */
export function BucketsSitesPage() {
  const workbook = useWorkbook();
  const { version } = workbook;
  const options = useFilterOptions();
  const { filters, setFilters, isDefault } = useDashboardFilters(options.data);
  const [searchParams, setSearchParams] = useSearchParams();
  const team = teamFrom(searchParams);
  const nsla = Boolean(team) && searchParams.get('nsla') === '1';
  const nslaMonth = team ? searchParams.get('nsla_month') : null;
  const setNsla = (on: boolean) => setSearchParams((current) => {
    const next = new URLSearchParams(current);
    if (on) next.set('nsla', '1');
    else next.delete('nsla');
    return next;
  }, { replace: true });
  // Resetting the filters keeps the CI / IE context (it is left only with Back or "All sites").
  const reset = () => setSearchParams((current) => new URLSearchParams(
    [...current.entries()].filter(([k]) => team && (TEAM_SITES_PARAMS as readonly string[]).includes(k))), { replace: true });
  const leaveTeam = () => setSearchParams((current) => new URLSearchParams(
    [...current.entries()].filter(([k]) => !(TEAM_SITES_PARAMS as readonly string[]).includes(k))), { replace: true });
  // The bucket drill-down lives in the URL so alerts and other pages can link to it (e.g. ?bucket=lt_60).
  const bucketParam = searchParams.get('bucket') ?? '';
  const bucket: BucketId | '' = (BUCKET_ORDER as string[]).includes(bucketParam) ? (bucketParam as BucketId) : '';
  // bucket_basis=daily filters on uptime on the reporting date instead of MTD.
  const bucketBasis = searchParams.get('bucket_basis') === 'daily' ? 'daily' : 'mtd';
  const setBucket = (id: BucketId | '') => setSearchParams((current) => {
    const next = new URLSearchParams(current);
    if (id) next.set('bucket', id);
    else next.delete('bucket');
    next.delete('bucket_basis');
    return next;
  }, { replace: true });
  const [selectedSite, setSelectedSite] = useState<SiteRecord | null>(null);
  const tableRef = useRef<HTMLDivElement>(null);
  const ready = Boolean(filters);
  useEffect(() => {
    if (bucket && ready) tableRef.current?.scrollIntoView({ behavior: 'smooth', block: 'start' });
  }, [bucket, ready]);

  // The person's identity goes to the API with every request: it limits the chart and the table on the server.
  const params = filters ? new URLSearchParams(filters.snapshotParams) : null;
  if (params && team) {
    params.set('team_group', team.group);
    params.set('team', team.name);
    params.set('team_project', team.project);
    params.set('team_circle', team.circle);
  }
  const tableParams = params ? new URLSearchParams(params) : null;
  if (tableParams && nsla) tableParams.set('below_sla', 'true');
  const snapshotKey = params ? `${version}|${params}` : null;
  const breakdown = useApiQuery(snapshotKey, (signal) => fetchBreakdowns(params!, signal));

  if (!workbook.loading && !workbook.error && !workbook.active) {
    return (
      <Card className="mx-auto mt-10 max-w-xl items-center gap-3 px-8 py-10 text-center">
        <FileUp className="size-8 text-muted-foreground" aria-hidden="true" />
        <h1 className="text-lg font-semibold">No reporting data loaded</h1>
        <p className="text-sm text-muted-foreground">Import the Uptime Master and Consolidation Matrix (Data Source page) to see uptime buckets and site details.</p>
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
        <AlertDescription>{fatal.message} No sample data is substituted.</AlertDescription>
      </Alert>
    );
  }
  if (!options.data || !filters) {
    return (
      <div className="space-y-4" aria-busy="true" aria-label="Loading uptime buckets">
        <Skeleton className="h-20 w-full" />
        <Skeleton className="h-72 w-full" />
      </div>
    );
  }

  const scopeLabel = populationSites(filters.scope);
  const summary = [filters.reportType || 'All projects', filters.circle ? `Circle ${filters.circle}` : 'All circles', `Population: ${scopeLabel}`].join(' · ');
  const outsideScope = team && ((filters.reportType && filters.reportType !== team.project) || (filters.circle && filters.circle !== team.circle));

  return (
    <div className="space-y-4">
      <FilterBar options={options.data} filters={filters} onChange={setFilters} onReset={reset} canReset={!isDefault || bucket !== ''}
        showTrendRange={false} title="Uptime buckets & site details"
        description={<>{options.data.month.label} reporting month · {summary}</>} />

      {team && (
        <section aria-label="CI / IE sites" className="flex flex-wrap items-center gap-x-4 gap-y-2 rounded-xl border bg-card px-4 py-2.5 shadow-xs">
          <Link to={team.back} className={buttonVariants({ variant: 'outline', size: 'sm' })}><ArrowLeft /> Back to CI &amp; IE Performance</Link>
          <p className="flex items-center gap-1.5 text-sm">
            <UserRound className="size-4 text-muted-foreground" aria-hidden="true" />
            <span className="font-semibold">{team.group.toUpperCase()}: {team.name}</span>
            <span className="text-muted-foreground">· {team.project} · {team.circle} · assigned sites only</span>
          </p>
          <div role="group" aria-label="NSLA filter" className="inline-flex rounded-md border p-0.5 text-xs">
            {[[false, 'All assigned sites'], [true, 'NSLA (< 98.5% MTD)']].map(([on, label]) => (
              <button key={String(on)} type="button" aria-pressed={nsla === on} onClick={() => setNsla(on as boolean)}
                className={cn('rounded px-2 py-1 font-medium', nsla === on ? 'bg-primary text-primary-foreground' : 'text-muted-foreground hover:text-foreground')}>{label as string}</button>
            ))}
          </div>
          <button type="button" onClick={leaveTeam} className="ml-auto text-xs text-muted-foreground underline-offset-4 hover:underline">Show all sites</button>
          {nslaMonth && (
            <p className="w-full text-xs text-amber-800">
              CI &amp; IE Performance showed {nslaMonth}; site details are for the current reporting month ({options.data.month.label}) up to the reporting date.
            </p>
          )}
          {outsideScope && (
            <p className="w-full text-xs text-amber-800" role="status">
              The project or circle filter is outside {team.name}&apos;s assignment ({team.project} · {team.circle}), so no site matches.
            </p>
          )}
        </section>
      )}

      <BucketDistribution breakdown={breakdown.data} loading={breakdown.loading} error={breakdown.error} onSelectBucket={setBucket} />

      <div ref={tableRef} className="scroll-mt-20">
        <SiteTable params={tableParams!} version={version} bucket={bucket} bucketBasis={bucketBasis}
          onBucketChange={setBucket} onSelectSite={setSelectedSite}
          title={team ? `Sites of ${team.name}${nsla ? ' · NSLA (below 98.5% MTD)' : ''}` : undefined} />
      </div>

      <SiteDetailSheet site={selectedSite} onClose={() => setSelectedSite(null)} />
    </div>
  );
}
