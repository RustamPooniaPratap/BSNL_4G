import { useState } from 'react';
import { useSearchParams } from 'react-router-dom';
import { ChevronLeft, ChevronRight, Plus } from 'lucide-react';
import { Alert, AlertDescription } from '@/components/ui/alert';
import { Button } from '@/components/ui/button';
import { Card } from '@/components/ui/card';
import { Input } from '@/components/ui/input';
import { Sheet, SheetContent, SheetDescription, SheetHeader, SheetTitle } from '@/components/ui/sheet';
import { Skeleton } from '@/components/ui/skeleton';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table';
import { Field, SelectField } from '../../components/data/DataEntry';
import { RcaRecordSheet } from '../../components/rca/RcaRecordSheet';
import { Field as FilterField } from '../../components/dashboard/FilterBar';
import { RcaFilterBar, SourceValue, StatusBadge } from '../../components/rca/RcaShared';
import { PageHeading } from '../../context/pageHeader';
import { FILTER_KEYS, formatMin, rcaCoverageText, shortProject, type FilterKey } from '../../lib/rca';
import { useApiQuery } from '../../hooks/useApiQuery';
import { activeCirclesOf, useOrganization } from '../../hooks/useOrganization';
import { formatDate, formatNumber } from '../../lib/format';
import { createRcaRecord, fetchRcaOptions, fetchRcaRecords } from '../../services/api';
import type { RcaOptions, RcaRecordInput } from '../../types/rca';

const ORDERINGS = [
  { value: 'outage_desc', label: 'Largest outage first' }, { value: 'outage_asc', label: 'Smallest outage first' },
  { value: 'date_desc', label: 'Latest date first' }, { value: 'circle', label: 'By project and circle' }, { value: 'site', label: 'By Site ID' },
];
const PAGE_SIZE = 25;

