import { useState } from 'react';
import { ChevronDown } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Popover, PopoverContent, PopoverTrigger } from '@/components/ui/popover';

/** A multi-value filter: "All" when nothing is chosen; a search box for long lists. */
export function MultiSelect({ id, label, options, value, onChange, allLabel = 'All', width = 'w-44' }: {
  id: string; label: string; options: { key: string; label: string }[]; value: string[]; onChange: (v: string[]) => void; allLabel?: string; width?: string;
}) {
  const [q, setQ] = useState('');
  const chosen = new Set(value);
  const shown = options.filter((o) => !q || o.label.toLowerCase().includes(q.toLowerCase())).slice(0, 300);
  const summary = !value.length ? allLabel : value.length === 1 ? (options.find((o) => o.key === value[0])?.label ?? value[0]) : `${value.length} selected`;
  return (
    <Popover>
      <PopoverTrigger asChild>
        <Button id={id} type="button" variant="outline" aria-label={`${label}: ${summary}`} className={`h-9 justify-between font-normal ${width}`}>
          <span className="truncate">{summary}</span><ChevronDown className="opacity-60" />
        </Button>
      </PopoverTrigger>
      <PopoverContent align="start" className="w-72 p-2 text-sm">
        {options.length > 10 && <Input aria-label={`Search ${label}`} placeholder="Search" value={q} onChange={(e) => setQ(e.target.value)} className="mb-2 h-8" />}
        <div className="mb-1 flex justify-between text-xs">
          <button type="button" className="font-medium text-primary" onClick={() => onChange([])}>{allLabel}</button>
          {value.length > 0 && <span className="text-muted-foreground">{value.length} selected</span>}
        </div>
        <ul className="max-h-64 overflow-y-auto" aria-label={`${label} options`}>
          {shown.map((o) => (
            <li key={o.key}>
              <label className="flex cursor-pointer items-center gap-2 rounded px-1 py-1 hover:bg-muted">
                <input type="checkbox" checked={chosen.has(o.key)} onChange={() => onChange(chosen.has(o.key) ? value.filter((v) => v !== o.key) : [...value, o.key])} />
                <span className="truncate">{o.label}</span>
              </label>
            </li>
          ))}
          {!shown.length && <li className="px-1 py-2 text-xs text-muted-foreground">No match.</li>}
          {options.length > shown.length && !q && <li className="px-1 py-1 text-xs text-muted-foreground">Type to search the other {options.length - shown.length}.</li>}
        </ul>
      </PopoverContent>
    </Popover>
  );
}
