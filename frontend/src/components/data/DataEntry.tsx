import type { ReactNode } from 'react';
import { CircleAlert, TriangleAlert } from 'lucide-react';
import { Label } from '@/components/ui/label';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import { cn } from '@/lib/utils';

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
