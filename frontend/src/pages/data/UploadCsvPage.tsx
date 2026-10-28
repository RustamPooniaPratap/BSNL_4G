import { useMemo, useRef, useState, type DragEvent } from 'react';
import { Link } from 'react-router-dom';
import { CircleAlert, CircleCheck, FileText, Loader2, MapPinPlus, RefreshCw, Sheet, TriangleAlert, Upload, X } from 'lucide-react';
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Input } from '@/components/ui/input';
import { Skeleton } from '@/components/ui/skeleton';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table';
import { cn } from '@/lib/utils';
import { DataEntryHeader, Field, NoWorkbook, ReviewList, SelectField, ValidatedLocally, type Step } from '../../components/data/DataEntry';
import { useWorkbook } from '../../context/workbook';
import { useApiQuery } from '../../hooks/useApiQuery';
import { useSiteRegistry } from '../../hooks/useSiteRegistry';
import {
  COLUMN_ALIASES, VALIDATED_MESSAGES, fieldA11y, formatBytes, newSiteLink, parseCsv, parseDate, validateCsv,
  type ColumnRole, type DateCheck, type ParsedCsv,
} from '../../lib/dataEntry';
import { formatDate, formatNumber } from '../../lib/format';
import { fetchFilterOptions } from '../../services/api';

const MAX_BYTES = 10 * 1024 * 1024;  // read in the browser, so keep it modest
const PREVIEW_ROWS = 10;
const ISSUES_SHOWN = 100;
const ROLE_LABELS: Record<ColumnRole, string> = {
  site_id: 'Site ID', outage_minutes: 'Outage minutes', availability_pct: 'Availability %', circle: 'Circle',
  date: 'Date', site_name: 'Site name', report_type: 'Report type',
};

interface LoadedFile {
  name: string;
  size: number;
  csv: ParsedCsv | null;
  error: string | null;
}

