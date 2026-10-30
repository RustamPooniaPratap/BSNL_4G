import { useRef, useState, type DragEvent, type ReactNode } from 'react';
import { Check, CircleAlert, CloudUpload, FileSpreadsheet, FolderOpen, Loader2, RefreshCw, X } from 'lucide-react';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card } from '@/components/ui/card';
import { Label } from '@/components/ui/label';
import { cn } from '@/lib/utils';
import { formatBytes } from '../../lib/dataEntry';

/**
 * Visual building blocks shared by the upload pages (Upload CSV, Upload RCA Data). They hold presentation only: each
 * page keeps its own fields, file checks, API calls and workflow state.
 */

export type StepState = 'todo' | 'current' | 'active' | 'done' | 'failed';
const STEP_TEXT: Record<StepState, string> = { todo: 'not started', current: 'next', active: 'in progress', done: 'completed', failed: 'did not pass' };

/** Numbered progress steps; each page decides the states from what its server reported. */
export function UploadSteps({ steps }: { steps: [string, StepState][] }) {
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

/** A labelled form control with a required marker and an error line. */
export function DetailField({ id, label, required = false, error, children }: { id: string; label: string; required?: boolean; error?: string | null; children: ReactNode }) {
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

export interface FileStatus { label: string; tone: string }

/**
 * Drag-and-drop area with Browse Files, and the selected file with its status, Replace and Remove.
 * ``check`` returns why a picked file is refused (type, empty, size), or null; a refused file is never passed on.
 */
export function FileDropZone({ inputId, inputLabel, accept, title, dropTitle, description, hint, kind, oneFileMessage, file, status,
  busy, spinning, requiredError, check, onFile }: {
  inputId: string; inputLabel: string; accept: string; title: string; dropTitle: string; description: string; hint: ReactNode; kind: string;
  oneFileMessage: string; file: File | null; status: FileStatus | null; busy: boolean; spinning: boolean;
  /** Shown when no file is chosen (e.g. after the user tried to continue), unless a refused-file message is shown. */
  requiredError?: string | null;
  check: (file: File) => string | null; onFile: (file: File | null) => void;
}) {
  const input = useRef<HTMLInputElement>(null);
  const [dragging, setDragging] = useState(false);
  const [fileError, setFileError] = useState<string | null>(null);
  const pick = (picked: File | null) => {
    setFileError(null);
    if (input.current) input.current.value = '';  // the same file can be chosen again after Remove
    if (!picked) return onFile(null);
    const problem = check(picked);
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
      setFileError(oneFileMessage);
      return onFile(null);
    }
    pick(files[0] ?? null);
  };
  return (
    <>
      <div
        onDragOver={(e) => { e.preventDefault(); if (!busy) setDragging(true); }}
        onDragLeave={() => setDragging(false)}
        onDrop={onDrop}
        data-dragging={dragging || undefined}
        className={cn('relative flex flex-1 flex-col items-center justify-center gap-2 rounded-xl border-2 border-dashed px-6 py-8 text-center transition-colors',
          dragging ? 'border-primary bg-primary/5' : fileError ? 'border-destructive/50 bg-destructive/5' : 'border-border bg-muted/20',
          busy && 'opacity-70')}>
        <input ref={input} id={inputId} type="file" accept={accept} className="sr-only" aria-label={inputLabel} disabled={busy}
          onChange={(e) => pick(e.target.files?.[0] ?? null)} />
        <span className={cn('grid size-12 place-items-center rounded-full', dragging ? 'bg-primary text-primary-foreground' : 'bg-primary/10 text-primary')}>
          <CloudUpload className="size-6" aria-hidden="true" />
        </span>
        <h2 className="text-base font-semibold">{dragging ? dropTitle : title}</h2>
        <p className="text-sm text-muted-foreground">{description}</p>
        <Button type="button" variant="outline" disabled={busy} onClick={() => input.current?.click()}><FolderOpen /> Browse Files</Button>
        <p className="max-w-md text-xs text-muted-foreground">{hint}</p>
      </div>
      {fileError && <p className="flex items-center gap-1.5 text-sm text-destructive" role="alert"><CircleAlert className="size-4" aria-hidden="true" />{fileError}</p>}
      {!file && !fileError && requiredError && <p className="text-sm text-destructive">{requiredError}</p>}
      {file && (
        <div className="flex flex-wrap items-center gap-3 rounded-lg border px-3 py-2" aria-label="Selected file">
          <span className="grid size-9 shrink-0 place-items-center rounded-md bg-emerald-50 text-emerald-700"><FileSpreadsheet className="size-5" aria-hidden="true" /></span>
          <div className="min-w-0 flex-1">
            <p className="truncate text-sm font-medium" title={file.name}>{file.name}</p>
            <p className="text-xs text-muted-foreground">{kind} · {formatBytes(file.size)}</p>
          </div>
          {status && <Badge variant="outline" className={cn('font-medium', status.tone)}>{spinning && <Loader2 className="animate-spin" />}{status.label}</Badge>}
          <Button type="button" variant="ghost" size="sm" disabled={busy} onClick={() => input.current?.click()}><RefreshCw /> Replace</Button>
          <Button type="button" variant="ghost" size="sm" disabled={busy} aria-label="Remove file" onClick={() => pick(null)}><X /> Remove</Button>
        </div>
      )}
    </>
  );
}
