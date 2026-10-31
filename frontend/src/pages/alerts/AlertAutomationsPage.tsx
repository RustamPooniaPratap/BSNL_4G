import { useState } from 'react';
import { Link } from 'react-router-dom';
import { CalendarClock, Loader2, Pause, Pencil, Play, Plus, Trash2, Upload, Zap } from 'lucide-react';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card } from '@/components/ui/card';
import { Input } from '@/components/ui/input';
import { Sheet, SheetContent, SheetDescription, SheetHeader, SheetTitle } from '@/components/ui/sheet';
import { Skeleton } from '@/components/ui/skeleton';
import { cn } from '@/lib/utils';
import { Field, SelectField } from '../../components/data/DataEntry';
import { PageHeading } from '../../context/pageHeader';
import { useApiQuery } from '../../hooks/useApiQuery';
import { activeCirclesOf, useOrganization } from '../../hooks/useOrganization';
import { formatDateTime } from '../../lib/format';
import {
  deleteAlertAutomation, enableAlertAutomation, fetchAlertAutomations, fetchAlertOptions, previewAlertAutomation, runAlertAutomation, saveAlertAutomation, uploadAlertFile,
} from '../../services/api';
import type { AlertAutomation, AlertAutomationInput, AlertKind, AlertOptions, AlertPreview } from '../../types/alerts';
import { WorkerStatus } from './AlertParts';

const WEEKDAYS = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday'];
const STEPS = ['Schedule', 'Scope', 'Recipients', 'Attachments', 'Message', 'Review'] as const;
const DAYS = [{ value: 'yesterday', label: 'Previous day' }, { value: 'today', label: 'Today' }, { value: 'latest', label: 'Latest date with data' }];
const errorsOf = (e: unknown) => Object.fromEntries(Object.entries((e as { details?: Record<string, unknown> }).details ?? {})
  .map(([k, v]) => [k, Array.isArray(v) ? String(v[0]) : String(v)]));
const list = (text: string) => text.split(/[\s,;]+/).map((s) => s.trim()).filter(Boolean);

function schedule(a: Pick<AlertAutomation, 'frequency' | 'run_time' | 'weekday' | 'month_day' | 'start_date'>) {
  switch (a.frequency) {
    case 'event': return 'When an upload fails';
    case 'once': return `Once, ${a.start_date ?? ''} ${a.run_time}`;
    case 'weekly': return `Every ${WEEKDAYS[a.weekday]} at ${a.run_time}`;
    case 'monthly': return `Monthly on day ${a.month_day} at ${a.run_time}`;
    default: return `Daily at ${a.run_time}`;
  }
}

