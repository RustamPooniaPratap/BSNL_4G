import { useMemo, useState } from 'react';
import { Link, useSearchParams } from 'react-router-dom';
import { Loader2, MapPinPlus, SearchCheck } from 'lucide-react';
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert';
import { Button, buttonVariants } from '@/components/ui/button';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Input } from '@/components/ui/input';
import { Skeleton } from '@/components/ui/skeleton';
import { DataEntryHeader, Field, NoWorkbook, ReviewList, SelectField, ValidatedLocally, type Step } from '../../components/data/DataEntry';
import { useWorkbook } from '../../context/workbook';
import { useApiQuery } from '../../hooks/useApiQuery';
import { findSite, useSiteRegistry } from '../../hooks/useSiteRegistry';
import { SITE_ID_PATTERNS, VALIDATED_MESSAGES, fieldA11y, normaliseSiteId, siteIdError } from '../../lib/dataEntry';
import { fetchFilterOptions } from '../../services/api';
import type { SiteRecord } from '../../types';

/** Master site attributes, as in the Up-Time Report columns (Project, Circle, btsIpId, Site name, OA, BA, On-Air, EB, O&M Start, IE, CI). */
interface SiteDraft {
  reportType: string;
  circle: string;
  siteId: string;
  siteName: string;
  oa: string;
  ba: string;
  eb: string;
  onAir: string;
  omStart: string;
  ieName: string;
  ciName: string;
}
const EMPTY: SiteDraft = { reportType: '', circle: '', siteId: '', siteName: '', oa: '', ba: '', eb: '', onAir: '', omStart: '', ieName: '', ciName: '' };
const YES_NO = [{ value: 'Yes', label: 'Yes' }, { value: 'No', label: 'No' }];
const POWER = [{ value: 'EB', label: 'EB' }, { value: 'N-EB', label: 'N-EB' }];
const TEXT_MAX = 80;

