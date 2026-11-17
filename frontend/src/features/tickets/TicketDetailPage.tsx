import { useEffect, useState } from 'react';
import { Link, useParams } from 'react-router-dom';
import { AlertTriangle, ArrowLeft, RotateCw } from 'lucide-react';
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { closeTicket, fetchTicket, reopenTicket, retryTicketNotification } from '../../services/api';
import type { TicketDetailResponse, TicketNotification } from '../../types/tickets';
import { formatDate, formatDateTime } from '../../lib/format';
import { TicketError, TicketPageFrame } from './TicketPageFrame';

export function TicketDetailPage() {
  const { ticketId } = useParams();
  const id = Number(ticketId);
  const [detail, setDetail] = useState<TicketDetailResponse | null>(null);
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  const [remarks, setRemarks] = useState('');
  const [reason, setReason] = useState('');
  const invalidId = !Number.isInteger(id) || id < 1;

  useEffect(() => {
    if (invalidId) return;
    const controller = new AbortController();
    fetchTicket(id, controller.signal).then((result) => {
      setDetail(result);
      setError('');
    }).catch((cause: unknown) => {
      if (!controller.signal.aborted) setError(cause instanceof Error ? cause.message : 'Ticket details could not be loaded.');
    });
    return () => controller.abort();
  }, [id, invalidId]);

  const reload = async () => {
    setError('');
    try {
      setDetail(await fetchTicket(id));
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : 'Ticket details could not be refreshed.');
    }
  };

  const perform = async (action: () => Promise<unknown>) => {
    setBusy(true);
    setError('');
    try {
      await action();
      await reload();
      setRemarks('');
      setReason('');
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : 'The ticket action could not be completed.');
    } finally {
      setBusy(false);
    }
  };

  const currentDetail = detail?.ticket.id === id ? detail : null;
  const ticket = currentDetail?.ticket;
  const permissions = currentDetail?.permissions ?? { close: false, reopen: false, retry: false };
  return (
    <TicketPageFrame title={ticket ? `Ticket ${ticket.portal_ticket_id}` : 'Ticket Details'} subtitle="Ticket record, status history and individual email delivery">
      {(invalidId || error) && <TicketError message={invalidId ? 'Invalid ticket identifier.' : error} />}
      <Button asChild variant="outline" size="sm"><Link to="/tickets/all"><ArrowLeft />Back to All Tickets</Link></Button>
      {!ticket ? <p className="text-sm text-muted-foreground">Loading ticket details…</p> : (
        <>
          <Card>
            <CardHeader>
              <CardTitle className="flex flex-wrap items-center gap-2 text-base">
                {ticket.site_name || ticket.site_id}
                <Badge variant={ticket.status === 'Open' ? 'outline' : 'secondary'}>{ticket.status}</Badge>
              </CardTitle>
              <CardDescription>{ticket.site_id} · {ticket.circle} · {ticket.project}</CardDescription>
            </CardHeader>
            <CardContent className="grid gap-x-6 gap-y-4 sm:grid-cols-2 lg:grid-cols-3">
              <Field label="Portal Ticket ID" value={ticket.portal_ticket_id} />
              <Field label="Outage date" value={formatDate(ticket.outage_date)} />
              <Field label="Actual Down Time" value={formatDateTime(ticket.actual_down_time)} />
              <Field label="Reporting Time to Partner" value={formatDateTime(ticket.reporting_time_to_partner)} />
              <Field label="Restoration Time" value={formatDateTime(ticket.restoration_time)} />
              <Field label="Outage minutes" value={ticket.outage_minutes ?? '—'} />
              <Field label="MTTR (hours)" value={ticket.mttr_hours ?? '—'} />
              <Field label="OA / BA" value={[ticket.oa, ticket.ba].filter(Boolean).join(' / ') || '—'} />
              <Field label="Vendor / outage bucket" value={[ticket.vendor_name, ticket.outage_bucket].filter(Boolean).join(' / ') || '—'} />
              <Field label="Email recipient" value={ticket.email_id || '—'} />
              <Field label="Created by" value={ticket.created_by || 'system'} />
              <Field label="Created at" value={formatDateTime(ticket.created_at)} />
              <Field label="Last uploaded" value={formatDateTime(ticket.last_uploaded_at)} />
              {ticket.closed_at && <Field label={`Closed (${ticket.closure_source || 'unknown source'})`} value={`${formatDateTime(ticket.closed_at)}${ticket.closed_by ? ` · ${ticket.closed_by}` : ''}`} />}
              {ticket.closure_remarks && <Field label="Closure remarks" value={ticket.closure_remarks} />}
              <div className="sm:col-span-2 lg:col-span-3"><Field label="Detail RCA" value={ticket.detail_rca || '—'} /></div>
            </CardContent>
          </Card>

          {(permissions.close && ticket.status === 'Open') && (
            <Card>
              <CardHeader><CardTitle className="text-sm">Close ticket</CardTitle><CardDescription className="text-xs">Manual closure requires a reason and is added to the audit history.</CardDescription></CardHeader>
              <CardContent className="space-y-3">
                <textarea className="min-h-20 w-full rounded-md border bg-background p-2 text-sm" maxLength={5000} value={remarks} onChange={(event) => setRemarks(event.target.value)} placeholder="Closure remarks" />
                <Button variant="outline" disabled={busy || !remarks.trim()} onClick={() => perform(() => closeTicket(id, remarks))}>Close Ticket</Button>
              </CardContent>
            </Card>
          )}
          {(permissions.reopen && ticket.status === 'Closed') && (
            <Card>
              <CardHeader><CardTitle className="text-sm">Reopen ticket</CardTitle><CardDescription className="text-xs">A reopening reason is required. The notification is sent to this ticket’s recorded recipient.</CardDescription></CardHeader>
              <CardContent className="space-y-3">
                <textarea className="min-h-20 w-full rounded-md border bg-background p-2 text-sm" maxLength={5000} value={reason} onChange={(event) => setReason(event.target.value)} placeholder="Reason for reopening" />
                <Button disabled={busy || !reason.trim()} onClick={() => perform(() => reopenTicket(id, reason))}>Reopen Ticket</Button>
              </CardContent>
            </Card>
          )}

          <Card>
            <CardHeader><CardTitle className="text-sm">Notification history</CardTitle><CardDescription className="text-xs">Each ticket email is sent only to its own Excel row’s Email ID.</CardDescription></CardHeader>
            <CardContent className="space-y-3">
              {ticket.notifications.length ? ticket.notifications.map((notification) => (
                <Notification key={notification.id} notification={notification} canRetry={permissions.retry} busy={busy} onRetry={() => perform(() => retryTicketNotification(notification.id))} />
              )) : <p className="text-sm text-muted-foreground">No notifications have been recorded.</p>}
            </CardContent>
          </Card>

          <Card>
            <CardHeader><CardTitle className="text-sm">Ticket history</CardTitle><CardDescription className="text-xs">Audit events preserve the original Excel values and each status transition.</CardDescription></CardHeader>
            <CardContent className="space-y-3">
              {ticket.events.length ? ticket.events.map((event) => (
                <div key={event.id} className="border-l-2 pl-3">
                  <p className="text-sm font-medium">{event.action.replaceAll('_', ' ')} <span className="font-normal text-muted-foreground">· {event.source.replaceAll('_', ' ')}</span></p>
                  <p className="text-xs text-muted-foreground">{formatDateTime(event.created_at)} · {event.actor || 'system'}{event.status_before || event.status_after ? ` · ${event.status_before || '—'} → ${event.status_after || '—'}` : ''}</p>
                  {event.remarks && <p className="mt-1 whitespace-pre-wrap text-sm">{event.remarks}</p>}
                  {typeof event.changes.source_values === 'object' && event.changes.source_values !== null && (
                    <details className="mt-1 text-xs"><summary className="cursor-pointer text-muted-foreground">Original Excel row values</summary><pre className="mt-2 overflow-auto rounded bg-muted p-2">{JSON.stringify(event.changes.source_values, null, 2)}</pre></details>
                  )}
                </div>
              )) : <p className="text-sm text-muted-foreground">No ticket events have been recorded.</p>}
            </CardContent>
          </Card>
        </>
      )}
    </TicketPageFrame>
  );
}

