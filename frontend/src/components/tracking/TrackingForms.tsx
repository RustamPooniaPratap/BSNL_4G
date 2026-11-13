import { useState, type ReactNode } from 'react';
import { CircleCheck, CircleX, Clock, FileText, FlaskConical, Mail, Send, TriangleAlert } from 'lucide-react';
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { cn } from '@/lib/utils';
import { Field, SelectField } from '../data/DataEntry';
import { useApiQuery } from '../../hooks/useApiQuery';
import { fieldA11y } from '../../lib/dataEntry';
import { formatDateTime } from '../../lib/format';
import { ApiError, fetchReminderTemplate, sendPersonalEmail, sendReminder } from '../../services/api';
import type { EmailResult, EmailStatus, ReminderRequest } from '../../types';
import {
  FOLLOW_UP_METHODS, arrivalErrors, emailErrors, splitAddresses, arrivalWarnings, contactErrors, followUpErrors, localDate, localTime, shortType,
  type ArrivalDraft, type ArrivalRecord, type Contact, type EmailDraft, type Deadline, type DeadlineConfig, type FollowUpDraft,
  type FollowUpMethod, type Requirement,
} from '../../lib/tracking';

const textareaClass = 'min-h-16 w-full rounded-md border border-input bg-transparent px-3 py-2 text-sm shadow-xs outline-none focus-visible:border-ring focus-visible:ring-[3px] focus-visible:ring-ring/50';

function FormActions({ submitLabel, onCancel, extra }: { submitLabel: string; onCancel: () => void; extra?: ReactNode }) {
  return (
    <div className="flex flex-wrap items-center gap-2 pt-1">
      <Button type="submit">{submitLabel}</Button>
      <Button type="button" variant="outline" onClick={onCancel}>Cancel</Button>
      {extra}
    </div>
  );
}

