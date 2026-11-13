import { useState } from 'react';
import { AlertTriangle, CheckCircle2, Database, Download, Loader2, Upload } from 'lucide-react';
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { formatNumber } from '../../lib/format';
import { commitMatrixImport, discardMatrixImport, matrixIssuesUrl, previewMatrixImport } from '../../services/api';
import type { MatrixImportBatch, MatrixPreviewCounts } from '../../types/matrixImport';

const COUNTS: [keyof MatrixPreviewCounts, string, boolean][] = [
  ['total_rows', 'Rows detected', false], ['new_sites', 'New sites', false], ['updated_sites', 'Sites to update', false],
  ['unchanged_sites', 'Unchanged sites', false], ['rejected_rows', 'Rejected rows', true], ['duplicate_site_ids', 'Duplicate site IDs', true],
  ['conflicting_mappings', 'Conflicting mappings', true], ['missing_mandatory', 'Missing mandatory fields', true],
  ['invalid_circle_or_technology', 'Invalid circle / technology', true], ['effective_date_issues', 'Effective dates to review', true],
  ['effective_date_changes', 'Effective dates changed', false], ['blank_values_kept', 'Blank cells (stored value kept)', false],
  ['sites_not_in_file', 'Sites not in this file (kept)', false],
];
const FIELD = (f: string) => f.replace(/_/g, ' ');

/**
 * Consolidation Matrix import: the site master of the new data layer (sites, identities, effective dates). Preview
 * first (nothing is written), review every rejected row and conflict, then confirm the import explicitly.
 */
