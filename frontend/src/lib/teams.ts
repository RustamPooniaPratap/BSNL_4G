import type { SiteRecord, TeamGroup } from '../types';

/** Label the API uses for sites without a CI or IE name. */
export const UNASSIGNED = 'Unassigned';

/** Team page for the CI or IE responsible for a site, scoped to the site's report type and circle. */
export function teamLink(group: TeamGroup, name: string, site?: Pick<SiteRecord, 'report_type' | 'circle'>) {
  const query = new URLSearchParams({ group, team: name });
  if (site) {
    query.set('report_type', site.report_type);
    query.set('circle', site.circle);
  }
  return `/teams?${query}`;
}

/** URL parameters of a CI / IE opened from CI & IE Performance (kept when the page's own filters change or reset). */
export const TEAM_SITES_PARAMS = ['team_group', 'team', 'team_project', 'team_circle', 'nsla', 'back', 'nsla_month'] as const;

/**
 * Uptime Buckets & Site Details for the sites of one CI or IE. A person is identified by group, name, project and circle
 * (one row of the CI & IE NSLA table): the same name under another project or circle is not included. The server
 * restricts the data to that person; ``back`` is the CI & IE Performance URL to return to.
 */
export function teamSitesLink(group: TeamGroup, person: { name: string; report_type: string; circle: string },
  { scope, back, month }: { scope: string; back: string; month?: string }) {
  const query = new URLSearchParams({
    report_type: person.report_type, circle: person.circle, scope,
    team_group: group, team: person.name, team_project: person.report_type, team_circle: person.circle, back,
  });
  if (month) query.set('nsla_month', month);
  return `/thresholds/buckets?${query}`;
}
