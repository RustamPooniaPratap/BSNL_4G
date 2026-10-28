import { useState, type ReactNode } from 'react';
import { Lock } from 'lucide-react';
import { Alert, AlertDescription } from '@/components/ui/alert';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Sheet, SheetContent, SheetDescription, SheetHeader, SheetTitle } from '@/components/ui/sheet';
import { Skeleton } from '@/components/ui/skeleton';
import { useAuth } from '../../context/auth';
import { useApiQuery } from '../../hooks/useApiQuery';
import { formatDate } from '../../lib/format';
import { addRcaComment, fetchRcaRecord, updateRcaWorkflow } from '../../services/api';
import type { RcaRecordDetail, RcaWorkflowInput } from '../../types/rca';
import { Field, SelectField } from '../data/DataEntry';
import { NOT_RECORDED, formatMin } from '../../lib/rca';
import { SourceValue, StatusBadge } from './RcaShared';

const STATUSES: [string, string][] = [
  ['investigation', 'Investigation'], ['rca_review', 'RCA Review'], ['action_pending', 'Action Pending'],
  ['action_completed', 'Action Completed'], ['closed', 'Verified / Closed'],
];
const REVIEWS: [string, string][] = [['pending', 'Pending review'], ['confirmed', 'Root cause confirmed'], ['needs_revision', 'Needs revision']];
const VERIFICATIONS: [string, string][] = [['effective', 'Effective'], ['not_effective', 'Not effective'], ['not_verifiable', 'Could not be verified']];
const NONE = 'none';
const textareaClass = 'min-h-20 w-full rounded-md border bg-transparent px-3 py-2 text-sm shadow-xs focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none';

/** One RCA record: source facts (read-only), the reviewed category, follow-up, comments and history. */
export function RcaRecordSheet({ recordId, onClose, onChanged }: { recordId: number | null; onClose: () => void; onChanged?: () => void }) {
  const loaded = useApiQuery(recordId == null ? null : `rca-record-${recordId}`, (signal) => fetchRcaRecord(recordId!, signal));
  // After a save the server returns the updated record; it replaces the loaded one for this record.
  const [saved, setSaved] = useState<RcaRecordDetail | null>(null);
  const record = saved?.id === recordId ? saved : loaded.data?.id === recordId ? loaded.data : null;
  const error = loaded.error?.message ?? null;
  // Kept here: a save re-keys the follow-up form (fresh values), which would drop a message held inside it.
  const [notice, setNotice] = useState<string | null>(null);
  const updated = (next: RcaRecordDetail, message?: string) => { setSaved(next); setNotice(message ?? null); onChanged?.(); };

  return (
    <Sheet open={recordId != null} onOpenChange={(open) => { if (!open) onClose(); }}>
      <SheetContent className="w-full overflow-y-auto sm:max-w-xl">
        <SheetHeader>
          <SheetTitle className="font-mono">{record?.site_id ?? 'RCA record'}</SheetTitle>
          <SheetDescription>
            {record ? `${record.site_name || 'Site'} · ${record.project} · ${record.circle} · ${formatDate(record.reporting_date)}` : 'Loading the record…'}
          </SheetDescription>
        </SheetHeader>
        <div className="space-y-5 px-4 pb-6">
          {error && <Alert variant="destructive"><AlertDescription>{error}</AlertDescription></Alert>}
          {!record && !error && <Skeleton className="h-64 w-full" />}
          {record && (
            <>
              <Section title="Source RCA (as in the workbook)" icon={<Lock className="size-3.5" aria-hidden="true" />}>
                <dl className="grid grid-cols-[9rem_1fr] gap-x-3 gap-y-1.5 text-sm">
                  <Row label="Reporting date">{formatDate(record.reporting_date)}</Row>
                  <Row label="Project">{record.project}{record.project_raw !== record.project && <span className="text-muted-foreground"> (source: “{record.project_raw}”)</span>}</Row>
                  <Row label="Circle">{record.circle} <span className="text-muted-foreground">({record.circle_raw})</span></Row>
                  <Row label="Site">{record.site_id} · {record.site_name || '—'}</Row>
                  <Row label="OA / BA">{record.oa || '—'} / {record.ba || '—'}</Row>
                  <Row label="O&M Start">{record.om_start_raw || '—'}</Row>
                  <Row label="Outage">{formatMin(record.outage_minutes)}</Row>
                  <Row label="Final Bucket"><SourceValue value={record.final_bucket} unclassified={record.final_bucket_unclassified} /></Row>
                  <Row label="Bucket - 2"><SourceValue value={record.bucket_2} unclassified={record.bucket_2_unclassified} notApplicable={!record.rca_applicable} /></Row>
                  <Row label="RCA"><span className="whitespace-pre-wrap"><SourceValue value={record.rca_text} unclassified={record.rca_unclassified} /></span></Row>
                  <Row label="RCA applicability">
                    {record.rca_applicable ? 'RCA required'
                      : <span className="text-muted-foreground">Other Media — RCA not applicable (by Final Bucket)</span>}
                  </Row>
                  <Row label="Cause category">
                    {record.category ? <span className="font-medium">{record.category.name} <span className="text-xs font-normal text-emerald-700">(reviewed)</span></span>
                      : <span className="text-muted-foreground italic">Unreviewed: no approved mapping for this description yet</span>}
                  </Row>
                  <Row label="Traceability">
                    <span className="text-xs text-muted-foreground">
                      {record.source === 'import' ? `${record.source_file ?? 'Import'}, Excel row ${record.source_row ?? '—'} (import #${record.batch ?? '—'})`
                        : `Recorded in the portal by ${record.created_by ?? 'unknown'} on ${formatDate(record.created_at.slice(0, 10))}`}
                    </span>
                  </Row>
                </dl>
                {record.source === 'import' && <p className="mt-2 text-xs text-muted-foreground">Imported facts are read-only; re-import a corrected workbook to change them.</p>}
              </Section>

              {record.other_records.length > 0 && (
                <Section title={`Other RCA records for this site (${record.other_records.length})`}>
                  <ul className="space-y-1 text-sm">
                    {record.other_records.map((o) => <li key={o.id}>{formatDate(o.reporting_date)} · {formatMin(o.outage_minutes)} · <span className="text-muted-foreground">{o.rca_text}</span></li>)}
                  </ul>
                </Section>
              )}

              <WorkflowForm key={`${record.id}-${record.workflow?.updated_at ?? 'none'}`} record={record} notice={notice} onSaved={updated} />
              <Comments record={record} onSaved={updated} />

              {record.history.length > 0 && (
                <Section title="History">
                  <ul className="space-y-1 text-xs text-muted-foreground">
                    {record.history.map((h, i) => (
                      <li key={i}>{new Date(h.at).toLocaleString('en-IN')} · {h.user ?? 'system'} · {h.action.replace(/_/g, ' ')}
                        {Object.keys(h.changes).length > 0 && `: ${Object.keys(h.changes).filter((k) => k !== 'batch').join(', ')}`}</li>
                    ))}
                  </ul>
                </Section>
              )}
            </>
          )}
        </div>
      </SheetContent>
    </Sheet>
  );
}

