import { useState } from 'react';
import { CalendarRange, ChevronDown } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Popover, PopoverContent, PopoverTrigger } from '@/components/ui/popover';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import { cn } from '@/lib/utils';
import { WEEK_RANGES, type DashboardFilterState, type ResolvedFilters } from '../../hooks/useDashboardFilters';
import { formatDate, formatShortDate } from '../../lib/format';
import type { FilterOptions } from '../../types';

type Mode = 'range' | 'dates' | 'weeks' | 'months';

const MODES: { value: Mode; label: string }[] = [
  { value: 'range', label: 'Date range' },
  { value: 'dates', label: 'Specific dates' },
  { value: 'weeks', label: 'Weeks' },
  { value: 'months', label: 'Months' },
];

interface TrendPeriodPickerProps {
  id: string;
  options: FilterOptions;
  filters: ResolvedFilters;
  onChange: (changes: Partial<DashboardFilterState>) => void;
}

const currentMode = (filters: ResolvedFilters): Mode =>
  filters.trendView === 'monthly' ? 'months' : filters.trendView === 'weekly' ? 'weeks' : filters.dayList.length ? 'dates' : 'range';

/**
 * One control for the trend chart's period: a date range, hand-picked dates, workbook weeks, or months.
 * Choosing a kind of period also switches the chart to the matching view (daily, weekly or monthly).
 */
