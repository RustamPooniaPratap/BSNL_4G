import { formatShortDate } from './format';
import type { MissingUnits } from '../types/reporting';

/**
 * "LWE OD for 03 Oct; 4G Saturation MP for 02 Oct, 03 Oct": the missing reporting units with their dates, grouped by
 * unit. Empty when nothing is listed.
 */
export function describeMissing(missing: MissingUnits[] | null | undefined, limit = 6): string {
  const byUnit = new Map<string, string[]>();
  for (const entry of missing ?? []) {
    for (const unit of entry.units ?? []) byUnit.set(unit, [...(byUnit.get(unit) ?? []), entry.date]);
  }
  const parts = [...byUnit].map(([unit, dates]) => `${unit} for ${dates.map(formatShortDate).join(', ')}`);
  if (parts.length > limit) return `${parts.slice(0, limit).join('; ')} and ${parts.length - limit} more`;
  return parts.join('; ');
}

/** Text status of a period for data tables: "Provisional (missing LWE OD for 03 Oct)", "Complete", or "—" without a status. */
export function statusText(p: { status?: string | null; finalization_status?: string | null; missing?: MissingUnits[] | null }) {
  if (p.finalization_status === 'incomplete_missing_data') return 'Incomplete — Missing Data';
  if (p.finalization_status === 'complete') return 'Complete (finalized)';
  if (!p.status) return '—';
  const detail = p.status === 'Provisional' ? describeMissing(p.missing) : '';
  return detail ? `${p.status} (missing ${detail})` : p.status;
}
