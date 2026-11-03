import { AlertCircle } from 'lucide-react';
import { DEMO_DATA_NOTICE } from '../../services/hierarchyMockData';

export function DemoDataBadge() {
  return (
    <div className="flex items-center gap-2 rounded-lg border border-amber-300 bg-amber-50 px-3 py-2 text-xs font-medium text-amber-900 shadow-2xs">
      <AlertCircle className="size-4 shrink-0 text-amber-600" aria-hidden="true" />
      <span>{DEMO_DATA_NOTICE}</span>
    </div>
  );
}