function Section({ title, icon, children }: { title: string; icon?: ReactNode; children: ReactNode }) {
  return (
    <section className="space-y-2" aria-label={title}>
      <h3 className="flex items-center gap-1.5 text-sm font-semibold">{icon}{title}</h3>
      {children}
    </section>
  );
}

function Row({ label, children }: { label: string; children: ReactNode }) {
  return (<><dt className="text-muted-foreground">{label}</dt><dd className="min-w-0 break-words">{children}</dd></>);
}

function WorkflowForm({ record, notice, onSaved }: { record: RcaRecordDetail; notice: string | null; onSaved: (r: RcaRecordDetail, message?: string) => void }) {
  const isAdmin = useAuth().user?.role === 'admin';
  const w = record.workflow;
  const initial = (): Required<RcaWorkflowInput> => ({
    status: w?.status ?? '', review_status: w?.review_status ?? '', corrective_action: w?.corrective_action ?? '', owner: w?.owner ?? '',
    target_date: w?.target_date ?? '', completed_date: w?.completed_date ?? '', verification: w?.verification ?? '',
  });
  const [form, setForm] = useState(initial);
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [message, setMessage] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const set = <K extends keyof RcaWorkflowInput>(key: K, value: string) => setForm((f) => ({ ...f, [key]: value }));
  const statuses = STATUSES.filter(([v]) => isAdmin || v !== 'closed' || form.status === 'closed');

  async function save() {
    setSaving(true);
    setErrors({});
    setMessage(null);
    try {
      onSaved(await updateRcaWorkflow(record.id, form), 'Follow-up saved.');
    } catch (e) {
      const details = (e as { details?: Record<string, unknown> }).details ?? {};
      setErrors(Object.fromEntries(Object.entries(details).map(([k, v]) => [k, Array.isArray(v) ? String(v[0]) : String(v)])));
      setMessage(e instanceof Error ? e.message : String(e));
    } finally {
      setSaving(false);
    }
  }

  return (
    <Section title="Follow-up and corrective action">
      <div className="flex items-center gap-2 text-xs text-muted-foreground">
        Current status: <StatusBadge status={w?.status ?? null} label={w?.status_label ?? null} />
        {w?.updated_by && <span>· last updated by {w.updated_by} on {new Date(w.updated_at).toLocaleString('en-IN')}</span>}
      </div>
      {!w && <p className="text-xs text-muted-foreground">Nothing has been recorded yet. The workbook has no status, owner or corrective action, so none is assumed.</p>}
      <div className="grid gap-3 sm:grid-cols-2">
        <Field id="wf-status" label="Status" plain error={errors.status}>
          <SelectField id="wf-status" value={form.status || NONE} placeholder={NOT_RECORDED} onChange={(v) => set('status', v === NONE ? '' : v)}
            options={[{ value: NONE, label: NOT_RECORDED }, ...statuses.map(([value, label]) => ({ value, label }))]} />
        </Field>
        <Field id="wf-owner" label="Assigned owner / team" plain error={errors.owner}>
          <Input id="wf-owner" value={form.owner} onChange={(e) => set('owner', e.target.value)} placeholder={NOT_RECORDED} />
        </Field>
        <Field id="wf-action" label="Corrective action" plain error={errors.corrective_action} className="sm:col-span-2">
          <textarea id="wf-action" className={textareaClass} value={form.corrective_action} onChange={(e) => set('corrective_action', e.target.value)} placeholder={NOT_RECORDED} />
        </Field>
        <Field id="wf-target" label="Target completion date" plain error={errors.target_date}>
          <Input id="wf-target" type="date" value={form.target_date} onChange={(e) => set('target_date', e.target.value)} />
        </Field>
        <Field id="wf-done" label="Actual completion date" plain error={errors.completed_date}>
          <Input id="wf-done" type="date" value={form.completed_date} onChange={(e) => set('completed_date', e.target.value)} />
        </Field>
        <Field id="wf-review" label="Root-cause review" plain error={errors.review_status} hint={isAdmin ? undefined : 'Recorded by an Admin'}>
          <SelectField id="wf-review" value={form.review_status || NONE} placeholder={NOT_RECORDED} disabled={!isAdmin}
            onChange={(v) => set('review_status', v === NONE ? '' : v)}
            options={[{ value: NONE, label: NOT_RECORDED }, ...REVIEWS.map(([value, label]) => ({ value, label }))]} />
        </Field>
        <Field id="wf-verify" label="Verification outcome" plain error={errors.verification} hint={isAdmin ? undefined : 'Recorded by an Admin'}>
          <SelectField id="wf-verify" value={form.verification || NONE} placeholder={NOT_RECORDED} disabled={!isAdmin}
            onChange={(v) => set('verification', v === NONE ? '' : v)}
            options={[{ value: NONE, label: NOT_RECORDED }, ...VERIFICATIONS.map(([value, label]) => ({ value, label }))]} />
        </Field>
      </div>
      {w?.reviewer && <p className="text-xs text-muted-foreground">Reviewed by {w.reviewer}{w.reviewed_at ? ` on ${new Date(w.reviewed_at).toLocaleString('en-IN')}` : ''}.</p>}
      <div className="flex items-center gap-3">
        <Button type="button" size="sm" onClick={save} disabled={saving}>{saving ? 'Saving…' : 'Save follow-up'}</Button>
        {(message ?? notice) && <span className={message ? 'text-xs text-destructive' : 'text-xs text-emerald-700'} role="status">{message ?? notice}</span>}
      </div>
      <p className="text-xs text-muted-foreground">Workflow: Investigation → RCA Review → Action Pending → Action Completed → Verified / Closed. Closing needs a verification outcome (Admin).</p>
    </Section>
  );
}

