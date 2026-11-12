import { Link } from 'react-router-dom';
import { AlertTriangle } from 'lucide-react';
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert';
import { Badge } from '@/components/ui/badge';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Skeleton } from '@/components/ui/skeleton';
import { useWorkbook } from '../context/workbook';
import { formatDate, formatNumber } from '../lib/format';

/**
 * Read-only status of the reporting data (the data layer every page reads; GET /api/dashboard/workbook/). Data enters
 * only through the imports on the Data Source page and the raw daily CSV upload; there is no source to switch.
 */
export function DataLayerStatus() {
  const { active, loading, error, message } = useWorkbook();
  if (loading) return <Skeleton className="h-40 w-full" />;
  if (error) {
    return <Alert variant="destructive"><AlertTriangle /><AlertTitle>Status unavailable</AlertTitle><AlertDescription>{error.message}</AlertDescription></Alert>;
  }
  if (!active) {
    return (
      <Card role="region" aria-label="Reporting data">
        <CardHeader>
          <CardTitle className="text-sm font-semibold">No reporting data yet</CardTitle>
          <CardDescription className="text-xs">
            {message ?? 'Import the Consolidation Matrix (site master) and the Uptime Master below.'} No sample data is shown in the meantime.
          </CardDescription>
        </CardHeader>
      </Card>
    );
  }
  const warnings = active.warnings.filter((w) => w.severity === 'warning');
  return (
    <Card role="region" aria-label="Reporting data">
      <CardHeader>
        <CardTitle className="flex items-center gap-2 text-sm font-semibold">
          Reporting data
          {warnings.length ? <Badge variant="destructive">{warnings.length} to review</Badge> : <Badge variant="secondary">No warnings</Badge>}
        </CardTitle>
        <CardDescription className="text-xs">
          Every dashboard page reads the data layer. It is updated by the imports below and by raw daily CSV uploads; there is no other source.
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-3 text-sm">
        <dl className="grid grid-cols-2 gap-x-4 gap-y-2.5 md:grid-cols-4">
          <Item label="Reporting month" value={active.month} />
          <Item label="Latest reporting date" value={formatDate(active.latest_reporting_date)} />
          <Item label="Reported days" value={String(active.reporting_dates.length)} />
          {Object.entries(active.by_report_type).map(([type, count]) => <Item key={type} label={`${type} sites`} value={formatNumber(count)} />)}
          <Item label="Circles" value={active.circles.join(', ') || '—'} />
        </dl>
        <Link to="/data-source" className="inline-block text-xs font-medium underline underline-offset-4">Data quality and definitions</Link>
      </CardContent>
    </Card>
  );
}

function Item({ label, value }: { label: string; value: string }) {
  return (
    <div className="min-w-0">
      <dt className="text-xs text-muted-foreground">{label}</dt>
      <dd className="mt-0.5 break-words">{value}</dd>
    </div>
  );
}
