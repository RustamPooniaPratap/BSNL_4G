import { useCallback, useEffect, useState, type ReactNode } from 'react';
import { Link } from 'react-router-dom';
import { AlertTriangle, Building2, CalendarDays, CheckCircle2, CircleAlert, Layers, Mail, RefreshCw, Search, Send, Ticket, Upload } from 'lucide-react';
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table';
import { fetchTicketDashboard, fetchTicketOptions, fetchTickets } from '../../services/api';
import type { TicketDashboardResponse, TicketListItem, TicketOptions, TicketPage, TicketStatusFilter } from '../../types/tickets';
import { formatDate, formatNumber } from '../../lib/format';
import { CloseTicketSheet } from './CloseTicketSheet';
import { TicketError, TicketPageFrame } from './TicketPageFrame';

const EMPTY: TicketDashboardResponse = {
  kpis: { total: 0, open: 0, closed: 0, created_today: 0, notifications_accepted: 0, notifications_failed: 0 },
  status: [], circles: [], vendors: [], buckets: [], monthly: [],
};
const STATUS_OPTIONS: { value: TicketStatusFilter; label: string }[] = [
  { value: 'Open', label: 'Open' },
  { value: 'Closed', label: 'Closed' },
  { value: 'All', label: 'All Tickets' },
];
const PAGE_SIZE = '25';
const INITIAL_FILTERS = { q: '', status: 'Open' as TicketStatusFilter, circle: '', vendor_name: '', date_from: '', date_to: '' };
type Filters = typeof INITIAL_FILTERS;

const countLabel = (total: number, status: TicketStatusFilter) =>
  `${formatNumber(total)} ${status === 'All' ? '' : `${status.toLowerCase()} `}ticket${total === 1 ? '' : 's'}`;

