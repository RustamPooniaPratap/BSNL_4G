import { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import { Button } from '@/components/ui/button';
import { Card, CardContent } from '@/components/ui/card';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table';
import { fetchTicketOptions, fetchTickets } from '../../services/api';
import type { TicketOptions, TicketPage } from '../../types/tickets';
import { formatDate, formatDateTime, formatNumber } from '../../lib/format';
import { TicketError, TicketPageFrame } from './TicketPageFrame';

export function TicketListPage() {
  const [options, setOptions] = useState<TicketOptions | null>(null);
  const [page, setPage] = useState<TicketPage | null>(null);
  const [error, setError] = useState('');
  const [optionsError, setOptionsError] = useState('');
  const [filters, setFilters] = useState({ q: '', circle: '', status: 'All', vendor_name: '', date_from: '', date_to: '', sort: '-created_at', page_size: '25' });
  const [currentPage, setCurrentPage] = useState(1);

  useEffect(() => {
    const controller = new AbortController();
    fetchTicketOptions(controller.signal).then(setOptions).catch((reason: unknown) => {
      if (!controller.signal.aborted) setOptionsError(reason instanceof Error ? reason.message : 'Ticket filters could not be loaded.');
    });
    return () => controller.abort();
  }, []);

  useEffect(() => {
    const controller = new AbortController();
    const params = new URLSearchParams(Object.entries(filters).filter(([, value]) => value) as [string, string][]);
    params.set('page', String(currentPage));
    fetchTickets(params, controller.signal).then((result) => {
      setPage(result);
      setError('');
    }).catch((reason: unknown) => {
      if (!controller.signal.aborted) setError(reason instanceof Error ? reason.message : 'Tickets could not be loaded.');
    });
    return () => controller.abort();
  }, [filters, currentPage]);

  const update = (key: keyof typeof filters, value: string) => {
    setError('');
    setCurrentPage(1);
    setFilters((current) => ({ ...current, [key]: value }));
  };

  return (
    <TicketPageFrame title="All Tickets" subtitle="Search and review tickets within your assigned project and circle scope">
      {optionsError && <TicketError message={optionsError} />}
      {error && <TicketError message={error} />}
      <Card>
        <CardContent className="grid gap-3 pt-5 sm:grid-cols-2 lg:grid-cols-4">
          <label className="space-y-1 text-xs text-muted-foreground">Search
            <input className="h-8 w-full rounded-md border bg-background px-2 text-sm text-foreground" value={filters.q} placeholder="Ticket ID, Site ID or name" onChange={(event) => update('q', event.target.value)} />
          </label>
          <label className="space-y-1 text-xs text-muted-foreground">Circle
            <select className="h-8 w-full rounded-md border bg-background px-2 text-sm text-foreground" value={filters.circle} onChange={(event) => update('circle', event.target.value)}>
              <option value="">All circles</option>{(options?.circles ?? []).map((circle) => <option key={circle}>{circle}</option>)}
            </select>
          </label>
          <label className="space-y-1 text-xs text-muted-foreground">Status
            <select className="h-8 w-full rounded-md border bg-background px-2 text-sm text-foreground" value={filters.status} onChange={(event) => update('status', event.target.value)}>
              <option value="All">All statuses</option>{(options?.statuses ?? ['Open', 'Closed']).map((status) => <option key={status}>{status}</option>)}
            </select>
          </label>
          <label className="space-y-1 text-xs text-muted-foreground">Vendor
            <select className="h-8 w-full rounded-md border bg-background px-2 text-sm text-foreground" value={filters.vendor_name} onChange={(event) => update('vendor_name', event.target.value)}>
              <option value="">All vendors</option>{(options?.vendors ?? []).map((vendor) => <option key={vendor}>{vendor}</option>)}
            </select>
          </label>
          <label className="space-y-1 text-xs text-muted-foreground">From date
            <input type="date" className="h-8 w-full rounded-md border bg-background px-2 text-sm text-foreground" value={filters.date_from} onChange={(event) => update('date_from', event.target.value)} />
          </label>
          <label className="space-y-1 text-xs text-muted-foreground">To date
            <input type="date" className="h-8 w-full rounded-md border bg-background px-2 text-sm text-foreground" value={filters.date_to} onChange={(event) => update('date_to', event.target.value)} />
          </label>
          <label className="space-y-1 text-xs text-muted-foreground">Sort by
            <select className="h-8 w-full rounded-md border bg-background px-2 text-sm text-foreground" value={filters.sort} onChange={(event) => update('sort', event.target.value)}>
              <option value="-created_at">Newest created</option><option value="created_at">Oldest created</option>
              <option value="-outage_date">Latest outage</option><option value="outage_date">Earliest outage</option>
              <option value="portal_ticket_id">Ticket ID</option><option value="circle">Circle</option><option value="status">Status</option>
            </select>
          </label>
          <label className="space-y-1 text-xs text-muted-foreground">Rows per page
            <select className="h-8 w-full rounded-md border bg-background px-2 text-sm text-foreground" value={filters.page_size} onChange={(event) => update('page_size', event.target.value)}>
              <option value="25">25</option><option value="50">50</option><option value="100">100</option>
            </select>
          </label>
        </CardContent>
      </Card>

      <Card>
        <CardContent className="overflow-x-auto px-0 pt-3">
          <Table className="text-xs">
            <TableHeader><TableRow className="bg-muted/50 hover:bg-muted/50">
              <TableHead>Portal Ticket ID</TableHead><TableHead>Outage date</TableHead><TableHead>Circle</TableHead>
              <TableHead>Site</TableHead><TableHead>Vendor</TableHead><TableHead className="text-right">Outage min.</TableHead>
              <TableHead>Status</TableHead><TableHead>Updated</TableHead>
            </TableRow></TableHeader>
            <TableBody>
              {page?.tickets.length ? page.tickets.map((ticket) => (
                <TableRow key={ticket.id}>
                  <TableCell><Link className="font-medium text-primary underline-offset-4 hover:underline" to={`/tickets/${ticket.id}`}>{ticket.portal_ticket_id}</Link></TableCell>
                  <TableCell>{formatDate(ticket.outage_date)}</TableCell><TableCell>{ticket.circle}</TableCell>
                  <TableCell className="whitespace-normal"><span className="font-medium">{ticket.site_id}</span><span className="block text-muted-foreground">{ticket.site_name}</span></TableCell>
                  <TableCell>{ticket.vendor_name || '—'}</TableCell><TableCell className="text-right tabular-nums">{ticket.outage_minutes ?? '—'}</TableCell>
                  <TableCell><span className={ticket.status === 'Open' ? 'font-medium text-amber-700' : 'font-medium text-emerald-700'}>{ticket.status}</span></TableCell>
                  <TableCell>{formatDateTime(ticket.updated_at)}</TableCell>
                </TableRow>
              )) : <TableRow><TableCell colSpan={8} className="py-8 text-center text-muted-foreground">{error ? 'Unable to display tickets.' : 'No tickets match these filters.'}</TableCell></TableRow>}
            </TableBody>
          </Table>
          <div className="flex flex-wrap items-center justify-between gap-3 px-4 py-3 text-xs text-muted-foreground">
            <span>{formatNumber(page?.total ?? 0)} tickets</span>
            <div className="flex items-center gap-2">
              <span>Page {page?.page ?? 1} of {page?.pages ?? 1}</span>
              <Button variant="outline" size="sm" disabled={!page || page.page <= 1} onClick={() => setCurrentPage((value) => Math.max(1, value - 1))}>Previous</Button>
              <Button variant="outline" size="sm" disabled={!page || page.page >= page.pages} onClick={() => setCurrentPage((value) => value + 1)}>Next</Button>
            </div>
          </div>
        </CardContent>
      </Card>
    </TicketPageFrame>
  );
}
