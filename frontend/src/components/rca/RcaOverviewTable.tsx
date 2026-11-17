import { useState } from 'react';
import { Building2, ChevronLeft, ChevronRight, CircleHelp, Clock, Network, Search, ShieldCheck } from 'lucide-react';
import { Card } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Skeleton } from '@/components/ui/skeleton';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table';
import { cn } from '@/lib/utils';
import { formatMin } from '../../lib/rca';
import { formatNumber } from '../../lib/format';
import { useApiQuery } from '../../hooks/useApiQuery';
import { usePopulation } from '../../context/population';
import { useRcaBucketMappingRevision } from '../../lib/rcaBucketMapping';
import { fetchRcaOverview } from '../../services/api';
import type { RcaOverviewResponse, RcaOverviewRow, RcaOverviewSplit } from '../../types/rca';
import { RcaKpiTile, RcaSection } from './RcaTiles';

const TABS = [
  { id: 'circle', label: 'Circle-wise', entityHeader: 'Circle' },
  { id: 'ci', label: 'CI-wise', entityHeader: 'Cluster Incharge (CI)' },
  { id: 'ie', label: 'IE-wise', entityHeader: 'Individual Equipment (IE)' },
  { id: 'site', label: 'Site-wise', entityHeader: 'Site ID & Name' },
] as const;

type TabId = (typeof TABS)[number]['id'];

interface Props {
  query: URLSearchParams;
}

