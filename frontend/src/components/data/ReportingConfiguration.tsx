import { Fragment, useState } from 'react';
import { CheckCircle2, ChevronDown, ChevronRight, Loader2 } from 'lucide-react';
import { Alert, AlertTitle } from '@/components/ui/alert';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { useApiQuery } from '../../hooks/useApiQuery';
import { formatDate, formatDateTime } from '../../lib/format';
import {
  changeCoverageThreshold, createReportingUnit, fetchCoverageThreshold, fetchReportingUnits, fieldError, updateReportingUnit,
} from '../../services/api';
import type { ReportingUnit, ReportingUnitAction, ReportingUnitChange, ReportingUnitPatch } from '../../types/reporting';

const TECHNOLOGIES = ['4G Saturation', 'LWE'];
const ACTION_LABEL: Record<ReportingUnitAction, string> = {
  created: 'Created', corrected: 'Corrected', deactivated: 'Deactivated', reactivated: 'Reactivated',
};
const FIELD_LABEL: Record<string, string> = { active_from: 'Active from', active_until: 'Active until', notes: 'Notes', technology: 'Technology', circle: 'Circle' };
const today = () => new Date().toLocaleDateString('en-CA');
const errorText = (e: unknown) => (e instanceof Error ? e.message : String(e));
const pct = (v: number | null | undefined) => (v == null ? '—' : `${v.toLocaleString('en-IN', { maximumFractionDigits: 2 })} %`);

/** Field messages of a validation error for the given fields, plus the top-level message when no field matched. */
function errorsOf(e: unknown, fields: string[]) {
  const byField = Object.fromEntries(fields.map((f) => [f, fieldError(e, f)]).filter(([, m]) => m)) as Record<string, string>;
  return { byField, message: Object.keys(byField).length ? null : errorText(e) };
}

function Field({ id, label, error, children }: { id: string; label: string; error?: string | null; children: React.ReactNode }) {
  return (
    <div className="flex flex-col gap-1">
      <Label htmlFor={id} className="text-xs">{label}</Label>
      {children}
      {error && <p className="text-xs text-destructive" id={`${id}-error`}>{error}</p>}
    </div>
  );
}

/** "Active until: — → 30 Nov 2026" for each field a change touched. */
function changeSummary(c: ReportingUnitChange) {
  const keys = [...new Set([...Object.keys(c.before ?? {}), ...Object.keys(c.after ?? {})])]
    .filter((k) => (c.before as Record<string, unknown>)?.[k] !== (c.after as Record<string, unknown>)?.[k]);
  const show = (v: unknown) => (v == null || v === '' ? '—' : /^\d{4}-\d{2}-\d{2}$/.test(String(v)) ? formatDate(String(v)) : String(v));
  if (c.action === 'created') return `Active from ${show(c.after?.active_from)}`;
  return keys.map((k) => `${FIELD_LABEL[k] ?? k}: ${show((c.before as Record<string, unknown>)?.[k])} → ${show((c.after as Record<string, unknown>)?.[k])}`).join('; ');
}

// --- Reporting units ---------------------------------------------------------------------------------

type Mode = 'correct' | 'deactivate' | 'reactivate';

/**
 * Admin: the reporting units (circle + technology) expected to send daily data, with their activation and deactivation
 * dates. Every change needs a reason and is kept in the unit's history.
 */
