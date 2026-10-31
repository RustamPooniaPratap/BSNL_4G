import { useState } from 'react';
import { Loader2, RefreshCw, RotateCcw, Send } from 'lucide-react';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card } from '@/components/ui/card';
import { Input } from '@/components/ui/input';
import { Sheet, SheetContent, SheetDescription, SheetHeader, SheetTitle } from '@/components/ui/sheet';
import { Skeleton } from '@/components/ui/skeleton';
import { cn } from '@/lib/utils';
import { Field, SelectField } from '../../components/data/DataEntry';
import { PageHeading } from '../../context/pageHeader';
import { useApiQuery } from '../../hooks/useApiQuery';
import { formatDateTime } from '../../lib/format';
import { fetchAlertAutomations, fetchAlertHistory, fetchAlertMessage, resendAlertMessage, retryAlertMessage } from '../../services/api';
import type { AlertMessage } from '../../types/alerts';
import { WorkerStatus } from './AlertParts';

const STATUSES = [
  { value: 'queued', label: 'Queued' }, { value: 'processing', label: 'Processing' },
  { value: 'accepted', label: 'Accepted by SMTP' }, { value: 'failed', label: 'Failed' },
];
const TONE: Record<AlertMessage['status'], string> = {
  queued: 'border-slate-300 text-slate-700', processing: 'border-sky-300 text-sky-800',
  accepted: 'border-emerald-300 text-emerald-800', failed: 'border-destructive/40 text-destructive',
};
type Filters = { date_from: string; date_to: string; automation: string; status: string; recipient: string };
const NONE: Filters = { date_from: '', date_to: '', automation: '', status: '', recipient: '' };

function StatusBadge({ m }: { m: Pick<AlertMessage, 'status' | 'status_label'> }) {
  return <Badge variant="outline" className={TONE[m.status]}>{m.status_label}</Badge>;
}

/**
 * Alert › Email History: every email the module prepared, with its SMTP result. "Accepted by SMTP" means the mail
 * server took the message; the portal cannot know whether it reached the mailbox.
 */