export function RcaOverviewTable({ query }: Props) {
  const [tab, setTab] = useState<TabId>('circle');
  const [page, setPage] = useState(1);
  const [search, setSearch] = useState('');

  // Combine parent query with tab, page, and search
  const tabQuery = new URLSearchParams(query);
  tabQuery.set('tab', tab);
  if (tab === 'ie' || tab === 'site') {
    tabQuery.set('page', String(page));
    tabQuery.set('page_size', '25');
  }
  if (search.trim()) {
    tabQuery.set('q', search.trim());
  }

  const { scope } = usePopulation();
  const mappingRevision = useRcaBucketMappingRevision();
  const overview = useApiQuery<RcaOverviewResponse>(
    `rca-overview-${scope}-${tab}-${page}-${search}-${tabQuery}-${mappingRevision}`,
    (signal) => fetchRcaOverview(tabQuery, scope, signal)
  );

  const data = overview.data;
  const currentTabDef = TABS.find((t) => t.id === tab)!;

  const handleTabChange = (newTab: TabId) => {
    setTab(newTab);
    setPage(1);
    setSearch('');
  };

  return (
    <div className="space-y-4">
      {/* Responsibility KPIs use the current Final Bucket mapping. */}
      {data ? (
        <RcaSection heading="Responsibility KPIs" label="RCA responsibility KPIs" columns={5}>
          <RcaKpiTile
            label="Own"
            definition="Outage records whose current Final Bucket mapping is Own"
            icon={ShieldCheck}
            tint="sky"
            value={formatMin(data.kpis.own.outage_minutes)}
            context={`${formatNumber(data.kpis.own.records)} incidents · ${data.kpis.own.share_pct}% share`}
          />
          <RcaKpiTile
            label="Customer"
            definition="Outage records whose current Final Bucket mapping is Customer"
            icon={Building2}
            tint="amber"
            value={formatMin(data.kpis.customer.outage_minutes)}
            context={`${formatNumber(data.kpis.customer.records)} incidents · ${data.kpis.customer.share_pct}% share`}
          />
          <RcaKpiTile
            label="Third Party"
            definition="Outage records whose current Final Bucket mapping is Third Party"
            icon={Network}
            tint="teal"
            value={formatMin(data.kpis.third_party.outage_minutes)}
            context={`${formatNumber(data.kpis.third_party.records)} incidents · ${data.kpis.third_party.share_pct}% share`}
          />
          <RcaKpiTile
            label="Pending"
            definition="Outage records whose current mapping is explicitly Pending"
            icon={Clock}
            tint="violet"
            value={formatMin(data.kpis.pending.outage_minutes)}
            context={`${formatNumber(data.kpis.pending.records)} incidents · ${data.kpis.pending.share_pct}% share`}
          />
          <RcaKpiTile
            label="Unclassified"
            definition="Blank, unapproved, or unmapped Final Buckets"
            icon={CircleHelp}
            tint="slate"
            value={formatMin(data.kpis.unclassified.outage_minutes)}
            context={`${formatNumber(data.kpis.unclassified.records)} incidents · ${data.kpis.unclassified.share_pct}% share`}
          />
        </RcaSection>
      ) : (
        <div className="grid grid-cols-1 gap-2.5 md:grid-cols-2 xl:grid-cols-5">
          <Skeleton className="h-24 w-full" />
          <Skeleton className="h-24 w-full" />
          <Skeleton className="h-24 w-full" />
          <Skeleton className="h-24 w-full" />
          <Skeleton className="h-24 w-full" />
        </div>
      )}

      {/* 4 Tabs and Table Card */}
      <Card className="gap-0 overflow-hidden rounded-xl border p-0 shadow-xs">
        {/* Navigation Tabs Header */}
        <div className="flex flex-wrap items-center justify-between border-b bg-muted/30 px-4 py-2.5">
          <nav aria-label="RCA breakdown tabs" className="flex flex-wrap gap-1.5">
            {TABS.map((t) => (
              <button
                key={t.id}
                type="button"
                onClick={() => handleTabChange(t.id)}
                className={cn(
                  'rounded-lg px-3.5 py-1.5 text-xs font-semibold transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring',
                  tab === t.id
                    ? 'bg-primary text-primary-foreground shadow-xs'
                    : 'text-muted-foreground hover:bg-muted hover:text-foreground'
                )}
              >
                {t.label}
              </button>
            ))}
          </nav>

          {/* Search filter for paginated tabs */}
          {(tab === 'ie' || tab === 'site' || tab === 'ci') && (
            <div className="relative mt-2 sm:mt-0">
              <Search className="absolute left-2.5 top-2.5 size-3.5 text-muted-foreground" />
              <Input
                type="search"
                placeholder={`Search ${currentTabDef.label}...`}
                value={search}
                onChange={(e) => {
                  setSearch(e.target.value);
                  setPage(1);
                }}
                className="h-8 w-56 pl-8 text-xs bg-background"
              />
            </div>
          )}
        </div>

        {/* Table Content */}
        {!data && overview.loading ? (
          <div className="p-8">
            <Skeleton className="h-64 w-full" />
          </div>
        ) : !data || data.rows.length === 0 ? (
          <div className="px-4 py-12 text-center text-sm text-muted-foreground">
            No records match the current filters.
          </div>
        ) : (
          <div className="overflow-x-auto">
            <Table className="text-xs">
              <TableHeader>
                <TableRow className="border-b bg-muted/40 hover:bg-muted/40">
                  <TableHead className="min-w-40 font-semibold text-foreground">
                    {currentTabDef.entityHeader}
                  </TableHead>
                  <TableHead className="text-right font-semibold text-foreground">Site Count</TableHead>
                  <TableHead className="text-right font-semibold text-foreground">O&M Start Sites</TableHead>
                  <TableHead className="text-right font-semibold text-foreground">Uptime %</TableHead>
                  <TableHead className="text-center font-semibold text-foreground">Target</TableHead>
                  <TableHead className="text-right font-semibold text-foreground">Gap</TableHead>
                  <TableHead className="text-right font-semibold text-foreground">Outage Min</TableHead>
                  <TableHead className="text-center font-semibold text-foreground">Status</TableHead>
                  <TableHead className="min-w-48 text-center font-semibold text-foreground">Split</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {/* Total Row */}
                {data.total_row && (
                  <TableRow className="border-b-2 bg-muted/60 font-semibold hover:bg-muted/70">
                    <TableCell className="font-bold text-foreground">
                      {data.total_row.name}
                      <span className="block text-[10px] font-normal text-muted-foreground">
                        {data.total_row.detail}
                      </span>
                    </TableCell>
                    <TableCell className="text-right tabular-nums">{formatNumber(data.total_row.site_count)}</TableCell>
                    <TableCell className="text-right tabular-nums">{formatNumber(data.total_row.om_start_sites)}</TableCell>
                    <TableCell className="text-right tabular-nums">{formatUptime(data.total_row.uptime_pct)}</TableCell>
                    <TableCell className="text-center font-medium tabular-nums text-muted-foreground">{data.total_row.target}</TableCell>
                    <TableCell className="text-right tabular-nums">{renderGap(data.total_row.gap)}</TableCell>
                    <TableCell className="text-right tabular-nums">{formatNumber(data.total_row.outage_min)}</TableCell>
                    <TableCell className="text-center">{renderStatus(data.total_row.status)}</TableCell>
                    <TableCell><SplitBar split={data.total_row.split} /></TableCell>
                  </TableRow>
                )}

                {/* Data Rows */}
                {data.rows.map((row) => (
                  <TableRow key={row.id} className="hover:bg-muted/30">
                    <TableCell className="font-medium">
                      <span className="text-foreground">{row.name}</span>
                      {row.detail && (
                        <span className="block text-[10px] text-muted-foreground">{row.detail}</span>
                      )}
                    </TableCell>
                    <TableCell className="text-right tabular-nums">{formatNumber(row.site_count)}</TableCell>
                    <TableCell className="text-right tabular-nums">{formatNumber(row.om_start_sites)}</TableCell>
                    <TableCell className="text-right tabular-nums font-medium">{formatUptime(row.uptime_pct)}</TableCell>
                    <TableCell className="text-center tabular-nums text-muted-foreground">{row.target}</TableCell>
                    <TableCell className="text-right tabular-nums">{renderGap(row.gap)}</TableCell>
                    <TableCell className="text-right tabular-nums">{formatNumber(row.outage_min)}</TableCell>
                    <TableCell className="text-center">{renderStatus(row.status)}</TableCell>
                    <TableCell><SplitBar split={row.split} /></TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </div>
        )}

        {/* Pagination Bar for Paginated Views */}
        {data && data.pages > 1 && (
          <div className="flex items-center justify-between border-t bg-muted/20 px-4 py-2.5 text-xs text-muted-foreground">
            <div>
              Showing {formatNumber((page - 1) * data.page_size + 1)}–{formatNumber(Math.min(page * data.page_size, data.count))} of {formatNumber(data.count)} items
            </div>
            <div className="flex items-center gap-2">
              <Button
                variant="outline"
                size="sm"
                disabled={page <= 1}
                onClick={() => setPage((p) => Math.max(p - 1, 1))}
                className="h-7 px-2.5 text-xs"
              >
                <ChevronLeft className="mr-1 size-3.5" /> Previous
              </Button>
              <span className="font-medium">
                Page {page} of {data.pages}
              </span>
              <Button
                variant="outline"
                size="sm"
                disabled={page >= data.pages}
                onClick={() => setPage((p) => Math.min(p + 1, data.pages))}
                className="h-7 px-2.5 text-xs"
              >
                Next <ChevronRight className="ml-1 size-3.5" />
              </Button>
            </div>
          </div>
        )}
      </Card>
    </div>
  );
}

function formatUptime(uptime: number | null | undefined): string {
  if (uptime === null || uptime === undefined || Number.isNaN(uptime)) return 'N/A';
  return `${uptime.toFixed(2)}%`;
}

function renderGap(gap: number | null | undefined) {
  if (gap === null || gap === undefined || Number.isNaN(gap)) {
    return <span className="text-muted-foreground">—</span>;
  }
  if (gap > 0) {
    return <span className="font-semibold text-emerald-600">+{gap.toFixed(2)}%</span>;
  }
  if (gap === 0) {
    return <span className="font-medium text-foreground">0.00%</span>;
  }
  return <span className="font-semibold text-rose-600">{gap.toFixed(2)}%</span>;
}

function renderStatus(status: RcaOverviewRow['status']) {
  if (status === 'Meeting SLA') {
    return (
      <span className="inline-flex items-center rounded-full border border-emerald-200 bg-emerald-50 px-2 py-0.5 text-[11px] font-semibold text-emerald-800">
        Meeting SLA
      </span>
    );
  }
  if (status === 'Not Meeting SLA') {
    return (
      <span className="inline-flex items-center rounded-full border border-rose-200 bg-rose-50 px-2 py-0.5 text-[11px] font-semibold text-rose-800">
        Not Meeting SLA
      </span>
    );
  }
  return (
    <span className="inline-flex items-center rounded-full border border-muted bg-muted/60 px-2 py-0.5 text-[11px] font-medium text-muted-foreground">
      N/A
    </span>
  );
}

function SplitBar({ split }: { split: RcaOverviewSplit | null }) {
  if (!split) {
    return <span className="text-center text-muted-foreground block">—</span>;
  }

  const { own, customer, third_party, pending, unclassified } = split;
  const tooltipText = `Own: ${own}% (${formatNumber(split.own_min ?? 0)} min)\nCustomer: ${customer}% (${formatNumber(split.customer_min ?? 0)} min)\nThird Party: ${third_party}% (${formatNumber(split.third_party_min ?? 0)} min)\nPending: ${pending}% (${formatNumber(split.pending_min ?? 0)} min)\nUnclassified: ${unclassified}% (${formatNumber(split.unclassified_min ?? 0)} min)`;

  return (
    <div className="space-y-1 cursor-help" title={tooltipText}>
      {/* Multi-segment attribution bar */}
      <div className="flex h-2.5 w-full overflow-hidden rounded-full bg-muted/50 border border-black/5">
        {own > 0 && (
          <div style={{ width: `${own}%` }} className="bg-sky-500 transition-all" />
        )}
        {customer > 0 && (
          <div style={{ width: `${customer}%` }} className="bg-amber-500 transition-all" />
        )}
        {third_party > 0 && (
          <div style={{ width: `${third_party}%` }} className="bg-teal-500 transition-all" />
        )}
        {pending > 0 && (
          <div style={{ width: `${pending}%` }} className="bg-violet-400 transition-all" />
        )}
        {unclassified > 0 && (
          <div style={{ width: `${unclassified}%` }} className="bg-slate-400 transition-all" />
        )}
      </div>

      {/* Compact inline percentage summary */}
      <div className="flex items-center justify-between text-[10px] text-muted-foreground tabular-nums">
        <span className="text-sky-600 font-medium">O:{Math.round(own)}%</span>
        <span className="text-amber-600 font-medium">C:{Math.round(customer)}%</span>
        <span className="text-teal-600 font-medium">3P:{Math.round(third_party)}%</span>
        <span className="text-violet-600 font-medium">P:{Math.round(pending)}%</span>
        <span className="text-slate-600 font-medium">U:{Math.round(unclassified)}%</span>
      </div>
    </div>
  );
}