/** A new master site record, separate from daily reporting. Duplicate Site IDs are refused. */
export function AddSitePage() {
  const workbook = useWorkbook();
  const options = useApiQuery(workbook.active ? `${workbook.version}|filters` : null, fetchFilterOptions);
  const [params] = useSearchParams();
  // Pre-filled when arriving from an unknown Site ID in Add Row or Upload CSV.
  const [draft, setDraft] = useState<SiteDraft>(() => ({
    ...EMPTY,
    siteId: normaliseSiteId(params.get('site_id') ?? ''),
    reportType: params.get('report_type') ?? '',
    circle: params.get('circle') ?? '',
  }));
  const [step, setStep] = useState<Step>('edit');
  const [showErrors, setShowErrors] = useState(false);
  const set = (changes: Partial<SiteDraft>) => setDraft((d) => ({ ...d, ...changes }));
  const registry = useSiteRegistry(workbook.version, draft.reportType, draft.circle);

  const siteId = normaliseSiteId(draft.siteId);
  const formatError = draft.siteId ? siteIdError(draft.siteId, draft.reportType) : null;
  // Site IDs are unique across both report types in the workbook, so look everywhere.
  const lookup = useApiQuery(siteId && !formatError && draft.reportType ? `${workbook.version}|find|${siteId}` : null, (signal) => findSite(siteId, signal));
  const duplicate: SiteRecord | null = lookup.data ?? null;

  const errors = useMemo(() => {
    const e: Partial<Record<keyof SiteDraft, string>> = {};
    if (!draft.reportType) e.reportType = 'Choose a report type.';
    if (!draft.circle) e.circle = 'Choose a circle.';
    const idError = siteIdError(draft.siteId, draft.reportType);
    if (idError) e.siteId = idError;
    else if (duplicate) e.siteId = `${duplicate.site_id} already exists (${duplicate.report_type} · ${duplicate.circle}).`;
    if (!draft.siteName.trim()) e.siteName = 'Site name is required.';
    else if (draft.siteName.trim().length < 2) e.siteName = 'Site name is too short.';
    if (!draft.onAir) e.onAir = 'Choose the On-Air status.';
    return e;
  }, [draft, duplicate]);
  const visible = (field: keyof SiteDraft) => (showErrors || (field === 'siteId' && duplicate) ? errors[field] : undefined);

  // Existing names in the circle, offered as suggestions (free text is still allowed).
  const names = useMemo(() => {
    const sites = [...(registry.sites?.values() ?? [])];
    const unique = (values: string[]) => [...new Set(values.filter((v) => v && v !== 'Unassigned'))].sort();
    return { oa: unique(sites.map((s) => s.oa)), ba: unique(sites.map((s) => s.ba)), ie: unique(sites.map((s) => s.ie_name)), ci: unique(sites.map((s) => s.ci_name)) };
  }, [registry.sites]);

  if (!workbook.loading && !workbook.active) return <NoWorkbook />;
  if (!options.data) return <Skeleton className="h-96 w-full" aria-label="Loading form" />;

  const circles = options.data.circles.filter((c) => !draft.reportType || c.report_types.includes(draft.reportType));
  const canReview = Object.keys(errors).length === 0 && !lookup.loading && !lookup.error;
  const review = () => { setShowErrors(true); if (canReview) setStep('review'); };
  const pattern = SITE_ID_PATTERNS[draft.reportType];
  const text = (field: 'siteName' | 'oa' | 'ba' | 'ieName' | 'ciName', placeholder: string, list?: string) => (
    <Input {...fieldA11y(`site-${field}`, visible(field))} value={draft[field]} placeholder={placeholder} maxLength={TEXT_MAX}
      list={list} autoComplete="off" onChange={(e) => set({ [field]: e.target.value })} />
  );

  return (
    <div className="space-y-5">
      <DataEntryHeader
        icon={<MapPinPlus />}
        accent="bg-emerald-50 text-emerald-700"
        title="Add new site"
        description="Prepare a new site for the master site list. This is separate from daily reporting: daily rows and CSV uploads can only use sites that already exist."
        step={step}
      />

      {step === 'done' ? (
        <ValidatedLocally message={VALIDATED_MESSAGES.site}>
          <p className="mt-1">The site is not added to the Master workbook or the database, so Add Row and Upload CSV will still treat it as unknown.</p>
          <div className="mt-3 flex flex-wrap gap-2">
            <Button size="sm" onClick={() => { setDraft(EMPTY); setShowErrors(false); setStep('edit'); }}>Prepare another site</Button>
            <Button size="sm" variant="outline" onClick={() => setStep('edit')}>Back to this site</Button>
          </div>
        </ValidatedLocally>
      ) : step === 'review' ? (
        <Card>
          <CardHeader>
            <CardTitle className="text-sm font-semibold">Review the new site</CardTitle>
            <CardDescription className="text-xs">Confirming only validates in the browser; the site is not registered anywhere.</CardDescription>
          </CardHeader>
          <CardContent className="space-y-4">
            <ReviewList items={[
              { label: 'Report type', value: draft.reportType },
              { label: 'Circle', value: draft.circle },
              { label: 'Site ID / BTS IP ID', value: <span className="font-mono">{siteId}</span> },
              { label: 'Site name', value: draft.siteName.trim() },
              { label: 'OA / BA', value: `${draft.oa.trim() || '—'} / ${draft.ba.trim() || '—'}` },
              { label: 'Power (EB / N-EB)', value: draft.eb || '—' },
              { label: 'On-Air', value: draft.onAir },
              { label: 'O&M Start (current month)', value: draft.omStart || '—' },
              { label: 'IE / CI', value: `${draft.ieName.trim() || '—'} / ${draft.ciName.trim() || '—'}` },
            ]} />
            <div className="flex flex-wrap gap-2">
              <Button onClick={() => setStep('done')}>Confirm site details</Button>
              <Button variant="outline" onClick={() => setStep('edit')}>Back to edit</Button>
            </div>
          </CardContent>
        </Card>
      ) : (
        <Card>
          <CardHeader>
            <CardTitle className="text-sm font-semibold">Site details</CardTitle>
            <CardDescription className="text-xs">
              Fields marked * are required, as in the workbook's Up-Time Report (Project, Circle, btsIpId, Site name, On-Air).
            </CardDescription>
          </CardHeader>
          <CardContent>
            <form noValidate onSubmit={(e) => { e.preventDefault(); review(); }} className="space-y-5">
              <fieldset className="grid min-w-0 grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3">
                <legend className="mb-2 text-xs font-semibold text-muted-foreground uppercase">Identity</legend>
                <Field id="site-report-type" label="Report type" required error={visible('reportType')}>
                  <SelectField id="site-report-type" value={draft.reportType} placeholder="Choose report type" error={visible('reportType')}
                    options={options.data.report_types.map((t) => ({ value: t.value, label: t.label }))}
                    onChange={(reportType) => set({ reportType, circle: options.data!.circles.find((c) => c.value === draft.circle)?.report_types.includes(reportType) ? draft.circle : '' })} />
                </Field>
                <Field id="site-circle" label="Circle" required error={visible('circle')} hint="Existing circles only.">
                  <SelectField id="site-circle" value={draft.circle} disabled={!draft.reportType} error={visible('circle')}
                    placeholder={draft.reportType ? 'Choose circle' : 'Choose report type first'}
                    options={circles.map((c) => ({ value: c.value, label: c.label }))} onChange={(circle) => set({ circle })} />
                </Field>
                <Field id="site-siteId" label="Site ID / BTS IP ID" required error={visible('siteId') ?? formatError}
                  hint={lookup.loading ? 'Checking for an existing site…' : pattern ? `Format like ${pattern.example}` : 'Choose the report type to check the format'}>
                  <Input {...fieldA11y('site-siteId', visible('siteId') ?? formatError)} value={draft.siteId} maxLength={20} autoComplete="off"
                    className="font-mono uppercase placeholder:font-sans placeholder:normal-case" placeholder={pattern?.example} onChange={(e) => set({ siteId: e.target.value.toUpperCase() })} />
                </Field>
                <Field id="site-siteName" label="Site name" required error={visible('siteName')}>{text('siteName', 'e.g. Bhadwa Kheda')}</Field>
              </fieldset>

              {duplicate && (
                <Alert variant="destructive">
                  <SearchCheck />
                  <AlertTitle>{duplicate.site_id} is already registered</AlertTitle>
                  <AlertDescription>
                    <p>{duplicate.site_name} · {duplicate.report_type} · {duplicate.circle} · OA {duplicate.oa || '—'}. A site ID can be registered only once.</p>
                    <Link to={`/?${new URLSearchParams({ report_type: duplicate.report_type, circle: duplicate.circle, scope: 'all' })}`}
                      className={buttonVariants({ size: 'sm', variant: 'outline', className: 'mt-2' })}>
                      Review sites in {duplicate.circle}
                    </Link>
                  </AlertDescription>
                </Alert>
              )}
              {lookup.error && (
                <Alert variant="destructive"><AlertTitle>Could not check for an existing site</AlertTitle><AlertDescription>{lookup.error.message}</AlertDescription></Alert>
              )}

              <fieldset className="grid min-w-0 grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3">
                <legend className="mb-2 text-xs font-semibold text-muted-foreground uppercase">Location and status</legend>
                <Field id="site-oa" label="OA" hint="Operating area, e.g. Bhopal.">{text('oa', 'OA', 'site-oa-options')}</Field>
                <Field id="site-ba" label="BA (Business Area)">{text('ba', 'BA', 'site-ba-options')}</Field>
                <Field id="site-eb" label="Power (EB / N-EB)">
                  <SelectField id="site-eb" value={draft.eb} placeholder="Choose" options={POWER} onChange={(eb) => set({ eb })} />
                </Field>
                <Field id="site-onAir" label="On-Air" required error={visible('onAir')}>
                  <SelectField id="site-onAir" value={draft.onAir} placeholder="Choose" options={YES_NO} error={visible('onAir')} onChange={(onAir) => set({ onAir })} />
                </Field>
                <Field id="site-omStart" label="O&M Start (current month)">
                  <SelectField id="site-omStart" value={draft.omStart} placeholder="Choose" options={YES_NO} onChange={(omStart) => set({ omStart })} />
                </Field>
              </fieldset>

              <fieldset className="grid min-w-0 grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3">
                <legend className="mb-2 text-xs font-semibold text-muted-foreground uppercase">Responsibility</legend>
                <Field id="site-ieName" label="IE Name">{text('ieName', 'Engineer', 'site-ie-options')}</Field>
                <Field id="site-ciName" label="CI Name">{text('ciName', 'Cluster in-charge', 'site-ci-options')}</Field>
              </fieldset>
              {(['oa', 'ba', 'ie', 'ci'] as const).map((k) => (
                <datalist key={k} id={`site-${k}-options`}>{names[k].map((n) => <option key={n} value={n} />)}</datalist>
              ))}

              <div className="flex flex-wrap items-center gap-2">
                <Button type="submit" disabled={lookup.loading}>{lookup.loading && <Loader2 className="animate-spin" />} Review site</Button>
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