function Field({ label, value }: { label: string; value: string }) {
  return <div className="min-w-0"><p className="text-xs text-muted-foreground">{label}</p><p className="mt-0.5 whitespace-pre-wrap break-words text-sm">{value}</p></div>;
}

function Notification({ notification, canRetry, busy, onRetry }: {
  notification: TicketNotification;
  canRetry: boolean;
  busy: boolean;
  onRetry: () => void;
}) {
  const accepted = notification.status === 'accepted';
  return (
    <div className="rounded-lg border p-3">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div className="flex flex-wrap items-center gap-2">
          <Badge variant={accepted ? 'secondary' : notification.status === 'failed' ? 'destructive' : 'outline'}>{notification.status}</Badge>
          <span className="text-sm font-medium">{notification.kind.replaceAll('_', ' ')}</span>
          <span className="text-xs text-muted-foreground">to {notification.recipient}</span>
        </div>
        {canRetry && notification.status === 'failed' && <Button variant="outline" size="sm" disabled={busy} onClick={onRetry}><RotateCw />Retry</Button>}
      </div>
      <p className="mt-1 text-xs text-muted-foreground">{formatDateTime(notification.created_at)} · {notification.attempts} attempt(s)</p>
      {notification.error && <Alert variant="destructive" className="mt-2"><AlertTriangle /><AlertTitle>Delivery failed</AlertTitle><AlertDescription>{notification.error}</AlertDescription></Alert>}
      {notification.attempt_log.map((attempt) => (
        <p key={attempt.number} className="mt-2 text-xs text-muted-foreground">
          Attempt {attempt.number} · {attempt.accepted ? `accepted ${formatDateTime(attempt.accepted_at)}` : `failed: ${attempt.detail}`}
        </p>
      ))}
    </div>
  );
}