export function ReportingUnitsCard() {
  const [tick, setTick] = useState(0);
  const units = useApiQuery(`reporting-units|${tick}`, fetchReportingUnits);
  const [action, setAction] = useState<{ id: number; mode: Mode } | null>(null);
  const [expanded, setExpanded] = useState<number | null>(null);
  const [done, setDone] = useState<string | null>(null);
  const reload = (message: string) => { setDone(message); setAction(null); setTick((t) => t + 1); };
  const circles = [...new Set((units.data?.units ?? []).map((u) => u.circle))].sort();
  return (
    <Card role="region" aria-label="Reporting units">
      <CardHeader>
        <CardTitle className="text-sm font-semibold">Reporting units</CardTitle>
        <CardDescription className="text-xs">
          The circles and technologies expected to send daily data, from their activation date until their deactivation date. A date counts as Complete
          only when every active unit has reported. Each change needs a reason; finalized months keep the units they were finalized with.
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-3">
        {units.error && <p className="text-xs text-destructive" role="alert">{units.error.message}</p>}
        {done && (
          <Alert className="border-emerald-200 bg-emerald-50/70" role="status">
            <CheckCircle2 className="text-emerald-700" /><AlertTitle>{done}</AlertTitle>
          </Alert>
        )}
        {units.data && (units.data.units.length === 0 ? <p className="text-xs text-muted-foreground">No reporting units configured yet.</p> : (
          <div className="overflow-x-auto rounded-md border">
            <table className="w-full text-left text-xs">
              <caption className="sr-only">Reporting units</caption>
              <thead className="bg-muted"><tr>{['Technology', 'Circle', 'Active from', 'Active until', 'Last change', ''].map((h) => <th key={h} className="px-2.5 py-1.5 font-medium">{h}</th>)}</tr></thead>
              <tbody className="divide-y">
                {units.data.units.map((u) => {
                  const last = u.changes[0];
                  const name = `${u.technology} ${u.circle}`;
                  return (
                    <Fragment key={u.id}>
                      <tr aria-label={name}>
                        <td className="px-2.5 py-1.5">{u.technology}</td>
                        <td className="px-2.5 py-1.5 font-medium">{u.circle}</td>
                        <td className="px-2.5 py-1.5">{formatDate(u.active_from)}</td>
                        <td className="px-2.5 py-1.5">{u.active_until ? <Badge variant="outline">Inactive from {formatDate(u.active_until)}</Badge>
                          : <Badge className="bg-emerald-600">Active</Badge>}</td>
                        <td className="max-w-72 px-2.5 py-1.5">
                          {last ? <>{ACTION_LABEL[last.action] ?? last.action} · {last.user ?? '—'} · {formatDateTime(last.at)}
                            {last.reason && <span className="block text-muted-foreground">{last.reason}</span>}</> : '—'}
                        </td>
                        <td className="px-2.5 py-1.5">
                          <div className="flex flex-wrap gap-1">
                            <Button size="sm" variant="outline" className="h-7 text-xs" aria-label={`Correct ${name}`}
                              onClick={() => { setAction({ id: u.id, mode: 'correct' }); setDone(null); }}>Correct</Button>
                            {u.active_until ? (
                              <Button size="sm" variant="outline" className="h-7 text-xs" aria-label={`Reactivate ${name}`}
                                onClick={() => { setAction({ id: u.id, mode: 'reactivate' }); setDone(null); }}>Reactivate</Button>
                            ) : (
                              <Button size="sm" variant="outline" className="h-7 text-xs" aria-label={`Deactivate ${name}`}
                                onClick={() => { setAction({ id: u.id, mode: 'deactivate' }); setDone(null); }}>Deactivate</Button>
                            )}
                            <Button size="sm" variant="ghost" className="h-7 text-xs" aria-expanded={expanded === u.id} aria-label={`Change history of ${name}`}
                              onClick={() => setExpanded((e) => (e === u.id ? null : u.id))}>
                              {expanded === u.id ? <ChevronDown /> : <ChevronRight />} History ({u.changes.length})
                            </Button>
                          </div>
                        </td>
                      </tr>
                      {action?.id === u.id && (
                        <tr><td colSpan={6} className="bg-muted/30 px-2.5 py-2">
                          <UnitChangeForm unit={u} mode={action.mode} onCancel={() => setAction(null)}
                            onDone={(message) => reload(message)} />
                        </td></tr>
                      )}
                      {expanded === u.id && (
                        <tr><td colSpan={6} className="bg-muted/20 px-2.5 py-2"><UnitHistory unit={u} /></td></tr>
                      )}
                    </Fragment>
                  );
                })}
              </tbody>
            </table>
          </div>
        ))}
        <AddUnitForm circles={circles} onDone={(message) => reload(message)} />
      </CardContent>
    </Card>
  );
}

