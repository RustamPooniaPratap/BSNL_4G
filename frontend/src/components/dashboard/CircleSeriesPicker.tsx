import { useState } from 'react';
import { ChevronDown, Search, X } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Popover, PopoverContent, PopoverTrigger } from '@/components/ui/popover';
import { MAX_CIRCLES, circleColor, circleLabel, shortType } from '../../lib/circleSeries';
import type { CircleSeriesInfo } from '../../types';

/**
 * Choose the circles drawn as separate lines: one by one, or a whole network (all 4G / all LWE).
 * Searchable; only circles in the current data are offered (e.g. LWE circles on the LWE page).
 * Beyond MAX_CIRCLES lines the chart gets busy, so a note points to the heatmap.
 */
export function CircleSeriesPicker({ available, selected, allKeys, onChange }: {
  available: CircleSeriesInfo[]; selected: string[]; allKeys: string[]; onChange: (keys: string[]) => void;
}) {
  const [query, setQuery] = useState('');
  const needle = query.trim().toLowerCase();
  const shown = available.filter((c) => !needle || circleLabel(c.key).toLowerCase().includes(needle) || c.report_type.toLowerCase().includes(needle));
  const types = [...new Set(shown.map((c) => c.report_type))];
  const order = available.map((c) => c.key);
  const set = (keys: Set<string>) => onChange(order.filter((k) => keys.has(k)));
  const toggle = (key: string) => {
    const next = new Set(selected);
    if (next.has(key)) next.delete(key); else next.add(key);
    set(next);
  };
  const typeKeys = (type: string) => available.filter((c) => c.report_type === type).map((c) => c.key);
  const toggleType = (type: string) => {
    const keys = typeKeys(type);
    const next = new Set(selected);
    const all = keys.every((k) => next.has(k));
    keys.forEach((k) => (all ? next.delete(k) : next.add(k)));
    set(next);
  };
  const allTypes = [...new Set(available.map((c) => c.report_type))];
  const wholeType = allTypes.find((t) => {
    const keys = typeKeys(t);
    return keys.length === selected.length && keys.every((k) => selected.includes(k));
  });
  const summary = !selected.length ? 'Choose circles' : selected.length === available.length && allTypes.length > 1 ? `All ${available.length} circles`
    : wholeType ? `All ${shortType(wholeType)} circles` : selected.length <= 2 ? selected.map(circleLabel).join(', ') : `${selected.length} circles`;

  return (
    <div className="flex flex-wrap items-center gap-2" role="group" aria-label="Circle comparison">
      <Popover onOpenChange={(open) => { if (!open) setQuery(''); }}>
        <PopoverTrigger asChild>
          <Button variant="outline" size="sm" className="h-8 min-w-40 justify-between font-normal" aria-label={`Compare circles: ${summary}`}>
            {summary} <ChevronDown className="text-muted-foreground" />
          </Button>
        </PopoverTrigger>
        <PopoverContent align="start" className="w-64 p-2">
          <div className="relative mb-1.5">
            <Search className="absolute top-1/2 left-2 size-3.5 -translate-y-1/2 text-muted-foreground" aria-hidden="true" />
            <Input value={query} onChange={(e) => setQuery(e.target.value)} placeholder="Search circles" aria-label="Search circles" className="h-8 pl-7 text-sm" />
          </div>
          <p className="mb-1 px-1 text-[11px] text-muted-foreground" aria-live="polite">{selected.length} of {available.length} selected</p>
          <div className="max-h-64 space-y-1.5 overflow-y-auto">
            {types.map((type) => (
              <fieldset key={type}>
                <legend className="w-full">
                  <TypeCheckbox label={`All ${shortType(type)} circles`} text={`All ${shortType(type)}`} keys={typeKeys(type)} selected={selected} onToggle={() => toggleType(type)} />
                </legend>
                {shown.filter((c) => c.report_type === type).map((c) => (
                  <label key={c.key} className="flex cursor-pointer items-center gap-2 rounded py-1 pr-1.5 pl-5 text-sm hover:bg-muted">
                    <input type="checkbox" className="size-3.5 accent-primary" checked={selected.includes(c.key)} onChange={() => toggle(c.key)} />
                    <span className="size-2.5 shrink-0 rounded-full" style={{ background: circleColor(c.key, allKeys) }} aria-hidden="true" />
                    <span className="flex-1">{circleLabel(c.key)}</span>
                    <span className="text-[11px] text-muted-foreground tabular-nums">{c.sites.toLocaleString('en-IN')} sites</span>
                  </label>
                ))}
              </fieldset>
            ))}
            {!shown.length && <p className="px-1 py-2 text-xs text-muted-foreground">No circle matches “{query}”.</p>}
          </div>
        </PopoverContent>
      </Popover>
      {selected.length > 0 && (
        <Button variant="ghost" size="sm" className="h-8 px-2 text-xs" onClick={() => onChange([])} aria-label="Clear circle selection">
          <X /> Clear
        </Button>
      )}
      {selected.length > MAX_CIRCLES && (
        <span className="text-[11px] text-muted-foreground">{selected.length} lines: the Heatmap view is easier to read for many circles.</span>
      )}
    </div>
  );
}

/** Network checkbox: ticked when all its circles are selected, partly ticked when some are. */
function TypeCheckbox({ label, text, keys, selected, onToggle }: {
  label: string; text: string; keys: string[]; selected: string[]; onToggle: () => void;
}) {
  const count = keys.filter((k) => selected.includes(k)).length;
  const all = count === keys.length && count > 0;
  return (
    <label className="flex cursor-pointer items-center gap-2 rounded px-1.5 py-1 hover:bg-muted">
      <input type="checkbox" className="size-3.5 accent-primary" aria-label={label} checked={all}
        ref={(el) => { if (el) el.indeterminate = count > 0 && !all; }} onChange={onToggle} />
      <span className="flex-1 text-[11px] font-semibold tracking-wider text-muted-foreground uppercase">{text}</span>
      <span className="text-[11px] text-muted-foreground tabular-nums">{count}/{keys.length}</span>
    </label>
  );
}
