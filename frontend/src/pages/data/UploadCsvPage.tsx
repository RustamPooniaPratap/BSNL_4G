import { useRef, useState, type DragEvent, type ReactNode } from 'react';
import { Check, CircleAlert, CircleCheck, CloudUpload, Download, FileSpreadsheet, FolderOpen, History, Info, Loader2, MapPin, RefreshCw, ShieldCheck, X } from 'lucide-react';
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card } from '@/components/ui/card';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Skeleton } from '@/components/ui/skeleton';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table';
import { cn } from '@/lib/utils';
import { SelectField } from '../../components/data/DataEntry';
import { ReportDownloadCard } from '../../components/data/ReportDownload';
import { PageHeading } from '../../context/pageHeader';
import { useAuth } from '../../context/auth';
import { useWorkbook } from '../../context/workbook';
import { useApiQuery } from '../../hooks/useApiQuery';
import { formatBytes } from '../../lib/dataEntry';
import { formatDate, formatDateTime, formatNumber } from '../../lib/format';
import {
  commitRawUpload, discardRawUpload, fetchRawUploadOptions, fetchRawUploadRows, fetchRawUploads, fetchRawUpload, previewRawUpload,
  rawUploadIssuesUrl,
} from '../../services/api';
import type { RawProject, RawRowStatus, RawUpload, RawUploadOptions } from '../../types/rawUpload';

const STATUS: Record<RawRowStatus, { label: string; tone: string }> = {
  ready: { label: 'Ready', tone: 'border-emerald-300 bg-emerald-50 text-emerald-800' },
  identical: { label: 'Already stored', tone: 'border-slate-300 bg-slate-50 text-slate-700' },
  duplicate: { label: 'Duplicate / conflict', tone: 'border-amber-300 bg-amber-50 text-amber-800' },
  out_of_scope: { label: 'Out of scope', tone: 'border-slate-300 bg-slate-100 text-slate-600' },
  scope_mismatch: { label: 'Project / circle mismatch', tone: 'border-orange-300 bg-orange-50 text-orange-800' },
  unresolved: { label: 'Unresolved ID', tone: 'border-orange-300 bg-orange-50 text-orange-800' },
  availability: { label: 'Availability problem', tone: 'border-red-300 bg-red-50 text-red-800' },
  date: { label: 'Date problem', tone: 'border-red-300 bg-red-50 text-red-800' },
  other: { label: 'Invalid row', tone: 'border-red-300 bg-red-50 text-red-800' },
};

/**
 * Data Entry -> Upload CSV: the raw daily CNMC availability file of one circle and date. The server validates it against
 * the approved site master, calculates outage minutes and shows a preview; nothing is saved until the import is
 * confirmed, and the result shown is the server's. The dashboard source setting is never changed by an import.
 */
