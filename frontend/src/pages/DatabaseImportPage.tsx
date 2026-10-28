import { useState, type ReactNode } from 'react';
import { AlertTriangle, CheckCircle2, Database, Download, FileSpreadsheet, Loader2, TriangleAlert, Upload } from 'lucide-react';
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Skeleton } from '@/components/ui/skeleton';
import { cn } from '@/lib/utils';
import { useWorkbook } from '../context/workbook';
import { WorkbookPage } from './WorkbookPage';
import { useApiQuery } from '../hooks/useApiQuery';
import { formatDate, formatDateTime, formatNumber } from '../lib/format';
import {
  commitImport, discardImport, fetchDataSource, fetchImports, importIssuesUrl, previewImport, setDataSource,
} from '../services/api';
import type { DataSourceKind, DataSourceState, ImportBatch, ImportComparison, ImportFileSummary } from '../types';

const short = (key: string) => key.replace('4G Saturation|', '4G · ').replace('LWE|', 'LWE · ');
const value = (v: unknown) => (v == null || v === '' ? '—' : typeof v === 'number' ? formatNumber(Math.round(v * 100) / 100) : String(v));

/**
 * Admin: the dashboard's data source. Pick Excel to upload the Master workbook the dashboard reads; pick
 * PostgreSQL to import workbooks into the database and read from it. Switching asks for confirmation.
 */
