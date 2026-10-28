import type { ReactNode } from 'react';
import { Link } from 'react-router-dom';
import { CheckCircle2, CircleAlert, FileUp, Info, MapPinPlus, TriangleAlert } from 'lucide-react';
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert';
import { Button, buttonVariants } from '@/components/ui/button';
import { Card } from '@/components/ui/card';
import { Label } from '@/components/ui/label';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import { cn } from '@/lib/utils';
import { newSiteLink } from '../../lib/dataEntry';
import type { SiteRecord } from '../../types';

export type Step = 'edit' | 'review' | 'done';

export function DataEntryHeader({ icon, title, description, step, accent }: {
  icon: ReactNode; title: string; description: string; step: Step; accent: string;
}) {
  const steps: { id: Step; label: string }[] = [{ id: 'edit', label: 'Details' }, { id: 'review', label: 'Review' }, { id: 'done', label: 'Validated' }];
  const current = steps.findIndex((s) => s.id === step);
  return (
    <header className="space-y-3">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="flex items-start gap-3">
          <span className={cn('flex size-10 shrink-0 items-center justify-center rounded-lg [&_svg]:size-5', accent)} aria-hidden="true">{icon}</span>
          <div>
            <h1 className="text-xl font-semibold tracking-tight">{title}</h1>
            <p className="mt-0.5 max-w-3xl text-sm text-muted-foreground">{description}</p>
          </div>
        </div>
        <ol className="flex items-center gap-1.5 text-xs" aria-label="Progress">
          {steps.map((s, i) => (
            <li key={s.id} className="flex items-center gap-1.5" aria-current={i === current ? 'step' : undefined}>
              <span className={cn('flex size-5 items-center justify-center rounded-full border text-[10px] font-semibold',
                i < current && 'border-primary bg-primary text-primary-foreground',
                i === current && 'border-primary text-primary',
                i > current && 'text-muted-foreground')}>{i + 1}</span>
              <span className={cn(i === current ? 'font-medium' : 'text-muted-foreground')}>{s.label}</span>
              {i < steps.length - 1 && <span className="mx-1 h-px w-4 bg-border" aria-hidden="true" />}
            </li>
          ))}
        </ol>
      </div>
      <LocalOnlyNotice />
    </header>
  );
}

export function LocalOnlyNotice() {
  return (
    <Alert className="border-sky-200 bg-sky-50/60">
      <Info className="text-sky-700" />
      <AlertTitle>Checked in your browser only</AlertTitle>
      <AlertDescription>
        Nothing on this page is saved or sent to the server, the database or the Master workbook. Checks against master
        data use the workbook currently loaded and are preliminary; they do not guarantee database uniqueness.
      </AlertDescription>
    </Alert>
  );
}

export function NoWorkbook() {
  return (
    <Card className="mx-auto mt-10 max-w-xl items-center gap-3 px-8 py-10 text-center">
      <FileUp className="size-8 text-muted-foreground" aria-hidden="true" />
      <h1 className="text-lg font-semibold">No Master workbook loaded</h1>
      <p className="text-sm text-muted-foreground">Site checks need the master data, so upload the consolidated workbook first.</p>
      <Link to="/workbook" className={buttonVariants({ size: 'sm' })}><FileUp /> Upload workbook</Link>
    </Card>
  );
}

/** Label, required marker, hint and inline error for one form control. */
export function Field({ id, label, required, error, warning, hint, children, className, plain }: {
  id: string; label: string; required?: boolean; error?: string | null; warning?: string | null; hint?: ReactNode;
  children: ReactNode; className?: string;
  /** Filters and settings: no "(optional)" marker. */
  plain?: boolean;
}) {
  return (
    <div className={cn('flex min-w-0 flex-col gap-1.5', className)}>
      <Label htmlFor={id} className="text-xs font-medium">
        {label}
        {required ? <span className="text-destructive" aria-hidden="true">*</span> : plain ? null : <span className="font-normal text-muted-foreground">(optional)</span>}
      </Label>
      {children}
      {error ? (
        <p id={`${id}-error`} className="flex items-start gap-1 text-xs text-destructive" role="alert">
          <CircleAlert className="mt-px size-3.5 shrink-0" aria-hidden="true" /> {error}
        </p>
      ) : warning ? (
        <p id={`${id}-warning`} className="flex items-start gap-1 text-xs text-amber-700">
          <TriangleAlert className="mt-px size-3.5 shrink-0" aria-hidden="true" /> {warning}
        </p>
      ) : hint ? <p className="text-xs text-muted-foreground">{hint}</p> : null}
    </div>
  );
}

export function SelectField({ id, value, onChange, options, placeholder, disabled, error }: {
  id: string; value: string; onChange: (value: string) => void; options: { value: string; label: string }[];
  placeholder: string; disabled?: boolean; error?: string | null;
}) {
  return (
    <Select value={value || undefined} onValueChange={onChange} disabled={disabled}>
      <SelectTrigger id={id} className="w-full" aria-invalid={error ? true : undefined}><SelectValue placeholder={placeholder} /></SelectTrigger>
      <SelectContent>
        {options.map((o) => <SelectItem key={o.value} value={o.value}>{o.label}</SelectItem>)}
      </SelectContent>
    </Select>
  );
}

export function ReviewList({ items }: { items: { label: string; value: ReactNode }[] }) {
  return (
    <dl className="grid grid-cols-1 gap-x-6 gap-y-3 text-sm sm:grid-cols-2 lg:grid-cols-3">
      {items.map((item) => (
        <div key={item.label} className="min-w-0">
          <dt className="text-xs text-muted-foreground">{item.label}</dt>
          <dd className="mt-0.5 font-medium break-words">{item.value}</dd>
        </div>
      ))}
    </dl>
  );
}

export function ValidatedLocally({ message, children }: { message: string; children?: ReactNode }) {
  return (
    <Alert className="border-emerald-200 bg-emerald-50/70" role="status">
      <CheckCircle2 className="text-emerald-700" />
      <AlertTitle>{message}</AlertTitle>
      <AlertDescription>
        Nothing has been saved. The details stay on this page only until you leave or start again.
        {children}
      </AlertDescription>
    </Alert>
  );
}

export function UnknownSite({ siteId, reportType, circle, elsewhere, checking, onUse }: {
  siteId: string; reportType: string; circle: string; elsewhere: SiteRecord | null; checking: boolean; onUse?: (site: SiteRecord) => void;
}) {
  return (
    <Alert className="border-amber-300 bg-amber-50/70">
      <MapPinPlus className="text-amber-700" />
      <AlertTitle>Site {siteId} is not in the {reportType} · {circle} master data</AlertTitle>
      <AlertDescription>
        {checking ? 'Checking the other circles…' : elsewhere ? (
          <span>
            It belongs to <strong>{elsewhere.report_type} · {elsewhere.circle}</strong> ({elsewhere.site_name}).
            {onUse && <Button type="button" variant="link" size="sm" className="h-auto px-1" onClick={() => onUse(elsewhere)}>Use that circle</Button>}
          </span>
        ) : (
          <span>
            Daily records can only be prepared for existing sites, and unknown sites are never created automatically.{' '}
            <Link to={newSiteLink(siteId, reportType, circle)} className={buttonVariants({ size: 'sm', variant: 'outline', className: 'mt-2' })}>
              <MapPinPlus /> Add new site {siteId}
            </Link>
          </span>
        )}
      </AlertDescription>
    </Alert>
  );
}
