import { useEffect, useRef, useState } from 'react';
import { Link, useSearchParams } from 'react-router-dom';
import { Database, FileUp } from 'lucide-react';
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
import { useDashboardFilters } from '../hooks/useDashboardFilters';
import { fetchBreakdowns, fetchFilterOptions } from '../services/api';
import type { BucketId, SiteRecord } from '../types';

/**
 * Threshold Analysis › Uptime Buckets & Site Details: the site uptime bucket chart and the site table,
 * moved here from the Overview / 4G / LWE pages. Same components, endpoints and URL parameters
 * (report_type, circle, scope, date, bucket, bucket_basis), so links and filters carry over.
 */
export function BucketsSitesPage() {
  const workbook = useWorkbook();
  const { version } = workbook;
  const options = useApiQuery(workbook.active ? `${version}|filters` : null, fetchFilterOptions);
  const { filters, setFilters, reset, isDefault } = useDashboardFilters(options.data);
  const [searchParams, setSearchParams] = useSearchParams();
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

  const snapshotKey = filters ? `${version}|${filters.snapshotParams}` : null;
  const breakdown = useApiQuery(snapshotKey, (signal) => fetchBreakdowns(filters!.snapshotParams, signal));

  if (!workbook.loading && !workbook.error && !workbook.active) {
    return (
      <Card className="mx-auto mt-10 max-w-xl items-center gap-3 px-8 py-10 text-center">
        <FileUp className="size-8 text-muted-foreground" aria-hidden="true" />
        <h1 className="text-lg font-semibold">No Master workbook loaded</h1>
        <p className="text-sm text-muted-foreground">Upload the consolidated 4G Saturation &amp; LWE workbook to see uptime buckets and site details.</p>
        <Link to="/workbook" className={buttonVariants({ size: 'sm' })}><FileUp /> Upload workbook</Link>
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

  const scopeLabel = options.data.scopes.find((s) => s.value === filters.scope)?.label ?? filters.scope;
  const summary = [filters.reportType || 'All projects', filters.circle ? `Circle ${filters.circle}` : 'All circles', scopeLabel].join(' · ');

  return (
    <div className="space-y-4">
      <FilterBar options={options.data} filters={filters} onChange={setFilters} onReset={reset} canReset={!isDefault || bucket !== ''}
        showTrendRange={false} title="Uptime buckets & site details"
        description={<>{options.data.month.label} reporting month · {summary}</>} />

      <BucketDistribution breakdown={breakdown.data} loading={breakdown.loading} error={breakdown.error} onSelectBucket={setBucket} />

      <div ref={tableRef} className="scroll-mt-20">
        <SiteTable params={filters.snapshotParams} version={version} bucket={bucket} bucketBasis={bucketBasis}
          onBucketChange={setBucket} onSelectSite={setSelectedSite} />
      </div>

      <SiteDetailSheet site={selectedSite} onClose={() => setSelectedSite(null)} />
    </div>
  );
}
