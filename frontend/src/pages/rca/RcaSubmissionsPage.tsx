import { useState } from 'react';
import { Link, useSearchParams } from 'react-router-dom';
import { Download, FileCheck2 } from 'lucide-react';
import { Alert, AlertDescription } from '@/components/ui/alert';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card } from '@/components/ui/card';
import { Input } from '@/components/ui/input';
import { Skeleton } from '@/components/ui/skeleton';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table';
import { Field, SelectField } from '../../components/data/DataEntry';
import { Field as FilterField, FilterCard } from '../../components/dashboard/FilterBar';
import { CycleBadge } from '../../components/rca/RcaShared';
import { PageHeading } from '../../context/pageHeader';
import { useApiQuery } from '../../hooks/useApiQuery';
import { formatDateTime, formatNumber } from '../../lib/format';
import { formatMin, periodText, shortProject } from '../../lib/rca';
import {
  fetchRcaCycle, fetchRcaCycles, fetchRcaImports, finalizeRcaCycle, rcaCycleWorkbookUrl, rcaIssuesUrl, rcaReportFileUrl, setRcaRequired, startRcaCycle,
} from '../../services/api';
import type { RcaCycle, RcaCycleDetail, RcaImportBatch } from '../../types/rca';

type Unit = [string, string];
const unitKey = ([p, c]: Unit) => `${p}|${c}`;

/**
 * RCA Submissions (Admin): every upload and every reporting period. For a period, the expected projects / circles
 * (configured here) are compared with the accepted records: a unit is received only when accepted records of that
 * project and circle exist. Upload status is shown apart from period completeness. Every figure comes from the API.
 */
export function RcaSubmissionsPage() {
  const [params, setParams] = useSearchParams();
  const [version, setVersion] = useState(0);
  const list = useApiQuery(`rca-cycles-${version}`, (signal) => fetchRcaCycles(signal));
  const all = useApiQuery(`rca-all-uploads-${version}`, (signal) => fetchRcaImports(signal, true));
  const selected = Number(params.get('cycle')) || list.data?.cycles[0]?.id || null;
  const detail = useApiQuery(selected ? `rca-cycle-${selected}-${version}` : null, (signal) => fetchRcaCycle(selected!, signal));
  const [starting, setStarting] = useState(false);
  const refresh = () => setVersion((v) => v + 1);
  const choose = (id: number) => setParams((cur) => { const next = new URLSearchParams(cur); next.set('cycle', String(id)); return next; }, { replace: true });
  const cycle = detail.data && detail.data.id === selected ? detail.data : null;

  return (
    <div className="space-y-4">
      <PageHeading title="RCA Submissions"
        subtitle={`${list.data ? `${list.data.cycles.length} reporting period${list.data.cycles.length === 1 ? '' : 's'}` : 'Loading'} · circle submissions (confirmed circle files) are tracked apart from RCA data availability`} />
      {list.error && <Alert variant="destructive"><AlertDescription>{list.error.message}</AlertDescription></Alert>}
      <FilterCard label="Reporting period"
        footer={list.data && !list.data.cycles.length && !starting
          ? 'No reporting period yet. The first accepted upload creates its period; you can also start one here with its expected scope.' : undefined}
        actions={(
          <>
            <Button asChild variant="outline" className="h-9"><Link to="/rca/import">Upload RCA data</Link></Button>
            <Button type="button" className="h-9" variant={starting ? 'ghost' : 'outline'} onClick={() => setStarting((s) => !s)}>{starting ? 'Cancel' : 'Start a reporting period'}</Button>
          </>
        )}>
        {list.data && list.data.cycles.length > 0 && (
          <FilterField id="rca-cycle" label="Reporting period" className="w-[28rem] max-w-full">
            <SelectField id="rca-cycle" value={selected ? String(selected) : ''} placeholder="Choose a period" onChange={(v) => choose(Number(v))}
              options={list.data.cycles.map((c) => ({ value: String(c.id), label: `${c.period_label}${c.name ? ` · ${c.name}` : ''} · ${c.status.label}` }))} />
          </FilterField>
        )}
      </FilterCard>
      {starting && list.data && (
        <StartPeriod defaults={list.data.default_units} available={list.data.available_units}
          onStarted={(created) => { setStarting(false); choose(created.id); refresh(); }} />
      )}

      {list.data && list.data.cycles.length > 0 && <DailyStatus cycles={list.data.cycles} selected={selected} onOpen={choose} />}

      {detail.error && <Alert variant="destructive"><AlertDescription>{detail.error.message}</AlertDescription></Alert>}
      {selected && !cycle && !detail.error && <Skeleton className="h-72 w-full" />}
      {cycle && <PeriodView key={cycle.id} cycle={cycle} onChanged={refresh} />}

      <Card className="gap-2 rounded-xl px-5 py-4" aria-label="All uploads">
        <h2 className="text-base font-semibold">All uploads</h2>
        {all.data ? <UploadTable uploads={all.data.imports} showPeriod empty="No RCA data has been uploaded yet." />
          : <p className="text-sm text-muted-foreground">{all.error ? all.error.message : 'Loading…'}</p>}
      </Card>
    </div>
  );
}

