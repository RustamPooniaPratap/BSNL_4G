import { RotateCcw } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { cn } from '@/lib/utils';
import { Card } from '@/components/ui/card';
import { PageHeading } from '../../context/pageHeader';
import { Label } from '@/components/ui/label';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import type { DashboardFilterState, ResolvedFilters } from '../../hooks/useDashboardFilters';
import { formatDate } from '../../lib/format';
import type { FilterOptions, Scope } from '../../types';
import { TrendPeriodPicker } from './TrendPeriodPicker';

const ALL = '__all__';

interface FilterBarProps {
  options: FilterOptions;
  filters: ResolvedFilters;
  onChange: (changes: Partial<DashboardFilterState>) => void;
  onReset: () => void;
  canReset: boolean;
  /** Pages without a trend chart hide the trend range. */
  showTrendRange?: boolean;
  /** Pages that show every scope side by side hide the scope selector. */
  showScope?: boolean;
  /** Pages that pick a month instead of a day hide the reporting date. */
  showDate?: boolean;
  /** Extra controls in the same row (e.g. a comparison period). */
  extra?: React.ReactNode;
  /** Page title and description, shown above the filters in the same card. */
  title?: React.ReactNode;
  description?: React.ReactNode;
  /** Page-level controls shown beside the title (e.g. a view switch). */
  actions?: React.ReactNode;
}

/** Page title and filters in one compact card: one row of fixed-width controls that wraps on narrow screens. */
export function FilterBar({ options, filters, onChange, onReset, canReset, showTrendRange = true, showScope = true, showDate = true, extra, title, description, actions }: FilterBarProps) {
  const circles = options.circles.filter((c) => !filters.reportType || c.report_types.includes(filters.reportType));
  const dates = [...options.reporting_dates].reverse();

  const setReportType = (value: string) => {
    const reportType = value === ALL ? '' : value;
    const circleStillValid = options.circles
      .find((c) => c.value === filters.circle)?.report_types.includes(reportType);
    onChange({ reportType, ...(reportType && !circleStillValid ? { circle: '' } : {}) });
  };

  return (
    <Card className="gap-0 rounded-xl px-4 py-2.5 shadow-xs">
      {/* The page title and its context are shown in the top application bar. */}
      {title && <PageHeading title={title} subtitle={description} />}
      <div role="search" aria-label="Dashboard filters" className="flex flex-wrap items-end gap-x-3 gap-y-2">
        <Field id="filter-report-type" label="Project" className="w-36">
          <Select value={filters.reportType || ALL} onValueChange={setReportType}>
            <SelectTrigger id="filter-report-type" className="h-9 w-full"><SelectValue /></SelectTrigger>
            <SelectContent>
              <SelectItem value={ALL}>All projects</SelectItem>
              {options.report_types.map((t) => (
                <SelectItem key={t.value} value={t.value}>{t.label}</SelectItem>
              ))}
            </SelectContent>
          </Select>
        </Field>

        <Field id="filter-circle" label="Circle" className="w-32">
          <Select value={filters.circle || ALL} onValueChange={(v) => onChange({ circle: v === ALL ? '' : v })}>
            <SelectTrigger id="filter-circle" className="h-9 w-full"><SelectValue /></SelectTrigger>
            <SelectContent>
              <SelectItem value={ALL}>All circles</SelectItem>
              {circles.map((c) => (
                <SelectItem key={c.value} value={c.value}>{c.label}</SelectItem>
              ))}
            </SelectContent>
          </Select>
        </Field>

        {showScope && <Field id="filter-scope" label="Site scope" className="w-36">
          <Select value={filters.scope} onValueChange={(v) => onChange({ scope: v as Scope })}>
            <SelectTrigger id="filter-scope" className="h-9 w-full"><SelectValue /></SelectTrigger>
            <SelectContent>
              {options.scopes.map((s) => (
                <SelectItem key={s.value} value={s.value} disabled={!s.available}>{s.label}</SelectItem>
              ))}
            </SelectContent>
          </Select>
        </Field>}

        {showDate && <Field id="filter-date" label="Reporting date" className="w-44">
          <DateSelect id="filter-date" value={filters.date} dates={dates}
            latest={options.default_date} onChange={(date) => onChange({ date })} />
        </Field>}

        {extra}
        {showTrendRange && (
          <Field id="filter-trend-period" label="Trend period" className="w-60">
            <TrendPeriodPicker id="filter-trend-period" options={options} filters={filters} onChange={onChange} />
          </Field>
        )}

        <Button variant="ghost" size="icon" className="size-9" onClick={onReset} disabled={!canReset} aria-label="Reset filters" title="Reset filters">
          <RotateCcw />
        </Button>
        {actions && <div className="ml-auto self-end">{actions}</div>}
      </div>
    </Card>
  );
}

/**
 * The filter card of the dashboard pages, for any page: one compact row of labelled controls that wraps on narrow
 * screens, with page actions at the right. Use <Field> for each control so the labels match.
 */
export function FilterCard({ label = 'Filters', children, actions, footer }: {
  label?: string; children: React.ReactNode; actions?: React.ReactNode; footer?: React.ReactNode;
}) {
  return (
    <Card className="gap-0 rounded-xl px-4 py-2.5 shadow-xs">
      {/* Every control is 36 px high, as in the dashboard FilterBar, so labels and controls line up across the row. */}
      <div role="search" aria-label={label}
        className="flex flex-wrap items-end gap-x-3 gap-y-2 [&_[data-slot=select-trigger]]:h-9 [&_input:not([type=checkbox])]:h-9">
        {children}
        {actions && <div className="ml-auto flex items-end gap-2 self-end">{actions}</div>}
      </div>
      {footer && <div className="mt-2 text-xs text-muted-foreground">{footer}</div>}
    </Card>
  );
}

export function Field({ id, label, children, className }: { id: string; label: string; children: React.ReactNode; className?: string }) {
  return (
    <div className={cn('flex min-w-0 flex-col gap-1', className)}>
      <Label htmlFor={id} className="text-[11px] font-medium text-muted-foreground">{label}</Label>
      {children}
    </div>
  );
}

function DateSelect({ id, value, dates, latest, onChange }: {
  id: string; value: string; dates: string[]; latest?: string | null; onChange: (value: string) => void;
}) {
  return (
    <Select value={value} onValueChange={onChange} disabled={!dates.length}>
      <SelectTrigger id={id} className="h-9 w-full"><SelectValue placeholder="No dates" /></SelectTrigger>
      <SelectContent>
        {dates.map((d) => (
          <SelectItem key={d} value={d}>{formatDate(d)}{d === latest ? ' (latest)' : ''}</SelectItem>
        ))}
      </SelectContent>
    </Select>
  );
}
