import { CalendarRange, Database, RotateCcw, X } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Card } from '@/components/ui/card';
import { Input } from '@/components/ui/input';
import { Skeleton } from '@/components/ui/skeleton';
import { cn } from '@/lib/utils';
import { Field } from '../../../components/dashboard/FilterBar';
import { PopulationSelect } from '../../../components/PopulationSelect';
import { formatDate } from '../../../lib/format';
import type { KpiFilterOptions, KpiSummary } from '../types';
import type { MultiKey, useKpiFilters } from '../useKpiFilters';
import { MultiSelect } from './MultiSelect';

const project = (p: string) => (p === '4G Saturation' ? '4G' : p);
const FIELD_LABELS: Record<MultiKey, string> = {
  project: 'Project', circle: 'Circle', ci: 'CI / Cluster', ie: 'IE', site: 'Site', bucket: 'Bucket', final_bucket: 'Final Bucket',
};

/**
 * The All KPI's report header and filters in one card: the reporting period and data date on top, the filters in a
 * grid (CI/Cluster, IE and Site options follow the selected circles; the server cascades them), the active selections
 * as removable chips and Reset at the bottom. Filters apply as soon as they change, as before.
 */
export function KpiFilters({ f, options, summary, showFinalBucket }: {
  f: ReturnType<typeof useKpiFilters>; options: KpiFilterOptions; summary?: KpiSummary | null; showFinalBucket: boolean;
}) {
  const first = options.dates[0];
  const last = options.dates.at(-1);
  const labelOf = (key: MultiKey, v: string) => {
    if (key === 'project') return project(v);
    if (key === 'ci') return options.cis.find((c) => c.key === v)?.label ?? v.split('::')[1] ?? v;
    if (key === 'ie') return options.ies.find((i) => i.key === v)?.label ?? v.split('::')[2] ?? v;
    if (key === 'site') return options.sites.find((s) => s.key === v)?.label ?? v;
    if (key === 'bucket') return options.buckets.find((b) => b.key === v)?.label ?? v;
    return v;
  };
  const keys = (Object.keys(FIELD_LABELS) as MultiKey[]).filter((k) => k !== 'final_bucket' || showFinalBucket);
  const chips = keys.filter((k) => f.values[k].length);
  return (
    <Card className="gap-0 py-0 shadow-xs">
      <ReportStrip summary={summary} latest={last} />
      <div role="search" aria-label="All KPI's filters"
        className={cn('grid grid-cols-2 gap-x-3 gap-y-2.5 px-4 py-3 sm:grid-cols-3 lg:grid-cols-4 [&_input]:h-9', showFinalBucket ? 'xl:grid-cols-10' : 'xl:grid-cols-9')}>
        <Field id="kpi-from" label="From">
          <Input id="kpi-from" type="date" min={first} max={last} value={f.dateFrom || options.default_period?.start || ''} onChange={(e) => f.update({ date_from: e.target.value })} />
        </Field>
        <Field id="kpi-to" label="To">
          <Input id="kpi-to" type="date" min={first} max={last} value={f.dateTo || options.default_period?.end || ''} onChange={(e) => f.update({ date_to: e.target.value })} />
        </Field>
        <PopulationSelect id="kpi-population" className="w-auto" />
        <Field id="kpi-project" label="Project">
          <MultiSelect id="kpi-project" label="Project" allLabel="All projects" value={f.values.project} onChange={(v) => f.setMulti('project', v)}
            options={options.projects.map((p) => ({ key: p, label: project(p) }))} />
        </Field>
        <Field id="kpi-circle" label="Circle">
          <MultiSelect id="kpi-circle" label="Circle" allLabel="All circles" value={f.values.circle} onChange={(v) => f.setMulti('circle', v)}
            options={options.circles.map((c) => ({ key: c, label: c }))} />
        </Field>
        <Field id="kpi-ci" label="CI / Cluster">
          <MultiSelect id="kpi-ci" label="CI / Cluster" allLabel="All CIs" value={f.values.ci} onChange={(v) => f.setMulti('ci', v)}
            options={options.cis.map((c) => ({ key: c.key, label: `${c.label} · ${c.circle}` }))} />
        </Field>
        <Field id="kpi-ie" label="IE">
          <MultiSelect id="kpi-ie" label="IE" allLabel="All IEs" value={f.values.ie} onChange={(v) => f.setMulti('ie', v)}
            options={options.ies.map((i) => ({ key: i.key, label: `${i.label} · ${i.ci}` }))} />
        </Field>
        <Field id="kpi-site" label="Site ID / name">
          <MultiSelect id="kpi-site" label="Site" allLabel="All sites" value={f.values.site} onChange={(v) => f.setMulti('site', v)} options={options.sites} />
        </Field>
        <Field id="kpi-bucket" label="Availability bucket">
          <MultiSelect id="kpi-bucket" label="Availability bucket" allLabel="All buckets" value={f.values.bucket} onChange={(v) => f.setMulti('bucket', v)}
            options={options.buckets} />
        </Field>
        {showFinalBucket && (
          <Field id="kpi-final" label="RCA Final Bucket">
            <MultiSelect id="kpi-final" label="RCA Final Bucket" allLabel="All Final Buckets" value={f.values.final_bucket} onChange={(v) => f.setMulti('final_bucket', v)}
              options={options.final_buckets.map((b) => ({ key: b, label: b }))} />
          </Field>
        )}
      </div>
      <div className="flex flex-wrap items-center gap-1.5 border-t px-4 py-2">
        {(f.dateFrom || f.dateTo) && (
          <Chip field="Period" label={`${formatDate(f.dateFrom || options.default_period?.start)} – ${formatDate(f.dateTo || options.default_period?.end)}`}
            onRemove={() => f.update({ date_from: null, date_to: null })} />
        )}
        {chips.map((k) => {
          const v = f.values[k];
          return v.length > 3
            ? <Chip key={k} field={FIELD_LABELS[k]} label={`${v.length} selected`} onRemove={() => f.setMulti(k, [])} />
            : v.map((x) => <Chip key={`${k}-${x}`} field={FIELD_LABELS[k]} label={labelOf(k, x)} onRemove={() => f.setMulti(k, v.filter((y) => y !== x))} />);
        })}
        {!f.active && <span className="text-[11px] text-muted-foreground">No filters applied: all sites in your access scope, latest month to date.</span>}
        <Button type="button" variant="outline" size="sm" className="ml-auto h-8" disabled={!f.active} onClick={f.reset} aria-label="Reset filters">
          <RotateCcw /> Reset filters
        </Button>
      </div>
    </Card>
  );
}

