import { useRef, useState, type DragEvent } from 'react';
import { Link } from 'react-router-dom';
import { AlertTriangle, CheckCircle2, FileSpreadsheet, Loader2, UploadCloud, X } from 'lucide-react';
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { PageHeading } from '../context/pageHeader';
import { Skeleton } from '@/components/ui/skeleton';
import { cn } from '@/lib/utils';
import { useWorkbook } from '../context/workbook';
import { formatDate, formatDateTime, formatNumber } from '../lib/format';
import { ApiError, uploadWorkbook } from '../services/api';
import type { ActiveWorkbook } from '../types';

const MAX_BYTES = 50 * 1024 * 1024;

type Phase =
  | { kind: 'idle' }
  | { kind: 'uploading'; progress: number }
  | { kind: 'validating' }
  | { kind: 'accepted'; workbook: ActiveWorkbook }
  | { kind: 'rejected'; message: string; problems: string[] };

export function WorkbookPage({ embedded = false }: { embedded?: boolean } = {}) {
  const { active, loading, error, setActive } = useWorkbook();
  const [file, setFile] = useState<File | null>(null);
  const [phase, setPhase] = useState<Phase>({ kind: 'idle' });
  const [dragging, setDragging] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);
  const busy = phase.kind === 'uploading' || phase.kind === 'validating';

  const choose = (candidate: File | undefined) => {
    if (!candidate) return;
    if (!candidate.name.toLowerCase().endsWith('.xlsx')) {
      setFile(null);
      setPhase({ kind: 'rejected', message: 'Choose the Master workbook saved as an Excel .xlsx file.', problems: [] });
      return;
    }
    if (candidate.size > MAX_BYTES) {
      setFile(null);
      setPhase({ kind: 'rejected', message: 'The workbook is larger than the 50 MB limit.', problems: [] });
      return;
    }
    setFile(candidate);
    setPhase({ kind: 'idle' });
  };

  const onDrop = (event: DragEvent) => {
    event.preventDefault();
    setDragging(false);
    if (!busy) choose(event.dataTransfer.files[0]);
  };

  const submit = async () => {
    if (!file) return;
    setPhase({ kind: 'uploading', progress: 0 });
    try {
      const result = await uploadWorkbook(file, (progress) =>
        setPhase(progress >= 1 ? { kind: 'validating' } : { kind: 'uploading', progress }));
      if (result.active) {
        setActive(result.active);
        setPhase({ kind: 'accepted', workbook: result.active });
        setFile(null);
      }
    } catch (err) {
      const problems = err instanceof ApiError && Array.isArray(err.details.problems) ? (err.details.problems as string[]) : [];
      setPhase({ kind: 'rejected', message: err instanceof Error ? err.message : 'The upload failed.', problems });
    }
  };

  return (
    <div className="space-y-4">
      {!embedded && (
        <PageHeading title="Master Workbook"
          subtitle="The Excel source of the dashboard · a new upload replaces the current one only if it passes validation" />
      )}

      <div className="grid grid-cols-1 items-start gap-4 xl:grid-cols-5">
        <Card className="xl:col-span-3">
          <CardHeader>
            <CardTitle className="text-sm font-semibold">Upload consolidated workbook</CardTitle>
            <CardDescription className="text-xs">
              Excel .xlsx, up to 50 MB, containing the "Up-Time Report" sheet. The file is read, never modified; macros are not accepted.
            </CardDescription>
          </CardHeader>
          <CardContent className="space-y-4">
            <div
              onDragOver={(e) => { e.preventDefault(); if (!busy) setDragging(true); }}
              onDragLeave={() => setDragging(false)}
              onDrop={onDrop}
              className={cn(
                'flex flex-col items-center justify-center gap-2 rounded-xl border-2 border-dashed px-6 py-10 text-center transition-colors',
                dragging ? 'border-primary bg-primary/5' : 'border-border',
                busy && 'opacity-60',
              )}
            >
              <UploadCloud className="size-8 text-muted-foreground" aria-hidden="true" />
              <p className="text-sm font-medium">Drag the workbook here, or</p>
              <Button variant="outline" size="sm" onClick={() => inputRef.current?.click()} disabled={busy}>
                Choose file
              </Button>
              <input
                ref={inputRef}
                type="file"
                accept=".xlsx,application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
                className="sr-only"
                aria-label="Choose Master workbook"
                onChange={(e) => { choose(e.target.files?.[0]); e.target.value = ''; }}
              />
            </div>

            {file && (
              <div className="flex items-center justify-between gap-3 rounded-lg border px-3 py-2.5">
                <div className="flex min-w-0 items-center gap-2.5">
                  <FileSpreadsheet className="size-5 shrink-0 text-emerald-700" aria-hidden="true" />
                  <div className="min-w-0">
                    <p className="truncate text-sm font-medium">{file.name}</p>
                    <p className="text-xs text-muted-foreground">{(file.size / (1024 * 1024)).toFixed(1)} MB</p>
                  </div>
                </div>
                <div className="flex shrink-0 items-center gap-1.5">
                  <Button variant="ghost" size="icon-sm" onClick={() => setFile(null)} disabled={busy} aria-label="Remove selected file">
                    <X />
                  </Button>
                  <Button size="sm" onClick={submit} disabled={busy}>
                    {busy ? <Loader2 className="animate-spin" /> : <UploadCloud />} Upload and validate
                  </Button>
                </div>
              </div>
            )}

            <UploadStatus phase={phase} hadPrevious={active !== null} />
          </CardContent>
        </Card>

        <div className="xl:col-span-2">
          {loading ? <Skeleton className="h-72 w-full" /> : error ? (
            <Alert variant="destructive"><AlertTriangle /><AlertTitle>Status unavailable</AlertTitle><AlertDescription>{error.message}</AlertDescription></Alert>
          ) : active ? <ActiveCard workbook={active} /> : (
            <Card>
              <CardHeader>
                <CardTitle className="text-sm font-semibold">No workbook loaded</CardTitle>
                <CardDescription className="text-xs">Upload the consolidated workbook to populate the dashboard. No sample data is shown in the meantime.</CardDescription>
              </CardHeader>
            </Card>
          )}
        </div>
      </div>
    </div>
  );
}