/** One row per reporting date (or period): completeness from the expected scope, and the upload outcomes beside it. */
function DailyStatus({ cycles, selected, onOpen }: { cycles: RcaCycle[]; selected: number | null; onOpen: (id: number) => void }) {
  return (
    <Card className="gap-2 rounded-xl px-5 py-4" aria-label="Daily reporting status">
      <h2 className="text-base font-semibold">Daily reporting status</h2>
      <div className="overflow-x-auto">
        <Table>
          <TableHeader>
            <TableRow>{['Reporting date', 'Report', 'Status', 'Expected data received', 'Pending', 'Imported uploads', 'Validation failed', 'Awaiting confirmation', 'Corrections', 'Last upload', ''].map((h) => <TableHead key={h}>{h}</TableHead>)}</TableRow>
          </TableHeader>
          <TableBody>
            {cycles.map((c) => {
              const u = c.uploads_summary;
              return (
                <TableRow key={c.id} className={c.id === selected ? 'bg-muted/50' : undefined}>
                  <TableCell className="font-medium whitespace-nowrap">{c.period_label}</TableCell>
                  <TableCell className="max-w-44 truncate" title={c.name ?? ''}>{c.name ?? '—'}</TableCell>
                  <TableCell><CycleBadge code={c.status.code} label={c.status.label} /></TableCell>
                  <TableCell className="tabular-nums">{c.status.required ? `${c.status.received} of ${c.status.required}` : 'Scope not configured'}</TableCell>
                  <TableCell className="max-w-56 min-w-40 text-xs whitespace-normal">{c.status.outstanding.map((o) => `${o.circle} ${shortProject(o.project)}`).join(', ') || '—'}</TableCell>
                  <TableCell className="tabular-nums">{formatNumber(u.imported)}{u.with_rejected_rows ? <span className="text-xs text-destructive"> ({u.with_rejected_rows} with rejected rows)</span> : null}</TableCell>
                  <TableCell className={`tabular-nums ${u.validation_failed ? 'text-destructive' : ''}`}>{formatNumber(u.validation_failed)}</TableCell>
                  <TableCell className="tabular-nums">{formatNumber(u.awaiting_confirmation)}</TableCell>
                  <TableCell className={`tabular-nums ${u.corrections ? 'text-amber-800' : ''}`}>{formatNumber(u.corrections)}</TableCell>
                  <TableCell className="whitespace-nowrap">{u.last_upload_at ? formatDateTime(u.last_upload_at) : '—'}</TableCell>
                  <TableCell><Button type="button" size="sm" variant="ghost" onClick={() => onOpen(c.id)} aria-label={`Open ${c.period_label}`}>Open</Button></TableCell>
                </TableRow>
              );
            })}
          </TableBody>
        </Table>
      </div>
    </Card>
  );
}