export function ArrivalForm({ initial, requirements, arrivals, editingId, fileSuggestions, now, onSave, onCancel }: {
  initial: ArrivalDraft; requirements: Requirement[]; arrivals: Record<string, ArrivalRecord>; editingId?: string;
  fileSuggestions: string[]; now: Date; onSave: (draft: ArrivalDraft) => void; onCancel: () => void;
}) {
  const [draft, setDraft] = useState(initial);
  const [submitted, setSubmitted] = useState(false);
  const set = (changes: Partial<ArrivalDraft>) => setDraft((d) => ({ ...d, ...changes }));
  const errors = arrivalErrors(draft, arrivals, now, editingId);
  const show = (k: keyof ArrivalDraft) => (submitted || k === 'circle' ? errors[k] : undefined);
  const warnings = arrivalWarnings(draft);
  const circles = [...new Set(requirements.filter((r) => !draft.reportType || r.reportType === draft.reportType).map((r) => r.circle))];
  const types = [...new Set(requirements.map((r) => r.reportType))];

  return (
    <form noValidate className="space-y-3" onSubmit={(e) => {
      e.preventDefault();
      setSubmitted(true);
      if (Object.keys(errors).length === 0) onSave({ ...draft, fileName: draft.fileName.trim(), receivedBy: draft.receivedBy.trim() });
    }}>
      <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
        <Field id="arr-type" label="Report type" required error={show('reportType')}>
          <SelectField id="arr-type" value={draft.reportType} placeholder="Choose" error={show('reportType')}
            options={types.map((t) => ({ value: t, label: t }))}
            onChange={(reportType) => set({ reportType, circle: requirements.some((r) => r.reportType === reportType && r.circle === draft.circle) ? draft.circle : '' })} />
        </Field>
        <Field id="arr-circle" label="Circle / State" required error={show('circle')}>
          <SelectField id="arr-circle" value={draft.circle} placeholder="Choose" error={show('circle')} disabled={!draft.reportType}
            options={circles.map((c) => ({ value: c, label: c }))} onChange={(circle) => set({ circle })} />
        </Field>
        <Field id="arr-reporting" label="Reporting date" required error={show('reportingDate')}>
          <Input type="date" {...fieldA11y('arr-reporting', show('reportingDate'))} value={draft.reportingDate} onChange={(e) => set({ reportingDate: e.target.value })} />
        </Field>
      </div>

      <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
        <Field id="arr-date" label="Actual arrival date" required error={show('arrivalDate')}>
          <Input type="date" {...fieldA11y('arr-date', show('arrivalDate'))} value={draft.arrivalDate} max={localDate(now)}
            onChange={(e) => set({ arrivalDate: e.target.value, timeIsEntryTime: false })} />
        </Field>
        <Field id="arr-time" label="Actual arrival time" required error={show('arrivalTime')}
          hint={draft.timeIsEntryTime ? 'Set to the time of entry, and labelled that way.' : undefined}>
          <Input type="time" {...fieldA11y('arr-time', show('arrivalTime'))} value={draft.arrivalTime}
            onChange={(e) => set({ arrivalTime: e.target.value, timeIsEntryTime: false })} />
        </Field>
        <div className="flex items-end">
          <Button type="button" variant="outline" size="sm" className="w-full"
            onClick={() => set({ arrivalDate: localDate(now), arrivalTime: localTime(now), timeIsEntryTime: true })}>
            <Clock /> It arrived just now
          </Button>
        </div>
      </div>

      <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
        <Field id="arr-file" label="CSV file name" error={show('fileName')} hint="Without it the note is flagged for review.">
          <Input {...fieldA11y('arr-file', show('fileName'))} value={draft.fileName} list="arr-file-options" maxLength={200}
            placeholder="e.g. MP_LWE_16-10-2026.csv" onChange={(e) => set({ fileName: e.target.value })} />
          <datalist id="arr-file-options">{fileSuggestions.map((f) => <option key={f} value={f} />)}</datalist>
        </Field>
        <Field id="arr-by" label="Received by">
          <Input id="arr-by" value={draft.receivedBy} maxLength={80} placeholder="Reporting-team member" onChange={(e) => set({ receivedBy: e.target.value })} />
        </Field>
      </div>
      <Field id="arr-notes" label="Notes">
        <textarea id="arr-notes" className={textareaClass} value={draft.notes} maxLength={500} onChange={(e) => set({ notes: e.target.value })} />
      </Field>
      {warnings.length > 0 && (
        <Alert className="border-amber-300 bg-amber-50/70">
          <TriangleAlert className="text-amber-700" />
          <AlertDescription><ul className="list-disc pl-4">{warnings.map((w) => <li key={w}>{w}</li>)}</ul></AlertDescription>
        </Alert>
      )}
      <FormActions submitLabel={editingId ? 'Save changes' : 'Record arrival'} onCancel={onCancel} />
    </form>
  );
}

export function ContactForm({ title, initial, onSave, onCancel }: {
  title: string; initial: Contact; onSave: (contact: Contact) => void; onCancel: () => void;
}) {
  const [contact, setContact] = useState(initial);
  const [submitted, setSubmitted] = useState(false);
  const errors = contactErrors(contact);
  const show = (k: keyof Contact) => (submitted ? errors[k] : undefined);
  const input = (k: keyof Contact, label: string, props: Record<string, unknown> = {}) => (
    <Field id={`contact-${k}`} label={label} error={show(k)}>
      <Input {...fieldA11y(`contact-${k}`, show(k))} value={contact[k]} maxLength={120} {...props}
        onChange={(e) => setContact((c) => ({ ...c, [k]: e.target.value }))} />
    </Field>
  );
  return (
    <form noValidate className="space-y-3" onSubmit={(e) => {
      e.preventDefault();
      setSubmitted(true);
      if (Object.keys(errors).length === 0) {
        onSave(Object.fromEntries(Object.entries(contact).map(([k, v]) => [k, v.trim()])) as unknown as Contact);
      }
    }}>
      <p className="text-xs text-muted-foreground">Contact for {title}. Every field is optional; leave unknown details blank.</p>
      <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
        {input('name', 'Contact person')}
        {input('designation', 'Designation')}
        {input('phone', 'Phone number', { type: 'tel', inputMode: 'tel' })}
        {input('email', 'Email address', { type: 'email' })}
        {input('backup', 'Backup contact')}
      </div>
      <Field id="contact-notes" label="Notes">
        <textarea id="contact-notes" className={textareaClass} value={contact.notes} maxLength={500}
          onChange={(e) => setContact((c) => ({ ...c, notes: e.target.value }))} />
      </Field>
      <FormActions submitLabel="Save contact" onCancel={onCancel} />
    </form>
  );
}

