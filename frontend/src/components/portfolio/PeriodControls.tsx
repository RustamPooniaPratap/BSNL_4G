import { useState, type ReactNode } from 'react';
import { CalendarDays, ChevronLeft, ChevronRight, CircleAlert } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Card } from '@/components/ui/card';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Popover, PopoverContent, PopoverTrigger } from '@/components/ui/popover';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import { cn } from '@/lib/utils';
import {
  GRANULARITIES, formatDate, monthLabel, nextDate, previousDate, shiftWeek, weekPeriod, weeksAvailable,
  type Availability, type Period, type PeriodChange, type PeriodSelection,
} from '../../lib/periods';

const MONTH_NAMES = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];

function Segmented<T extends string>({ value, options, onChange, label, disabled }: {
  value: T; options: [T, string][]; onChange: (v: T) => void; label: string; disabled?: Partial<Record<T, string>>;
}) {
  return (
    <div className="inline-flex h-9 rounded-lg border bg-muted/40 p-0.5" role="group" aria-label={label}>
      {options.map(([v, text]) => (
        <button key={v} type="button" aria-pressed={value === v} disabled={Boolean(disabled?.[v])} title={disabled?.[v]}
          onClick={() => onChange(v)}
          className={cn('rounded-md px-3 text-[13px] font-medium transition-colors focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none disabled:cursor-not-allowed disabled:opacity-40',
            value === v ? 'bg-background text-foreground shadow-xs' : 'text-muted-foreground hover:text-foreground')}>
          {text}
        </button>
      ))}
    </div>
  );
}

function Control({ id, label, children }: { id: string; label: string; children: React.ReactNode }) {
  return (
    <div className="flex min-w-0 flex-col gap-1">
      <Label htmlFor={id} className="text-[11px] font-medium text-muted-foreground">{label}</Label>
      <div className="flex items-center gap-1">{children}</div>
    </div>
  );
}

function StepButton({ dir, onClick, disabled, label }: { dir: -1 | 1; onClick: () => void; disabled: boolean; label: string }) {
  const Icon = dir < 0 ? ChevronLeft : ChevronRight;
  return <Button type="button" variant="outline" size="icon" className="size-9 shrink-0" aria-label={label} disabled={disabled} onClick={onClick}><Icon /></Button>;
}

/** Calendar date input limited to the reporting month's dates; dates without data are reported, not applied silently. */
function DateField({ id, value, min, max, onChange }: { id: string; value: string; min: string; max: string; onChange: (d: string) => void }) {
  return <Input id={id} type="date" className="h-9 w-36" value={value} min={min} max={max} onChange={(e) => { if (e.target.value) onChange(e.target.value); }} />;
}

/** Month and year grid: navigate years, pick a month; months without the needed data are disabled with the reason. */
function MonthPicker({ id, value, onChange, enabled, allowNone, label }: {
  id: string; value: string | null; onChange: (key: string) => void; enabled: (key: string) => string | null; allowNone?: boolean; label: string;
}) {
  const [open, setOpen] = useState(false);
  const [year, setYear] = useState(() => Number((value ?? '').slice(0, 4)) || new Date().getFullYear());
  return (
    <Popover open={open} onOpenChange={(o) => { setOpen(o); if (o && value) setYear(Number(value.slice(0, 4))); }}>
      <PopoverTrigger asChild>
        <Button id={id} type="button" variant="outline" className="h-9 w-32 justify-between font-normal" aria-label={`${label}: ${value ? monthLabel(value) : 'none'}`}>
          {value ? monthLabel(value) : 'No comparison'} <CalendarDays className="text-muted-foreground" />
        </Button>
      </PopoverTrigger>
      <PopoverContent className="w-64 p-3" align="start">
        <div className="mb-2 flex items-center justify-between">
          <Button type="button" variant="ghost" size="icon" className="size-7" aria-label="Previous year" onClick={() => setYear(year - 1)}><ChevronLeft /></Button>
          <span className="text-sm font-semibold" aria-live="polite">{year}</span>
          <Button type="button" variant="ghost" size="icon" className="size-7" aria-label="Next year" onClick={() => setYear(year + 1)}><ChevronRight /></Button>
        </div>
        <div className="grid grid-cols-3 gap-1" role="grid" aria-label={`${label}, ${year}`}>
          {MONTH_NAMES.map((name, i) => {
            const key = `${year}-${String(i + 1).padStart(2, '0')}`;
            const reason = enabled(key);
            return (
              <button key={key} type="button" disabled={Boolean(reason)} title={reason ?? undefined} aria-pressed={key === value}
                aria-label={`${name} ${year}${reason ? ` (${reason})` : ''}`}
                onClick={() => { onChange(key); setOpen(false); }}
                className={cn('h-8 rounded-md text-sm transition-colors focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none disabled:cursor-not-allowed disabled:text-muted-foreground/40',
                  key === value ? 'bg-primary text-primary-foreground' : 'hover:bg-muted')}>
                {name}
              </button>
            );
          })}
        </div>
        {allowNone && (
          <Button type="button" variant="ghost" size="sm" className="mt-2 w-full" onClick={() => { onChange('none'); setOpen(false); }}>No comparison</Button>
        )}
      </PopoverContent>
    </Popover>
  );
}

