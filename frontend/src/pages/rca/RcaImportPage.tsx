import { useRef, useState } from 'react';
import { Link } from 'react-router-dom';
import { Download, Upload } from 'lucide-react';
import { Alert, AlertDescription } from '@/components/ui/alert';
import { Button } from '@/components/ui/button';
import { Card } from '@/components/ui/card';
import { Input } from '@/components/ui/input';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table';
import { SelectField } from '../../components/data/DataEntry';
import { Field as FilterField } from '../../components/dashboard/FilterBar';
import { PageHeading } from '../../context/pageHeader';
import { RcaImportPreview, type CommitChoices } from '../../components/rca/RcaImportPreview';
import { useAuth } from '../../context/auth';
import { useApiQuery } from '../../hooks/useApiQuery';
import { formatDateTime, formatNumber } from '../../lib/format';
import { formatMin, periodText } from '../../lib/rca';
import { commitRcaImport, discardRcaImport, fetchRcaImport, fetchRcaImports, previewRcaImport, rcaImportWorkbookUrl, rcaIssuesUrl } from '../../services/api';
import type { RcaImportBatch, RcaProjectScope, RcaUploadDetails } from '../../types/rca';

const SCOPES: { value: RcaProjectScope; label: string }[] = [
  { value: 'both', label: 'Both (4G Saturation and LWE)' }, { value: '4G Saturation', label: '4G Saturation' }, { value: 'LWE', label: 'LWE' },
];
const EMPTY: RcaUploadDetails = { report_name: '', period_start: '', period_end: '', project_scope: 'both', remarks: '' };

/**
 * Upload RCA Data (NOC Lead and Admin): enter the report details, upload the completed RCA workbook, check the
 * validation and confirm the import. The uploader is the signed-in account. Each user sees their own uploads here;
 * Admins monitor every upload on RCA Submissions.
 */