export function TicketDashboardPage() {
  const [options, setOptions] = useState<TicketOptions | null>(null);
  const [data, setData] = useState<TicketDashboardResponse | null>(null);
  const [page, setPage] = useState<TicketPage | null>(null);
  const [error, setError] = useState('');
  const [tableError, setTableError] = useState('');
  const [optionsError, setOptionsError] = useState('');
  const [notice, setNotice] = useState('');
  const [filters, setFilters] = useState<Filters>(INITIAL_FILTERS);
  const [currentPage, setCurrentPage] = useState(1);
  const [closing, setClosing] = useState<TicketListItem | null>(null);
  const [refresh, setRefresh] = useState(0);

  useEffect(() => {
    const controller = new AbortController();
    fetchTicketOptions(controller.signal).then(setOptions).catch((reason: unknown) => {
      if (!controller.signal.aborted) setOptionsError(reason instanceof Error ? reason.message : 'Ticket filters could not be loaded.');
    });
    return () => controller.abort();
  }, []);

  // KPI cards and breakdowns are overall figures (the user's whole ticket scope): the table filters never apply to them.
  useEffect(() => {
    const controller = new AbortController();
    fetchTicketDashboard(new URLSearchParams(), controller.signal).then((result) => {
      setData(result);
      setError('');
    }).catch((reason: unknown) => {
      if (!controller.signal.aborted) setError(reason instanceof Error ? reason.message : 'Ticket dashboard could not be loaded.');
    });
    return () => controller.abort();
  }, [refresh]);

  // The ticket table is filtered and paginated by the API; every filter is sent together.
  useEffect(() => {
    const controller = new AbortController();
    const params = new URLSearchParams(Object.entries(filters).filter(([, value]) => value) as [string, string][]);
    params.set('page', String(currentPage));
    params.set('page_size', PAGE_SIZE);
    fetchTickets(params, controller.signal).then((result) => {
      setPage(result);
      setTableError('');
    }).catch((reason: unknown) => {
      if (!controller.signal.aborted) setTableError(reason instanceof Error ? reason.message : 'Tickets could not be loaded.');
    });
    return () => controller.abort();
  }, [filters, currentPage, refresh]);

  const update = (key: keyof Filters, value: string) => {
    setTableError('');
    setNotice('');
    setCurrentPage(1);
    setFilters((current) => ({ ...current, [key]: value }));
  };
  const onClosed = useCallback((ticket: TicketListItem) => {
    setClosing(null);
    setNotice(`Ticket ${ticket.portal_ticket_id} was closed.`);
    setRefresh((value) => value + 1);
  }, []);
  const figures = data ?? EMPTY;
  const tickets = page?.tickets ?? [];

  return (
    <TicketPageFrame title="Ticket Dashboard" subtitle="Pending OFC outages, ticket status and notification delivery">
      <header className="flex flex-col gap-4 border-b border-slate-200 pb-4 sm:flex-row sm:items-center sm:justify-between">
        <div>
          <h2 className="flex items-center gap-2 text-2xl font-semibold tracking-tight text-slate-900">
            <Ticket className="size-6 text-primary" aria-hidden="true" />
            Ticket Management
          </h2>
          <p className="mt-1 text-sm text-muted-foreground">Real-time OFC outage ticketing, partner notifications and closure tracking.</p>
        </div>
        <div className="flex shrink-0 gap-2">
          <Button variant="outline" onClick={() => setRefresh((value) => value + 1)}>
            <RefreshCw className="size-4" aria-hidden="true" /> Refresh
          </Button>
          {options?.can_upload && (
            <Button asChild>
              <Link to="/tickets/upload"><Upload className="size-4" aria-hidden="true" /> Upload Excel</Link>
            </Button>
          )}
        </div>
      </header>

      {optionsError && <TicketError message={optionsError} />}
      {error && <TicketError message={error} />}

      <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-3 2xl:grid-cols-6">
        <Metric label="Total Tickets" hint="All logged outage events" value={figures.kpis.total} tone="slate" icon={<Ticket />} />
        <Metric label="Open Tickets" hint="Awaiting resolution remarks" value={figures.kpis.open} tone="amber" icon={<CircleAlert />} />
        <Metric label="Closed Tickets" hint="Resolved with remarks" value={figures.kpis.closed} tone="emerald" icon={<CheckCircle2 />} />
        <Metric label="Created today" hint="New tickets logged today" value={figures.kpis.created_today} tone="violet" icon={<CalendarDays />} />
        <Metric label="Emails Sent" hint="Accepted by the mail server" value={figures.kpis.notifications_accepted} tone="blue" icon={<Send />} />
        <Metric label="Emails Failed" hint="Review delivery history" value={figures.kpis.notifications_failed} tone="rose" icon={<Mail />} />
      </div>

      {figures.kpis.notifications_failed > 0 && (
        <Alert variant="destructive">
          <AlertTriangle />
          <AlertTitle>Some ticket emails need attention</AlertTitle>
          <AlertDescription>{formatNumber(figures.kpis.notifications_failed)} notification(s) failed. Review their delivery history from the ticket details.</AlertDescription>
        </Alert>
      )}

      <Card className="border-slate-200 shadow-sm">
        <CardHeader className="border-b border-slate-100 bg-slate-50/70 py-3">
          <CardTitle className="text-sm font-semibold">Filter tickets</CardTitle>
          <CardDescription className="text-xs">Search and filter the ticket list. Open tickets are shown by default.</CardDescription>
        </CardHeader>
        <CardContent className="grid items-end gap-3 p-4 sm:grid-cols-2 xl:grid-cols-12">
          <label className="space-y-1.5 text-xs font-medium text-slate-600 sm:col-span-2 xl:col-span-3">Search
            <span className="relative block">
              <Search className="pointer-events-none absolute left-3 top-1/2 size-4 -translate-y-1/2 text-slate-400" aria-hidden="true" />
              <input className="h-10 w-full rounded-lg border border-slate-200 bg-white pl-9 pr-3 text-sm text-foreground shadow-sm outline-none transition focus:border-sky-400 focus:ring-2 focus:ring-sky-100" value={filters.q} placeholder="Ticket ID, Site ID or Site Name" onChange={(event) => update('q', event.target.value)} />
            </span>
          </label>
          <label className="space-y-1.5 text-xs font-medium text-slate-600 xl:col-span-2">Status
            <select className="h-10 w-full rounded-lg border border-slate-200 bg-white px-3 text-sm text-foreground shadow-sm outline-none transition focus:border-sky-400 focus:ring-2 focus:ring-sky-100" value={filters.status} onChange={(event) => update('status', event.target.value)}>
              {STATUS_OPTIONS.map((option) => <option key={option.value} value={option.value}>{option.label}</option>)}
            </select>
          </label>
          <label className="space-y-1.5 text-xs font-medium text-slate-600 xl:col-span-2">Circle
            <select className="h-10 w-full rounded-lg border border-slate-200 bg-white px-3 text-sm text-foreground shadow-sm outline-none transition focus:border-sky-400 focus:ring-2 focus:ring-sky-100" value={filters.circle} onChange={(event) => update('circle', event.target.value)}>
              <option value="">All circles</option>
              {(options?.circles ?? []).map((circle) => <option key={circle}>{circle}</option>)}
            </select>
          </label>
          <label className="space-y-1.5 text-xs font-medium text-slate-600 xl:col-span-2">Vendor
            <select className="h-10 w-full rounded-lg border border-slate-200 bg-white px-3 text-sm text-foreground shadow-sm outline-none transition focus:border-sky-400 focus:ring-2 focus:ring-sky-100" value={filters.vendor_name} onChange={(event) => update('vendor_name', event.target.value)}>
              <option value="">All vendors</option>
              {(options?.vendors ?? []).map((vendor) => <option key={vendor}>{vendor}</option>)}
            </select>
          </label>
          <div className="grid grid-cols-2 gap-3 sm:col-span-2 xl:col-span-3">
            <label className="space-y-1.5 text-xs font-medium text-slate-600">From date
              <input type="date" className="h-10 w-full min-w-0 rounded-lg border border-slate-200 bg-white px-2 text-sm text-foreground shadow-sm outline-none transition focus:border-sky-400 focus:ring-2 focus:ring-sky-100" value={filters.date_from} onChange={(event) => update('date_from', event.target.value)} />
            </label>
            <label className="space-y-1.5 text-xs font-medium text-slate-600">To date
              <input type="date" className="h-10 w-full min-w-0 rounded-lg border border-slate-200 bg-white px-2 text-sm text-foreground shadow-sm outline-none transition focus:border-sky-400 focus:ring-2 focus:ring-sky-100" value={filters.date_to} onChange={(event) => update('date_to', event.target.value)} />
            </label>
          </div>
        </CardContent>
        <CardContent className="flex flex-wrap items-center justify-between gap-2 border-t border-slate-100 bg-slate-50/50 px-4 py-2.5 text-xs text-muted-foreground">
          <span data-testid="ticket-count">{page ? countLabel(page.total, filters.status) : 'Loading tickets…'}</span>
          <span>{formatNumber(tickets.length)} shown on this page</span>
        </CardContent>
      </Card>

      <Card className="overflow-hidden border-slate-200 shadow-sm">
        <div className="flex flex-wrap items-center justify-between gap-2 border-b border-slate-100 px-4 py-3">
          <div>
            <h3 className="text-sm font-semibold text-slate-900">Ticket register</h3>
            <p className="mt-0.5 text-xs text-muted-foreground">View outage details or close eligible open tickets.</p>
          </div>
          <Badge variant="outline" className="border-slate-200 bg-slate-50 text-slate-600">{page ? countLabel(page.total, filters.status) : 'Loading…'}</Badge>
        </div>
        <CardContent className="overflow-x-auto px-0 pt-0">
          {tableError && <div className="px-4 pb-3"><TicketError message={tableError} /></div>}
          {notice && <p role="status" className="px-4 pb-3 text-sm text-emerald-700">{notice}</p>}
          <Table aria-label="Ticket register" className="min-w-[900px] text-sm">
            <TableHeader><TableRow className="bg-slate-50/90 hover:bg-slate-50/90">
              <TableHead className="h-11 text-[11px] font-semibold uppercase tracking-wide text-slate-500">Ticket ID</TableHead>
              <TableHead className="h-11 text-[11px] font-semibold uppercase tracking-wide text-slate-500">Outage date</TableHead>
              <TableHead className="h-11 text-[11px] font-semibold uppercase tracking-wide text-slate-500">Circle</TableHead>
              <TableHead className="h-11 text-[11px] font-semibold uppercase tracking-wide text-slate-500">Site</TableHead>
              <TableHead className="h-11 text-[11px] font-semibold uppercase tracking-wide text-slate-500">Vendor</TableHead>
              <TableHead className="h-11 text-right text-[11px] font-semibold uppercase tracking-wide text-slate-500">Outage min.</TableHead>
              <TableHead className="h-11 text-[11px] font-semibold uppercase tracking-wide text-slate-500">Status</TableHead>
              <TableHead className="h-11 text-right text-[11px] font-semibold uppercase tracking-wide text-slate-500">Actions</TableHead>
            </TableRow></TableHeader>
            <TableBody>
              {tickets.length ? tickets.map((ticket) => (
                <TableRow key={ticket.id} className="transition-colors hover:bg-sky-50/50">
                  <TableCell className="py-3"><Link className="font-semibold text-primary underline-offset-4 hover:underline" to={`/tickets/${ticket.id}`}>{ticket.portal_ticket_id}</Link></TableCell>
                  <TableCell className="whitespace-nowrap py-3 text-slate-600">{formatDate(ticket.outage_date)}</TableCell>
                  <TableCell className="py-3"><Badge variant="outline" className="border-slate-200 bg-white text-slate-700">{ticket.circle}</Badge></TableCell>
                  <TableCell className="whitespace-normal py-3"><span className="font-medium text-slate-800">{ticket.site_id}</span><span className="block text-xs text-muted-foreground">{ticket.site_name}</span></TableCell>
                  <TableCell className="py-3 text-slate-600">{ticket.vendor_name || '—'}</TableCell>
                  <TableCell className="py-3 text-right font-medium tabular-nums text-slate-700">{ticket.outage_minutes ?? '—'}</TableCell>
                  <TableCell className="py-3">
                    <Badge variant="outline" className={ticket.status === 'Open'
                      ? 'border-amber-200 bg-amber-50 text-amber-800'
                      : 'border-emerald-200 bg-emerald-50 text-emerald-800'}>
                      {ticket.status === 'Open' ? <CircleAlert aria-hidden="true" /> : <CheckCircle2 aria-hidden="true" />}
                      {ticket.status}
                    </Badge>
                  </TableCell>
                  <TableCell className="text-right">
                    <div className="flex justify-end gap-2">
                      <Button asChild variant="ghost" size="sm"><Link to={`/tickets/${ticket.id}`} aria-label={`View ${ticket.portal_ticket_id}`}>View</Link></Button>
                      {ticket.status === 'Open' && ticket.can_close && (
                        <Button variant="outline" size="sm" aria-label={`Close ${ticket.portal_ticket_id}`} onClick={() => { setNotice(''); setClosing(ticket); }}>Close</Button>
                      )}
                    </div>
                  </TableCell>
                </TableRow>
              )) : <TableRow><TableCell colSpan={8} className="py-12 text-center">
                <div className="flex flex-col items-center gap-2 text-muted-foreground">
                  <span className="flex size-11 items-center justify-center rounded-full bg-slate-100 text-slate-400"><Ticket className="size-5" aria-hidden="true" /></span>
                  <span className="font-medium text-slate-600">{tableError ? 'Unable to display tickets.' : page ? 'No tickets match these filters.' : 'Loading tickets…'}</span>
                  {page && !tableError && <span className="text-xs">Try widening the date range or clearing a filter.</span>}
                </div>
              </TableCell></TableRow>}
            </TableBody>
          </Table>
          <div className="flex flex-wrap items-center justify-between gap-3 border-t border-slate-100 bg-slate-50/50 px-4 py-3 text-xs text-muted-foreground">
            <span>{page ? `Showing ${formatNumber((page.page - 1) * page.page_size + 1)}–${formatNumber(Math.min(page.page * page.page_size, page.total))} of ${formatNumber(page.total)}` : '—'}</span>
            <div className="flex items-center gap-2">
              <span className="mr-1">Page {page?.page ?? 1} of {page?.pages ?? 1}</span>
              <Button variant="outline" size="sm" disabled={!page || page.page <= 1} onClick={() => setCurrentPage((value) => Math.max(1, value - 1))}>Previous</Button>
              <Button variant="outline" size="sm" disabled={!page || page.page >= page.pages} onClick={() => setCurrentPage((value) => value + 1)}>Next</Button>
            </div>
          </div>
        </CardContent>
      </Card>

      <div className="grid gap-3 lg:grid-cols-2">
        <Breakdown title="All tickets by circle" icon={<Building2 />} accent="bg-sky-500" rows={figures.circles.map((row) => [row.circle, row.count])} />
        <Breakdown title="All tickets by vendor" icon={<Layers />} accent="bg-violet-500" rows={figures.vendors.map((row) => [row.vendor_name || 'Not specified', row.count])} />
        <Breakdown title="All tickets by outage bucket" icon={<Ticket />} accent="bg-amber-500" rows={figures.buckets.map((row) => [row.outage_bucket || 'Not specified', row.count])} />
        <Breakdown title="All tickets by month" icon={<CalendarDays />} accent="bg-emerald-500" rows={figures.monthly.map((row) => [row.month, row.count])} />
      </div>

      <CloseTicketSheet ticket={closing} onCancel={() => setClosing(null)} onClosed={onClosed} />
    </TicketPageFrame>
  );
}

