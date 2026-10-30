import { useState } from 'react';
import { Link } from 'react-router-dom';
import { CircleAlert, CircleCheck, Download, History, Info, Loader2, ShieldCheck, UserRound } from 'lucide-react';
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert';
import { Button } from '@/components/ui/button';
import { Card } from '@/components/ui/card';
import { Input } from '@/components/ui/input';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table';
import { cn } from '@/lib/utils';
import { SelectField } from '../../components/data/DataEntry';
import { DetailField, FileDropZone, UploadSteps, type FileStatus } from '../../components/data/UploadParts';
import { PageHeading } from '../../context/pageHeader';
import { RcaImportPreview, type CommitChoices } from '../../components/rca/RcaImportPreview';
import { useAuth } from '../../context/auth';
import { useApiQuery } from '../../hooks/useApiQuery';
import { formatBytes } from '../../lib/dataEntry';
import { formatDateTime, formatNumber } from '../../lib/format';
import { formatMin, periodText } from '../../lib/rca';
import { commitRcaImport, discardRcaImport, fetchRcaImport, fetchRcaImports, previewRcaImport, rcaImportWorkbookUrl, rcaIssuesUrl } from '../../services/api';
import type { RcaImportBatch, RcaProjectScope, RcaUploadDetails } from '../../types/rca';

const SCOPES: { value: RcaProjectScope; label: string }[] = [
  { value: 'both', label: 'Both (4G Saturation and LWE)' }, { value: '4G Saturation', label: '4G Saturation' }, { value: 'LWE', label: 'LWE' },
];
const EMPTY: RcaUploadDetails = { report_name: '', period_start: '', period_end: '', project_scope: 'both', remarks: '' };
const WORKBOOK_TYPES = ['.xlsx', '.xlsm'];
type Phase = 'idle' | 'validating' | 'importing' | 'discarding' | 'loading';
type ErrorPhase = 'validate' | 'import' | 'other';

/**
 * Upload RCA Data (NOC Lead and Admin): enter the report details, upload the completed RCA workbook, check the
 * validation and confirm the import. The uploader is the signed-in account. Each user sees their own uploads here;
 * Admins monitor every upload on RCA Submissions. The layout matches Upload CSV (shared UploadParts); the RCA workflow,
 * checks and API are its own.
 */