export function FollowUpForm({ title, contactName, now, onSave, onCancel }: {
  title: string; contactName: string; now: Date; onSave: (draft: FollowUpDraft & { method: FollowUpMethod }) => void; onCancel: () => void;
}) {
  const [draft, setDraft] = useState<FollowUpDraft>({
    at: `${localDate(now)}T${localTime(now)}`, contactPerson: contactName, method: '', outcome: '', expectedAt: '', nextFollowUp: '',
  });
  const [submitted, setSubmitted] = useState(false);
  const errors = followUpErrors(draft, now);
  const show = (k: keyof FollowUpDraft) => (submitted ? errors[k] : undefined);
  const set = (changes: Partial<FollowUpDraft>) => setDraft((d) => ({ ...d, ...changes }));
  return (
    <form noValidate className="space-y-3" onSubmit={(e) => {
      e.preventDefault();
      setSubmitted(true);
      if (Object.keys(errors).length === 0) onSave({ ...draft, method: draft.method as FollowUpMethod, outcome: draft.outcome.trim(), contactPerson: draft.contactPerson.trim() });
    }}>
      <p className="text-xs text-muted-foreground">
        Records a follow-up you have already made for {title}. Nothing is sent from here. A contact is not required; internal notes are fine.
      </p>
      <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
        <Field id="fu-at" label="Follow-up date and time" required error={show('at')}>
          <Input type="datetime-local" {...fieldA11y('fu-at', show('at'))} value={draft.at} onChange={(e) => set({ at: e.target.value })} />
        </Field>
        <Field id="fu-method" label="Method" required error={show('method')}>
          <SelectField id="fu-method" value={draft.method} placeholder="Choose" error={show('method')}
            options={Object.entries(FOLLOW_UP_METHODS).map(([value, label]) => ({ value, label }))} onChange={(method) => set({ method: method as FollowUpMethod })} />
        </Field>
        <Field id="fu-contact" label="Contact person">
          <Input id="fu-contact" value={draft.contactPerson} maxLength={120} placeholder="If known" onChange={(e) => set({ contactPerson: e.target.value })} />
        </Field>
        <Field id="fu-expected" label="Expected submission" hint="Only if they gave a time.">
          <Input id="fu-expected" type="datetime-local" value={draft.expectedAt} onChange={(e) => set({ expectedAt: e.target.value })} />
        </Field>
        <Field id="fu-next" label="Next follow-up" error={show('nextFollowUp')}>
          <Input type="datetime-local" {...fieldA11y('fu-next', show('nextFollowUp'))} value={draft.nextFollowUp} onChange={(e) => set({ nextFollowUp: e.target.value })} />
        </Field>
      </div>
      <Field id="fu-outcome" label="Outcome / notes" required error={show('outcome')}>
        <textarea {...fieldA11y('fu-outcome', show('outcome'))} className={cn(textareaClass, show('outcome') && 'border-destructive')}
          value={draft.outcome} maxLength={500} onChange={(e) => set({ outcome: e.target.value })} />
      </Field>
      <FormActions submitLabel="Add follow-up" onCancel={onCancel} />
    </form>
  );
}