function Comments({ record, onSaved }: { record: RcaRecordDetail; onSaved: (r: RcaRecordDetail) => void }) {
  const [text, setText] = useState('');
  const [evidence, setEvidence] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  async function add() {
    setSaving(true);
    setError(null);
    try {
      onSaved(await addRcaComment(record.id, text, evidence));
      setText('');
      setEvidence('');
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setSaving(false);
    }
  }
  return (
    <Section title={`Comments and evidence (${record.comments.length})`}>
      {record.comments.length === 0 && <p className="text-xs text-muted-foreground">No comments yet.</p>}
      <ul className="space-y-2">
        {record.comments.map((c) => (
          <li key={c.id} className="rounded-md border px-3 py-2 text-sm">
            <p className="whitespace-pre-wrap">{c.text}</p>
            <p className="mt-1 text-xs text-muted-foreground">{c.author ?? 'unknown'} · {new Date(c.created_at).toLocaleString('en-IN')}{c.evidence && ` · Evidence: ${c.evidence}`}</p>
          </li>
        ))}
      </ul>
      <div className="space-y-2">
        <textarea aria-label="New comment" className={textareaClass} value={text} onChange={(e) => setText(e.target.value)} placeholder="Add a comment" />
        <div className="flex flex-wrap items-center gap-2">
          <Input aria-label="Evidence reference" value={evidence} onChange={(e) => setEvidence(e.target.value)} placeholder="Evidence reference (document no., link, docket)" className="max-w-sm" />
          <Button type="button" size="sm" variant="outline" onClick={add} disabled={saving || !text.trim()}>Add comment</Button>
        </div>
        {error && <p className="text-xs text-destructive" role="alert">{error}</p>}
      </div>
    </Section>
  );
}
