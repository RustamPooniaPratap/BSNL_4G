import { useState } from 'react';
import { Link, Navigate, useLocation } from 'react-router-dom';
import { RefreshCw, Search } from 'lucide-react';
import { Alert, AlertDescription } from '@/components/ui/alert';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Sheet, SheetContent, SheetDescription, SheetHeader, SheetTitle } from '@/components/ui/sheet';
import { Skeleton } from '@/components/ui/skeleton';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table';
import { cn } from '@/lib/utils';
import { SelectField } from '../../components/data/DataEntry';
import { PageHeading } from '../../context/pageHeader';
import { useApiQuery } from '../../hooks/useApiQuery';
import { formatDate, formatNumber } from '../../lib/format';
import { ApiError } from '../../services/api';
import { fetchEndpoint, fetchEndpoints, fetchRegistryOverview, reviewEndpoint, syncRegistry } from './api';
import type { ApiEndpointDetail, ApiEndpointRow, EndpointStatus, RegistryOverview, SyncResult } from './types';

/** API Master tabs. Phase 1 has the registry; applications, permissions, documentation and logs come with later phases. */
const TABS = [
  { path: '/admin/api-master', label: 'API Overview' },
  { path: '/admin/api-master/registry', label: 'API Registry' },
] as const;

const STATUS_LABEL: Record<EndpointStatus, string> = { pending: 'Pending', approved: 'Approved', rejected: 'Rejected', deprecated: 'Deprecated' };
const STATUS_CLASS: Record<EndpointStatus, string> = {
  pending: 'border-amber-300 bg-amber-50 text-amber-800',
  approved: 'border-emerald-300 bg-emerald-50 text-emerald-800',
  rejected: 'border-rose-300 bg-rose-50 text-rose-800',
  deprecated: 'border-slate-300 bg-slate-100 text-slate-700',
};
const METHOD_CLASS: Record<string, string> = {
  GET: 'border-emerald-300 bg-emerald-50 text-emerald-800', POST: 'border-sky-300 bg-sky-50 text-sky-800',
  PUT: 'border-amber-300 bg-amber-50 text-amber-800', PATCH: 'border-violet-300 bg-violet-50 text-violet-800',
  DELETE: 'border-rose-300 bg-rose-50 text-rose-800',
};
const errorText = (e: unknown) => (e instanceof ApiError
  ? Object.values(e.details).map(String).join(' ') || e.message
  : e instanceof Error ? e.message : 'The request failed.');

export function MethodBadge({ method }: { method: string }) {
  return <Badge variant="outline" className={cn('font-mono text-[11px]', METHOD_CLASS[method])}>{method}</Badge>;
}

export function StatusPill({ status }: { status: EndpointStatus }) {
  return <Badge variant="outline" className={STATUS_CLASS[status]}>{STATUS_LABEL[status]}</Badge>;
}

/** API Master (Admin > API Master): the registry of the portal's own endpoints and their review for external use. */
export function ApiMasterPage() {
  const location = useLocation();
  const path = location.pathname.replace(/\/+$/, '') || '/admin/api-master';
  const current = TABS.find((t) => t.path === path);
  const [version, setVersion] = useState(0);
  if (!current) return <Navigate to="/admin/api-master" replace />;
  return (
    <div className="flex flex-col gap-3">
      <PageHeading title="API Master"
        subtitle="The portal's API endpoints, discovered from the backend, and which of them may be exposed to external applications." />
      <nav aria-label="API Master sections" className="flex flex-wrap gap-1 rounded-xl border bg-card p-1 shadow-xs">
        {TABS.map((t) => (
          <Link key={t.path} to={t.path} aria-current={t === current ? 'page' : undefined}
            className={cn('rounded-lg px-3 py-1.5 text-xs font-medium transition-colors focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none',
              t === current ? 'bg-primary text-primary-foreground font-semibold shadow-xs' : 'text-muted-foreground hover:bg-muted hover:text-foreground')}>
            {t.label}
          </Link>
        ))}
      </nav>
      {current.path === '/admin/api-master'
        ? <Overview version={version} onSynced={() => setVersion((v) => v + 1)} />
        : <Registry version={version} onChanged={() => setVersion((v) => v + 1)} />}
    </div>
  );
}

