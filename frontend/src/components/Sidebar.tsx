import { Fragment, useState } from 'react';
import { Link, useLocation } from 'react-router-dom';
import {
  Activity, BriefcaseBusiness, ChevronRight, LayoutGrid, Database, FileSpreadsheet, FolderCog, Gauge, HardDrive, Inbox,
  LayoutDashboard, Radio, Sheet, SquarePen, UserCog, Users, ClipboardList, ClipboardCheck, ChartBar, FileUp, Layers3, UserCheck, Trophy, Table2, ListTree, MapPinned, ChartLine, Building2, TableProperties, BellRing, Mail, Workflow, History, Plug, Landmark, FileSignature,
} from 'lucide-react';
import { cn } from '@/lib/utils';
import { canOpen, hasPermission, useAuth } from '../context/auth';
import type { KpiTab } from '../features/all-kpis/useKpiFilters';
import type { AuthUser } from '../types';

type Icon = React.ComponentType<{ className?: string }>;
type IsActive = (pathname: string, params: URLSearchParams) => boolean;

interface NavItem {
  to: string;
  label: string;
  icon: Icon;
  isActive: IsActive;
  /** While the current page is under this path, the link keeps the current query (e.g. the RCA Summary filters). */
  keepQueryWithin?: string;
  /** Query parameters to set or remove while preserving other parameters within keepQueryWithin. */
  queryChanges?: Record<string, string | null>;
  /** Optional nested heading, used to retain the All KPI's existing section groups. */
  section?: string;
  /** Shown only when this holds for the signed-in user (beyond the role's pages); the server checks again. */
  show?: (user: AuthUser | null) => boolean;
}

/**
 * A top-level entry:
 * - `link`: a single page;
 * - `group`: a collapsible heading over its pages; with `link`, the label opens that page and only the chevron toggles;
 * - `section`: a small fixed heading over its pages;
 * - `heading`: a small fixed heading over the entries that follow it (shown only when one of them is).
 */
type NavEntry =
  | { kind: 'link'; item: NavItem }
  | { kind: 'group'; id: string; label: string; icon: Icon; link?: NavItem; items: NavItem[]; defaultOpen?: boolean }
  | { kind: 'section'; heading: string; items: NavItem[] }
  | { kind: 'heading'; heading: string };

const page = (to: string, label: string, icon: Icon): NavItem => ({ to, label, icon, isActive: (p) => p === to });
const kpiPage = (tab: KpiTab, label: string, icon: Icon, section: string, show?: NavItem['show']): NavItem => ({
  to: '/all-kpis',
  label,
  icon,
  section,
  keepQueryWithin: '/all-kpis',
  queryChanges: { tab: tab === 'overview' ? null : tab },
  isActive: (p, q) => p === '/all-kpis' && (q.get('tab') ?? 'overview') === tab,
  show,
});