/** A cleaned CSV of daily records for one report type, circle and reporting date, checked in the browser. */
export function UploadCsvPage() {
  const workbook = useWorkbook();
  const options = useApiQuery(workbook.active ? `${workbook.version}|filters` : null, fetchFilterOptions);
  const [meta, setMeta] = useState({ reportType: '', circle: '', date: '' });
  const [file, setFile] = useState<LoadedFile | null>(null);
  const [reading, setReading] = useState(false);
  const [dragging, setDragging] = useState(false);
  const [step, setStep] = useState<Step>('edit');
  const input = useRef<HTMLInputElement>(null);
  const registry = useSiteRegistry(workbook.version, meta.reportType, meta.circle);

  const date = parseDate(meta.date);
  const metaErrors = {
    reportType: meta.reportType ? null : 'Choose a report type.',
    circle: meta.circle ? null : 'Choose a circle.',
    date: !meta.date ? 'Choose the reporting date.' : !date ? 'Enter a valid date.' : null,
  };
  const metaReady = !metaErrors.reportType && !metaErrors.circle && !metaErrors.date;
  const validation = useMemo(
    () => (file?.csv ? validateCsv(file.csv, { reportType: meta.reportType, circle: meta.circle, date: date ?? '' }, registry.sites ? new Set(registry.sites.keys()) : null) : null),
    [file, meta.reportType, meta.circle, date, registry.sites],
  );

  const choose = async (picked: File | undefined) => {
    // The upload details come first: dates, circles and Site IDs are checked against them.
    if (!picked || !metaReady) return;
    setStep('edit');
    if (!picked.name.toLowerCase().endsWith('.csv')) {
      setFile({ name: picked.name, size: picked.size, csv: null, error: 'Only .csv files are accepted here. Save the sheet as CSV (comma-separated) first.' });
      return;
    }
    if (picked.size === 0) {
      setFile({ name: picked.name, size: 0, csv: null, error: 'The file is empty.' });
      return;
    }
    if (picked.size > MAX_BYTES) {
      setFile({ name: picked.name, size: picked.size, csv: null, error: `The file is larger than ${formatBytes(MAX_BYTES)}; split it before checking.` });
      return;
    }
    setReading(true);
    try {
      const text = await picked.text();
      setFile({ name: picked.name, size: picked.size, csv: parseCsv(text), error: null });
    } catch {
      setFile({ name: picked.name, size: picked.size, csv: null, error: 'The file could not be read.' });
    } finally {
      setReading(false);
      if (input.current) input.current.value = '';
    }
  };
  const remove = () => { setFile(null); setStep('edit'); };

  if (!workbook.loading && !workbook.active) return <NoWorkbook />;
  if (!options.data) return <Skeleton className="h-96 w-full" aria-label="Loading form" />;

  const circles = options.data.circles.filter((c) => !meta.reportType || c.report_types.includes(meta.reportType));
  const checking = Boolean(validation && registry.loading);
  const ready = metaReady && validation != null && validation.errorCount === 0 && validation.rowCount > 0 && !checking && !registry.error;
  const unknownIds = validation
    ? [...new Set(validation.issues.filter((i) => i.unknownSite && i.siteId).map((i) => i.siteId!))] : [];

  const summary = file && validation && (
    <ReviewList items={[
      { label: 'Report type', value: meta.reportType || '—' },
      { label: 'Circle', value: meta.circle || '—' },
      { label: 'Reporting date', value: date ? formatDate(date) : '—' },
      { label: 'File', value: `${file.name} (${formatBytes(file.size)})` },
      { label: 'Rows', value: `${formatNumber(validation.rowCount)} (${formatNumber(validation.validRows)} passed)` },
      { label: 'Values', value: validation.measure === 'availability_pct' ? 'Availability %' : validation.measure === 'outage_minutes' ? 'Outage minutes' : '—' },
    ]} />
  );

  return (
    <div className="space-y-5">
      <DataEntryHeader
        icon={<Sheet />}
        accent="bg-violet-50 text-violet-700"
        title="Upload CSV"
        description="Check a cleaned CSV of daily records for one report type, circle and reporting date. The file is read in your browser and is not uploaded."
        step={step}
      />

      {step === 'done' ? (
        <ValidatedLocally message={VALIDATED_MESSAGES.csv}>
          <div className="mt-3 space-y-3">{summary}</div>
          <div className="mt-3 flex flex-wrap gap-2">
            <Button size="sm" onClick={() => { remove(); setMeta({ reportType: '', circle: '', date: '' }); }}>Check another file</Button>
            <Button size="sm" variant="outline" onClick={() => setStep('edit')}>Back to this file</Button>
          </div>
        </ValidatedLocally>
      ) : step === 'review' ? (
        <Card>
          <CardHeader>
            <CardTitle className="text-sm font-semibold">Confirm the upload details</CardTitle>
            <CardDescription className="text-xs">Confirming only records that the browser checks passed; nothing is sent.</CardDescription>
          </CardHeader>
          <CardContent className="space-y-4">
            {summary}
            {validation!.warningCount > 0 && (
              <p className="text-xs text-amber-700">{validation!.warningCount} warning{validation!.warningCount === 1 ? '' : 's'} to be aware of (see the checks on the previous step).</p>
            )}
            <div className="flex flex-wrap gap-2">
              <Button onClick={() => setStep('done')}>Confirm CSV</Button>
              <Button variant="outline" onClick={() => setStep('edit')}>Back to edit</Button>
            </div>
          </CardContent>
        </Card>
      ) : (
        <>
          <Card>
            <CardHeader>
              <CardTitle className="text-sm font-semibold">1. Upload details</CardTitle>
              <CardDescription className="text-xs">Apply to every row. If the file has its own circle or date column, rows that disagree are flagged, never overwritten.</CardDescription>
            </CardHeader>
            <CardContent>
              <div className="grid grid-cols-1 gap-4 sm:grid-cols-3">
                <Field id="csv-report-type" label="Report type" required error={file ? metaErrors.reportType : null}>
                  <SelectField id="csv-report-type" value={meta.reportType} placeholder="Choose report type"
                    options={options.data.report_types.map((t) => ({ value: t.value, label: t.label }))}
                    onChange={(reportType) => setMeta((m) => ({ ...m, reportType, circle: options.data!.circles.find((c) => c.value === m.circle)?.report_types.includes(reportType) ? m.circle : '' }))} />
                </Field>
                <Field id="csv-circle" label="Circle" required error={file ? metaErrors.circle : null}>
                  <SelectField id="csv-circle" value={meta.circle} disabled={!meta.reportType}
                    placeholder={meta.reportType ? 'Choose circle' : 'Choose report type first'}
                    options={circles.map((c) => ({ value: c.value, label: c.label }))}
                    onChange={(circle) => setMeta((m) => ({ ...m, circle }))} />
                </Field>
                <Field id="csv-date" label="Reporting date" required error={file ? metaErrors.date : null}>
                  <Input type="date" {...fieldA11y('csv-date', file ? metaErrors.date : null)} value={meta.date}
                    onChange={(e) => setMeta((m) => ({ ...m, date: e.target.value }))} />
                </Field>
              </div>
            </CardContent>
          </Card>

          <Card>
            <CardHeader>
              <CardTitle className="text-sm font-semibold">2. CSV file</CardTitle>
              <CardDescription className="text-xs">
                Required columns: a Site ID ({COLUMN_ALIASES.site_id.join(' / ')}), the reporting date ({COLUMN_ALIASES.date.join(' / ')})
                and one value column: outage minutes ({COLUMN_ALIASES.outage_minutes.join(' / ')}) or availability %
                ({COLUMN_ALIASES.availability_pct.join(' / ')}). Optional: {COLUMN_ALIASES.circle[0]}, {COLUMN_ALIASES.site_name[0]},
                {' '}{COLUMN_ALIASES.report_type.join(' / ')}. Other columns are listed but not checked.
              </CardDescription>
            </CardHeader>
            <CardContent className="space-y-4">
              <input ref={input} type="file" accept=".csv,text/csv" className="sr-only" aria-label="Choose CSV file"
                disabled={!metaReady} onChange={(e) => void choose(e.target.files?.[0])} />
              {!file ? (
                <div
                  onDragOver={(e: DragEvent) => { e.preventDefault(); setDragging(metaReady); }}
                  onDragLeave={() => setDragging(false)}
                  onDrop={(e: DragEvent) => { e.preventDefault(); setDragging(false); void choose(e.dataTransfer.files?.[0]); }}
                  className={cn('flex flex-col items-center justify-center gap-2 rounded-lg border-2 border-dashed px-6 py-10 text-center',
                    dragging ? 'border-primary bg-primary/5' : 'border-border', !metaReady && 'bg-muted/40')}
                >
                  {reading ? <Loader2 className="size-6 animate-spin text-muted-foreground" /> : <Upload className="size-6 text-muted-foreground" aria-hidden="true" />}
                  {metaReady ? <p className="text-sm">Drag a .csv file here, or</p>
                    : <p className="text-sm text-muted-foreground">Choose the report type, circle and reporting date above first.</p>}
                  <Button type="button" size="sm" variant="outline" disabled={!metaReady} onClick={() => input.current?.click()}>Choose file</Button>
                </div>
              ) : (
                <div className="flex flex-wrap items-center justify-between gap-3 rounded-lg border px-4 py-3">
                  <div className="flex min-w-0 items-center gap-3">
                    <FileText className="size-5 shrink-0 text-muted-foreground" aria-hidden="true" />
                    <div className="min-w-0">
                      <p className="truncate text-sm font-medium">{file.name}</p>
                      <p className="text-xs text-muted-foreground">
                        {formatBytes(file.size)}{file.csv ? ` · ${formatNumber(file.csv.rows.length)} data rows · ${file.csv.headers.length} columns` : ''}
                      </p>
                    </div>
                  </div>
                  <div className="flex gap-2">
                    <Button type="button" size="sm" variant="outline" disabled={!metaReady} onClick={() => input.current?.click()}><RefreshCw /> Replace</Button>
                    <Button type="button" size="sm" variant="ghost" onClick={remove}><X /> Remove</Button>
                  </div>
                </div>
              )}
              {file?.error && (
                <Alert variant="destructive"><CircleAlert /><AlertTitle>File not accepted</AlertTitle><AlertDescription>{file.error}</AlertDescription></Alert>
              )}
            </CardContent>
          </Card>

          {file?.csv && validation && (
            <>
              <Preview csv={file.csv} roles={validation.roles} />
              <DateCheckCard check={validation.dateCheck} />
              <Checks validation={validation} checking={checking} unknownIds={unknownIds} meta={meta} metaReady={metaReady} registryError={registry.error} />
              <Card>
                <CardHeader>
                  <CardTitle className="text-sm font-semibold">3. Summary</CardTitle>
                  <CardDescription className="text-xs">
                    {ready ? 'All checks passed. Review and confirm.' : 'Confirmation is available once the upload details are complete and the file has no errors.'}
                  </CardDescription>
                </CardHeader>
                <CardContent className="space-y-4">
                  {summary}
                  <Button disabled={!ready} onClick={() => setStep('review')}>Review and confirm</Button>
                </CardContent>
              </Card>
            </>
          )}
        </>
      )}
    </div>
  );
}