export function MatrixImportPanel({ onCommitted }: { onCommitted: () => void }) {
  const [file, setFile] = useState<File | null>(null);
  const [batch, setBatch] = useState<MatrixImportBatch | null>(null);
  const [reviewed, setReviewed] = useState(false);
  const [busy, setBusy] = useState<'preview' | 'commit' | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [done, setDone] = useState<MatrixImportBatch | null>(null);
  const run = async (kind: 'preview' | 'commit') => {
    setBusy(kind);
    setError(null);
    try {
      if (kind === 'preview') {
        setDone(null);
        setReviewed(false);
        setBatch(await previewMatrixImport(file!));
      } else {
        setDone(await commitMatrixImport(batch!.id));
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
  const p = r?.preview;
  const changes = p ? p.new_sites + p.updated_sites : 0;
  return (
    <div className="space-y-3" role="region" aria-label="Consolidation Matrix import">
      <p className="text-xs text-muted-foreground">
        Reads the “Raw Data” sheet of the Consolidated Escalation Matrix into the site master of the new data layer (sites, On-Air and O&amp;M Start dates,
        identities). Blank cells never replace stored values, sites are never deleted, and daily or monthly performance records are not changed.
      </p>
      <div className="flex max-w-md flex-col gap-1">
        <Label htmlFor="matrix-file" className="text-xs">Consolidated Escalation Matrix (.xlsx)</Label>
        <Input id="matrix-file" type="file" accept=".xlsx,.xlsm" onChange={(e) => { setFile(e.target.files?.[0] ?? null); setBatch(null); setDone(null); }} />
      </div>
      <Button onClick={() => run('preview')} disabled={!file || busy !== null}>
        {busy === 'preview' ? <Loader2 className="animate-spin" /> : <Upload />} {busy === 'preview' ? 'Validating…' : 'Preview matrix import'}
      </Button>
      {error && <Alert variant="destructive"><AlertTriangle /><AlertTitle>Import not possible</AlertTitle><AlertDescription>{error}</AlertDescription></Alert>}
      {done && done.report.committed && (
        <Alert className="border-emerald-200 bg-emerald-50/70" role="status">
          <CheckCircle2 className="text-emerald-700" />
          <AlertTitle>Consolidation Matrix #{done.id} imported</AlertTitle>
          <AlertDescription>
            {formatNumber(done.report.committed.inserted)} new sites, {formatNumber(done.report.committed.updated)} updated, {formatNumber(done.report.committed.unchanged)} unchanged
            {done.report.committed.no_longer_in_matrix ? `, ${formatNumber(done.report.committed.no_longer_in_matrix)} not in the file (kept and flagged)` : ''}.
            {done.report.preview?.rejected_rows ? ` ${formatNumber(done.report.preview.rejected_rows)} rejected rows were not imported.` : ''} The dashboard pages use the updated site master.
          </AlertDescription>
        </Alert>
      )}
      {batch && r && p && (
        <section aria-label="Matrix import preview" className="space-y-3 rounded-xl border p-3">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <h2 className="text-sm font-semibold">Preview #{batch.id}: {batch.file} · sheet “{r.sheet}” · nothing has been written yet</h2>
            <a href={matrixIssuesUrl(batch.id)} className="inline-flex items-center gap-1 text-xs font-medium text-primary underline-offset-4 hover:underline">
              <Download className="size-3.5" /> Rejected rows and review items (CSV)
            </a>
          </div>
          <dl className="grid grid-cols-2 gap-2 sm:grid-cols-4 lg:grid-cols-7" aria-label="Preview counts">
            {COUNTS.map(([key, label, warn]) => (
              <div key={key} className="rounded-lg border px-3 py-2">
                <dt className="text-[11px] text-muted-foreground">{label}</dt>
                <dd className={`text-sm font-semibold tabular-nums ${warn && p[key] ? 'text-destructive' : ''}`}>{formatNumber(p[key])}</dd>
              </div>
            ))}
          </dl>
          {(r.warnings ?? []).map((w) => <p key={w} className="text-xs text-amber-800">{w}</p>)}
          {(r.columns_not_in_file ?? []).length > 0 && (
            <p className="text-xs text-muted-foreground">Columns not in this file, stored values kept: {r.columns_not_in_file!.map(FIELD).join(', ')}.</p>
          )}
          {(r.rejected ?? []).length > 0 && (
            <div className="space-y-1" aria-label="Rejected rows">
              <h3 className="text-xs font-semibold">Rejected rows (not imported)</h3>
              <ul className="text-xs">{Object.entries(r.rejected_by_reason ?? {}).map(([code, v]) => <li key={code}>{v.reason}: {formatNumber(v.rows)}</li>)}</ul>
              <div className="max-h-64 overflow-auto rounded border">
                <table className="w-full text-xs">
                  <thead><tr className="border-b text-left text-muted-foreground">{['Excel row', 'BSNL Site ID', 'Entity', 'Circle', 'Reason'].map((h) => <th key={h} className="px-2 py-1 font-medium">{h}</th>)}</tr></thead>
                  <tbody>{r.rejected!.slice(0, 200).map((x, i) => (
                    <tr key={`${x.row}-${i}`} className="border-b last:border-0"><td className="px-2 py-1 tabular-nums">{x.row ?? '—'}</td><td className="px-2 py-1">{x.site_id || '—'}</td>
                      <td className="px-2 py-1">{x.entity || '—'}</td><td className="px-2 py-1">{x.circle || '—'}</td><td className="px-2 py-1">{x.reason}</td></tr>
                  ))}</tbody>
                </table>
              </div>
            </div>
          )}
          {(r.identifier_conflicts ?? []).length > 0 && (
            <div className="text-xs" aria-label="Identifier conflicts">
              <h3 className="font-semibold">Identifiers claimed by several sites (assigned to none until resolved)</h3>
              <ul>{r.identifier_conflicts!.slice(0, 20).map((c) => <li key={c.kind + c.value}>{c.kind} {c.value}: {c.sites.join(', ')}</li>)}</ul>
            </div>
          )}
          {(r.effective_date_review_rows ?? []).length > 0 && (
            <div className="text-xs" aria-label="Effective dates to review">
              <h3 className="font-semibold">Effective dates to review</h3>
              <ul>{Object.entries(r.effective_date_review ?? {}).map(([code, n]) => <li key={code}>{FIELD(code)}: {formatNumber(n)}</li>)}</ul>
            </div>
          )}
          {(r.effective_date_changes ?? []).length > 0 && (
            <div className="text-xs" aria-label="Effective date changes">
              <h3 className="font-semibold">Effective dates that change ({formatNumber(p.effective_date_changes)})</h3>
              <ul>{r.effective_date_changes!.slice(0, 10).map((c) => <li key={`${c.site_id}-${c.field}`}>{c.site_id}: {FIELD(c.field)} {c.from ?? 'blank'} → {c.to ?? 'blank'}</li>)}</ul>
            </div>
          )}
          {Object.keys(r.changed_fields ?? {}).length > 0 && (
            <p className="text-xs text-muted-foreground">Fields that change: {Object.entries(r.changed_fields!).slice(0, 12).map(([f, n]) => `${FIELD(f)} ${formatNumber(n)}`).join(' · ')}</p>
          )}
          <label className="flex items-start gap-2 rounded-lg border px-3 py-2 text-sm">
            <input type="checkbox" className="mt-1" checked={reviewed} onChange={(e) => setReviewed(e.target.checked)} />
            <span>I have reviewed the preview. Import the {formatNumber(changes)} new and changed sites{p.rejected_rows ? ` without the ${formatNumber(p.rejected_rows)} rejected rows` : ''}.</span>
          </label>
          <div className="flex flex-wrap gap-2">
            <Button onClick={() => run('commit')} disabled={busy !== null || !reviewed || !batch.can_commit}>
              {busy === 'commit' ? <Loader2 className="animate-spin" /> : <Database />} {busy === 'commit' ? 'Importing…' : 'Confirm matrix import'}
            </Button>
            <Button variant="ghost" disabled={busy !== null} onClick={async () => { await discardMatrixImport(batch.id); setBatch(null); }}>Discard preview</Button>
          </div>
        </section>
      )}
    </div>
  );
}
