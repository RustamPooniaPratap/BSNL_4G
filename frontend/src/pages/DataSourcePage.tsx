import { useEffect } from 'react';
import { Link, useLocation } from 'react-router-dom';
import { AlertTriangle, CheckCircle2, Info } from 'lucide-react';
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert';
import { Badge } from '@/components/ui/badge';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { PageHeading } from '../context/pageHeader';
import { Skeleton } from '@/components/ui/skeleton';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table';
import { useWorkbook } from '../context/workbook';
import { useApiQuery } from '../hooks/useApiQuery';
import { formatDate, formatDateTime, formatNumber, formatPct } from '../lib/format';
import { fetchSourceStatus } from '../services/api';
import type { CalculationCheck, CalculationDifference } from '../types';

const DEFINITIONS: { name: string; definition: string }[] = [
  { name: 'Uptime %', definition: '1 − Σ outage minutes ÷ (1,440 × site-days reported). Outage-weighted, not an average of site percentages.' },
  { name: 'Daily uptime', definition: 'Uptime for sites in scope on the selected reporting date (workbook: Day wise Trend).' },
  { name: 'MTD uptime', definition: 'Uptime from the 1st of the month to the selected date (workbook: Summ, "Oct-26 MTD").' },
  { name: 'On-Air sites', definition: 'Sites with On-Air = "Yes". The default population (Population selector), matching the workbook\'s "Overall Up-Time".' },
  { name: 'O&M Start sites', definition: 'Sites with "O&M Start - <month>" = "Yes", matching the workbook\'s "O&M Start - Up-Time".' },
  { name: 'Uptime buckets', definition: 'Each site\'s MTD uptime grouped as <60, 60–90, 90–97, 97–98.5 and ≥98.5% (workbook Bucket formula).' },
  { name: 'Monthly uptime', definition: 'Uptime per month from each site\'s "<month> Outage Min." column ÷ (1,440 × days in month × sites with a value), using today\'s scope flags. Sites with a blank month are excluded; the workbook counts them as 100% up, and both figures are shown.' },
  { name: 'Team performance', definition: 'The same uptime formula applied to the sites assigned to each CI or IE in the CI Name / IE Name columns. Blank or "-" names are grouped as Unassigned.' },
  { name: 'Reporting coverage', definition: 'Sites in scope with an outage value on the date ÷ sites in scope. Blank values are not treated as zero outage.' },
];

