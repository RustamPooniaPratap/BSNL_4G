import { useState } from 'react';
import { Search } from 'lucide-react';
import { Alert, AlertDescription } from '@/components/ui/alert';
import { Button } from '@/components/ui/button';
import { Card } from '@/components/ui/card';
import { PageHeading } from '../../context/pageHeader';
import { Input } from '@/components/ui/input';
import { Skeleton } from '@/components/ui/skeleton';
import { Field, SelectField } from '../../components/data/DataEntry';
import { Segmented } from '../../components/rca/RcaShared';
import { formatMin } from '../../lib/rca';
import { useApiQuery } from '../../hooks/useApiQuery';
import { formatNumber } from '../../lib/format';
import { createRcaCategory, fetchRcaCauses, mapRcaCauses, unmapRcaCauses } from '../../services/api';
import type { RcaCauseItem, RcaCauses } from '../../types/rca';

const NEW = '__new__';

/**
 * Admin review of RCA descriptions: map selected descriptions to a canonical cause category.
 * Only the descriptions an Admin selects are mapped; similar spellings are never merged automatically,
 * and the source RCA text is not changed.
 */
export function RcaMappingPage() {
  const [version, setVersion] = useState(0);
  const loaded = useApiQuery(`rca-causes-${version}`, (signal) => fetchRcaCauses(signal));
  const [override, setOverride] = useState<RcaCauses | null>(null);
  const data = override ?? loaded.data;
  const [tab, setTab] = useState<'queue' | 'mapped'>('queue');
  const [query, setQuery] = useState('');
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [category, setCategory] = useState('');
  const [newName, setNewName] = useState('');
  const [message, setMessage] = useState<{ tone: 'ok' | 'error'; text: string } | null>(null);
  const [busy, setBusy] = useState(false);

  const list = (tab === 'queue' ? data?.queue : data?.mapped) ?? [];
  const needle = query.trim().toLowerCase();
  const shown = list.filter((i) => !needle || i.spellings.some((t) => t.toLowerCase().includes(needle)) || i.category?.name.toLowerCase().includes(needle));
  const toggle = (key: string) => setSelected((cur) => { const next = new Set(cur); if (next.has(key)) next.delete(key); else next.add(key); return next; });
  const selectedRecords = list.filter((i) => selected.has(i.key)).reduce((a, i) => a + i.records, 0);

  async function run(action: () => Promise<RcaCauses>, done: string) {
    setBusy(true);
    setMessage(null);
    try {
      setOverride(await action());
      setSelected(new Set());
      setMessage({ tone: 'ok', text: done });
    } catch (e) {
      setMessage({ tone: 'error', text: e instanceof Error ? e.message : String(e) });
    } finally {
      setBusy(false);
    }
  }
  const approve = () => run(async () => {
    let id = Number(category);
    if (category === NEW) {
      const created = await createRcaCategory(newName.trim());
      id = created.id;
      setCategory(String(id));
      setNewName('');
    }
    return mapRcaCauses([...selected], id);
  }, `Mapped ${selected.size} description${selected.size === 1 ? '' : 's'} (${formatNumber(selectedRecords)} records).`);
  const unmap = () => run(() => unmapRcaCauses([...selected]), `Returned ${selected.size} description${selected.size === 1 ? '' : 's'} to the review queue.`);

  return (
    <div className="space-y-3">
      <PageHeading title="RCA Cause Mapping"
        subtitle="Only the selected descriptions are mapped; similar spellings are never merged automatically and the RCA text is kept unchanged" />
      {data && (
      <Card className="gap-0 rounded-xl px-4 py-2.5 shadow-xs">
          <dl className="flex flex-wrap gap-x-6 gap-y-1 text-sm">
            <div><dt className="inline text-muted-foreground">Reviewed descriptions: </dt><dd className="inline font-semibold">{formatNumber(data.stats.mapped_descriptions)} of {formatNumber(data.stats.descriptions)}</dd></div>
            <div><dt className="inline text-muted-foreground">Records covered: </dt><dd className="inline font-semibold">{formatNumber(data.stats.mapped_records)} of {formatNumber(data.stats.records)}</dd></div>
            <div><dt className="inline text-muted-foreground">Categories: </dt><dd className="inline font-semibold">{formatNumber(data.categories.length)}</dd></div>
            {data.stats.no_description_records > 0 && <div><dt className="inline text-muted-foreground">Records without a description: </dt><dd className="inline font-semibold">{formatNumber(data.stats.no_description_records)}</dd></div>}
          </dl>
      </Card>
      )}

      {loaded.error && !override && <Alert variant="destructive"><AlertDescription>{loaded.error.message}</AlertDescription></Alert>}
      {!data && !loaded.error && <Skeleton className="h-96 w-full" />}
      {data && (
        <Card className="gap-3 rounded-xl px-4 py-3">
          <div className="flex flex-wrap items-end gap-3">
            <Segmented label="List" value={tab} onChange={(t) => { setTab(t); setSelected(new Set()); }}
              options={[['queue', `Review queue (${data.queue.length})`], ['mapped', `Mapped (${data.mapped.length})`]]} />
            <div className="relative w-72">
              <Search className="absolute top-1/2 left-2.5 size-4 -translate-y-1/2 text-muted-foreground" aria-hidden="true" />
              <Input value={query} onChange={(e) => setQuery(e.target.value)} placeholder="Search descriptions" aria-label="Search descriptions" className="pl-8" />
            </div>
            <Button type="button" variant="ghost" size="sm" onClick={() => setSelected(new Set(shown.map((i) => i.key)))} disabled={!shown.length}>Select shown ({shown.length})</Button>
            <Button type="button" variant="ghost" size="sm" onClick={() => setSelected(new Set())} disabled={!selected.size}>Clear selection</Button>
            <Button type="button" variant="ghost" size="sm" onClick={() => { setOverride(null); setVersion((v) => v + 1); }}>Refresh</Button>
          </div>

          <div className="flex flex-wrap items-end gap-3 rounded-lg border bg-muted/30 px-3 py-2.5">
            <p className="text-sm"><span className="font-semibold">{selected.size}</span> selected <span className="text-muted-foreground">({formatNumber(selectedRecords)} records)</span></p>
            {tab === 'queue' ? (
              <>
                <Field id="map-category" label="Category" plain className="w-60">
                  <SelectField id="map-category" value={category} placeholder="Choose a category" onChange={setCategory}
                    options={[...data.categories.map((c) => ({ value: String(c.id), label: `${c.name} (${c.descriptions})` })), { value: NEW, label: '+ New category…' }]} />
                </Field>
                {category === NEW && (
                  <Field id="map-new" label="New category name" plain className="w-60">
                    <Input id="map-new" value={newName} onChange={(e) => setNewName(e.target.value)} placeholder="e.g. Media fluctuation" />
                  </Field>
                )}
                <Button type="button" size="sm" disabled={busy || !selected.size || !category || (category === NEW && !newName.trim())} onClick={approve}>Approve mapping</Button>
              </>
            ) : (
              <Button type="button" size="sm" variant="outline" disabled={busy || !selected.size} onClick={unmap}>Return to review queue</Button>
            )}
            {message && <span className={message.tone === 'ok' ? 'text-xs text-emerald-700' : 'text-xs text-destructive'} role="status">{message.text}</span>}
          </div>

          {shown.length === 0 ? <p className="py-8 text-center text-sm text-muted-foreground">{tab === 'queue' ? 'No unmapped descriptions match.' : 'No mapped descriptions yet.'}</p> : (
            <ul className="divide-y rounded-lg border" aria-label={tab === 'queue' ? 'Unmapped RCA descriptions' : 'Mapped RCA descriptions'}>
              {shown.map((item) => <CauseRow key={item.key} item={item} checked={selected.has(item.key)} onToggle={() => toggle(item.key)} />)}
            </ul>
          )}
        </Card>
      )}
    </div>
  );
}

function CauseRow({ item, checked, onToggle }: { item: RcaCauseItem; checked: boolean; onToggle: () => void }) {
  return (
    <li>
      <label className="flex cursor-pointer items-start gap-3 px-3 py-2 hover:bg-muted/40">
        <input type="checkbox" className="mt-1 size-4 accent-primary" checked={checked} onChange={onToggle} aria-label={`Select "${item.text}"`} />
        <span className="min-w-0 flex-1">
          <span className="block text-sm break-words">{item.text}</span>
          {item.spellings.length > 1 && <span className="block text-[11px] text-muted-foreground">Also written: {item.spellings.filter((t) => t !== item.text).map((t) => `“${t}”`).join(', ')}</span>}
          {item.category && (
            <span className="block text-[11px] text-emerald-700">→ {item.category.name}{item.reviewed_by ? ` · approved by ${item.reviewed_by}` : ''}</span>
          )}
        </span>
        <span className="shrink-0 text-right text-xs tabular-nums">
          <span className="block font-semibold">{formatNumber(item.records)} records</span>
          <span className="block text-muted-foreground">{formatMin(item.outage_minutes)}</span>
        </span>
      </label>
    </li>
  );
}