function WeekSelect({ id, value, weeks, onChange, allowNone, exclude }: {
  id: string; value: string | null; weeks: Period[]; onChange: (id: string) => void; allowNone?: boolean; exclude?: string;
}) {
  const current = value ? weeks.find((w) => w.id === value) ?? null : null;
  return (
    <Select value={value ?? 'none'} onValueChange={onChange}>
      <SelectTrigger id={id} className="h-9 w-52"><SelectValue>{current ? current.label : value ? value : 'No comparison'}</SelectValue></SelectTrigger>
      <SelectContent>
        {allowNone && <SelectItem value="none">No comparison</SelectItem>}
        {weeks.filter((w) => w.id !== exclude).map((w) => (
          <SelectItem key={w.id} value={w.id} disabled={!w.available}>
            {w.label}
            <span className="text-xs text-muted-foreground">{w.available ? (w.partial ? `${w.dates.length} of ${w.days} days` : `${w.days} days`) : 'no data'}</span>
          </SelectItem>
        ))}
      </SelectContent>
    </Select>
  );
}

/** Granularity, the selected period and a comparison period of the same granularity. */
export function PeriodControls({ av, reportingDates, sel, onChange, monthEnabled, children, notes: extraNotes = [], header }: {
  av: Availability; reportingDates: string[]; sel: PeriodSelection; onChange: (change: PeriodChange) => void;
  /** Other filters (project, circle) shown in the same compact bar. */
  children?: ReactNode;
  /** Further notes about the comparison, shown with the period notes. */
  notes?: string[];
  /** Page title shown above the filters, in the same card. */
  header?: ReactNode;
  /** Why a month cannot be picked for the current basis (null when it can). */
  monthEnabled: (key: string, forComparison: boolean) => string | null;
}) {
  const weeks = weeksAvailable(av);
  const dayAv: Availability = { ...av, dates: reportingDates };
  const [first, last] = [reportingDates[0] ?? av.latest, reportingDates.at(-1) ?? av.latest];
  const unavailable = (p: Period | null) => (p && !p.available ? p.reason ?? 'Not available.' : null);
  const prevWeek = shiftWeek(sel.week, -1);
  const nextWeek = shiftWeek(sel.week, 1);
  const weekOk = (id: string | null) => Boolean(id && weekPeriod(id, av).available);
  // A typed date without data is reported here and not applied (the filters would otherwise fall back silently).
  const [dateError, setDateError] = useState<{ field: 'date' | 'vs'; text: string } | null>(null);
  const pickDate = (field: 'date' | 'vs', d: string) => {
    if (!reportingDates.includes(d)) {
      setDateError({ field, text: `No data for ${formatDate(d)}: choose a reporting date between ${formatDate(first)} and ${formatDate(last)}.` });
      return;
    }
    setDateError(null);
    onChange(field === 'date' ? { date: d } : { vs: d });
  };

  // Shown in one line under the bar, so a message never changes the width of the controls.
  const notes = [
    dateError?.text,
    unavailable(sel.selected) && `${sel.view === 'day' ? 'Date' : sel.view === 'week' ? 'Week' : 'Month'}: ${unavailable(sel.selected)}`,
    unavailable(sel.comparison) && `Comparison ${sel.comparison!.label.split(' · ')[0]}: ${unavailable(sel.comparison)}`,
    ...extraNotes,
  ].filter((n): n is string => Boolean(n));

  return (
    <Card className="gap-0 rounded-xl px-4 py-2.5 shadow-xs">
      {header && <header className="mb-2.5 border-b pb-2.5">{header}</header>}
      <div role="search" aria-label="Portfolio filters">
      <div className="flex flex-wrap items-start gap-x-3 gap-y-2">
      <div role="group" aria-label="Reporting period" className="flex flex-wrap items-start gap-x-3 gap-y-2">
        <div className="flex flex-col gap-1">
          <span className="text-[11px] font-medium text-muted-foreground">Period</span>
          <Segmented label="Period type" value={sel.view} options={GRANULARITIES} onChange={(view) => onChange({ view })} />
        </div>

        {sel.view === 'day' && (
          <>
            <Control id="period-date" label="Date">
              <StepButton dir={-1} label="Previous date" disabled={!previousDate(sel.date, dayAv)} onClick={() => onChange({ date: previousDate(sel.date, dayAv)! })} />
              <DateField id="period-date" value={sel.date} min={first} max={last} onChange={(d) => pickDate('date', d)} />
              <StepButton dir={1} label="Next date" disabled={!nextDate(sel.date, dayAv)} onClick={() => onChange({ date: nextDate(sel.date, dayAv)! })} />
            </Control>
            <Control id="period-vs-date" label="Compare with date">
              <DateField id="period-vs-date" value={sel.vsDate ?? ''} min={first} max={last} onChange={(d) => pickDate('vs', d)} />
              <Button type="button" variant={sel.vsDate ? 'ghost' : 'secondary'} size="sm" className="h-9" aria-pressed={!sel.vsDate}
                onClick={() => onChange({ vs: sel.vsDate ? 'none' : previousDate(sel.date, dayAv) ?? 'none' })}>
                {sel.vsDate ? 'No comparison' : 'Compare'}
              </Button>
            </Control>
          </>
        )}

        {sel.view === 'week' && (
          <>
            <Control id="period-week" label="Week">
              <StepButton dir={-1} label="Previous week" disabled={!weekOk(prevWeek)} onClick={() => onChange({ week: prevWeek! })} />
              <WeekSelect id="period-week" value={sel.week} weeks={weeks} onChange={(week) => onChange({ week })} />
              <StepButton dir={1} label="Next week" disabled={!weekOk(nextWeek)} onClick={() => onChange({ week: nextWeek! })} />
            </Control>
            <Control id="period-vs-week" label="Compare with week">
              <WeekSelect id="period-vs-week" value={sel.vsWeek} weeks={sel.vsWeek && !weeks.some((w) => w.id === sel.vsWeek) ? [weekPeriod(sel.vsWeek, av), ...weeks] : weeks}
                exclude={sel.week} allowNone onChange={(vs) => onChange({ vs })} />
            </Control>
          </>
        )}

        {sel.view === 'month' && (
          <>
            <Control id="period-month" label="Month">
              <MonthPicker id="period-month" label="Month" value={sel.month} enabled={(k) => monthEnabled(k, false)} onChange={(month) => onChange({ month })} />
            </Control>
            <div className="flex flex-col gap-1">
              <span className="text-[11px] font-medium text-muted-foreground">Basis</span>
              <Segmented label="Month basis" value={sel.basis} options={[['mtd', 'MTD'], ['full', 'Full month']]} onChange={(basis) => onChange({ basis })}
                disabled={{ full: sel.month === av.currentMonth ? `${monthLabel(sel.month)} is in progress` : !av.fullMonths.has(sel.month) ? 'No monthly total' : undefined,
                  mtd: av.dailyMonths.has(sel.month) ? undefined : 'No daily data for this month' }} />
            </div>
            <Control id="period-vs-month" label="Compare with month">
              <MonthPicker id="period-vs-month" label="Compare with month" value={sel.vsMonth} allowNone enabled={(k) => (k === sel.month ? 'The selected month' : monthEnabled(k, true))}
                onChange={(vs) => onChange({ vs })} />
            </Control>
          </>
        )}
      </div>
      {children && <span className="hidden w-px self-stretch bg-border sm:block" aria-hidden="true" />}
      {children}
      </div>
      {notes.length > 0 && (
        <ul className="mt-1.5 space-y-0.5 border-t pt-1.5 text-xs text-amber-800" aria-label="Period notes">
          {notes.map((text) => <li key={text} className="flex items-start gap-1" role="status"><CircleAlert className="mt-px size-3.5 shrink-0" aria-hidden="true" />{text}</li>)}
        </ul>
      )}
      </div>
    </Card>
  );
}