function UnitHistory({ unit }: { unit: ReportingUnit }) {
  if (!unit.changes.length) return <p className="text-xs text-muted-foreground">No changes recorded.</p>;
  return (
    <ol className="space-y-1 text-xs" aria-label={`Changes of ${unit.technology} ${unit.circle}`}>
      {unit.changes.map((c, i) => (
        <li key={`${c.at}-${i}`} className="rounded border bg-card px-2 py-1">
          <span className="font-medium">{ACTION_LABEL[c.action] ?? c.action}</span> · {c.user ?? '—'} · {formatDateTime(c.at)}
          {changeSummary(c) && <span className="block">{changeSummary(c)}</span>}
          <span className="block text-muted-foreground">Reason: {c.reason || '—'}</span>
        </li>
      ))}
    </ol>
  );
}

function UnitChangeForm({ unit, mode, onCancel, onDone }: { unit: ReportingUnit; mode: Mode; onCancel: () => void; onDone: (message: string) => void }) {
  const name = `${unit.technology} ${unit.circle}`;
  const [activeFrom, setActiveFrom] = useState(unit.active_from);
  const [notes, setNotes] = useState(unit.notes ?? '');
  const [until, setUntil] = useState(today());
  const [reason, setReason] = useState('');
  const [busy, setBusy] = useState(false);
  const [errors, setErrors] = useState<{ byField: Record<string, string>; message: string | null } | null>(null);
  const id = `unit-${unit.id}-${mode}`;
  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    const patch: ReportingUnitPatch = mode === 'correct' ? { active_from: activeFrom, notes, reason: reason.trim() }
      : mode === 'deactivate' ? { active_until: until, reason: reason.trim() } : { active_until: null, reason: reason.trim() };
    setBusy(true);
    setErrors(null);
    try {
      await updateReportingUnit(unit.id, patch);
      onDone(mode === 'correct' ? `${name} corrected` : mode === 'deactivate' ? `${name} deactivated from ${formatDate(until)}` : `${name} reactivated`);
    } catch (err) {
      setErrors(errorsOf(err, ['active_from', 'active_until', 'notes', 'reason']));
    } finally {
      setBusy(false);
    }
  };
  const title = mode === 'correct' ? `Correct ${name}` : mode === 'deactivate' ? `Deactivate ${name}` : `Reactivate ${name}`;
  return (
    <form onSubmit={submit} aria-label={title} className="space-y-2">
      <p className="text-xs font-semibold">{title}</p>
      {mode === 'deactivate' && <p className="text-xs text-muted-foreground">From this date the unit is no longer expected to report: missing data no longer makes a date Provisional.</p>}
      {mode === 'reactivate' && <p className="text-xs text-muted-foreground">The unit is expected to report again (its deactivation date is cleared).</p>}
      <div className="grid gap-2 sm:grid-cols-4">
        {mode === 'correct' && (
          <>
            <Field id={`${id}-from`} label="Active from" error={errors?.byField.active_from}>
              <Input id={`${id}-from`} type="date" value={activeFrom} onChange={(e) => setActiveFrom(e.target.value)} required />
            </Field>
            <Field id={`${id}-notes`} label="Notes" error={errors?.byField.notes}>
              <Input id={`${id}-notes`} value={notes} onChange={(e) => setNotes(e.target.value)} />
            </Field>
          </>
        )}
        {mode === 'deactivate' && (
          <Field id={`${id}-until`} label="Active until (deactivation date)" error={errors?.byField.active_until}>
            <Input id={`${id}-until`} type="date" value={until} onChange={(e) => setUntil(e.target.value)} required />
          </Field>
        )}
        <div className="sm:col-span-2">
          <Field id={`${id}-reason`} label="Reason (required)" error={errors?.byField.reason}>
            <Input id={`${id}-reason`} value={reason} onChange={(e) => setReason(e.target.value)} placeholder="e.g. Circle letter of 7 Nov" />
          </Field>
        </div>
      </div>
      {errors?.message && <p className="text-xs text-destructive" role="alert">{errors.message}</p>}
      <div className="flex gap-2">
        <Button type="submit" size="sm" disabled={busy || !reason.trim() || (mode === 'deactivate' && !until)}>
          {busy && <Loader2 className="animate-spin" />} {mode === 'correct' ? 'Save correction' : mode === 'deactivate' ? 'Deactivate unit' : 'Reactivate unit'}
        </Button>
        <Button type="button" size="sm" variant="ghost" onClick={onCancel} disabled={busy}>Cancel</Button>
      </div>
    </form>
  );
}

