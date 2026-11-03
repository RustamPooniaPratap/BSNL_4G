import { RotateCcw } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Field, FilterCard } from '../../../components/dashboard/FilterBar';
import type { KpiFilterOptions } from '../types';
import type { useKpiFilters } from '../useKpiFilters';
import { MultiSelect } from './MultiSelect';

/** The All KPI's filters. CI/Cluster, IE and Site options follow the selected circles (the server cascades them). */
export function KpiFilters({ f, options, showFinalBucket }: { f: ReturnType<typeof useKpiFilters>; options: KpiFilterOptions; showFinalBucket: boolean }) {
  const first = options.dates[0];
  const last = options.dates.at(-1);
  return (
    <FilterCard label="All KPI's filters" actions={(
      <Button type="button" variant="ghost" size="icon" className="size-9" aria-label="Reset filters" title="Reset filters" disabled={!f.active} onClick={f.reset}><RotateCcw /></Button>
    )}>
      <Field id="kpi-from" label="From" className="w-36">
        <Input id="kpi-from" type="date" min={first} max={last} value={f.dateFrom || options.default_period?.start || ''} onChange={(e) => f.update({ date_from: e.target.value })} />
      </Field>
      <Field id="kpi-to" label="To" className="w-36">
        <Input id="kpi-to" type="date" min={first} max={last} value={f.dateTo || options.default_period?.end || ''} onChange={(e) => f.update({ date_to: e.target.value })} />
      </Field>
      <Field id="kpi-project" label="Project" className="w-auto">
        <MultiSelect id="kpi-project" label="Project" allLabel="All projects" width="w-36" value={f.values.project} onChange={(v) => f.setMulti('project', v)}
          options={options.projects.map((p) => ({ key: p, label: p === '4G Saturation' ? '4G' : p }))} />
      </Field>
      <Field id="kpi-circle" label="Circle" className="w-auto">
        <MultiSelect id="kpi-circle" label="Circle" allLabel="All circles" width="w-36" value={f.values.circle} onChange={(v) => f.setMulti('circle', v)}
          options={options.circles.map((c) => ({ key: c, label: c }))} />
      </Field>
      <Field id="kpi-ci" label="CI / Cluster" className="w-auto">
        <MultiSelect id="kpi-ci" label="CI / Cluster" allLabel="All CIs" value={f.values.ci} onChange={(v) => f.setMulti('ci', v)}
          options={options.cis.map((c) => ({ key: c.key, label: `${c.label} · ${c.circle}` }))} />
      </Field>
      <Field id="kpi-ie" label="IE" className="w-auto">
        <MultiSelect id="kpi-ie" label="IE" allLabel="All IEs" value={f.values.ie} onChange={(v) => f.setMulti('ie', v)}
          options={options.ies.map((i) => ({ key: i.key, label: `${i.label} · ${i.ci}` }))} />
      </Field>
      <Field id="kpi-site" label="Site ID / name" className="w-auto">
        <MultiSelect id="kpi-site" label="Site" allLabel="All sites" value={f.values.site} onChange={(v) => f.setMulti('site', v)} options={options.sites} />
      </Field>
      <Field id="kpi-bucket" label="Availability bucket" className="w-auto">
        <MultiSelect id="kpi-bucket" label="Availability bucket" allLabel="All buckets" value={f.values.bucket} onChange={(v) => f.setMulti('bucket', v)}
          options={options.buckets} />
      </Field>
      {showFinalBucket && (
        <Field id="kpi-final" label="RCA Final Bucket" className="w-auto">
          <MultiSelect id="kpi-final" label="RCA Final Bucket" allLabel="All Final Buckets" value={f.values.final_bucket} onChange={(v) => f.setMulti('final_bucket', v)}
            options={options.final_buckets.map((b) => ({ key: b, label: b }))} />
        </Field>
      )}
    </FilterCard>
  );
}
