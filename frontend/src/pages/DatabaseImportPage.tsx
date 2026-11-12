import { useState } from 'react';
import { CheckCircle2, Download, Loader2, Lock } from 'lucide-react';
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { PageHeading } from '../context/pageHeader';
import { cn } from '@/lib/utils';
import { LweMappingPanel } from '../components/data/LweMappingPanel';
import { MatrixImportPanel } from '../components/data/MatrixImportPanel';
import { SitedataUptimePanel } from '../components/data/SitedataUptimePanel';
import { UnmatchedSitesCard } from '../components/data/UnmatchedSitesCard';
import { CoverageThresholdCard, ReportingUnitsCard } from '../components/data/ReportingConfiguration';
import { PeriodStatusBadge } from '../components/reporting/ReportingStatus';
import { useWorkbook } from '../context/workbook';
import { DataLayerStatus } from './WorkbookPage';
import { useApiQuery } from '../hooks/useApiQuery';
import { formatDateTime, formatNumber, formatShortDate } from '../lib/format';
import {
  fetchMonthlyResults, fetchNewLayerUploads, fieldError, finalizeMonth, lweMappingIssuesUrl, reopenMonth, matrixIssuesUrl, sitedataUptimeIssuesUrl,
} from '../services/api';
import type { MonthlyResult, NewLayerUpload } from '../types/matrixImport';
import type { FinalizeMonthResult } from '../types/reporting';


/**
 * Admin: the Data Source page. Every dashboard page reads the data layer (apps.sitedata); this page shows its status and
 * holds its imports (Up-Time Report, Consolidation Matrix, LWE Band ID mapping), the monthly results and their
 * finalization, the sites missing from the site master and the import history. Corrections are made in the Data Panel.
 */
export function DatabaseImportPage() {
  const [tick, setTick] = useState(0);
  const workbook = useWorkbook();
  const history = useApiQuery(`new-layer-uploads|${tick}`, fetchNewLayerUploads);
  const refresh = () => { setTick((t) => t + 1); workbook.refresh(); };
  return (
    <div className="space-y-4">
      <PageHeading title="Data Source"
        subtitle="Every dashboard page reads the reporting data (the data layer). Import the Uptime Master, Consolidation Matrix and LWE Band ID mapping here." />
      <DataLayerStatus />
      <ImportPanel onCommitted={refresh} />
      <section aria-label="Reporting configuration" className="space-y-4">
        <h2 className="text-sm font-semibold text-muted-foreground uppercase">Reporting configuration</h2>
        <ReportingUnitsCard />
        <CoverageThresholdCard />
        <MonthlyResultsCard refreshKey={tick} />
      </section>
      <UnmatchedSitesCard refreshKey={tick} />
      {history.data && <ImportHistory uploads={history.data} />}
    </div>
  );
}

/** The workbook types: each goes into the data layer (sitedata) with its own importer. */
type WorkbookType = '' | 'uptime' | 'matrix' | 'lwe_mapping';
const WORKBOOK_TYPES: { value: Exclude<WorkbookType, ''>; label: string; hint: string }[] = [
  { value: 'uptime', label: 'Up-Time Report', hint: 'Up-Time Report or day-wise outage workbook: the daily values every dashboard page reads.' },
  { value: 'matrix', label: 'Consolidation Matrix', hint: 'Consolidated Escalation Matrix (Raw Data sheet): the site master, its identities and effective dates.' },
  { value: 'lwe_mapping', label: 'LWE Band ID mapping', hint: 'Raw LWE band IDs (2100 / 700 MHz, BTS IP ID) linked to the master sites: needed to import LWE raw CSV rows.' },
];

function ImportPanel({ onCommitted }: { onCommitted: () => void }) {
  const [kind, setKind] = useState<WorkbookType>('');
  return (
    <Card role="region" aria-label="Import a workbook">
      <CardHeader>
        <CardTitle className="text-sm font-semibold">Import a workbook into the reporting data</CardTitle>
        <CardDescription className="text-xs">
          Workbooks are imported into the data layer, which every dashboard page reads. Choose the workbook type first: each type has its own
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
        {kind === 'lwe_mapping' && <LweMappingPanel onCommitted={onCommitted} />}
      </CardContent>
    </Card>
  );
}

