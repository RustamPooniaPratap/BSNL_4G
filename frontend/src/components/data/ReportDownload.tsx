import { useState } from 'react';
import { CircleAlert, CircleCheck, Download, Loader2 } from 'lucide-react';
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { cn } from '@/lib/utils';
import { Field, FilterCard } from '../dashboard/FilterBar';
import { SelectField } from './DataEntry';
import { usePopulation } from '../../context/population';
import { useFilterOptions } from '../../hooks/useFilterOptions';
import { PopulationSelect } from '../PopulationSelect';
import { formatDate } from '../../lib/format';
import { downloadReport, type ReportKind } from '../../services/api';
import type { RawUploadOptions } from '../../types/rawUpload';

const KINDS: { value: ReportKind; label: string; hint: string }[] = [
  { value: 'daily', label: 'Daily Uptime Report', hint: 'One sheet for one reporting date: site, outage minutes, availability and bucket.' },
  { value: 'consolidated', label: 'Full Consolidated Report', hint: 'The 13-sheet consolidated workbook for the month to the reporting date.' },
];

/** Save a downloaded file through a temporary link (the response was checked before this is called). */
function save(blob: Blob, filename: string) {
  const url = URL.createObjectURL(blob);
  const link = document.createElement('a');
  link.href = url;
  link.download = filename;
  document.body.appendChild(link);
  link.click();
  link.remove();
  URL.revokeObjectURL(url);
}

/**
 * Report downloads from the reporting data (the data layer). Project and circle options come from
 * the user's permitted circles; the server checks them again. Dates come from the active source's reported dates.
 */
export function ReportDownloadCard({ options }: { options: RawUploadOptions }) {
  const filters = useFilterOptions();
  // Every export is for the global population (On-Air / O&M Start), the same as the dashboard figures.
  const { scope, sitesLabel } = usePopulation();
  const [kind, setKind] = useState<ReportKind>('daily');
  const [project, setProject] = useState('');
  const [circle, setCircle] = useState('');
  const [day, setDay] = useState('');
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState<{ ok: boolean; text: string } | null>(null);

  const projects = options.projects.filter((p) => !project || p.value === project);
  const circles = [...new Set(projects.flatMap((p) => p.circles))].sort();
  const current = filters.data?.reporting_dates ?? [];
  const history = (filters.data?.daily_history ?? []).flatMap((h) => h.dates);
  const dailyDates = [...history, ...current];
  const latest = filters.data?.default_date ?? '';
  const reportDate = day || (kind === 'consolidated' ? latest : '');
  const dateKnown = kind === 'daily' ? dailyDates.includes(reportDate) : current.includes(reportDate);
  const noCircles = options.assigned_circles != null && options.assigned_circles.length === 0;
  const missing = noCircles ? 'No circle is assigned to your account.'
    : !filters.data ? (filters.error ? filters.error.message : 'Loading the reporting dates…')
      : !reportDate ? 'Choose the reporting date.'
        : !dateKnown ? `The active source has no daily values for ${formatDate(reportDate)}.` : null;
  const change = (apply: () => void) => { apply(); setResult(null); };

  const download = async () => {
    setBusy(true);
    setResult(null);
    try {
      const params: Record<string, string> = { report_type: project, circle, [kind === 'daily' ? 'date' : 'reporting_date']: reportDate };
      const { blob, filename } = await downloadReport(kind, params, scope);
      save(blob, filename);
      setResult({ ok: true, text: `Downloaded ${filename}.` });
    } catch (error) {
      setResult({ ok: false, text: error instanceof Error ? error.message : String(error) });
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="space-y-2">
      <FilterCard label="Download report" title="Download report"
        footer={`${KINDS.find((k) => k.value === kind)!.hint} Population: ${sitesLabel}. Source: ${filters.data?.source.workbook ?? 'the active data source'}.`}
        actions={(
          <Button className="h-9" disabled={busy || missing !== null} onClick={download} title={missing ?? `Download for ${sitesLabel}`}
            aria-label={busy ? 'Preparing…' : `Download (${sitesLabel})`}>
            {busy ? <Loader2 className="animate-spin" /> : <Download />} {busy ? 'Preparing…' : 'Download'}
          </Button>
        )}>
        <Field id="report-kind" label="Report type">
          <div id="report-kind" role="radiogroup" aria-label="Report type" className="inline-flex h-9 rounded-lg border bg-muted/40 p-0.5">
            {KINDS.map((k) => (
              <button key={k.value} type="button" role="radio" aria-checked={kind === k.value}
                onClick={() => change(() => { setKind(k.value); setDay(''); })}
                className={cn('rounded-md px-3 text-xs font-medium whitespace-nowrap transition-colors focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none',
                  kind === k.value ? 'bg-background text-foreground shadow-xs' : 'text-muted-foreground hover:text-foreground')}>
                {k.label}
              </button>
            ))}
          </div>
        </Field>
        <Field id="report-project" label="Project" className="w-40">
          <SelectField id="report-project" value={project || 'all'} placeholder="Project"
            onChange={(v) => change(() => { setProject(v === 'all' ? '' : v); setCircle(''); })}
            options={[{ value: 'all', label: 'All Projects' }, ...options.projects.map((p) => ({ value: p.value, label: p.value }))]} />
        </Field>
        <Field id="report-circle" label="Circle" className="w-36">
          <SelectField id="report-circle" value={circle || 'all'} placeholder="Circle" onChange={(v) => change(() => setCircle(v === 'all' ? '' : v))}
            options={[{ value: 'all', label: options.assigned_circles == null ? 'All Circles' : 'All my circles' }, ...circles.map((c) => ({ value: c, label: c }))]} />
        </Field>
        <PopulationSelect id="report-population" />
        <Field id="report-date" label={kind === 'daily' ? 'Report date' : 'Month to date, up to'} className="w-44">
          <Input id="report-date" type="date" className="h-9" value={reportDate}
            min={(kind === 'daily' ? dailyDates[0] : current[0]) || undefined} max={latest || undefined}
            onChange={(e) => change(() => setDay(e.target.value))} />
        </Field>
      </FilterCard>
      {missing && reportDate && !dateKnown && filters.data && <p className="text-xs text-amber-700" role="status">{missing}</p>}
      {result && (
        <Alert variant={result.ok ? 'default' : 'destructive'} role={result.ok ? 'status' : 'alert'}
          className={result.ok ? 'border-emerald-200 bg-emerald-50/70' : undefined}>
          {result.ok ? <CircleCheck className="text-emerald-700" /> : <CircleAlert />}
          <AlertTitle>{result.ok ? 'Report downloaded' : 'The report could not be prepared'}</AlertTitle>
          <AlertDescription>{result.text}</AlertDescription>
        </Alert>
      )}
    </div>
  );
}
