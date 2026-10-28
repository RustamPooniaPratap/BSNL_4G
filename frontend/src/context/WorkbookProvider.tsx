import { useCallback, useEffect, useMemo, useState, type ReactNode } from 'react';
import { fetchWorkbookStatus } from '../services/api';
import type { ActiveWorkbook } from '../types';
import { WorkbookContext, type WorkbookContextValue } from './workbook';

interface State {
  active: ActiveWorkbook | null;
  message: string | null;
  loading: boolean;
  error: Error | null;
}

export function WorkbookProvider({ children }: { children: ReactNode }) {
  const [state, setState] = useState<State>({ active: null, message: null, loading: true, error: null });
  const [reloadToken, setReloadToken] = useState(0);

  useEffect(() => {
    const controller = new AbortController();
    fetchWorkbookStatus(controller.signal)
      .then((status) => {
        if (!controller.signal.aborted) {
          setState({ active: status.active, message: status.message ?? null, loading: false, error: null });
        }
      })
      .catch((error: unknown) => {
        if (!controller.signal.aborted) {
          setState({ active: null, message: null, loading: false, error: error instanceof Error ? error : new Error(String(error)) });
        }
      });
    return () => controller.abort();
  }, [reloadToken]);

  const refresh = useCallback(() => {
    setState((s) => ({ ...s, loading: true }));
    setReloadToken((n) => n + 1);
  }, []);
  const setActive = useCallback((active: ActiveWorkbook) => {
    setState({ active, message: null, loading: false, error: null });
  }, []);

  const value = useMemo<WorkbookContextValue>(() => ({
    ...state,
    version: state.active ? `${state.active.workbook}|${state.active.uploaded_at ?? state.active.modified_at}` : 'none',
    refresh,
    setActive,
  }), [state, refresh, setActive]);

  return <WorkbookContext.Provider value={value}>{children}</WorkbookContext.Provider>;
}