const monthLabel = (month: string) => new Date(`${month}T00:00:00`).toLocaleDateString('en-IN', { month: 'short', year: 'numeric' });

/** Finalization state of a month; an older response without finalization_status falls back to ``finalized``. */
const stateOf = (m: MonthlyResult) => m.finalization_status ?? (m.finalized ? 'finalized' : 'open');
const isFinal = (m: MonthlyResult) => ['complete', 'incomplete_missing_data', 'finalized'].includes(stateOf(m));

function MonthStatus({ m }: { m: MonthlyResult }) {
  const state = stateOf(m);
  const f = m.finalization;
  const final = state === 'complete' || state === 'incomplete_missing_data';
  const missing = final ? f?.missing ?? [] : [];
  return (
    <div className="space-y-1">
      <div className="flex flex-wrap items-center gap-1">
        {state === 'open' && <Badge variant="outline">Open</Badge>}
        {state === 'reopened' && <Badge variant="outline" className="border-amber-300 text-amber-800">Reopened</Badge>}
        {(final || state === 'finalized') && <Badge><Lock className="size-3" /> Finalized</Badge>}
        {final && <PeriodStatusBadge finalizationStatus={state} />}
      </div>
      {final && f?.finalized_at && <p className="text-[11px] text-muted-foreground">Revision {f.revision} · {f.finalized_by ?? '—'} · {formatDateTime(f.finalized_at)}</p>}
      {state === 'reopened' && f?.reopened_at && (
        <p className="text-[11px] text-muted-foreground">Reopened by {f.reopened_by ?? '—'} · {formatDateTime(f.reopened_at)}{f.reopen_reason ? ` · ${f.reopen_reason}` : ''}</p>
      )}
      {missing.length > 0 && (
        <details className="text-[11px]">
          <summary className="cursor-pointer text-red-800">Missing data: {missing.length} unit{missing.length === 1 ? '' : 's'}</summary>
          <ul className="mt-1 space-y-0.5" aria-label={`Missing data of ${monthLabel(m.month)}`}>
            {missing.map((u) => (
              <li key={`${u.technology}|${u.circle}`}>
                <span className="font-medium">{u.technology} {u.circle}</span>: {u.dates.length} day{u.dates.length === 1 ? '' : 's'} ({u.dates.slice(0, 10).map(formatShortDate).join(', ')}{u.dates.length > 10 ? ' …' : ''})
              </li>
            ))}
          </ul>
        </details>
      )}
    </div>
  );
}

/**
 * Monthly results of the data layer; an Admin finalizes a month after confirming (a finalized month is not
 * recalculated), also with missing data (then "Incomplete — Missing Data"), and may reopen it with a reason.
 */
