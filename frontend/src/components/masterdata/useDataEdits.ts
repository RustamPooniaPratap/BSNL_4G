import { useCallback, useMemo, useState } from 'react';
import type { MasterColumn, MasterRow, MasterSaveErrors, MasterSaveRequest } from '../../types/masterData';

/** A stored value as the text an editor starts from (the server converts it back by the column's type). */
export function cellText(value: MasterRow[string] | undefined, kind: MasterColumn['kind']): string {
  if (value === null || value === undefined) return '';
  if (kind === 'bool') return value ? 'Yes' : 'No';
  if (kind === 'date' || kind === 'month') return String(value).slice(0, 10);
  return String(value);
}

export interface NewRow { tmp: number; values: Record<string, string> }

/**
 * Pending Data Panel edits of one dataset, kept in the browser until Save Changes: changed cells per existing row
 * (only cells that differ from the stored value), new rows, and the server's errors of the last refused save.
 */
export function useDataEdits() {
  const [changes, setChanges] = useState<Record<number, Record<string, string>>>({});
  const [versions, setVersions] = useState<Record<number, string>>({});
  const [additions, setAdditions] = useState<NewRow[]>([]);
  const [errors, setErrors] = useState<MasterSaveErrors | null>(null);
  const [nextTmp, setNextTmp] = useState(1);

  const setCell = useCallback((row: MasterRow, column: MasterColumn, value: string) => {
    setVersions((current) => row.updated_at && current[row._id] === undefined ? { ...current, [row._id]: row.updated_at } : current);
    setChanges((current) => {
      const rowChanges = { ...(current[row._id] ?? {}) };
      if (value === cellText(row[column.key], column.kind)) delete rowChanges[column.key];  // back to the stored value
      else rowChanges[column.key] = value;
      const next = { ...current };
      if (Object.keys(rowChanges).length) next[row._id] = rowChanges;
      else delete next[row._id];
      return next;
    });
  }, []);
  const setNewCell = useCallback((tmp: number, key: string, value: string) => {
    setAdditions((rows) => rows.map((r) => (r.tmp === tmp ? { ...r, values: { ...r.values, [key]: value } } : r)));
  }, []);
  const addRow = useCallback(() => {
    setAdditions((rows) => [{ tmp: nextTmp, values: {} }, ...rows]);
    setNextTmp((n) => n + 1);
  }, [nextTmp]);
  /** Drops a new row that was never saved (stored records are never deleted). */
  const removeNew = useCallback((tmp: number) => setAdditions((rows) => rows.filter((r) => r.tmp !== tmp)), []);
  const discard = useCallback(() => {
    setChanges({});
    setVersions({});
    setAdditions([]);
    setErrors(null);
  }, []);

  const cells = useMemo(() => Object.values(changes).reduce((n, r) => n + Object.keys(r).length, 0), [changes]);
  const rows = Object.keys(changes).length;
  const payload = (): MasterSaveRequest => ({
    changes: Object.entries(changes).map(([id, values]) => ({
      id: Number(id), values, ...(versions[Number(id)] ? { updated_at: versions[Number(id)] } : {}),
    })),
    // Oldest first, so the server's indexes match the order the rows were added in.
    additions: [...additions].reverse().map((r) => ({ values: Object.fromEntries(Object.entries(r.values).filter(([, v]) => v !== '')) })),
  });
  /** The server's error index of a new row (additions are sent oldest first). */
  const additionIndex = (tmp: number) => [...additions].reverse().findIndex((r) => r.tmp === tmp);

  return { changes, additions, errors, setErrors, setCell, setNewCell, addRow, removeNew, discard, cells, rows,
    dirty: cells > 0 || additions.length > 0, payload, additionIndex };
}
export type DataEdits = ReturnType<typeof useDataEdits>;
