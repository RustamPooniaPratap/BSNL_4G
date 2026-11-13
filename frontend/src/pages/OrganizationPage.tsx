import { Link, Navigate, useLocation } from 'react-router-dom';
import { cn } from '@/lib/utils';
import { AccessTab, CodeMappingTab, HistoryTab } from '../components/organization/AdminTabs';
import { CirclesTab, MappingTab, ProjectsTab } from '../components/organization/MasterTabs';
import {
  OmAssignmentsTab,
  OperationalAreasTab,
  PersonnelTab,
  SourceMappingsAndConflictsTab,
  SiteAssignmentsTab,
  PersonnelMergeTab,
} from '../components/organization/HierarchyTabs';
import { PageHeading } from '../context/pageHeader';

/** The organization tabs: projects, circles, hierarchy, personnel, assignments, access and history. */
const TABS = [
  { path: '/admin/organization', label: 'Projects', Tab: ProjectsTab },
  { path: '/admin/organization/circles', label: 'Circles', Tab: CirclesTab },
  { path: '/admin/organization/operational-areas', label: 'Operational Areas', Tab: OperationalAreasTab },
  { path: '/admin/organization/mapping', label: 'Project-Circle Mapping', Tab: MappingTab },
  { path: '/admin/organization/om-assignments', label: 'O&M Assignments', Tab: OmAssignmentsTab },
  { path: '/admin/organization/personnel', label: 'Personnel Master', Tab: PersonnelTab },
  { path: '/admin/organization/site-assignments', label: 'Site Assignments', Tab: SiteAssignmentsTab },
  { path: '/admin/organization/conflicts', label: 'Mappings & Conflicts', Tab: SourceMappingsAndConflictsTab },
  { path: '/admin/organization/personnel-merge', label: 'Personnel Merge', Tab: PersonnelMergeTab },
  { path: '/admin/organization/access', label: 'User Access', Tab: AccessTab },
  { path: '/admin/organization/code-mapping', label: 'Code Mapping', Tab: CodeMappingTab },
  { path: '/admin/organization/history', label: 'Change History', Tab: HistoryTab },
];

/**
 * Admin-only: projects, circles, team hierarchy, personnel identity, site assignments,
 * access control and change history.
 */
export function OrganizationPage() {
  const location = useLocation();
  const path = location.pathname.replace(/\/+$/, '') || '/admin/organization';
  const current = TABS.find((t) => t.path === path);
  if (!current) return <Navigate to="/admin/organization" replace />;
  const { Tab } = current;
  return (
    <div className="flex flex-col gap-3">
      <PageHeading title="Organization & Team Performance Hierarchy"
        subtitle="Manage Circles, Operational Areas, O&M Managers, Personnel, site assignments, and identity mappings." />
      <nav aria-label="Organization sections" className="flex flex-wrap gap-1 rounded-xl border bg-card p-1 shadow-xs">
        {TABS.map((t) => (
          <Link key={t.path} to={t.path} aria-current={t === current ? 'page' : undefined}
            className={cn('rounded-lg px-3 py-1.5 text-xs font-medium transition-colors focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none',
              t === current ? 'bg-primary text-primary-foreground font-semibold shadow-xs' : 'text-muted-foreground hover:bg-muted hover:text-foreground')}>
            {t.label}
          </Link>
        ))}
      </nav>
      <Tab />
    </div>
  );
}