export function TrendPeriodPicker({ id, options, filters, onChange }: TrendPeriodPickerProps) {
  const [open, setOpen] = useState(false);
  const [mode, setMode] = useState<Mode>(currentMode(filters));
  const dates = options.reporting_dates;
  const monthOptions = options.months ?? [];
  const monthEnd = Number(options.month.end.slice(8, 10));
  const weekRanges = WEEK_RANGES.map((w) => ({ ...w, last: Math.min(w.last, monthEnd) }));
  const dayOf = (day: number) => `${options.month.start.slice(0, 8)}${String(day).padStart(2, '0')}`;

  const chooseMode = (next: Mode) => {
    setMode(next);
    // Switching the kind of period switches the chart view; existing selections are kept.
    if (next === 'range') onChange({ trend: '', days: '' });
    else if (next === 'dates') onChange({ trend: '' });
    else onChange({ trend: next === 'weeks' ? 'weekly' : 'monthly' });
  };

  const toggle = (current: string[], value: string) =>
    (current.includes(value) ? current.filter((v) => v !== value) : [...current, value]);

  return (
    <Popover open={open} onOpenChange={(next) => { setOpen(next); if (next) setMode(currentMode(filters)); }}>
      <PopoverTrigger asChild>
        <Button id={id} variant="outline" className="w-full justify-between font-normal">
          <span className="flex min-w-0 items-center gap-2">
            <CalendarRange className="size-4 shrink-0 text-muted-foreground" />
            <span className="truncate">{summary(filters, monthOptions)}</span>
          </span>
          <ChevronDown className="size-4 shrink-0 opacity-50" />
        </Button>
      </PopoverTrigger>
      <PopoverContent align="start" className="w-[22rem] p-0">
        <div className="grid grid-cols-4 gap-0.5 border-b p-1" role="tablist" aria-label="Kind of trend period">
          {MODES.map((m) => (
            <button
              key={m.value}
              type="button"
              role="tab"
              aria-selected={mode === m.value}
              onClick={() => chooseMode(m.value)}
              className={cn('rounded-md px-1.5 py-1.5 text-xs font-medium transition-colors focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none',
                mode === m.value ? 'bg-primary text-primary-foreground' : 'text-muted-foreground hover:bg-muted hover:text-foreground')}
            >
              {m.label}
            </button>
          ))}
        </div>

        <div className="space-y-3 p-3" role="tabpanel">
          {mode === 'range' && (
            <>
              <p className="text-xs text-muted-foreground">Daily uptime for every day in the range.</p>
              <div className="grid grid-cols-2 gap-2">
                <RangeSelect label="From" value={filters.from} dates={dates.filter((d) => !filters.to || d <= filters.to)}
                  onChange={(from) => onChange({ from, days: '', trend: '' })} />
                <RangeSelect label="To" value={filters.to} dates={dates.filter((d) => !filters.from || d >= filters.from)}
                  onChange={(to) => onChange({ to, days: '', trend: '' })} />
              </div>
              <Presets items={[
                { label: 'Last 7 days', onClick: () => onChange({ from: dates.at(-7) ?? dates[0], to: dates.at(-1) ?? '', days: '', trend: '' }) },
                { label: 'Month to date', onClick: () => onChange({ from: '', to: '', days: '', trend: '' }) },
              ]} />
            </>
          )}

          {mode === 'dates' && (
            <>
              <p className="text-xs text-muted-foreground">Pick any reported days of {options.month.label} to compare side by side.</p>
              <div className="grid grid-cols-7 gap-1" role="group" aria-label="Specific dates">
                {['M', 'T', 'W', 'T', 'F', 'S', 'S'].map((d, i) => (
                  <span key={i} className="text-center text-[10px] font-medium text-muted-foreground">{d}</span>
                ))}
                {Array.from({ length: (new Date(`${options.month.start}T00:00:00`).getDay() + 6) % 7 }, (_, i) => <span key={`pad-${i}`} />)}
                {Array.from({ length: monthEnd }, (_, i) => {
                  const day = dayOf(i + 1);
                  const available = dates.includes(day);
                  const selected = filters.dayList.includes(day);
                  return (
                    <button
                      key={day}
                      type="button"
                      disabled={!available}
                      aria-pressed={selected}
                      aria-label={`${formatDate(day)}${available ? '' : ' (not reported)'}`}
                      onClick={() => onChange({ days: toggle(filters.dayList, day).sort().join(','), trend: '' })}
                      className={cn('h-8 rounded-md text-xs tabular-nums transition-colors focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none',
                        selected ? 'bg-primary font-semibold text-primary-foreground'
                          : available ? 'hover:bg-muted' : 'cursor-not-allowed text-muted-foreground/40')}
                    >
                      {i + 1}
                    </button>
                  );
                })}
              </div>
              <Presets items={[
                { label: `Every ${weekdayName(dates.at(-1))}`, onClick: () => onChange({ days: dates.filter((d) => weekdayOf(d) === weekdayOf(dates.at(-1) ?? '')).join(','), trend: '' }) },
                { label: 'Week starts (1, 8, 15, 22)', onClick: () => onChange({ days: [1, 8, 15, 22].map(dayOf).filter((d) => dates.includes(d)).join(','), trend: '' }) },
                { label: 'Clear', onClick: () => onChange({ days: '', trend: '' }) },
              ]} />
              {!filters.dayList.length && <p className="text-xs text-muted-foreground">No dates picked: the date range is shown.</p>}
            </>
          )}

          {mode === 'weeks' && (
            <>
              <p className="text-xs text-muted-foreground">The workbook's weeks of {options.month.label}. Leave all unticked to compare every week.</p>
              <div className="grid grid-cols-2 gap-1.5" role="group" aria-label="Weeks">
                {weekRanges.map((w) => {
                  const selected = filters.weekList.includes(w.week);
                  const reported = dates.some((d) => Number(d.slice(8)) >= w.first && Number(d.slice(8)) <= w.last);
                  return (
                    <button
                      key={w.week}
                      type="button"
                      aria-pressed={selected}
                      onClick={() => onChange({ weeks: toggle(filters.weekList.map(String), String(w.week)).sort().join(','), trend: 'weekly' })}
                      className={cn('rounded-md border px-2.5 py-1.5 text-left text-xs transition-colors focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none',
                        selected ? 'border-primary bg-primary/10 font-semibold' : 'hover:bg-muted')}
                    >
                      Week {w.week}
                      <span className="block text-[11px] font-normal text-muted-foreground">
                        {formatShortDate(dayOf(w.first))}–{formatShortDate(dayOf(w.last))}{reported ? '' : ' · no data yet'}
                      </span>
                    </button>
                  );
                })}
              </div>
              <Presets items={[{ label: 'All weeks', onClick: () => onChange({ weeks: '', trend: 'weekly' }) }]} />
            </>
          )}

          {mode === 'months' && (
            <>
              <p className="text-xs text-muted-foreground">Monthly uptime. Pick any months, or leave all unticked for the full history.</p>
              <div className="grid grid-cols-4 gap-1" role="group" aria-label="Months">
                {monthOptions.map((m) => {
                  const selected = filters.monthList.includes(m.key);
                  return (
                    <button
                      key={m.key}
                      type="button"
                      aria-pressed={selected}
                      onClick={() => onChange({ months: monthOptions.map((o) => o.key).filter((k) => toggle(filters.monthList, m.key).includes(k)).join(','), trend: 'monthly' })}
                      className={cn('rounded-md border px-1 py-1.5 text-xs transition-colors focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none',
                        selected ? 'border-primary bg-primary/10 font-semibold' : 'hover:bg-muted')}
                    >
                      {m.label.replace(' MTD', '')}{m.label.endsWith('MTD') && <span className="block text-[10px] text-muted-foreground">MTD</span>}
                    </button>
                  );
                })}
              </div>
              <Presets items={[3, 6, 12].filter((n) => n < monthOptions.length).map((n) => ({
                label: `Last ${n}`, onClick: () => onChange({ months: monthOptions.slice(-n).map((m) => m.key).join(','), trend: 'monthly' }),
              })).concat([{ label: 'All months', onClick: () => onChange({ months: '', trend: 'monthly' }) }])} />
            </>
          )}
        </div>
        <div className="flex justify-end border-t px-3 py-2">
          <Button size="sm" onClick={() => setOpen(false)}>Done</Button>
        </div>
      </PopoverContent>
    </Popover>
  );
}