function SyncButton({ onSynced }: { onSynced: (r: SyncResult) => void }) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  return (
    <div className="flex flex-col items-end gap-1">
      <Button type="button" size="sm" variant="outline" disabled={busy} onClick={async () => {
        setBusy(true); setError(null);
        try { onSynced(await syncRegistry()); } catch (e) { setError(errorText(e)); } finally { setBusy(false); }
      }}>
        <RefreshCw className={cn('size-3.5', busy && 'animate-spin')} aria-hidden="true" /> {busy ? 'Discovering…' : 'Discover endpoints'}
      </Button>
      {error && <p className="text-xs text-destructive" role="alert">{error}</p>}
    </div>
  );
}

function Stat({ label, value, hint }: { label: string; value: number; hint?: string }) {
  return (
    <div role="group" aria-label={label} className="rounded-xl border bg-card p-3 shadow-xs">
      <div className="text-[11px] font-medium text-muted-foreground">{label}</div>
      <div className="mt-1 text-2xl font-semibold tabular-nums">{formatNumber(value)}</div>
      {hint && <div className="mt-0.5 text-[11px] text-muted-foreground">{hint}</div>}
    </div>
  );
}

function Overview({ version, onSynced }: { version: number; onSynced: () => void }) {
  const q = useApiQuery(`api-master-overview-${version}`, (signal) => fetchRegistryOverview(signal));
  const [result, setResult] = useState<SyncResult | null>(null);
  const o: RegistryOverview | null = q.data;
  return (
    <>
      <Card>
        <CardHeader className="flex flex-row items-start justify-between gap-3">
          <div>
            <CardTitle className="text-base">Registered APIs</CardTitle>
            <CardDescription>
              Every route and method of the portal's URL configuration. New endpoints start as Pending; blocked endpoints
              (authentication, user management, administration, uploads, exports and writes) can never be approved.
              {o?.last_sync && ` Last discovery: ${formatDate(o.last_sync.slice(0, 10))}.`}
            </CardDescription>
          </div>
          <SyncButton onSynced={(r) => { setResult(r); onSynced(); }} />
        </CardHeader>
        <CardContent className="flex flex-col gap-3">
          {result && (
            <Alert role="status"><AlertDescription>
              Discovery finished: {result.discovered} endpoints found, {result.created} new, {result.updated} updated,
              {' '}{result.no_longer_present} no longer present{result.approvals_withdrawn ? `, ${result.approvals_withdrawn} approvals withdrawn` : ''}.
            </AlertDescription></Alert>
          )}
          {q.error && <Alert variant="destructive"><AlertDescription>{q.error.message}</AlertDescription></Alert>}
          {!o && !q.error && <Skeleton className="h-24 w-full" aria-label="Loading the registry overview" />}
          {o && o.total === 0 && (
            <p className="rounded-lg border border-dashed p-4 text-sm text-muted-foreground">
              The registry is empty. Use Discover endpoints to read the portal's API endpoints.
            </p>
          )}
          {o && o.total > 0 && (
            <>
              <div className="grid grid-cols-2 gap-2 sm:grid-cols-3 lg:grid-cols-6" aria-label="Registry counts">
                <Stat label="Total registered APIs" value={o.total} />
                <Stat label="Approved APIs" value={o.approved} />
                <Stat label="Pending APIs" value={o.pending} />
                <Stat label="Rejected / deprecated" value={o.rejected + o.deprecated} />
                <Stat label="Reviewable" value={o.reviewable} hint={`${o.field_review} need a field review`} />
                <Stat label="Blocked (internal only)" value={o.blocked} />
              </div>
              <div className="flex flex-wrap gap-2 text-xs text-muted-foreground" aria-label="Endpoints by method">
                {Object.entries(o.methods).map(([m, n]) => <span key={m} className="inline-flex items-center gap-1"><MethodBadge method={m} /> {n}</span>)}
              </div>
              <Table aria-label="Endpoints by module">
                <TableHeader><TableRow>
                  <TableHead>Module</TableHead><TableHead className="text-right">Endpoints</TableHead>
                  <TableHead className="text-right">Approved</TableHead><TableHead className="text-right">Blocked</TableHead>
                </TableRow></TableHeader>
                <TableBody>
                  {o.modules.map((m) => (
                    <TableRow key={m.module}>
                      <TableCell>{m.module}</TableCell><TableCell className="text-right tabular-nums">{m.total}</TableCell>
                      <TableCell className="text-right tabular-nums">{m.approved}</TableCell><TableCell className="text-right tabular-nums">{m.blocked}</TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </>
          )}
        </CardContent>
      </Card>
      <p className="text-xs text-muted-foreground">
        External applications, credentials and API request statistics appear here once those parts of the API Master are
        in place. Approving an endpoint records the review decision only: it becomes callable by external applications when
        its external route is implemented.
      </p>
    </>
  );
}

const ALL = 'all';

function Registry({ version, onChanged }: { version: number; onChanged: () => void }) {
  const [q, setQ] = useState('');
  const [module, setModule] = useState(ALL);
  const [method, setMethod] = useState(ALL);
  const [status, setStatus] = useState(ALL);
  const [access, setAccess] = useState(ALL);
  const [selected, setSelected] = useState<number | null>(null);
  const params = new URLSearchParams();
  if (q.trim()) params.set('q', q.trim());
  for (const [k, v] of [['module', module], ['method', method], ['status', status], ['access', access]] as const) if (v !== ALL) params.set(k, v);
  const list = useApiQuery(`api-master-endpoints-${version}-${params}`, (signal) => fetchEndpoints(params, signal));
  const overview = useApiQuery(`api-master-overview-${version}`, (signal) => fetchRegistryOverview(signal));
  const modules = overview.data?.modules.map((m) => m.module) ?? [];
  const rows = list.data?.results ?? [];
  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-base">API Registry</CardTitle>
        <CardDescription>Select an endpoint to see its details and record a review decision.</CardDescription>
      </CardHeader>
      <CardContent className="flex flex-col gap-3">
        <div className="flex flex-wrap items-end gap-2" aria-label="Registry filters">
          <div className="flex w-64 flex-col gap-1">
            <Label htmlFor="api-search" className="text-[11px] text-muted-foreground">Search</Label>
            <div className="relative">
              <Search className="absolute top-1/2 left-2.5 size-4 -translate-y-1/2 text-muted-foreground" aria-hidden="true" />
              <Input id="api-search" className="h-9 pl-8" placeholder="Name, route or description" value={q} onChange={(e) => setQ(e.target.value)} />
            </div>
          </div>
          {([
            ['api-module', 'Module', module, setModule, [{ value: ALL, label: 'All modules' }, ...modules.map((m) => ({ value: m, label: m }))]],
            ['api-method', 'HTTP method', method, setMethod, [{ value: ALL, label: 'All methods' }, ...['GET', 'POST', 'PUT', 'PATCH', 'DELETE'].map((m) => ({ value: m, label: m }))]],
            ['api-status', 'Approval status', status, setStatus, [{ value: ALL, label: 'All statuses' }, ...Object.entries(STATUS_LABEL).map(([value, label]) => ({ value, label }))]],
            ['api-access', 'Access type', access, setAccess, [{ value: ALL, label: 'All' }, { value: 'reviewable', label: 'Reviewable' }, { value: 'blocked', label: 'Blocked (internal only)' }]],
          ] as const).map(([id, label, value, set, options]) => (
            <div key={id} className="flex w-44 flex-col gap-1">
              <Label htmlFor={id} className="text-[11px] text-muted-foreground">{label}</Label>
              <SelectField id={id} value={value} onChange={set} options={[...options]} placeholder={label} />
            </div>
          ))}
          <span className="ml-auto text-xs text-muted-foreground" aria-live="polite">{list.data ? `${list.data.count} endpoints` : ''}</span>
        </div>
        {list.error && <Alert variant="destructive"><AlertDescription>{list.error.message}</AlertDescription></Alert>}
        {list.loading && !list.data && <Skeleton className="h-64 w-full" aria-label="Loading endpoints" />}
        {list.data && rows.length === 0 && (
          <p className="rounded-lg border border-dashed p-4 text-sm text-muted-foreground">
            No endpoint matches these filters{overview.data?.total === 0 ? '. The registry is empty: run Discover endpoints on API Overview.' : '.'}
          </p>
        )}
        {rows.length > 0 && (
          <div className="overflow-x-auto rounded-lg border">
            <Table aria-label="API endpoints">
              <TableHeader><TableRow>
                <TableHead>API Name</TableHead><TableHead>Endpoint URL</TableHead><TableHead>HTTP Method</TableHead><TableHead>Module</TableHead>
                <TableHead>Description</TableHead><TableHead>Access Type</TableHead><TableHead>Approval Status</TableHead><TableHead>Action</TableHead>
              </TableRow></TableHeader>
              <TableBody>
                {rows.map((r) => <EndpointRow key={r.id} row={r} onOpen={() => setSelected(r.id)} />)}
              </TableBody>
            </Table>
          </div>
        )}
      </CardContent>
      <EndpointSheet id={selected} version={version} onClose={() => setSelected(null)} onChanged={onChanged} />
    </Card>
  );
}

function EndpointRow({ row, onOpen }: { row: ApiEndpointRow; onOpen: () => void }) {
  return (
    <TableRow>
      <TableCell className="font-medium">{row.name}</TableCell>
      <TableCell className="font-mono text-xs">{row.path}</TableCell>
      <TableCell><MethodBadge method={row.method} /></TableCell>
      <TableCell>{row.module}</TableCell>
      <TableCell className="max-w-72 truncate text-xs text-muted-foreground" title={row.description || undefined}>{row.description || '—'}</TableCell>
      <TableCell className="text-xs">
        {row.access_type}
        {row.blocked && <span className="block text-muted-foreground">{row.block_reason}</span>}
        {!row.blocked && row.field_review && <span className="block text-amber-700">Field review: {row.field_review}</span>}
      </TableCell>
      <TableCell><StatusPill status={row.status} /></TableCell>
      <TableCell><Button type="button" size="sm" variant="outline" onClick={onOpen} aria-label={`View ${row.method} ${row.path}`}>View</Button></TableCell>
    </TableRow>
  );
}

function EndpointSheet({ id, version, onClose, onChanged }: { id: number | null; version: number; onClose: () => void; onChanged: () => void }) {
  const detail = useApiQuery(id === null ? null : `api-master-endpoint-${id}-${version}`, (signal) => fetchEndpoint(id!, signal));
  const e = detail.data;
  return (
    <Sheet open={id !== null} onOpenChange={(open) => { if (!open) onClose(); }}>
      <SheetContent className="w-full overflow-y-auto sm:max-w-xl">
        <SheetHeader>
          <SheetTitle className="flex items-center gap-2">{e && <MethodBadge method={e.method} />}{e?.name ?? 'Endpoint'}</SheetTitle>
          <SheetDescription>{e?.description || 'No description in the code.'}</SheetDescription>
        </SheetHeader>
        <div className="flex flex-col gap-4 px-4 pb-6 text-sm">
          {detail.error && <Alert variant="destructive"><AlertDescription>{detail.error.message}</AlertDescription></Alert>}
          {!e && !detail.error && <Skeleton className="h-48 w-full" aria-label="Loading the endpoint" />}
          {e && <EndpointFacts e={e} />}
          {e && <ReviewForm key={`${e.id}-${e.status}`} e={e} onChanged={onChanged} />}
        </div>
      </SheetContent>
    </Sheet>
  );
}

function EndpointFacts({ e }: { e: ApiEndpointDetail }) {
  const row = (label: string, value: React.ReactNode) => (
    <div className="grid grid-cols-[9rem_1fr] gap-2 border-b py-1.5 last:border-0">
      <dt className="text-xs text-muted-foreground">{label}</dt><dd className="min-w-0 break-words">{value}</dd>
    </div>
  );
  return (
    <dl aria-label="Endpoint details">
      {row('Endpoint path', <code className="font-mono text-xs">{e.path}</code>)}
      {row('HTTP method', e.method)}
      {row('Module', e.module)}
      {row('Approval status', <StatusPill status={e.status} />)}
      {row('Access type', <>{e.access_type}{e.blocked && <span className="block text-xs text-muted-foreground">{e.block_reason}</span>}</>)}
      {e.field_review && row('Field review', <span className="text-amber-700">{e.field_review}</span>)}
      {row('Path parameters', e.path_params.length ? e.path_params.map((p) => `${p.name} (${p.type})`).join(', ') : 'None')}
      {row('Authentication', e.authentication_classes.length ? `Portal session (${e.authentication_classes.join(', ')})` : 'None (open endpoint)')}
      {row('Permission', e.permission_classes.join(', ') || '—')}
      {row('View', <code className="font-mono text-xs">{e.view}</code>)}
      {row('External route', e.external_route ?? 'Not implemented yet')}
      {row('Query parameters & response', 'Documented from the code, with contract tests, when the endpoint gets its external route.')}
      {row('Last review', e.reviewed_at ? `${e.reviewed_by ?? '—'}, ${formatDate(e.reviewed_at.slice(0, 10))}: ${e.review_note}` : 'Not reviewed')}
    </dl>
  );
}

function ReviewForm({ e, onChanged }: { e: ApiEndpointDetail; onChanged: () => void }) {
  const choices = e.allowed_transitions.filter((s) => !(e.blocked && s === 'approved'));
  const [status, setStatus] = useState<string>('');
  const [note, setNote] = useState('');
  const [fieldsReviewed, setFieldsReviewed] = useState(false);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState<{ ok: boolean; text: string } | null>(null);
  if (e.blocked && !choices.length) return null;
  return (
    <form aria-label="Review decision" className="flex flex-col gap-2 rounded-lg border bg-muted/30 p-3" onSubmit={async (ev) => {
      ev.preventDefault();
      if (!status) { setMessage({ ok: false, text: 'Choose a decision.' }); return; }
      setBusy(true); setMessage(null);
      try {
        const updated = await reviewEndpoint(e.id, { status: status as EndpointStatus, note, fields_reviewed: fieldsReviewed });
        setMessage({ ok: true, text: `Saved: ${updated.status_label}.` });
        onChanged();
      } catch (err) {
        setMessage({ ok: false, text: errorText(err) });
      } finally { setBusy(false); }
    }}>
      <h3 className="text-sm font-semibold">Review decision</h3>
      {e.blocked && <p className="text-xs text-muted-foreground">Blocked endpoints can never be approved for external use.</p>}
      <div className="flex flex-col gap-1">
        <Label htmlFor="review-status" className="text-[11px] text-muted-foreground">New status</Label>
        <SelectField id="review-status" value={status} onChange={setStatus} placeholder="Choose a decision"
          options={choices.map((s) => ({ value: s, label: STATUS_LABEL[s] }))} disabled={busy || !choices.length} />
      </div>
      <div className="flex flex-col gap-1">
        <Label htmlFor="review-note" className="text-[11px] text-muted-foreground">Reason (required)</Label>
        <textarea id="review-note" rows={3} maxLength={2000} value={note} onChange={(ev) => setNote(ev.target.value)} disabled={busy}
          className="rounded-md border bg-background px-2.5 py-1.5 text-sm outline-none focus-visible:ring-2 focus-visible:ring-ring" />
      </div>
      {e.field_review && status === 'approved' && (
        <label className="flex items-start gap-2 text-xs">
          <input type="checkbox" checked={fieldsReviewed} onChange={(ev) => setFieldsReviewed(ev.target.checked)} disabled={busy} className="mt-0.5" />
          <span>I have reviewed the response fields ({e.field_review}) and they may be shared externally.</span>
        </label>
      )}
      <div className="flex items-center gap-2">
        <Button type="submit" size="sm" disabled={busy || !choices.length}>{busy ? 'Saving…' : 'Save decision'}</Button>
        {message && <span role={message.ok ? 'status' : 'alert'} className={cn('text-xs', message.ok ? 'text-emerald-700' : 'text-destructive')}>{message.text}</span>}
      </div>
    </form>
  );
}
