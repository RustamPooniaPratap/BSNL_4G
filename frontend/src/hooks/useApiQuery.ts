import { useEffect, useState } from 'react';

interface QueryState<T> {
  data: T | null;
  error: Error | null;
  loading: boolean;
}

/**
 * Run `fetcher` whenever `key` changes. The previous request is aborted, so a
 * slow response for an old filter selection can never overwrite a newer one.
 * Pass `null` as the key to skip fetching.
 */
export function useApiQuery<T>(key: string | null, fetcher: (signal: AbortSignal) => Promise<T>): QueryState<T> {
  const [state, setState] = useState<QueryState<T>>({ data: null, error: null, loading: key !== null });

  useEffect(() => {
    if (key === null) return;
    const controller = new AbortController();
    setState((previous) => ({ data: previous.data, error: null, loading: true }));
    fetcher(controller.signal)
      .then((data) => {
        if (!controller.signal.aborted) setState({ data, error: null, loading: false });
      })
      .catch((error: unknown) => {
        if (controller.signal.aborted) return;
        setState({ data: null, error: error instanceof Error ? error : new Error(String(error)), loading: false });
      });
    return () => controller.abort();
    // The fetcher is recreated on every render; `key` captures everything it depends on.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [key]);

  return state;
}
