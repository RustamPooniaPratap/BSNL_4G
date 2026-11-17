import type { ReactNode } from 'react';
import { RotateCcw, Search } from 'lucide-react';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { cn } from '@/lib/utils';
import { SelectField } from '../data/DataEntry';
import { Field, FilterCard } from '../dashboard/FilterBar';
import { ALL, FILTER_KEYS, NOT_RECORDED, SITE_SCOPES, type FilterKey } from '../../lib/rca';
import { approvedSubBuckets } from '../../lib/rcaTaxonomy';
import type { RcaCycleCode, RcaOptions, RcaStatus, RcaUnitCode } from '../../types/rca';
import { PopulationSelect } from '../PopulationSelect';

const CYCLE_TONE: Record<RcaCycleCode | RcaUnitCode, string> = {
  unconfigured: 'border-slate-300 bg-slate-50 text-slate-700',
  awaiting: 'border-slate-300 bg-slate-50 text-slate-700',
  pending: 'border-amber-300 bg-amber-50 text-amber-800',
  review: 'border-amber-300 bg-amber-50 text-amber-800',
  partial: 'border-sky-300 bg-sky-50 text-sky-800',
  ready: 'border-violet-300 bg-violet-50 text-violet-800',
  received: 'border-emerald-300 bg-emerald-50 text-emerald-800',
  final: 'border-emerald-300 bg-emerald-50 text-emerald-800',
  revised: 'border-orange-300 bg-orange-50 text-orange-800',
};

/** Status of a reporting period or of one expected project / circle, as computed by the API. */
export function CycleBadge({ code, label }: { code: RcaCycleCode | RcaUnitCode; label: string }) {
  return <Badge variant="outline" className={cn('font-medium', CYCLE_TONE[code])}>{label}</Badge>;
}

const STATUS_TONE: Record<RcaStatus, string> = {
  investigation: 'border-sky-200 bg-sky-50 text-sky-800',
  rca_review: 'border-violet-200 bg-violet-50 text-violet-800',
  action_pending: 'border-amber-200 bg-amber-50 text-amber-800',
  action_completed: 'border-emerald-200 bg-emerald-50 text-emerald-800',
  closed: 'border-slate-300 bg-slate-100 text-slate-800',
};

export function StatusBadge({ status, label }: { status: RcaStatus | null; label: string | null }) {
  if (!status) return <span className="text-xs text-muted-foreground italic">{NOT_RECORDED}</span>;
  return <Badge variant="outline" className={cn('font-medium', STATUS_TONE[status])}>{label}</Badge>;
}

/** A source value, with blank or "-" shown as unclassified (the value itself is kept as written). */
export function SourceValue({ value, unclassified, notApplicable }: { value: string; unclassified: boolean; notApplicable?: boolean }) {
  if (!unclassified) return <>{value}</>;
  // A blank cause field of an Other Media record is expected (RCA not applicable), not missing information.
  if (notApplicable) return <span className="text-muted-foreground" title={`Source value: "${value || 'blank'}". RCA is not applicable to Other Media.`}>{value || '—'} <span className="text-[10px]">(not applicable)</span></span>;
  return <span className="text-muted-foreground italic" title={`Source value: "${value || 'blank'}"`}>Unclassified{value ? ` (${value})` : ''}</span>;
}

/** The Sub Bucket filter offers the approved Sub Buckets of the chosen Final Bucket (all of them when none is chosen). */
const subBucketOptions = (options: RcaOptions, finalBucket: string) => {
  const final = options.final_buckets.find((o) => o.value === finalBucket)?.label;
  if (!final) return options.bucket_2;
  // In the chosen Final Bucket's own taxonomy order, then the blank choice.
  const byLabel = new Map(options.bucket_2.map((o) => [o.label, o]));
  return [...approvedSubBuckets(options, final).flatMap((label) => byLabel.get(label) ?? []), ...options.bucket_2.filter((o) => o.unclassified)];
};

