import { useRef, useState } from 'react';
import { CircleAlert, CircleCheck, Download, FileText, Upload, X } from 'lucide-react';
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card } from '@/components/ui/card';
import { Input } from '@/components/ui/input';
import { Skeleton } from '@/components/ui/skeleton';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table';
import { cn } from '@/lib/utils';
import { Field, FilterCard } from '../../components/dashboard/FilterBar';
import { SelectField } from '../../components/data/DataEntry';
import { PageHeading } from '../../context/pageHeader';
import { useAuth } from '../../context/auth';
import { useWorkbook } from '../../context/workbook';
import { useApiQuery } from '../../hooks/useApiQuery';
import { formatBytes } from '../../lib/dataEntry';
import { formatDate, formatDateTime, formatNumber } from '../../lib/format';
import {
  commitRawUpload, discardRawUpload, fetchRawUploadOptions, fetchRawUploadRows, fetchRawUploads, fetchRawUpload, previewRawUpload,
  rawExportUrl, rawUploadIssuesUrl,
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
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const run = async (action: () => Promise<void>) => {
    setBusy(true);
    setError(null);
    try {
      await action();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  };
  const o = options.data;
  const scope = o?.assigned_circles == null ? 'every circle' : o.assigned_circles.length ? `circle${o.assigned_circles.length > 1 ? 's' : ''} ${o.assigned_circles.join(', ')}` : 'no circle';

  return (
    <div className="space-y-4">
      <PageHeading title="Upload CSV"
        subtitle={`Raw daily CNMC availability file · validated on the server against the approved site master · ${user?.username ?? ''}: ${scope}`} />
      {options.error && <Alert variant="destructive"><AlertDescription>{options.error.message}</AlertDescription></Alert>}
      {!o && !options.error && <Skeleton className="h-24 w-full" />}
      {o && o.assigned_circles?.length === 0 && (
        <Alert variant="destructive" role="alert">
          <CircleAlert />
          <AlertTitle>No circle is assigned to your account</AlertTitle>
          <AlertDescription>Raw daily data can be uploaded only for assigned circles. Ask an Admin to assign your circle on Users &amp; Roles.</AlertDescription>
        </Alert>
      )}
      {o && <UploadForm options={o} busy={busy} onPreview={(file, details) => run(async () => { setBatch(await previewRawUpload(file, details)); setVersion((v) => v + 1); })} />}
      {error && <Alert variant="destructive" role="alert"><AlertDescription>{error}</AlertDescription></Alert>}
      {batch && (
        <PreviewCard key={batch.id} batch={batch} busy={busy}
          onCommit={() => run(async () => {
            setBatch(await commitRawUpload(batch.id));
            setVersion((v) => v + 1);
            workbook.refresh();  // database-backed pages reload their figures; the source setting is unchanged
          })}
          onDiscard={() => run(async () => { await discardRawUpload(batch.id); setBatch(null); setVersion((v) => v + 1); })} />
      )}
      {o && <ExportCard options={o} />}
      <Card className="gap-2 rounded-xl px-4 py-3" aria-label="My uploads">
        <h2 className="text-base font-semibold">{user?.role === 'admin' ? 'Raw uploads' : 'My uploads'}</h2>
        {history.data?.uploads.length ? (
          <div className="overflow-x-auto">
            <Table>
              <TableHeader><TableRow>{['#', 'File', 'Project', 'Circle', 'Reporting date', 'Uploaded', 'By', 'Status', 'Inserted · skipped · rejected', ''].map((h) => <TableHead key={h}>{h}</TableHead>)}</TableRow></TableHeader>
              <TableBody>
                {history.data.uploads.map((b) => (
                  <TableRow key={b.id}>
                    <TableCell>{b.id}</TableCell>
                    <TableCell className="max-w-48 truncate" title={b.file}>{b.file}</TableCell>
                    <TableCell>{b.project}</TableCell>
                    <TableCell>{b.circle}</TableCell>
                    <TableCell className="whitespace-nowrap">{formatDate(b.reporting_date)}</TableCell>
                    <TableCell className="whitespace-nowrap">{formatDateTime(b.uploaded_at)}</TableCell>
                    <TableCell>{b.uploaded_by ?? '—'}</TableCell>
                    <TableCell className={cn((b.status === 'failed' || b.status === 'rejected') && 'text-destructive')}>{b.status_label}</TableCell>
                    <TableCell className="text-xs tabular-nums">{b.daily ? `${formatNumber(b.daily.inserted + b.daily.filled)} · ${formatNumber(b.daily.skipped_identical + b.daily.skipped_repeats)} · ${formatNumber(b.daily.rejected)}` : b.error ? <span className="text-destructive">{b.error}</span> : '—'}</TableCell>
                    <TableCell><Button type="button" size="sm" variant="ghost" onClick={() => run(async () => setBatch(await fetchRawUpload(b.id)))}>View</Button></TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </div>
        ) : <p className="text-sm text-muted-foreground">{history.error ? history.error.message : history.data ? 'No raw uploads yet.' : 'Loading…'}</p>}
      </Card>
    </div>
  );
}

function UploadForm({ options, busy, onPreview }: {
  options: RawUploadOptions; busy: boolean; onPreview: (file: File, details: { project: RawProject; circle: string; reporting_date: string; remarks: string }) => void;
}) {
  const input = useRef<HTMLInputElement>(null);
  const [project, setProject] = useState<RawProject>('4G Saturation');
  const circles = options.projects.find((p) => p.value === project)?.circles ?? [];
  const fixed = options.assigned_circles?.length === 1 ? options.assigned_circles[0] : null;
  const [circle, setCircle] = useState(fixed ?? '');
  const [day, setDay] = useState('');
  const [remarks, setRemarks] = useState('');
  const [file, setFile] = useState<File | null>(null);
  const [fileError, setFileError] = useState<string | null>(null);
  const configured = options.projects.find((p) => p.value === project)?.configured ?? false;
  const pick = (f: File | null) => {
    setFileError(null);
    setFile(null);
    if (!f) return;
    if (!f.name.toLowerCase().endsWith('.csv')) return setFileError(`${f.name}: choose the CSV file exported from CNMC (.csv).`);
    if (f.size > options.max_bytes) return setFileError(`${f.name} is larger than ${formatBytes(options.max_bytes)}.`);
    setFile(f);
  };
  const ready = file && circle && day && circles.includes(circle);
  return (
    <>
      <FilterCard label="Upload details"
        footer={<>Availability is read from <strong>{options.projects.find((p) => p.value === project)?.availability_column}</strong>; {options.formula}. A blank availability is never read as 0.
          {' '}The file must hold one Report Date, equal to the reporting date, and only the selected circle.</>}
        actions={<Button type="button" className="h-9" disabled={!ready || busy} onClick={() => file && onPreview(file, { project, circle, reporting_date: day, remarks })}>
          {busy ? 'Validating…' : 'Validate on server'}
        </Button>}>
        <Field id="raw-project" label="Project" className="w-40">
          <SelectField id="raw-project" value={project} placeholder="Project" onChange={(v) => { setProject(v as RawProject); if (!fixed) setCircle(''); }}
            options={options.projects.map((p) => ({ value: p.value, label: p.configured ? p.value : `${p.value} (mapping pending)` }))} />
        </Field>
        <Field id="raw-circle" label={fixed ? 'Circle (assigned)' : 'Circle'} className="w-32">
          {fixed ? <Input id="raw-circle" className="h-9" value={fixed} readOnly aria-readonly="true" />
            : <SelectField id="raw-circle" value={circle} placeholder={circles.length ? 'Circle' : 'None available'} disabled={!circles.length}
              onChange={setCircle} options={circles.map((c) => ({ value: c, label: c }))} />}
        </Field>
        <Field id="raw-date" label="Reporting date" className="w-40">
          <Input id="raw-date" type="date" className="h-9" value={day} onChange={(e) => setDay(e.target.value)} />
        </Field>
        <Field id="raw-remarks" label="Remarks (optional)" className="w-56">
          <Input id="raw-remarks" className="h-9" value={remarks} onChange={(e) => setRemarks(e.target.value)} placeholder="e.g. resent after correction" />
        </Field>
        <Field id="raw-file" label="CSV file" className="min-w-56">
          <div className="flex h-9 items-center gap-2">
            <input ref={input} id="raw-file" type="file" accept=".csv,text/csv" className="sr-only" aria-label="Raw daily CSV file"
              onChange={(e) => pick(e.target.files?.[0] ?? null)} />
            <Button type="button" variant="outline" className="h-9" onClick={() => input.current?.click()}><Upload /> Choose file</Button>
            {file ? (
              <span className="flex items-center gap-1 text-sm" title={file.name}>
                <FileText className="size-4 text-muted-foreground" aria-hidden="true" />
                <span className="max-w-40 truncate">{file.name}</span>
                <span className="text-xs text-muted-foreground">{formatBytes(file.size)}</span>
                <Button type="button" variant="ghost" size="icon" className="size-7" aria-label="Remove file"
                  onClick={() => { setFile(null); if (input.current) input.current.value = ''; }}><X /></Button>
              </span>
            ) : <span className="text-sm text-muted-foreground">No file chosen</span>}
          </div>
        </Field>
      </FilterCard>
      {fileError && <Alert variant="destructive"><AlertDescription>{fileError}</AlertDescription></Alert>}
      {!configured && (
        <Alert><AlertDescription>
          LWE files can be validated, but no LWE row can be imported yet: the mapping of raw LWE IDs to master sites (and the 2100 / 700 MHz selection) is not configured.
        </AlertDescription></Alert>
      )}
    </>
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
            ) : <Button type="button" onClick={() => setConfirming(true)}>Import {formatNumber(s!.ready_to_import)} records…</Button>}
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

function ExportCard({ options }: { options: RawUploadOptions }) {
  const [project, setProject] = useState<RawProject>('4G Saturation');
  const circles = options.projects.find((p) => p.value === project)?.circles ?? [];
  const [circle, setCircle] = useState('');
  const [from, setFrom] = useState('');
  const [to, setTo] = useState('');
  const ready = from && to && (options.assigned_circles == null || options.assigned_circles.length > 0);
  const url = (output: 'csv' | 'xlsx') => rawExportUrl({ project, circle, date_from: from, date_to: to, output });
  return (
    <FilterCard label="Export consolidated daily data"
      footer="Daily records stored in the database for approved master sites of the chosen project, limited to your circles; one row per site and day."
      actions={ready ? (
        <>
          <Button asChild variant="outline" className="h-9"><a href={url('csv')}><Download /> CSV</a></Button>
          <Button asChild variant="outline" className="h-9"><a href={url('xlsx')}><Download /> Excel</a></Button>
        </>
      ) : <span className="pb-2 text-xs text-muted-foreground">Choose the dates to export.</span>}>
      <Field id="export-project" label="Export: project" className="w-40">
        <SelectField id="export-project" value={project} placeholder="Project" onChange={(v) => { setProject(v as RawProject); setCircle(''); }}
          options={options.projects.map((p) => ({ value: p.value, label: p.value }))} />
      </Field>
      <Field id="export-circle" label="Circle" className="w-36">
        <SelectField id="export-circle" value={circle || 'all'} placeholder="Circle" onChange={(v) => setCircle(v === 'all' ? '' : v)}
          options={[{ value: 'all', label: options.assigned_circles == null ? 'All circles' : 'All my circles' }, ...circles.map((c) => ({ value: c, label: c }))]} />
      </Field>
      <Field id="export-from" label="From" className="w-40"><Input id="export-from" type="date" className="h-9" value={from} onChange={(e) => setFrom(e.target.value)} /></Field>
      <Field id="export-to" label="To" className="w-40"><Input id="export-to" type="date" className="h-9" value={to} min={from || undefined} onChange={(e) => setTo(e.target.value)} /></Field>
    </FilterCard>
  );
}
