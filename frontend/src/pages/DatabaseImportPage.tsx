import { useState } from 'react';
import { Database, Download, FileSpreadsheet, Loader2, TriangleAlert } from 'lucide-react';
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { PageHeading } from '../context/pageHeader';
import { Skeleton } from '@/components/ui/skeleton';
import { cn } from '@/lib/utils';
import { MatrixImportPanel } from '../components/data/MatrixImportPanel';
import { SitedataUptimePanel } from '../components/data/SitedataUptimePanel';
import { UnmatchedSitesCard } from '../components/data/UnmatchedSitesCard';
import { useWorkbook } from '../context/workbook';
import { WorkbookPage } from './WorkbookPage';
import { useApiQuery } from '../hooks/useApiQuery';
import { formatDateTime, formatNumber } from '../lib/format';
import { fetchDataSource, fetchNewLayerUploads, matrixIssuesUrl, setDataSource, sitedataUptimeIssuesUrl } from '../services/api';
import type { DataSourceKind, DataSourceState } from '../types';
import type { NewLayerUpload } from '../types/matrixImport';


/**
 * Admin: the dashboard's data source. Pick Excel to upload the Master workbook the dashboard reads; pick
 * PostgreSQL to import workbooks into the database and read from it. Switching asks for confirmation.
 */
export function DatabaseImportPage() {
  const [tick, setTick] = useState(0);
  const source = useApiQuery(`data-source|${tick}`, fetchDataSource);
  const history = useApiQuery(`new-layer-uploads|${tick}`, fetchNewLayerUploads);
  const refresh = () => setTick((t) => t + 1);
  // The tile being looked at; it defaults to the active source.
  const [picked, setPicked] = useState<DataSourceKind | null>(null);
  const view = picked ?? source.data?.active ?? 'excel';
  return (
    <div className="space-y-4">
      <PageHeading title="Data Source"
        subtitle="Where every dashboard page reads its data: the Excel workbook (upload the Master workbook) or the PostgreSQL database (import workbooks)" />
      {source.error ? <Alert variant="destructive"><AlertTitle>Data source unavailable</AlertTitle><AlertDescription>{source.error.message}</AlertDescription></Alert>
        : source.data ? <SourceSelector state={source.data} view={view} onView={setPicked} onChanged={() => { setPicked(null); refresh(); }} />
          : <Skeleton className="h-40 w-full" />}
      {view === 'excel' ? <WorkbookPage embedded /> : (
        <>
          <ImportPanel onCommitted={refresh} />
          <UnmatchedSitesCard refreshKey={tick} />
          {history.data && <ImportHistory uploads={history.data} />}
        </>
      )}
    </div>
  );
}

