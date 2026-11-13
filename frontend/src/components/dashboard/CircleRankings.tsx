import { Link } from 'react-router-dom';
import { Info, Trophy } from 'lucide-react';
import { cn } from '@/lib/utils';
import { ChartCard } from './ChartCard';
import { formatNumber, formatPct } from '../../lib/format';
import type { GroupRanking, RankedPerson, TeamGroup, TopPerformerCircle } from '../../types';

const GROUP_LABELS: Record<TeamGroup, string> = { ci: 'CI', ie: 'IE' };
const projectLabel = (type: string) => (type === '4G Saturation' ? '4G' : type);
const TH = 'border-b bg-muted/50 px-3 py-2 text-[11px] font-medium whitespace-nowrap text-muted-foreground';
const TD = 'border-b px-3 py-2 align-middle';

export function CircleRankings({ circle, period, link }: {
  circle: TopPerformerCircle; period: string; link: (group: TeamGroup, c: TopPerformerCircle, name: string) => string;
}) {
  return (
    <section className="grid items-start gap-3 lg:grid-cols-2" aria-label={`${circle.circle} ${projectLabel(circle.report_type)} rankings`}>
      {(['ci', 'ie'] as TeamGroup[]).map((group) => (
        <RankingTable key={group} title={`${circle.circle} · ${projectLabel(circle.report_type)} — ${GROUP_LABELS[group]} ranking`}
          group={group} ranking={circle[group]} period={period} link={(name) => link(group, circle, name)} />
      ))}
    </section>
  );
}

export function RankingTable({ title, group, ranking, period, link }: {
  title: string; group: TeamGroup; ranking: GroupRanking; period: string; link: (name: string) => string;
}) {
  const label = GROUP_LABELS[group];
  const ranked = (ranking?.ranking ?? []).filter((p) => p.rank != null);
  const unranked = (ranking?.ranking ?? []).filter((p) => p.rank == null);
  const topList = ranking?.top ?? [];

  return (
    <ChartCard
      title={title}
      description={`${period} · ${formatNumber(ranking?.people_eligible ?? 0)} of ${formatNumber(ranking?.people_total ?? 0)} ${label}s eligible · lowest NSLA % first`}
      empty={!ranking?.ranking?.length}
      emptyMessage={`No ${label} is assigned in this circle.`}
      bodyClassName="px-0"
    >
      {ranking?.status === 'insufficient' && (
        <p className="mx-4 mb-1 flex items-start gap-1.5 rounded-md border border-amber-200 bg-amber-50 px-2.5 py-1.5 text-xs text-amber-900">
          <Info className="mt-px size-3.5 shrink-0" aria-hidden="true" />
          <span>Insufficient data to name a top {label}: {ranking.reason}</span>
        </p>
      )}
      {ranking?.status === 'tie' && (
        <p className="mx-4 mb-1 flex items-start gap-1.5 rounded-md border border-sky-200 bg-sky-50 px-2.5 py-1.5 text-xs text-sky-900">
          <Info className="mt-px size-3.5 shrink-0" aria-hidden="true" />
          <span>Tie · {topList.length} {label}s share the top rank with equal NSLA %</span>
        </p>
      )}
      <div className="max-h-[26rem] overflow-auto" role="region" aria-label={`${title} table`} tabIndex={0}>
        <table className="w-full border-separate border-spacing-0 text-xs tabular-nums">
          <thead className="sticky top-0 z-10">
            <tr>
              <th scope="col" className={cn(TH, 'w-12 text-center')}>Rank</th>
              <th scope="col" className={cn(TH, 'text-left')}>{label}</th>
              <th scope="col" className={cn(TH, 'text-right')}>Assigned</th>
              <th scope="col" className={cn(TH, 'text-right')}>NSLA sites</th>
              <th scope="col" className={cn(TH, 'w-32 text-right')}>NSLA %</th>
              <th scope="col" className={cn(TH, 'text-right')} title="Assigned sites with a value in the period">Reported</th>
            </tr>
          </thead>
          <tbody>
            {ranked.map((p) => (
              <PersonRow
                key={p.name}
                person={p}
                top={topList.includes(p.name)}
                unnamed={!topList.length && p.rank === 1}
                label={label}
                link={link}
              />
            ))}
          </tbody>
          {unranked.length > 0 && (
            <tbody>
              <tr>
                <th colSpan={6} scope="rowgroup" className="border-b bg-card px-3 pt-3 pb-1 text-left text-[10px] font-semibold tracking-wider text-muted-foreground uppercase">
                  Not ranked · {unranked.length}
                </th>
              </tr>
              {unranked.map((p) => (
                <PersonRow
                  key={p.name}
                  person={p}
                  top={false}
                  unnamed={false}
                  label={label}
                  link={link}
                />
              ))}
            </tbody>
          )}
        </table>
      </div>
    </ChartCard>
  );
}

export function PersonRow({ person: p, top, unnamed, label, link }: {
  person: RankedPerson; top: boolean; unnamed: boolean; label: string; link: (name: string) => string;
}) {
  const complete = p.sites_reported === p.sites_in_scope;
  return (
    <tr className={cn(top ? 'bg-emerald-50/60' : 'hover:bg-muted/40', p.rank == null && 'text-muted-foreground')}>
      <td className={cn(TD, 'text-center')}>
        {p.rank == null ? '—' : (
          <span className={cn('inline-flex size-5 items-center justify-center rounded-full text-[11px] font-semibold',
            top ? 'bg-emerald-600 text-white' : 'bg-muted text-foreground')}>{p.rank}</span>
        )}
      </td>
      <td className={cn(TD, 'max-w-64')}>
        <div className="flex items-center gap-1.5">
          {top && <Trophy className="size-3.5 shrink-0 text-amber-500" aria-hidden="true" />}
          <Link
            to={link(p.name)}
            className={cn('truncate hover:text-primary hover:underline', top ? 'font-semibold text-emerald-900' : 'font-medium')}
            title={p.name}
          >
            {p.name}
          </Link>
        </div>
        {p.reason && <span className="block text-[11px]">{p.reason}</span>}
        {unnamed && <span className="block text-[11px] text-muted-foreground">Not named top: too few eligible {label}s to compare</span>}
        {!!p.other_assignments?.length && <span className="block text-[11px] text-muted-foreground">Also assigned: {p.other_assignments.join(', ')}</span>}
      </td>
      <td className={cn(TD, 'text-right')}>{formatNumber(p.sites_in_scope)}</td>
      <td className={cn(TD, 'text-right')}>{formatNumber(p.nsla_sites)}</td>
      <td className={cn(TD, 'text-right')}>
        <div className="flex items-center justify-end gap-2">
          {p.nsla_pct != null && (
            <span className="h-1.5 w-14 overflow-hidden rounded-full bg-muted" aria-hidden="true">
              <span className={cn('block h-full rounded-full', top ? 'bg-emerald-500' : 'bg-slate-400')} style={{ width: `${Math.min(100, p.nsla_pct)}%` }} />
            </span>
          )}
          <span className="w-12 font-medium">{formatPct(p.nsla_pct, 1)}</span>
        </div>
      </td>
      <td className={cn(TD, 'text-right', !complete && 'text-amber-700')} title={complete ? 'Every assigned site reported' : 'Some assigned sites have no value'}>
        {formatNumber(p.sites_reported)} / {formatNumber(p.sites_in_scope)}
      </td>
    </tr>
  );
}