export function DataSourcePage() {
  const workbook = useWorkbook();
  const { data, error, loading } = useApiQuery(workbook.active ? `${workbook.version}|source` : null, fetchSourceStatus);
  const { hash } = useLocation();

  // Alerts link to a section (e.g. #calculation-check); scroll to it once the page has rendered.
  useEffect(() => {
    if (data && hash) document.getElementById(hash.slice(1))?.scrollIntoView({ block: 'start' });
  }, [data, hash]);

  if (!workbook.loading && !workbook.active) {
    return (
      <Alert className="max-w-2xl">
        <Info />
        <AlertTitle>No reporting data loaded</AlertTitle>
        <AlertDescription>
          {workbook.error?.message ?? workbook.message}{' '}
          <Link to="/workbook" className="font-medium text-foreground underline underline-offset-4">Open the Data Source page</Link>
        </AlertDescription>
      </Alert>
    );
  }

  if (error) {
    return (
      <Alert variant="destructive" className="max-w-2xl">
        <AlertTriangle />
        <AlertTitle>Data source unavailable</AlertTitle>
        <AlertDescription>{error.message}</AlertDescription>
      </Alert>
    );
  }
  if (loading || !data) return <Skeleton className="h-96 w-full" aria-label="Loading data source status" />;

  const warnings = data.warnings.filter((w) => w.severity === 'warning');
  const notes = data.warnings.filter((w) => w.severity === 'info');

  return (
    <div className="space-y-4">
      <PageHeading title="Data Source & Quality" subtitle="What the dashboard reads, what was validated, and how each figure is defined" />

      <div className="grid grid-cols-1 gap-4 lg:grid-cols-3">
        <Card className="lg:col-span-2">
          <CardHeader>
            <CardTitle className="text-sm font-semibold">Reporting data</CardTitle>
            <CardDescription className="text-xs">The data layer every page reads, filled by the imports on the <Link to="/workbook" className="underline underline-offset-4">Data Source</Link> page and by raw daily CSV uploads.</CardDescription>
          </CardHeader>
          <CardContent>
            <dl className="grid grid-cols-1 gap-x-6 gap-y-3 text-sm sm:grid-cols-2">
              <Item label="Workbook" value={data.source.workbook} />
              <Item label="Sheet" value={data.source.sheet} />
              <Item label="Last modified" value={formatDateTime(data.source.modified_at)} />
              <Item label="Uploaded" value={data.source.uploaded_at ? formatDateTime(data.source.uploaded_at) : 'Configured on the server'} />
              <Item label="Reporting month" value={data.month} />
              <Item label="Latest reporting date" value={formatDate(data.source.latest_reporting_date)} />
              <Item label="Reported days" value={`${data.reporting_dates.length} (${formatDate(data.reporting_dates[0])} – ${formatDate(data.reporting_dates.at(-1))})`} />
              <Item label="Missing days before latest" value={data.missing_dates.length ? data.missing_dates.map(formatDate).join(', ') : 'None'} />
            </dl>
          </CardContent>
        </Card>
        <Card>
          <CardHeader>
            <CardTitle className="text-sm font-semibold">Sites</CardTitle>
            <CardDescription className="text-xs">One row per site in Up-Time Report.</CardDescription>
          </CardHeader>
          <CardContent>
            <dl className="space-y-2 text-sm">
              <Item label="Total" value={formatNumber(data.site_counts.total)} inline />
              {Object.entries(data.site_counts.by_report_type).map(([type, count]) => (
                <Item key={type} label={type} value={formatNumber(count)} inline />
              ))}
              <Item label="On-Air" value={formatNumber(data.site_counts.on_air)} inline />
              <Item label="O&M Start" value={data.site_counts.om_start == null ? 'Not available' : formatNumber(data.site_counts.om_start)} inline />
            </dl>
          </CardContent>
        </Card>
      </div>

      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2 text-sm font-semibold">
            Validation results
            {warnings.length ? <Badge variant="destructive">{warnings.length} to review</Badge>
              : <Badge variant="secondary" className="gap-1"><CheckCircle2 className="size-3" /> No issues</Badge>}
          </CardTitle>
          <CardDescription className="text-xs">Checks run every time the workbook is loaded.</CardDescription>
        </CardHeader>
        <CardContent className="px-0">
          {data.warnings.length === 0 ? (
            <p className="px-4 text-sm text-muted-foreground">All structural and value checks passed.</p>
          ) : (
            <Table className="text-xs">
              <TableHeader>
                <TableRow className="bg-muted/50 hover:bg-muted/50">
                  <TableHead className="w-24">Severity</TableHead>
                  <TableHead>Finding</TableHead>
                  <TableHead className="w-20 text-right">Count</TableHead>
                  <TableHead>Examples</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {[...warnings, ...notes].map((w) => (
                  <TableRow key={w.code}>
                    <TableCell>
                      {w.severity === 'warning'
                        ? <span className="inline-flex items-center gap-1 text-amber-700"><AlertTriangle className="size-3.5" /> Review</span>
                        : <span className="inline-flex items-center gap-1 text-muted-foreground"><Info className="size-3.5" /> Note</span>}
                    </TableCell>
                    <TableCell className="whitespace-normal">{w.message}</TableCell>
                    <TableCell className="text-right tabular-nums">{formatNumber(w.count)}</TableCell>
                    <TableCell className="font-mono text-[11px] whitespace-normal text-muted-foreground">{w.examples.join('; ') || '—'}</TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          )}
        </CardContent>
      </Card>

      <CalculationCheckCard check={data.calculation_check} />

      <Card>
        <CardHeader>
          <CardTitle className="text-sm font-semibold">Worksheets ({data.sheets.length})</CardTitle>
          <CardDescription className="text-xs">
            All figures are calculated from Up-Time Report. The summary sheets are formulas over it; their values are never
            copied, only compared with the dashboard's own results in the calculation check above.
          </CardDescription>
        </CardHeader>
        <CardContent>
          <dl className="divide-y text-sm">
            {data.sheets.map((sheet) => (
              <div key={sheet.name} className="grid grid-cols-1 gap-1 py-2 sm:grid-cols-[12rem_1fr]">
                <dt className="font-medium">{sheet.name}</dt>
                <dd className="text-muted-foreground">{sheet.role}</dd>
              </div>
            ))}
          </dl>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle className="text-sm font-semibold">Definitions</CardTitle>
          <CardDescription className="text-xs">Reproduced from the workbook's summary sheets and reconciled against their values. See docs/business-rules.md.</CardDescription>
        </CardHeader>
        <CardContent>
          <dl className="divide-y text-sm">
            {DEFINITIONS.map((d) => (
              <div key={d.name} className="grid grid-cols-1 gap-1 py-2.5 sm:grid-cols-[12rem_1fr]">
                <dt className="font-medium">{d.name}</dt>
                <dd className="text-muted-foreground">{d.definition}</dd>
              </div>
            ))}
          </dl>
        </CardContent>
      </Card>
    </div>
  );
}

function CalculationCheckCard({ check }: { check: CalculationCheck }) {
  const listed = check.differences.length;
  return (
    <Card id="calculation-check" className="scroll-mt-20">
      <CardHeader>
        <CardTitle className="flex items-center gap-2 text-sm font-semibold">
          Calculation check
          {check.difference_count ? <Badge variant="destructive">{check.difference_count} major {check.difference_count === 1 ? 'difference' : 'differences'}</Badge>
            : check.checked ? <Badge variant="secondary" className="gap-1"><CheckCircle2 className="size-3" /> All match</Badge>
              : <Badge variant="outline">Nothing to compare</Badge>}
        </CardTitle>
        <CardDescription className="text-xs">
          {check.checked
            ? `${formatNumber(check.checked)} current-month figures in ${check.sheets.join(' and ')} were recalculated from the daily outage minutes, for the site population each formula divides by. `
              + `A difference is major when uptime differs by ${check.tolerance_pts} percentage points or more, or a site count differs at all.`
            : 'No current-month summary tables (Summ, Day wise Trend) were found in this workbook to compare with.'}
          {' '}Earlier months are not compared: Summ's monthly totals are frozen pasted values.
        </CardDescription>
      </CardHeader>
      {listed > 0 && (
        <CardContent className="px-0">
          <Table className="text-xs">
            <TableHeader>
              <TableRow className="bg-muted/50 hover:bg-muted/50">
                <TableHead className="w-36">Workbook cell</TableHead>
                <TableHead>Figure</TableHead>
                <TableHead className="w-24 text-right">Workbook</TableHead>
                <TableHead className="w-24 text-right">Dashboard</TableHead>
                <TableHead className="w-24 text-right">Difference</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {check.differences.map((d) => (
                <TableRow key={`${d.sheet}!${d.cell}`}>
                  <TableCell className="font-mono text-[11px]">{d.sheet}!{d.cell}</TableCell>
                  <TableCell className="whitespace-normal">
                    {d.description}
                    {d.formula && <span className="mt-0.5 block font-mono text-[11px] break-all text-muted-foreground">{d.formula}</span>}
                  </TableCell>
                  <TableCell className="text-right tabular-nums">{formatFigure(d, d.workbook)}</TableCell>
                  <TableCell className="text-right tabular-nums">{formatFigure(d, d.dashboard)}</TableCell>
                  <TableCell className="text-right font-medium tabular-nums text-red-700">
                    {d.difference > 0 ? '+' : ''}{d.unit === 'sites' ? formatNumber(d.difference) : `${d.difference.toFixed(2)} pts`}
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
          {check.difference_count > listed && (
            <p className="px-4 pt-2 text-xs text-muted-foreground">Showing the {listed} largest of {formatNumber(check.difference_count)} differences.</p>
          )}
        </CardContent>
      )}
    </Card>
  );
}

const formatFigure = (d: CalculationDifference, value: number) => (d.unit === 'sites' ? formatNumber(value) : formatPct(value));

function Item({ label, value, inline }: { label: string; value: string; inline?: boolean }) {
  return (
    <div className={inline ? 'flex items-baseline justify-between gap-3' : 'min-w-0'}>
      <dt className="text-xs text-muted-foreground">{label}</dt>
      <dd className={inline ? 'font-medium tabular-nums' : 'mt-0.5 break-words'}>{value}</dd>
    </div>
  );
}