export function UploadCsvPage() {
  const { user } = useAuth();
  const workbook = useWorkbook();
  const [version, setVersion] = useState(0);
  const options = useApiQuery('raw-upload-options', (signal) => fetchRawUploadOptions(signal));
  const history = useApiQuery(`raw-uploads-${version}`, (signal) => fetchRawUploads(signal));
  const [batch, setBatch] = useState<RawUpload | null>(null);
  const [phase, setPhase] = useState<Phase>('idle');
  const [error, setError] = useState<{ phase: 'validate' | 'import' | 'other'; message: string } | null>(null);
  const [form, setForm] = useState<FormState>({ project: '4G Saturation', circle: '', day: '', remarks: '' });
  const [file, setFile] = useState<File | null>(null);
  const o = options.data;
  const fixed = o?.assigned_circles?.length === 1 ? o.assigned_circles[0] : null;
  const circle = fixed ?? form.circle;

  const run = async (kind: Phase, action: () => Promise<void>) => {
    setPhase(kind);
    setError(null);
    try {
      await action();
    } catch (e) {
      setError({ phase: kind === 'validating' ? 'validate' : kind === 'importing' ? 'import' : 'other', message: e instanceof Error ? e.message : String(e) });
    } finally {
      setPhase('idle');
    }
  };
  // Any change to the file or the details makes an earlier preview stale: it is cleared so it can never be imported by mistake.
  const changeFile = (next: File | null) => { setFile(next); setBatch(null); setError(null); };
  const changeForm = (patch: Partial<FormState>) => { setForm((f) => ({ ...f, ...patch })); setBatch(null); setError(null); };
  const validate = () => file && run('validating', async () => {
    setBatch(await previewRawUpload(file, { project: form.project, circle, reporting_date: form.day, remarks: form.remarks }));
    setVersion((v) => v + 1);
  });

  return (
    <div className="space-y-4">
      <PageHeading title="Raw Data Upload & Consolidation"
        subtitle="Upload daily CNMC availability data, validate site scope, calculate outage minutes, and update the reporting database." />
      <WorkflowSteps batch={batch} phase={phase} error={error?.phase ?? null} />
      {options.error && <Alert variant="destructive"><AlertDescription>{options.error.message}</AlertDescription></Alert>}
      {!o && !options.error && <Skeleton className="h-64 w-full" />}
      {o && o.assigned_circles?.length === 0 && (
        <Alert variant="destructive" role="alert">
          <CircleAlert />
          <AlertTitle>No circle is assigned to your account</AlertTitle>
          <AlertDescription>Raw daily data can be uploaded only for assigned circles. Ask an Admin to assign your circle on Users &amp; Roles.</AlertDescription>
        </Alert>
      )}
      {o && (
        <UploadPanel options={o} username={user?.username ?? ''} form={form} circle={circle} fixed={fixed} file={file} batch={batch} phase={phase}
          error={error} onForm={changeForm} onFile={changeFile} onValidate={validate} />
      )}
      {error?.phase === 'other' && <Alert variant="destructive" role="alert"><AlertDescription>{error.message}</AlertDescription></Alert>}
      {batch && (
        <PreviewCard key={batch.id} batch={batch} busy={phase !== 'idle'}
          onCommit={() => run('importing', async () => {
            setBatch(await commitRawUpload(batch.id));
            setVersion((v) => v + 1);
            workbook.refresh();  // database-backed pages reload their figures; the source setting is unchanged
          })}
          onDiscard={() => run('discarding', async () => { await discardRawUpload(batch.id); setBatch(null); setVersion((v) => v + 1); })} />
      )}
      {error?.phase === 'import' && (
        <Alert variant="destructive" role="alert"><CircleAlert /><AlertTitle>The import did not complete</AlertTitle><AlertDescription>{error.message} Nothing was saved.</AlertDescription></Alert>
      )}
      <div className="grid items-start gap-4 xl:grid-cols-5">
        {o && <div className="xl:col-span-2"><ReportDownloadCard options={o} /></div>}
        <Card className="gap-2 rounded-xl px-4 py-3 xl:col-span-3" aria-label="My uploads">
          <div className="flex items-center gap-2">
            <History className="size-4 text-muted-foreground" aria-hidden="true" />
            <h2 className="text-sm font-semibold">{user?.role === 'admin' ? 'Raw uploads' : 'My uploads'}</h2>
          </div>
          {history.data?.uploads.length ? (
            <div className="overflow-x-auto">
              <Table>
                <TableHeader><TableRow>{['#', 'File', 'Project', 'Circle', 'Reporting date', 'Uploaded', 'By', 'Status', 'Inserted · skipped · rejected', ''].map((h) => <TableHead key={h}>{h}</TableHead>)}</TableRow></TableHeader>
                <TableBody>
                  {history.data.uploads.map((b) => (
                    <TableRow key={b.id}>
                      <TableCell>{b.id}</TableCell>
                      <TableCell className="max-w-40 truncate" title={b.file}>{b.file}</TableCell>
                      <TableCell>{b.project}</TableCell>
                      <TableCell>{b.circle}</TableCell>
                      <TableCell className="whitespace-nowrap">{formatDate(b.reporting_date)}</TableCell>
                      <TableCell className="whitespace-nowrap">{formatDateTime(b.uploaded_at)}</TableCell>
                      <TableCell>{b.uploaded_by ?? '—'}</TableCell>
                      <TableCell className={cn((b.status === 'failed' || b.status === 'rejected') && 'text-destructive')}>{b.status_label}</TableCell>
                      <TableCell className="text-xs tabular-nums">{b.daily ? `${formatNumber(b.daily.inserted + b.daily.filled)} · ${formatNumber(b.daily.skipped_identical + b.daily.skipped_repeats)} · ${formatNumber(b.daily.rejected)}` : b.error ? <span className="text-destructive">{b.error}</span> : '—'}</TableCell>
                      <TableCell><Button type="button" size="sm" variant="ghost" onClick={() => run('loading', async () => setBatch(await fetchRawUpload(b.id)))}>View</Button></TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </div>
          ) : <p className="text-sm text-muted-foreground">{history.error ? history.error.message : history.data ? 'No raw uploads yet.' : 'Loading…'}</p>}
        </Card>
      </div>
    </div>
  );
}

type Phase = 'idle' | 'validating' | 'importing' | 'discarding' | 'loading';
interface FormState { project: RawProject; circle: string; day: string; remarks: string }
type StepState = 'todo' | 'current' | 'active' | 'done' | 'failed';

/** Upload -> Validate & Preview -> Confirm Import -> Results, from what the server actually reported (never ahead of it). */
function WorkflowSteps({ batch, phase, error }: { batch: RawUpload | null; phase: Phase; error: 'validate' | 'import' | 'other' | null }) {
  const accepted = !!batch;  // the server received the file and recorded the upload
  const ready = batch?.status === 'previewed' && !!batch.summary?.ready_to_import;
  const committed = batch?.status === 'committed';
  const validateFailed = (!!batch && !committed && !ready && batch.status !== 'discarded') || error === 'validate';
  const steps: [string, StepState][] = [
    ['Upload', accepted ? 'done' : phase === 'validating' ? 'active' : 'current'],
    ['Validate & Preview', committed || ready ? 'done' : validateFailed ? 'failed' : phase === 'validating' ? 'active' : 'todo'],
    ['Confirm Import', committed ? 'done' : error === 'import' ? 'failed' : phase === 'importing' ? 'active' : ready ? 'current' : 'todo'],
    ['Results', committed ? 'done' : 'todo'],
  ];
  return (
    <Card className="rounded-xl px-4 py-2.5 shadow-xs">
      <ol className="flex flex-wrap items-center gap-x-2 gap-y-1.5 text-xs" aria-label="Upload progress">
        {steps.map(([label, state], i) => (
          <li key={label} className="flex items-center gap-2" aria-current={state === 'current' || state === 'active' ? 'step' : undefined}
            data-state={state}>
            <span className={cn('flex size-6 shrink-0 items-center justify-center rounded-full border text-[11px] font-semibold',
              state === 'done' && 'border-emerald-600 bg-emerald-600 text-white',
              state === 'failed' && 'border-destructive bg-destructive text-white',
              (state === 'current' || state === 'active') && 'border-primary text-primary',
              state === 'todo' && 'text-muted-foreground')}>
              {state === 'done' ? <Check className="size-3.5" aria-hidden="true" /> : state === 'failed' ? <X className="size-3.5" aria-hidden="true" />
                : state === 'active' ? <Loader2 className="size-3.5 animate-spin" aria-hidden="true" /> : i + 1}
            </span>
            <span className={cn('font-medium', state === 'todo' && 'text-muted-foreground', state === 'failed' && 'text-destructive')}>
              {label}<span className="sr-only"> ({STEP_TEXT[state]})</span>
            </span>
            {i < steps.length - 1 && <span className="mx-1 h-px w-6 bg-border sm:w-10" aria-hidden="true" />}
          </li>
        ))}
      </ol>
    </Card>
  );
}
const STEP_TEXT: Record<StepState, string> = { todo: 'not started', current: 'next', active: 'in progress', done: 'completed', failed: 'did not pass' };

function UploadPanel({ options, username, form, circle, fixed, file, batch, phase, error, onForm, onFile, onValidate }: {
  options: RawUploadOptions; username: string; form: FormState; circle: string; fixed: string | null; file: File | null; batch: RawUpload | null;
  phase: Phase; error: { phase: string; message: string } | null; onForm: (patch: Partial<FormState>) => void; onFile: (file: File | null) => void;
  onValidate: () => void;
}) {
  const input = useRef<HTMLInputElement>(null);
  const [dragging, setDragging] = useState(false);
  const [fileError, setFileError] = useState<string | null>(null);
  const [touched, setTouched] = useState<Record<string, boolean>>({});
  const project = options.projects.find((p) => p.value === form.project);
  const circles = project?.circles ?? [];
  const [today] = useState(() => new Date().toLocaleDateString('en-CA'));  // the user's local date, YYYY-MM-DD
  const errors = {
    circle: !circle ? 'Choose the circle of the file.' : !circles.includes(circle) ? `You cannot upload ${form.project} data for ${circle}.` : null,
    day: !form.day ? 'Choose the reporting date of the file.' : form.day > today ? 'The reporting date cannot be in the future.' : null,
    file: !file ? 'Choose the CSV file.' : null,
  };
  const missing = [errors.circle && 'circle', errors.day && 'reporting date', errors.file && 'CSV file'].filter(Boolean) as string[];
  const busy = phase !== 'idle';
  const show = (field: keyof typeof errors) => (touched[field] ? errors[field] : null);
  const pick = (picked: File | null) => {
    setFileError(null);
    setTouched((t) => ({ ...t, file: true }));
    if (input.current) input.current.value = '';  // the same file can be chosen again after Remove
    if (!picked) return onFile(null);
    const problem = !picked.name.toLowerCase().endsWith('.csv') ? `${picked.name}: choose the CSV file exported from CNMC (.csv).`
      : picked.size === 0 ? `${picked.name} is empty.` : picked.size > options.max_bytes ? `${picked.name} is larger than ${formatBytes(options.max_bytes)}.` : null;
    if (problem) {
      setFileError(problem);
      return onFile(null);
    }
    onFile(picked);
  };
  const onDrop = (event: DragEvent<HTMLDivElement>) => {
    event.preventDefault();
    setDragging(false);
    if (busy) return;
    const files = event.dataTransfer.files;
    if (files.length > 1) {
      setFileError('Drop one CSV file at a time.');
      return onFile(null);
    }
    pick(files[0] ?? null);
  };
  const fileState: { label: string; tone: string } | null = !file ? null
    : phase === 'validating' ? { label: 'Validating on the server…', tone: 'border-sky-300 bg-sky-50 text-sky-800' }
      : phase === 'importing' ? { label: 'Import in progress…', tone: 'border-sky-300 bg-sky-50 text-sky-800' }
        : error?.phase === 'import' ? { label: 'Import failed', tone: 'border-red-300 bg-red-50 text-red-800' }
          : error?.phase === 'validate' ? { label: 'Validation failed', tone: 'border-red-300 bg-red-50 text-red-800' }
            : batch?.status === 'committed' ? { label: 'Imported', tone: 'border-emerald-300 bg-emerald-50 text-emerald-800' }
              : batch?.status === 'previewed' && batch.summary?.ready_to_import ? { label: 'Validation passed', tone: 'border-emerald-300 bg-emerald-50 text-emerald-800' }
                : batch ? { label: batch.status === 'previewed' ? 'Nothing importable' : 'Blocked — see the preview', tone: 'border-red-300 bg-red-50 text-red-800' }
                  : { label: 'Ready to validate', tone: 'border-slate-300 bg-slate-50 text-slate-700' };

  return (
    <div className="grid items-stretch gap-4 lg:grid-cols-5">
      <Card className="gap-3 rounded-xl px-4 py-3 lg:col-span-2" aria-label="Upload details">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <h2 className="text-sm font-semibold">Upload details</h2>
          <span className="inline-flex items-center gap-1 rounded-full border bg-muted/40 px-2 py-0.5 text-[11px] text-muted-foreground" title="Circles you may upload for">
            <MapPin className="size-3" aria-hidden="true" />
            {username}: {options.assigned_circles == null ? 'all circles' : options.assigned_circles.length ? options.assigned_circles.join(', ') : 'no circle'}
          </span>
        </div>
        <div className="grid gap-3 sm:grid-cols-2">
          <DetailField id="raw-project" label="Project" required>
            <SelectField id="raw-project" value={form.project} placeholder="Project" disabled={busy}
              onChange={(v) => onForm({ project: v as RawProject, ...(fixed ? {} : { circle: '' }) })}
              options={options.projects.map((p) => ({ value: p.value, label: p.configured ? p.value : `${p.value} (mapping pending)` }))} />
          </DetailField>
          <DetailField id="raw-circle" label={fixed ? 'Circle (assigned)' : 'Circle'} required error={show('circle')}>
            {fixed ? <Input id="raw-circle" className="h-9 bg-muted/40" value={fixed} readOnly aria-readonly="true" />
              : <SelectField id="raw-circle" value={form.circle} placeholder={circles.length ? 'Choose circle' : 'None available'} disabled={!circles.length || busy}
                error={show('circle')} onChange={(v) => { setTouched((t) => ({ ...t, circle: true })); onForm({ circle: v }); }}
                options={circles.map((c) => ({ value: c, label: c }))} />}
          </DetailField>
          <DetailField id="raw-date" label="Reporting date" required error={show('day')}>
            <Input id="raw-date" type="date" className="h-9" value={form.day} max={today} disabled={busy} aria-invalid={show('day') ? true : undefined}
              onChange={(e) => onForm({ day: e.target.value })} onBlur={() => setTouched((t) => ({ ...t, day: true }))} />
          </DetailField>
          <DetailField id="raw-remarks" label="Remarks (optional)">
            <Input id="raw-remarks" className="h-9" value={form.remarks} disabled={busy} onChange={(e) => onForm({ remarks: e.target.value })} placeholder="e.g. resent after correction" />
          </DetailField>
        </div>
        <div className="rounded-lg border bg-muted/30 px-3 py-2 text-xs text-muted-foreground">
          <p className="flex items-center gap-1.5 font-medium text-foreground"><Info className="size-3.5" aria-hidden="true" /> How the file is checked</p>
          <p className="mt-1">One Report Date equal to the reporting date, only the selected circle, and sites of the approved {form.project} master.
            Availability is read from <strong>{project?.availability_column}</strong>; {options.formula}. A blank availability is never read as 0.</p>
        </div>
        {!project?.configured && (
          <Alert><AlertDescription className="text-xs">
            LWE files can be validated, but no LWE row can be imported yet: the mapping of raw LWE IDs to master sites (and the 2100 / 700 MHz selection) is not configured.
          </AlertDescription></Alert>
        )}
      </Card>

      <Card className="gap-3 rounded-xl px-4 py-3 lg:col-span-3" aria-label="CSV file">
        <div
          onDragOver={(e) => { e.preventDefault(); if (!busy) setDragging(true); }}
          onDragLeave={() => setDragging(false)}
          onDrop={onDrop}
          data-dragging={dragging || undefined}
          className={cn('relative flex flex-1 flex-col items-center justify-center gap-2 rounded-xl border-2 border-dashed px-6 py-8 text-center transition-colors',
            dragging ? 'border-primary bg-primary/5' : fileError ? 'border-destructive/50 bg-destructive/5' : 'border-border bg-muted/20',
            busy && 'opacity-70')}>
          <input ref={input} id="raw-file" type="file" accept=".csv,text/csv" className="sr-only" aria-label="Raw daily CSV file" disabled={busy}
            onChange={(e) => pick(e.target.files?.[0] ?? null)} />
          <span className={cn('grid size-12 place-items-center rounded-full', dragging ? 'bg-primary text-primary-foreground' : 'bg-primary/10 text-primary')}>
            <CloudUpload className="size-6" aria-hidden="true" />
          </span>
          <h2 className="text-base font-semibold">{dragging ? 'Drop the CSV to select it' : 'Upload your daily CSV file'}</h2>
          <p className="text-sm text-muted-foreground">Drag and drop your CSV here, or browse files from your computer.</p>
          <Button type="button" variant="outline" disabled={busy} onClick={() => input.current?.click()}><FolderOpen /> Browse Files</Button>
          <p className="max-w-md text-xs text-muted-foreground">
            The daily CNMC availability dump (<span className="font-mono">nw_aval_btsipid_wise_day…</span>) as .csv, up to {formatBytes(options.max_bytes)}.
            The server checks every row before anything is imported, and nothing is saved until you confirm.
          </p>
        </div>
        {fileError && <p className="flex items-center gap-1.5 text-sm text-destructive" role="alert"><CircleAlert className="size-4" aria-hidden="true" />{fileError}</p>}
        {!file && !fileError && touched.file && <p className="text-sm text-destructive">{errors.file}</p>}
        {file && (
          <div className="flex flex-wrap items-center gap-3 rounded-lg border px-3 py-2" aria-label="Selected file">
            <span className="grid size-9 shrink-0 place-items-center rounded-md bg-emerald-50 text-emerald-700"><FileSpreadsheet className="size-5" aria-hidden="true" /></span>
            <div className="min-w-0 flex-1">
              <p className="truncate text-sm font-medium" title={file.name}>{file.name}</p>
              <p className="text-xs text-muted-foreground">CSV · {formatBytes(file.size)}</p>
            </div>
            {fileState && <Badge variant="outline" className={cn('font-medium', fileState.tone)}>{phase !== 'idle' && <Loader2 className="animate-spin" />}{fileState.label}</Badge>}
            <Button type="button" variant="ghost" size="sm" disabled={busy} onClick={() => input.current?.click()}><RefreshCw /> Replace</Button>
            <Button type="button" variant="ghost" size="sm" disabled={busy} aria-label="Remove file" onClick={() => pick(null)}><X /> Remove</Button>
          </div>
        )}
        {error?.phase === 'validate' && (
          <Alert variant="destructive" role="alert"><CircleAlert /><AlertTitle>The file could not be validated</AlertTitle><AlertDescription>{error.message}</AlertDescription></Alert>
        )}
        <div className="flex flex-wrap items-center justify-end gap-3 border-t pt-3">
          {missing.length > 0 && <p className="mr-auto text-xs text-muted-foreground">Still needed: {missing.join(', ')}.</p>}
          <Button type="button" size="lg" disabled={missing.length > 0 || busy}
            onClick={() => { setTouched({ circle: true, day: true, file: true }); if (!missing.length) onValidate(); }}>
            {phase === 'validating' ? <><Loader2 className="animate-spin" /> Validating…</> : <><ShieldCheck /> Validate CSV</>}
          </Button>
        </div>
      </Card>
    </div>
  );
}

function DetailField({ id, label, required = false, error, children }: { id: string; label: string; required?: boolean; error?: string | null; children: ReactNode }) {
  return (
    <div className="flex min-w-0 flex-col gap-1">
      <div className="flex items-center gap-1">
        <Label htmlFor={id} className="text-[11px] font-medium text-muted-foreground">{label}</Label>
        {required && <span className="text-[11px] text-destructive" aria-hidden="true" title="Required">*</span>}
      </div>
      {children}
      {error && <p id={`${id}-error`} className="text-xs text-destructive">{error}</p>}
    </div>
  );
}

const TILES: [keyof NonNullable<RawUpload['summary']>, string, string][] = [
  ['total_rows', 'Rows in file', ''], ['valid_in_scope', 'Valid, in scope', ''], ['ready_to_import', 'Ready to import', 'text-emerald-700'],
  ['identical_skipped', 'Already stored (skipped)', ''], ['out_of_scope', 'Out of scope', ''],
  ['project_or_circle_mismatches', 'Project / circle mismatch', 'text-orange-700'], ['unresolved_or_ambiguous', 'Unresolved / ambiguous', 'text-orange-700'],
  ['availability_problems', 'Missing / invalid availability', 'text-destructive'], ['duplicates_or_conflicts', 'Duplicates / conflicts', 'text-amber-700'],
  ['date_mismatches', 'Date problems', 'text-destructive'], ['other_invalid', 'Other invalid', 'text-destructive'],
];

function PreviewCard({ batch, busy, onCommit, onDiscard }: { batch: RawUpload; busy: boolean; onCommit: () => void; onDiscard: () => void }) {
  const [status, setStatus] = useState<RawRowStatus | ''>('');
  const [page, setPage] = useState(1);
  const [confirming, setConfirming] = useState(false);
  const rows = useApiQuery(`raw-rows-${batch.id}-${batch.status}-${status}-${page}`, (signal) => fetchRawUploadRows(batch.id, status, page, signal));
  const s = batch.summary;
  const committed = batch.status === 'committed';
  const canCommit = batch.status === 'previewed' && !!s?.ready_to_import;
  const byStatus = (st: RawRowStatus) => Object.entries(s?.by_code ?? {}).filter(([code]) => statusOf(code) === st).reduce((a, [, n]) => a + n, 0);
  return (
    <Card className="gap-3 rounded-xl px-4 py-3" aria-label={committed ? 'Import result' : 'Validation preview'}>
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div>
          <h2 className="text-base font-semibold">{committed ? 'Imported' : batch.status === 'previewed' ? 'Validation preview — nothing saved yet' : batch.status_label}: {batch.file}</h2>
          <p className="text-xs text-muted-foreground">
            Upload #{batch.id} · {batch.project} · {batch.circle} · {formatDate(batch.reporting_date)} · by {batch.uploaded_by ?? '—'} {formatDateTime(batch.uploaded_at)}
            {batch.file_info ? ` · header on line ${batch.file_info.header_line}${batch.file_info.preamble.length ? ` (above it: “${batch.file_info.preamble.join(' / ')}”)` : ''}` : ''}
          </p>
        </div>
        <a href={rawUploadIssuesUrl(batch.id)} className="inline-flex items-center gap-1.5 text-sm font-medium underline underline-offset-2"><Download className="size-4" /> Validation report (CSV)</a>
      </div>
      {batch.file_issues?.map((i) => (
        <Alert key={i.code} variant="destructive" role="alert"><CircleAlert /><AlertTitle>The file cannot be imported</AlertTitle><AlertDescription>{i.message}</AlertDescription></Alert>
      ))}
      {batch.status === 'failed' && batch.error && <Alert variant="destructive" role="alert"><AlertDescription>{batch.error}</AlertDescription></Alert>}
      {batch.already_imported && !committed && <Alert><AlertDescription>This exact file was already imported (upload #{batch.already_imported.batch}); importing it again adds nothing.</AlertDescription></Alert>}
      {committed && batch.daily && (
        <Alert className="border-emerald-300 bg-emerald-50" role="status">
          <CircleCheck className="text-emerald-700" />
          <AlertTitle>Saved to the database {formatDateTime(batch.committed_at)}</AlertTitle>
          <AlertDescription>
            {formatNumber(batch.daily.inserted)} daily records inserted{batch.daily.filled ? `, ${formatNumber(batch.daily.filled)} empty days filled` : ''},
            {' '}{formatNumber(batch.daily.skipped_identical)} already stored and {formatNumber(batch.daily.skipped_repeats)} repeated rows skipped, {formatNumber(batch.daily.rejected)} rows not imported.
            Database-backed dashboard pages now include them; the dashboard data source setting is unchanged.
          </AlertDescription>
        </Alert>
      )}
      {s && (
        <dl className="grid grid-cols-2 gap-2 sm:grid-cols-4 xl:grid-cols-6">
          {TILES.map(([key, label, tone]) => (
            <div key={key} className="rounded-lg border px-3 py-2">
              <dt className="text-xs text-muted-foreground">{label}</dt>
              <dd className={cn('text-lg font-semibold tabular-nums', (s[key] as number) ? tone : '')}>{formatNumber(s[key] as number)}</dd>
            </div>
          ))}
          {batch.master_scope && (
            <div className="rounded-lg border px-3 py-2">
              <dt className="text-xs text-muted-foreground">Master sites in file</dt>
              <dd className="text-lg font-semibold tabular-nums">{formatNumber(batch.master_scope.sites_in_file)} <span className="text-xs font-normal text-muted-foreground">of {formatNumber(batch.master_scope.sites)}</span></dd>
            </div>
          )}
        </dl>
      )}
      {batch.master_scope && batch.master_scope.missing_from_file > 0 && (
        <p className="text-xs text-muted-foreground">
          {formatNumber(batch.master_scope.missing_from_file)} approved {batch.project} sites of {batch.circle} have no row in this file (e.g. {batch.master_scope.missing_examples.slice(0, 5).join(', ')}); their day stays a gap, never 0.
        </p>
      )}
      {batch.availability_rule && (
        <p className="text-xs text-muted-foreground">Availability source: <strong>{batch.availability_rule.column}</strong>{batch.availability_rule.confirmed ? '' : ' (not confirmed for this project)'} · {batch.availability_rule.formula}.</p>
      )}

      <div className="flex flex-wrap items-center gap-1" role="group" aria-label="Show rows">
        {(['', 'ready', 'identical', 'duplicate', 'out_of_scope', 'scope_mismatch', 'unresolved', 'availability', 'date', 'other'] as const).map((st) => {
          const n = st ? byStatus(st) : s?.total_rows ?? 0;
          if (st && !n) return null;
          return (
            <Button key={st || 'all'} type="button" size="sm" variant={status === st ? 'default' : 'outline'} className="h-7 text-xs" aria-pressed={status === st}
              onClick={() => { setStatus(st); setPage(1); }}>
              {st ? STATUS[st].label : 'All rows'} ({formatNumber(n)})
            </Button>
          );
        })}
      </div>
      <div className="overflow-x-auto">
        <Table aria-label="Rows">
          <TableHeader>
            <TableRow>{['Line', 'Raw BTS IP ID', 'Master site', 'Circle', 'Report date', 'Availability %', 'Outage min', 'Status', 'Reason'].map((h) => <TableHead key={h}>{h}</TableHead>)}</TableRow>
          </TableHeader>
          <TableBody>
            {(rows.data?.rows ?? []).map((r) => (
              <TableRow key={r.line}>
                <TableCell className="tabular-nums">{r.line}</TableCell>
                <TableCell className="font-mono text-xs">{r.raw_id || <span className="text-muted-foreground italic">blank</span>}</TableCell>
                <TableCell className="text-xs">{r.site_id ? <><span className="font-mono">{r.site_id}</span> <span className="text-muted-foreground">{r.site_name}</span></> : '—'}</TableCell>
                <TableCell>{r.circle}</TableCell>
                <TableCell className="whitespace-nowrap">{r.report_date}</TableCell>
                <TableCell className="tabular-nums">{r.availability ?? (r.raw_availability ? <span className="text-destructive">{r.raw_availability}</span> : <span className="text-muted-foreground italic">blank</span>)}</TableCell>
                <TableCell className="tabular-nums">{r.outage_minutes == null ? '—' : r.outage_minutes.toLocaleString('en-IN', { maximumFractionDigits: 2 })}</TableCell>
                <TableCell><Badge variant="outline" className={cn('font-medium', STATUS[r.status].tone)}>{r.label}</Badge></TableCell>
                <TableCell className="max-w-96 text-xs whitespace-normal">{r.message}{r.note && <span className="block text-muted-foreground">{r.note}</span>}</TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
        {rows.error && <p className="text-sm text-destructive">{rows.error.message}</p>}
      </div>
      {rows.data && rows.data.pages > 1 && (
        <div className="flex items-center gap-2 text-xs">
          <Button type="button" size="sm" variant="outline" disabled={page <= 1} onClick={() => setPage((p) => p - 1)}>Previous</Button>
          <span>Page {rows.data.page} of {rows.data.pages} · {formatNumber(rows.data.count)} rows</span>
          <Button type="button" size="sm" variant="outline" disabled={page >= rows.data.pages} onClick={() => setPage((p) => p + 1)}>Next</Button>
        </div>
      )}

      {batch.status === 'previewed' && (
        <div className="flex flex-wrap items-center gap-2 border-t pt-3">
          {!canCommit ? <p className="text-sm text-muted-foreground">No row is ready to import.</p>
            : confirming ? (
              <>
                <p className="text-sm">Save <strong>{formatNumber(s!.ready_to_import)}</strong> daily records for {batch.circle} · {formatDate(batch.reporting_date)} to the database?</p>
                <Button type="button" onClick={onCommit} disabled={busy}>{busy ? 'Importing…' : 'Yes, import'}</Button>
                <Button type="button" variant="ghost" onClick={() => setConfirming(false)} disabled={busy}>Back</Button>
              </>
            ) : <Button type="button" onClick={() => setConfirming(true)}>Import {formatNumber(s!.ready_to_import)} record{s!.ready_to_import === 1 ? '' : 's'}…</Button>}
          <Button type="button" variant="ghost" onClick={onDiscard} disabled={busy}>Discard</Button>
        </div>
      )}
    </Card>
  );
}

/** Reason code -> preview status group (mirrors the server's grouping for the filter counts). */
function statusOf(code: string): RawRowStatus {
  const groups: Record<string, RawRowStatus> = {
    ready: 'ready', fills_missing: 'ready', identical: 'identical', duplicate_row: 'duplicate', conflicting_duplicate: 'duplicate',
    conflict_existing: 'duplicate', unknown_site: 'out_of_scope', other_circle: 'scope_mismatch', other_project: 'scope_mismatch',
    circle_mismatch: 'scope_mismatch', blank_site_id: 'unresolved', ambiguous_site: 'unresolved', lwe_mapping_not_configured: 'unresolved',
    missing_availability: 'availability', invalid_availability: 'availability', availability_out_of_range: 'availability',
    date_mismatch: 'date', invalid_date: 'date',
  };
  return groups[code] ?? 'other';
}