function Preview({ csv, roles }: { csv: ParsedCsv; roles: Partial<Record<ColumnRole, number>> }) {
  const roleOf = (index: number) => (Object.entries(roles) as [ColumnRole, number][]).find(([, i]) => i === index)?.[0];
  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-sm font-semibold">Preview</CardTitle>
        <CardDescription className="text-xs">
          {formatNumber(csv.rows.length)} data rows detected · showing the first {Math.min(PREVIEW_ROWS, csv.rows.length)}
        </CardDescription>
      </CardHeader>
      <CardContent className="px-0">
        <div className="overflow-x-auto">
          <Table className="text-xs">
            <TableHeader>
              <TableRow className="bg-muted/50 hover:bg-muted/50">
                <TableHead className="w-14 text-right">Line</TableHead>
                {csv.headers.map((h, i) => {
                  const role = roleOf(i);
                  return (
                    <TableHead key={`${h}-${i}`} className="whitespace-nowrap">
                      {h || <span className="italic text-muted-foreground">(no name)</span>}
                      <Badge variant={role ? 'secondary' : 'outline'} className="ml-1.5 font-normal">{role ? ROLE_LABELS[role] : 'not used'}</Badge>
                    </TableHead>
                  );
                })}
              </TableRow>
            </TableHeader>
            <TableBody>
              {csv.rows.slice(0, PREVIEW_ROWS).map((row, r) => (
                <TableRow key={csv.lines[r]}>
                  <TableCell className="text-right text-muted-foreground tabular-nums">{csv.lines[r]}</TableCell>
                  {csv.headers.map((_, c) => <TableCell key={c} className="whitespace-nowrap">{row[c] ?? <span className="text-destructive">missing</span>}</TableCell>)}
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </div>
      </CardContent>
    </Card>
  );
}

const LINES_SHOWN = 15;
const lineList = (lines: number[]) =>
  `line${lines.length === 1 ? '' : 's'} ${lines.slice(0, LINES_SHOWN).join(', ')}${lines.length > LINES_SHOWN ? ` and ${lines.length - LINES_SHOWN} more` : ''}`;

/** File-level reporting date check: the expected date, every date found, and on which lines. */
function DateCheckCard({ check }: { check: DateCheck }) {
  const passed = check.status === 'passed';
  return (
    <Card className={cn(check.status === 'failed' && 'border-destructive/40')} role="region" aria-label="Reporting date check">
      <CardHeader>
        <CardTitle className="flex flex-wrap items-center gap-2 text-sm font-semibold">
          Reporting date check
          {passed ? <Badge variant="secondary" className="gap-1"><CircleCheck className="size-3" /> Passed</Badge>
            : check.status === 'failed' ? <Badge variant="destructive">Failed</Badge> : <Badge variant="outline">Waiting</Badge>}
        </CardTitle>
        <CardDescription className="text-xs">{check.message}</CardDescription>
      </CardHeader>
      {check.status !== 'pending' && (
        <CardContent>
          <dl className="grid grid-cols-1 gap-x-6 gap-y-2 text-sm sm:grid-cols-[10rem_1fr]">
            <dt className="text-xs text-muted-foreground">Expected (selected)</dt>
            <dd className="font-medium">{check.expected ? formatDate(check.expected) : '—'}</dd>
            <dt className="text-xs text-muted-foreground">Date column</dt>
            <dd className="font-medium">{check.column ?? <span className="text-destructive">Missing</span>}</dd>
            <dt className="text-xs text-muted-foreground">Dates in the file</dt>
            <dd>
              {check.detected.length ? (
                <ul className="space-y-1">
                  {check.detected.map((d) => (
                    <li key={d.date} className={cn(d.date !== check.expected && 'text-destructive')}>
                      <span className="font-medium">{formatDate(d.date)}</span>
                      {' '}· {formatNumber(d.lines.length)} row{d.lines.length === 1 ? '' : 's'}
                      {d.date !== check.expected && <span className="text-xs"> ({lineList(d.lines)})</span>}
                    </li>
                  ))}
                </ul>
              ) : '—'}
            </dd>
            {check.invalid.length > 0 && (
              <>
                <dt className="text-xs text-muted-foreground">Missing or unreadable</dt>
                <dd>
                  <ul className="space-y-1 text-destructive">
                    {check.invalid.map((i) => (
                      <li key={i.value}>
                        <span className="font-medium">{i.value ? `"${i.value}"` : 'Empty'}</span>{' '}
                        <span className="text-xs">({lineList(i.lines)})</span>
                      </li>
                    ))}
                  </ul>
                </dd>
              </>
            )}
          </dl>
        </CardContent>
      )}
    </Card>
  );
}

function Checks({ validation, checking, unknownIds, meta, metaReady, registryError }: {
  validation: ReturnType<typeof validateCsv>; checking: boolean; unknownIds: string[];
  meta: { reportType: string; circle: string }; metaReady: boolean; registryError: Error | null;
}) {
  const shown = validation.issues.slice(0, ISSUES_SHOWN);
  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex flex-wrap items-center gap-2 text-sm font-semibold">
          Checks
          {checking ? <Badge variant="outline" className="gap-1"><Loader2 className="size-3 animate-spin" /> Checking Site IDs</Badge>
            : validation.errorCount ? <Badge variant="destructive">{formatNumber(validation.errorCount)} error{validation.errorCount === 1 ? '' : 's'}</Badge>
              : <Badge variant="secondary">No errors</Badge>}
          {validation.warningCount > 0 && <Badge variant="outline" className="border-amber-300 text-amber-800">{formatNumber(validation.warningCount)} warning{validation.warningCount === 1 ? '' : 's'}</Badge>}
        </CardTitle>
        <CardDescription className="text-xs">
          {!metaReady ? 'Choose the report type and circle to check Site IDs against the master data.'
            : `Site IDs are checked against the ${meta.reportType} · ${meta.circle} sites in the loaded Master workbook.`}
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-3">
        {registryError && <Alert variant="destructive"><AlertTitle>Master data could not be loaded</AlertTitle><AlertDescription>{registryError.message}</AlertDescription></Alert>}
        {unknownIds.length > 0 && (
          <Alert className="border-amber-300 bg-amber-50/70">
            <MapPinPlus className="text-amber-700" />
            <AlertTitle>{unknownIds.length} Site ID{unknownIds.length === 1 ? '' : 's'} not in the master data</AlertTitle>
            <AlertDescription>
              <p>Unknown sites are never created from daily data. Add them as new sites first, or correct the IDs.</p>
              <ul className="mt-1.5 flex flex-wrap gap-1.5">
                {unknownIds.slice(0, 12).map((id) => (
                  <li key={id}>
                    <Link to={newSiteLink(id, meta.reportType, meta.circle)} className="inline-flex items-center gap-1 rounded border bg-background px-1.5 py-0.5 font-mono text-[11px] underline-offset-2 hover:underline">
                      <MapPinPlus className="size-3" /> {id}
                    </Link>
                  </li>
                ))}
                {unknownIds.length > 12 && <li className="text-xs">and {unknownIds.length - 12} more</li>}
              </ul>
            </AlertDescription>
          </Alert>
        )}
        {shown.length === 0 ? (
          <p className="text-sm text-muted-foreground">{checking ? 'Waiting for the master data…' : 'Every row passed the checks.'}</p>
        ) : (
          <ul className="max-h-80 divide-y overflow-auto rounded-md border text-xs" aria-label="Problems found">
            {shown.map((issue, i) => (
              <li key={i} className="flex gap-2 px-3 py-1.5">
                {issue.severity === 'error'
                  ? <CircleAlert className="mt-px size-3.5 shrink-0 text-destructive" aria-label="Error" />
                  : <TriangleAlert className="mt-px size-3.5 shrink-0 text-amber-600" aria-label="Warning" />}
                <span className="w-16 shrink-0 text-muted-foreground tabular-nums">{issue.line ? `Line ${issue.line}` : 'File'}</span>
                <span>{issue.message}</span>
              </li>
            ))}
          </ul>
        )}
        {validation.issues.length > ISSUES_SHOWN && (
          <p className="text-xs text-muted-foreground">Showing the first {ISSUES_SHOWN} of {formatNumber(validation.issues.length)} findings.</p>
        )}
      </CardContent>
    </Card>
  );
}