function StartPeriod({ defaults, available, onStarted }: { defaults: Unit[]; available: Unit[]; onStarted: (c: RcaCycleDetail) => void }) {
  const [period, setPeriod] = useState({ name: '', period_start: '', period_end: '', notes: '' });
  const [units, setUnits] = useState<Set<string>>(() => new Set(defaults.map(unitKey)));
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const set = (key: keyof typeof period, value: string) => setPeriod((p) => ({ ...p, [key]: value }));
  const start = async () => {
    setBusy(true);
    setError(null);
    try {
      onStarted(await startRcaCycle(period, available.filter((u) => units.has(unitKey(u)))));
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  };
  return (
    <div className="space-y-3 rounded-lg border bg-muted/30 px-4 py-3" aria-label="Start a reporting period">
      <div className="flex flex-wrap items-end gap-3">
        <Field id="period-name" label="Report name" plain className="min-w-64 flex-1">
          <Input id="period-name" value={period.name} onChange={(e) => set('name', e.target.value)} placeholder="e.g. October 2026 RCA Report" />
        </Field>
        <Field id="period-from" label="Reporting date (or first day)" plain className="w-52">
          <Input id="period-from" type="date" value={period.period_start} onChange={(e) => set('period_start', e.target.value)} />
        </Field>
        <Field id="period-to" label="Last day (for a period)" plain className="w-52">
          <Input id="period-to" type="date" value={period.period_end} min={period.period_start || undefined} onChange={(e) => set('period_end', e.target.value)} />
        </Field>
      </div>
      <UnitPicker available={available} value={units} onChange={setUnits} />
      {error && <Alert variant="destructive"><AlertDescription>{error}</AlertDescription></Alert>}
      <Button type="button" onClick={start} disabled={busy || !period.period_start}>{busy ? 'Starting…' : `Start period expecting ${units.size} projects / circles`}</Button>
    </div>
  );
}

/** Expected scope: one checkbox per project / circle of the Up-Time Report. */
function UnitPicker({ available, value, onChange }: { available: Unit[]; value: Set<string>; onChange: (v: Set<string>) => void }) {
  const projects = [...new Set(available.map(([p]) => p))];
  const toggle = (key: string) => { const next = new Set(value); if (next.has(key)) next.delete(key); else next.add(key); onChange(next); };
  return (
    <div className="space-y-2">
      <p className="text-xs font-medium">Expected projects and circles</p>
      {projects.map((project) => (
        <fieldset key={project} className="flex flex-wrap items-center gap-x-4 gap-y-1">
          <legend className="mb-1 text-xs text-muted-foreground">{project}</legend>
          {available.filter(([p]) => p === project).map((u) => (
            <label key={unitKey(u)} className="flex items-center gap-1.5 text-sm">
              <input type="checkbox" checked={value.has(unitKey(u))} onChange={() => toggle(unitKey(u))} aria-label={`${project} ${u[1]}`} />
              {u[1]}
            </label>
          ))}
        </fieldset>
      ))}
    </div>
  );
}

function PeriodView({ cycle, onChanged }: { cycle: RcaCycleDetail; onChanged: () => void }) {
  const s = cycle.status;
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [done, setDone] = useState<string | null>(null);
  const finalize = async () => {
    setBusy(true);
    setError(null);
    try {
      const result = await finalizeRcaCycle(cycle.id);
      setDone(result.created ? `Final report v${result.report.version} generated from ${formatNumber(result.report.record_count)} accepted records.`
        : `The final report v${result.report.version} already reflects the accepted records; no new version was created.`);
      onChanged();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  };
  const current = cycle.reports.find((r) => r.current);

  return (
    <>
      <Card className="gap-3 rounded-xl px-5 py-4" aria-label="Period status">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div className="space-y-1">
            <h2 className="flex flex-wrap items-center gap-2 text-base font-semibold">
              {cycle.name ?? 'Reporting period'} · {cycle.period_label} <CycleBadge code={s.code} label={s.label} />
              {s.final_version && <span className="text-xs font-normal text-muted-foreground">latest final: v{s.final_version}</span>}
            </h2>
            <p className="text-sm">
              {s.required ? <><span className="font-semibold tabular-nums">{s.received} of {s.required}</span> expected projects / circles have accepted data · </>
                : <span className="text-amber-800">No expected projects / circles are configured, so completeness cannot be judged. </span>}
              <span className="tabular-nums">{formatNumber(cycle.records)}</span> accepted RCA records in the period
            </p>
            {s.outstanding.length > 0 && (
              <p className="text-sm text-amber-800">Pending (no accepted records): {s.outstanding.map((o) => `${o.circle} ${shortProject(o.project)}`).join(', ')}</p>
            )}
            {s.upload_awaiting_confirmation && <p className="text-sm text-amber-800">An upload for this period is validated but not yet confirmed; its rows do not count until imported.</p>}
            {s.code === 'revised' && <p className="text-sm text-orange-800">Records changed after final report v{s.final_version}. Review the change, then generate the revised version; v{s.final_version} stays available.</p>}
          </div>
          <div className="flex flex-wrap gap-2">
            <Button asChild variant="outline">
              <a href={rcaCycleWorkbookUrl(cycle.id)}><Download />{s.code === 'final' && current ? `Download final report v${current.version}` : s.complete ? 'Download draft report' : 'Download partial report'}</a>
            </Button>
            {s.can_finalize && (
              <Button type="button" onClick={finalize} disabled={busy}>
                <FileCheck2 />{busy ? 'Generating…' : s.code === 'revised' ? `Generate revised final report (v${(s.final_version ?? 0) + 1})` : 'Generate final report'}
              </Button>
            )}
          </div>
        </div>
        {!s.complete && <p className="text-xs text-muted-foreground">The downloaded workbook is labelled partial until every expected project / circle has accepted data.</p>}
        {error && <Alert variant="destructive"><AlertDescription>{error}</AlertDescription></Alert>}
        {done && <Alert><AlertDescription>{done}</AlertDescription></Alert>}
      </Card>

      <Card className="gap-2 rounded-xl px-5 py-4" aria-label="Expected coverage">
        <h2 className="text-base font-semibold">Circle submissions and RCA data</h2>
        <p className="text-xs text-muted-foreground">
          Circle submission: a confirmed Upload Circle RCA file of that project, circle and date (consolidated uploads never count). RCA data: accepted records of
          the project and circle, from any upload; the final report needs data for every expected unit. No deadline is configured, so receipt times are shown without
          on-time or late.
        </p>
        {cycle.units.length ? (
          <div className="overflow-x-auto">
            <Table>
              <TableHeader><TableRow>{['Circle', 'Project', 'Circle submission', 'Received', 'RCA data', 'Accepted records', 'Outage minutes', 'From uploaded files'].map((h) => <TableHead key={h}>{h}</TableHead>)}</TableRow></TableHeader>
              <TableBody>
                {cycle.units.map((u) => (
                  <TableRow key={`${u.project}|${u.circle}`}>
                    <TableCell className="font-medium">{u.circle}</TableCell>
                    <TableCell>{u.project}</TableCell>
                    <TableCell>
                      <Badge variant="outline" className={u.submission_status === 'received' ? 'border-emerald-300 text-emerald-800' : 'border-slate-300 text-slate-600'}>
                        {u.submission_label ?? 'Not received'}
                      </Badge>
                    </TableCell>
                    <TableCell className="text-xs whitespace-nowrap">
                      {u.submission ? <>{formatDateTime(u.submission.committed_at ?? u.submission.uploaded_at)}<span className="block text-muted-foreground">by {u.submission.uploaded_by ?? '—'} · #{u.submission.batch}</span></> : '—'}
                    </TableCell>
                    <TableCell><CycleBadge code={u.status} label={u.data_label ?? u.status_label} /></TableCell>
                    <TableCell className="tabular-nums">{formatNumber(u.records)}</TableCell>
                    <TableCell className="tabular-nums">{u.records ? formatMin(u.outage_minutes) : '—'}</TableCell>
                    <TableCell className="max-w-80 truncate text-xs" title={u.source_files.join(', ')}>{u.source_files.join(', ') || '—'}</TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </div>
        ) : <p className="text-sm text-muted-foreground">Configure the expected projects and circles below to track what is still pending.</p>}
        {cycle.unexpected.length > 0 && (
          <p className="text-xs text-muted-foreground">Also in the accepted data, outside the expected scope: {cycle.unexpected.map((u) => `${u.circle} ${shortProject(u.project)} (${formatNumber(u.records)})`).join(', ')}.</p>
        )}
      </Card>

      <ScopeEditor cycle={cycle} onChanged={onChanged} />

      <Card className="gap-2 rounded-xl px-5 py-4" aria-label="Period uploads">
        <h2 className="text-base font-semibold">Uploads for this period</h2>
        <UploadTable uploads={cycle.uploads} empty="No upload for this period yet." />
      </Card>

      <Card className="gap-2 rounded-xl px-5 py-4" aria-label="Final reports">
        <h2 className="text-base font-semibold">Final reports</h2>
        {cycle.reports.length ? (
          <Table>
            <TableHeader><TableRow>{['Version', 'Generated', 'By', 'Records', 'Status', ''].map((h) => <TableHead key={h}>{h}</TableHead>)}</TableRow></TableHeader>
            <TableBody>
              {cycle.reports.map((r) => (
                <TableRow key={r.id}>
                  <TableCell className="font-medium">v{r.version}</TableCell>
                  <TableCell className="whitespace-nowrap">{formatDateTime(r.generated_at)}</TableCell>
                  <TableCell>{r.automatic ? 'Automatic (expected data complete)' : r.generated_by ?? '—'}</TableCell>
                  <TableCell className="tabular-nums">{formatNumber(r.record_count)}</TableCell>
                  <TableCell>{r.current ? (s.code === 'revised' ? 'Current, records changed since' : 'Current') : `Superseded ${formatDateTime(r.superseded_at)}`}</TableCell>
                  <TableCell>{r.available ? <a href={rcaReportFileUrl(cycle.id, r.id)} className="text-xs underline">{r.filename}</a> : <span className="text-xs text-destructive">File missing</span>}</TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        ) : <p className="text-sm text-muted-foreground">No final report yet. It is generated once every expected project / circle has accepted data.</p>}
      </Card>
    </>
  );
}

function UploadTable({ uploads, showPeriod = false, empty }: { uploads: RcaImportBatch[]; showPeriod?: boolean; empty: string }) {
  if (!uploads.length) return <p className="text-sm text-muted-foreground">{empty}</p>;
  const headers = ['#', 'Report', ...(showPeriod ? ['Period'] : []), 'Uploaded by', 'File', 'Type · scope', 'Uploaded', 'Status', 'Circles in workbook', 'Imported · updated · skipped · rejected', ''];
  return (
    <div className="overflow-x-auto">
      <Table>
        <TableHeader><TableRow>{headers.map((h) => <TableHead key={h}>{h}</TableHead>)}</TableRow></TableHeader>
        <TableBody>
          {uploads.map((b) => {
            const c = b.counts;
            const n = (v: number | boolean | undefined) => (typeof v === 'number' ? formatNumber(v) : '—');
            const problem = b.status === 'failed' || b.status === 'rejected' || (b.status === 'committed' && Number(c.rejected) > 0);
            return (
              <TableRow key={b.id}>
                <TableCell>{b.id}</TableCell>
                <TableCell className="max-w-44 truncate" title={b.report_name ?? ''}>{b.report_name ?? '—'}</TableCell>
                {showPeriod && <TableCell className="whitespace-nowrap">{periodText(b.period_start, b.period_end)}</TableCell>}
                <TableCell>{b.imported_by ?? '—'}</TableCell>
                <TableCell className="max-w-44 truncate" title={b.file}>{b.file}</TableCell>
                <TableCell className="text-xs">
                  {b.upload_type === 'circle' ? `Circle · ${b.circle} ${b.project_scope ? shortProject(b.project_scope) : ''}` : b.upload_type === 'consolidated' ? 'Consolidated' : 'Legacy'}
                  <span className="block text-muted-foreground">{b.project_scope === 'both' ? '4G + LWE' : b.project_scope ? shortProject(b.project_scope) : '—'}</span>
                </TableCell>
                <TableCell className="whitespace-nowrap">{formatDateTime(b.uploaded_at)}</TableCell>
                <TableCell className={problem ? 'text-destructive' : ''}>
                  {b.status_label}{b.correction && <span className="block text-xs text-amber-800">Correction</span>}
                </TableCell>
                <TableCell className="max-w-56 min-w-32 text-xs whitespace-normal">{b.units.map(([p, ci]) => `${ci} ${shortProject(p)}`).join(', ') || '—'}</TableCell>
                <TableCell className="text-xs tabular-nums">{b.status === 'committed' ? `${n(c.inserted)} · ${n(c.updated)} · ${n(c.skipped)} · ${n(c.rejected)}` : b.error ?? `${n(c.valid)} valid · ${n(c.rejected)} rejected`}</TableCell>
                <TableCell>{b.status !== 'discarded' && <a href={rcaIssuesUrl(b.id)} className="text-xs underline">Validation report</a>}</TableCell>
              </TableRow>
            );
          })}
        </TableBody>
      </Table>
    </div>
  );
}

function ScopeEditor({ cycle, onChanged }: { cycle: RcaCycleDetail; onChanged: () => void }) {
  const initial = () => new Set(cycle.units.map((u) => unitKey([u.project, u.circle])));
  const [open, setOpen] = useState(false);
  const [value, setValue] = useState<Set<string>>(initial);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const known = [...cycle.available_units];
  for (const u of cycle.units) if (!known.some(([p, c]) => p === u.project && c === u.circle)) known.push([u.project, u.circle]);
  const save = async () => {
    setBusy(true);
    setError(null);
    try {
      await setRcaRequired(cycle.id, known.filter((u) => value.has(unitKey(u))));
      setOpen(false);
      onChanged();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  };
  return (
    <Card className="gap-2 rounded-xl px-5 py-4" aria-label="Configure expected scope">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h2 className="text-base font-semibold">Expected projects and circles</h2>
        {cycle.locked ? <span className="text-xs text-muted-foreground">Fixed: the final report has been generated.</span>
          : <Button type="button" size="sm" variant="ghost" onClick={() => { setValue(initial()); setOpen((o) => !o); }}>{open ? 'Cancel' : cycle.units.length ? 'Change' : 'Configure'}</Button>}
      </div>
      {open && !cycle.locked && (
        <>
          <UnitPicker available={known} value={value} onChange={setValue} />
          {error && <Alert variant="destructive"><AlertDescription>{error}</AlertDescription></Alert>}
          <Button type="button" className="w-fit" onClick={save} disabled={busy}>{busy ? 'Saving…' : `Save ${value.size} expected projects / circles`}</Button>
        </>
      )}
    </Card>
  );
}