const entries: NavEntry[] = [
  { kind: 'link', item: page('/portfolio', 'Site Portfolio', BriefcaseBusiness) },
  { kind: 'link', item: { ...page('/master-data', 'Master Data', TableProperties), isActive: (p) => p === '/master-data' || p.startsWith('/master-data/') } },
  {
    kind: 'group', id: 'overview', label: 'Overview', icon: LayoutDashboard, defaultOpen: true,
    link: { to: '/', label: 'Overview', icon: LayoutDashboard, isActive: (p, q) => p === '/' && !q.get('report_type') },
    items: [
      { to: '/?report_type=4G+Saturation', label: '4G Saturation', icon: Radio,
        isActive: (p, q) => p === '/' && q.get('report_type') === '4G Saturation' },
      { to: '/?report_type=LWE', label: 'LWE', icon: FileSpreadsheet,
        isActive: (p, q) => p === '/' && q.get('report_type') === 'LWE' },
    ],
  },
  {
    kind: 'group', id: 'thresholds', label: 'Threshold Analysis', icon: Gauge,
    link: page('/thresholds', 'Threshold Analysis', Gauge),
    items: [page('/thresholds/buckets', 'Uptime Buckets & Site Details', Layers3)],
  },
  {
    kind: 'group', id: 'teams', label: 'Team Performance', icon: Users,
    link: page('/teams', 'Team Performance', Users),
    items: [
      { ...page('/teams/hierarchy', 'Performance Hierarchy', ListTree), isActive: (p) => p.startsWith('/teams/hierarchy') },
      page('/teams/ci-ie', 'CI & IE Performance', UserCheck),
      { ...page('/teams/top', 'Circle-wise Top Performers', Trophy), isActive: (p) => p === '/teams/top' || p.startsWith('/teams/top/') || p.startsWith('/teams/circle/') || p.startsWith('/team-performance/circle/') },
    ],
  },
  {
    kind: 'group', id: 'all-kpis', label: "All KPI's", icon: LayoutGrid,
    items: [
      kpiPage('overview', 'All KPIs – Overview', LayoutDashboard, 'Overview & Reports'),
      kpiPage('trends', 'KPI Trends (Month / Week)', ChartLine, 'Overview & Reports'),
      kpiPage('ranking', 'Ranking', Trophy, 'Overview & Reports'),
      kpiPage('availability', 'Availability', Activity, 'Performance KPIs'),
      kpiPage('outage', 'Outage Minutes', Gauge, 'Performance KPIs'),
      kpiPage('usd', 'USD Sites', Radio, 'Performance KPIs'),
      kpiPage('nsla', 'NSLA Sites', ClipboardCheck, 'Performance KPIs'),
      kpiPage('below_98_5', 'Sites Below 98.5%', Layers3, 'Performance KPIs'),
      kpiPage('below_60', 'Sites Below 60%', Activity, 'Performance KPIs'),
      kpiPage('rca', 'RCA', ChartBar, 'Analysis', (u) => hasPermission(u, 'rca_summary.view')),
      kpiPage('drilldown', 'Circle / CI / IE / Site', MapPinned, 'Analysis'),
    ],
  },
  { kind: 'heading', heading: 'RCA' },
  { kind: 'link', item: page('/rca', 'RCA Register', ClipboardList) },
  {
    kind: 'group', id: 'rca-summary', label: 'RCA Summary', icon: ChartBar,
    // The label opens the Overview (highlighted as the Overview child); links inside the section keep its filters.
    link: { ...page('/rca/summary', 'RCA Summary', ChartBar), isActive: () => false, keepQueryWithin: '/rca/summary' },
    items: [
      { ...page('/rca/summary', 'Overview', LayoutDashboard), keepQueryWithin: '/rca/summary' },
      { ...page('/rca/summary/breakdown', 'Circle-wise RCA Breakdown', Table2), keepQueryWithin: '/rca/summary' },
      { ...page('/rca/summary/root-causes', 'Root Cause Analysis', ListTree), keepQueryWithin: '/rca/summary' },
      { ...page('/rca/summary/circles', 'Project & Circle Analysis', MapPinned), keepQueryWithin: '/rca/summary' },
      { ...page('/rca/summary/trends', 'Daily & Monthly Trends', ChartLine), keepQueryWithin: '/rca/summary' },
    ],
  },
  { kind: 'link', item: page('/rca/submissions', 'RCA Submissions', ClipboardCheck) },
  {
    kind: 'group', id: 'rca-upload', label: 'Upload RCA Data', icon: FileUp, defaultOpen: true,
    items: [
      page('/rca/import', 'Upload Circle RCA', FileUp),
      { ...page('/rca/import/consolidated', 'Upload Consolidated RCA', Layers3), show: (u) => !!u?.rca_upload?.consolidated },
    ],
  },
  { kind: 'heading', heading: 'Operations' },
  {
    kind: 'group', id: 'tickets', label: 'Ticket Management', icon: ClipboardList,
    items: [
      page('/tickets', 'Ticket Dashboard', LayoutDashboard),
      page('/tickets/all', 'All Tickets', Table2),
      page('/tickets/upload', 'Upload Excel', FileUp),
    ],
  },
  {
    kind: 'group', id: 'bsnl-module', label: 'BSNL Module', icon: Landmark,
    items: [
      page('/bsnl/auto-email-reports', 'Auto Email Reports', Mail),
      page('/bsnl/letters', 'BSNL Letters', FileSignature),
    ],
  },
  { kind: 'heading', heading: 'Data' },
  {
    kind: 'group', id: 'data-management', label: 'Data Management', icon: FolderCog,
    items: [page('/workbook', 'Data Source', HardDrive), page('/data-source', 'Data Source & Quality', Database)],
  },
  {
    kind: 'group', id: 'data-entry', label: 'Uptime Data', icon: SquarePen,
    items: [page('/data/upload-csv', 'Uptime Data Upload', Sheet)],
  },
  { kind: 'group', id: 'csv-arrival', label: 'Data Arrival & Follow-up', icon: Inbox, items: [page('/daily-ingestion', 'CSV Arrival Tracking', Inbox)] },
  { kind: 'section', heading: 'Administration', items: [{ ...page('/admin/users', 'Users & Roles', UserCog), isActive: (p) => p === '/admin/users' || p.startsWith('/admin/users/') },
    { ...page('/admin/organization', 'Organization', Building2), isActive: (p) => p === '/admin/organization' || p.startsWith('/admin/organization/') },
    { ...page('/admin/api-master', 'API Master', Plug), isActive: (p) => p === '/admin/api-master' || p.startsWith('/admin/api-master/') }] },
  {
    kind: 'group', id: 'alert', label: 'Alert', icon: BellRing,
    items: [page('/admin/alerts/email', 'Email Setup', Mail), page('/admin/alerts/automations', 'Automations', Workflow), page('/admin/alerts/history', 'Email History', History)],
  },
];