export function DeadlineForm({ reportTypes, config, onSave, onCancel }: {
  reportTypes: string[]; config: DeadlineConfig; onSave: (config: DeadlineConfig) => void; onCancel: () => void;
}) {
  const [rows, setRows] = useState(() => Object.fromEntries(reportTypes.map((t) => [t, config[t] ?? null])) as Record<string, Deadline | null>);
  return (
    <form noValidate className="space-y-3" onSubmit={(e) => { e.preventDefault(); onSave(rows); }}>
      <p className="text-xs text-muted-foreground">
        A submission is only marked Late once a deadline is set here and has passed. No deadline is assumed by default.
      </p>
      {reportTypes.map((t) => {
        const rule = rows[t];
        return (
          <fieldset key={t} className="grid grid-cols-1 items-end gap-3 rounded-lg border p-3 sm:grid-cols-[1fr_9rem_8rem]">
            <legend className="px-1 text-xs font-semibold">{t}</legend>
            <label className="flex items-center gap-2 text-sm">
              <input type="checkbox" className="size-4 accent-primary" checked={Boolean(rule)}
                onChange={(e) => setRows((r) => ({ ...r, [t]: e.target.checked ? { dayOffset: 1, time: '10:00' } : null }))} />
              Deadline configured
            </label>
            <Field plain id={`dl-day-${shortType(t)}`} label="Due">
              <SelectField id={`dl-day-${shortType(t)}`} value={rule ? String(rule.dayOffset) : ''} placeholder="—" disabled={!rule}
                options={[{ value: '0', label: 'Same day' }, { value: '1', label: 'Next day' }, { value: '2', label: 'Day after next' }]}
                onChange={(v) => setRows((r) => ({ ...r, [t]: { ...(r[t] as Deadline), dayOffset: Number(v) } }))} />
            </Field>
            <Field plain id={`dl-time-${shortType(t)}`} label="By (time)">
              <Input id={`dl-time-${shortType(t)}`} type="time" disabled={!rule} value={rule?.time ?? ''}
                onChange={(e) => setRows((r) => ({ ...r, [t]: { ...(r[t] as Deadline), time: e.target.value || '10:00' } }))} />
            </Field>
          </fieldset>
        );
      })}
      <FormActions submitLabel="Save deadlines" onCancel={onCancel} />
    </form>
  );
}

// --- Email ---------------------------------------------------------------------------------

/** Labels test mode wherever an email can be sent: nothing leaves the machine. */
export function EmailModeNote({ status, error }: { status: EmailStatus | null; error?: Error | null }) {
  if (error) {
    return (
      <Alert variant="destructive">
        <CircleX />
        <AlertTitle>Email is unavailable</AlertTitle>
        <AlertDescription>{error.message}</AlertDescription>
      </Alert>
    );
  }
  if (!status) return null;
  return status.test_mode ? (
    <Alert className="border-amber-300 bg-amber-50/70">
      <FlaskConical className="text-amber-700" />
      <AlertTitle>TEST MODE</AlertTitle>
      <AlertDescription>Emails are printed in the backend terminal and are not delivered to anyone.</AlertDescription>
    </Alert>
  ) : (
    <Alert>
      <Mail />
      <AlertTitle>Live email</AlertTitle>
      <AlertDescription>Emails are sent from {status.from_email} through {status.transport}.</AlertDescription>
    </Alert>
  );
}

function SendOutcome({ result, error }: { result: EmailResult | null; error: Error | null }) {
  if (error) {
    return (
      <Alert variant="destructive" role="alert">
        <CircleX />
        <AlertTitle>Not sent</AlertTitle>
        <AlertDescription>{error.message}</AlertDescription>
      </Alert>
    );
  }
  if (!result) return null;
  return (
    <Alert className={result.test_mode ? 'border-amber-300 bg-amber-50/70' : 'border-emerald-200 bg-emerald-50/70'} role="status">
      <CircleCheck className={result.test_mode ? 'text-amber-700' : 'text-emerald-700'} />
      <AlertTitle>{result.test_mode ? 'Printed in the backend terminal (test mode)' : 'Accepted by the mail server'}</AlertTitle>
      <AlertDescription>
        {result.message} To: {result.to.join(', ')}{result.cc.length ? ` · CC: ${result.cc.join(', ')}` : ''}.
      </AlertDescription>
    </Alert>
  );
}

function Preview({ to, cc, subject, body }: { to: string; cc?: string; subject: string; body: string }) {
  const row = (label: string, value: ReactNode) => (
    <div className="grid grid-cols-[4.5rem_1fr] gap-2 py-1"><dt className="text-xs text-muted-foreground">{label}</dt><dd className="min-w-0 break-words">{value}</dd></div>
  );
  return (
    <section aria-label="Email preview" className="rounded-md border bg-muted/30 px-3 py-2 text-sm">
      <dl className="divide-y">
        {row('To', to || <span className="text-muted-foreground">—</span>)}
        {cc ? row('CC', cc) : null}
        {row('Subject', subject)}
      </dl>
      <pre className="mt-2 border-t pt-2 font-sans text-sm whitespace-pre-wrap">{body}</pre>
    </section>
  );
}

const reminderQuery = (reminder: ReminderRequest) =>
  new URLSearchParams(Object.entries(reminder).filter(([, v]) => v) as [string, string][]).toString();

