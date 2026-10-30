import { useState } from 'react';
import { Link, useLocation } from 'react-router-dom';
import {
  BriefcaseBusiness, ChevronRight, ClipboardPen, Database, FileSpreadsheet, FolderCog, Gauge, HardDrive, Inbox,
  LayoutDashboard, MapPinPlus, Radio, Sheet, SquarePen, UserCog, Users, ClipboardList, ClipboardCheck, ChartBar, FileUp, Layers3, UserCheck, Trophy, Table2, ListTree, MapPinned, ChartLine, Building2,
} from 'lucide-react';
import { cn } from '@/lib/utils';
import { canOpen, useAuth } from '../context/auth';

type Icon = React.ComponentType<{ className?: string }>;
type IsActive = (pathname: string, params: URLSearchParams) => boolean;

interface NavItem {
  to: string;
  label: string;
  icon: Icon;
  isActive: IsActive;
  /** While the current page is under this path, the link keeps the current query (e.g. the RCA Summary filters). */
  keepQueryWithin?: string;
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

const entries: NavEntry[] = [
  { kind: 'link', item: page('/portfolio', 'Site Portfolio', BriefcaseBusiness) },
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
    items: [page('/teams/ci-ie', 'CI & IE Performance', UserCheck), page('/teams/top', 'Circle-wise Top Performers', Trophy)],
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
  { kind: 'link', item: page('/rca/import', 'Upload RCA Data', FileUp) },
  { kind: 'heading', heading: 'Data' },
  {
    kind: 'group', id: 'data-management', label: 'Data Management', icon: FolderCog,
    items: [page('/workbook', 'Data Source', HardDrive), page('/data-source', 'Data Source & Quality', Database)],
  },
  {
    kind: 'group', id: 'data-entry', label: 'Data Entry', icon: SquarePen,
    items: [page('/data/add-row', 'Add Row', ClipboardPen), page('/data/upload-csv', 'Upload CSV', Sheet), page('/data/new-site', 'Add Site', MapPinPlus)],
  },
  { kind: 'group', id: 'csv-arrival', label: 'CSV Arrival & Follow-up', icon: Inbox, items: [page('/daily-ingestion', 'CSV Arrival Tracking', Inbox)] },
  { kind: 'section', heading: 'Administration', items: [page('/admin/users', 'Users & Roles', UserCog),
    { ...page('/admin/organization', 'Organization', Building2), isActive: (p) => p === '/admin/organization' || p.startsWith('/admin/organization/') }] },
];

const groupIsActive = (entry: Extract<NavEntry, { kind: 'group' }>, pathname: string, params: URLSearchParams) =>
  [...(entry.link ? [entry.link] : []), ...entry.items].some((item) => item.isActive(pathname, params));

export function Sidebar({ onNavigate }: { onNavigate?: () => void }) {
  const location = useLocation();
  const params = new URLSearchParams(location.search);
  const { user } = useAuth();
  // Only the pages the role may open are listed (the pages and the API check the role as well).
  const allowed = (item: NavItem) => canOpen(user?.role, item.to.split('?')[0]);
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
    return (
      <Link
        to={item.keepQueryWithin && location.pathname.startsWith(item.keepQueryWithin) ? `${item.to}${location.search}` : item.to}
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
                    {entry.items.map((item) => <li key={item.to} className="flex">{renderLink(item, true)}</li>)}
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
