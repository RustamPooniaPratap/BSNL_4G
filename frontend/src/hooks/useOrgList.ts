import { useState } from 'react';
import { useApiQuery } from './useApiQuery';
import { invalidateOrganization } from './useOrganization';

/** A tab's last result, shown above its list. */
export type Notice = { kind: 'ok' | 'error'; text: string } | null;

/** A tab's list and its save/reload cycle: reloads after a change, and tells every catalog-driven selector to reload too. */
export function useOrgList<T>(name: string, fetcher: (signal: AbortSignal) => Promise<T>) {
  const [version, setVersion] = useState(0);
  const query = useApiQuery<T>(`org-${name}|${version}`, fetcher);
  const [notice, setNotice] = useState<Notice>(null);
  const [busy, setBusy] = useState(false);
  /** Run a change; once the server committed it, show ``done`` (or what ``done`` makes of the server's answer) and
   * reload. Returns false when the server refused it: nothing is shown as saved then. */
  const change = async <R,>(action: () => Promise<R>, done: string | ((result: R) => string)) => {
    setBusy(true);
    setNotice(null);
    try {
      const result = await action();
      setNotice({ kind: 'ok', text: typeof done === 'function' ? done(result) : done });
      setVersion((v) => v + 1);
      invalidateOrganization();
      return true;
    } catch (e) {
      const details = (e as { details?: Record<string, unknown> }).details ?? {};
      const fields = Object.values(details).flat().map(String).filter(Boolean);
      setNotice({ kind: 'error', text: fields.length ? fields.join(' ') : (e as Error).message });
      return false;
    } finally {
      setBusy(false);
    }
  };
  return { ...query, notice, setNotice, busy, change };
}
