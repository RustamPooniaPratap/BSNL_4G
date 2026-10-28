import { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import { ArrowDown, ArrowUp, ArrowUpDown, ChevronLeft, ChevronRight, Search, X } from 'lucide-react';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table';
import { useApiQuery } from '../../hooks/useApiQuery';
import { formatDate, formatMinutes, formatNumber, formatPct } from '../../lib/format';
import { teamLink, UNASSIGNED } from '../../lib/teams';
import { fetchRecords } from '../../services/api';
import { cn } from '@/lib/utils';
import type { BucketId, SiteRecord, SortField, TeamGroup } from '../../types';
import { ChartCard } from './ChartCard';
import { BUCKET_COLORS, BUCKET_LABELS } from './constants';

const PAGE_SIZE = 25;

const COLUMNS: { field: SortField | null; label: string; align?: 'right' }[] = [
  { field: 'site_id', label: 'Site ID' },
  { field: 'site_name', label: 'Site name' },
  { field: 'report_type', label: 'Type' },
  { field: 'circle', label: 'Circle' },
  { field: 'oa', label: 'OA' },
  { field: 'outage_minutes', label: 'Outage', align: 'right' },
  { field: 'daily_uptime_pct', label: 'Daily uptime', align: 'right' },
  { field: 'mtd_uptime_pct', label: 'MTD uptime', align: 'right' },
  { field: null, label: 'MTD bucket' },
  { field: 'ie_name', label: 'IE' },
  { field: 'ci_name', label: 'CI' },
];

export interface TeamFilter {
  group: TeamGroup;
  name: string;
}

interface SiteTableProps {
  params: URLSearchParams;
  /** Active workbook version; part of the query key so a new upload refetches. */
  version: string;
  bucket: BucketId | '';
  onBucketChange: (bucket: BucketId | '') => void;
  onSelectSite: (site: SiteRecord) => void;
  /** Whether ``bucket`` applies to MTD uptime (default) or uptime on the reporting date. */
  bucketBasis?: 'mtd' | 'daily';
  /** Only sites assigned to this CI or IE. */
  team?: TeamFilter | null;
  onClearTeam?: () => void;
  title?: string;
}

export function SiteTable({
  params, version, bucket, onBucketChange, onSelectSite, team, onClearTeam, title = 'Site detail', bucketBasis = 'mtd',
}: SiteTableProps) {
  const [searchInput, setSearchInput] = useState('');
  const [search, setSearch] = useState('');
  const [sort, setSort] = useState<{ field: SortField; direction: 'asc' | 'desc' }>({ field: 'mtd_uptime_pct', direction: 'asc' });
  // Any change to the filters, search or bucket starts again from page 1.
  const filterKey = `${version}|${params.toString()}|${search}|${bucket}|${bucketBasis}|${team?.group}|${team?.name}`;
  const [pageState, setPageState] = useState({ key: filterKey, page: 1 });
  const page = pageState.key === filterKey ? pageState.page : 1;
  const setPage = (next: number) => setPageState({ key: filterKey, page: next });

  useEffect(() => {
    const timer = window.setTimeout(() => setSearch(searchInput.trim()), 300);
    return () => window.clearTimeout(timer);
  }, [searchInput]);

  const query = new URLSearchParams(params);
  if (search) query.set('search', search);
  if (bucket) query.set('bucket', bucket);
  if (bucket && bucketBasis === 'daily') query.set('bucket_basis', 'daily');
  if (team) query.set(team.group === 'ci' ? 'ci_name' : 'ie_name', team.name);
  query.set('sort', sort.field);
  query.set('direction', sort.direction);
  query.set('page', String(page));
  query.set('page_size', String(PAGE_SIZE));
  const key = `${version}|${query}`;
  const { data, error, loading } = useApiQuery(key, (signal) => fetchRecords(query, signal));

  const toggleSort = (field: SortField) =>
    setSort((s) => ({ field, direction: s.field === field && s.direction === 'asc' ? 'desc' : 'asc' }));

  const records = data?.records ?? [];
  const pages = data?.pages ?? 1;

  return (
    <ChartCard
      title={title}
      description={
        data
          ? `${formatNumber(data.count)} matching sites · values for ${formatDate(data.reporting_date)} · select a row for the daily history`
          : 'Sites in the current filter scope'
      }
      action={
        <div className="flex flex-wrap items-center justify-end gap-2">
          {team && (
            <Badge variant="outline" className="gap-1">
              {team.group.toUpperCase()}: {team.name}
              {onClearTeam && (
                <button type="button" onClick={onClearTeam} aria-label="Clear team filter" className="rounded-sm hover:text-foreground">
                  <X className="size-3" />
                </button>
              )}
            </Badge>
          )}
          {bucket && (
            <Badge variant="outline" className="gap-1">
              <span className="size-2 rounded-full" style={{ background: BUCKET_COLORS[bucket] }} aria-hidden="true" />
              {BUCKET_LABELS[bucket]} {bucketBasis === 'daily' ? `on ${formatDate(params.get('reporting_date'))}` : 'MTD'}
              <button type="button" onClick={() => onBucketChange('')} aria-label="Clear bucket filter" className="rounded-sm hover:text-foreground">
                <X className="size-3" />
              </button>
            </Badge>
          )}
          <div className="relative">
            <Search className="pointer-events-none absolute top-1/2 left-2.5 size-3.5 -translate-y-1/2 text-muted-foreground" aria-hidden="true" />
            <Input
              type="search"
              value={searchInput}
              onChange={(e) => setSearchInput(e.target.value)}
              placeholder="Search ID, name, OA, BA, IE, CI"
              aria-label="Search sites"
              className="h-8 w-56 pl-8"
              maxLength={100}
            />
          </div>
        </div>
      }
      loading={loading}
      error={error}
      empty={!records.length}
      emptyMessage={search ? `No sites match “${search}”.` : 'No sites match the selected filters.'}
      bodyClassName="px-0"
    >
      <div className="overflow-x-auto">
        <Table className="text-xs">
          <TableHeader>
            <TableRow className="bg-muted/50 hover:bg-muted/50">
              {COLUMNS.map((column) => {
                const active = column.field === sort.field;
                return (
                  <TableHead
                    key={column.label}
                    className={column.align === 'right' ? 'text-right' : undefined}
                    aria-sort={active ? (sort.direction === 'asc' ? 'ascending' : 'descending') : undefined}
                  >
                    {column.field ? (
                      <button
                        type="button"
                        onClick={() => toggleSort(column.field!)}
                        className="inline-flex items-center gap-1 rounded font-medium hover:text-foreground focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none"
                      >
                        {column.label}
                        {active ? (sort.direction === 'asc' ? <ArrowUp className="size-3" /> : <ArrowDown className="size-3" />)
                          : <ArrowUpDown className="size-3 opacity-40" />}
                      </button>
                    ) : column.label}
                  </TableHead>
                );
              })}
            </TableRow>
          </TableHeader>
          <TableBody>
            {records.map((row) => (
              <TableRow
                key={`${row.report_type}-${row.site_id}`}
                className="cursor-pointer"
                tabIndex={0}
                onClick={() => onSelectSite(row)}
                onKeyDown={(e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); onSelectSite(row); } }}
                aria-label={`${row.site_id} ${row.site_name}: open daily history`}
              >
                <TableCell className="font-mono font-medium">{row.site_id}</TableCell>
                <TableCell className="max-w-48 truncate" title={row.site_name}>{row.site_name || '—'}</TableCell>
                <TableCell>{row.report_type}</TableCell>
                <TableCell>{row.circle}</TableCell>
                <TableCell className="max-w-32 truncate" title={row.oa}>{row.oa || '—'}</TableCell>
                <TableCell className="text-right tabular-nums">{row.outage_minutes == null ? 'Not reported' : formatMinutes(row.outage_minutes)}</TableCell>
                <TableCell className="text-right tabular-nums">{formatPct(row.daily_uptime_pct)}</TableCell>
                <TableCell className="text-right font-medium tabular-nums">{formatPct(row.mtd_uptime_pct)}</TableCell>
                <TableCell><BucketBadge bucket={row.bucket} /></TableCell>
                <TableCell className="max-w-36 truncate"><PersonLink group="ie" name={row.ie_name} site={row} /></TableCell>
                <TableCell className="max-w-36 truncate"><PersonLink group="ci" name={row.ci_name} site={row} /></TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </div>
      <nav className="flex items-center justify-between gap-3 border-t px-4 pt-3 text-xs text-muted-foreground" aria-label="Table pagination">
        <span>Page {data?.page ?? page} of {pages}</span>
        <div className="flex gap-1.5">
          <Button variant="outline" size="sm" onClick={() => setPage(page - 1)} disabled={page <= 1 || loading}>
            <ChevronLeft /> Previous
          </Button>
          <Button variant="outline" size="sm" onClick={() => setPage(page + 1)} disabled={page >= pages || loading}>
            Next <ChevronRight />
          </Button>
        </div>
      </nav>
    </ChartCard>
  );
}

function PersonLink({ group, name, site }: { group: TeamGroup; name: string; site: SiteRecord }) {
  if (!name || name === UNASSIGNED) return <span className="text-muted-foreground italic">{UNASSIGNED}</span>;
  return (
    <Link
      to={teamLink(group, name, site)}
      onClick={(e) => e.stopPropagation()}
      onKeyDown={(e) => e.stopPropagation()}
      title={`${group === 'ci' ? 'CI' : 'IE'} ${name}: open team performance`}
      className={cn('font-medium underline-offset-4 hover:underline focus-visible:underline focus-visible:outline-none')}
    >
      {name}
    </Link>
  );
}

export function BucketBadge({ bucket }: { bucket: BucketId | null }) {
  if (!bucket) return <span className="text-muted-foreground">—</span>;
  return (
    <span className="inline-flex items-center gap-1.5 whitespace-nowrap">
      <span className="size-2 rounded-full" style={{ background: BUCKET_COLORS[bucket] }} aria-hidden="true" />
      {BUCKET_LABELS[bucket]}
    </span>
  );
}
