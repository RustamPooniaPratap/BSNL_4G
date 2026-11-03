import { useCallback, useEffect, useMemo, useState, type ReactNode } from 'react';
import { AUTH_EVENT, devSignIn as apiDevSignIn, fetchMe, signIn as apiSignIn, signOut as apiSignOut, type AuthEvent } from '../services/api';
import type { AuthUser } from '../types';
import { AuthContext, type AuthContextValue } from './auth';

/** Loads the signed-in user from the session on start, and signs out when the server reports an ended session. */
export function AuthProvider({ children }: { children: ReactNode }) {
  const [status, setStatus] = useState<AuthContextValue['status']>('loading');
  const [user, setUserState] = useState<AuthUser | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  useEffect(() => {
    const controller = new AbortController();
    fetchMe(controller.signal)
      .then(({ user: me }) => { setUserState(me); setStatus('signed_in'); })
      .catch((error) => {
        if (error instanceof DOMException && error.name === 'AbortError') return;
        setStatus('signed_out');
      });
    return () => controller.abort();
  }, []);

  useEffect(() => {
    const onEvent = (event: Event) => {
      const kind = (event as CustomEvent<AuthEvent>).detail;
      if (kind === 'expired') {
        setUserState(null);
        setStatus('signed_out');
        setNotice('Your session has ended. Sign in again to continue.');
      } else if (kind === 'password_change_required') {
        setUserState((u) => (u ? { ...u, must_change_password: true } : u));
      }
    };
    window.addEventListener(AUTH_EVENT, onEvent);
    return () => window.removeEventListener(AUTH_EVENT, onEvent);
  }, []);

  const signIn = useCallback(async (email: string, password: string, remember = false) => {
    const me = await apiSignIn(email, password, remember);
    setUserState(me);
    setStatus('signed_in');
    setNotice(null);
    return me;
  }, []);

  const devSignIn = useCallback(async () => {
    const me = await apiDevSignIn();
    setUserState(me);
    setStatus('signed_in');
    setNotice(null);
    return me;
  }, []);

  const signOut = useCallback(async () => {
    try {
      await apiSignOut();
    } finally {
      setUserState(null);
      setStatus('signed_out');
      setNotice('You have signed out.');
    }
  }, []);

  const setUser = useCallback((me: AuthUser) => setUserState(me), []);
  const value = useMemo(() => ({ status, user, notice, signIn, devSignIn, signOut, setUser }), [status, user, notice, signIn, devSignIn, signOut, setUser]);
  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}
