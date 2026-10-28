import { createContext, useContext } from 'react';
import type { AuthUser, Role } from '../types';

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

/** Pages each role may open. Admin-only pages are refused by the backend as well. */
export const ADMIN_ONLY_PATHS = ['/daily-ingestion', '/teams', '/teams/ci-ie', '/teams/top', '/workbook', '/data/database', '/admin/users', '/rca/summary', '/rca/submissions', '/rca/mappings', '/rca/import'];
/** Admin-only pages a NOC Lead may open as well (their own RCA uploads; the API limits them to their own). */
export const NOC_LEAD_PATHS = ['/rca/import'];

/** A NOC Lead opens what a CI opens, plus uploading RCA data. */
export const canOpen = (role: Role | null | undefined, path: string) =>
  role === 'admin' || ((role === 'ci' || role === 'noc_lead') && !ADMIN_ONLY_PATHS.includes(path)) || (role === 'noc_lead' && NOC_LEAD_PATHS.includes(path));
