import { useEffect, useState } from 'react';
import { ClipboardPen, Loader2 } from 'lucide-react';
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Input } from '@/components/ui/input';
import { Skeleton } from '@/components/ui/skeleton';
import {
  DataEntryHeader, Field, NoWorkbook, ReviewList, SelectField, UnknownSite, ValidatedLocally, type Step,
} from '../../components/data/DataEntry';
import { useWorkbook } from '../../context/workbook';
import { useApiQuery } from '../../hooks/useApiQuery';
import { useFilterOptions } from '../../hooks/useFilterOptions';
import { findSite, useSiteRegistry } from '../../hooks/useSiteRegistry';
import {
  VALIDATED_MESSAGES, fieldA11y, normaliseSiteId, outageError, outageWarning, parseDate, parseNumber, siteIdError,
} from '../../lib/dataEntry';
import { formatDate, formatMinutes } from '../../lib/format';
import { fetchSiteDetail } from '../../services/api';
import type { SiteRecord } from '../../types';

interface RowDraft {
  reportType: string;
  circle: string;
  date: string;
  siteId: string;
  outage: string;
}
const EMPTY: RowDraft = { reportType: '', circle: '', date: '', siteId: '', outage: '' };
const todayIso = () => new Date(Date.now() - new Date().getTimezoneOffset() * 60000).toISOString().slice(0, 10);

