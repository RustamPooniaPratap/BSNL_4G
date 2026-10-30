import type { ReactNode } from 'react';
import { Link, Navigate, useLocation } from 'react-router-dom';
import { ShieldAlert } from 'lucide-react';
import { buttonVariants } from '@/components/ui/button';
import { Card } from '@/components/ui/card';
import { Skeleton } from '@/components/ui/skeleton';
import { canOpen, useAuth } from '../../context/auth';

/**
 * Pages need a signed-in user; a temporary password must be replaced first.
 * This only decides what to render: the API refuses the same requests on its own.
 */
export function RequireAuth({ children, allowPasswordChange = false }: { children: ReactNode; allowPasswordChange?: boolean }) {
  const { status, user } = useAuth();
  const location = useLocation();
  if (status === 'loading') return <div className="p-6" aria-busy="true"><Skeleton className="h-96 w-full" aria-label="Checking your session" /></div>;
  if (status === 'signed_out' || !user) return <Navigate to="/login" replace state={{ from: `${location.pathname}${location.search}` }} />;
  if (user.must_change_password && !allowPasswordChange) return <Navigate to="/change-password" replace />;
  return <>{children}</>;
}

/** Admin-only pages: other roles see an explanation instead (direct URLs included). */
export function RequireAdmin({ children }: { children: ReactNode }) {
  const { user } = useAuth();
  const location = useLocation();
  return canOpen(user?.role, location.pathname) && user?.role === 'admin' ? <>{children}</> : <Unauthorized />;
}

/** Pages open to more than one role (e.g. RCA upload for Admins and NOC Leads): the role's page list decides. */
export function RequirePage({ children }: { children: ReactNode }) {
  const { user } = useAuth();
  const location = useLocation();
  return canOpen(user?.role, location.pathname) ? <>{children}</> : <Unauthorized />;
}

/** Upload Consolidated RCA: Admins and members of the RCA Consolidated Uploaders group (the server checks every upload). */
export function RequireRcaConsolidated({ children }: { children: ReactNode }) {
  const { user } = useAuth();
  return user?.rca_upload?.consolidated ? <>{children}</> : <Unauthorized />;
}

export function Unauthorized() {
  const { user } = useAuth();
  return (
    <Card role="alert" className="mx-auto mt-10 max-w-xl items-center gap-3 px-8 py-10 text-center">
      <ShieldAlert className="size-8 text-muted-foreground" aria-hidden="true" />
      <h1 className="text-lg font-semibold">You do not have access to this page</h1>
      <p className="text-sm text-muted-foreground">
        This page is not available to your role{user ? `; you are signed in as ${user.username} (${user.role_label})` : ''}.
        Ask an Admin if you need it.
      </p>
      <Link to="/portfolio" className={buttonVariants({ size: 'sm' })}>Go to Site Portfolio</Link>
    </Card>
  );
}