/** Alert › Automations: the five templates, the configured automations and their actions (all checked by the server). */
export function AlertAutomationsPage() {
  const [version, setVersion] = useState(0);
  const options = useApiQuery('alert-options', fetchAlertOptions);
  const autos = useApiQuery(`alert-automations-${version}`, fetchAlertAutomations);
  const [editing, setEditing] = useState<AlertAutomation | AlertAutomationInput | null>(null);
  const [notice, setNotice] = useState<{ ok: boolean; text: string } | null>(null);
  const reload = () => setVersion((v) => v + 1);
  const act = async (action: () => Promise<unknown>, done: string) => {
    setNotice(null);
    try {
      await action();
      setNotice({ ok: true, text: done });
      reload();
    } catch (e) {
      setNotice({ ok: false, text: Object.values(errorsOf(e))[0] ?? (e as Error).message });
    }
  };
  const o = options.data;
  const fresh = (kind: AlertKind): AlertAutomationInput => {
    const k = o!.kinds.find((x) => x.value === kind)!;
    const t = o!.templates.find((x) => x.value === k.template)!;
    return { name: k.label, kind, frequency: k.frequency, run_time: '09:00', timezone: o!.timezone, weekday: 0, month_day: 1, start_date: null, end_date: null,
      project: '', circles: [], report_day: k.report_day as AlertAutomationInput['report_day'], to_users: [], to_emails: [], cc: [], bcc: [],
      include_responsible: kind !== 'uptime_report' && kind !== 'custom', attachments: [], extra_file: null, distribution: 'same',
      template: t.value, subject: t.subject, message: kind === 'csv_reminder' || kind === 'rca_reminder' || kind === 'upload_failure' ? '{{notification_message}}' : t.message };
  };
  return (
    <div className="space-y-4">
      <PageHeading title="Automations" subtitle="Choose a template, set when it runs, who receives it and which reports are attached, preview the email, then enable it." />
      {o && <WorkerStatus worker={o.worker} />}
      {o && !o.account_active && (
        <p className="rounded-md border border-amber-200 bg-amber-50 px-3 py-2 text-sm text-amber-900" role="status">
          No active email account: automations can be prepared but not enabled. <Link to="/admin/alerts/email" className="font-medium underline">Open Email Setup</Link>.
        </p>
      )}
      {notice && <p role={notice.ok ? 'status' : 'alert'} className={cn('rounded-md border px-3 py-2 text-sm', notice.ok ? 'border-emerald-200 bg-emerald-50 text-emerald-900' : 'border-destructive/30 bg-destructive/5 text-destructive')}>{notice.text}</p>}
      <section aria-label="Templates" className="space-y-2">
        <h2 className="text-xs font-semibold tracking-[0.14em] text-muted-foreground uppercase">New automation</h2>
        <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-5">
          {o?.kinds.map((k) => (
            <Card key={k.value} className="gap-2 rounded-xl px-4 py-3 shadow-xs">
              <p className="text-sm font-semibold">{k.label}</p>
              <p className="flex-1 text-xs text-muted-foreground">{k.description}</p>
              <Button size="sm" variant="outline" className="self-start" onClick={() => setEditing(fresh(k.value))}><Plus /> Configure</Button>
            </Card>
          )) ?? <Skeleton className="h-28 xl:col-span-5" />}
        </div>
      </section>
      <section aria-label="Configured automations" className="space-y-2">
        <h2 className="text-xs font-semibold tracking-[0.14em] text-muted-foreground uppercase">Configured automations</h2>
        {autos.error && <p className="text-sm text-destructive">{autos.error.message}</p>}
        {autos.data && !autos.data.automations.length && <p className="text-sm text-muted-foreground">No automation yet: configure one of the templates above.</p>}
        <div className="grid gap-3 lg:grid-cols-2">
          {autos.data?.automations.map((a) => (
            <Card key={a.id} role="group" aria-label={`Automation ${a.name}`} className="gap-2 rounded-xl px-4 py-3 shadow-xs">
              <div className="flex items-start justify-between gap-2">
                <div>
                  <p className="text-sm font-semibold">{a.name}</p>
                  <p className="text-xs text-muted-foreground">{a.kind_label} · {schedule(a)}{a.frequency !== 'event' ? ` (${a.timezone})` : ''}</p>
                </div>
                {a.enabled ? <Badge variant="outline" className="border-emerald-300 text-emerald-800">Enabled</Badge> : <Badge variant="outline">Paused</Badge>}
              </div>
              <p className="text-xs text-muted-foreground">
                <CalendarClock className="mr-1 inline size-3.5" aria-hidden="true" />
                {a.enabled && a.next_run_at ? `Next run ${formatDateTime(a.next_run_at)}` : a.frequency === 'event' ? (a.enabled ? 'Waiting for upload failures' : 'Not listening') : 'Not scheduled'}
                {a.last_run_at ? ` · last run ${formatDateTime(a.last_run_at)}` : ''}
                {' · '}{a.attachments.length + (a.extra_file ? 1 : 0)} attachment(s)
              </p>
              <div className="flex flex-wrap gap-1.5">
                <Button size="sm" variant="outline" onClick={() => setEditing(a)}><Pencil /> Edit</Button>
                <Button size="sm" variant="outline" onClick={() => act(() => enableAlertAutomation(a.id, !a.enabled), a.enabled ? `${a.name} paused.` : `${a.name} enabled.`)}>
                  {a.enabled ? <><Pause /> Pause</> : <><Play /> Enable</>}
                </Button>
                {a.kind !== 'upload_failure' && (
                  <Button size="sm" variant="outline" onClick={() => act(() => runAlertAutomation(a.id), `${a.name} queued: the worker sends it within a minute. See Email History.`)}><Zap /> Run Now</Button>
                )}
                <Button size="sm" variant="ghost" className="text-destructive" aria-label={`Delete ${a.name}`}
                  onClick={() => { if (globalThis.confirm?.(`Delete ${a.name}? Its email history is kept.`) !== false) void act(() => deleteAlertAutomation(a.id), `${a.name} deleted.`); }}>
                  <Trash2 />
                </Button>
              </div>
            </Card>
          ))}
        </div>
      </section>
      {editing && o && (
        <AutomationSheet options={o} value={editing} onClose={() => setEditing(null)}
          onSaved={(text) => { setEditing(null); setNotice({ ok: true, text }); reload(); }} />
      )}
    </div>
  );
}

