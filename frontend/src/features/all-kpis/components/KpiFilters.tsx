import { RotateCcw, X } from 'lucide-react';
import { Input } from '@/components/ui/input';
import { PopulationSelect } from '../../../components/PopulationSelect';
import { formatDate } from '../../../lib/format';
import type { KpiFilterOptions } from '../types';
import type { MultiKey, useKpiFilters } from '../useKpiFilters';
import { MultiSelect } from './MultiSelect';

const project = (p: string) => (p === '4G Saturation' ? '4G' : p);
const FIELD_LABELS: Record<MultiKey, string> = {
  project: 'Project', circle: 'Circle', ci: 'CI / Cluster', ie: 'IE', site: 'Site', bucket: 'Bucket', final_bucket: 'Final Bucket',
};

/**
 * A labelled control of the filter bar: compact upper-case label above, a flexible width with a minimum, so every
 * filter fits in one row on desktop and the row wraps only when the screen is too narrow (no filter is ever hidden).
 */
function Field({ id, label, title, kind, children }: { id: string; label: string; title?: string; kind?: 'date'; children: React.ReactNode }) {
  return (
    <div className={kind === 'date' ? 'akp-f date' : 'akp-f'}>
      <label htmlFor={id} title={title}>{label}</label>
      {children}
    </div>
  );
}

/**
 * The All KPI's filter bar (sticky, reference style): period, population, Project → Circle → CI/Cluster → IE → Site
 * (the server cascades the options), availability bucket and, on the RCA view, the Final Bucket. The active selections
 * are removable chips. Filters apply as soon as they change and are kept in the URL, as before.
 */
export function KpiFilters({ f, options, showFinalBucket }: {
  f: ReturnType<typeof useKpiFilters>; options: KpiFilterOptions; showFinalBucket: boolean;
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
    <>
      <div role="search" aria-label="All KPI's filters" className="akp-fbar-in">
        <Field id="kpi-from" label="From" kind="date">
          <Input id="kpi-from" type="date" min={first} max={last} value={f.dateFrom || options.default_period?.start || ''} onChange={(e) => f.update({ date_from: e.target.value })} />
        </Field>
        <Field id="kpi-to" label="To" kind="date">
          <Input id="kpi-to" type="date" min={first} max={last} value={f.dateTo || options.default_period?.end || ''} onChange={(e) => f.update({ date_to: e.target.value })} />
        </Field>
        <div className="akp-f akp-pop">
          <PopulationSelect id="kpi-population" className="w-full" />
        </div>
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
        <Field id="kpi-site" label="Site" title="Site ID / name">
          <MultiSelect id="kpi-site" label="Site" allLabel="All sites" value={f.values.site} onChange={(v) => f.setMulti('site', v)} options={options.sites} />
        </Field>
        <Field id="kpi-bucket" label="Bucket" title="Availability bucket">
          <MultiSelect id="kpi-bucket" label="Availability bucket" allLabel="All buckets" value={f.values.bucket} onChange={(v) => f.setMulti('bucket', v)}
            options={options.buckets} />
        </Field>
        {showFinalBucket && (
          <Field id="kpi-final" label="Final Bucket" title="RCA Final Bucket">
            <MultiSelect id="kpi-final" label="RCA Final Bucket" allLabel="All Final Buckets" value={f.values.final_bucket} onChange={(v) => f.setMulti('final_bucket', v)}
              options={options.final_buckets.map((b) => ({ key: b, label: b }))} />
          </Field>
        )}
        <button type="button" className="akp-btn akp-reset" disabled={!f.active} onClick={f.reset} aria-label="Reset filters" title="Reset filters">
          <RotateCcw className="size-3.5" aria-hidden="true" />
        </button>
      </div>
      {f.active && <div className="akp-chips">
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
      </div>}
    </>
  );
}

function Chip({ field, label, onRemove }: { field: string; label: string; onRemove: () => void }) {
  return (
    <span className="akp-chip">
      <span className="k">{field}:</span><span className="truncate font-medium">{label}</span>
      <button type="button" aria-label={`Remove ${field} ${label}`} onClick={onRemove}><X className="size-3" aria-hidden="true" /></button>
    </span>
  );
}
