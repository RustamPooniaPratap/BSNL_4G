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