export function RcaImportPage() {
  const { user } = useAuth();
  const [version, setVersion] = useState(0);
  const history = useApiQuery(`rca-imports-${version}`, (signal) => fetchRcaImports(signal));
  const maxBytes = history.data?.max_bytes ?? null;
  const [details, setDetails] = useState<RcaUploadDetails>(EMPTY);
  const [file, setFile] = useState<File | null>(null);
  const [batch, setBatch] = useState<RcaImportBatch | null>(null);
  const [result, setResult] = useState<RcaImportBatch | null>(null);
  const [phase, setPhase] = useState<Phase>('idle');
  const [error, setError] = useState<{ phase: ErrorPhase; message: string } | null>(null);
  const [touched, setTouched] = useState<Record<string, boolean>>({});
  const busy = phase !== 'idle';
  // Any change to the details or the file makes an earlier validation stale: it is cleared so it can never be imported by mistake.
  const set = (key: keyof RcaUploadDetails, value: string) => { setDetails((d) => ({ ...d, [key]: value })); setBatch(null); setError(null); };
  const changeFile = (next: File | null) => { setFile(next); setBatch(null); setError(null); setTouched((t) => ({ ...t, file: true })); };

  async function run(kind: Phase, action: () => Promise<void>) {
    setPhase(kind);
    setError(null);
    try {
      await action();
    } catch (e) {
      setError({ phase: kind === 'validating' ? 'validate' : kind === 'importing' ? 'import' : 'other', message: e instanceof Error ? e.message : String(e) });
    } finally {
      setPhase('idle');
    }
  }
  const validate = () => run('validating', async () => {
    setResult(null);
    setBatch(await previewRcaImport(file!, details));
    setVersion((v) => v + 1);
  });
  const commit = (choices: CommitChoices) => run('importing', async () => {
    const done = await commitRcaImport(batch!.id, choices);
    setResult(done);
    setBatch(null);
    setFile(null);
    setDetails(EMPTY);
    setTouched({});
    setVersion((v) => v + 1);
  });
  const discard = () => run('discarding', async () => { await discardRcaImport(batch!.id); setBatch(null); setVersion((v) => v + 1); });
  const open = (id: number) => run('loading', async () => { setBatch(null); setResult(await fetchRcaImport(id)); });

  const errors = {
    report_name: details.report_name.trim() ? null : 'Enter the report name.',
    period_start: details.period_start ? null : 'Choose the reporting date.',
    period_end: details.period_end && details.period_start && details.period_end < details.period_start ? 'The last day is before the reporting date.' : null,
    file: file ? null : 'Choose the RCA workbook.',
  };
  const missing = [errors.report_name && 'report name', errors.period_start && 'reporting date', errors.file && 'RCA workbook'].filter(Boolean) as string[];
  const show = (field: keyof typeof errors) => (touched[field] ? errors[field] : null);
  const checkFile = (picked: File) => (!WORKBOOK_TYPES.some((t) => picked.name.toLowerCase().endsWith(t)) ? `${picked.name}: choose the RCA workbook (.xlsx or .xlsm).`
    : picked.size === 0 ? `${picked.name} is empty.` : maxBytes && picked.size > maxBytes ? `${picked.name} is larger than ${formatBytes(maxBytes)}.` : null);

  // Steps from what the server reported, never ahead of it.
  const shown = batch ?? result;
  const committed = result?.status === 'committed';
  const ready = batch?.status === 'previewed';
  const validateFailed = (!!shown && !committed && !ready && shown.status !== 'discarded') || error?.phase === 'validate';
  const fileStatus: FileStatus | null = !file ? null
    : phase === 'validating' ? { label: 'Validating on the server…', tone: 'border-sky-300 bg-sky-50 text-sky-800' }
      : phase === 'importing' ? { label: 'Import in progress…', tone: 'border-sky-300 bg-sky-50 text-sky-800' }
        : error?.phase === 'import' ? { label: 'Import failed', tone: 'border-red-300 bg-red-50 text-red-800' }
          : error?.phase === 'validate' ? { label: 'Validation failed', tone: 'border-red-300 bg-red-50 text-red-800' }
            : batch?.status === 'previewed' ? { label: 'Validation passed', tone: 'border-emerald-300 bg-emerald-50 text-emerald-800' }
              : batch ? { label: 'Rejected — see the validation result', tone: 'border-red-300 bg-red-50 text-red-800' }
                : { label: 'Ready to validate', tone: 'border-slate-300 bg-slate-50 text-slate-700' };

  return (
    <div className="space-y-4">
      <PageHeading title="Upload RCA Data"
        subtitle="Upload and validate completed RCA reports, review records, and import them into the RCA reporting database." />
      <UploadSteps steps={[
        ['Upload', shown ? 'done' : phase === 'validating' ? 'active' : 'current'],
        ['Validate & Preview', committed || ready ? 'done' : validateFailed ? 'failed' : phase === 'validating' ? 'active' : 'todo'],
        ['Confirm Import', committed ? 'done' : error?.phase === 'import' ? 'failed' : phase === 'importing' ? 'active' : ready ? 'current' : 'todo'],
        ['Results', committed ? 'done' : 'todo'],
      ]} />

      <form aria-label="Report details" className="grid items-stretch gap-4 lg:grid-cols-5"
        onSubmit={(e) => { e.preventDefault(); setTouched({ report_name: true, period_start: true, file: true }); if (!missing.length && !errors.period_end) void validate(); }}>
        <Card className="gap-3 rounded-xl px-4 py-3 lg:col-span-2" aria-label="Upload details">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <h2 className="text-sm font-semibold">Upload details</h2>
            <span className="inline-flex items-center gap-1 rounded-full border bg-muted/40 px-2 py-0.5 text-[11px] text-muted-foreground" title="The uploader is the signed-in account">
              <UserRound className="size-3" aria-hidden="true" /> uploaded as {user?.username ?? '—'}
            </span>
          </div>
          <div className="grid gap-3 sm:grid-cols-2">
            <div className="sm:col-span-2">
              <DetailField id="report-name" label="Report name" required error={show('report_name')}>
                <Input id="report-name" className="h-9" value={details.report_name} disabled={busy} aria-invalid={show('report_name') ? true : undefined}
                  onChange={(e) => set('report_name', e.target.value)} onBlur={() => setTouched((t) => ({ ...t, report_name: true }))} placeholder="e.g. October 2026 RCA Report" />
              </DetailField>
            </div>
            <DetailField id="period-start" label="Reporting date" required error={show('period_start')}>
              <Input id="period-start" type="date" className="h-9" value={details.period_start} disabled={busy} aria-invalid={show('period_start') ? true : undefined}
                onChange={(e) => set('period_start', e.target.value)} onBlur={() => setTouched((t) => ({ ...t, period_start: true }))} />
            </DetailField>
            <DetailField id="period-end" label="Last day (multi-day period)" error={errors.period_end}>
              <Input id="period-end" type="date" className="h-9" value={details.period_end} min={details.period_start || undefined} disabled={busy}
                onChange={(e) => set('period_end', e.target.value)} />
            </DetailField>
            <DetailField id="project-scope" label="Project scope" required>
              <SelectField id="project-scope" value={details.project_scope} placeholder="Project scope" options={SCOPES} disabled={busy} onChange={(v) => set('project_scope', v)} />
            </DetailField>
            <DetailField id="remarks" label="Remarks (optional)">
              <Input id="remarks" className="h-9" value={details.remarks} disabled={busy} onChange={(e) => set('remarks', e.target.value)} placeholder="e.g. corrected workbook" />
            </DetailField>
          </div>
          <div className="rounded-lg border bg-muted/30 px-3 py-2 text-xs text-muted-foreground">
            <p className="flex items-center gap-1.5 font-medium text-foreground"><Info className="size-3.5" aria-hidden="true" /> How the workbook is checked</p>
            <p className="mt-1">The data sheet (e.g. “RCA Backup”) is found by its columns: Date, Project, Circle, Site ID, Site Name, OA, BA, O&amp;M Start (Yes/No), Outage Min., Final Bucket, Bucket - 2, RCA.</p>
            <p className="mt-1">Daily workbooks are cumulative: earlier dates are compared, never removed. Rows dated after the reporting date are rejected; every row needs a project of the scope and a Site ID of the Up-Time Report.</p>
          </div>
        </Card>

        <Card className="gap-3 rounded-xl px-4 py-3 lg:col-span-3" aria-label="RCA workbook file">
          <FileDropZone inputId="rca-file" inputLabel="RCA workbook" accept=".xlsx,.xlsm" kind="Excel workbook" file={file} status={fileStatus} busy={busy}
            spinning={busy} title="Upload your RCA workbook" dropTitle="Drop the workbook to select it"
            description="Drag and drop the completed RCA workbook here, or browse files from your computer." oneFileMessage="Drop one workbook at a time."
            hint={<>The daily RCA workbook as .xlsx or .xlsm{maxBytes ? `, up to ${formatBytes(maxBytes)}` : ''}. The server checks every row before anything is imported, and nothing is saved until you confirm.</>}
            requiredError={show('file')} check={checkFile} onFile={changeFile} />
          {error?.phase === 'validate' && (
            <Alert variant="destructive" role="alert"><CircleAlert /><AlertTitle>The workbook could not be validated</AlertTitle><AlertDescription>{error.message}</AlertDescription></Alert>
          )}
          <div className="mt-auto flex flex-wrap items-center justify-end gap-3 border-t pt-3">
            {missing.length > 0 && <p className="mr-auto text-xs text-muted-foreground">Still needed: {missing.join(', ')}.</p>}
            <Button type="submit" size="lg" disabled={missing.length > 0 || !!errors.period_end || busy}>
              {phase === 'validating' ? <><Loader2 className="animate-spin" /> Validating…</> : <><ShieldCheck /> Validate workbook</>}
            </Button>
          </div>
        </Card>
      </form>

      {error?.phase === 'other' && <Alert variant="destructive" role="alert"><AlertDescription>{error.message}</AlertDescription></Alert>}
      {batch && <RcaImportPreview key={batch.id} batch={batch} busy={busy} onCommit={commit} onDiscard={discard} />}
      {error?.phase === 'import' && (
        <Alert variant="destructive" role="alert"><CircleAlert /><AlertTitle>The import did not complete</AlertTitle><AlertDescription>{error.message} Nothing was saved.</AlertDescription></Alert>
      )}
      {result?.status === 'committed' && (
        <Alert className="border-emerald-200 bg-emerald-50/70" role="status">
          <CircleCheck className="text-emerald-700" />
          <AlertTitle>Import complete</AlertTitle>
          <AlertDescription>Upload #{result.id} was imported into the RCA reporting database.</AlertDescription>
        </Alert>
      )}
      {result && <UploadSummary batch={result} />}

      <Card className="gap-2 rounded-xl px-4 py-3" aria-label="My uploads">
        <div className="flex flex-wrap items-center gap-2">
          <History className="size-4 text-muted-foreground" aria-hidden="true" />
          <h2 className="text-sm font-semibold">My uploads</h2>
          {history.data && <p className="text-xs text-muted-foreground">· {formatNumber(history.data.records)} accepted RCA records in the database in total.{user?.role === 'admin' && <> Every user's uploads are on <Link to="/rca/submissions" className="underline">RCA Submissions</Link>.</>}</p>}
        </div>
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
                    <TableCell className={cn((b.status === 'failed' || b.status === 'rejected') && 'text-destructive')}>{b.status_label}{b.correction && <span className="ml-1 text-xs text-amber-800">(correction)</span>}</TableCell>
                    <TableCell className="max-w-72 truncate text-xs tabular-nums" title={b.status === 'committed' ? undefined : b.error ?? undefined}>{b.status === 'committed' ? `${n(b.counts.inserted)} · ${n(b.counts.updated)} · ${n(b.counts.skipped)} · ${n(b.counts.rejected)}` : b.error ?? '—'}</TableCell>
                    <TableCell><Button type="button" size="sm" variant="ghost" disabled={busy} onClick={() => open(b.id)}>View</Button></TableCell>
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
    <Card className="gap-3 rounded-xl px-4 py-3" aria-label="Upload summary">
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