/** One daily reporting record (outage minutes for one site on one date) for an existing site. */
export function AddRowPage() {
  const workbook = useWorkbook();
  const options = useFilterOptions();
  const [draft, setDraft] = useState<RowDraft>(EMPTY);
  const [step, setStep] = useState<Step>('edit');
  const [showErrors, setShowErrors] = useState(false);
  const registry = useSiteRegistry(workbook.version, draft.reportType, draft.circle);
  const set = (changes: Partial<RowDraft>) => setDraft((d) => ({ ...d, ...changes }));

  const siteId = normaliseSiteId(draft.siteId);
  const formatError = draft.siteId ? siteIdError(draft.siteId, draft.reportType) : null;
  const site: SiteRecord | undefined = registry.sites?.get(siteId);
  const unknown = Boolean(registry.sites && siteId && !formatError && !site);
  const elsewhere = useApiQuery(unknown ? `${workbook.version}|find|${siteId}` : null, (signal) => findSite(siteId, signal));

  // Does the workbook already hold a value for this site on this date?
  const date = parseDate(draft.date);
  const detail = useApiQuery(site && date ? `${workbook.version}|detail|${site.report_type}|${site.site_id}` : null,
    (signal) => fetchSiteDetail(site!.site_id, site!.report_type, signal));
  const existing = detail.data?.daily.find((d) => d.date === date && d.reported);

  const errors = (() => {
    const e: Partial<Record<keyof RowDraft, string>> = {};
    if (!draft.reportType) e.reportType = 'Choose a report type.';
    if (!draft.circle) e.circle = 'Choose a circle.';
    if (!draft.date) e.date = 'Choose the reporting date.';
    else if (!date) e.date = 'Enter a valid date.';
    else if (date > todayIso()) e.date = 'The reporting date cannot be in the future.';
    const idError = siteIdError(draft.siteId, draft.reportType);
    if (idError) e.siteId = idError;
    else if (unknown) e.siteId = `Site ${siteId} is not in the ${draft.reportType} · ${draft.circle} master data.`;
    const outage = outageError(draft.outage);
    if (outage) e.outage = outage;
    return e;
  })();
  const visible = (field: keyof RowDraft) => (showErrors || (field === 'siteId' && unknown) ? errors[field] : undefined);

  const month = options.data?.month;
  const warnings = [
    outageWarning(draft.outage),
    date && month && (date < month.start || date > month.end)
      ? `${formatDate(date)} is outside the workbook's reporting month (${month.label}).` : null,
    existing ? `The workbook already has ${formatMinutes(existing.outage_minutes)} for ${siteId} on ${formatDate(date)}. This record would conflict with it.` : null,
  ].filter((w): w is string => Boolean(w));

  useEffect(() => { if (step === 'done') window.scrollTo?.({ top: 0 }); }, [step]);

  if (!workbook.loading && !workbook.active) return <NoWorkbook />;
  if (!options.data) return <Skeleton className="h-96 w-full" aria-label="Loading form" />;

  const circles = options.data.circles.filter((c) => !draft.reportType || c.report_types.includes(draft.reportType));
  const canReview = Object.keys(errors).length === 0 && !registry.loading && Boolean(site);
  const review = () => {
    setShowErrors(true);
    if (canReview) setStep('review');
  };

  return (
    <div className="space-y-4">
      <DataEntryHeader
        icon={<ClipboardPen />}
        accent="bg-blue-50 text-blue-700"
        title="Add row"
        description="Prepare one daily reporting record (outage minutes for one site on one date) for a site that already exists in the master data."
        step={step}
      />

      {step === 'done' ? (
        <ValidatedLocally message={VALIDATED_MESSAGES.row}>
          <div className="mt-3 flex flex-wrap gap-2">
            <Button size="sm" onClick={() => { setDraft(EMPTY); setShowErrors(false); setStep('edit'); }}>Prepare another row</Button>
            <Button size="sm" variant="outline" onClick={() => setStep('edit')}>Back to this record</Button>
          </div>
        </ValidatedLocally>
      ) : step === 'review' ? (
        <Card>
          <CardHeader>
            <CardTitle className="text-sm font-semibold">Review the record</CardTitle>
            <CardDescription className="text-xs">Check the details, then confirm. Confirming only validates in the browser.</CardDescription>
          </CardHeader>
          <CardContent className="space-y-3">
            <ReviewList items={[
              { label: 'Report type', value: draft.reportType },
              { label: 'Circle', value: draft.circle },
              { label: 'Reporting date', value: formatDate(date) },
              { label: 'Site ID', value: <span className="font-mono">{siteId}</span> },
              { label: 'Site name', value: site?.site_name || '—' },
              { label: 'Outage minutes', value: formatMinutes(parseNumber(draft.outage)) },
              { label: 'On-Air (master data)', value: site?.on_air ? 'Yes' : 'No' },
              { label: 'O&M Start (master data)', value: site?.om_start ? 'Yes' : 'No' },
            ]} />
            <WarningList warnings={warnings} />
            <div className="flex flex-wrap gap-2">
              <Button onClick={() => setStep('done')}>Confirm record</Button>
              <Button variant="outline" onClick={() => setStep('edit')}>Back to edit</Button>
            </div>
          </CardContent>
        </Card>
      ) : (
        <Card>
          <CardHeader>
            <CardTitle className="text-sm font-semibold">Record details</CardTitle>
            <CardDescription className="text-xs">Fields marked * are required.</CardDescription>
          </CardHeader>
          <CardContent>
            <form noValidate onSubmit={(e) => { e.preventDefault(); review(); }} className="space-y-4">
              <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3">
                <Field id="row-report-type" label="Report type" required error={visible('reportType')}>
                  <SelectField id="row-report-type" value={draft.reportType} placeholder="Choose report type" error={visible('reportType')}
                    options={options.data.report_types.map((t) => ({ value: t.value, label: t.label }))}
                    onChange={(reportType) => set({ reportType, circle: options.data!.circles.find((c) => c.value === draft.circle)?.report_types.includes(reportType) ? draft.circle : '' })} />
                </Field>
                <Field id="row-circle" label="Circle" required error={visible('circle')}>
                  <SelectField id="row-circle" value={draft.circle} placeholder={draft.reportType ? 'Choose circle' : 'Choose report type first'}
                    disabled={!draft.reportType} error={visible('circle')}
                    options={circles.map((c) => ({ value: c.value, label: c.label }))} onChange={(circle) => set({ circle })} />
                </Field>
                <Field id="row-date" label="Reporting date" required error={visible('date')}
                  hint={month ? `Workbook month: ${month.label}` : undefined}>
                  <Input type="date" {...fieldA11y('row-date', visible('date'))} value={draft.date} max={todayIso()}
                    onChange={(e) => set({ date: e.target.value })} />
                </Field>
                <Field id="row-site" label="Site ID / BTS IP ID" required error={visible('siteId') ?? formatError}
                  hint={registry.loading ? 'Loading the circle\'s sites…' : registry.sites ? `${registry.sites.size.toLocaleString('en-IN')} sites in ${draft.reportType} · ${draft.circle}` : 'Choose report type and circle to check the site'}>
                  <Input {...fieldA11y('row-site', visible('siteId') ?? formatError)} value={draft.siteId} list="row-site-options" autoComplete="off"
                    placeholder={draft.reportType === 'LWE' ? 'e.g. LWEBH0303' : 'e.g. UVMPBPL00012'} maxLength={20}
                    onChange={(e) => set({ siteId: e.target.value.toUpperCase() })} className="font-mono uppercase placeholder:font-sans placeholder:normal-case" />
                  <datalist id="row-site-options">
                    {[...(registry.sites?.values() ?? [])].map((s) => <option key={s.site_id} value={s.site_id}>{s.site_name}</option>)}
                  </datalist>
                </Field>
                <Field id="row-outage" label="Outage minutes" required error={visible('outage')} warning={outageWarning(draft.outage)}
                  hint="Total outage on that date, 0 to 1,440 minutes.">
                  <Input {...fieldA11y('row-outage', visible('outage'), outageWarning(draft.outage))} inputMode="decimal" value={draft.outage}
                    placeholder="0" onChange={(e) => set({ outage: e.target.value })} />
                </Field>
              </div>

              {unknown && (
                <UnknownSite siteId={siteId} reportType={draft.reportType} circle={draft.circle}
                  elsewhere={elsewhere.data} checking={elsewhere.loading}
                  onUse={(s) => set({ reportType: s.report_type, circle: s.circle })} />
              )}
              {registry.error && (
                <Alert variant="destructive"><AlertTitle>Master data could not be loaded</AlertTitle><AlertDescription>{registry.error.message}</AlertDescription></Alert>
              )}
              {site && <SiteSummary site={site} />}
              {site && <WarningList warnings={warnings.filter((w) => !w.startsWith('More than'))} />}

              <div className="flex flex-wrap items-center gap-2">
                <Button type="submit" disabled={registry.loading}>
                  {registry.loading && <Loader2 className="animate-spin" />} Review record
                </Button>
                <Button type="button" variant="ghost" onClick={() => { setDraft(EMPTY); setShowErrors(false); }}>Clear</Button>
                {showErrors && !canReview && <span className="text-xs text-destructive">Fix the highlighted fields to continue.</span>}
              </div>
            </form>
          </CardContent>
        </Card>
      )}
    </div>
  );
}

function SiteSummary({ site }: { site: SiteRecord }) {
  return (
    <div className="rounded-lg border bg-muted/40 px-4 py-3">
      <p className="mb-2 text-xs font-medium text-muted-foreground">Site found in the master data (read-only)</p>
      <ReviewList items={[
        { label: 'Site name', value: site.site_name || '—' },
        { label: 'OA / BA', value: `${site.oa || '—'} / ${site.ba || '—'}` },
        { label: 'On-Air', value: site.on_air ? 'Yes' : 'No' },
        { label: 'O&M Start', value: site.om_start ? 'Yes' : 'No' },
        { label: 'Power', value: site.eb || '—' },
        { label: 'IE / CI', value: `${site.ie_name} / ${site.ci_name}` },
      ]} />
    </div>
  );
}

function WarningList({ warnings }: { warnings: string[] }) {
  if (!warnings.length) return null;
  return (
    <Alert className="border-amber-300 bg-amber-50/70">
      <AlertTitle>Please check</AlertTitle>
      <AlertDescription>
        <ul className="list-disc pl-4">{warnings.map((w) => <li key={w}>{w}</li>)}</ul>
      </AlertDescription>
    </Alert>
  );
}