/** Send the standard reminder now: shows the resolved recipient and the backend's text before sending. */
export function ReminderSend({ reminder, label, recipient, status, statusError, onAddContact, onCompose, onCancel }: {
  reminder: ReminderRequest; label: string; recipient: string; status: EmailStatus | null; statusError: Error | null;
  onAddContact: () => void; onCompose: () => void; onCancel: () => void;
}) {
  const template = useApiQuery(`reminder-template|${reminderQuery(reminder)}`, (signal) => fetchReminderTemplate(reminder, signal));
  const [sending, setSending] = useState(false);
  const [result, setResult] = useState<EmailResult | null>(null);
  const [error, setError] = useState<Error | null>(null);
  const missing = recipient ? null : "No email address is recorded for this circle's contact, so the reminder cannot be sent.";

  const send = async () => {
    setSending(true);
    setError(null);
    try {
      setResult(await sendReminder({ ...reminder, to: recipient, cc: '' }));
    } catch (e) {
      setError(e instanceof Error ? e : new Error('The reminder could not be sent.'));
    } finally {
      setSending(false);
    }
  };

  return (
    <div className="space-y-3">
      <EmailModeNote status={status} error={statusError} />
      <dl className="grid grid-cols-[8rem_1fr] gap-x-2 gap-y-1 text-sm">
        <dt className="text-xs text-muted-foreground">Report</dt><dd>{label}</dd>
        <dt className="text-xs text-muted-foreground">Deadline</dt>
        <dd>{reminder.deadline ? formatDateTime(reminder.deadline) : 'Not configured (not mentioned in the email)'}</dd>
        <dt className="text-xs text-muted-foreground">Recipient</dt><dd>{recipient || <span className="text-destructive">Missing</span>}</dd>
      </dl>
      {missing && (
        <Alert variant="destructive">
          <TriangleAlert />
          <AlertTitle>Recipient missing</AlertTitle>
          <AlertDescription>
            {missing}
            <Button size="sm" variant="outline" className="mt-2" onClick={onAddContact}>Add contact email</Button>
          </AlertDescription>
        </Alert>
      )}
      {template.error ? (
        <Alert variant="destructive"><CircleX /><AlertTitle>Reminder unavailable</AlertTitle><AlertDescription>{template.error.message}</AlertDescription></Alert>
      ) : template.data ? (
        <Preview to={recipient} subject={template.data.subject} body={template.data.body} />
      ) : <p className="text-sm text-muted-foreground" aria-busy="true">Loading the standard reminder…</p>}
      <SendOutcome result={result} error={error} />
      <div className="flex flex-wrap items-center gap-2">
        {!result && (
          <Button onClick={send} disabled={sending || Boolean(missing) || !template.data || Boolean(statusError)}>
            <Send /> {sending ? 'Sending…' : 'Send reminder now'}
          </Button>
        )}
        <Button variant="outline" onClick={onCancel} disabled={sending}>{result ? 'Close' : 'Cancel'}</Button>
        {!result && <Button variant="ghost" onClick={onCompose} disabled={sending}><Mail /> Edit as personal email</Button>}
      </div>
    </div>
  );
}

