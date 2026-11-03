import { useMemo, useState } from 'react';
import { Search, ChevronLeft, ChevronRight, Layers } from 'lucide-react';
import { Input } from '@/components/ui/input';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import { Button } from '@/components/ui/button';
import { cn } from '@/lib/utils';
import { formatNumber, formatPct } from '../../lib/format';
import type { HierarchySiteRow } from '../../types/hierarchy';

const TH = 'border-b bg-muted/50 px-3 py-2 text-[11px] font-medium whitespace-nowrap text-muted-foreground';
const TD = 'border-b px-3 py-2 align-middle text-xs tabular-nums';

interface AssignedSitesTableProps {
  sites: HierarchySiteRow[];
  title?: string;
  subtitle?: string;
}

export function AssignedSitesTable({
  sites,
  title = 'Assigned Sites',
  subtitle = 'Complete inventory of physical sites assigned within this hierarchy context',
}: AssignedSitesTableProps) {
  const [search, setSearch] = useState('');
  const [pageSize, setPageSize] = useState<number>(10);
  const [page, setPage] = useState<number>(1);

  // Filter sites by search string across site_id, site_name, oa, ie_name
  const filteredSites = useMemo(() => {
    if (!search.trim()) return sites;
    const term = search.toLowerCase().trim();
    return sites.filter(
      (s) =>
        s.site_id.toLowerCase().includes(term) ||
        s.site_name.toLowerCase().includes(term) ||
        s.oa_name.toLowerCase().includes(term) ||
        s.ie_name.toLowerCase().includes(term)
    );
  }, [sites, search]);

  const totalPages = Math.max(1, Math.ceil(filteredSites.length / pageSize));
  const currentPage = Math.min(page, totalPages);
  const pagedSites = useMemo(() => {
    const start = (currentPage - 1) * pageSize;
    return filteredSites.slice(start, start + pageSize);
  }, [filteredSites, currentPage, pageSize]);

  return (
    <div className="rounded-xl border bg-card shadow-xs">
      <div className="flex flex-col gap-3 border-b p-4 sm:flex-row sm:items-center sm:justify-between">
        <div>
          <div className="flex items-center gap-2">
            <Layers className="size-4 text-primary" aria-hidden="true" />
            <h2 className="text-sm font-semibold text-foreground">{title}</h2>
            <span className="rounded-full bg-muted px-2 py-0.5 text-[11px] font-medium text-muted-foreground">
              {formatNumber(filteredSites.length)} {filteredSites.length === 1 ? 'site' : 'sites'}
            </span>
          </div>
          <p className="mt-0.5 text-xs text-muted-foreground">{subtitle}</p>
        </div>

        <div className="flex flex-wrap items-center gap-2">
          <div className="relative w-48 sm:w-64">
            <Search className="absolute left-2.5 top-1/2 size-3.5 -translate-y-1/2 text-muted-foreground" aria-hidden="true" />
            <Input
              type="search"
              placeholder="Search site, OA or IE..."
              value={search}
              onChange={(e) => {
                setSearch(e.target.value);
                setPage(1);
              }}
              className="h-8 pl-8 text-xs"
              aria-label="Search assigned sites"
            />
          </div>

          <Select
            value={String(pageSize)}
            onValueChange={(val) => {
              setPageSize(Number(val));
              setPage(1);
            }}
          >
            <SelectTrigger className="h-8 w-24 text-xs">
              <SelectValue placeholder="Page size" />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="10">10 / page</SelectItem>
              <SelectItem value="25">25 / page</SelectItem>
              <SelectItem value="50">50 / page</SelectItem>
            </SelectContent>
          </Select>
        </div>
      </div>

      <div className="overflow-x-auto">
        <table className="w-full min-w-[56rem] border-separate border-spacing-0">
          <thead>
            <tr>
              <th scope="col" className={cn(TH, 'sticky left-0 z-10 w-28 text-left')}>Site ID</th>
              <th scope="col" className={cn(TH, 'text-left')}>Site Name</th>
              <th scope="col" className={cn(TH, 'text-center')}>Circle</th>
              <th scope="col" className={cn(TH, 'text-left')}>OA</th>
              <th scope="col" className={cn(TH, 'text-left')}>Assigned IE</th>
              <th scope="col" className={cn(TH, 'text-center')}>Status</th>
              <th scope="col" className={cn(TH, 'text-right')}>Availability %</th>
              <th scope="col" className={cn(TH, 'text-center')}>NSLA Status</th>
              <th scope="col" className={cn(TH, 'text-center')}>USD Status</th>
              <th scope="col" className={cn(TH, 'text-right')}>Incidents</th>
            </tr>
          </thead>
          <tbody>
            {pagedSites.length === 0 ? (
              <tr>
                <td colSpan={10} className="p-8 text-center text-xs text-muted-foreground">
                  No assigned sites match the search filter.
                </td>
              </tr>
            ) : (
              pagedSites.map((site) => (
                <tr key={site.site_id} className="hover:bg-muted/40 transition-colors">
                  <th scope="row" className={cn(TD, 'sticky left-0 z-10 bg-card font-mono font-medium text-foreground')}>
                    {site.site_id}
                  </th>
                  <td className={cn(TD, 'max-w-48 truncate font-medium text-foreground')} title={site.site_name}>
                    {site.site_name}
                  </td>
                  <td className={cn(TD, 'text-center font-medium text-muted-foreground')}>
                    {site.circle}
                  </td>
                  <td className={cn(TD, 'text-muted-foreground')}>
                    {site.oa_name}
                  </td>
                  <td className={cn(TD, 'font-medium text-foreground')}>
                    {site.ie_name}
                  </td>
                  <td className={cn(TD, 'text-center')}>
                    <span
                      className={cn(
                        'inline-block rounded px-1.5 py-0.5 text-[10px] font-semibold',
                        site.site_status === 'On-Air' && 'bg-emerald-50 text-emerald-800',
                        site.site_status === 'Degraded' && 'bg-amber-50 text-amber-800',
                        site.site_status === 'Critical' && 'bg-rose-50 text-rose-800'
                      )}
                    >
                      {site.site_status}
                    </span>
                  </td>
                  <td className={cn(TD, 'text-right font-medium text-foreground')}>
                    {formatPct(site.availability_pct, 2)}
                  </td>
                  <td className={cn(TD, 'text-center')}>
                    <span
                      className={cn(
                        'inline-block rounded px-1.5 py-0.5 text-[10px] font-medium',
                        site.nsla_status === 'Meeting SLA'
                          ? 'bg-emerald-50 text-emerald-800'
                          : 'bg-rose-50 text-rose-800'
                      )}
                    >
                      {site.nsla_status}
                    </span>
                  </td>
                  <td className={cn(TD, 'text-center')}>
                    <span
                      className={cn(
                        'inline-block rounded px-1.5 py-0.5 text-[10px] font-medium',
                        site.usd_status === 'Normal' ? 'text-muted-foreground' : 'bg-rose-50 text-rose-700'
                      )}
                    >
                      {site.usd_status}
                    </span>
                  </td>
                  <td className={cn(TD, 'text-right')}>
                    {formatNumber(site.incident_count)}
                  </td>
                </tr>
              ))
            )}
          </tbody>
        </table>
      </div>

      {/* Pagination Footer */}
      {totalPages > 1 && (
        <div className="flex items-center justify-between border-t px-4 py-2.5 text-xs text-muted-foreground">
          <span>
            Page {currentPage} of {totalPages} ({formatNumber(filteredSites.length)} total sites)
          </span>
          <div className="flex items-center gap-1">
            <Button
              size="sm"
              variant="outline"
              disabled={currentPage <= 1}
              onClick={() => setPage((p) => Math.max(1, p - 1))}
              className="h-7 px-2"
              aria-label="Previous page"
            >
              <ChevronLeft className="size-3.5" />
            </Button>
            <Button
              size="sm"
              variant="outline"
              disabled={currentPage >= totalPages}
              onClick={() => setPage((p) => Math.min(totalPages, p + 1))}
              className="h-7 px-2"
              aria-label="Next page"
            >
              <ChevronRight className="size-3.5" />
            </Button>
          </div>
        </div>
      )}
    </div>
  );
}

