import { createContext, useContext } from 'react';
import type { ActiveWorkbook } from '../types';

export interface WorkbookContextValue {
  /** The active Master workbook, or null when none has been uploaded. */
  active: ActiveWorkbook | null;
  /** Server message when no workbook is active. */
  message: string | null;
  loading: boolean;
  error: Error | null;
  /**
   * Changes whenever a different workbook becomes active. Every data query includes it
   * in its key, so a new upload refreshes all panels and stale data is never shown.
   */
  version: string;
  refresh: () => void;
  setActive: (active: ActiveWorkbook) => void;
}

export const WorkbookContext = createContext<WorkbookContextValue | null>(null);

export function useWorkbook(): WorkbookContextValue {
  const value = useContext(WorkbookContext);
  if (!value) throw new Error('useWorkbook must be used inside WorkbookProvider');
  return value;
}
