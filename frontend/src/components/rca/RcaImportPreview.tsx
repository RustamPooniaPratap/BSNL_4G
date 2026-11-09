import { useState } from 'react';
import { Download } from 'lucide-react';
import { Alert, AlertDescription } from '@/components/ui/alert';
import { Button } from '@/components/ui/button';
import { Card } from '@/components/ui/card';
import { formatDate, formatNumber } from '../../lib/format';
import { periodText } from '../../lib/rca';
import { rcaIssuesUrl } from '../../services/api';
import type { RcaImportBatch } from '../../types/rca';
import { Segmented } from './RcaShared';

export type ConflictAction = 'skip' | 'overwrite';
export type MissingAction = 'keep' | 'withdraw';
export interface CommitChoices { conflict_action: ConflictAction | ''; missing_action: MissingAction | ''; accept_rejected: boolean }

/**
 * The validation result of an uploaded RCA workbook (nothing is in the database yet) with the import decision.
 * Rejected rows, rows that differ from stored records and stored records a corrected workbook no longer lists each
 * need an explicit choice before the import. A workbook without any valid row cannot be imported.
 */
export function RcaImportPreview({ batch, busy, onCommit, onDiscard }: {
  batch: RcaImportBatch; busy: boolean; onCommit: (choices: CommitChoices) => void; onDiscard: () => void;
}) {
  const [conflicts, setConflicts] = useState<ConflictAction>('skip');
  const [missing, setMissing] = useState<MissingAction>('keep');
  const [acceptRejected, setAcceptRejected] = useState(false);
  const r = batch.report;
  if (!r) return null;
  const rejected = batch.status === 'rejected';
  const missingRows = r.missing_rows ?? 0;
  const restored = r.restored_rows ?? 0;
  const needsRejectedConfirmation = !rejected && r.rejected_rows > 0;
  const tiles: [string, number, boolean][] = [
    ['Rows read', r.rows_read, false], ['Valid rows', r.valid_rows, false], ['Rejected rows', r.rejected_rows, true],
    ['New records', r.new_rows + restored, false], ['Already stored (duplicates)', r.unchanged_rows, false],
    ['Differ from stored', r.conflict_rows, true], ['Stored, not in workbook', missingRows, true],
  ];

  return (
    <Card className="gap-4 rounded-xl px-5 py-4" aria-label="Import preview">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h2 className="text-base font-semibold">{rejected ? 'Rejected' : 'Validation result'}: {batch.report_name ?? batch.file}</h2>
          <p className="text-xs text-muted-foreground">
            {batch.file} · sheet “{r.sheet}”{r.header_row && r.header_row > 1 ? ` (header on row ${r.header_row})` : ''} · upload #{batch.id} · reporting period {periodText(batch.period_start, batch.period_end)}
            {batch.project_scope ? ` · ${batch.project_scope === 'both' ? '4G Saturation and LWE' : batch.project_scope}` : ''} · not yet imported
          </p>
        </div>
        <a href={rcaIssuesUrl(batch.id)} className="inline-flex items-center gap-1.5 text-sm font-medium underline underline-offset-2"><Download className="size-4" /> Validation report (CSV)</a>
      </div>
      {rejected && (
        <Alert variant="destructive"><AlertDescription>
          {batch.error} Previously imported data is unchanged. Download the validation report, correct the workbook and upload it again.
        </AlertDescription></Alert>
      )}
      {r.already_imported && (
        <Alert><AlertDescription>This exact workbook was already imported (upload #{r.already_imported.batch}, {new Date(r.already_imported.committed_at).toLocaleString('en-IN')}). Importing it again adds nothing.</AlertDescription></Alert>
      )}
      {r.is_correction && (
        <Alert className="border-amber-300 bg-amber-50"><AlertDescription>
          Correction: this period already has {r.earlier_uploads_for_period} imported upload{r.earlier_uploads_for_period === 1 ? '' : 's'}, and this workbook changes or drops some of their records. Review the differences below.
        </AlertDescription></Alert>
      )}
      {r.coverage && r.coverage.missing.length > 0 && (
        <Alert className="border-amber-300 bg-amber-50"><AlertDescription>
          No rows for the reporting date from {r.coverage.missing.map(([p, c]) => `${c} ${p === '4G Saturation' ? '4G' : p}`).join(', ')}
          {' '}(expected by the {r.coverage.source === 'period' ? 'reporting period' : 'previous period’s'} scope). They stay pending until data for them is imported.
        </AlertDescription></Alert>
      )}
      {r.coverage && !r.coverage.expected.length && (
        <p className="text-xs text-muted-foreground">No expected projects / circles are configured yet, so coverage is not checked; an Admin sets them on RCA Submissions.</p>
      )}
      <dl className="grid gap-3 sm:grid-cols-4 lg:grid-cols-7">
        {tiles.map(([label, value, warn]) => (
          <div key={label} className="rounded-lg border px-3 py-2">
            <dt className="text-xs text-muted-foreground">{label}</dt>
            <dd className={`text-lg font-semibold tabular-nums ${warn && value ? 'text-destructive' : ''}`}>{formatNumber(value)}</dd>
          </div>
        ))}
      </dl>
      {r.by_date && r.by_date.length > 0 && (
        <div className="overflow-x-auto">
          <table className="w-full text-xs" aria-label="Rows by reporting date">
            <thead><tr className="border-b text-left text-muted-foreground">
              {['Date', 'Rows', 'New', 'Already stored', 'Differ from stored', 'Stored, not in workbook', 'Classified as'].map((h) => <th key={h} className="px-2 py-1 font-medium">{h}</th>)}
            </tr></thead>
            <tbody>
              {r.by_date.map((d) => (
                <tr key={d.date} className={`border-b last:border-0 ${d.earlier_date ? 'text-muted-foreground' : ''}`}>
                  <td className="px-2 py-1 whitespace-nowrap">{formatDate(d.date)}</td>
                  <td className="px-2 py-1 tabular-nums">{formatNumber(d.rows)}</td>
                  <td className="px-2 py-1 tabular-nums">{formatNumber(d.new)}</td>
                  <td className="px-2 py-1 tabular-nums">{formatNumber(d.unchanged)}</td>
                  <td className={`px-2 py-1 tabular-nums ${d.changed ? 'text-destructive' : ''}`}>{formatNumber(d.changed)}</td>
                  <td className={`px-2 py-1 tabular-nums ${d.missing ? 'text-destructive' : ''}`}>{d.earlier_date ? '— (never withdrawn)' : formatNumber(d.missing)}</td>
                  <td className="px-2 py-1">{d.kind}</td>
                </tr>
              ))}
            </tbody>
          </table>
          {(r.earlier_date_rows ?? 0) > 0 && <p className="mt-1 text-xs text-muted-foreground">The workbook also repeats earlier dates ({formatNumber(r.earlier_date_rows!)} rows): identical rows are skipped, new ones are added under their own date, differences need your choice below, and nothing of an earlier date is withdrawn.</p>}
        </div>
      )}
      <div className="grid gap-4 text-sm lg:grid-cols-3">
        <Counts title="Reporting dates" items={Object.entries(r.dates).map(([d, n]) => [formatDate(d), n])} />
        <Counts title="Project and circle (valid rows)" items={Object.entries(r.circles).map(([k, n]) => [k.replace('|', ' / '), n])} />
        <Counts title="Circles (source name → code)" items={Object.entries(r.circle_names)} />
      </div>
      {r.new_final_buckets && Object.keys(r.new_final_buckets).length > 0 && (
        <p className="rounded-lg border border-sky-200 bg-sky-50 px-3 py-2 text-xs">
          Final Bucket labels not found in any stored record, kept exactly as written (none is read as “Other Media” or any other category):{' '}
          {Object.entries(r.new_final_buckets).map(([label, count]) => `“${label}” (${formatNumber(count)})`).join(', ')}.
        </p>
      )}
      <ValidationGroups r={r} />
      <div className="space-y-1 text-sm">
        <h3 className="font-semibold">Validation</h3>
        <p className="text-xs text-muted-foreground">
          {formatNumber(r.severity_counts.error)} errors (rows rejected) · {formatNumber(r.severity_counts.warning)} warnings · {formatNumber(r.severity_counts.info)} notes.
          Total Outage Min. of valid rows: {formatNumber(Math.round(r.outage_minutes))} · {formatNumber(r.distinct_rca)} distinct RCA descriptions.
          {r.rca_not_applicable_rows != null && ` Other Media (RCA not applicable): ${formatNumber(r.rca_not_applicable_rows)} · RCA required but information missing: ${formatNumber(r.missing_rca_rows ?? 0)}.`}
        </p>
        <ul className="list-disc space-y-0.5 pl-5 text-xs">
          {Object.entries(r.issue_counts).map(([code, n]) => <li key={code}><span className="font-mono">{code}</span>: {formatNumber(n)}</li>)}
          {Object.entries(r.label_variants).flatMap(([field, groups]) => groups.map((g) => (
            <li key={field + g.join()}>{field === 'om_start_raw' ? 'O&M Start' : field === 'final_bucket' ? 'Final Bucket' : 'Bucket - 2'} spellings grouped for filtering (values kept): {g.map((v) => `“${v}”`).join(', ')}</li>
          )))}
        </ul>
        {r.issues.filter((i) => i.severity !== 'info' || i.row == null).slice(0, 25).map((i, n) => (
          <p key={n} className={`text-xs ${i.severity === 'error' ? 'text-destructive' : i.severity === 'warning' ? 'text-amber-700' : 'text-muted-foreground'}`}>
            {i.row ? `Row ${i.row}${i.site_id ? ` (${i.site_id})` : ''}: ` : ''}{i.message}
          </p>
        ))}
      </div>
      {needsRejectedConfirmation && (
        <label className="flex items-start gap-2 rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-sm">
          <input type="checkbox" className="mt-1" checked={acceptRejected} onChange={(e) => setAcceptRejected(e.target.checked)} />
          <span>Import the {formatNumber(r.valid_rows)} valid rows without the {formatNumber(r.rejected_rows)} rejected rows. The rejected rows stay out of the database until a corrected workbook is uploaded.</span>
        </label>
      )}
      {!rejected && r.conflict_rows > 0 && (
        <div className="space-y-2 rounded-lg border border-amber-300 bg-amber-50 px-3 py-2 text-sm">
          <p><span className="font-semibold">{formatNumber(r.conflict_rows)} rows differ</span> from RCA records already stored for the same date, project and site. Choose what to do:</p>
          <Segmented label="Conflicting rows" value={conflicts} onChange={setConflicts} options={[['skip', 'Keep stored records (skip)'], ['overwrite', 'Update with this workbook']]} />
          <ul className="space-y-0.5 text-xs">
            {r.conflicts.slice(0, 8).map((c) => (
              <li key={c.row}>Row {c.row} ({c.site_id}): {Object.entries(c.differences).map(([f, d]) => `${f} “${show(d.database)}” → “${show(d.file)}”`).join('; ')}</li>
            ))}
          </ul>
        </div>
      )}
      {!rejected && missingRows > 0 && (
        <div className="space-y-2 rounded-lg border border-amber-300 bg-amber-50 px-3 py-2 text-sm">
          <p><span className="font-semibold">{formatNumber(missingRows)} stored records</span> of this period and project scope are not in this workbook. Choose what to do:</p>
          <Segmented label="Records not in this workbook" value={missing} onChange={setMissing}
            options={[['keep', 'Keep them'], ['withdraw', 'Withdraw them (the workbook replaces them)']]} />
          <p className="text-xs text-muted-foreground">Withdrawn records stay in the database with their history but leave the register, the summary and the reports.</p>
          <ul className="space-y-0.5 text-xs">
            {(r.missing ?? []).slice(0, 8).map((m) => <li key={m.record_id}>{m.site_id} ({m.project} / {m.circle}), {m.final_bucket || 'no Final Bucket'}, from {m.source_file || 'the portal'}</li>)}
          </ul>
        </div>
      )}
      {!rejected && (
        <div className="flex gap-2">
          <Button type="button" disabled={busy || (needsRejectedConfirmation && !acceptRejected)}
            onClick={() => onCommit({ conflict_action: r.conflict_rows ? conflicts : '', missing_action: missingRows ? missing : '', accept_rejected: acceptRejected })}>
            {busy ? 'Importing…' : `Confirm import of ${formatNumber(r.valid_rows)} valid rows`}
          </Button>
          <Button type="button" variant="ghost" onClick={onDiscard} disabled={busy}>Discard</Button>
        </div>
      )}
    </Card>
  );
}

const rowsText = (rows: number[], total: number) => `row${rows.length === 1 ? '' : 's'} ${rows.join(', ')}${total > rows.length ? ', …' : ''}`;

/** The validation priorities: duplicates and Final Bucket reject rows; Sub Bucket and RCA description never block. */
function ValidationGroups({ r }: { r: NonNullable<RcaImportBatch['report']> }) {
  const dup = r.duplicates;
  const finals = r.final_bucket_problems ?? [];
  const subs = r.sub_bucket_warnings;
  return (
    <div className="space-y-2 text-xs" aria-label="Validation priorities">
      {dup && dup.rows > 0 && (
        <div className="rounded-lg border border-red-200 bg-red-50 px-3 py-2">
          <p><span className="font-semibold">{formatNumber(dup.rows)} duplicate rows rejected</span> ({formatNumber(dup.groups)} duplicate groups, {formatNumber(dup.sites)} sites;
            {' '}{formatNumber(dup.identical_rows)} identical, {formatNumber(dup.differing_rows)} with another RCA description, outage or other column).
            A duplicate has the same Site ID, date, Final Bucket and Sub Bucket as an earlier row; the first row is kept. The full list is in the validation report.</p>
          <ul className="mt-1 space-y-0.5">
            {dup.examples.slice(0, 8).map((g) => <li key={`${g.project}|${g.site_id}|${g.reporting_date}|${g.final_bucket}|${g.sub_bucket}`}>{g.site_id} ({g.project}), {formatDate(g.reporting_date)}, {g.final_bucket} / {g.sub_bucket || 'blank'}: kept row {g.first_row}, rejected {rowsText(g.rejected_rows.slice(0, 5), g.rejected_rows.length)}</li>)}
          </ul>
        </div>
      )}
      {finals.length > 0 && (
        <div className="rounded-lg border border-red-200 bg-red-50 px-3 py-2">
          <p className="font-semibold">{formatNumber(r.final_bucket_error_rows ?? 0)} rows with a missing or unapproved Final Bucket: the workbook cannot be imported until they are corrected.</p>
          <ul className="mt-1 space-y-0.5">
            {finals.map((p) => <li key={p.code + p.value}>“{p.value || 'blank'}”: {formatNumber(p.rows)} rows ({rowsText(p.example_rows, p.rows)})</li>)}
          </ul>
        </div>
      )}
      {subs && subs.rows > 0 && (
        <div className="rounded-lg border border-amber-200 bg-amber-50 px-3 py-2">
          <p><span className="font-semibold">{formatNumber(subs.rows)} Sub Bucket warnings</span> ({formatNumber(subs.not_approved_rows)} not an approved sub-bucket of their Final Bucket, {formatNumber(subs.missing_rows)} blank). Kept as written; they do not block the import.</p>
          <ul className="mt-1 space-y-0.5">
            {subs.values.slice(0, 8).map((p) => <li key={p.final_bucket + p.code + p.value}>{p.final_bucket} / “{p.value || 'blank'}”: {formatNumber(p.rows)} rows ({rowsText(p.example_rows, p.rows)})</li>)}
          </ul>
        </div>
      )}
      {(r.sites_with_several_records ?? 0) > 0 && (
        <p className="text-muted-foreground">{formatNumber(r.sites_with_several_records!)} sites have more than one RCA record on a date, each with another Final Bucket or Sub Bucket.</p>
      )}
      {(r.rca_description_warnings ?? 0) > 0 && (
        <p className="text-muted-foreground">{formatNumber(r.rca_description_warnings!)} rows have a blank or placeholder RCA description: kept as written; they do not block the import.</p>
      )}
    </div>
  );
}

function show(value: unknown) {
  return value == null || value === '' ? 'blank' : String(value);
}

function Counts({ title, items }: { title: string; items: [string, number][] }) {
  return (
    <div>
      <h3 className="mb-1 text-xs font-semibold text-muted-foreground uppercase">{title}</h3>
      <ul className="space-y-0.5">
        {items.map(([k, n]) => <li key={k} className="flex justify-between gap-3"><span>{k}</span><span className="tabular-nums">{formatNumber(n)}</span></li>)}
      </ul>
    </div>
  );
}
