/**
 * The title shown in the top application bar for each route, until (or unless) the page sets its own title and
 * context with <PageHeading>. Labels follow the sidebar.
 */
const TITLES: Record<string, string> = {
  '/': 'Overview',
  '/portfolio': 'Site Portfolio',
  '/thresholds': 'Threshold Analysis',
  '/thresholds/buckets': 'Uptime Buckets & Site Details',
  '/teams': 'Team Performance',
  '/teams/ci-ie': 'CI & IE Performance',
  '/teams/top': 'Circle-wise Top Performers',
  '/workbook': 'Master Workbook',
  '/data/database': 'Data Source',
  '/data-source': 'Data Source & Quality',
  '/data/add-row': 'Add Row',
  '/data/upload-csv': 'Upload CSV',
  '/data/new-site': 'Add New Site',
  '/daily-ingestion': 'CSV Arrival & Follow-up',
  '/admin/users': 'Users & Roles · Users',
  '/admin/users/roles': 'Users & Roles · Roles & Permissions',
  '/admin/users/assignments': 'Users & Roles · Access Assignments',
  '/admin/users/history': 'Users & Roles · Access History',
  '/master-data': 'Master Data · Uptime Master',
  '/master-data/escalation': 'Master Data · CI-wise Consolidation & Escalation Matrix',
  '/master-data/rca': 'Master Data · RCA Data',
  '/admin/organization': 'Organization · Projects',
  '/admin/organization/circles': 'Organization · Circles',
  '/admin/organization/mapping': 'Organization · Project-Circle Mapping',
  '/admin/organization/access': 'Organization · User Access',
  '/admin/organization/code-mapping': 'Organization · Code Mapping',
  '/admin/organization/history': 'Organization · Change History',
  '/admin/alerts/email': 'Alert · Email Setup',
  '/admin/alerts/automations': 'Alert · Automations',
  '/admin/alerts/history': 'Alert · Email History',
  '/rca': 'RCA Register',
  '/rca/summary': 'RCA Summary',
  '/rca/summary/breakdown': 'Circle-wise RCA Breakdown',
  '/rca/summary/root-causes': 'Root Cause Analysis',
  '/rca/summary/circles': 'Project & Circle Analysis',
  '/rca/summary/trends': 'Daily & Monthly Trends',
  '/rca/submissions': 'RCA Submissions',
  '/rca/import': 'Upload Circle RCA',
  '/rca/import/consolidated': 'Upload Consolidated RCA',
  '/rca/mappings': 'RCA Cause Mapping',
  '/change-password': 'Change Password',
};
const REPORT_TYPES: Record<string, string> = { '4G Saturation': '4G Saturation', LWE: 'LWE' };

export function routeTitle(pathname: string, search = ''): string {
  const path = pathname.length > 1 ? pathname.replace(/\/+$/, '') : pathname;
  if (path === '/') {
    const reportType = new URLSearchParams(search).get('report_type');
    if (reportType && REPORT_TYPES[reportType]) return REPORT_TYPES[reportType];
  }
  if (path.startsWith('/teams/top/circle/') || path.startsWith('/teams/circle/') || path.startsWith('/team-performance/circle/')) {
    return 'Circle Details';
  }
  return TITLES[path] ?? '4G Saturation & LWE Reporting';
}