/** Reporting period, the comparison period and the latest date with daily data (from the API; nothing estimated). */
function ReportStrip({ summary, latest }: { summary?: KpiSummary | null; latest?: string }) {
  const p = summary?.period;
  return (
    <div className="flex flex-wrap items-center gap-x-4 gap-y-1 rounded-t-xl border-b bg-muted/40 px-4 py-2 text-xs text-muted-foreground">
      <span className="inline-flex items-center gap-1.5">
        <CalendarRange className="size-3.5" aria-hidden="true" />Reporting period
        {p ? <span className="font-semibold text-foreground">{p.label}</span> : <Skeleton className="h-3.5 w-28" />}
      </span>
      {p?.days_in_period != null && <span className="tabular-nums">{p.days_with_data} of {p.days_in_period} days with daily data</span>}
      {summary?.previous_period && <span>Compared with <span className="font-medium text-foreground">{summary.previous_period.label}</span></span>}
      {latest && (
        <span className="inline-flex items-center gap-1.5 sm:ml-auto">
          <Database className="size-3.5" aria-hidden="true" />Daily data up to <span className="font-medium text-foreground">{formatDate(latest)}</span>
        </span>
      )}
    </div>
  );
}

function Chip({ field, label, onRemove }: { field: string; label: string; onRemove: () => void }) {
  return (
    <span className="inline-flex max-w-64 items-center gap-1 rounded-md border bg-background py-0.5 pr-0.5 pl-2 text-[11px]">
      <span className="text-muted-foreground">{field}:</span><span className="truncate font-medium">{label}</span>
      <button type="button" className="rounded p-0.5 text-muted-foreground hover:bg-muted hover:text-foreground" aria-label={`Remove ${field} ${label}`} onClick={onRemove}>
        <X className="size-3" aria-hidden="true" />
      </button>
    </span>
  );
}