function SourceSelector({ state, view, onView, onChanged }: {
  state: DataSourceState; view: DataSourceKind; onView: (v: DataSourceKind | null) => void; onChanged: () => void;
}) {
  const workbook = useWorkbook();
  // Viewing the source that is not active offers the switch (after confirmation).
  const pending = view !== state.active ? view : null;
  const [acknowledged, setAcknowledged] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const db = state.database;
  const warnings = pending === 'database' ? db.warnings : [];
  const confirm = async () => {
    if (!pending) return;
    setBusy(true);
    setError(null);
    try {
      await setDataSource(pending, acknowledged);
      setAcknowledged(false);
      workbook.refresh();  // every page reloads its figures from the new source
      onChanged();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  };
  return (
    <Card role="region" aria-label="Dashboard data source">
      <CardHeader>
        <CardTitle className="text-sm font-semibold">Dashboard data source</CardTitle>
        <CardDescription className="text-xs">
          One setting for every user and every page (Site Portfolio, Overview, 4G, LWE, Threshold Analysis and the rest). Select a source to see its
          tools; the dashboard changes only after you confirm.
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-3">
        <div className="grid grid-cols-1 gap-3 md:grid-cols-2" role="radiogroup" aria-label="Data source">
          {state.options.map((o) => {
            const active = state.active === o.value;
            const detail = o.value === 'excel' ? 'The uploaded Master workbook (current behaviour).'
              : db.empty ? 'Empty: import a workbook below first.'
                : `${formatNumber(db.sites)} sites · ${formatNumber(db.daily_records)} daily records · last import ${db.last_import ? formatDateTime(db.last_import.committed_at) : '—'}`;
            return (
              <button key={o.value} type="button" role="radio" aria-checked={view === o.value}
                onClick={() => { onView(o.value === state.active ? null : o.value); setAcknowledged(false); setError(null); }}
                className={cn('flex items-start gap-3 rounded-xl border p-3 text-left transition-colors',
                  view === o.value ? 'border-primary bg-primary/5 ring-1 ring-primary/30' : 'hover:bg-muted/50')}>
                {o.value === 'excel' ? <FileSpreadsheet className="mt-0.5 size-5 text-emerald-700" /> : <Database className="mt-0.5 size-5 text-sky-700" />}
                <span className="min-w-0">
                  <span className="flex items-center gap-2 text-sm font-medium">{o.label}{active ? <Badge>In use by the dashboard</Badge> : <Badge variant="outline">Not in use</Badge>}</span>
                  <span className="block text-xs text-muted-foreground">{detail}</span>
                </span>
              </button>
            );
          })}
        </div>
        {state.active === 'database' && db.warnings.length > 0 && <Warnings title="The active database source is incomplete" items={db.warnings} />}
        {pending === 'database' && db.empty && (
          <p className="rounded-xl border border-dashed p-3 text-sm text-muted-foreground" role="status">
            The database is empty. Import the Master workbook below; then you can switch the dashboard to PostgreSQL.
          </p>
        )}
        {pending && !(pending === 'database' && db.empty) && (
          <div className="space-y-2 rounded-xl border border-amber-300 bg-amber-50/70 p-3" role="alertdialog" aria-label="Confirm data source change">
            <p className="text-sm font-medium">Switch every dashboard page to the {pending === 'excel' ? 'Excel workbook' : 'PostgreSQL database'}?</p>
            <p className="text-xs text-muted-foreground">All users will see figures from this source straight away.</p>
            {warnings.length > 0 && (
              <>
                <Warnings title="Missing or incomplete data in the database" items={warnings} />
                <label className="flex items-center gap-2 text-xs">
                  <input type="checkbox" className="size-3.5 accent-primary" checked={acknowledged} onChange={(e) => setAcknowledged(e.target.checked)} />
                  I understand these periods and comparisons will be missing.
                </label>
              </>
            )}
            {error && <p className="text-xs text-destructive" role="alert">{error}</p>}
            <div className="flex gap-2">
              <Button size="sm" onClick={confirm} disabled={busy || (warnings.length > 0 && !acknowledged)}>
                {busy && <Loader2 className="animate-spin" />} Switch source
              </Button>
              <Button size="sm" variant="ghost" onClick={() => onView(null)} disabled={busy}>Keep {state.label}</Button>
            </div>
          </div>
        )}
      </CardContent>
    </Card>
  );
}

function Warnings({ title, items }: { title: string; items: string[] }) {
  return (
    <Alert className="border-amber-300 bg-amber-50/70">
      <TriangleAlert className="text-amber-700" />
      <AlertTitle>{title}</AlertTitle>
      <AlertDescription><ul className="list-disc pl-4">{items.map((w) => <li key={w}>{w}</li>)}</ul></AlertDescription>
    </Alert>
  );
}

/** The workbook types: both go into the new data layer (sitedata), each with its own importer. */
type WorkbookType = '' | 'uptime' | 'matrix';
const WORKBOOK_TYPES: { value: Exclude<WorkbookType, ''>; label: string; hint: string }[] = [
  { value: 'uptime', label: 'Up-Time Report', hint: 'Up-Time Report or day-wise outage workbook: the daily values every dashboard page reads.' },
  { value: 'matrix', label: 'Consolidation Matrix', hint: 'Consolidated Escalation Matrix (Raw Data sheet): the site master, its identities and effective dates.' },
];

function ImportPanel({ onCommitted }: { onCommitted: () => void }) {
  const [kind, setKind] = useState<WorkbookType>('');
  return (
    <Card role="region" aria-label="Import into PostgreSQL">
      <CardHeader>
        <CardTitle className="text-sm font-semibold">Import a workbook into PostgreSQL</CardTitle>
        <CardDescription className="text-xs">
          Workbooks are imported into the new data layer, which every dashboard page reads. Choose the workbook type first: each type has its own
          importer. Nothing is written until you confirm after the preview; records are never deleted, and importing the same file again adds nothing.
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-4">
        <fieldset className="space-y-2" aria-label="Workbook type">
          <legend className="text-xs font-medium">Workbook type <span className="text-destructive">*</span></legend>
          <div className="flex flex-wrap gap-2">
            {WORKBOOK_TYPES.map((t) => (
              <label key={t.value} className={cn('flex max-w-sm cursor-pointer items-start gap-2 rounded-lg border px-3 py-2 text-xs', kind === t.value && 'border-primary bg-primary/5')}>
                <input type="radio" name="workbook-type" value={t.value} className="mt-0.5 accent-primary" checked={kind === t.value} onChange={() => setKind(t.value)} />
                <span><span className="font-semibold">{t.label}</span><span className="block text-muted-foreground">{t.hint}</span></span>
              </label>
            ))}
          </div>
          {!kind && <p className="text-xs text-muted-foreground" role="note">Select the workbook type before choosing a file.</p>}
        </fieldset>
        {kind === 'uptime' && <SitedataUptimePanel onCommitted={onCommitted} />}
        {kind === 'matrix' && <MatrixImportPanel onCommitted={onCommitted} />}
      </CardContent>
    </Card>
  );
}

const KIND_LABEL: Record<NewLayerUpload['kind'], string> = { uptime_master: 'Up-Time Report', consolidation_matrix: 'Consolidation Matrix' };

/** Recent uploads into the new data layer (both workbook types), newest first, with each one's error report. */
function ImportHistory({ uploads }: { uploads: NewLayerUpload[] }) {
  return (
    <Card role="region" aria-label="Import history">
      <CardHeader>
        <CardTitle className="text-sm font-semibold">Import history</CardTitle>
        <CardDescription className="text-xs">Uploads into the new data layer. Up-Time Report counts are site-days; Consolidation Matrix counts are sites.</CardDescription>
      </CardHeader>
      <CardContent>
        {uploads.length === 0 ? <p className="text-xs text-muted-foreground">No uploads yet.</p> : (
          <div className="overflow-x-auto rounded-md border">
            <table className="w-full text-left text-xs">
              <caption className="sr-only">Import history</caption>
              <thead className="bg-muted"><tr>{['#', 'Type', 'File', 'Status', 'By', 'Committed', 'New / changed', 'Already stored', 'Rejected', 'Report'].map((h) => <th key={h} className="px-2.5 py-1.5 font-medium">{h}</th>)}</tr></thead>
              <tbody className="divide-y">
                {uploads.map((u) => (
                  <tr key={`${u.kind}-${u.id}`}>
                    <td className="px-2.5 py-1.5">{u.id}</td>
                    <td className="px-2.5 py-1.5">{KIND_LABEL[u.kind]}{u.technology ? ` · ${u.technology}` : ''}</td>
                    <td className="px-2.5 py-1.5">{u.file}</td>
                    <td className="px-2.5 py-1.5"><Badge variant={u.status === 'committed' ? 'default' : u.status === 'failed' ? 'destructive' : 'outline'}>{u.status}</Badge></td>
                    <td className="px-2.5 py-1.5">{u.uploaded_by ?? '—'}</td>
                    <td className="px-2.5 py-1.5">{u.committed_at ? formatDateTime(u.committed_at) : '—'}</td>
                    <td className="px-2.5 py-1.5 tabular-nums">{formatNumber(u.counts.accepted)}</td>
                    <td className="px-2.5 py-1.5 tabular-nums">{formatNumber(u.counts.duplicate)}</td>
                    <td className="px-2.5 py-1.5 tabular-nums">{formatNumber(u.counts.rejected)}</td>
                    <td className="px-2.5 py-1.5">
                      <a href={u.kind === 'uptime_master' ? sitedataUptimeIssuesUrl(u.id) : matrixIssuesUrl(u.id)} aria-label={`Error report of upload ${u.id}`}
                        className="inline-flex items-center gap-1 text-primary underline-offset-4 hover:underline"><Download className="size-3.5" /> CSV</a>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </CardContent>
    </Card>
  );
}