function AutomationSheet({ options, value, onClose, onSaved }: { options: AlertOptions; value: AlertAutomation | AlertAutomationInput; onClose: () => void; onSaved: (text: string) => void }) {
  const id = 'id' in value ? value.id : null;
  const [f, setF] = useState<AlertAutomationInput>(value);
  const [step, setStep] = useState(0);
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [busy, setBusy] = useState(false);
  const [preview, setPreview] = useState<AlertPreview | null>(null);
  const [fileName, setFileName] = useState<string | null>('extra_file_name' in value ? value.extra_file_name : null);
  const catalog = useOrganization();
  const set = <K extends keyof AlertAutomationInput>(k: K, v: AlertAutomationInput[K]) => { setF((x) => ({ ...x, [k]: v })); setPreview(null); };
  const event = f.kind === 'upload_failure';
  const reminder = f.kind === 'csv_reminder' || f.kind === 'rca_reminder';
  const circles = f.project ? activeCirclesOf(catalog.data, f.project) : [...new Set((catalog.data?.associations ?? []).filter((a) => a.is_active).map((a) => a.circle))].sort();
  const goPreview = async (next: number) => {
    setStep(next);
    if (next !== STEPS.length - 1) return;
    setBusy(true);
    try {
      setPreview(await previewAlertAutomation(f));
      setErrors({});
    } catch (e) {
      setErrors(errorsOf(e));
    } finally {
      setBusy(false);
    }
  };
  const save = async (enable: boolean) => {
    setBusy(true);
    setErrors({});
    try {
      const saved = (await saveAlertAutomation(id, f)).automation;
      if (enable && !saved.enabled) await enableAlertAutomation(saved.id, true);
      onSaved(enable ? `${f.name} saved and enabled.` : `${f.name} saved.`);
    } catch (e) {
      setErrors(errorsOf(e));
    } finally {
      setBusy(false);
    }
  };
  const check = (label: string, checked: boolean, onChange: (v: boolean) => void) => (
    <label className="flex items-center gap-2 text-sm"><input type="checkbox" checked={checked} onChange={(e) => onChange(e.target.checked)} />{label}</label>
  );
  const emails = (k: 'to_emails' | 'cc' | 'bcc', label: string) => (
    <Field id={`al-${k}`} label={label} error={errors[k]} hint="Separate addresses with commas or spaces.">
      <Input id={`al-${k}`} defaultValue={f[k].join(', ')} onBlur={(e) => set(k, [...new Set(list(e.target.value).map((s) => s.toLowerCase()))])} />
    </Field>
  );
  return (
    <Sheet open onOpenChange={(open) => { if (!open) onClose(); }}>
      <SheetContent className="w-full overflow-y-auto sm:max-w-2xl">
        <SheetHeader>
          <SheetTitle>{id ? 'Edit' : 'Configure'}: {options.kinds.find((k) => k.value === f.kind)?.label}</SheetTitle>
          <SheetDescription>{options.kinds.find((k) => k.value === f.kind)?.description}</SheetDescription>
        </SheetHeader>
        <div className="space-y-4 px-4 pb-6">
          <ol className="flex flex-wrap gap-1" aria-label="Steps">
            {STEPS.map((s, i) => (
              <li key={s}><button type="button" aria-current={i === step ? 'step' : undefined} onClick={() => { void goPreview(i); }}
                className={cn('rounded-md px-2.5 py-1 text-xs font-medium', i === step ? 'bg-primary text-primary-foreground' : 'text-muted-foreground hover:bg-muted')}>{i + 1}. {s}</button></li>
            ))}
          </ol>
          {Object.keys(errors).length > 0 && <p role="alert" className="rounded-md border border-destructive/30 bg-destructive/5 px-3 py-2 text-sm text-destructive">{Object.entries(errors).map(([k, v]) => `${k.replace('_', ' ')}: ${v}`).join(' · ')}</p>}

          {step === 0 && (
            <div className="grid gap-3 sm:grid-cols-2">
              <Field id="al-name" label="Name" required><Input id="al-name" value={f.name} onChange={(e) => set('name', e.target.value)} /></Field>
              {event ? <p className="text-sm text-muted-foreground sm:col-span-2">Runs when a raw CSV or RCA upload fails or is rejected; no schedule is needed.</p> : (
                <>
                  <Field id="al-frequency" label="Frequency" required>
                    <SelectField id="al-frequency" value={f.frequency} placeholder="Frequency" onChange={(v) => set('frequency', v as AlertAutomationInput['frequency'])}
                      options={[['once', 'One time'], ['daily', 'Daily'], ['weekly', 'Weekly'], ['monthly', 'Monthly']].map(([value, label]) => ({ value, label }))} />
                  </Field>
                  <Field id="al-time" label="Time" required><Input id="al-time" type="time" value={f.run_time} onChange={(e) => set('run_time', e.target.value)} /></Field>
                  <Field id="al-tz" label="Timezone" required><Input id="al-tz" value={f.timezone} onChange={(e) => set('timezone', e.target.value)} /></Field>
                  {f.frequency === 'weekly' && (
                    <Field id="al-weekday" label="Day of the week" required>
                      <SelectField id="al-weekday" value={String(f.weekday)} placeholder="Day" onChange={(v) => set('weekday', Number(v))} options={WEEKDAYS.map((d, i) => ({ value: String(i), label: d }))} />
                    </Field>
                  )}
                  {f.frequency === 'monthly' && (
                    <Field id="al-mday" label="Day of the month (1–28)" required>
                      <Input id="al-mday" type="number" min={1} max={28} value={f.month_day} onChange={(e) => set('month_day', Number(e.target.value))} />
                    </Field>
                  )}
                  <Field id="al-start" label={f.frequency === 'once' ? 'Date' : 'Start date'} required={f.frequency === 'once'}>
                    <Input id="al-start" type="date" value={f.start_date ?? ''} onChange={(e) => set('start_date', e.target.value || null)} />
                  </Field>
                  {f.frequency !== 'once' && (
                    <Field id="al-end" label="End date"><Input id="al-end" type="date" value={f.end_date ?? ''} onChange={(e) => set('end_date', e.target.value || null)} /></Field>
                  )}
                </>
              )}
            </div>
          )}

          {step === 1 && (
            <div className="grid gap-3 sm:grid-cols-2">
              <Field id="al-project" label="Project">
                <SelectField id="al-project" value={f.project || '__all'} placeholder="All projects" onChange={(v) => { set('project', v === '__all' ? '' : v); set('circles', []); }}
                  options={[{ value: '__all', label: 'All projects' }, ...(catalog.data?.projects ?? []).filter((p) => p.is_active).map((p) => ({ value: p.key, label: p.name }))]} />
              </Field>
              <Field id="al-day" label={reminder ? 'Reporting date checked' : 'Reporting date of the reports'}>
                <SelectField id="al-day" value={f.report_day} placeholder="Reporting date" onChange={(v) => set('report_day', v as AlertAutomationInput['report_day'])} options={DAYS} />
              </Field>
              <fieldset className="sm:col-span-2">
                <legend className="mb-1 text-xs font-medium">Circles <span className="font-normal text-muted-foreground">(none selected: all circles)</span></legend>
                <div className="flex flex-wrap gap-x-4 gap-y-1">
                  {circles.map((c) => check(c, f.circles.includes(c), (on) => set('circles', on ? [...f.circles, c].sort() : f.circles.filter((x) => x !== c))))}
                </div>
              </fieldset>
            </div>
          )}

          {step === 2 && (
            <div className="space-y-3">
              {(reminder || event) && check(reminder ? 'Also send to the users granted each pending circle (Organization › User Access)' : 'Also send to the user who uploaded the file',
                f.include_responsible, (v) => set('include_responsible', v))}
              <fieldset>
                <legend className="mb-1 text-xs font-medium">Portal users (To)</legend>
                <div className="grid max-h-48 gap-1 overflow-y-auto rounded-md border p-2 sm:grid-cols-2">
                  {options.users.map((u) => check(`${u.name || u.username} · ${u.role} · ${u.email}`, f.to_users.includes(u.id),
                    (on) => set('to_users', on ? [...f.to_users, u.id] : f.to_users.filter((x) => x !== u.id))))}
                  {!options.users.length && <p className="text-xs text-muted-foreground">No portal user has an email address yet (Users & Roles).</p>}
                </div>
              </fieldset>
              {emails('to_emails', 'Other email addresses (To)')}
              <div className="grid gap-3 sm:grid-cols-2">{emails('cc', 'CC')}{emails('bcc', 'BCC')}</div>
            </div>
          )}

          {step === 3 && (
            <div className="space-y-3">
              {event ? <p className="text-sm text-muted-foreground">Upload failure alerts carry no report.</p> : (
                <>
                  <ul className="space-y-2">
                    {options.reports.map((r) => {
                      const chosen = f.attachments.find((a) => a.report === r.value);
                      return (
                        <li key={r.value} className="rounded-md border px-3 py-2">
                          {check(r.label, !!chosen, (on) => set('attachments', on ? [...f.attachments, { report: r.value, format: r.formats[0] }] : f.attachments.filter((a) => a.report !== r.value)))}
                          <p className="ml-6 text-xs text-muted-foreground">{r.description} Format: {r.formats.join(', ').toUpperCase()}.</p>
                        </li>
                      );
                    })}
                  </ul>
                  <Field id="al-dist" label="Distribution">
                    <SelectField id="al-dist" value={f.distribution} placeholder="Distribution" onChange={(v) => set('distribution', v as AlertAutomationInput['distribution'])}
                      options={[{ value: 'same', label: 'Same report for all recipients' }, { value: 'per_recipient', label: 'Relevant report per recipient (their circles only)' }]} />
                  </Field>
                  <Field id="al-file" label="Additional approved file (Admin)" hint={`${options.file_types.join(', ')} · up to ${Math.round(options.max_file_bytes / 1048576)} MB`}>
                    <div className="flex items-center gap-2">
                      <label className="inline-flex cursor-pointer items-center gap-1.5 rounded-md border px-3 py-1.5 text-sm hover:bg-muted">
                        <Upload className="size-4" /> Choose file
                        <input type="file" className="sr-only" aria-label="Additional file" accept={options.file_types.join(',')} onChange={async (e) => {
                          const file = e.target.files?.[0];
                          if (!file) return;
                          try { const r = await uploadAlertFile(file); set('extra_file', r.id); setFileName(r.name); } catch (err) { setErrors(errorsOf(err)); }
                        }} />
                      </label>
                      {f.extra_file && <span className="text-sm">{fileName} <button type="button" className="text-xs text-destructive underline" onClick={() => { set('extra_file', null); setFileName(null); }}>Remove</button></span>}
                    </div>
                  </Field>
                </>
              )}
            </div>
          )}

          {step === 4 && (
            <div className="space-y-3">
              <Field id="al-template" label="Email template">
                <SelectField id="al-template" value={f.template} placeholder="Template" options={options.templates.map((t) => ({ value: t.value, label: t.label }))}
                  onChange={(v) => { const t = options.templates.find((x) => x.value === v)!; setF((x) => ({ ...x, template: t.value, subject: t.subject })); setPreview(null); }} />
              </Field>
              <Field id="al-subject" label="Subject" error={errors.subject}><Input id="al-subject" value={f.subject} onChange={(e) => set('subject', e.target.value)} /></Field>
              <Field id="al-message" label="Message" error={errors.message}>
                <textarea id="al-message" rows={6} value={f.message} onChange={(e) => set('message', e.target.value)} className="w-full rounded-md border bg-transparent px-3 py-2 text-sm" />
              </Field>
              <p className="text-xs text-muted-foreground">Placeholders: {options.placeholders.map((p) => `{{${p}}}`).join(' ')}</p>
            </div>
          )}

          {step === 5 && (
            <div className="space-y-3">
              {busy && !preview && <Skeleton className="h-64" />}
              {preview && (
                <>
                  <dl className="grid grid-cols-[9rem_1fr] gap-x-3 gap-y-1 text-sm">
                    <dt className="text-muted-foreground">Schedule</dt><dd>{schedule(f)}{preview.next_run_at ? ` · next ${formatDateTime(preview.next_run_at)}` : ''}</dd>
                    <dt className="text-muted-foreground">Scope</dt><dd>{f.project || 'All projects'} · {f.circles.join(', ') || 'All circles'}</dd>
                    <dt className="text-muted-foreground">Recipients</dt>
                    <dd>{[...options.users.filter((u) => f.to_users.includes(u.id)).map((u) => u.email), ...f.to_emails].join(', ') || '—'}
                      {f.cc.length ? ` · CC ${f.cc.join(', ')}` : ''}{f.bcc.length ? ` · BCC ${f.bcc.join(', ')}` : ''}
                      {f.include_responsible && (reminder || event) ? ' · + responsible users' : ''}</dd>
                    <dt className="text-muted-foreground">Attachments</dt><dd>{preview.attachments.map((a) => `${a.name} (${a.format.toUpperCase()})`).join(', ') || 'None'}</dd>
                    <dt className="text-muted-foreground">Subject</dt><dd className="font-medium">{preview.subject}</dd>
                  </dl>
                  <iframe title="Email preview" sandbox="" srcDoc={preview.html} className="h-[28rem] w-full rounded-md border bg-white" />
                </>
              )}
            </div>
          )}

          <div className="flex flex-wrap justify-between gap-2 border-t pt-3">
            <Button type="button" variant="ghost" onClick={onClose}>Cancel</Button>
            <div className="flex gap-2">
              {step > 0 && <Button type="button" variant="outline" onClick={() => { void goPreview(step - 1); }}>Back</Button>}
              {step < STEPS.length - 1 ? <Button type="button" onClick={() => { void goPreview(step + 1); }}>Next</Button> : (
                <>
                  <Button type="button" variant="outline" disabled={busy} onClick={() => { void save(false); }}>{busy && <Loader2 className="animate-spin" />}Save</Button>
                  <Button type="button" disabled={busy || !options.account_active} onClick={() => { void save(true); }}>Save and Enable</Button>
                </>
              )}
            </div>
          </div>
        </div>
      </SheetContent>
    </Sheet>
  );
}
