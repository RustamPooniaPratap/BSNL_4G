import { useState, type ReactNode } from 'react';
import { CircleAlert, CircleCheck, Loader2, Search } from 'lucide-react';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { cn } from '@/lib/utils';
import type { Notice } from '../../hooks/useOrgList';
import { formatNumber } from '../../lib/format';
import type { OrgUsage } from '../../types/organization';

/** Building blocks shared by the Organization tabs (presentation and the save/reload cycle; the server validates). */

export function NoticeLine({ notice }: { notice: Notice }) {
  if (!notice) return null;
  const ok = notice.kind === 'ok';
  return (
    <p role={ok ? 'status' : 'alert'} className={cn('flex items-start gap-1.5 rounded-md border px-3 py-2 text-sm',
      ok ? 'border-emerald-200 bg-emerald-50 text-emerald-900' : 'border-destructive/30 bg-destructive/5 text-destructive')}>
      {ok ? <CircleCheck className="mt-0.5 size-4 shrink-0" aria-hidden="true" /> : <CircleAlert className="mt-0.5 size-4 shrink-0" aria-hidden="true" />}
      {notice.text}
    </p>
  );
}

export function ActiveBadge({ active, label }: { active: boolean; label?: string }) {
  return active
    ? <Badge variant="outline" className="border-emerald-300 text-emerald-800">{label ?? 'Active'}</Badge>
    : <Badge variant="outline" className="border-slate-300 text-slate-600">{label ? `${label} (inactive)` : 'Inactive'}</Badge>;
}

export function SearchBox({ id, value, onChange, placeholder }: { id: string; value: string; onChange: (v: string) => void; placeholder: string }) {
  return (
    <div className="relative w-full sm:w-64">
      <Search className="pointer-events-none absolute top-1/2 left-2.5 size-3.5 -translate-y-1/2 text-muted-foreground" aria-hidden="true" />
      <Input id={id} type="search" aria-label={placeholder} placeholder={placeholder} value={value} onChange={(e) => onChange(e.target.value)} className="h-8 pl-8 text-sm" />
    </div>
  );
}

/** Filter chips such as All / Active / Inactive. */
export function Chips<T extends string>({ label, value, options, onChange }: { label: string; value: T; options: [T, string][]; onChange: (v: T) => void }) {
  return (
    <div role="group" aria-label={label} className="inline-flex rounded-md border p-0.5">
      {options.map(([v, text]) => (
        <button key={v} type="button" aria-pressed={v === value} onClick={() => onChange(v)}
          className={cn('rounded px-2 py-0.5 text-xs font-medium', v === value ? 'bg-primary text-primary-foreground' : 'text-muted-foreground hover:bg-muted')}>
          {text}
        </button>
      ))}
    </div>
  );
}

/**
 * A button that asks before acting: the confirmation names the effect and takes an optional reason, recorded in the
 * change history.
 */
export function ConfirmAction({ label, title, effect, destructive = false, disabled, busy, onConfirm }: {
  label: string; title: string; effect: ReactNode; destructive?: boolean; disabled?: boolean; busy?: boolean;
  onConfirm: (reason: string) => Promise<unknown>;
}) {
  const [open, setOpen] = useState(false);
  const [reason, setReason] = useState('');
  if (!open) {
    return <Button type="button" size="sm" variant={destructive ? 'outline' : 'ghost'} className="h-7 px-2 text-xs" disabled={disabled}
      aria-label={title} onClick={() => { setReason(''); setOpen(true); }}>{label}</Button>;
  }
  return (
    <div role="alertdialog" aria-label={title} className="flex w-72 flex-col gap-2 rounded-md border bg-card p-2.5 text-left text-xs shadow-md">
      <p className="font-medium">{title}</p>
      <p className="text-muted-foreground">{effect}</p>
      <Input aria-label="Reason (optional)" placeholder="Reason (optional, kept in the history)" value={reason} onChange={(e) => setReason(e.target.value)} className="h-7 text-xs" />
      <div className="flex justify-end gap-1">
        <Button type="button" size="sm" variant="ghost" className="h-7 px-2 text-xs" onClick={() => setOpen(false)}>Cancel</Button>
        <Button type="button" size="sm" variant={destructive ? 'destructive' : 'default'} className="h-7 px-2 text-xs" disabled={busy}
          onClick={() => { void onConfirm(reason).then(() => setOpen(false)); }}>
          {busy && <Loader2 className="animate-spin" />}Confirm
        </Button>
      </div>
    </div>
  );
}

/** Stored records of a project/circle; "—" when none (never a made-up figure). */
export function UsageSummary({ usage }: { usage: OrgUsage }) {
  const parts: [number, string, string][] = [[usage.sites, 'site', 'sites'], [usage.daily, 'daily', 'daily'], [usage.monthly, 'monthly', 'monthly'],
    [usage.uploads, 'upload', 'uploads'], [usage.rca, 'RCA', 'RCA'], [usage.rca_expected ?? 0, 'expected RCA unit', 'expected RCA units'],
    [usage.escalation ?? 0, 'escalation site', 'escalation sites'], [usage.users, 'user', 'users']];
  const shown = parts.filter(([n]) => n > 0);
  if (!shown.length) return <span className="text-muted-foreground">No records</span>;
  return <span className="text-muted-foreground">{shown.map(([n, one, many]) => `${formatNumber(n)} ${n === 1 ? one : many}`).join(' · ')}</span>;
}