/** The RCA filters, in the same compact filter card and label style as the dashboard pages. */
export function RcaFilterBar({ options, params, onChange, onReset, search = false, statusFilter = false, population = false, actions, lead }: {
  options: RcaOptions; params: URLSearchParams; onChange: (key: FilterKey, value: string, extra?: Partial<Record<FilterKey, string>>) => void; onReset: () => void;
  search?: boolean; statusFilter?: boolean; actions?: ReactNode;
  /** The global population selector (RCA Summary: its site metrics). With it, the Site Scope record filter is not shown. */
  population?: boolean;
  /** Page-specific controls placed before the shared filters (e.g. a reporting-date selector). */
  lead?: ReactNode;
}) {
  const get = (k: FilterKey) => params.get(k) ?? '';
  const project = get('project');
  const circles = options.circles.filter((c) => !project || c.project === project);
  const select = (key: FilterKey, label: string, all: string, items: { value: string; label: string }[], width = 'w-40') => (
    <Field id={`rca-${key}`} label={label} className={width}>
      <SelectField id={`rca-${key}`} value={get(key) || ALL} placeholder={all} onChange={(v) => change(key, v === ALL ? '' : v)}
        options={[{ value: ALL, label: all }, ...items]} />
    </Field>
  );
  // A new Final Bucket clears a chosen Bucket - 2 that is not one of its approved Sub Buckets (one URL update).
  const change = (key: FilterKey, value: string) => {
    const sub = get('bucket_2');
    if (key === 'final_bucket' && sub && !subBucketOptions(options, value).some((o) => o.value === sub)) {
      onChange(key, value, { bucket_2: '' });
    } else onChange(key, value);
  };
  const dates = options.dates;
  const active = FILTER_KEYS.some((k) => get(k) && !(population && k === 'site_scope'));
  return (
    <FilterCard label="RCA filters" actions={actions}>
      {lead}
      {search && (
        <Field id="rca-q" label="Search" className="w-60">
          <div className="relative">
            <Search className="absolute top-1/2 left-2.5 size-4 -translate-y-1/2 text-muted-foreground" aria-hidden="true" />
            <Input id="rca-q" value={get('q')} onChange={(e) => onChange('q', e.target.value)} placeholder="Site ID, name, OA, BA or RCA text" className="h-9 pl-8" />
          </div>
        </Field>
      )}
      <Field id="rca-date-from" label="From" className="w-36">
        <Input id="rca-date-from" type="date" className="h-9" value={get('date_from')} min={dates[0]} max={dates.at(-1)} onChange={(e) => onChange('date_from', e.target.value)} />
      </Field>
      <Field id="rca-date-to" label="To" className="w-36">
        <Input id="rca-date-to" type="date" className="h-9" value={get('date_to')} min={dates[0]} max={dates.at(-1)} onChange={(e) => onChange('date_to', e.target.value)} />
      </Field>
      {select('project', 'Project', 'All projects', options.projects.map((p) => ({ value: p, label: p })), 'w-36')}
      {select('circle', 'Circle', 'All circles', [...new Map(circles.map((c) => [c.circle, c])).values()]
        .map((c) => ({ value: c.circle, label: `${c.circle} · ${c.circle_raw}` })), 'w-44')}
      {/* RCA Summary: Population is the one site control (no Site Scope record filter); the RCA Register keeps Site Scope. */}
      {!population && <SiteScopeField value={get('site_scope')} onChange={(v) => onChange('site_scope', v)} />}
      {population && <PopulationSelect id="rca-population" />}
      {select('final_bucket', 'Final Bucket', 'All Final Buckets', options.final_buckets, 'w-44')}
      {select('responsibility', 'Responsibility', 'All responsibilities', options.responsibilities, 'w-44')}
      {select('bucket_2', 'Bucket - 2', 'All Bucket - 2', subBucketOptions(options, get('final_bucket')), 'w-44')}
      {select('category', 'Cause category', 'All categories', [
        ...options.categories, { value: 'unreviewed', label: 'Unreviewed descriptions' },
      ], 'w-48')}
      {select('rca', 'RCA applicability', 'All records', [
        { value: 'required', label: 'RCA required' }, { value: 'missing', label: 'RCA Required — Missing Information' },
        { value: 'not_applicable', label: 'Other Media — RCA Not Applicable' },
      ], 'w-56')}
      {statusFilter && select('status', 'Follow-up status', 'All statuses', [...options.statuses, { value: 'not_recorded', label: NOT_RECORDED }], 'w-44')}
      <Button type="button" variant="ghost" size="icon" className="size-9" aria-label="Reset filters" title="Reset filters" disabled={!active} onClick={onReset}>
        <RotateCcw />
      </Button>
    </FilterCard>
  );
}

