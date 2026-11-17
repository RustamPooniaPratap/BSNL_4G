import { useCallback, useRef, useState } from 'react';
import { ApiError } from '../../services/api';

const nf = new Map<number, Intl.NumberFormat>();
/** Reference ``fmt``: Indian digit grouping, '–' for no value. */
export function fmt(value: number | null | undefined, decimals = 0): string {
  if (value === null || value === undefined || Number.isNaN(value)) return '–';
  if (!nf.has(decimals)) nf.set(decimals, new Intl.NumberFormat('en-IN', { minimumFractionDigits: decimals, maximumFractionDigits: decimals }));
  return nf.get(decimals)!.format(value);
}

export function errorText(cause: unknown, fallback: string): string {
  if (cause instanceof ApiError || cause instanceof Error) return cause.message || fallback;
  return fallback;
}

/** Save a downloaded file through a temporary link. */
export function saveBlob(blob: Blob, filename: string) {
  const url = URL.createObjectURL(blob);
  const link = document.createElement('a');
  link.href = url;
  link.download = filename;
  document.body.appendChild(link);
  link.click();
  link.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1500);
}

/** One async action at a time with its own busy, error and success state (prevents duplicate submissions). */
export function useAction() {
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  const running = useRef(false);
  const run = useCallback(async (key: string, action: () => Promise<string | void>) => {
    if (running.current) return;
    running.current = true;
    setBusy(key);
    setError('');
    setNotice('');
    try {
      const message = await action();
      if (message) setNotice(message);
    } catch (cause) {
      setError(errorText(cause, 'The action could not be completed.'));
    } finally {
      running.current = false;
      setBusy(null);
    }
  }, []);
  return { busy, error, notice, run, setError, setNotice };
}

