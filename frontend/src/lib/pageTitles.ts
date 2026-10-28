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
  '/admin/users': 'Users & Roles',
  '/rca': 'RCA Register',
  '/rca/summary': 'RCA Summary',
  '/rca/submissions': 'RCA Submissions',
  '/rca/import': 'Upload RCA Data',
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
  return TITLES[path] ?? '4G Saturation & LWE Reporting';
}
