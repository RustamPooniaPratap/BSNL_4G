import { Clock } from 'lucide-react';
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert';
import { cn } from '@/lib/utils';
import { describeMissing } from '../../lib/reportingStatus';
import type { Continuity, MissingUnits, ReportingStatus } from '../../types/reporting';

const TONE = {
  complete: 'border-emerald-300 bg-emerald-50 text-emerald-800',
  provisional: 'border-amber-300 bg-amber-50 text-amber-800',
  incomplete: 'border-orange-300 bg-red-50 text-red-800',
} as const;

interface PeriodStatusBadgeProps {
  /** Complete / Provisional of the period; missing in older responses (then nothing is shown). */
  status?: ReportingStatus | null;
  /** Set for a finalized month: overrides ``status``. */
  finalizationStatus?: string | null;
  /** Missing units, listed in the tooltip. */
  missing?: MissingUnits[] | null;
  className?: string;
}

/**
 * Small badge next to a weekly / monthly / period figure: "Complete" (green), "Provisional" (amber) or, for a month
 * finalized with missing data, "Incomplete — Missing Data" (red). Renders nothing without a status.
 */
export function PeriodStatusBadge({ status, finalizationStatus, missing, className }: PeriodStatusBadgeProps) {
  const kind = finalizationStatus === 'incomplete_missing_data' ? 'incomplete'
    : finalizationStatus === 'complete' || (!finalizationStatus && status === 'Complete') ? 'complete'
      : status === 'Provisional' ? 'provisional'
        : status === 'Complete' ? 'complete' : null;
  if (!kind) return null;
  const label = kind === 'incomplete' ? 'Incomplete — Missing Data' : kind === 'complete' ? 'Complete' : 'Provisional';
  const detail = describeMissing(missing);
  const title = kind === 'complete' ? (finalizationStatus === 'complete' ? 'Finalized: every reporting unit reported' : 'Every reporting unit reported')
    : detail ? `Missing: ${detail}` : kind === 'provisional' ? 'Not every reporting unit has reported yet' : 'Finalized with missing data';
  return (
    <span data-slot="period-status" data-status={kind} title={title}
      className={cn('inline-flex h-4.5 shrink-0 items-center rounded-full border px-1.5 text-[10px] leading-none font-medium whitespace-nowrap', TONE[kind], className)}>
      {label}
    </span>
  );
}

/**
 * Banner when the month to date is Provisional: "Provisional — awaiting LWE OD for 03 Oct". Nothing for a Complete
 * month to date or an older response without ``mtd_status``.
 */
export function ProvisionalBanner({ continuity, className }: { continuity: Continuity | null | undefined; className?: string }) {
  if (!continuity || continuity.mtd_status !== 'Provisional') return null;
  const missing = continuity.missing?.length ? continuity.missing
    : (continuity.date_status ?? []).filter((d) => d.status === 'Provisional').map((d) => ({ date: d.date, units: d.missing_units }));
  const detail = describeMissing(missing);
  return (
    <Alert className={cn('border-amber-300 bg-amber-50/70', className)} role="status" aria-label="Provisional figures">
      <Clock className="text-amber-700" />
      <AlertTitle>{detail ? `Provisional — awaiting ${detail}` : 'Provisional — not every reporting unit has reported yet'}</AlertTitle>
      <AlertDescription>
        Month-to-date figures use the data received so far and can change when the missing data arrives. Dates are not dropped because another unit is missing.
      </AlertDescription>
    </Alert>
  );
}