/** Every RCA record, searchable and filtered; a row opens the record for review and follow-up. */
export function RcaRegisterPage() {
  const [params, setParams] = useSearchParams();
  const [version, setVersion] = useState(0);
  const [creating, setCreating] = useState(false);
  const options = useApiQuery(`rca-options-${version}`, (signal) => fetchRcaOptions(signal));
  const query = new URLSearchParams();
  for (const key of [...FILTER_KEYS, 'page', 'ordering']) {
    const v = params.get(key);
    if (v) query.set(key, v);
  }
  query.set('page_size', String(PAGE_SIZE));
  const records = useApiQuery(`rca-records-${query}-${version}`, (signal) => fetchRcaRecords(query, signal));
  const recordId = params.get('record') ? Number(params.get('record')) : null;

  const update = (changes: Record<string, string>, replace = true) => setParams((cur) => {
    const next = new URLSearchParams(cur);
    for (const [k, v] of Object.entries(changes)) {
      if (v) next.set(k, v); else next.delete(k);
    }
    return next;
  }, { replace });
  const onFilter = (key: FilterKey, value: string) => update({ [key]: value, page: '', ...(key === 'project' ? { circle: '' } : {}) });
  const page = records.data?.page ?? 1;

  return (
    <div className="space-y-4">
      <PageHeading title="RCA Register"
        subtitle={`${options.data ? rcaCoverageText(options.data.dates) : 'Loading'} · source fields (Final Bucket, Bucket - 2, RCA) shown as written`} />
      {options.error && <Alert variant="destructive"><AlertDescription>{options.error.message}</AlertDescription></Alert>}
      {options.data ? (
        <RcaFilterBar options={options.data} params={params} onChange={onFilter} search statusFilter
          onReset={() => setParams(new URLSearchParams(), { replace: true })}
          actions={(
            <>
              <FilterField id="rca-order" label="Sort" className="w-48">
                <SelectField id="rca-order" value={params.get('ordering') || 'outage_desc'} placeholder="Sort" options={ORDERINGS}
                  onChange={(v) => update({ ordering: v === 'outage_desc' ? '' : v, page: '' })} />
              </FilterField>
              <Button type="button" className="h-9" onClick={() => setCreating(true)}><Plus /> Record RCA</Button>
            </>
          )} />
      ) : !options.error && <Skeleton className="h-16 w-full" />}

      <Card className="gap-0 overflow-hidden rounded-xl py-0">
        <div className="flex items-center justify-between border-b px-4 py-3">
          <p className="text-sm font-medium" aria-live="polite">
            {records.data ? `${formatNumber(records.data.count)} RCA record${records.data.count === 1 ? '' : 's'}` : 'Loading records…'}
            {options.data && records.data && records.data.count !== options.data.total_records && <span className="font-normal text-muted-foreground"> of {formatNumber(options.data.total_records)}</span>}
          </p>
          {records.data && records.data.pages > 1 && <Pager page={page} pages={records.data.pages} onPage={(p) => update({ page: p > 1 ? String(p) : '' }, false)} />}
        </div>
        {records.error ? <Alert variant="destructive" className="m-4"><AlertDescription>{records.error.message}</AlertDescription></Alert>
          : !records.data ? <Skeleton className="m-4 h-80" />
            : records.data.count === 0 ? <p className="px-4 py-10 text-center text-sm text-muted-foreground">No RCA records match these filters.</p>
              : (
                <div className="overflow-x-auto">
                  <Table>
                    <TableHeader>
                      <TableRow>
                        {['Date', 'Site ID', 'Site name', 'Project', 'Circle', 'Outage', 'Final Bucket', 'Bucket - 2', 'RCA', 'Cause category', 'Follow-up'].map((h) => (
                          <TableHead key={h} className={h === 'Outage' ? 'text-right' : undefined}>{h}</TableHead>
                        ))}
                      </TableRow>
                    </TableHeader>
                    <TableBody>
                      {records.data.results.map((r) => (
                        <TableRow key={r.id} className="cursor-pointer" onClick={() => update({ record: String(r.id) }, false)}>
                          <TableCell className="whitespace-nowrap">{formatDate(r.reporting_date)}</TableCell>
                          <TableCell className="font-mono text-xs">
                            <button type="button" className="underline-offset-2 hover:underline focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none"
                              onClick={(e) => { e.stopPropagation(); update({ record: String(r.id) }, false); }}>{r.site_id}</button>
                          </TableCell>
                          <TableCell className="max-w-40 truncate" title={r.site_name}>{r.site_name || '—'}</TableCell>
                          <TableCell title={r.project_raw !== r.project ? `Source: ${r.project_raw}` : undefined}>{shortProject(r.project)}</TableCell>
                          <TableCell>{r.circle}</TableCell>
                          <TableCell className="text-right tabular-nums">{formatMin(r.outage_minutes)}</TableCell>
                          <TableCell><SourceValue value={r.final_bucket} unclassified={r.final_bucket_unclassified} /></TableCell>
                          <TableCell><SourceValue value={r.bucket_2} unclassified={r.bucket_2_unclassified} notApplicable={!r.rca_applicable} /></TableCell>
                          <TableCell className="max-w-72 truncate" title={r.rca_text}><SourceValue value={r.rca_text} unclassified={r.rca_unclassified} /></TableCell>
                          <TableCell>{r.category ? r.category.name : <span className="text-xs text-muted-foreground italic">Unreviewed</span>}</TableCell>
                          <TableCell><StatusBadge status={r.status} label={r.status_label} /></TableCell>
                        </TableRow>
                      ))}
                    </TableBody>
                  </Table>
                </div>
              )}
        {records.data && records.data.pages > 1 && (
          <div className="flex justify-end border-t px-4 py-2"><Pager page={page} pages={records.data.pages} onPage={(p) => update({ page: p > 1 ? String(p) : '' }, false)} /></div>
        )}
      </Card>

      <RcaRecordSheet recordId={recordId} onClose={() => update({ record: '' }, false)} onChanged={() => setVersion((v) => v + 1)} />
      {options.data && (
        <NewRecordSheet open={creating} options={options.data} onClose={() => setCreating(false)}
          onCreated={(id) => { setCreating(false); setVersion((v) => v + 1); update({ record: String(id) }, false); }} />
      )}
    </div>
  );
}

function Pager({ page, pages, onPage }: { page: number; pages: number; onPage: (p: number) => void }) {
  return (
    <nav className="flex items-center gap-2 text-xs" aria-label="Pages">
      <Button type="button" variant="outline" size="icon" className="size-7" aria-label="Previous page" disabled={page <= 1} onClick={() => onPage(page - 1)}><ChevronLeft /></Button>
      <span className="tabular-nums">Page {page} of {pages}</span>
      <Button type="button" variant="outline" size="icon" className="size-7" aria-label="Next page" disabled={page >= pages} onClick={() => onPage(page + 1)}><ChevronRight /></Button>
    </nav>
  );
}

