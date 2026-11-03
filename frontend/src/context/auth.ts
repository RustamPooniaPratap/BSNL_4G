import { createContext, useContext } from 'react';
import type { AuthUser } from '../types';

/** Who is signed in. The server decides the role; the UI only uses it to choose what to show. */
export interface AuthContextValue {
  status: 'loading' | 'signed_out' | 'signed_in';
  user: AuthUser | null;
  /** Why the user was signed out, e.g. an expired session. */
  notice: string | null;
  /** remember: keep the session for 7 days instead of ending it with the browser. */
  signIn: (username: string, password: string, remember?: boolean) => Promise<AuthUser>;
  /** Development only: sign in through the backend's bypass (refused by the server unless enabled). */
  devSignIn: () => Promise<AuthUser>;
  signOut: () => Promise<void>;
  /** Replace the user after a password change. */
  setUser: (user: AuthUser) => void;
}

export const AuthContext = createContext<AuthContextValue | null>(null);

export function useAuth(): AuthContextValue {
  const value = useContext(AuthContext);
  if (!value) throw new Error('useAuth must be used inside AuthProvider');
  return value;
}

/** Pages that stay with the Admin role (the backend refuses their APIs to everyone else). */
export const ADMIN_ONLY_PATHS = ['/daily-ingestion', '/teams', '/teams/ci-ie', '/teams/top', '/workbook', '/data/database', '/admin/users', '/admin/users/roles', '/admin/users/assignments', '/admin/users/history', '/admin/organization', '/admin/organization/circles', '/admin/organization/mapping', '/admin/organization/access', '/admin/organization/code-mapping', '/admin/organization/history', '/rca/submissions', '/rca/mappings', '/admin/alerts/email', '/admin/alerts/automations', '/admin/alerts/history'];

/**
 * The permission ('module.action', see Users & Roles › Roles & Permissions) each other page needs. A user opens the page
 * when they hold it on at least one project/circle; the API then limits the data to those pairs.
 */
const PAGE_PERMISSIONS: Record<string, string> = {
  '/': 'dashboard.view', '/portfolio': 'dashboard.view', '/thresholds': 'dashboard.view', '/thresholds/buckets': 'dashboard.view',
  '/data-source': 'dashboard.view', '/master-data': 'data_*.view',
  '/data/upload-csv': 'csv_upload.upload', '/data/add-row': 'csv_upload.upload', '/data/new-site': 'csv_upload.upload',
  '/rca': 'rca_register.view', '/rca/import': 'rca_upload.upload', '/rca/summary': 'rca_summary.view',
};
const PREFIXES = ['/master-data', '/rca/summary'];

export function pagePermission(path: string): string | undefined {
  return PAGE_PERMISSIONS[path] ?? PAGE_PERMISSIONS[PREFIXES.find((p) => path.startsWith(`${p}/`)) ?? ''];
}

/** Whether the user holds ``permission`` ('module.action') on at least one project/circle. */
export function hasPermission(user: AuthUser | null | undefined, permission: string): boolean {
  const [module, action] = permission.split('.');
  if (user?.role === 'admin') return true;
  // 'data_*': any Data Panel dataset (each dataset is its own module, data_<dataset>).
  if (module.endsWith('*')) return Object.entries(user?.permissions ?? {}).some(([m, actions]) => m.startsWith(module.slice(0, -1)) && actions.includes(action));
  return !!user?.permissions?.[module]?.includes(action);
}

/** Admin: every page. Others: the pages their permissions allow (never the Admin-only ones). */
export function canOpen(user: AuthUser | null | undefined, path: string): boolean {
  if (!user?.role) return false;
  if (user.role === 'admin') return true;
  if (ADMIN_ONLY_PATHS.includes(path) || path.startsWith('/teams') || path.startsWith('/team-performance')) return false;
  if (path === '/rca/import/consolidated') return !!user.rca_upload?.consolidated;
  const needed = pagePermission(path);
  return needed === undefined || hasPermission(user, needed);
}

/** The first page the user may open (for users without the dashboard, e.g. an upload-only role). */
export function homePath(user: AuthUser | null | undefined): string | null {
  return ['/', '/rca/import', '/data/upload-csv', '/rca', '/master-data', '/rca/summary', '/rca/import/consolidated'].find((p) => canOpen(user, p)) ?? null;
}