/**
 * Site Scope of the RCA pages: All Sites (default), O&M Start Sites or O&M Not Started Sites. The same control on every
 * RCA page; the server applies it to every figure (KPIs, tables, charts, totals). ``''`` means All Sites.
 */
export function SiteScopeField({ value, onChange, id = 'rca-site-scope' }: { value: string; onChange: (value: string) => void; id?: string }) {
  return (
    <Field id={id} label="Site Scope" className="w-48">
      <SelectField id={id} value={value || 'all'} placeholder="All Sites" onChange={(v) => onChange(v === 'all' ? '' : v)}
        options={SITE_SCOPES.map((s) => ({ value: s.value, label: s.label }))} />
    </Field>
  );
}

export interface BarRow {
  key: string;
  label: string;
  value: number | null;
  display: string;
  note?: string;
  muted?: boolean;
  title?: string;
}

/** Ranked horizontal bars (largest first, as given), each with its value; muted rows are unclassified. */
export function RankedBars({ rows, label, color = 'var(--chart-1)', onSelect }: {
  rows: BarRow[]; label: string; color?: string; onSelect?: (key: string) => void;
}) {
  const max = Math.max(1, ...rows.map((r) => r.value ?? 0));
  return (
    <ol className="space-y-1" aria-label={label}>
      {rows.map((r) => {
        const body = (
          <>
            <span className={cn('truncate text-left text-xs', r.muted ? 'text-muted-foreground italic' : 'font-medium')}>{r.label}</span>
            <span className="relative h-3.5 rounded-sm bg-muted/60">
              {r.value != null && r.value > 0 && (
                <span className="absolute inset-y-0 left-0 rounded-sm" style={{ width: `${(100 * r.value) / max}%`, background: r.muted ? 'var(--muted-foreground)' : color, opacity: r.muted ? 0.45 : 1 }} />
              )}
            </span>
            <span className="text-right text-xs tabular-nums">{r.display}{r.note && <span className="ml-1 text-[10px] text-muted-foreground">{r.note}</span>}</span>
          </>
        );
        const cls = 'grid w-full grid-cols-[minmax(0,11rem)_1fr_minmax(5.5rem,auto)] items-center gap-2 rounded px-1 py-0.5';
        return (
          <li key={r.key} title={r.title}>
            {onSelect ? (
              <button type="button" className={cn(cls, 'hover:bg-muted/60 focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none')} onClick={() => onSelect(r.key)}>{body}</button>
            ) : <div className={cls}>{body}</div>}
          </li>
        );
      })}
    </ol>
  );
}

export function Segmented<T extends string>({ value, onChange, options, label }: { value: T; onChange: (v: T) => void; options: [T, string][]; label: string }) {
  return (
    <div className="inline-flex rounded-lg border p-0.5" role="group" aria-label={label}>
      {options.map(([v, text]) => (
        <button key={v} type="button" aria-pressed={value === v} onClick={() => onChange(v)}
          className={cn('rounded-md px-2.5 py-1 text-xs font-medium', value === v ? 'bg-primary text-primary-foreground' : 'text-muted-foreground hover:text-foreground')}>
          {text}
        </button>
      ))}
    </div>
  );
}