/** Record a new RCA incident (a site may have several over time). Validated by the server like an import. */
function NewRecordSheet({ open, options, onClose, onCreated }: { open: boolean; options: RcaOptions; onClose: () => void; onCreated: (id: number) => void }) {
  const empty: RcaRecordInput = { reporting_date: '', project: '', circle: '', site_id: '', site_name: '', oa: '', ba: '', om_start_raw: '', outage_minutes: '', final_bucket: '', bucket_2: '', rca_text: '' };
  const [form, setForm] = useState<RcaRecordInput>(empty);
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [message, setMessage] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const set = (key: keyof RcaRecordInput, value: string) => setForm((f) => ({ ...f, [key]: value }));
  // Active projects, and the active circles of the chosen project (Administration > Organization).
  const catalog = useOrganization();
  const projects = (catalog.data?.projects ?? []).filter((p) => p.is_active);
  const circles = activeCirclesOf(catalog.data, form.project);
  const known = (list: { value: string; label: string; unclassified?: boolean }[]) => list.filter((o) => !o.unclassified).map((o) => o.label);

  async function submit() {
    setSaving(true);
    setErrors({});
    setMessage(null);
    try {
      const created = await createRcaRecord({ ...form, outage_minutes: form.outage_minutes === '' ? null : form.outage_minutes });
      setForm(empty);
      onCreated(created.id);
    } catch (e) {
      const details = (e as { details?: Record<string, unknown> }).details ?? {};
      setErrors(Object.fromEntries(Object.entries(details).map(([k, v]) => [k, Array.isArray(v) ? String(v[0]) : String(v)])));
      setMessage(e instanceof Error ? e.message : String(e));
    } finally {
      setSaving(false);
    }
  }
  const text = (key: keyof RcaRecordInput, label: string, required = false, list?: string) => (
    <Field id={`new-${key}`} label={label} required={required} error={errors[key]}>
      <Input id={`new-${key}`} value={String(form[key] ?? '')} onChange={(e) => set(key, e.target.value)} list={list} />
    </Field>
  );
  return (
    <Sheet open={open} onOpenChange={(o) => { if (!o) onClose(); }}>
      <SheetContent className="w-full overflow-y-auto sm:max-w-lg">
        <SheetHeader>
          <SheetTitle>Record an RCA</SheetTitle>
          <SheetDescription>A new incident for a site. Use the same labels as the RCA workbook where they apply.</SheetDescription>
        </SheetHeader>
        <div className="grid gap-3 px-4 pb-6 sm:grid-cols-2">
          <Field id="new-reporting_date" label="Reporting date" required error={errors.reporting_date}>
            <Input id="new-reporting_date" type="date" value={form.reporting_date} onChange={(e) => set('reporting_date', e.target.value)} />
          </Field>
          <Field id="new-project" label="Project" required error={errors.project}>
            <SelectField id="new-project" value={form.project} placeholder="Choose" onChange={(v) => setForm((f) => ({ ...f, project: v, circle: '' }))} options={projects.map((p) => ({ value: p.key, label: p.name }))} />
          </Field>
          <Field id="new-circle" label="Circle" required error={errors.circle}>
            <SelectField id="new-circle" value={form.circle} placeholder={form.project ? 'Choose' : 'Choose the project first'} disabled={!circles.length} onChange={(v) => set('circle', v)} options={circles.map((c) => ({ value: c, label: c }))} />
          </Field>
          {text('site_id', 'Site ID', true)}
          {text('site_name', 'Site name')}
          {text('oa', 'OA')}
          {text('ba', 'BA')}
          <Field id="new-om" label="O&M Start" error={errors.om_start_raw}>
            <SelectField id="new-om" value={form.om_start_raw ?? ''} placeholder="Not recorded" onChange={(v) => set('om_start_raw', v)} options={[{ value: 'Yes', label: 'Yes' }, { value: 'No', label: 'No' }]} />
          </Field>
          <Field id="new-outage_minutes" label="Outage minutes" error={errors.outage_minutes} hint="Leave blank if not known (not 0).">
            <Input id="new-outage_minutes" type="number" min={0} step="any" value={String(form.outage_minutes ?? '')} onChange={(e) => set('outage_minutes', e.target.value)} />
          </Field>
          {text('final_bucket', 'Final Bucket', false, 'rca-final-buckets')}
          {text('bucket_2', 'Bucket - 2', false, 'rca-bucket-2')}
          <datalist id="rca-final-buckets">{known(options.final_buckets).map((v) => <option key={v} value={v} />)}</datalist>
          <datalist id="rca-bucket-2">{known(options.bucket_2).map((v) => <option key={v} value={v} />)}</datalist>
          <Field id="new-rca_text" label="RCA description" required error={errors.rca_text} className="sm:col-span-2">
            <textarea id="new-rca_text" className="min-h-20 w-full rounded-md border bg-transparent px-3 py-2 text-sm shadow-xs" value={form.rca_text} onChange={(e) => set('rca_text', e.target.value)} />
          </Field>
          <div className="flex items-center gap-3 sm:col-span-2">
            <Button type="button" onClick={submit} disabled={saving}>{saving ? 'Saving…' : 'Save RCA'}</Button>
            <Button type="button" variant="ghost" onClick={onClose}>Cancel</Button>
            {message && <span className="text-xs text-destructive" role="alert">{message}</span>}
          </div>
        </div>
      </SheetContent>
    </Sheet>
  );
}
