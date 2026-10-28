import { useRef, useState } from 'react';
import { Link } from 'react-router-dom';
import { Download, FileUp, Upload } from 'lucide-react';
import { Alert, AlertDescription } from '@/components/ui/alert';
import { Button } from '@/components/ui/button';
import { Card } from '@/components/ui/card';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table';
import { useApiQuery } from '../../hooks/useApiQuery';
import { formatDate, formatNumber } from '../../lib/format';
import { commitRcaImport, discardRcaImport, fetchRcaImports, previewRcaImport, rcaIssuesUrl } from '../../services/api';
import type { RcaImportBatch } from '../../types/rca';
import { Segmented } from '../../components/rca/RcaShared';

/** Admin: upload the RCA workbook, check the preview, then commit it to the database in one transaction. */
export function RcaImportPage() {
  const [version, setVersion] = useState(0);
  const history = useApiQuery(`rca-imports-${version}`, (signal) => fetchRcaImports(signal));
  const input = useRef<HTMLInputElement>(null);
  const [file, setFile] = useState<File | null>(null);
  const [batch, setBatch] = useState<RcaImportBatch | null>(null);
  const [conflicts, setConflicts] = useState<'skip' | 'overwrite'>('skip');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [done, setDone] = useState<string | null>(null);

  async function step(action: () => Promise<void>) {
    setBusy(true);
    setError(null);
    try {
      await action();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }
  const preview = () => step(async () => { setDone(null); setBatch(await previewRcaImport(file!)); setVersion((v) => v + 1); });
  const commit = () => step(async () => {
    const result = await commitRcaImport(batch!.id, batch!.report!.conflict_rows ? conflicts : '');
    const c = result.counts;
    setDone(`Imported: ${formatNumber(c.inserted)} new records, ${formatNumber(c.unchanged)} already present` +
      (c.conflicts ? `, ${formatNumber(c.conflicts)} conflicts (${c.overwritten ? `${c.overwritten} overwritten` : `${c.skipped_conflicts} skipped`})` : '') +
      `. The database now holds ${formatNumber(result.records)} RCA records.`);
    setBatch(null);
    setFile(null);
    setVersion((v) => v + 1);
  });
  const discard = () => step(async () => { await discardRcaImport(batch!.id); setBatch(null); setVersion((v) => v + 1); });
  const r = batch?.report;

  return (
    <div className="space-y-4">
      <Card className="gap-3 rounded-xl px-5 py-4">
        <div className="flex items-start gap-3">
          <span className="grid size-9 place-items-center rounded-lg bg-primary/10 text-primary"><FileUp className="size-5" aria-hidden="true" /></span>
          <div>
            <h1 className="text-xl font-semibold tracking-tight">RCA import</h1>
            <p className="text-sm text-muted-foreground">
              Upload the RCA workbook (sheet "Sheet1": Date, Project, Circle, Site ID, Site Name, OA, BA, O&M Start (Yes/No), Outage Min., Final Bucket, Bucket - 2, RCA).
              Nothing is written until you commit the preview. A repeat import adds nothing twice, and rows that differ from stored records are never overwritten without your choice.
            </p>
          </div>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <input ref={input} type="file" accept=".xlsx,.xlsm" className="hidden" aria-label="RCA workbook"
            onChange={(e) => { setFile(e.target.files?.[0] ?? null); setBatch(null); setDone(null); }} />
          <Button type="button" variant="outline" onClick={() => input.current?.click()}><Upload /> Choose workbook</Button>
          <span className="text-sm text-muted-foreground">{file ? file.name : 'No file chosen'}</span>
          <Button type="button" onClick={preview} disabled={!file || busy}>{busy && !batch ? 'Checking…' : 'Preview'}</Button>
        </div>
        {error && <Alert variant="destructive"><AlertDescription>{error}</AlertDescription></Alert>}
        {done && <Alert><AlertDescription>{done} <Link to="/rca" className="font-medium underline">Open the RCA Register</Link></AlertDescription></Alert>}
      </Card>

      {batch && r && (
        <Card className="gap-4 rounded-xl px-5 py-4" aria-label="Import preview">
          <div className="flex flex-wrap items-start justify-between gap-3">
            <div>
              <h2 className="text-base font-semibold">Preview: {batch.file}</h2>
              <p className="text-xs text-muted-foreground">Import #{batch.id} · checksum {batch.checksum.slice(0, 12)}… · not yet in the database</p>
            </div>
            <a href={rcaIssuesUrl(batch.id)} className="inline-flex items-center gap-1.5 text-sm font-medium underline underline-offset-2"><Download className="size-4" /> Validation report (CSV)</a>
          </div>
          {r.already_imported && (
            <Alert><AlertDescription>This exact file was already imported (import #{r.already_imported.batch}, {new Date(r.already_imported.committed_at).toLocaleString('en-IN')}). Committing again adds nothing.</AlertDescription></Alert>
          )}
          <dl className="grid gap-3 sm:grid-cols-3 lg:grid-cols-6">
            {[
              ['Valid rows', r.valid_rows], ['Rejected rows', r.rejected_rows], ['Distinct sites', r.distinct_sites],
              ['New records', r.new_rows], ['Already present', r.unchanged_rows], ['Conflicts', r.conflict_rows],
            ].map(([label, value]) => (
              <div key={label as string} className="rounded-lg border px-3 py-2">
                <dt className="text-xs text-muted-foreground">{label}</dt>
                <dd className={`text-lg font-semibold tabular-nums ${(label === 'Rejected rows' || label === 'Conflicts') && Number(value) ? 'text-destructive' : ''}`}>{formatNumber(Number(value))}</dd>
              </div>
            ))}
          </dl>
          <div className="grid gap-4 text-sm lg:grid-cols-3">
            <Counts title="Reporting dates" items={Object.entries(r.dates).map(([d, n]) => [formatDate(d), n])} />
            <Counts title="Projects (source label → read as)" items={Object.entries(r.projects_raw).map(([p, n]) => [`${p} → ${p.toLowerCase().startsWith('4g') ? '4G Saturation' : p}`, n])} />
            <Counts title="Circles (source name → code)" items={Object.entries(r.circle_names)} />
          </div>
          <div className="space-y-1 text-sm">
            <h3 className="font-semibold">Validation</h3>
            <p className="text-xs text-muted-foreground">
              {formatNumber(r.severity_counts.error)} errors (rows rejected) · {formatNumber(r.severity_counts.warning)} warnings · {formatNumber(r.severity_counts.info)} notes.
              Total Outage Min.: {formatNumber(Math.round(r.outage_minutes))} · {formatNumber(r.distinct_rca)} distinct RCA descriptions.
            </p>
            <ul className="list-disc space-y-0.5 pl-5 text-xs">
              {Object.entries(r.issue_counts).map(([code, n]) => <li key={code}><span className="font-mono">{code}</span>: {formatNumber(n)}</li>)}
              {Object.entries(r.label_variants).flatMap(([field, groups]) => groups.map((g) => (
                <li key={field + g.join()}>{field === 'om_start_raw' ? 'O&M Start' : field === 'final_bucket' ? 'Final Bucket' : 'Bucket - 2'} spellings grouped for filtering (values kept): {g.map((v) => `“${v}”`).join(', ')}</li>
              )))}
            </ul>
            {r.issues.filter((i) => i.severity !== 'info' || i.row == null).slice(0, 12).map((i, n) => (
              <p key={n} className={`text-xs ${i.severity === 'error' ? 'text-destructive' : i.severity === 'warning' ? 'text-amber-700' : 'text-muted-foreground'}`}>
                {i.row ? `Row ${i.row}${i.site_id ? ` (${i.site_id})` : ''}: ` : ''}{i.message}
              </p>
            ))}
          </div>
          {r.conflict_rows > 0 && (
            <div className="space-y-2 rounded-lg border border-amber-300 bg-amber-50 px-3 py-2 text-sm">
              <p><span className="font-semibold">{formatNumber(r.conflict_rows)} rows differ</span> from RCA records already stored for the same date, project and site. Choose what to do:</p>
              <Segmented label="Conflicting rows" value={conflicts} onChange={setConflicts} options={[['skip', 'Keep stored records (skip)'], ['overwrite', 'Overwrite with this file']]} />
              <ul className="text-xs">
                {r.conflicts.slice(0, 5).map((c) => <li key={c.row}>Row {c.row} ({c.site_id}): {Object.keys(c.differences).join(', ')}</li>)}
              </ul>
            </div>
          )}
          <div className="flex gap-2">
            <Button type="button" onClick={commit} disabled={busy || !r.valid_rows}>{busy ? 'Working…' : `Commit ${formatNumber(r.new_rows)} new records`}</Button>
            <Button type="button" variant="ghost" onClick={discard} disabled={busy}>Discard preview</Button>
          </div>
        </Card>
      )}

      <Card className="gap-2 rounded-xl px-5 py-4">
        <h2 className="text-base font-semibold">Import history</h2>
        {history.data && <p className="text-xs text-muted-foreground">{formatNumber(history.data.records)} RCA records in the database.</p>}
        {history.data?.imports.length ? (
          <div className="overflow-x-auto">
            <Table>
              <TableHeader><TableRow>{['#', 'File', 'Status', 'Uploaded', 'By', 'Result', ''].map((h) => <TableHead key={h}>{h}</TableHead>)}</TableRow></TableHeader>
              <TableBody>
                {history.data.imports.map((b) => (
                  <TableRow key={b.id}>
                    <TableCell>{b.id}</TableCell>
                    <TableCell className="max-w-56 truncate" title={b.file}>{b.file}</TableCell>
                    <TableCell className="capitalize">{b.status}</TableCell>
                    <TableCell className="whitespace-nowrap">{new Date(b.uploaded_at).toLocaleString('en-IN')}</TableCell>
                    <TableCell>{b.imported_by ?? '—'}</TableCell>
                    <TableCell className="text-xs">{b.status === 'committed' ? `${formatNumber(b.counts.inserted ?? 0)} new · ${formatNumber(b.counts.unchanged ?? 0)} unchanged · ${formatNumber(b.counts.conflicts ?? 0)} conflicts`
                      : b.error ?? (b.status === 'previewed' ? `${formatNumber(b.counts.valid ?? 0)} valid rows, not committed` : '—')}</TableCell>
                    <TableCell>{b.status !== 'failed' && <a href={rcaIssuesUrl(b.id)} className="text-xs underline">Report</a>}</TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </div>
        ) : <p className="text-sm text-muted-foreground">{history.error ? history.error.message : history.data ? 'No RCA imports yet.' : 'Loading…'}</p>}
      </Card>
    </div>
  );
}

function Counts({ title, items }: { title: string; items: [string, number][] }) {
  return (
    <div>
      <h3 className="mb-1 text-xs font-semibold text-muted-foreground uppercase">{title}</h3>
      <ul className="space-y-0.5">
        {items.map(([k, n]) => <li key={k} className="flex justify-between gap-3"><span>{k}</span><span className="tabular-nums">{formatNumber(n)}</span></li>)}
      </ul>
    </div>
  );
}