function AddUnitForm({ circles, onDone }: { circles: string[]; onDone: (message: string) => void }) {
  const [open, setOpen] = useState(false);
  const [technology, setTechnology] = useState('');
  const [circle, setCircle] = useState('');
  const [activeFrom, setActiveFrom] = useState('');
  const [notes, setNotes] = useState('');
  const [reason, setReason] = useState('');
  const [busy, setBusy] = useState(false);
  const [errors, setErrors] = useState<{ byField: Record<string, string>; message: string | null } | null>(null);
  if (!open) return <Button size="sm" variant="outline" onClick={() => setOpen(true)}>Add reporting unit</Button>;
  const ready = technology && circle.trim() && activeFrom && reason.trim();
  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    setBusy(true);
    setErrors(null);
    try {
      const { unit } = await createReportingUnit({ technology, circle: circle.trim().toUpperCase(), active_from: activeFrom, reason: reason.trim(), ...(notes.trim() ? { notes: notes.trim() } : {}) });
      setOpen(false);
      setTechnology(''); setCircle(''); setActiveFrom(''); setNotes(''); setReason('');
      onDone(`${unit.technology} ${unit.circle} added, active from ${formatDate(unit.active_from)}`);
    } catch (err) {
      setErrors(errorsOf(err, ['technology', 'circle', 'active_from', 'notes', 'reason']));
    } finally {
      setBusy(false);
    }
  };
  return (
    <form onSubmit={submit} aria-label="Add reporting unit" className="space-y-2 rounded-md border px-3 py-2">
      <p className="text-xs font-semibold">Add reporting unit</p>
      <div className="grid gap-2 sm:grid-cols-3 lg:grid-cols-6">
        <Field id="unit-technology" label="Technology" error={errors?.byField.technology}>
          <select id="unit-technology" value={technology} onChange={(e) => setTechnology(e.target.value)} className="h-8 rounded-md border bg-transparent px-2 text-sm">
            <option value="">Choose</option>
            {TECHNOLOGIES.map((t) => <option key={t} value={t}>{t}</option>)}
          </select>
        </Field>
        <Field id="unit-circle" label="Circle" error={errors?.byField.circle}>
          <Input id="unit-circle" value={circle} onChange={(e) => setCircle(e.target.value)} list="unit-circles" placeholder="e.g. OD" />
          <datalist id="unit-circles">{circles.map((c) => <option key={c} value={c} />)}</datalist>
        </Field>
        <Field id="unit-from" label="Active from" error={errors?.byField.active_from}>
          <Input id="unit-from" type="date" value={activeFrom} onChange={(e) => setActiveFrom(e.target.value)} />
        </Field>
        <Field id="unit-notes" label="Notes (optional)" error={errors?.byField.notes}>
          <Input id="unit-notes" value={notes} onChange={(e) => setNotes(e.target.value)} />
        </Field>
        <div className="sm:col-span-2">
          <Field id="unit-reason" label="Reason (required)" error={errors?.byField.reason}>
            <Input id="unit-reason" value={reason} onChange={(e) => setReason(e.target.value)} placeholder="e.g. New circle in the programme" />
          </Field>
        </div>
      </div>
      {errors?.message && <p className="text-xs text-destructive" role="alert">{errors.message}</p>}
      <div className="flex gap-2">
        <Button type="submit" size="sm" disabled={busy || !ready}>{busy && <Loader2 className="animate-spin" />} Add unit</Button>
        <Button type="button" size="sm" variant="ghost" onClick={() => { setOpen(false); setErrors(null); }} disabled={busy}>Cancel</Button>
      </div>
    </form>
  );
}