export function DatabaseImportPage() {
  const [tick, setTick] = useState(0);
  const source = useApiQuery(`data-source|${tick}`, fetchDataSource);
  const history = useApiQuery(`imports|${tick}`, fetchImports);
  const refresh = () => setTick((t) => t + 1);
  // The tile being looked at; it defaults to the active source.
  const [picked, setPicked] = useState<DataSourceKind | null>(null);
  const view = picked ?? source.data?.active ?? 'excel';
  return (
    <div className="space-y-4">
      <Card className="gap-0 rounded-2xl px-5 py-3 shadow-xs">
        <h1 className="text-xl font-semibold tracking-tight">Data source</h1>
        <p className="mt-0.5 text-sm text-muted-foreground">
          Choose where every dashboard page reads its data: <strong>Excel workbook</strong> (upload the Master workbook) or
          <strong> PostgreSQL database</strong> (import workbooks into the database).
        </p>
      </Card>
      {source.error ? <Alert variant="destructive"><AlertTitle>Data source unavailable</AlertTitle><AlertDescription>{source.error.message}</AlertDescription></Alert>
        : source.data ? <SourceSelector state={source.data} view={view} onView={setPicked} onChanged={() => { setPicked(null); refresh(); }} />
          : <Skeleton className="h-40 w-full" />}
      {view === 'excel' ? <WorkbookPage embedded /> : (
        <>
          <ImportPanel onCommitted={refresh} />
          {history.data && <DatabaseContents state={history.data.database} imports={history.data.imports} />}
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

function ImportPanel({ onCommitted }: { onCommitted: () => void }) {
  const [file, setFile] = useState<File | null>(null);
  const [other, setOther] = useState<File | null>(null);
  const [project, setProject] = useState('');
  const [dailyOnly, setDailyOnly] = useState(false);
  const [batch, setBatch] = useState<ImportBatch | null>(null);
  const [choice, setChoice] = useState<'primary' | 'reconciliation' | ''>('');
  const [busy, setBusy] = useState<'preview' | 'commit' | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [done, setDone] = useState<ImportBatch | null>(null);
  const run = async (kind: 'preview' | 'commit') => {
    setBusy(kind);
    setError(null);
    try {
      if (kind === 'preview') {
        setDone(null);
        setChoice('');
        setBatch(await previewImport(file!, dailyOnly ? null : other, { project, dailyOnly }));
      } else {
        const result = await commitImport(batch!.id, choice);
        setDone(result);
        setBatch(null);
        onCommitted();
      }
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(null);
    }
  };
  const report = batch?.report;
  const differences = report?.comparison?.sites_with_differences ?? 0;
  return (
    <Card role="region" aria-label="Import into PostgreSQL">
      <CardHeader>
        <CardTitle className="text-sm font-semibold">Import a workbook into PostgreSQL</CardTitle>
        <CardDescription className="text-xs">
          Reads the Up-Time Report sheet. Nothing is written until you commit after the preview; records are inserted or updated, never deleted,
          and importing the same file again changes nothing. Importing does not switch the dashboard source.
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-4">
        <div className="grid grid-cols-1 gap-3 md:grid-cols-2">
          <div className="flex flex-col gap-1">
            <Label htmlFor="import-file" className="text-xs">Master workbook (consolidated, or a September workbook)</Label>
            <Input id="import-file" type="file" accept=".xlsx,.xlsm" onChange={(e) => setFile(e.target.files?.[0] ?? null)} />
          </div>
          <div className="flex flex-col gap-1">
            <Label htmlFor="import-other" className="text-xs">Second report to compare (optional, e.g. RJ, MP &amp; OD - Uptime Report)</Label>
            <Input id="import-other" type="file" accept=".xlsx,.xlsm" disabled={dailyOnly} onChange={(e) => setOther(e.target.files?.[0] ?? null)} />
          </div>
        </div>
        <div className="flex flex-wrap items-end gap-x-6 gap-y-2 text-xs">
          <div className="flex flex-col gap-1">
            <Label htmlFor="import-project" className="text-xs">Project, if the sheet has no Project column</Label>
            <select id="import-project" value={project} onChange={(e) => setProject(e.target.value)} className="h-9 rounded-md border bg-transparent px-2 text-sm">
              <option value="">From the Project column</option>
              <option value="4G Saturation">4G Saturation (e.g. the RJ, MP &amp; OD report)</option>
              <option value="LWE">LWE</option>
            </select>
          </div>
          <label className="flex max-w-md items-start gap-2">
            <input type="checkbox" className="mt-0.5 size-3.5 accent-primary" checked={dailyOnly} onChange={(e) => setDailyOnly(e.target.checked)} />
            <span><strong>Daily values only</strong>: add the day-wise values (e.g. a previous month&apos;s workbook) to sites already in the database,
              without changing site details or monthly figures.</span>
          </label>
        </div>
        <Button onClick={() => run('preview')} disabled={!file || busy !== null}>
          {busy === 'preview' ? <Loader2 className="animate-spin" /> : <Upload />} {busy === 'preview' ? 'Validating… (can take a minute)' : 'Preview import'}
        </Button>
        {error && <Alert variant="destructive"><AlertTriangle /><AlertTitle>Import not possible</AlertTitle><AlertDescription>{error}</AlertDescription></Alert>}
        {done && (
          <Alert className="border-emerald-200 bg-emerald-50/70" role="status">
            <CheckCircle2 className="text-emerald-700" />
            <AlertTitle>Import #{done.id} committed</AlertTitle>
            <AlertDescription>{(['sites', 'monthly', 'daily'] as const).map((k) => {
              const c = done.counts[k] as { inserted: number; updated: number; unchanged: number };
              return `${k}: ${formatNumber(c.inserted)} new, ${formatNumber(c.updated)} updated, ${formatNumber(c.unchanged)} unchanged`;
            }).join(' · ')}</AlertDescription>
          </Alert>
        )}
        {batch && report && (
          <section aria-label="Import preview" className="space-y-4 rounded-xl border p-4">
            <div className="flex flex-wrap items-center justify-between gap-2">
              <h2 className="text-sm font-semibold">Preview #{batch.id}: nothing has been written yet</h2>
              <a href={importIssuesUrl(batch.id)} className="inline-flex items-center gap-1 text-xs font-medium text-primary underline-offset-4 hover:underline"><Download className="size-3.5" /> Error report (CSV)</a>
            </div>
            {report.already_imported && (
              <Alert><CheckCircle2 /><AlertTitle>This exact file was already imported</AlertTitle>
                <AlertDescription>Import #{report.already_imported.batch} on {formatDateTime(report.already_imported.committed_at)}. Committing again changes nothing.</AlertDescription></Alert>
            )}
            <div className="grid grid-cols-1 gap-4 xl:grid-cols-2">
              <FileReport title="Master workbook" s={report.primary} />
              {report.reconciliation && <FileReport title="Second report" s={report.reconciliation} />}
            </div>
            <p className="text-xs text-muted-foreground">
              Database: {formatNumber(report.database_effect.new_sites)} new sites, {formatNumber(report.database_effect.existing_sites)} already there
              {report.database_effect.database_sites_not_in_file ? `; ${formatNumber(report.database_effect.database_sites_not_in_file)} sites in the database are not in this file and are kept` : ''}.
            </p>
            {report.daily_effect && (
              <div className="rounded-lg border border-sky-200 bg-sky-50/60 p-3 text-xs" role="region" aria-label="Daily values only">
                <p className="font-medium">Daily values only: {report.daily_effect.months.join(', ')}. Site details and monthly figures are not changed.</p>
                <p>{formatNumber(report.daily_effect.sites_in_database)} of {formatNumber(report.daily_effect.sites_in_file)} sites are in the database
                  {report.daily_effect.sites_not_in_database ? `; ${formatNumber(report.daily_effect.sites_not_in_database)} are not and will be skipped` : ''}.</p>
                {Object.entries(report.daily_effect.monthly_total_checks).map(([m, c]) => (
                  <p key={m}>{m}: daily values add up to the monthly total for {formatNumber(c.sites_compared - c.database_monthly_total_differs)} of {formatNumber(c.sites_compared)} sites
                    (database total){c.file_monthly_total_differs ? `; ${formatNumber(c.file_monthly_total_differs)} differ from the file's own total` : ''}.</p>
                ))}
              </div>
            )}
            {report.comparison && <Comparison c={report.comparison} choice={choice} onChoice={setChoice} />}
            <div className="flex flex-wrap gap-2">
              <Button onClick={() => run('commit')} disabled={busy !== null || (differences > 0 && !choice)}>
                {busy === 'commit' ? <Loader2 className="animate-spin" /> : <Database />} {busy === 'commit' ? 'Importing… (can take two minutes)' : 'Commit import'}
              </Button>
              <Button variant="ghost" disabled={busy !== null} onClick={async () => { await discardImport(batch.id); setBatch(null); onCommitted(); }}>Discard preview</Button>
              {differences > 0 && !choice && <span className="self-center text-xs text-amber-800">Choose which file's values to apply first.</span>}
            </div>
          </section>
        )}
      </CardContent>
    </Card>
  );
}

function Stat({ label, children }: { label: string; children: ReactNode }) {
  return <div><dt className="text-[11px] text-muted-foreground">{label}</dt><dd className="text-sm font-semibold tabular-nums">{children}</dd></div>;
}

function FileReport({ title, s }: { title: string; s: ImportFileSummary }) {
  const issues = Object.entries(s.issues);
  return (
    <div className="space-y-3 rounded-lg bg-muted/40 p-3 text-xs">
      <p className="font-medium">{title}: <span className="font-normal">{s.filename} · sheet “{s.sheet}”{s.has_project_column ? '' : ' · no Project column (read as 4G Saturation)'}</span></p>
      <dl className="grid grid-cols-3 gap-2 sm:grid-cols-6">
        <Stat label="Data rows">{formatNumber(s.data_rows)}</Stat>
        <Stat label="Sites">{formatNumber(s.sites)}</Stat>
        <Stat label="Distinct IDs">{formatNumber(s.distinct_site_ids)}</Stat>
        <Stat label="Rejected"><span className={s.rejected ? 'text-destructive' : undefined}>{formatNumber(s.rejected)}</span></Stat>
        <Stat label="Flagged">{formatNumber(s.flagged)}</Stat>
        <Stat label="Skipped (blank / totals)">{formatNumber(Object.values(s.skipped).reduce((a, b) => a + b, 0))}</Stat>
      </dl>
      <p><span className="text-muted-foreground">By project:</span> {Object.entries(s.by_project).map(([k, v]) => `${k} ${formatNumber(v)}`).join(' · ')}</p>
      <p><span className="text-muted-foreground">By circle:</span> {Object.entries(s.by_circle).map(([k, v]) => `${short(k)} ${formatNumber(v)}`).join(' · ')}</p>
      <p><span className="text-muted-foreground">Monthly (sites with values):</span> {Object.values(s.months).map((m) => `${m.label} ${formatNumber(m.sites_with_values)}`).join(' · ')}</p>
      {Object.entries(s.daily).map(([k, d]) => (
        <p key={k}>
          <span className="text-muted-foreground">Daily {k} (outage {d.outage_columns}{d.uptime_columns ? `, uptime ${d.uptime_columns}` : ''}):</span>{' '}
          {d.reported_dates.length ? `${formatDate(d.reported_dates[0])} – ${formatDate(d.reported_dates.at(-1))}, ${d.reported_dates.length} reported dates, ${formatNumber(d.site_day_values)} values` : 'no reported dates'}
          {Object.keys(d.missing_values).length ? `; missing values on ${Object.keys(d.missing_values).length} dates` : '; no missing values'}
        </p>
      ))}
      {issues.length > 0 ? (
        <ul className="space-y-1">{issues.map(([code, i]) => (
          <li key={code}><Badge variant={i.severity === 'rejected' ? 'destructive' : 'outline'}>{i.severity}</Badge> {code}: {formatNumber(i.count)} (e.g. {i.examples.slice(0, 3).map((e) => `row ${e.row ?? '—'} ${e.site_id}`).join(', ')})</li>
        ))}</ul>
      ) : <p className="text-emerald-800">No rejected or flagged rows.</p>}
    </div>
  );
}

function Comparison({ c, choice, onChoice }: { c: ImportComparison; choice: string; onChoice: (v: 'primary' | 'reconciliation') => void }) {
  return (
    <div className="space-y-2 rounded-lg border border-amber-300 bg-amber-50/50 p-3 text-xs" role="region" aria-label="Differences between the two files">
      <p className="text-sm font-medium">
        {formatNumber(c.overlapping_sites)} sites in both files · {formatNumber(c.sites_with_differences)} with differences
        {c.only_in_primary || c.only_in_reconciliation ? ` · ${c.only_in_primary} only in the workbook, ${c.only_in_reconciliation} only in the second report` : ''}
      </p>
      {c.dates_only_in_reconciliation.length > 0 && <p>Dates only in the second report: {c.dates_only_in_reconciliation.map(formatDate).join(', ')}.</p>}
      <div className="max-h-64 overflow-auto rounded border bg-background">
        <table className="w-full text-left">
          <thead className="sticky top-0 bg-muted"><tr><th className="px-2 py-1">Field</th><th className="px-2 py-1 text-right">Sites</th><th className="px-2 py-1">Example</th></tr></thead>
          <tbody className="divide-y">
            {Object.entries(c.differences).map(([field, d]) => {
              const e = d.examples[0];
              return (
                <tr key={field}>
                  <td className="px-2 py-1 font-medium">{field}</td>
                  <td className="px-2 py-1 text-right tabular-nums">{formatNumber(d.count)}</td>
                  <td className="px-2 py-1">{e ? `${e.circle} ${e.site_id}${e.where ? ` ${e.where}` : ''}: ${value(e.primary)} vs ${value(e.reconciliation)}` : ''}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
      <fieldset className="space-y-1">
        <legend className="font-medium">For sites in both files, apply the values from:</legend>
        <label className="flex items-center gap-2"><input type="radio" name="conflict" checked={choice === 'primary'} onChange={() => onChoice('primary')} /> the Master workbook ({c.primary})</label>
        <label className="flex items-center gap-2"><input type="radio" name="conflict" checked={choice === 'reconciliation'} onChange={() => onChoice('reconciliation')} /> the second report ({c.reconciliation})</label>
      </fieldset>
    </div>
  );
}

function DatabaseContents({ state, imports }: { state: import('../types').DatabaseCompleteness; imports: ImportBatch[] }) {
  return (
    <Card role="region" aria-label="Database contents">
      <CardHeader>
        <CardTitle className="text-sm font-semibold">PostgreSQL contents</CardTitle>
        <CardDescription className="text-xs">
          {formatNumber(state.sites)} sites · {formatNumber(state.monthly_records)} monthly records ({state.months.length} months) · {formatNumber(state.daily_records)} daily records
          {Object.values(state.daily_months).map((m) => ` · ${m.label} daily ${formatDate(m.first)} – ${formatDate(m.last)} (${m.days} days)`).join('')}
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-3">
        {state.warnings.length > 0 && <Warnings title="Data completeness" items={state.warnings} />}
        <div className="overflow-x-auto rounded-md border">
          <table className="w-full text-left text-xs">
            <caption className="sr-only">Import history</caption>
            <thead className="bg-muted"><tr>{['#', 'File', 'Status', 'By', 'Committed', 'Sites (new / updated)', 'Daily (new / updated)', 'Rejected'].map((h) => <th key={h} className="px-2.5 py-1.5 font-medium">{h}</th>)}</tr></thead>
            <tbody className="divide-y">
              {imports.map((b) => {
                const n = (k: string) => { const c = b.counts[k] as { inserted: number; updated: number } | undefined; return c ? `${formatNumber(c.inserted)} / ${formatNumber(c.updated)}` : '—'; };
                return (
                  <tr key={b.id}>
                    <td className="px-2.5 py-1.5">{b.id}</td>
                    <td className="px-2.5 py-1.5">{b.file}{b.reconciliation_file ? ` + ${b.reconciliation_file} (applied: ${b.conflict_source ?? '—'})` : ''}</td>
                    <td className="px-2.5 py-1.5"><Badge variant={b.status === 'committed' ? 'default' : b.status === 'failed' ? 'destructive' : 'outline'}>{b.status}</Badge></td>
                    <td className="px-2.5 py-1.5">{b.imported_by ?? b.via}</td>
                    <td className="px-2.5 py-1.5">{b.committed_at ? formatDateTime(b.committed_at) : '—'}</td>
                    <td className="px-2.5 py-1.5 tabular-nums">{n('sites')}</td>
                    <td className="px-2.5 py-1.5 tabular-nums">{n('daily')}</td>
                    <td className="px-2.5 py-1.5 tabular-nums">{formatNumber(b.rejected)}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      </CardContent>
    </Card>
  );
}
