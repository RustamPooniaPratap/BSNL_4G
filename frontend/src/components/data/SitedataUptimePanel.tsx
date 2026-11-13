import { useState } from 'react';
import { AlertTriangle, CheckCircle2, Database, Download, Loader2, Upload } from 'lucide-react';
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { formatDateTime, formatNumber } from '../../lib/format';
import { commitSitedataUptime, discardSitedataUptime, previewSitedataUptime, sitedataUptimeIssuesUrl } from '../../services/api';
import type { UptimeImportBatch } from '../../types/matrixImport';

const COUNTS: [keyof UptimeImportBatch['counts'], string, boolean][] = [
  ['received', 'Site-days in scope', false], ['accepted', 'New records', false], ['duplicate', 'Already stored (same value)', false],
  ['conflict', 'Differ from a stored value (kept)', true], ['superseded', 'Replace a raw CSV value', false],
  ['rejected', 'Rejected', true], ['unmatched', 'Sites not in the site master', true],
];

/**
 * Up-Time Report into the new data layer: the daily table every dashboard page reads. Preview first (nothing is
 * written), then confirm. Duplicate files are checked against this destination only; a legacy import of the same
 * file is shown for information. Stored records keep their source precedence and authorized corrections.
 */
export function SitedataUptimePanel({ onCommitted }: { onCommitted: () => void }) {
  const [file, setFile] = useState<File | null>(null);
  const [project, setProject] = useState('');
  const [batch, setBatch] = useState<UptimeImportBatch | null>(null);
  const [reviewed, setReviewed] = useState(false);
  const [busy, setBusy] = useState<'preview' | 'commit' | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [done, setDone] = useState<UptimeImportBatch | null>(null);
  const run = async (kind: 'preview' | 'commit') => {
    setBusy(kind);
    setError(null);
    try {
      if (kind === 'preview') {
        setDone(null);
        setReviewed(false);
        setBatch(await previewSitedataUptime(file!, project));
      } else {
        setDone(await commitSitedataUptime(batch!.id));
        setBatch(null);
        onCommitted();
      }
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(null);
    }
  };
  const r = batch?.report;
  return (
    <div className="space-y-3" role="region" aria-label="Up-Time Report into the new data layer">
      <p className="text-xs text-muted-foreground">
        Adds the workbook's daily values to the new data layer, which every dashboard page reads. Sites come from the Consolidation Matrix; the workbook
        never creates sites. Values already stored, authorized corrections and higher-precedence sources are never overwritten.
      </p>
      <div className="grid grid-cols-1 gap-3 md:grid-cols-2">
        <div className="flex flex-col gap-1">
          <Label htmlFor="sitedata-uptime-file" className="text-xs">Up-Time Report workbook (.xlsx)</Label>
          <Input id="sitedata-uptime-file" type="file" accept=".xlsx,.xlsm" onChange={(e) => { setFile(e.target.files?.[0] ?? null); setBatch(null); setDone(null); }} />
        </div>
        <div className="flex flex-col gap-1">
          <Label htmlFor="sitedata-uptime-project" className="text-xs">Project, if the sheet has no Project column</Label>
          <select id="sitedata-uptime-project" value={project} onChange={(e) => setProject(e.target.value)} className="h-9 rounded-md border bg-transparent px-2 text-sm">
            <option value="">From the Project column</option>
            <option value="4G Saturation">4G Saturation (e.g. the RJ, MP &amp; OD report)</option>
            <option value="LWE">LWE</option>
          </select>
        </div>
      </div>
      <Button onClick={() => run('preview')} disabled={!file || busy !== null}>
        {busy === 'preview' ? <Loader2 className="animate-spin" /> : <Upload />} {busy === 'preview' ? 'Validating…' : 'Preview import into the new data layer'}
      </Button>
      {error && <Alert variant="destructive"><AlertTriangle /><AlertTitle>Import not possible</AlertTitle><AlertDescription>{error}</AlertDescription></Alert>}
      {done && (
        <Alert className="border-emerald-200 bg-emerald-50/70" role="status">
          <CheckCircle2 className="text-emerald-700" />
          <AlertTitle>Up-Time Report #{done.id} imported into the new data layer</AlertTitle>
          <AlertDescription>
            {formatNumber(done.counts.accepted)} new daily records, {formatNumber(done.counts.duplicate)} already stored
            {done.counts.conflict ? `, ${formatNumber(done.counts.conflict)} differing values kept out (logged)` : ''}
            {done.counts.unmatched ? `, ${formatNumber(done.counts.unmatched)} site-days of sites not in the site master` : ''}. The dashboard pages show the new values.
          </AlertDescription>
        </Alert>
      )}
      {batch && r && (
        <section aria-label="New data layer import preview" className="space-y-3 rounded-xl border p-3">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <h2 className="text-sm font-semibold">Preview #{batch.id}: {batch.file} · nothing has been written yet</h2>
            <a href={sitedataUptimeIssuesUrl(batch.id)} className="inline-flex items-center gap-1 text-xs font-medium text-primary underline-offset-4 hover:underline">
              <Download className="size-3.5" /> Rejected and unmatched rows (CSV)
            </a>
          </div>
          {r.already_imported && (
            <Alert><CheckCircle2 /><AlertTitle>This exact file was already imported into the new data layer</AlertTitle>
              <AlertDescription>Upload #{r.already_imported.batch} on {formatDateTime(r.already_imported.committed_at)}. Committing again adds no record that is already stored.</AlertDescription></Alert>
          )}
          <p className="text-xs text-muted-foreground">
            Months in the file: {(r.months_in_file ?? []).join(', ') || 'none'} · imported months: {(r.months_in_scope ?? []).join(', ')}
            {r.not_reported_site_days ? ` · ${formatNumber(r.not_reported_site_days)} blank site-days are not reported (never 0)` : ''}
          </p>
          <dl className="grid grid-cols-2 gap-2 sm:grid-cols-4 lg:grid-cols-7" aria-label="Preview counts">
            {COUNTS.map(([key, label, warn]) => (
              <div key={key} className="rounded-lg border px-3 py-2">
                <dt className="text-[11px] text-muted-foreground">{label}</dt>
                <dd className={`text-sm font-semibold tabular-nums ${warn && batch.counts[key] ? 'text-destructive' : ''}`}>{formatNumber(batch.counts[key])}</dd>
              </div>
            ))}
          </dl>
          {(r.warnings ?? []).map((w) => <p key={w} className="text-xs text-amber-800">{w}</p>)}
          {(r.sites_not_in_site_master ?? []).length > 0 && (
            <p className="text-xs">Not in the site master: {r.sites_not_in_site_master!.slice(0, 10).join(', ')}{(r.sites_not_in_site_master_count ?? 0) > 10 ? ', …' : ''}</p>
          )}
          <label className="flex items-start gap-2 rounded-lg border px-3 py-2 text-sm">
            <input type="checkbox" className="mt-1" checked={reviewed} onChange={(e) => setReviewed(e.target.checked)} />
            <span>I have reviewed the preview. Add the {formatNumber(batch.counts.accepted)} new daily records to the new data layer.</span>
          </label>
          <div className="flex flex-wrap gap-2">
            <Button onClick={() => run('commit')} disabled={busy !== null || !reviewed || !batch.can_commit}>
              {busy === 'commit' ? <Loader2 className="animate-spin" /> : <Database />} {busy === 'commit' ? 'Importing…' : 'Confirm import'}
            </Button>
            <Button variant="ghost" disabled={busy !== null} onClick={async () => { await discardSitedataUptime(batch.id); setBatch(null); }}>Discard preview</Button>
          </div>
        </section>
      )}
    </div>
  );
}
