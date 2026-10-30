import { Link, Navigate, useLocation } from 'react-router-dom';
import { cn } from '@/lib/utils';
import { AccessTab, CodeMappingTab, HistoryTab } from '../components/organization/AdminTabs';
import { CirclesTab, MappingTab, ProjectsTab } from '../components/organization/MasterTabs';
import { PageHeading } from '../context/pageHeader';

/** The six tabs: one sidebar entry (Administration > Organization), one URL per tab. */
const TABS = [
  { path: '/admin/organization', label: 'Projects', Tab: ProjectsTab },
  { path: '/admin/organization/circles', label: 'Circles', Tab: CirclesTab },
  { path: '/admin/organization/mapping', label: 'Project-Circle Mapping', Tab: MappingTab },
  { path: '/admin/organization/access', label: 'User Access', Tab: AccessTab },
  { path: '/admin/organization/code-mapping', label: 'Code Mapping', Tab: CodeMappingTab },
  { path: '/admin/organization/history', label: 'Change History', Tab: HistoryTab },
];

/**
 * Admin-only: the projects, the one global record per circle, which circles each project covers, how source files write
 * circle codes, who may use which project and circle, and the history of every change. The server enforces all of it.
 */
export function OrganizationPage() {
  const location = useLocation();
  const path = location.pathname.replace(/\/+$/, '') || '/admin/organization';
  const current = TABS.find((t) => t.path === path);
  if (!current) return <Navigate to="/admin/organization" replace />;
  const { Tab } = current;
  return (
    <div className="flex flex-col gap-4">
      <PageHeading title="Organization"
        subtitle="Projects, circles and their associations, source code mapping and project/circle user access. Used across uploads, reports and access checks." />
      <nav aria-label="Organization sections" className="flex flex-wrap gap-1 rounded-xl border bg-card p-1 shadow-xs">
        {TABS.map((t) => (
          <Link key={t.path} to={t.path} aria-current={t === current ? 'page' : undefined}
            className={cn('rounded-lg px-3 py-1.5 text-sm font-medium transition-colors focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none',
              t === current ? 'bg-primary text-primary-foreground' : 'text-muted-foreground hover:bg-muted hover:text-foreground')}>
            {t.label}
          </Link>
        ))}
      </nav>
      <Tab />
    </div>
  );
}
