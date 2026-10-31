import { Activity, TriangleAlert } from 'lucide-react';
import { formatDateTime } from '../../lib/format';
import type { AlertWorker } from '../../types/alerts';

/** Whether the background worker (manage.py run_alerts) is running: schedules and Run Now depend on it. */
export function WorkerStatus({ worker }: { worker: AlertWorker }) {
  return worker.running ? (
    <p className="flex items-center gap-1.5 text-xs text-emerald-800" role="status">
      <Activity className="size-3.5" aria-hidden="true" /> Alert worker running (last check {formatDateTime(worker.last_seen)}).
    </p>
  ) : (
    <p className="flex items-start gap-1.5 rounded-md border border-amber-200 bg-amber-50 px-3 py-2 text-xs text-amber-900" role="status">
      <TriangleAlert className="mt-px size-3.5 shrink-0" aria-hidden="true" />
      The alert worker is not running{worker.last_seen ? ` (last seen ${formatDateTime(worker.last_seen)})` : ''}: scheduled and Run Now emails wait until it starts
      (<code>python manage.py run_alerts</code>).
    </p>
  );
}