function UploadStatus({ phase, hadPrevious }: { phase: Phase; hadPrevious: boolean }) {
  if (phase.kind === 'uploading') {
    const percent = Math.round(phase.progress * 100);
    return (
      <div role="status" aria-live="polite" className="space-y-1.5">
        <div className="flex justify-between text-xs text-muted-foreground"><span>Uploading…</span><span>{percent}%</span></div>
        <div className="h-1.5 overflow-hidden rounded-full bg-muted" role="progressbar" aria-valuenow={percent} aria-valuemin={0} aria-valuemax={100} aria-label="Upload progress">
          <div className="h-full bg-primary transition-[width]" style={{ width: `${percent}%` }} />
        </div>
      </div>
    );
  }
  if (phase.kind === 'validating') {
    return (
      <p role="status" aria-live="polite" className="flex items-center gap-2 text-sm text-muted-foreground">
        <Loader2 className="size-4 animate-spin" aria-hidden="true" />
        Validating the workbook and calculating figures. This usually takes 10 to 20 seconds.
      </p>
    );
  }
  if (phase.kind === 'accepted') {
    const w = phase.workbook;
    return (
      <Alert role="status">
        <CheckCircle2 className="text-emerald-600" />
        <AlertTitle>Workbook accepted. The dashboard now uses “{w.workbook}”.</AlertTitle>
        <AlertDescription>
          {formatNumber(w.sites)} sites in {w.circles.length} circles · reporting dates {formatDate(w.reporting_dates[0])} to {formatDate(w.latest_reporting_date)}
          {w.warning_count > 0 && <> · {w.warning_count} data-quality {w.warning_count === 1 ? 'note' : 'notes'} (<Link to="/data-source" className="underline underline-offset-4">review</Link>)</>}
          . <Link to="/" className="font-medium text-foreground underline underline-offset-4">Open the dashboard</Link>
        </AlertDescription>
      </Alert>
    );
  }
  if (phase.kind === 'rejected') {
    return (
      <Alert variant="destructive" role="alert">
        <AlertTriangle />
        <AlertTitle>Workbook not accepted</AlertTitle>
        <AlertDescription>
          <p>{phase.message}</p>
          {phase.problems.length > 0 && <ul className="mt-1 list-disc pl-5">{phase.problems.map((p) => <li key={p}>{p}</li>)}</ul>}
          {!phase.message.includes('still in use') && hadPrevious && <p className="mt-1">The current workbook is still in use.</p>}
        </AlertDescription>
      </Alert>
    );
  }
  return null;
}

function ActiveCard({ workbook }: { workbook: ActiveWorkbook }) {
  const warnings = workbook.warnings.filter((w) => w.severity === 'warning');
  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-2 text-sm font-semibold">
          Workbook in use
          {warnings.length ? <Badge variant="destructive">{warnings.length} to review</Badge> : <Badge variant="secondary">Validated</Badge>}
        </CardTitle>
        <CardDescription className="text-xs break-all">{workbook.workbook}</CardDescription>
      </CardHeader>
      <CardContent className="space-y-4 text-sm">
        <dl className="grid grid-cols-2 gap-x-4 gap-y-2.5">
          <Item label="Uploaded" value={workbook.uploaded_at ? formatDateTime(workbook.uploaded_at) : 'Configured on the server'} />
          <Item label="Reporting month" value={workbook.month} />
          <Item label="Latest reporting date" value={formatDate(workbook.latest_reporting_date)} />
          <Item label="Reported days" value={String(workbook.reporting_dates.length)} />
          {Object.entries(workbook.by_report_type).map(([type, count]) => <Item key={type} label={`${type} sites`} value={formatNumber(count)} />)}
          <Item label="Circles" value={workbook.circles.join(', ')} />
        </dl>
        <div>
          <p className="mb-1.5 text-xs font-medium text-muted-foreground">Worksheets found ({workbook.sheets.length})</p>
          <ul className="divide-y rounded-md border text-xs">
            {workbook.sheets.map((sheet) => (
              <li key={sheet.name} className="flex items-start justify-between gap-3 px-2.5 py-1.5">
                <span className="font-medium">{sheet.name}</span>
                <span className="text-right text-muted-foreground">{sheet.role}</span>
              </li>
            ))}
          </ul>
        </div>
        <Link to="/data-source" className="inline-block text-xs font-medium underline underline-offset-4">Data quality and definitions</Link>
      </CardContent>
    </Card>
  );
}

function Item({ label, value }: { label: string; value: string }) {
  return (
    <div className="min-w-0">
      <dt className="text-xs text-muted-foreground">{label}</dt>
      <dd className="mt-0.5 break-words">{value}</dd>
    </div>
  );
}