function MonthlyResultsCard({ refreshKey }: { refreshKey: number }) {
  const [tick, setTick] = useState(0);
  const months = useApiQuery(`sitedata-months|${refreshKey}|${tick}`, fetchMonthlyResults);
  const [confirming, setConfirming] = useState<string | null>(null);
  const [reopening, setReopening] = useState<string | null>(null);
  const [reason, setReason] = useState('');
  const [notes, setNotes] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<{ title: string; message: string } | null>(null);
  const [done, setDone] = useState<FinalizeMonthResult | null>(null);
  const [reopened, setReopened] = useState<string | null>(null);
  const finalize = async (m: MonthlyResult) => {
    setBusy(true);
    setError(null);
    try {
      setDone(await finalizeMonth(m.month, notes.trim()));
      setReopened(null);
      setConfirming(null);
      setNotes('');
      setTick((t) => t + 1);
    } catch (e) {
      setError({ title: 'Month not finalized', message: (e as Error).message });
    } finally {
      setBusy(false);
    }
  };
  const reopen = async (m: MonthlyResult) => {
    setBusy(true);
    setError(null);
    try {
      await reopenMonth(m.month, reason.trim());
      setReopened(m.month);
      setDone(null);
      setReopening(null);
      setReason('');
      setTick((t) => t + 1);
    } catch (e) {
      setError({ title: 'Month not reopened', message: fieldError(e, 'reason') ?? (e as Error).message });
    } finally {
      setBusy(false);
    }
  };
  const doneIncomplete = done?.finalization?.status === 'incomplete_missing_data';
  return (
    <Card role="region" aria-label="Monthly results">
      <CardHeader>
        <CardTitle className="text-sm font-semibold">Monthly results</CardTitle>
        <CardDescription className="text-xs">
          Monthly site results calculated from the daily data. Finalizing a month freezes its results: later imports and corrections no longer recalculate it.
          A month can be finalized with missing data; it is then marked Incomplete — Missing Data and the missing units and dates are kept. Reopen a month
          (with a reason) to import late data, then finalize it again.
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-3">
        {months.error && <p className="text-xs text-destructive">{months.error.message}</p>}
        {error && <Alert variant="destructive" role="alert"><AlertTitle>{error.title}</AlertTitle><AlertDescription>{error.message}</AlertDescription></Alert>}
        {done && (
          <Alert className={doneIncomplete ? 'border-orange-300 bg-red-50/70' : 'border-emerald-200 bg-emerald-50/70'} role="status">
            <CheckCircle2 className={doneIncomplete ? 'text-red-700' : 'text-emerald-700'} />
            <AlertTitle>{monthLabel(done.month)} finalized{doneIncomplete ? ': Incomplete — Missing Data' : done.finalization?.status === 'complete' ? ': Complete' : ''}</AlertTitle>
            <AlertDescription>
              {formatNumber(done.finalized_records)} monthly site results are final.
              {doneIncomplete && done.finalization?.missing.length
                ? ` Missing: ${done.finalization.missing.map((u) => `${u.technology} ${u.circle} (${u.dates.length} day${u.dates.length === 1 ? '' : 's'})`).join(', ')}.` : ''}
            </AlertDescription>
          </Alert>
        )}
        {reopened && <Alert role="status"><AlertTitle>{monthLabel(reopened)} reopened</AlertTitle><AlertDescription>Late data can be imported; finalize the month again afterwards.</AlertDescription></Alert>}
        {months.data && (months.data.months.length === 0 ? <p className="text-xs text-muted-foreground">No monthly results yet.</p> : (
          <div className="overflow-x-auto rounded-md border">
            <table className="w-full text-left text-xs">
              <caption className="sr-only">Monthly results</caption>
              <thead className="bg-muted"><tr>{['Month', 'Site results', 'Calculated', 'Status', ''].map((h) => <th key={h} className="px-2.5 py-1.5 font-medium">{h}</th>)}</tr></thead>
              <tbody className="divide-y">
                {months.data.months.map((m) => {
                  const final = isFinal(m);
                  const canReopen = stateOf(m) === 'complete' || stateOf(m) === 'incomplete_missing_data';
                  return (
                    <tr key={m.month} className="align-top">
                      <td className="px-2.5 py-1.5">{monthLabel(m.month)}</td>
                      <td className="px-2.5 py-1.5 tabular-nums">{formatNumber(m.records)}</td>
                      <td className="px-2.5 py-1.5">{m.calculated_at ? formatDateTime(m.calculated_at) : '—'}</td>
                      <td className="px-2.5 py-1.5"><MonthStatus m={m} /></td>
                      <td className="px-2.5 py-1.5">
                        {!final && (confirming === m.month ? (
                          <div className="flex max-w-md flex-col gap-2" role="alertdialog" aria-label={`Confirm finalizing ${monthLabel(m.month)}`}>
                            <span>
                              Finalize {monthLabel(m.month)}? Its results will no longer change. If any reporting unit's data is missing, the month will be
                              marked &lsquo;Incomplete — Missing Data&rsquo; and the missing units and dates are recorded.
                            </span>
                            <Input aria-label="Finalization notes (optional)" placeholder="Notes (optional)" value={notes} onChange={(e) => setNotes(e.target.value)} className="h-7 text-xs" />
                            <div className="flex gap-2">
                              <Button size="sm" onClick={() => finalize(m)} disabled={busy}>{busy && <Loader2 className="animate-spin" />} Yes, finalize</Button>
                              <Button size="sm" variant="ghost" onClick={() => setConfirming(null)} disabled={busy}>Cancel</Button>
                            </div>
                          </div>
                        ) : (
                          <Button size="sm" variant="outline" onClick={() => { setConfirming(m.month); setReopening(null); setError(null); }} disabled={busy || m.records === 0}>
                            Finalize {monthLabel(m.month)}
                          </Button>
                        ))}
                        {canReopen && (reopening === m.month ? (
                          <form className="flex max-w-md flex-col gap-2" aria-label={`Reopen ${monthLabel(m.month)}`}
                            onSubmit={(e) => { e.preventDefault(); if (reason.trim()) void reopen(m); }}>
                            <span>Reopen {monthLabel(m.month)}? Its results are no longer final and are recalculated by later imports.</span>
                            <Input aria-label="Reason for reopening" placeholder="Reason (required)" value={reason} onChange={(e) => setReason(e.target.value)} className="h-7 text-xs" />
                            <div className="flex gap-2">
                              <Button type="submit" size="sm" disabled={busy || !reason.trim()}>{busy && <Loader2 className="animate-spin" />} Reopen month</Button>
                              <Button type="button" size="sm" variant="ghost" onClick={() => setReopening(null)} disabled={busy}>Cancel</Button>
                            </div>
                          </form>
                        ) : (
                          <Button size="sm" variant="outline" onClick={() => { setReopening(m.month); setConfirming(null); setReason(''); setError(null); }} disabled={busy}>
                            Reopen {monthLabel(m.month)}
                          </Button>
                        ))}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        ))}
      </CardContent>
    </Card>
  );
}

const KIND_LABEL: Record<NewLayerUpload['kind'], string> = {
  uptime_master: 'Up-Time Report', consolidation_matrix: 'Consolidation Matrix', lwe_band_mapping: 'LWE Band ID mapping',
};
const ISSUES_URL: Record<NewLayerUpload['kind'], (id: number) => string> = {
  uptime_master: sitedataUptimeIssuesUrl, consolidation_matrix: matrixIssuesUrl, lwe_band_mapping: lweMappingIssuesUrl,
};

/** Recent uploads into the data layer (every workbook type), newest first, with each one's error report. */
function ImportHistory({ uploads }: { uploads: NewLayerUpload[] }) {
  return (
    <Card role="region" aria-label="Import history">
      <CardHeader>
        <CardTitle className="text-sm font-semibold">Import history</CardTitle>
        <CardDescription className="text-xs">
          Uploads into the data layer. Up-Time Report counts are site-days; Consolidation Matrix counts are sites; LWE Band ID mapping counts are rows.
        </CardDescription>
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
                    <td className="px-2.5 py-1.5">{KIND_LABEL[u.kind] ?? u.kind}{u.technology ? ` · ${u.technology}` : ''}</td>
                    <td className="px-2.5 py-1.5">{u.file}</td>
                    <td className="px-2.5 py-1.5"><Badge variant={u.status === 'committed' ? 'default' : u.status === 'failed' ? 'destructive' : 'outline'}>{u.status}</Badge></td>
                    <td className="px-2.5 py-1.5">{u.uploaded_by ?? '—'}</td>
                    <td className="px-2.5 py-1.5">{u.committed_at ? formatDateTime(u.committed_at) : '—'}</td>
                    <td className="px-2.5 py-1.5 tabular-nums">{formatNumber(u.counts.accepted)}</td>
                    <td className="px-2.5 py-1.5 tabular-nums">{formatNumber(u.counts.duplicate)}</td>
                    <td className="px-2.5 py-1.5 tabular-nums">{formatNumber(u.counts.rejected)}</td>
                    <td className="px-2.5 py-1.5">
                      {ISSUES_URL[u.kind] && (
                        <a href={ISSUES_URL[u.kind](u.id)} aria-label={`Error report of upload ${u.id}`}
                          className="inline-flex items-center gap-1 text-primary underline-offset-4 hover:underline"><Download className="size-3.5" /> CSV</a>
                      )}
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