const metricTones = {
  slate: { border: 'border-l-slate-400', label: 'text-slate-500', value: 'text-slate-900', icon: 'bg-slate-100 text-slate-600' },
  amber: { border: 'border-l-amber-500', label: 'text-amber-700', value: 'text-amber-700', icon: 'bg-amber-100 text-amber-700' },
  emerald: { border: 'border-l-emerald-500', label: 'text-emerald-700', value: 'text-emerald-700', icon: 'bg-emerald-100 text-emerald-700' },
  violet: { border: 'border-l-violet-500', label: 'text-violet-700', value: 'text-violet-700', icon: 'bg-violet-100 text-violet-700' },
  blue: { border: 'border-l-blue-500', label: 'text-blue-700', value: 'text-blue-700', icon: 'bg-blue-100 text-blue-700' },
  rose: { border: 'border-l-rose-500', label: 'text-rose-700', value: 'text-rose-700', icon: 'bg-rose-100 text-rose-700' },
};

function Metric({ label, value, icon, hint, tone }: {
  label: string; value: number; icon: ReactNode; hint: string; tone: keyof typeof metricTones;
}) {
  const colors = metricTones[tone];
  return (
    <Card className={`border border-slate-200 border-l-4 ${colors.border} bg-gradient-to-br from-white to-slate-50/70 shadow-sm transition duration-200 hover:-translate-y-0.5 hover:shadow-md`}>
      <CardContent className="flex min-h-[126px] items-start justify-between gap-3 px-4 py-4">
        <div>
          <p className={`text-[11px] font-semibold uppercase tracking-[0.08em] ${colors.label}`}>{label}</p>
          <p className={`mt-2 text-3xl font-semibold leading-none tabular-nums ${colors.value}`} data-testid={`kpi-${label}`}>{formatNumber(value)}</p>
          <p className="mt-2 text-[11px] leading-4 text-muted-foreground">{hint}</p>
        </div>
        <span className={`flex size-9 shrink-0 items-center justify-center rounded-xl ${colors.icon}`}>{icon}</span>
      </CardContent>
    </Card>
  );
}

