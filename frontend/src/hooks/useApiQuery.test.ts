import { renderHook, waitFor } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { useApiQuery } from './useApiQuery';

function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((r) => { resolve = r; });
  return { promise, resolve };
}

describe('useApiQuery', () => {
  it('never lets a stale response overwrite a newer one', async () => {
    const slow = deferred<string>();
    const fast = deferred<string>();
    const signals: AbortSignal[] = [];
    const { result, rerender } = renderHook(
      ({ key }) => useApiQuery(key, (signal) => {
        signals.push(signal);
        return key === 'old' ? slow.promise : fast.promise;
      }),
      { initialProps: { key: 'old' } },
    );

    rerender({ key: 'new' });
    expect(signals[0].aborted).toBe(true);

    fast.resolve('new data');
    await waitFor(() => expect(result.current.data).toBe('new data'));
    slow.resolve('old data');
    await new Promise((r) => setTimeout(r, 0));
    expect(result.current.data).toBe('new data');
  });

  it('skips fetching when the key is null', () => {
    const { result } = renderHook(() => useApiQuery(null, () => Promise.resolve('x')));
    expect(result.current).toEqual({ data: null, error: null, loading: false });
  });

  it('exposes errors', async () => {
    const { result } = renderHook(() => useApiQuery('k', () => Promise.reject(new Error('boom'))));
    await waitFor(() => expect(result.current.error?.message).toBe('boom'));
    expect(result.current.loading).toBe(false);
  });
});