export function RcaImportPage() {
  const { user } = useAuth();
  const [version, setVersion] = useState(0);
  const history = useApiQuery(`rca-imports-${version}`, (signal) => fetchRcaImports(signal));
  const input = useRef<HTMLInputElement>(null);
  const [details, setDetails] = useState<RcaUploadDetails>(EMPTY);
  const [file, setFile] = useState<File | null>(null);
  const [batch, setBatch] = useState<RcaImportBatch | null>(null);
  const [result, setResult] = useState<RcaImportBatch | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const set = (key: keyof RcaUploadDetails, value: string) => setDetails((d) => ({ ...d, [key]: value }));

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
  const validate = () => step(async () => {
    setResult(null);
    setBatch(await previewRcaImport(file!, details));
    setVersion((v) => v + 1);
  });
  const commit = (choices: CommitChoices) => step(async () => {
    const done = await commitRcaImport(batch!.id, choices);
    setResult(done);
    setBatch(null);
    setFile(null);
    setDetails(EMPTY);
    if (input.current) input.current.value = '';
    setVersion((v) => v + 1);
  });
  const discard = () => step(async () => { await discardRcaImport(batch!.id); setBatch(null); setVersion((v) => v + 1); });
  const open = (id: number) => step(async () => { setBatch(null); setResult(await fetchRcaImport(id)); });
  const ready = file && details.report_name.trim() && details.period_start;

  return (
    <div className="space-y-4">
      <PageHeading title="Upload RCA Data"
        subtitle={`Daily RCA workbook (cumulative: earlier dates are compared, never removed) · uploaded as ${user?.username ?? '—'}`} />
      <Card className="gap-2 rounded-xl px-4 py-2.5 shadow-xs">
        <form aria-label="Report details" className="flex flex-wrap items-end gap-x-3 gap-y-2 [&_[data-slot=select-trigger]]:h-9" onSubmit={(e) => { e.preventDefault(); if (ready) void validate(); }}>
          <FilterField id="report-name" label="Report name *" className="w-64">
            <Input id="report-name" className="h-9" value={details.report_name} onChange={(e) => set('report_name', e.target.value)} placeholder="e.g. October 2026 RCA Report" />
          </FilterField>
          <FilterField id="period-start" label="Reporting date *" className="w-40">
            <Input id="period-start" type="date" className="h-9" value={details.period_start} onChange={(e) => set('period_start', e.target.value)} />
          </FilterField>
          <FilterField id="period-end" label="Last day (multi-day period)" className="w-44">
            <Input id="period-end" type="date" className="h-9" value={details.period_end} min={details.period_start || undefined} onChange={(e) => set('period_end', e.target.value)} />
          </FilterField>
          <FilterField id="project-scope" label="Project scope *" className="w-60">
            <SelectField id="project-scope" value={details.project_scope} placeholder="Project scope" options={SCOPES} onChange={(v) => set('project_scope', v)} />
          </FilterField>
          <FilterField id="remarks" label="Remarks" className="min-w-56 flex-1">
            <Input id="remarks" className="h-9" value={details.remarks} onChange={(e) => set('remarks', e.target.value)} placeholder="e.g. corrected workbook" />
          </FilterField>
          <div className="flex flex-wrap items-end gap-2">
            <input ref={input} type="file" accept=".xlsx,.xlsm" className="hidden" aria-label="RCA workbook"
              onChange={(e) => { setFile(e.target.files?.[0] ?? null); setBatch(null); }} />
            <Button type="button" variant="outline" className="h-9" onClick={() => input.current?.click()}><Upload /> Choose workbook</Button>
            <span className="max-w-56 truncate pb-2 text-sm text-muted-foreground" title={file?.name}>{file ? file.name : 'No file chosen'}</span>
            <Button type="submit" className="h-9" disabled={!ready || busy}>{busy && !batch ? 'Validating…' : 'Validate workbook'}</Button>
          </div>
        </form>
        <p className="text-xs text-muted-foreground">
          The data sheet (e.g. “RCA Backup”) is found by its columns: Date, Project, Circle, Site ID, Site Name, OA, BA, O&M Start (Yes/No), Outage Min., Final Bucket, Bucket - 2, RCA.
          Rows dated after the reporting date are rejected; every row needs a project of the scope and a Site ID of the Up-Time Report. Nothing is imported until you confirm.
        </p>
        {error && <Alert variant="destructive"><AlertDescription>{error}</AlertDescription></Alert>}
      </Card>

      {batch && <RcaImportPreview key={batch.id} batch={batch} busy={busy} onCommit={commit} onDiscard={discard} />}
      {result && <UploadSummary batch={result} />}

      <Card className="gap-2 rounded-xl px-5 py-4" aria-label="My uploads">
        <h2 className="text-base font-semibold">My uploads</h2>
        {history.data && <p className="text-xs text-muted-foreground">{formatNumber(history.data.records)} accepted RCA records in the database in total.{user?.role === 'admin' && <> Every user's uploads are on <Link to="/rca/submissions" className="underline">RCA Submissions</Link>.</>}</p>}
        {history.data?.imports.length ? (
          <div className="overflow-x-auto">
            <Table>
              <TableHeader><TableRow>{['#', 'Report', 'Period', 'File', 'Uploaded', 'Status', 'Imported · updated · skipped · rejected', ''].map((h) => <TableHead key={h}>{h}</TableHead>)}</TableRow></TableHeader>
              <TableBody>
                {history.data.imports.map((b) => (
                  <TableRow key={b.id}>
                    <TableCell>{b.id}</TableCell>
                    <TableCell className="max-w-48 truncate" title={b.report_name ?? ''}>{b.report_name ?? '—'}</TableCell>
                    <TableCell className="whitespace-nowrap">{periodText(b.period_start, b.period_end)}</TableCell>
                    <TableCell className="max-w-48 truncate" title={b.file}>{b.file}</TableCell>
                    <TableCell className="whitespace-nowrap">{formatDateTime(b.uploaded_at)}</TableCell>
                    <TableCell>{b.status_label}{b.correction && <span className="ml-1 text-xs text-amber-800">(correction)</span>}</TableCell>
                    <TableCell className="text-xs tabular-nums">{b.status === 'committed' ? `${n(b.counts.inserted)} · ${n(b.counts.updated)} · ${n(b.counts.skipped)} · ${n(b.counts.rejected)}` : b.error ?? '—'}</TableCell>
                    <TableCell><Button type="button" size="sm" variant="ghost" onClick={() => open(b.id)}>View</Button></TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </div>
        ) : <p className="text-sm text-muted-foreground">{history.error ? history.error.message : history.data ? 'You have not uploaded RCA data yet.' : 'Loading…'}</p>}
      </Card>
    </div>
  );
}

const n = (v: number | boolean | undefined) => (typeof v === 'number' ? formatNumber(v) : '—');

/** The result of one upload: its details, counts, project / circle breakdown and downloads. */
function UploadSummary({ batch }: { batch: RcaImportBatch }) {
  const c = batch.counts;
  const r = batch.report;
  const imported = batch.status === 'committed';
  const byProject: Record<string, number> = {};
  for (const [key, count] of Object.entries(r?.circles ?? {})) byProject[key.split('|')[0]] = (byProject[key.split('|')[0]] ?? 0) + count;
  const tiles: [string, number | boolean | undefined][] = imported
    ? [['Rows in workbook', c.total], ['Imported (new)', c.inserted], ['Updated', c.updated], ['Skipped or duplicate', c.skipped], ['Rejected', c.rejected], ['Withdrawn', c.withdrawn]]
    : [['Rows in workbook', c.total], ['Valid', c.valid], ['Rejected', c.rejected]];
  return (
    <Card className="gap-3 rounded-xl px-5 py-4" aria-label="Upload summary">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h2 className="text-base font-semibold">{batch.report_name ?? batch.file}</h2>
          <p className="text-xs text-muted-foreground">
            Reporting period {periodText(batch.period_start, batch.period_end)} · {batch.file} · uploaded {formatDateTime(batch.uploaded_at)} by {batch.imported_by ?? '—'}
            {batch.committed_at ? ` · imported ${formatDateTime(batch.committed_at)}` : ''}
          </p>
          {batch.remarks && <p className="text-xs">Remarks: {batch.remarks}</p>}
        </div>
        <div className="flex flex-col items-end gap-1 text-sm">
          <span className="font-medium">Status: {batch.status_label}{batch.correction ? ' (correction)' : ''}</span>
          <a href={rcaIssuesUrl(batch.id)} className="inline-flex items-center gap-1 underline underline-offset-2"><Download className="size-4" /> Validation report (CSV)</a>
          {imported && batch.cycle && <a href={rcaImportWorkbookUrl(batch.id)} className="inline-flex items-center gap-1 underline underline-offset-2"><Download className="size-4" /> Consolidated RCA report (Excel)</a>}
        </div>
      </div>
      {batch.error && <Alert variant={imported ? 'default' : 'destructive'}><AlertDescription>{batch.error}</AlertDescription></Alert>}
      <dl className="grid gap-3 sm:grid-cols-3 lg:grid-cols-6">
        {tiles.map(([label, value]) => (
          <div key={label} className="rounded-lg border px-3 py-2">
            <dt className="text-xs text-muted-foreground">{label}</dt>
            <dd className="text-lg font-semibold tabular-nums">{n(value)}</dd>
          </div>
        ))}
      </dl>
      {r && (
        <div className="grid gap-4 text-sm lg:grid-cols-3">
          <List title="Project-wise (valid rows)" items={Object.entries(byProject)} />
          <List title="Circle-wise (valid rows)" items={Object.entries(r.circles).map(([k, v]) => [k.replace('|', ' / '), v])} />
          <div>
            <h3 className="mb-1 text-xs font-semibold text-muted-foreground uppercase">Recorded outage</h3>
            <p className="tabular-nums">{formatMin(r.outage_minutes)} <span className="text-xs text-muted-foreground">(valid rows with a value)</span></p>
            {r.rca_not_applicable_rows != null && <p className="text-xs text-muted-foreground">Other Media (RCA not applicable): {formatNumber(r.rca_not_applicable_rows)} · RCA information missing: {formatNumber(r.missing_rca_rows ?? 0)}</p>}
          </div>
        </div>
      )}
    </Card>
  );
}

function List({ title, items }: { title: string; items: [string, number][] }) {
  return (
    <div>
      <h3 className="mb-1 text-xs font-semibold text-muted-foreground uppercase">{title}</h3>
      <ul className="space-y-0.5">
        {items.map(([k, v]) => <li key={k} className="flex justify-between gap-3"><span>{k}</span><span className="tabular-nums">{formatNumber(v)}</span></li>)}
      </ul>
    </div>
  );
}