export function AlertHistoryPage() {
  const [filters, setFilters] = useState<Filters>(NONE);
  const [page, setPage] = useState(1);
  const [version, setVersion] = useState(0);
  const [open, setOpen] = useState<number | null>(null);
  const params = new URLSearchParams(Object.entries({ ...filters, page: String(page) }).filter(([, v]) => v));
  const history = useApiQuery(`alert-history-${params}-${version}`, (signal) => fetchAlertHistory(params, signal));
  const autos = useApiQuery('alert-automations', fetchAlertAutomations);
  const set = (k: keyof Filters, v: string) => { setFilters((f) => ({ ...f, [k]: v })); setPage(1); };
  const h = history.data;
  return (
    <div className="space-y-4">
      <PageHeading title="Email History" subtitle="Every email sent by an automation, a test or a resend, with the mail server's response." />
      {h && <WorkerStatus worker={h.worker} />}
      <Card className="gap-3 px-4 py-3">
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-5">
          <Field id="h-from" label="From date"><Input id="h-from" type="date" value={filters.date_from} onChange={(e) => set('date_from', e.target.value)} /></Field>
          <Field id="h-to" label="To date"><Input id="h-to" type="date" value={filters.date_to} onChange={(e) => set('date_to', e.target.value)} /></Field>
          <Field id="h-auto" label="Automation">
            <SelectField id="h-auto" value={filters.automation || '__all'} placeholder="All automations" onChange={(v) => set('automation', v === '__all' ? '' : v)}
              options={[{ value: '__all', label: 'All automations' }, ...(autos.data?.automations ?? []).map((a) => ({ value: String(a.id), label: a.name }))]} />
          </Field>
          <Field id="h-status" label="Status">
            <SelectField id="h-status" value={filters.status || '__all'} placeholder="All statuses" onChange={(v) => set('status', v === '__all' ? '' : v)}
              options={[{ value: '__all', label: 'All statuses' }, ...STATUSES]} />
          </Field>
          <Field id="h-recipient" label="Recipient">
            <Input id="h-recipient" key={`r-${version}`} defaultValue={filters.recipient} placeholder="name@example.com"
              onBlur={(e) => set('recipient', e.target.value.trim())} onKeyDown={(e) => { if (e.key === 'Enter') set('recipient', e.currentTarget.value.trim()); }} />
          </Field>
        </div>
        <div className="flex gap-2">
          <Button size="sm" variant="outline" onClick={() => { setFilters(NONE); setPage(1); setVersion((v) => v + 1); }}>Reset</Button>
          <Button size="sm" variant="ghost" onClick={() => setVersion((v) => v + 1)}><RefreshCw /> Refresh</Button>
        </div>
      </Card>
      {history.error && <p role="alert" className="text-sm text-destructive">{history.error.message}</p>}
      {h && h.queued_runs > 0 && <p className="text-xs text-muted-foreground" role="status">{h.queued_runs} run(s) waiting for the worker.</p>}
      <Card className="gap-0 overflow-x-auto p-0">
        <table className="w-full text-sm">
          <thead className="bg-muted/50 text-left text-xs text-muted-foreground">
            <tr><th className="px-3 py-2">Created</th><th className="px-3 py-2">Automation</th><th className="px-3 py-2">Recipients</th>
              <th className="px-3 py-2">Subject</th><th className="px-3 py-2">Attachments</th><th className="px-3 py-2">Status</th><th className="px-3 py-2">Attempts</th></tr>
          </thead>
          <tbody>
            {!h && history.loading && <tr><td colSpan={7} className="p-3"><Skeleton className="h-24" /></td></tr>}
            {h && !h.messages.length && <tr><td colSpan={7} className="px-3 py-6 text-center text-muted-foreground">No email matches these filters.</td></tr>}
            {h?.messages.map((m) => (
              <tr key={m.id} className="cursor-pointer border-t hover:bg-muted/40" onClick={() => setOpen(m.id)}>
                <td className="px-3 py-2 whitespace-nowrap">{formatDateTime(m.created_at)}</td>
                <td className="px-3 py-2">{m.automation}{m.resend_of ? <span className="text-xs text-muted-foreground"> (resend)</span> : ''}</td>
                <td className="max-w-56 truncate px-3 py-2" title={m.to.join(', ')}>{m.to.join(', ')}{m.cc.length ? ` +${m.cc.length} CC` : ''}</td>
                <td className="max-w-72 truncate px-3 py-2"><button type="button" className="text-left hover:underline" onClick={() => setOpen(m.id)}>{m.subject}</button></td>
                <td className="px-3 py-2">{m.attachments.length}</td>
                <td className="px-3 py-2"><StatusBadge m={m} /></td>
                <td className="px-3 py-2">{m.attempts}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </Card>
      {h && h.pages > 1 && (
        <div className="flex items-center gap-2 text-sm">
          <Button size="sm" variant="outline" disabled={page <= 1} onClick={() => setPage((p) => p - 1)}>Previous</Button>
          <span>Page {h.page} of {h.pages} · {h.total} emails</span>
          <Button size="sm" variant="outline" disabled={page >= h.pages} onClick={() => setPage((p) => p + 1)}>Next</Button>
        </div>
      )}
      {h && h.runs_without_email.length > 0 && (
        <section aria-label="Runs without email" className="space-y-1">
          <h2 className="text-xs font-semibold tracking-[0.14em] text-muted-foreground uppercase">Recent runs that sent no email</h2>
          <ul className="space-y-1 text-sm">
            {h.runs_without_email.map((r) => <li key={r.id}>{formatDateTime(r.created_at)} · {r.automation} · {r.status}{r.detail ? `: ${r.detail}` : ''}</li>)}
          </ul>
        </section>
      )}
      {open !== null && <MessageSheet id={open} onClose={() => setOpen(null)} onChanged={(id) => { setOpen(id); setVersion((v) => v + 1); }} />}
    </div>
  );
}

function MessageSheet({ id, onClose, onChanged }: { id: number; onClose: () => void; onChanged: (id: number) => void }) {
  const [version, setVersion] = useState(0);
  const query = useApiQuery(`alert-message-${id}-${version}`, (signal) => fetchAlertMessage(id, signal));
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const m = query.data?.message;
  const act = async (name: string, action: () => Promise<{ message: AlertMessage }>) => {
    setBusy(name);
    setError(null);
    try {
      const r = await action();
      onChanged(r.message.id);
      setVersion((v) => v + 1);
    } catch (e) {
      const details = (e as { details?: Record<string, unknown> }).details ?? {};
      setError(String(Object.values(details).flat()[0] ?? (e as Error).message));
    } finally {
      setBusy(null);
    }
  };
  return (
    <Sheet open onOpenChange={(o) => { if (!o) onClose(); }}>
      <SheetContent className="w-full overflow-y-auto sm:max-w-2xl">
        <SheetHeader>
          <SheetTitle>{m?.subject ?? 'Email'}</SheetTitle>
          <SheetDescription>{m ? `${m.automation} · ${m.trigger} · created ${formatDateTime(m.created_at)}` : 'Loading…'}</SheetDescription>
        </SheetHeader>
        <div className="space-y-4 px-4 pb-6">
          {query.error && <p role="alert" className="text-sm text-destructive">{query.error.message}</p>}
          {!m && !query.error && <Skeleton className="h-64" />}
          {m && (
            <>
              <div className="flex flex-wrap items-center gap-2">
                <StatusBadge m={m} />
                {m.status === 'failed' && (
                  <Button size="sm" variant="outline" disabled={!!busy} onClick={() => { void act('retry', () => retryAlertMessage(m.id)); }}>
                    {busy === 'retry' ? <Loader2 className="animate-spin" /> : <RotateCcw />} Retry
                  </Button>
                )}
                {(m.status === 'accepted' || m.status === 'failed') && (
                  <Button size="sm" variant="outline" disabled={!!busy} onClick={() => { void act('resend', () => resendAlertMessage(m.id)); }}>
                    {busy === 'resend' ? <Loader2 className="animate-spin" /> : <Send />} Resend
                  </Button>
                )}
              </div>
              {error && <p role="alert" className="text-sm text-destructive">{error}</p>}
              <dl className="grid grid-cols-[8rem_1fr] gap-x-3 gap-y-1 text-sm">
                <dt className="text-muted-foreground">To</dt><dd className="break-all">{m.to.join(', ') || '—'}</dd>
                {m.cc.length > 0 && <><dt className="text-muted-foreground">CC</dt><dd className="break-all">{m.cc.join(', ')}</dd></>}
                {m.bcc.length > 0 && <><dt className="text-muted-foreground">BCC</dt><dd className="break-all">{m.bcc.join(', ')}</dd></>}
                <dt className="text-muted-foreground">Attachments</dt>
                <dd>{m.attachments.map((a) => `${a.name}${a.period ? ` (${a.period})` : ''}`).join(', ') || 'None'}</dd>
                <dt className="text-muted-foreground">Accepted at</dt><dd>{m.sent_at ? formatDateTime(m.sent_at) : '—'}</dd>
                <dt className="text-muted-foreground">SMTP response</dt><dd className="break-words">{m.smtp_response || '—'}</dd>
                {m.error && <><dt className="text-muted-foreground">Error</dt><dd className="break-words text-destructive">{m.error}</dd></>}
                {m.resend_of && <><dt className="text-muted-foreground">Resend of</dt><dd>Email #{m.resend_of}</dd></>}
                {!!m.resends?.length && <><dt className="text-muted-foreground">Resent as</dt><dd>{m.resends.map((r) => `#${r}`).join(', ')}</dd></>}
              </dl>
              <section aria-label="Attempts">
                <h3 className="mb-1 text-xs font-semibold text-muted-foreground uppercase">Attempts ({m.attempts})</h3>
                {m.attempt_log?.length ? (
                  <ul className="space-y-1 text-sm">
                    {m.attempt_log.map((t, i) => (
                      <li key={i} className={cn('rounded-md border px-2 py-1', t.ok ? 'border-emerald-200' : 'border-destructive/30')}>
                        {formatDateTime(t.at)} · {t.by} · {t.ok ? 'Accepted' : 'Failed'}: <span className="break-words">{t.detail}</span>
                      </li>
                    ))}
                  </ul>
                ) : <p className="text-sm text-muted-foreground">Not attempted yet.</p>}
              </section>
              <p className="text-[11px] text-muted-foreground">“Accepted by SMTP” means the mail server accepted the message; delivery to the mailbox is not reported back.</p>
              {m.html && <iframe title="Email content" sandbox="" srcDoc={m.html} className="h-[28rem] w-full rounded-md border bg-white" />}
            </>
          )}
        </div>
      </SheetContent>
    </Sheet>
  );
}
