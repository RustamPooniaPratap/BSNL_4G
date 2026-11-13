import { Link } from 'react-router-dom';
import { Bar, BarChart, CartesianGrid, Cell, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts';
import { Separator } from '@/components/ui/separator';
import { Sheet, SheetContent, SheetDescription, SheetHeader, SheetTitle } from '@/components/ui/sheet';
import { Skeleton } from '@/components/ui/skeleton';
import { usePopulation } from '../../context/population';
import { useApiQuery } from '../../hooks/useApiQuery';
import { formatDate, formatMinutes, formatPct, formatShortDate } from '../../lib/format';
import { teamLink, UNASSIGNED } from '../../lib/teams';
import { fetchSiteDetail } from '../../services/api';
import type { SiteRecord } from '../../types';
import { PanelMessage } from './ChartCard';
import { BucketBadge } from './SiteTable';
import { AXIS_TICK, BUCKET_COLORS } from './constants';

interface SiteDetailSheetProps {
  site: SiteRecord | null;
  onClose: () => void;
}

const barColor = (uptime: number) =>
  uptime >= 98.5 ? BUCKET_COLORS.gte_98_5 : uptime >= 90 ? BUCKET_COLORS['90_97'] : BUCKET_COLORS.lt_60;

export function SiteDetailSheet({ site, onClose }: SiteDetailSheetProps) {
  const { scope } = usePopulation();
  const key = site ? `${site.report_type}|${site.site_id}|${scope}` : null;
  const { data, error, loading } = useApiQuery(key, (signal) => fetchSiteDetail(site!.site_id, site!.report_type, signal, scope));
  const detail = data && site && data.site.site_id === site.site_id ? data : null;
  const reported = detail?.daily.filter((d) => d.reported) ?? [];

  return (
    <Sheet open={site !== null} onOpenChange={(open) => { if (!open) onClose(); }}>
      <SheetContent className="w-full overflow-y-auto sm:max-w-lg">
        <SheetHeader>
          <SheetTitle className="font-mono">{site?.site_id}</SheetTitle>
          <SheetDescription>{site?.site_name || 'Site'} · {site?.report_type} · {site?.circle}</SheetDescription>
        </SheetHeader>
        <div className="space-y-5 px-4 pb-6 text-sm">
          {error ? (
            <PanelMessage icon={null} title="Could not load site history" text={error.message} />
          ) : loading || !detail ? (
            <Skeleton className="h-72 w-full" />
          ) : (
            <>
              <div className="grid grid-cols-2 gap-3">
                <Stat label={`MTD uptime to ${formatShortDate(detail.reporting_date)}`} value={formatPct(detail.mtd_uptime_pct)} />
                <div>
                  <p className="text-xs text-muted-foreground">MTD bucket</p>
                  <p className="mt-1 text-sm font-medium"><BucketBadge bucket={detail.mtd_bucket} /></p>
                </div>
              </div>

              <section aria-labelledby="site-daily-heading">
                <h3 id="site-daily-heading" className="mb-2 text-xs font-semibold">Daily uptime ({reported.length} reported days)</h3>
                <div className="h-44" role="img" aria-label="Bar chart of this site's daily uptime">
                  <ResponsiveContainer width="100%" height="100%">
                    <BarChart data={reported} margin={{ top: 4, right: 4, bottom: 0, left: -16 }}>
                      <CartesianGrid strokeDasharray="3 3" vertical={false} stroke="var(--border)" />
                      <XAxis dataKey="date" tickFormatter={formatShortDate} tick={AXIS_TICK} tickLine={false} axisLine={false} minTickGap={12} />
                      <YAxis domain={[0, 100]} tickFormatter={(v: number) => `${v}%`} tick={AXIS_TICK} tickLine={false} axisLine={false} />
                      <Tooltip
                        labelFormatter={(label) => formatDate(String(label))}
                        formatter={(value) => formatPct(Number(value))}
                        contentStyle={{ fontSize: 12, borderRadius: 8 }}
                        cursor={{ fill: 'var(--muted)' }}
                      />
                      <Bar isAnimationActive={false} dataKey="uptime_pct" name="Uptime" radius={[2, 2, 0, 0]}>
                        {reported.map((d) => <Cell key={d.date} fill={barColor(d.uptime_pct ?? 0)} />)}
                      </Bar>
                    </BarChart>
                  </ResponsiveContainer>
                </div>
                <div className="mt-2 max-h-48 overflow-auto rounded-md border text-xs">
                  <table className="w-full tabular-nums">
                    <caption className="sr-only">Daily outage for {site?.site_id}</caption>
                    <thead className="sticky top-0 bg-muted text-left">
                      <tr><th scope="col" className="px-2.5 py-1.5 font-medium">Date</th><th scope="col" className="px-2.5 py-1.5 text-right font-medium">Outage</th><th scope="col" className="px-2.5 py-1.5 text-right font-medium">Uptime</th></tr>
                    </thead>
                    <tbody className="divide-y">
                      {reported.map((d) => (
                        <tr key={d.date}>
                          <td className="px-2.5 py-1">{formatDate(d.date)}</td>
                          <td className="px-2.5 py-1 text-right">{formatMinutes(d.outage_minutes)}</td>
                          <td className="px-2.5 py-1 text-right">{formatPct(d.uptime_pct)}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </section>

              <Separator />

              <dl className="grid grid-cols-2 gap-x-4 gap-y-3">
                <Field label="Circle" value={detail.site.circle === detail.site.circle_as_in_workbook
                  ? detail.site.circle : `${detail.site.circle} (workbook: ${detail.site.circle_as_in_workbook})`} />
                <Field label="OA / BA" value={`${detail.site.oa || '—'} / ${detail.site.ba || '—'}`} />
                <Field label="On-Air" value={detail.site.on_air ? 'Yes' : 'No'} />
                <Field label="O&M Start (this month)" value={detail.site.om_start ? 'Yes' : 'No'} />
                <Field label="Power" value={detail.site.eb || '—'} />
                <Field label="Workbook row" value={`Up-Time Report, row ${detail.site.source_row}`} />
                <Field label="IE (responsible)" value={detail.site.ie_name || '—'} onNavigate={onClose}
                  to={detail.site.ie_name && detail.site.ie_name !== UNASSIGNED ? teamLink('ie', detail.site.ie_name, detail.site) : undefined} />
                <Field label="CI (responsible)" value={detail.site.ci_name || '—'} onNavigate={onClose}
                  to={detail.site.ci_name && detail.site.ci_name !== UNASSIGNED ? teamLink('ci', detail.site.ci_name, detail.site) : undefined} />
              </dl>
            </>
          )}
        </div>
      </SheetContent>
    </Sheet>
  );
}

function Stat({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <p className="text-xs text-muted-foreground">{label}</p>
      <p className="mt-1 text-[18px] font-semibold tabular-nums">{value}</p>
    </div>
  );
}

function Field({ label, value, to, onNavigate }: { label: string; value: string; to?: string; onNavigate?: () => void }) {
  return (
    <div className="min-w-0">
      <dt className="text-xs text-muted-foreground">{label}</dt>
      <dd className="mt-0.5 truncate" title={value}>
        {to ? <Link to={to} onClick={onNavigate} className="font-medium underline underline-offset-4">{value}</Link> : value}
      </dd>
    </div>
  );
}