function summary(filters: ResolvedFilters, months: FilterOptions['months']) {
  if (filters.trendView === 'monthly') {
    if (!filters.monthList.length) return 'Months · all';
    const labels = months.filter((m) => filters.monthList.includes(m.key)).map((m) => m.label);
    if (labels.length <= 2) return `Months · ${labels.join(', ')}`;
    return `${labels.length} months · ${labels[0]}–${labels.at(-1)!.replace(' MTD', '')}`;
  }
  if (filters.trendView === 'weekly') {
    return filters.weekList.length ? `Weeks · ${filters.weekList.join(', ')}` : 'Weeks · all';
  }
  if (filters.dayList.length) {
    return filters.dayList.length <= 3
      ? `Dates · ${filters.dayList.map((d) => formatShortDate(d)).join(', ')}`
      : `Dates · ${filters.dayList.length} picked`;
  }
  return `${formatShortDate(filters.from)} – ${formatShortDate(filters.to)}`;
}

function RangeSelect({ label, value, dates, onChange }: { label: string; value: string; dates: string[]; onChange: (v: string) => void }) {
  return (
    <label className="flex flex-col gap-1 text-xs text-muted-foreground">
      {label}
      <Select value={value} onValueChange={onChange} disabled={!dates.length}>
        <SelectTrigger className="w-full" aria-label={`Trend ${label.toLowerCase()}`}><SelectValue placeholder="No dates" /></SelectTrigger>
        <SelectContent>
          {[...dates].reverse().map((d) => <SelectItem key={d} value={d}>{formatDate(d)}</SelectItem>)}
        </SelectContent>
      </Select>
    </label>
  );
}

function Presets({ items }: { items: { label: string; onClick: () => void }[] }) {
  return (
    <div className="flex flex-wrap gap-1.5">
      {items.map((item) => (
        <button key={item.label} type="button" onClick={item.onClick}
          className="rounded-full border px-2.5 py-0.5 text-[11px] text-muted-foreground transition-colors hover:bg-muted hover:text-foreground focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none">
          {item.label}
        </button>
      ))}
    </div>
  );
}

const weekdayOf = (iso: string) => new Date(`${iso}T00:00:00`).getDay();
const weekdayName = (iso: string | undefined) =>
  (iso ? new Intl.DateTimeFormat('en-IN', { weekday: 'long' }).format(new Date(`${iso}T00:00:00`)) : 'weekday');