const groupIsActive = (entry: Extract<NavEntry, { kind: 'group' }>, pathname: string, params: URLSearchParams) =>
  [...(entry.link ? [entry.link] : []), ...entry.items].some((item) => item.isActive(pathname, params));

export function Sidebar({ onNavigate }: { onNavigate?: () => void }) {
  const location = useLocation();
  const params = new URLSearchParams(location.search);
  const { user } = useAuth();
  // Only the pages the role may open are listed (the pages and the API check the role as well).
  const allowed = (item: NavItem) => canOpen(user, item.to.split('?')[0]) && (!item.show || item.show(user));
  const filtered = entries.flatMap((entry): NavEntry[] => {
    if (entry.kind === 'heading') return [entry];
    if (entry.kind === 'link') return allowed(entry.item) ? [entry] : [];
    const items = entry.items.filter(allowed);
    if (entry.kind === 'group' && entry.link && !allowed(entry.link)) return [];
    return items.length || (entry.kind === 'group' && entry.link) ? [{ ...entry, items }] : [];
  });
  // A heading with nothing visible under it (up to the next heading or section) is dropped.
  const visible = filtered.filter((entry, i) => entry.kind !== 'heading' || ['link', 'group'].includes(filtered[i + 1]?.kind));

  // Groups open by default, plus the group holding the current page. Kept in memory only (no storage):
  // after a refresh or a direct link the current page's group opens again.
  const activeGroup = visible.find((e) => e.kind === 'group' && groupIsActive(e, location.pathname, params));
  const activeId = activeGroup?.kind === 'group' ? activeGroup.id : null;
  const [open, setOpen] = useState<Set<string>>(() => new Set([
    ...entries.flatMap((e) => (e.kind === 'group' && e.defaultOpen ? [e.id] : [])), ...(activeId ? [activeId] : []),
  ]));
  const [seenKey, setSeenKey] = useState(location.pathname + location.search);
  const key = location.pathname + location.search;
  if (key !== seenKey) {
    // Navigating (link, back/forward) opens the new page's group; the chevron can still close it afterwards.
    setSeenKey(key);
    if (activeId && !open.has(activeId)) setOpen(new Set(open).add(activeId));
  }
  const toggle = (id: string) => setOpen((prev) => {
    const next = new Set(prev);
    if (next.has(id)) next.delete(id); else next.add(id);
    return next;
  });

  const renderLink = (item: NavItem, nested = false) => {
    const active = item.isActive(location.pathname, params);
    const ItemIcon = item.icon;
    const preservingQuery = item.keepQueryWithin && location.pathname.startsWith(item.keepQueryWithin);
    const query = new URLSearchParams(preservingQuery ? location.search : '');
    Object.entries(item.queryChanges ?? {}).forEach(([key, value]) => {
      if (value) query.set(key, value); else query.delete(key);
    });
    const search = query.toString();
    const to = item.queryChanges
      ? `${item.to}${search ? `?${search}` : ''}`
      : preservingQuery ? `${item.to}${location.search}` : item.to;
    return (
      <Link
        to={to}
        onClick={onNavigate}
        aria-current={active ? 'page' : undefined}
        className={cn(
          'flex min-w-0 flex-1 items-center gap-2.5 rounded-lg py-2 text-sm transition-colors focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none',
          nested ? 'px-3' : 'px-3 font-semibold',
          active ? 'bg-sidebar-accent font-semibold text-sidebar-accent-foreground'
            : cn(nested ? 'text-muted-foreground' : 'text-foreground', 'hover:bg-sidebar-accent hover:text-foreground'),
        )}
      >
        <ItemIcon className={cn('size-4 shrink-0', active || !nested ? 'text-foreground' : 'text-muted-foreground')} />
        <span className="min-w-0 leading-snug break-words">{item.label}</span>
      </Link>
    );
  };

  return (
    <div className="flex h-full flex-col bg-sidebar">
      <div className="flex flex-col gap-1 border-b px-4 py-4">
        <Link to="/" onClick={onNavigate} className="self-start rounded focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none">
          {/* logo.png is a square with wide padding; crop to the wordmark. */}
          <img src="/logo.png" alt="Pratap - Carving Lives" className="h-16 w-44 object-cover" />
        </Link>
        <p className="px-1 text-xs font-medium text-muted-foreground">4G Saturation &amp; LWE Reporting</p>
      </div>

      <nav className="min-h-0 flex-1 overflow-x-hidden overflow-y-auto px-3 py-3" aria-label="Main">
        <ul className="space-y-0.5">
          {visible.map((entry) => {
            if (entry.kind === 'link') return <li key={entry.item.to} className="flex">{renderLink(entry.item)}</li>;

            if (entry.kind === 'heading') {
              return (
                <li key={entry.heading} className="pt-3">
                  <p className="truncate px-3 pb-1 text-[11px] font-semibold tracking-wider text-muted-foreground uppercase">{entry.heading}</p>
                </li>
              );
            }

            if (entry.kind === 'section') {
              return (
                <li key={entry.heading} className="pt-3">
                  <p className="truncate px-3 pb-1 text-[11px] font-semibold tracking-wider text-muted-foreground uppercase">{entry.heading}</p>
                  <ul className="space-y-0.5">
                    {entry.items.map((item) => <li key={item.to} className="flex">{renderLink(item)}</li>)}
                  </ul>
                </li>
              );
            }

            const isOpen = open.has(entry.id);
            const listId = `nav-group-${entry.id}`;
            const GroupIcon = entry.icon;
            const chevron = <ChevronRight className={cn('size-4 shrink-0 transition-transform duration-200', isOpen && 'rotate-90')} aria-hidden="true" />;
            return (
              <li key={entry.id}>
                {entry.link ? (
                  <div className="flex items-center gap-0.5">
                    {renderLink(entry.link)}
                    <button
                      type="button"
                      onClick={() => toggle(entry.id)}
                      aria-expanded={isOpen}
                      aria-controls={listId}
                      aria-label={`${isOpen ? 'Collapse' : 'Expand'} ${entry.label}`}
                      className="rounded-lg p-2 text-muted-foreground transition-colors hover:bg-sidebar-accent hover:text-foreground focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none"
                    >
                      {chevron}
                    </button>
                  </div>
                ) : (
                  <button
                    type="button"
                    onClick={() => toggle(entry.id)}
                    aria-expanded={isOpen}
                    aria-controls={listId}
                    className={cn(
                      'flex w-full items-center gap-2.5 rounded-lg px-3 py-2 text-left text-sm transition-colors hover:bg-sidebar-accent hover:text-foreground focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none',
                      'font-semibold text-foreground',
                    )}
                  >
                    <GroupIcon className="size-4 shrink-0 text-foreground" />
                    <span className="min-w-0 flex-1 leading-snug break-words">{entry.label}</span>
                    {chevron}
                  </button>
                )}
                {/* Height animates through grid rows; a closed group is inert, so its links are neither focusable nor announced. */}
                <div
                  id={listId}
                  inert={!isOpen}
                  aria-hidden={!isOpen}
                  className={cn('grid transition-[grid-template-rows,opacity] duration-200 ease-out motion-reduce:transition-none',
                    isOpen ? 'grid-rows-[1fr] opacity-100' : 'grid-rows-[0fr] opacity-0')}
                >
                  <ul className="ml-[1.375rem] min-h-0 space-y-0.5 overflow-hidden border-l pt-0.5 pl-2">
                    {entry.items.map((item, index) => (
                      <Fragment key={item.label}>
                        {item.section && item.section !== entry.items[index - 1]?.section && (
                          <li className="pt-2 first:pt-1">
                            <p className="truncate px-3 pb-0.5 text-[10px] font-semibold tracking-wider text-muted-foreground uppercase">{item.section}</p>
                          </li>
                        )}
                        <li className="flex">{renderLink(item, true)}</li>
                      </Fragment>
                    ))}
                  </ul>
                </div>
              </li>
            );
          })}
        </ul>
      </nav>
    </div>
  );
}
