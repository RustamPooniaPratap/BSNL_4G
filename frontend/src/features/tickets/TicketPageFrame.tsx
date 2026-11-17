import { Link, useLocation } from 'react-router-dom';
import type { ReactNode } from 'react';
import { PageHeading } from '../../context/pageHeader';
import { canOpen, useAuth } from '../../context/auth';

const sections = [
  { path: '/tickets', label: 'Ticket Dashboard' },
  { path: '/tickets/all', label: 'All Tickets' },
  { path: '/tickets/upload', label: 'Upload Excel' },
];

export function TicketPageFrame({ title, subtitle, children }: {
  title: string;
  subtitle: string;
  children: ReactNode;
}) {
  const { user } = useAuth();
  const { pathname } = useLocation();
  const detailSection = /^\/tickets\/\d+$/.test(pathname) ? { path: pathname, label: 'Ticket Details' } : null;
  const visibleSections = [...sections, ...(detailSection ? [detailSection] : [])].filter((section) => canOpen(user, section.path));
  return (
    <div className="space-y-4">
      <PageHeading title={title} subtitle={subtitle} />
      <nav className="flex flex-wrap gap-2 border-b pb-3" aria-label="Ticket Management">
        {visibleSections.map((section) => (
          <Link
            key={section.path}
            to={section.path}
            aria-current={section.path === pathname ? 'page' : undefined}
            className={`rounded-md border px-3 py-1.5 text-sm transition-colors hover:bg-muted hover:text-foreground ${section.path === pathname ? 'bg-muted text-foreground' : 'text-muted-foreground'}`}
          >
            {section.label}
          </Link>
        ))}
      </nav>
      {children}
    </div>
  );
}

export function TicketError({ message }: { message: string }) {
  return (
    <div role="alert" className="rounded-lg border border-destructive/30 bg-destructive/5 px-4 py-3 text-sm text-destructive">
      {message}
    </div>
  );
}