function Breakdown({ title, rows, icon, accent }: { title: string; rows: [string, number][]; icon: ReactNode; accent: string }) {
  const max = Math.max(0, ...rows.map(([, count]) => count));
  return (
    <Card className="border-slate-200 shadow-sm">
      <CardHeader className="border-b border-slate-100 bg-slate-50/60 py-3">
        <div className="flex items-center gap-2.5">
          <span className={`flex size-8 items-center justify-center rounded-lg bg-white text-slate-600 shadow-sm ring-1 ring-slate-200 [&>svg]:size-4`}>{icon}</span>
          <CardTitle className="text-sm font-semibold">{title}</CardTitle>
        </div>
      </CardHeader>
      <CardContent className="pt-3">
        {rows.length ? (
          <ul className="space-y-3 text-sm">
            {rows.map(([label, count]) => (
              <li key={label} className="space-y-1.5">
                <div className="flex items-center justify-between gap-3">
                  <span className="truncate text-slate-700">{label}</span>
                  <span className="min-w-9 rounded-md bg-slate-100 px-2 py-0.5 text-center text-xs font-semibold tabular-nums text-slate-700">{formatNumber(count)}</span>
                </div>
                <div className="h-1.5 overflow-hidden rounded-full bg-slate-100">
                  <div className={`h-full rounded-full ${accent}`} style={{ width: max ? `${(count / max) * 100}%` : '0%' }} />
                </div>
              </li>
            ))}
          </ul>
        ) : <div className="flex min-h-20 flex-col items-center justify-center gap-1 text-center text-sm text-muted-foreground">
          <span className="flex size-8 items-center justify-center rounded-full bg-slate-100 text-slate-400">{icon}</span>
          <span>No ticket data yet.</span>
        </div>}
      </CardContent>
    </Card>
  );
}