/** Write or edit an email; review it, then send it with an explicit action. Closing never sends. */
export function ComposeEmail({ initial, reminder, status, statusError, onCancel }: {
  initial: EmailDraft; reminder?: ReminderRequest; status: EmailStatus | null; statusError: Error | null; onCancel: () => void;
}) {
  const [draft, setDraft] = useState(initial);
  const [step, setStep] = useState<'edit' | 'review'>('edit');
  const [submitted, setSubmitted] = useState(false);
  const [loadingTemplate, setLoadingTemplate] = useState(false);
  const [templateError, setTemplateError] = useState<string | null>(null);
  const [sending, setSending] = useState(false);
  const [result, setResult] = useState<EmailResult | null>(null);
  const [error, setError] = useState<Error | null>(null);
  const set = (changes: Partial<EmailDraft>) => setDraft((d) => ({ ...d, ...changes }));
  const errors = emailErrors(draft);
  // Field errors from the backend (it validates again) are shown on the fields.
  const serverErrors = error instanceof ApiError && error.status === 400 ? error.details : {};
  const show = (k: keyof EmailDraft) => (submitted ? errors[k] : undefined)
    ?? (Array.isArray(serverErrors[k]) ? String((serverErrors[k] as string[])[0]) : undefined);

  const loadTemplate = async () => {
    if (!reminder) return;
    setLoadingTemplate(true);
    setTemplateError(null);
    try {
      const t = await fetchReminderTemplate(reminder);
      set({ subject: t.subject, body: t.body });
    } catch (e) {
      setTemplateError(e instanceof Error ? e.message : 'The standard reminder could not be loaded.');
    } finally {
      setLoadingTemplate(false);
    }
  };

  const send = async () => {
    setSending(true);
    setError(null);
    try {
      setResult(await sendPersonalEmail(draft));
    } catch (e) {
      const failure = e instanceof Error ? e : new Error('The email could not be sent.');
      setError(failure);
      if (failure instanceof ApiError && failure.status === 400) setStep('edit');
    } finally {
      setSending(false);
    }
  };

  if (result) {
    return (
      <div className="space-y-3">
        <SendOutcome result={result} error={null} />
        <Button variant="outline" onClick={onCancel}>Close</Button>
      </div>
    );
  }

  if (step === 'review') {
    return (
      <div className="space-y-3">
        <EmailModeNote status={status} error={statusError} />
        <p className="text-sm">Check the email below. It is sent only when you select <strong>Send email</strong>.</p>
        <Preview to={splitAddresses(draft.to).join(', ')} cc={splitAddresses(draft.cc).join(', ')} subject={draft.subject.trim()} body={draft.body.trim()} />
        <SendOutcome result={null} error={error} />
        <div className="flex flex-wrap items-center gap-2">
          <Button onClick={send} disabled={sending || Boolean(statusError)}><Send /> {sending ? 'Sending…' : 'Send email'}</Button>
          <Button variant="outline" onClick={() => setStep('edit')} disabled={sending}>Back to edit</Button>
          <Button variant="ghost" onClick={onCancel} disabled={sending}>Cancel</Button>
        </div>
      </div>
    );
  }

  return (
    <form noValidate className="space-y-3" onSubmit={(e) => {
      e.preventDefault();
      setSubmitted(true);
      if (Object.keys(errors).length === 0) { setError(null); setStep('review'); }
    }}>
      <EmailModeNote status={status} error={statusError} />
      {reminder && (
        <div className="flex flex-wrap items-center gap-2">
          <Button type="button" size="sm" variant="outline" onClick={loadTemplate} disabled={loadingTemplate}>
            <FileText /> {loadingTemplate ? 'Loading…' : 'Load standard reminder'}
          </Button>
          <span className="text-xs text-muted-foreground">Replaces the subject and message; edit them before sending.</span>
          {templateError && <p className="w-full text-xs text-destructive" role="alert">{templateError}</p>}
        </div>
      )}
      <Field id="mail-to" label="To" required error={show('to')} hint="Separate several addresses with commas.">
        <Input {...fieldA11y('mail-to', show('to'))} type="text" inputMode="email" autoComplete="off" value={draft.to} maxLength={2000}
          onChange={(e) => set({ to: e.target.value })} />
      </Field>
      <Field id="mail-cc" label="CC" error={show('cc')}>
        <Input {...fieldA11y('mail-cc', show('cc'))} type="text" inputMode="email" autoComplete="off" value={draft.cc} maxLength={2000}
          onChange={(e) => set({ cc: e.target.value })} />
      </Field>
      <Field id="mail-subject" label="Subject" required error={show('subject')}>
        <Input {...fieldA11y('mail-subject', show('subject'))} value={draft.subject} maxLength={200} onChange={(e) => set({ subject: e.target.value })} />
      </Field>
      <Field id="mail-body" label="Message" required error={show('body')}>
        <textarea {...fieldA11y('mail-body', show('body'))} className={cn(textareaClass, 'min-h-48')} value={draft.body} maxLength={20000}
          onChange={(e) => set({ body: e.target.value })} />
      </Field>
      {error && !(error instanceof ApiError && error.status === 400) && <SendOutcome result={null} error={error} />}
      <FormActions submitLabel="Review email" onCancel={onCancel} />
    </form>
  );
}
