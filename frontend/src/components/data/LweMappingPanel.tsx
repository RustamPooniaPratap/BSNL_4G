import { useState } from 'react';
import { AlertTriangle, CheckCircle2, Database, Download, Loader2, Upload } from 'lucide-react';
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { formatNumber } from '../../lib/format';
import { commitLweMapping, discardLweMapping, lweMappingIssuesUrl, previewLweMapping } from '../../services/api';
import type { LweMappingBatch } from '../../types/matrixImport';

const FIELD = (f: string) => f.replace(/_/g, ' ');

/**
 * LWE Band ID mapping import: links the raw LWE band identifiers (BTS Site ID 2100 / 700, BTS IP ID) to the master sites,
 * so raw LWE CSV rows can be imported. Preview first (nothing is written), review, then confirm explicitly.
 */
export function LweMappingPanel({ onCommitted }: { onCommitted: () => void }) {
  const [file, setFile] = useState<File | null>(null);
  const [batch, setBatch] = useState<LweMappingBatch | null>(null);
  const [reviewed, setReviewed] = useState(false);
  const [busy, setBusy] = useState<'preview' | 'commit' | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [done, setDone] = useState<LweMappingBatch | null>(null);
  const run = async (kind: 'preview' | 'commit') => {
    setBusy(kind);
    setError(null);
    try {
      if (kind === 'preview') {
        setDone(null);
        setReviewed(false);
        setBatch(await previewLweMapping(file!));
      } else {
        setDone(await commitLweMapping(batch!.id));
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
  const c = batch?.counts;
  const changes = r?.changes;
  const tiles: [string, number | undefined, boolean][] = batch ? [
    ['Rows detected', c?.received, false], ['Accepted rows', c?.accepted, false], ['Rejected rows', c?.rejected, true],
    ['Repeated rows', c?.duplicate, false], ['Master IDs not in the site master', c?.unmatched, true],
    ['Sites added', changes?.added, false], ['Sites changed', changes?.changed, false], ['Sites unchanged', changes?.unchanged, false],
    ['LWE sites mapped after import', r?.lwe_sites_mapped_after_import, false], ['LWE sites without mapping', r?.lwe_sites_without_mapping, true],
  ] : [];
  return (
    <div className="space-y-3" role="region" aria-label="LWE Band ID mapping import">
      <p className="text-xs text-muted-foreground">
        Reads the LWE Band ID mapping workbook (Circle, BTS IP ID, BTS Site ID 2100 / 700, btsIpId - Master ID) and links each raw LWE identifier to
        its master site, so LWE rows of the raw daily CSV can be imported. Sites are never created; a site missing from the file keeps its mapping.
      </p>
      <div className="flex max-w-md flex-col gap-1">
        <Label htmlFor="lwe-mapping-file" className="text-xs">LWE Band ID mapping (.xlsx)</Label>
        <Input id="lwe-mapping-file" type="file" accept=".xlsx" onChange={(e) => { setFile(e.target.files?.[0] ?? null); setBatch(null); setDone(null); }} />
      </div>
      <Button onClick={() => run('preview')} disabled={!file || busy !== null}>
        {busy === 'preview' ? <Loader2 className="animate-spin" /> : <Upload />} {busy === 'preview' ? 'Validating…' : 'Preview mapping import'}
      </Button>
      {error && <Alert variant="destructive"><AlertTriangle /><AlertTitle>Import not possible</AlertTitle><AlertDescription>{error}</AlertDescription></Alert>}
      {done && done.status === 'committed' && (
        <Alert className="border-emerald-200 bg-emerald-50/70" role="status">
          <CheckCircle2 className="text-emerald-700" />
          <AlertTitle>LWE Band ID mapping #{done.id} imported</AlertTitle>
          <AlertDescription>
            {formatNumber(done.counts.accepted)} rows applied{done.report.identifiers_created != null ? `, ${formatNumber(done.report.identifiers_created)} identifiers added` : ''}
            {done.counts.rejected ? `, ${formatNumber(done.counts.rejected)} rejected rows not imported` : ''}. LWE rows of the raw daily CSV now resolve through this mapping.
          </AlertDescription>
        </Alert>
      )}
      {batch && r && (
        <section aria-label="LWE mapping preview" className="space-y-3 rounded-xl border p-3">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <h2 className="text-sm font-semibold">Preview #{batch.id}: {batch.file}{r.sheet ? ` · sheet “${r.sheet}”` : ''} · nothing has been written yet</h2>
            <a href={lweMappingIssuesUrl(batch.id)} className="inline-flex items-center gap-1 text-xs font-medium text-primary underline-offset-4 hover:underline">
              <Download className="size-3.5" /> Rejected rows and review items (CSV)
            </a>
          </div>
          <dl className="grid grid-cols-2 gap-2 sm:grid-cols-4 lg:grid-cols-5" aria-label="Preview counts">
            {tiles.map(([label, value, warn]) => (
              <div key={label} className="rounded-lg border px-3 py-2">
                <dt className="text-[11px] text-muted-foreground">{label}</dt>
                <dd className={`text-sm font-semibold tabular-nums ${warn && value ? 'text-destructive' : ''}`}>{formatNumber(value ?? 0)}</dd>
              </div>
            ))}
          </dl>
          {(r.warnings ?? []).map((w) => <p key={w} className="text-xs text-amber-800">{w}</p>)}
          {Object.keys(r.rejected_by_reason ?? {}).length > 0 && (
            <div className="text-xs" aria-label="Rejected rows">
              <h3 className="font-semibold">Rejected rows (not imported)</h3>
              <ul>{Object.entries(r.rejected_by_reason!).map(([code, n]) => <li key={code}>{FIELD(code)}: {formatNumber(n)}</li>)}</ul>
            </div>
          )}
          <label className="flex items-start gap-2 rounded-lg border px-3 py-2 text-sm">
            <input type="checkbox" className="mt-1" checked={reviewed} onChange={(e) => setReviewed(e.target.checked)} />
            <span>I have reviewed the preview. Import the {formatNumber(batch.counts.accepted)} accepted rows{batch.counts.rejected ? ` without the ${formatNumber(batch.counts.rejected)} rejected rows` : ''}.</span>
          </label>
          <div className="flex flex-wrap gap-2">
            <Button onClick={() => run('commit')} disabled={busy !== null || !reviewed || !batch.can_commit}>
              {busy === 'commit' ? <Loader2 className="animate-spin" /> : <Database />} {busy === 'commit' ? 'Importing…' : 'Confirm mapping import'}
            </Button>
            <Button variant="ghost" disabled={busy !== null} onClick={async () => { await discardLweMapping(batch.id); setBatch(null); }}>Discard preview</Button>
          </div>
        </section>
      )}
    </div>
  );
}
