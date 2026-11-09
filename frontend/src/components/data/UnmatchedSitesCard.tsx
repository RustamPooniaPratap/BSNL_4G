import { useState } from 'react';
import { Loader2, RefreshCw } from 'lucide-react';
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { useApiQuery } from '../../hooks/useApiQuery';
import { formatDate, formatNumber } from '../../lib/format';
import { fetchUnmatchedSites, mapAlternateIdentifier, processPendingRecords, refreshUnmatchedDetails } from '../../services/api';

const STATUS: Record<string, { label: string; variant: 'outline' | 'default' | 'secondary' }> = {
  pending: { label: 'Pending: not in the site master', variant: 'outline' },
  ready: { label: 'Resolved: ready to process', variant: 'secondary' },
  processed: { label: 'Processed', variant: 'default' },
};

/**
 * Data quality: Up-Time Report sites that are not in the Consolidation Matrix. Their values wait (never in a KPI) until an
 * Admin resolves the identity: add the site to the matrix and import it, or map an approved alternate identifier to an
 * existing master site; then process the pending records.
 */
export function UnmatchedSitesCard({ refreshKey }: { refreshKey: number }) {
  const [tick, setTick] = useState(0);
  const query = useApiQuery(`unmatched-sites|${refreshKey}|${tick}`, fetchUnmatchedSites);
  const [identifier, setIdentifier] = useState('');
  const [target, setTarget] = useState('');
  const [reason, setReason] = useState('');
  const [confirmProcess, setConfirmProcess] = useState(false);
  const [busy, setBusy] = useState<string | null>(null);
  const [message, setMessage] = useState<{ ok: boolean; text: string } | null>(null);
  const act = async (name: string, fn: () => Promise<string>) => {
    setBusy(name);
    setMessage(null);
    try {
      setMessage({ ok: true, text: await fn() });
      setTick((t) => t + 1);
    } catch (e) {
      setMessage({ ok: false, text: (e as Error).message });
    } finally {
      setBusy(null);
    }
  };
  const report = query.data;
  if (!report) return null;
  const pending = report.sites.filter((s) => s.status === 'pending');
  return (
    <Card role="region" aria-label="Sites not in the site master">
      <CardHeader>
        <CardTitle className="text-sm font-semibold">Sites not in the site master</CardTitle>
        <CardDescription className="text-xs">
          Up-Time Report sites that are not in the Consolidation Matrix. Their daily values are kept but not counted in any KPI until the identity is
          resolved: add the site to the Consolidation Matrix and import it, or map an approved alternate identifier to an existing site. Then process the
          pending records.
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-3 text-xs">
        {report.sites.length === 0 ? <p className="text-muted-foreground">Every Up-Time Report site is in the site master.</p> : (
          <div className="overflow-x-auto rounded-md border">
            <table className="w-full text-left">
              <caption className="sr-only">Unmatched sites</caption>
              <thead className="bg-muted"><tr>{['Site ID', 'Project', 'Circle', 'Reporting dates', 'Pending site-days', 'Reason', 'Status', 'Resolved to'].map((h) => <th key={h} className="px-2.5 py-1.5 font-medium">{h}</th>)}</tr></thead>
              <tbody className="divide-y">
                {report.sites.map((s) => (
                  <tr key={s.site_id}>
                    <td className="px-2.5 py-1.5 font-medium">{s.site_id}</td>
                    <td className="px-2.5 py-1.5">{s.project ?? '—'}</td>
                    <td className="px-2.5 py-1.5">{s.circle ?? '—'}</td>
                    <td className="px-2.5 py-1.5">{s.first_date ? `${formatDate(s.first_date)} – ${formatDate(s.last_date!)}` : '—'}</td>
                    <td className="px-2.5 py-1.5 tabular-nums">{s.pending_site_days == null ? 'Refresh to count' : formatNumber(s.pending_site_days)}</td>
                    <td className="px-2.5 py-1.5">{s.reason}</td>
                    <td className="px-2.5 py-1.5"><Badge variant={STATUS[s.status].variant}>{STATUS[s.status].label}</Badge></td>
                    <td className="px-2.5 py-1.5">{s.resolved_to ? `${s.resolved_to}${s.resolved_by === 'alternate_identifier' ? ' (alternate ID)' : ''}` : '—'}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
        {report.uploads_without_detail.length > 0 && (
          <div className="flex flex-wrap items-center gap-2">
            <span>Upload{report.uploads_without_detail.length > 1 ? 's' : ''} {report.uploads_without_detail.map((u) => `#${u}`).join(', ')} predate the per-site details.</span>
            <Button size="sm" variant="outline" disabled={busy !== null}
              onClick={() => act('refresh', async () => `${(await refreshUnmatchedDetails()).uploads_updated} upload(s) updated.`)}>
              {busy === 'refresh' ? <Loader2 className="animate-spin" /> : <RefreshCw />} Refresh details
            </Button>
          </div>
        )}
        {pending.length > 0 && (
          <form className="grid gap-2 rounded-lg border p-3 md:grid-cols-4" aria-label="Map an approved alternate identifier"
            onSubmit={(e) => { e.preventDefault(); void act('map', async () => { await mapAlternateIdentifier(identifier, target, reason); setReason(''); return `${identifier} now names ${target}.`; }); }}>
            <p className="font-medium md:col-span-4">Map an approved alternate identifier (only with evidence that it is the same site)</p>
            <div className="flex flex-col gap-1">
              <Label htmlFor="map-identifier" className="text-xs">Unmatched site ID</Label>
              <select id="map-identifier" value={identifier} onChange={(e) => setIdentifier(e.target.value)} className="h-9 rounded-md border bg-transparent px-2 text-sm">
                <option value="">Choose</option>
                {pending.map((s) => <option key={s.site_id} value={s.site_id}>{s.site_id}{s.project ? ` (${s.project})` : ''}</option>)}
              </select>
            </div>
            <div className="flex flex-col gap-1">
              <Label htmlFor="map-target" className="text-xs">Existing master BSNL Site ID</Label>
              <Input id="map-target" value={target} onChange={(e) => setTarget(e.target.value)} />
            </div>
            <div className="flex flex-col gap-1 md:col-span-2">
              <Label htmlFor="map-reason" className="text-xs">Evidence / reason</Label>
              <Input id="map-reason" value={reason} onChange={(e) => setReason(e.target.value)} />
            </div>
            <Button type="submit" size="sm" className="md:col-span-4 md:justify-self-start" disabled={busy !== null || !identifier || !target.trim() || !reason.trim()}>
              {busy === 'map' && <Loader2 className="animate-spin" />} Map identifier
            </Button>
          </form>
        )}
        {report.ready_sites > 0 && (
          <div className="space-y-2 rounded-lg border border-sky-200 bg-sky-50/60 p-3">
            <label className="flex items-start gap-2">
              <input type="checkbox" className="mt-0.5" checked={confirmProcess} onChange={(e) => setConfirmProcess(e.target.checked)} />
              <span>Process the pending records of the {report.ready_sites} resolved site(s): their daily values are added under the original uploads; stored
                values, authorized corrections and higher-precedence sources are kept.</span>
            </label>
            <Button size="sm" disabled={busy !== null || !confirmProcess}
              onClick={() => act('process', async () => { const r = await processPendingRecords(); setConfirmProcess(false); return `${formatNumber(r.counts.accepted ?? 0)} daily records added.`; })}>
              {busy === 'process' && <Loader2 className="animate-spin" />} Process pending records
            </Button>
          </div>
        )}
        {message && (
          <Alert variant={message.ok ? 'default' : 'destructive'} role={message.ok ? 'status' : 'alert'}>
            <AlertTitle>{message.ok ? 'Done' : 'Not possible'}</AlertTitle><AlertDescription>{message.text}</AlertDescription>
          </Alert>
        )}
      </CardContent>
    </Card>
  );
}