// --- Coverage threshold ----------------------------------------------------------------------------

/**
 * Admin: the coverage threshold (share of a unit's expected sites with data for the unit to count as reported on a
 * date). Separate from the 98.5 % site availability threshold. A past effective date re-labels earlier non-finalized
 * dates and needs an explicit confirmation.
 */
export function CoverageThresholdCard() {
  const [tick, setTick] = useState(0);
  const threshold = useApiQuery(`coverage-threshold|${tick}`, fetchCoverageThreshold);
  const [value, setValue] = useState('');
  const [effective, setEffective] = useState('');
  const [reason, setReason] = useState('');
  const [busy, setBusy] = useState(false);
  const [retroactive, setRetroactive] = useState<string | null>(null);
  const [errors, setErrors] = useState<{ byField: Record<string, string>; message: string | null } | null>(null);
  const [done, setDone] = useState<string | null>(null);
  const number = Number(value);
  const valid = value.trim() !== '' && Number.isFinite(number) && number >= 0 && number <= 100;
  const ready = valid && effective && reason.trim();

  const send = async (confirm: boolean) => {
    setBusy(true);
    setErrors(null);
    setDone(null);
    try {
      const result = await changeCoverageThreshold({ value_pct: number, effective_from: effective, reason: reason.trim(), ...(confirm ? { confirm_retroactive: true } : {}) });
      setRetroactive(null);
      setDone(`Coverage threshold set to ${pct(result.value_pct)} from ${formatDate(result.effective_from)}${result.previous_value_pct != null ? ` (was ${pct(result.previous_value_pct)})` : ''}.`);
      setValue(''); setEffective(''); setReason('');
      setTick((t) => t + 1);
    } catch (err) {
      const retro = fieldError(err, 'confirm_retroactive');
      if (retro && !confirm) setRetroactive(retro);
      else {
        setRetroactive(null);
        setErrors(errorsOf(err, ['value_pct', 'effective_from', 'reason']));
      }
    } finally {
      setBusy(false);
    }
  };
  const edit = <T,>(set: (v: T) => void) => (v: T) => { set(v); setRetroactive(null); };
  const data = threshold.data;
  return (
    <Card role="region" aria-label="Coverage threshold">
      <CardHeader>
        <CardTitle className="text-sm font-semibold">Coverage threshold</CardTitle>
        <CardDescription className="text-xs">
          The share of a reporting unit's expected sites that must have data for the unit to count as reported on a date. This is not the site
          availability threshold: a site's uptime is still measured against {pct(data?.availability_threshold_pct ?? 98.5)}.
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-3">
        {threshold.error && <p className="text-xs text-destructive" role="alert">{threshold.error.message}</p>}
        {data && (
          <dl className="grid grid-cols-2 gap-2 sm:max-w-md">
            <div className="rounded-lg border px-3 py-2">
              <dt className="text-xs text-muted-foreground">Current coverage threshold</dt>
              <dd className="text-lg font-semibold tabular-nums" aria-label="Current coverage threshold">{pct(data.current_pct)}</dd>
            </div>
            <div className="rounded-lg border px-3 py-2">
              <dt className="text-xs text-muted-foreground">Availability threshold (separate rule)</dt>
              <dd className="text-lg font-semibold tabular-nums text-muted-foreground">{pct(data.availability_threshold_pct)}</dd>
            </div>
          </dl>
        )}
        {done && <Alert className="border-emerald-200 bg-emerald-50/70" role="status"><CheckCircle2 className="text-emerald-700" /><AlertTitle>{done}</AlertTitle></Alert>}
        <form aria-label="Change coverage threshold" className="space-y-2 rounded-md border px-3 py-2"
          onSubmit={(e) => { e.preventDefault(); if (ready) void send(false); }}>
          <p className="text-xs font-semibold">Change the coverage threshold</p>
          <div className="grid gap-2 sm:grid-cols-4">
            <Field id="threshold-value" label="New value (%)" error={errors?.byField.value_pct ?? (value && !valid ? 'Give a percentage between 0 and 100.' : null)}>
              <Input id="threshold-value" type="number" min={0} max={100} step="0.01" value={value} onChange={(e) => edit(setValue)(e.target.value)} />
            </Field>
            <Field id="threshold-from" label="Effective from" error={errors?.byField.effective_from}>
              <Input id="threshold-from" type="date" value={effective} onChange={(e) => edit(setEffective)(e.target.value)} />
            </Field>
            <div className="sm:col-span-2">
              <Field id="threshold-reason" label="Reason (required)" error={errors?.byField.reason}>
                <Input id="threshold-reason" value={reason} onChange={(e) => edit(setReason)(e.target.value)} />
              </Field>
            </div>
          </div>
          {errors?.message && <p className="text-xs text-destructive" role="alert">{errors.message}</p>}
          {retroactive ? (
            <div role="alertdialog" aria-label="Confirm retroactive change" className="space-y-2 rounded-md border border-amber-300 bg-amber-50/70 px-3 py-2 text-xs">
              <p className="font-semibold">This change applies retroactively</p>
              <p>{retroactive}</p>
              <div className="flex gap-2">
                <Button type="button" size="sm" onClick={() => void send(true)} disabled={busy}>{busy && <Loader2 className="animate-spin" />} Yes, apply retroactively</Button>
                <Button type="button" size="sm" variant="ghost" onClick={() => setRetroactive(null)} disabled={busy}>Cancel</Button>
              </div>
            </div>
          ) : (
            <Button type="submit" size="sm" disabled={busy || !ready}>{busy && <Loader2 className="animate-spin" />} Save threshold</Button>
          )}
        </form>
        {data && (data.history.length === 0 ? <p className="text-xs text-muted-foreground">No changes recorded yet.</p> : (
          <div className="overflow-x-auto rounded-md border">
            <table className="w-full text-left text-xs" aria-label="Coverage threshold history">
              <caption className="sr-only">Coverage threshold history</caption>
              <thead className="bg-muted"><tr>{['Effective from', 'Value', 'Previous value', 'Changed by', 'Changed at', 'Reason'].map((h) => <th key={h} className="px-2.5 py-1.5 font-medium">{h}</th>)}</tr></thead>
              <tbody className="divide-y">
                {data.history.map((h, i) => (
                  <tr key={`${h.changed_at}-${i}`}>
                    <td className="px-2.5 py-1.5">{formatDate(h.effective_from)}</td>
                    <td className="px-2.5 py-1.5 tabular-nums">{pct(h.value_pct)}</td>
                    <td className="px-2.5 py-1.5 tabular-nums">{pct(h.previous_value_pct)}</td>
                    <td className="px-2.5 py-1.5">{h.changed_by ?? '—'}</td>
                    <td className="px-2.5 py-1.5">{formatDateTime(h.changed_at)}</td>
                    <td className="px-2.5 py-1.5">{h.reason}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ))}
      </CardContent>
    </Card>
  );
}
